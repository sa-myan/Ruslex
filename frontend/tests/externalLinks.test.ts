import { describe, expect, it } from 'vitest';
import { dictionaryLinks } from '../src/lib/externalLinks';

describe('external dictionary links', () => {
  it('contains the same four built-in dictionaries', () => {
    expect(dictionaryLinks('читать').map((link) => link.label)).toEqual([
      'Gramota',
      'OpenRussian',
      'Multitran',
      'Wiktionary',
    ]);
  });

  it('URL-encodes the Russian lemma', () => {
    const links = dictionaryLinks('а также');
    for (const link of links) {
      expect(link.url).toContain(encodeURIComponent('а также'));
    }
  });
});
