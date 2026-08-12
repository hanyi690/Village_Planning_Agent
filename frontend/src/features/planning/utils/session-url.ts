/** Helpers for syncing planning session id with the browser URL. */

export function getSessionIdFromUrl(): string | null {
  if (typeof window === 'undefined') return null;
  return new URL(window.location.href).searchParams.get('sessionId');
}

export function setSessionIdInUrl(sessionId: string): void {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.searchParams.set('sessionId', sessionId);
  window.history.replaceState({}, '', url.toString());
}

export function clearSessionIdFromUrl(): void {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.searchParams.delete('sessionId');
  window.history.replaceState({}, '', url.toString());
}
