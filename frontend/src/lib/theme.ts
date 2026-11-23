import { writable } from 'svelte/store';

export type Theme = 'light' | 'dark';
const STORAGE_KEY = 'ruslex-theme';

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // Private browsing may restrict local storage.
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export const theme = writable<Theme>(initialTheme());

theme.subscribe((value) => {
  document.documentElement.setAttribute('data-theme', value);
});

export function toggleTheme(): void {
  theme.update((current) => {
    const next: Theme = current === 'dark' ? 'light' : 'dark';
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The theme still changes for the current page.
    }
    return next;
  });
}
