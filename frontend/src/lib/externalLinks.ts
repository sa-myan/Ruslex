/** Standard dictionary sites are generated from the lemma, not stored in SQLite. */
export interface DictionaryLink {
  label: string;
  url: string;
}

export function dictionaryLinks(lemma: string): DictionaryLink[] {
  const encodedLemma = encodeURIComponent(lemma);
  return [
    { label: 'Gramota', url: `https://gramota.ru/poisk?mode=slovari&query=${encodedLemma}` },
    { label: 'OpenRussian', url: `https://en.openrussian.org/?search=${encodedLemma}` },
    { label: 'Multitran', url: `https://www.multitran.com/m.exe?l1=2&l2=1&s=${encodedLemma}` },
    { label: 'Wiktionary', url: `https://ru.wiktionary.org/wiki/${encodedLemma}` },
  ];
}
