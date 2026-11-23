import { describe, expect, it } from 'vitest';
import { compile } from 'svelte/compiler';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const sourceDirectory = fileURLToPath(new URL('../src/', import.meta.url));

function componentsIn(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((item) => {
    const path = join(directory, item.name);
    if (item.isDirectory()) return componentsIn(path);
    return item.name.endsWith('.svelte') ? [path] : [];
  });
}

describe('Svelte 5 component compatibility', () => {
  for (const file of componentsIn(sourceDirectory)) {
    const label = relative(sourceDirectory, file);

    it(`${label} compiles in runes mode`, () => {
      const source = readFileSync(file, 'utf8');

      // Catch future accidental reintroduction of legacy component syntax.
      expect(source).not.toMatch(/\bexport\s+let\b/);
      expect(source).not.toMatch(/^\s*\$:/m);
      expect(source).not.toMatch(/\bon:(?:click|input|change|submit|keydown|keyup|blur|focus)\b/);

      expect(() => compile(source, { filename: file, generate: 'client' })).not.toThrow();
    });
  }
});
