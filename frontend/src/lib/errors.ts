/** Return a useful message without assuming that thrown values are Error objects. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return typeof error === 'string' ? error : 'An unexpected error occurred.';
}

/** An aborted request is not an application error. */
export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}
