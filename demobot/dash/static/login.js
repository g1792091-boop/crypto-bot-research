// The login form posts to /login by itself (it works without this file). This only: the skin, the page to come back
// to (?next=, same-origin paths only, plus the hash the browser kept) and the error line.
(function () {
  try {
    var v = JSON.parse(localStorage.getItem("dl-skin") || "null");
    document.documentElement.dataset.skin = v === "classic" ? "classic" : "ai";
  } catch (e) { /* storage blocked: the default skin */ }
  document.addEventListener("DOMContentLoaded", function () {
    var q = new URLSearchParams(location.search);
    var raw = q.get("next") || "/";
    if (location.hash && raw.indexOf("#") < 0) raw += location.hash;
    var ok = /^\/(?![\/\\])[^\\\u0000-\u001f\u007f]*$/.test(raw) && !/^\/(login|api\/)/.test(raw);
    document.getElementById("next").value = ok ? raw : "/";
    var e = q.get("e");
    var err = document.getElementById("err");
    if (e === "wait") err.textContent = "시도가 너무 많습니다. 15분 뒤에 다시 하세요.";
    else if (e) err.textContent = "비밀번호가 틀렸습니다.";
    document.getElementById("pw").focus();
  });
})();
