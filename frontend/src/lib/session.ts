/** Authentication and editor/reviewer mode live independently of HTTP transport. */
import { writable } from 'svelte/store';
import type { User } from './types';
import { request } from './http';

export const user = writable<User | null>(null);
export const editMode = writable(false);
export const reviewMode = writable(false);

export async function refreshUser(): Promise<User> {
  const currentUser = await request<User>('/api/auth/me');
  user.set(currentUser);

  // Never retain privileged UI state after logout or permission revocation.
  if (!currentUser.can_edit) editMode.set(false);
  if (!currentUser.can_review) reviewMode.set(false);

  return currentUser;
}
