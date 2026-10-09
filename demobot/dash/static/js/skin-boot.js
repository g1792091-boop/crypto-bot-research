// Runs before the first paint (a plain script in <head>, no inline script under the CSP): the viewer's skin, text size
// and menu position, so the page never flashes the other ones. The switches themselves are in prefs.js.
(function () {
  var root = document.documentElement;
  function read(k) {
    try { return JSON.parse(localStorage.getItem("dl-" + k) || "null"); } catch (e) { return null; }
  }
  var skin = read("skin"), text = read("text"), nav = read("nav");
  root.dataset.skin = skin === "classic" ? "classic" : "ai";
  root.dataset.text = text === "lg" || text === "xl" ? text : "md";
  root.dataset.nav = nav === "left" ? "left" : "top";
})();
