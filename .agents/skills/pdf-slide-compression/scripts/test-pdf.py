#!/usr/bin/env python3
"""Regression tests. Uses generated PDFs and a disposable repo, never docs/."""
import importlib.util
import os
from pathlib import Path
import pty
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import pikepdf
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
spec = importlib.util.spec_from_file_location('compress_images', HERE / 'compress-images.py')
compression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compression)


def fixture(path):
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(720, 405))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
        Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica, Encoding=pikepdf.Name.WinAnsiEncoding))
    noise = Image.effect_noise((800, 600), 60).convert('RGB')
    image = pdf.make_stream(zlib.compress(noise.tobytes()))
    image.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
        Width=800, Height=600, BitsPerComponent=8, ColorSpace=pikepdf.Name.DeviceRGB,
        Filter=pikepdf.Name.FlateDecode))
    mask = pdf.make_stream(zlib.compress(bytes([200]) * 800 * 600))
    mask.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
        Width=800, Height=600, BitsPerComponent=8, ColorSpace=pikepdf.Name.DeviceGray,
        Filter=pikepdf.Name.FlateDecode))
    image.SMask = mask
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font), XObject=pikepdf.Dictionary(Im=image))
    page.Contents = pdf.make_stream(b'q 180 0 0 135 40 150 cm /Im Do Q\n'
        b'BT /F1 12 Tf 420 20 Td (Citation: Al\341n et al., 2026) Tj ET')
    page.Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name.Link, Rect=[420, 10, 680, 30],
        A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI='https://example.com')))])
    pdf.save(path)


def run(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, **kwargs)


class CompressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'Deck.pdf'
        self.out = Path(self.tmp.name) / 'Compressed.pdf'
        fixture(self.src)

    def test_compression_preserves_text_fonts_content_links_and_masks(self):
        compression.compress(self.src, self.out)
        self.assertLess(self.out.stat().st_size, self.src.stat().st_size)
        with pikepdf.open(self.src) as a, pikepdf.open(self.out) as b:
            self.assertEqual(a.pages[0].Contents.read_bytes(), b.pages[0].Contents.read_bytes())
            self.assertEqual(str(a.pages[0].Annots), str(b.pages[0].Annots))
            self.assertEqual(str(a.pages[0].Resources.Font), str(b.pages[0].Resources.Font))
            ia, ib = a.pages[0].Resources.XObject.Im, b.pages[0].Resources.XObject.Im
            self.assertEqual(ia.SMask.read_bytes(), ib.SMask.read_bytes())
            self.assertLess(ib.Width, ia.Width)

    def test_shared_form_uses_largest_placement(self):
        with pikepdf.open(self.src) as pdf:
            page = pdf.pages[0]
            form = pdf.make_stream(b'/Im Do')
            form.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Form,
                BBox=[0, 0, 1, 1], Resources=page.Resources))
            page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm=form))
            page.Contents = pdf.make_stream(b'q 10 0 0 10 0 0 cm /Fm Do Q q 300 0 0 200 0 0 cm /Fm Do Q')
            sizes = {}
            compression.walk(page, compression.IDENTITY, sizes)
            self.assertEqual(sizes[form.Resources.XObject.Im.objgen], (300, 200))

    def test_invisible_citation_is_rejected(self):
        with pikepdf.open(self.src) as pdf:
            page = pdf.pages[0]
            page.Contents = pdf.make_stream(page.Contents.read_bytes().replace(b'BT ', b'BT 3 Tr '))
            pdf.save(self.out)
        self.assertTrue(any('visible ink' in f for f in compression.verify(self.src, self.out)))

    def test_failed_render_cannot_pass_verification(self):
        real_command = compression.command
        def broken(tool, *args):
            if tool == 'pdftoppm':
                raise subprocess.CalledProcessError(1, [tool])
            return real_command(tool, *args)
        with patch.object(compression, 'command', side_effect=broken):
            with self.assertRaises(subprocess.CalledProcessError):
                compression.verify(self.src, self.src)

    def test_bad_page_geometry_cannot_pass_verification(self):
        with patch.object(compression, 'command', return_value='<html/>'):
            with self.assertRaises(ValueError):
                compression.word_boxes(self.src, 1)
        with pikepdf.open(self.src) as pdf:
            pdf.pages[0].MediaBox = [0, 0, 800, 405]
            pdf.save(self.out)
        self.assertTrue(any('dimensions' in f for f in compression.verify(self.src, self.out)))

    def test_spell_check_is_honest_when_unavailable(self):
        spec = importlib.util.spec_from_file_location('lint_slides', HERE / 'lint-slides.py')
        lint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint)
        with patch.object(lint.shutil, 'which', return_value=None):
            checker, name = lint.spell_checker()
        self.assertIsNone(checker)
        self.assertEqual(name, 'unavailable')

    def test_failed_verification_keeps_existing_output(self):
        self.out.write_bytes(b'previous reviewed output')
        with patch.object(compression, 'verify', return_value=['test failure']):
            with self.assertRaises(ValueError):
                compression.compress(self.src, self.out)
        self.assertEqual(self.out.read_bytes(), b'previous reviewed output')
        with self.assertRaises(ValueError):
            compression.compress(self.src, self.src)

    def test_unusual_decode_is_left_untouched(self):
        with pikepdf.open(self.src) as pdf:
            pdf.pages[0].Resources.XObject.Im.Decode = [1, 0, 1, 0, 1, 0]
            pdf.save(self.out)
        protected = Path(self.tmp.name) / 'protected.pdf'
        compression.compress(self.out, protected)
        with pikepdf.open(self.out) as a, pikepdf.open(protected) as b:
            self.assertEqual(a.pages[0].Resources.XObject.Im.read_bytes(), b.pages[0].Resources.XObject.Im.read_bytes())


class WorkflowTests(unittest.TestCase):
    def test_stage_review_approval_and_hook_in_disposable_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / '.agents/skills/pdf-slide-compression/scripts'
            scripts.mkdir(parents=True)
            for name in ('pdf.sh', 'compress-images.py', 'lint-slides.py'):
                shutil.copy2(HERE / name, scripts / name)
            (root / '.githooks').mkdir()
            shutil.copy2(REPO / '.githooks/pre-commit', root / '.githooks/pre-commit')
            run('git', 'init', '-q', str(root))
            (root / 'talks-original').mkdir()
            # Prevent the test from opening browser windows.
            tools = root / 'tools'
            tools.mkdir()
            opener = tools / 'open'
            opener.write_text('#!/bin/sh\nexit 0\n')
            opener.chmod(0o755)
            env = dict(os.environ, PATH=f'{tools}:{Path(sys.executable).parent}:{os.environ["PATH"]}')
            shell = '/bin/bash' if Path('/bin/bash').exists() else 'bash'
            def workflow(*args, ok=True):
                p = subprocess.run([shell, str(scripts / 'pdf.sh'), *args], cwd=root,
                                   env=env, capture_output=True, text=True)
                if ok:
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                else:
                    self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
                return p
            workflow('stage', '--all')  # no unmatched *.pdf glob
            source = root / 'talks-original/Deck.pdf'
            fixture(source)
            workflow('stage')
            html = (root / 'preview/compare.html').read_text()
            self.assertNotIn("$'", html)
            if shutil.which('node'):
                js = root / 'compare.js'
                js.write_text(re.search(r'<script>(.*?)</script>', html, re.S)[1])
                run('node', '--check', str(js))
            workflow('approve', ok=False)  # no TTY
            self.assertFalse((root / 'docs/Deck.pdf').exists())
            original = source.read_bytes()
            source.write_bytes(original + b'\n')
            self.assertIn('source changed', workflow('approve', ok=False).stderr)
            source.write_bytes(original)
            output = root / 'preview/Deck-compressed.pdf'
            reviewed = output.read_bytes()
            output.write_bytes(reviewed + b'\n')
            self.assertIn('preview changed', workflow('approve', ok=False).stderr)
            output.write_bytes(reviewed)

            # Simulated human ONLY inside this disposable repo.
            master, slave = pty.openpty()
            try:
                proc = subprocess.Popen([shell, str(scripts / 'pdf.sh'), 'approve'],
                    cwd=root, env=env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                os.close(slave)
                os.write(master, b'approved\n')
                stdout, _ = proc.communicate(timeout=30)
                self.assertEqual(proc.returncode, 0, stdout.decode())
            finally:
                os.close(master)
            self.assertEqual((root / 'docs/Deck.pdf').read_bytes(), reviewed)
            run('git', 'add', 'docs/Deck.pdf', cwd=root)
            hook = root / '.githooks/pre-commit'
            run(shell, str(hook), cwd=root)
            self.assertNotEqual(subprocess.run([shell, str(hook)], cwd=root,
                env=dict(env, MAX_PDF_BYTES='1'), capture_output=True).returncode, 0)
            run('git', '-c', 'user.name=PDF Tests', '-c', 'user.email=pdf-tests@example.invalid',
                'commit', '-qm', 'test fixture', cwd=root)
            (root / 'docs/Deck.pdf').rename(root / 'docs/Renamed.pdf')
            run('git', 'add', '-A', 'docs', cwd=root)
            self.assertNotEqual(subprocess.run([shell, str(hook)], cwd=root,
                capture_output=True).returncode, 0)  # approval is path + hash specific

            # A failed new stage invalidates any older review batch.
            fake = tools / 'pdftoppm'
            fake.write_text('#!/bin/sh\nexit 1\n')
            fake.chmod(0o755)
            workflow('stage', '--all', ok=False)
            self.assertFalse((root / 'preview/.stage-manifest').exists())
            workflow('approve', ok=False)


if __name__ == '__main__':
    unittest.main()
