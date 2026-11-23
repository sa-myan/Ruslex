import { describe, expect, it } from 'vitest';
import { errorMessage, isAbortError } from '../src/lib/errors';

describe('error utilities', () => {
  it('handles errors and non-errors', () => {
    expect(errorMessage(new Error('Cannot save'))).toBe('Cannot save');
    expect(errorMessage('Unexpected')).toBe('Unexpected');
    expect(errorMessage(null)).toBe('An unexpected error occurred.');
  });

  it('recognizes canceled requests', () => {
    expect(isAbortError(new DOMException('Canceled', 'AbortError'))).toBe(true);
    expect(isAbortError(new Error('Network error'))).toBe(false);
  });
});
