// The login form posts to /login by itself (it works without this file). This only shows the error line.
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    if (new URLSearchParams(location.search).get("bad")) document.getElementById("err").textContent = "비밀번호가 틀렸습니다.";
  });
})();
