const STORAGE_KEY = 'vpa-deleted-session-ids';

export function loadDeletedSessionIds(): Record<string, true> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return {};
    return Object.fromEntries(parsed.map((id) => [String(id), true as const]));
  } catch {
    return {};
  }
}

export function saveDeletedSessionIds(ids: Record<string, true>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.keys(ids)));
  } catch {
    // Ignore quota / private-mode errors.
  }
}
