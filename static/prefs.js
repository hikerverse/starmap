// Browser persistence: one versioned localStorage entry; failures (private mode, quota, disabled storage) are ignored
const KEY = 'starexplorer:prefs:v1';

function storage() {
  try {
    const s = window.localStorage;
    const probe = `${KEY}:probe`;
    s.setItem(probe, '1');
    s.removeItem(probe);
    return s;
  } catch {
    return null;
  }
}
const store = storage();

export const storageAvailable = store !== null;

export function loadPrefs() {
  try {
    const value = JSON.parse(store?.getItem(KEY) ?? 'null');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

let timer = null;
let pending = null;
let disabled = false;

export function savePrefs(getState, delay = 400) {
  if (!store || disabled) return;
  pending = getState;
  clearTimeout(timer);
  timer = setTimeout(flushPrefs, delay);
}

export function flushPrefs() {
  clearTimeout(timer);
  timer = null;
  if (!pending || disabled) return;
  const getState = pending;
  pending = null;
  try {
    store.setItem(KEY, JSON.stringify(getState()));
  } catch (err) {
    console.warn('Could not save settings:', err);
  }
}

// Removes every StarExplorer key and stops further saves until the page reloads
export function clearPrefs() {
  disabled = true;
  clearTimeout(timer);
  pending = null;
  if (!store) return;
  for (let i = store.length - 1; i >= 0; i--) {
    const key = store.key(i);
    if (key?.startsWith('starexplorer:')) store.removeItem(key);
  }
}

window.addEventListener('pagehide', flushPrefs);
