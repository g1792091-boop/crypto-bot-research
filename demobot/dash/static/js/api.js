// The one way to read the server: GET with the session cookie; a 401 goes to the login page (and comes back here).
export class ApiError extends Error {
  constructor(status, detail) { super(`HTTP ${status}`); this.status = status; this.detail = detail; }
}

export function toLogin() {
  const back = "/" + (location.hash || "");
  location.href = "/login?next=" + encodeURIComponent(back);
}

export async function getJSON(path, signal) {
  let res;
  try {
    res = await fetch(path, {credentials: "same-origin", cache: "no-store", headers: {Accept: "application/json"}, signal});
  } catch (e) {
    if (e && e.name === "AbortError") throw e;
    throw new ApiError(0, "network");
  }
  if (res.status === 401) { toLogin(); throw new ApiError(401, "login"); }
  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json()).detail; } catch (e) { /* not json */ }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

/** A snapshot answer the engine has not written yet. */
export const isMissing = (d) => !d || d.missing === true;
