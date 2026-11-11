// Runs in <head>, before the body paints, so a dark reader sees no light flash.
(function () {
  var KEY = "theme";

  function stored() {
    try {
      return localStorage.getItem(KEY);
    } catch (e) {
      return null;  // site data blocked: fall back to the system setting
    }
  }

  function preferred() {
    var saved = stored();
    if (saved === "dark" || saved === "light") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch (e) {
      // nothing to remember with; the page still renders
    }
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.textContent = theme === "dark" ? "☀" : "☽";
      btn.setAttribute("aria-label", theme === "dark" ? "Lichte weergave" : "Donkere weergave");
    }
  }

  apply(preferred());

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    apply(document.documentElement.getAttribute("data-theme") || "light");
    btn.addEventListener("click", function () {
      apply(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
  });
})();
