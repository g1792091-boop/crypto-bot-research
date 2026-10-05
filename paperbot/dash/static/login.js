// the login form (moved out of login.html so the Content-Security-Policy can forbid inline scripts)
// after logging in, back to the page that sent here (?next=): a same-origin path only ('/...', never '//host',
// a backslash or a control character), else the dashboard's front page
function nextPath() {
  const raw = new URLSearchParams(location.search).get("next") || "";
  return /^\/(?![\/\\])[^\\\u0000-\u001f\u007f]*$/.test(raw) && !/^\/(login|api\/)/.test(raw) ? raw : "/";
}
document.getElementById("f").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const r = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({password: document.getElementById("pw").value})});
  if (r.ok) { location.href = nextPath(); return; }
  const j = await r.json().catch(() => ({}));
  document.getElementById("err").textContent = r.status === 429 ? "시도가 너무 많습니다. 15분 뒤에 다시 하세요." : "비밀번호가 틀렸습니다.";
});
