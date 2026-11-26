import { describe, expect, it } from 'vitest';
import { organizeWordForms } from '../src/lib/wordForms';
import type { WordForm } from '../src/lib/types';

const f = (form: string, grammemes: string): WordForm => ({
  form, grammemes, source: 'pymorphy3',
});

describe('organizeWordForms', () => {
  it('groups noun cases and keeps alternate spellings without duplication', () => {
    const organized = organizeWordForms([
      f('дом', 'NOUN,nomn,sing'),
      f('дома', 'NOUN,gent,sing'),
      f('дому', 'NOUN,datv,sing'),
      f('дому', 'NOUN,datv,sing'),
      f('дому', 'NOUN,loct,sing'),
      f('домы', 'NOUN,nomn,plur'),
    ], 'NOUN');
    expect(organized.tables[0].title).toBe('Declension');
    expect(organized.tables[0].rows.find((row) => row.label === 'Dative')?.cells[0])
      .toEqual(['дому']);
    expect(organized.tables[0].rows.find((row) => row.label === 'Second locative')).toBeUndefined();
    expect(organized.unique).toHaveLength(5);
    expect(organized.spellingCount).toBe(4);
    expect(organized.other).toHaveLength(0);
  });

  it('handles verb conjugation, past tense, imperative and keeps participles for review', () => {
    const organized = organizeWordForms([
      f('читать', 'INFN,impf,tran'),
      f('читаю', 'VERB,1per,pres,sing,impf'),
      f('читаем', 'VERB,1per,pres,plur,impf'),
      f('читала', 'VERB,femn,past,sing,impf'),
      f('читай', 'VERB,impr,2per,sing,impf'),
      f('читая', 'GRND,impf,pres'),
    ], 'VERB');
    expect(organized.tables.map((table) => table.title)).toEqual([
      'Infinitive', 'Present', 'Past', 'Imperative',
    ]);
    expect(organized.tables[1].rows[0].cells).toEqual([['читаю'], ['читаем']]);
    expect(organized.other.map((item) => item.form)).toEqual(['читая']);
  });

  it('presents adjective genders and short forms', () => {
    const organized = organizeWordForms([
      f('новый', 'ADJF,masc,nomn,sing'),
      f('новая', 'ADJF,femn,nomn,sing'),
      f('новое', 'ADJF,neut,nomn,sing'),
      f('новые', 'ADJF,nomn,plur'),
      f('нов', 'ADJS,masc,sing'),
      f('нова', 'ADJS,femn,sing'),
    ], 'ADJF');
    expect(organized.tables.map((table) => table.title)).toEqual(['Full forms', 'Short forms']);
    expect(organized.tables[0].rows[0].cells).toEqual([
      ['новый'], ['новая'], ['новое'], ['новые'],
    ]);
  });

  it('never discards unsupported grammatical analyses', () => {
    const input = [f('как', 'ADVB'), f('как', 'CONJ')];
    const organized = organizeWordForms(input, 'ADVB');
    expect(organized.tables).toHaveLength(0);
    expect(organized.other).toEqual(input);
    expect(organized.unique).toHaveLength(2);
    expect(organized.spellingCount).toBe(1);
  });
});
