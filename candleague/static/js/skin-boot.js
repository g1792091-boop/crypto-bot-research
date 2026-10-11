// Runs before the first paint (a plain script in <head>, no inline script under the CSP): the viewer's skin, text size
// menu position and 숫자 움직임 (설정), so the page never flashes the other ones (copied from the demo lab's js/skin-boot.js; the keys
// start "cl-" here). The switches themselves are in prefs.js.
(function () {
  var root = document.documentElement;
  function read(k) {
    try { return JSON.parse(localStorage.getItem("cl-" + k) || "null"); } catch (e) { return null; }
  }
  var skin = read("skin"), text = read("text"), nav = read("nav"), motion = read("motion");
  root.dataset.skin = skin === "classic" ? "classic" : "ai";
  if (motion === "less") root.dataset.motion = "less";
  root.dataset.text = text === "lg" || text === "xl" ? text : "md";
  root.dataset.nav = nav === "left" ? "left" : "top";
})();
