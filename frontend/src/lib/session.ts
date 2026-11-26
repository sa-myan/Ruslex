/** Authentication and a single permission-aware work mode live outside HTTP transport. */
import { derived, writable } from 'svelte/store';
import type { User } from './types';
import { request } from './http';

export const user = writable<User | null>(null);
// One visible mode, with each operation still gated by its own permission.
export const workMode = writable(false);
export const editMode = derived([workMode, user],
  ([$mode, $user]) => $mode && Boolean($user?.can_edit));
export const reviewMode = derived([workMode, user],
  ([$mode, $user]) => $mode && Boolean($user?.can_review));

export async function refreshUser(): Promise<User> {
  const currentUser = await request<User>('/api/auth/me');
  user.set(currentUser);

  // Never retain privileged UI state after logout or permission revocation.
  if (!currentUser.can_edit && !currentUser.can_review) workMode.set(false);

  return currentUser;
}
