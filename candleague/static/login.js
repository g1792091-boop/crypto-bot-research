// The login form posts to /login by itself (it works without this file). This only: the viewer's skin and the error line.
(function () {
  try {
    var v = JSON.parse(localStorage.getItem("cl-skin") || "null");
    document.documentElement.dataset.skin = v === "classic" ? "classic" : "ai";
  } catch (e) { /* storage blocked: the default skin */ }
  document.addEventListener("DOMContentLoaded", function () {
    if (new URLSearchParams(location.search).get("bad")) document.getElementById("err").textContent = "비밀번호가 틀렸습니다.";
  });
})();
