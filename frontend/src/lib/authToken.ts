// Token storage for this prototype only. localStorage is readable by any
// script on the page, so this is vulnerable to XSS in a way an httpOnly
// cookie wouldn't be -- a real deployment should issue the JWT as an
// httpOnly, Secure, SameSite cookie instead and drop this module entirely.
// Kept deliberately this simple (no refresh tokens, no silent renewal)
// because the tradeoff is already documented, not hidden.

const STORAGE_KEY = "sentinelbank_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // private window / blocked storage -- the session just won't persist
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
