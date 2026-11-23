import { describe, expect, it } from 'vitest';
import { effectiveReviewStatus } from '../src/lib/searchFilters';

describe('dictionary visibility', () => {
  it('never requests hidden words outside review mode', () => {
    expect(effectiveReviewStatus(false, 'hidden')).toBe('visible');
    expect(effectiveReviewStatus(false, 'all')).toBe('visible');
    expect(effectiveReviewStatus(false, 'followup')).toBe('visible');
  });

  it('allows review filters only in review mode', () => {
    expect(effectiveReviewStatus(true, 'hidden')).toBe('hidden');
    expect(effectiveReviewStatus(true, 'all')).toBe('all');
  });
});
