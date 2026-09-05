const TOKEN_KEY = "foriflow.access_token";
const USER_KEY = "foriflow.username";
const ROLE_KEY = "foriflow.role";

export function getToken() {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUsername() {
  return window.localStorage.getItem(USER_KEY) ?? "";
}

export function getStoredRole() {
  return window.localStorage.getItem(ROLE_KEY) ?? "";
}

export function storeSession({ access_token, username, role }) {
  window.localStorage.setItem(TOKEN_KEY, access_token);
  window.localStorage.setItem(USER_KEY, username ?? "");
  window.localStorage.setItem(ROLE_KEY, role ?? "");
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.localStorage.removeItem(ROLE_KEY);
}

export function isLoggedIn() {
  return Boolean(getToken());
}
