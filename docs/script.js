// Share the homepage's theme preference; downloads also work without JavaScript.
const root = document.documentElement;
const toggle = document.querySelector('.theme-toggle');
function setTheme(theme) {
  root.dataset.theme = theme;
  toggle.setAttribute('aria-pressed', String(theme === 'dark'));
  toggle.textContent = theme === 'dark' ? '☀' : '☾';
}
try {
  if (localStorage.getItem('runxi-theme') === 'dark') setTheme('dark');
} catch { /* Storage may be disabled; the toggle still works. */ }
toggle.hidden = false;
toggle.addEventListener('click', () => {
  setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark');
  try { localStorage.setItem('runxi-theme', root.dataset.theme); }
  catch { /* Keep the selection for this page even when storage is disabled. */ }
});
