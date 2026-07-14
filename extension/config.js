// Companion runtime defaults. This committed copy holds the DEV values —
// build.mjs overwrites this file inside the production package with the real
// app/API origins. Loaded via importScripts() in background.js and a <script>
// tag in popup.html, so it must stay a plain script defining a global.
var NR_DEFAULTS = {
  apiUrl: "http://localhost:8000",
  appUrl: "http://localhost:5173",
};
