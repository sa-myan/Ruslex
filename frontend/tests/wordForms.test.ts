import { describe, expect, it } from 'vitest';
import { organizeWordForms } from '../src/lib/wordForms';
import type { WordForm } from '../src/lib/types';

const f = (form: string, grammemes: string, stressed?: string): WordForm => ({
  form, grammemes, source: 'pymorphy3', stressed,
});
describe('complete Russian morphology tables', () => {
  it('shows cases without losing duplicate grammatical analyses', () => {
    const o = organizeWordForms([
      f('дом', 'NOUN,nomn,sing'),
      f('дома', 'NOUN,gent,sing'),
      f('дому', 'NOUN,datv,sing'),
      f('дому', 'NOUN,datv,sing'),
      f('дому', 'NOUN,loct,sing'),
      f('домы', 'NOUN,nomn,plur'),
    ], 'NOUN');
    expect(o.tables[0].title).toBe('Declension');
    expect(o.tables[0].rows.find(row => row.label === 'Dative')?.cells[0]).toEqual(['дому']);
    expect(o.uniqueCount).toBe(5);
    expect(o.spellingCount).toBe(4);
  });

  it('shows verb forms, participles and gerunds as tables, not a hidden list', () => {
    const o = organizeWordForms([
      f('читать', 'INFN,impf,tran'),
      f('читаю', 'VERB,1per,pres,sing,impf', 'чита́ю'),
      f('читаем', 'VERB,1per,pres,plur,impf'),
      f('читала', 'VERB,femn,past,sing,impf'),
      f('читай', 'VERB,impr,2per,sing,impf'),
      f('читающий', 'PRTF,actv,pres,masc,nomn,sing'),
      f('читающая', 'PRTF,actv,pres,femn,nomn,sing'),
      f('читавший', 'PRTF,actv,past,masc,nomn,sing'),
      f('читан', 'PRTS,pssv,past,masc,sing'),
      f('читая', 'GRND,impf,pres'),
    ], 'VERB');
    expect(o.tables.map(t => t.title)).toEqual([
      'Infinitive', 'Present', 'Past tense', 'Imperative',
      'Present active participles', 'Past active participles',
      'Past passive short participles', 'Gerunds',
    ]);
    expect(o.tables[1].rows[0].cells).toEqual([['чита́ю'], ['читаем']]);
    expect(o.tables.find(t => t.title === 'Gerunds')?.rows[0].cells).toEqual([['читая']]);
    expect(o.accentedCount).toBe(1);
  });

  it('shows full and short adjective paradigms', () => {
    const o = organizeWordForms([
      f('новый','ADJF,masc,nomn,sing'),
      f('новая','ADJF,femn,nomn,sing'),
      f('новое','ADJF,neut,nomn,sing'),
      f('новые','ADJF,nomn,plur'),
      f('нов','ADJS,masc,sing'),
    ], 'ADJF');
    expect(o.tables.map(t=>t.title)).toEqual([
      'Full adjective forms', 'Short adjective forms',
    ]);
    expect(o.tables[0].rows[0].cells).toEqual([
      ['новый'], ['новая'], ['новое'], ['новые'],
    ]);
  });

  it('keeps unsupported grammemes in a visible additional table', () => {
    const o = organizeWordForms([f('как', 'ADVB'), f('как', 'CONJ')], 'ADVB');
    expect(o.tables).toHaveLength(1);
    expect(o.tables[0].title).toBe('Additional inflections');
    expect(o.tables[0].rows).toHaveLength(2);
    expect(o.spellingCount).toBe(1);
  });
});
