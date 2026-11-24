# OpenRussian reference tool (VPS only)

This is an optional, **read-only** reference tool for Russian headword stress,
е/ё spellings, English glosses, verb partners, and inflection forms.
It uses your separately compiled OpenRussian SQLite dump; it does **not**
replace the live Ruslex dictionary or its manually edited senses.

The original OpenRussian `rus.db` was not included in the development inputs,
so the first real lookup on your VPS is an important compatibility test.

## Setup

Store the old database outside the Git checkout. By default:

| VPS path | Container path | Access |
|---|---|---|
| `/srv/data/ruslex/reference/openrussian.db` | `/reference/openrussian.db` | Read-only |
| `/srv/data/ruslex/lexicon/lexicon.db` | `/live/lexicon.db` | Read-only |
| `/srv/data/ruslex/processing/reference_reports/` | `/work/reference_reports/` | Writable audit output |

For the usual DATA_ROOT:

~~~sh
cd /srv/apps/ruslex
mkdir -p /srv/data/ruslex/reference
cp /path/to/your/old/rus.db /srv/data/ruslex/reference/openrussian.db
chmod 640 /srv/data/ruslex/reference/openrussian.db
./process.sh build
./process.sh reference info
~~~

The file must be readable by the non-root container user specified by
`PUID:PGID` in your `.env`. Adjust the ownership of the file, if needed.
Never put it in Git, in a Docker image, or inside the public web container.
The standard installation command now creates the `reference` folder.

## Commands

~~~sh
./process.sh reference info
./process.sh reference lookup 'читать'
./process.sh reference lookup 'читать' --forms
./process.sh reference lookup 'замок'
./process.sh reference lookup 'елка'
./process.sh reference audit
~~~

`info` checks the source table layout and returns counts and a SHA-256
fingerprint. `lookup` shows each matching OpenRussian record separately,
including its ID, stress, type, English translations, and optional forms.
Search can match е and ё variants but never silently rewrites a lexeme.

`audit` compares the read-only OpenRussian reference against Ruslex
headwords. It writes a dated CSV and JSON report under
`/srv/data/ruslex/processing/reference_reports/`.

### Audit categories

| Status | Meaning |
|---|---|
| `candidate` | One plausible stressed reading; still **unverified** |
| `yo_review` | A possible е/ё spelling correction; inspect meaning |
| `ambiguous` | Multiple readings, stress or ё variants |
| `source_warning` | Missing/conflicting accent marks or corrupt source text |
| `not_found` | Word missing from this OpenRussian snapshot |

The audit includes reference IDs, type labels and reasons. It keeps different
homographs separate. If OpenRussian types are unknown, POS filtering
deliberately abstains instead of deleting candidates.

## What this does not do

- It makes **no AI calls**.
- It does **not** insert stress into Ruslex's database or website.
- It does **not** change lemmas, senses, review status or book occurrences.
- It does **not** assign homograph readings from context.
- It does **not** require stress-processing every inflected form; forms are
  optional lookup reference data.

Stress is converted from the old OpenRussian trailing-apostrophe convention
to Unicode combining acute U+0301. Ё is preserved as an actual letter.
Ambiguous or malformed source records require review.

For actual stress storage and promotion, we will need a separate versioned
schema migration, verification UI and provenance safeguards; these CSVs
are **suggestions**, not a database migration.

## Licensing

OpenRussian data is published under **CC BY-SA 4.0**. Review attribution
and share-alike obligations before publishing or redistributing its data
or derived records. This Git change contains no third-party dictionary data.

## Testing

~~~sh
PYTHONPATH=backend:. python3 -m unittest discover -s tests -p test_openrussian.py -v
python3 -m compileall -q processing
~~~

See `docs/BOOK_PROCESSING.md` for the separate OCR/AI pipeline.
