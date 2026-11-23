import { writable } from 'svelte/store';
import type { User } from './types';

export const user = writable<User|null>(null);
export const editMode = writable(false);
export const reviewMode = writable(false);
export const currentPath = writable(window.location.pathname);

export function navigate(path:string) {
  window.history.pushState({}, '', path);
  currentPath.set(path);
  window.scrollTo({top:0,behavior:'auto'});
}
window.addEventListener('popstate', () => currentPath.set(window.location.pathname));

function csrf():string {
  const cookie = document.cookie.split('; ').find(item => item.startsWith('csrftoken='));
  return cookie ? decodeURIComponent(cookie.split('=').slice(1).join('=')) : '';
}

export async function request<T>(url:string, options:RequestInit = {}):Promise<T> {
  const method = options.method || 'GET';
  const headers = new Headers(options.headers || {});
  if (!['GET','HEAD'].includes(method.toUpperCase())) {
    headers.set('X-CSRFToken', csrf());
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(url, { ...options, headers, credentials:'same-origin' });
  const contentType = response.headers.get('content-type') || '';
  const result = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof result === 'object' && result?.detail ? result.detail : `HTTP ${response.status}`;
    throw new Error(String(message));
  }
  return result as T;
}

export const mutate = <T>(url:string, method:'POST'|'PUT'|'PATCH'|'DELETE', body?:unknown) =>
  request<T>(url, {method, ...(body===undefined ? {} : {body: JSON.stringify(body)})});

export async function refreshUser():Promise<User> {
  const data = await request<User>('/api/auth/me');
  user.set(data);
  if (!data.can_edit) editMode.set(false);
  if (!data.can_review) reviewMode.set(false);
  return data;
}
