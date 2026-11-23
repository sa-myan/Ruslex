/** Deliberately minimal client-side navigation for Ruslex's small route list. */
import { writable } from 'svelte/store';

export const currentPath = writable(window.location.pathname);

export function navigate(path: string): void {
  window.history.pushState({}, '', path);
  currentPath.set(window.location.pathname);
  window.scrollTo({ top: 0, behavior: 'auto' });
}

window.addEventListener('popstate', () => {
  currentPath.set(window.location.pathname);
});
