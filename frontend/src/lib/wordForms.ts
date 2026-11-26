/** Group saved pymorphy3 analyses into complete readable paradigms. */
import type { WordForm } from './types';

export interface FormRow { label: string; cells: string[][] }
export interface FormTable { title: string; columns: string[]; rows: FormRow[] }
export interface OrganizedForms {
  tables: FormTable[];
  spellingCount: number;
  accentedCount: number;
  uniqueCount: number;
}

type Tags = Set<string>;
type Predicate = (tags: Tags) => boolean;
type RowDefinition = [label: string, predicates: Predicate[]];
const has = (...values: string[]): Predicate => tags => values.every(value => tags.has(value));
const hasNo = (...values: string[]): Predicate => tags => values.every(value => !tags.has(value));
const both = (...predicates: Predicate[]): Predicate => tags => predicates.every(fn => fn(tags));
const CASES: [string, string][] = [
  ['Nominative', 'nomn'], ['Genitive', 'gent'], ['Dative', 'datv'],
  ['Accusative', 'accs'], ['Instrumental', 'ablt'], ['Prepositional', 'loct'],
  ['Second genitive', 'gen2'], ['Second locative', 'loc2'],
  ['Second accusative', 'acc2'], ['Vocative', 'voct'],
];
const GENDERS: [string, string][] = [
  ['Masculine', 'masc'], ['Feminine', 'femn'], ['Neuter', 'neut'],
];

export function organizeWordForms(forms: WordForm[], pos: string): OrganizedForms {
  const unique = Array.from(new Map(forms.map(row =>
    [row.form + '\u0000' + row.grammemes, row],
  )).values());
  const parsed = unique.map((form, id) => ({
    id, form,
    tags: new Set(form.grammemes.split(',').map(tag => tag.trim())),
  }));
  const assigned = new Set<number>();
  const tables: FormTable[] = [];

  function cell(predicate: Predicate): string[] {
    const rows = parsed.filter(row => predicate(row.tags));
    for (const row of rows) assigned.add(row.id);
    return Array.from(new Set(rows.map(row => row.form.stressed || row.form.form)))
      .sort((a, b) => a.localeCompare(b, 'ru'));
  }
  function add(title: string, columns: string[], definitions: RowDefinition[]): void {
    const rows = definitions.map(([label, predicates]) => ({
      label, cells: predicates.map(cell),
    })).filter(row => row.cells.some(values => values.length));
    if (rows.length) tables.push({ title, columns, rows });
  }
  function declension(title: string, prefix: Predicate, adjective = false): void {
    const columns = adjective ? ['Masculine', 'Feminine', 'Neuter', 'Plural'] : ['Singular', 'Plural'];
    add(title, columns, CASES.map(([label, tag]) => [
      label,
      adjective
        ? [...GENDERS.map(([, gender]) => both(prefix, has(tag, 'sing', gender))),
            both(prefix, has(tag, 'plur'))]
        : [both(prefix, has(tag, 'sing')), both(prefix, has(tag, 'plur'))],
    ]));
  }
  function short(title: string, prefix: Predicate): void {
    add(title, ['Form'], [
      ...GENDERS.map(([label, gender]): RowDefinition =>
        [label, [both(prefix, has('sing', gender))]]),
      ['Plural', [both(prefix, has('plur'))]],
    ]);
  }
  function participles(): void {
    for (const [tense, tenseLabel] of [['pres', 'Present'], ['past', 'Past'], ['futr', 'Future']]) {
      for (const [voice, voiceLabel] of [['actv', 'active'], ['pssv', 'passive']]) {
        declension(`${tenseLabel} ${voiceLabel} participles`, has('PRTF', tense, voice), true);
        short(`${tenseLabel} ${voiceLabel} short participles`, has('PRTS', tense, voice));
      }
    }
    // Not all analyzers attach both voice and tense to participles.
    const remainingFull: Predicate = tags => tags.has('PRTF') &&
      ![...assigned].some(id => parsed[id].tags === tags);
    declension('Additional full participles', remainingFull, true);
    const remainingShort: Predicate = tags => tags.has('PRTS') &&
      ![...assigned].some(id => parsed[id].tags === tags);
    short('Additional short participles', remainingShort);
  }

  if (pos === 'NOUN' || pos === 'NPRO' || pos === 'NUMR') {
    declension('Declension', has(pos));
  }
  if (pos === 'ADJF' || pos === 'ADJS' || pos === 'COMP') {
    // OpenCorpora marks inflected superlatives with Supr; comparatives use
    // COMP (and optionally Cmp2). Neither belongs in the positive paradigm.
    const positive = hasNo('Supr', 'COMP', 'Cmp2');
    declension('Positive degree · full forms', both(has('ADJF'), positive), true);
    short('Positive degree · short forms', both(has('ADJS'), positive));
    add('Comparative degree', ['Form'], [
      ['Standard', [both(has('COMP'), hasNo('Cmp2'))]],
      ['Variant with по-', [has('Cmp2')]],
    ]);
    declension('Superlative degree · full forms', has('ADJF', 'Supr'), true);
    short('Superlative degree · short forms', has('ADJS', 'Supr'));
  }
  if (pos === 'VERB' || pos === 'INFN') {
    add('Infinitive', ['Form'], [['Infinitive', [has('INFN')]]]);
    for (const [title, tense] of [['Present', 'pres'], ['Future', 'futr']]) {
      add(title, ['Singular', 'Plural'], [
        ['1st person', [has('VERB', tense, '1per', 'sing'), has('VERB', tense, '1per', 'plur')]],
        ['2nd person', [has('VERB', tense, '2per', 'sing'), has('VERB', tense, '2per', 'plur')]],
        ['3rd person', [has('VERB', tense, '3per', 'sing'), has('VERB', tense, '3per', 'plur')]],
      ]);
    }
    short('Past tense', has('VERB', 'past'));
    add('Imperative', ['Singular', 'Plural'], [
      ['2nd person', [has('VERB', 'impr', 'sing'), has('VERB', 'impr', 'plur')]],
    ]);
    participles();
    add('Gerunds', ['Form'], [
      ['Present', [has('GRND', 'pres')]],
      ['Past', [has('GRND', 'past')]],
      ['Other', [both(has('GRND'), hasNo('pres', 'past'))]],
    ]);
  }
  if (pos === 'PRTF' || pos === 'PRTS') {
    participles();
  }

  // Never silently drop a generated form, even if a future pymorphy version
  // introduces new grammatical tags. Keep it in a visible table, not a raw dump.
  const remaining = parsed.filter(row => !assigned.has(row.id));
  if (remaining.length) {
    tables.push({
      title: 'Additional inflections',
      columns: ['Form'],
      rows: remaining.map(({ form, tags }) => ({
        label: Array.from(tags).filter(tag =>
          !['NOUN', 'VERB', 'ADJF', 'ADJS', 'PRTF', 'PRTS', 'GRND', 'INFN'].includes(tag),
        ).join(' · ') || 'Additional',
        cells: [[form.stressed || form.form]],
      })),
    });
  }

  return {
    tables,
    spellingCount: new Set(unique.map(row => row.form)).size,
    accentedCount: unique.filter(row => row.stressed && row.stressed !== row.form).length,
    uniqueCount: unique.length,
  };
}
