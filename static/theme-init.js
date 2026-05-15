/* Kjøres i <head> før CSS for å unngå blink ved lagret mørk modus. */
(function () {
  try {
    var t = localStorage.getItem("leadmap-theme");
    if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* private mode */ }
})();
