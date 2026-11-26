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
      'Positive degree · full forms', 'Positive degree · short forms',
    ]);
    expect(o.tables[0].rows[0].cells).toEqual([
      ['новый'], ['новая'], ['новое'], ['новые'],
    ]);
  });

  it('keeps superlatives and comparatives out of positive adjective forms', () => {
    const o = organizeWordForms([
      f('красивый', 'ADJF,masc,nomn,sing'),
      f('красивая', 'ADJF,femn,nomn,sing'),
      f('красив', 'ADJS,masc,sing'),
      f('красивее', 'COMP'),
      f('покрасивее', 'COMP,Cmp2'),
      f('красивейший', 'ADJF,Supr,masc,nomn,sing'),
      f('красивейшая', 'ADJF,Supr,femn,nomn,sing'),
      f('красивейших', 'ADJF,Supr,plur,gent'),
    ], 'ADJF');
    expect(o.tables.map(t => t.title)).toEqual([
      'Positive degree · full forms',
      'Positive degree · short forms',
      'Comparative degree',
      'Superlative degree · full forms',
    ]);
    expect(o.tables[0].rows[0].cells).toEqual([
      ['красивый'], ['красивая'], [], [],
    ]);
    expect(o.tables[1].rows[0].cells).toEqual([['красив']]);
    expect(o.tables[2].rows.map(r => r.cells[0])).toEqual([
      ['красивее'], ['покрасивее'],
    ]);
    expect(o.tables[3].rows[0].cells).toEqual([
      ['красивейший'], ['красивейшая'], [], [],
    ]);
    expect(o.tables[3].rows.find(r => r.label === 'Genitive')?.cells[3])
      .toEqual(['красивейших']);
    expect(o.tables.some(t => t.title === 'Additional inflections')).toBe(false);
    expect(o.uniqueCount).toBe(8);
  });

  it('keeps a standalone comparative entry in its own table', () => {
    const o = organizeWordForms([
      f('лучше', 'COMP'),
      f('получше', 'COMP,Cmp2'),
    ], 'COMP');
    expect(o.tables.map(t => t.title)).toEqual(['Comparative degree']);
    expect(o.tables[0].rows.map(r => r.cells[0])).toEqual([
      ['лучше'], ['получше'],
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
