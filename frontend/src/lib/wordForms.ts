/** Organize stored pymorphy3 analyses without inventing morphology or stress. */
import type { WordForm } from './types';

export interface FormRow {
  label: string;
  cells: string[][];
}
export interface FormTable {
  title: string;
  columns: string[];
  rows: FormRow[];
}
export interface OrganizedForms {
  unique: WordForm[];
  tables: FormTable[];
  other: WordForm[];
  spellingCount: number;
}

type Predicate = (tags: Set<string>) => boolean;
type RowDefinition = [label: string, predicates: Predicate[]];

const CASES: [string, string][] = [
  ['Nominative', 'nomn'],
  ['Genitive', 'gent'],
  ['Dative', 'datv'],
  ['Accusative', 'accs'],
  ['Instrumental', 'ablt'],
  ['Prepositional', 'loct'],
  ['Second genitive', 'gen2'],
  ['Second locative', 'loc2'],
  ['Second accusative', 'acc2'],
  ['Vocative', 'voct'],
];

const has = (...grammemes: string[]): Predicate =>
  (tags) => grammemes.every((grammeme) => tags.has(grammeme));

export function organizeWordForms(forms: WordForm[], pos: string): OrganizedForms {
  // Different analyses of the same surface are kept distinct in the audit view.
  const unique = Array.from(
    new Map(forms.map((form) => [form.form + '\u0000' + form.grammemes, form])).values(),
  );
  const parsed = unique.map((form, index) => ({
    form,
    index,
    tags: new Set(form.grammemes.split(',').map((part) => part.trim())),
  }));
  const assigned = new Set<number>();
  const tables: FormTable[] = [];

  function cell(predicate: Predicate): string[] {
    const matches = parsed.filter((item) => predicate(item.tags));
    for (const match of matches) assigned.add(match.index);
    return Array.from(new Set(matches.map((match) => match.form.form))).sort((a, b) =>
      a.localeCompare(b, 'ru'),
    );
  }

  function addTable(title: string, columns: string[], definitions: RowDefinition[]): void {
    const rows = definitions
      .map(([label, predicates]) => ({ label, cells: predicates.map(cell) }))
      .filter((row) => row.cells.some((values) => values.length > 0));
    if (rows.length) tables.push({ title, columns, rows });
  }

  if (pos === 'NOUN' || pos === 'NPRO' || pos === 'NUMR') {
    addTable('Declension', ['Singular', 'Plural'], CASES.map(([label, code]) => [
      label,
      [has(code, 'sing'), has(code, 'plur')],
    ]));
  } else if (pos === 'ADJF' || pos === 'PRTF') {
    const part = pos === 'ADJF' ? 'ADJF' : 'PRTF';
    addTable('Full forms', ['Masculine', 'Feminine', 'Neuter', 'Plural'],
      CASES.map(([label, code]) => [
        label,
        [
          has(part, code, 'sing', 'masc'),
          has(part, code, 'sing', 'femn'),
          has(part, code, 'sing', 'neut'),
          has(part, code, 'plur'),
        ],
      ]));
    const shortPart = pos === 'ADJF' ? 'ADJS' : 'PRTS';
    addTable('Short forms', ['Form'], [
      ['Masculine', [has(shortPart, 'sing', 'masc')]],
      ['Feminine', [has(shortPart, 'sing', 'femn')]],
      ['Neuter', [has(shortPart, 'sing', 'neut')]],
      ['Plural', [has(shortPart, 'plur')]],
    ]);
  } else if (pos === 'VERB' || pos === 'INFN') {
    addTable('Infinitive', ['Form'], [['Infinitive', [has('INFN')]]]);
    for (const [title, tense] of [['Present', 'pres'], ['Future', 'futr']]) {
      addTable(title, ['Singular', 'Plural'], [
        ['1st person', [has('VERB', tense, '1per', 'sing'), has('VERB', tense, '1per', 'plur')]],
        ['2nd person', [has('VERB', tense, '2per', 'sing'), has('VERB', tense, '2per', 'plur')]],
        ['3rd person', [has('VERB', tense, '3per', 'sing'), has('VERB', tense, '3per', 'plur')]],
      ]);
    }
    addTable('Past', ['Form'], [
      ['Masculine', [has('VERB', 'past', 'sing', 'masc')]],
      ['Feminine', [has('VERB', 'past', 'sing', 'femn')]],
      ['Neuter', [has('VERB', 'past', 'sing', 'neut')]],
      ['Plural', [has('VERB', 'past', 'plur')]],
    ]);
    addTable('Imperative', ['Singular', 'Plural'], [
      ['2nd person', [has('VERB', 'impr', 'sing'), has('VERB', 'impr', 'plur')]],
    ]);
  }

  return {
    unique,
    tables,
    other: unique.filter((_, index) => !assigned.has(index)),
    spellingCount: new Set(unique.map((row) => row.form)).size,
  };
}
