// Runs before the first paint (a plain script in <head>, no inline script under the CSP): the viewer's skin, so the
// page never flashes the other one. The switch itself is in app.js.
(function () {
  try {
    var v = JSON.parse(localStorage.getItem("dl-skin") || "null");
    document.documentElement.dataset.skin = v === "classic" ? "classic" : "ai";
  } catch (e) {
    document.documentElement.dataset.skin = "ai";
  }
})();
