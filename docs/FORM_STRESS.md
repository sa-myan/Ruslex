# Morphology tables and source-backed inflected stress

The generated paradigms include every stored morphological analysis, grouped
into cases, genders, tenses, persons, participles and gerunds. The website no
longer exposes the raw grammeme dumps. Unrecognized grammatical combinations
appear in a visible **Additional inflections** table rather than disappearing.

## Inflected stress is optional and source-backed

OpenRussian's `words_forms` table can provide accented spellings for forms
that already exist in `lexeme_forms`. Unlike pronunciation for a dictionary
headword, this process does not attempt to infer stress from a paradigm or
morphological rule.

- Match an OpenRussian headword to a Ruslex lexeme, not merely a form string.
- Require matching recognizable POS and either a unique compatible reference
  headword or a previously verified OpenRussian reference ID.
- Skip ambiguous stress, conflicting ё, malformed reference values and missing
  stress on multisyllabic source forms.
- Keep the OpenRussian database offline in the processing service; **do not**
  mount or query it from the public web container.
- Store the matched accented spelling in a dedicated
  `lexeme_form_stress` table with form ID, reference headword ID and SHA-256
  fingerprint. No generated form or headword record is overwritten.
- API includes `word_forms[].stressed` only when the optional table is present;
  missing readings remain ordinary unstressed spellings.
- The UI indicates source-backed inflection accents but does not present them
  as textbook attestations.

## VPS trial (works before merging this PR)

Stop editing your dictionary while changing its schema. The site may remain
running because the new web code checks whether the optional table is present.
Run the following in the **current feature-branch checkout** after deploying
the latest feature branch:

```sh
cd /srv/apps/ruslex
./process.sh build
./process.sh forms stress-plan        # no changes
./process.sh forms stress-rehearse    # creates only a disposable copy
```

Inspect the candidate counts, source availability and skipped reasons.
If sensible:

```sh
./manage.sh backup
./process.sh forms stress-init --confirm
./process.sh forms stress-plan
./process.sh forms stress-apply --confirm
./process.sh forms stress-plan
./manage.sh health
./manage.sh check
```

`stress-init` extends the schema; `stress-apply` performs a backed-up,
idempotent transaction. Both require explicit confirmation. A second apply
should insert **zero** rows. The procedure never calls an LLM.

If the optional `words_forms` reference table is absent, no stress is
promoted. If some forms are absent/ambiguous in that source, they remain
unstressed. Reporting candidate counts before applying is deliberate.

A later manual correction of a headword's lemma or POS makes the old generated
form row ineligible for display, including its associated form-stress record.

## License

OpenRussian's underlying data are licensed CC BY-SA 4.0. When displaying
derived inflection stress, preserve attribution and review share-alike
requirements before redistributing derived data. No OpenRussian data are
included in the Git repository.
