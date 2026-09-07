(function () {
  try {
    var stored = localStorage.getItem('nexusreach-theme');
    var dark = stored === 'dark' ||
      (stored !== 'light' && window.matchMedia &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (dark) document.documentElement.classList.add('dark');
  } catch (_) {
    // The app and public landing page both have safe light-mode defaults.
  }
})();
