# Offline AI extraction / enrichment / audit

The supplied v3 AI workflow was split by responsibility rather than embedded in Django views. This code is used for **offline processing against a snapshot**; the public Django site does not run model inference itself.

| Module | Purpose |
|---|---|
| `processing/storage.py` | Inspect input database, create consistent snapshot/workspace |
| `processing/prompts.py` | Prompt instructions for lexemes and page/occurrence extraction |
| `processing/provider.py` | Invoke configured OpenCode model provider process |
| `processing/validation.py` | Validate proposed objects, source attestation and response shape |
| `processing/workflow.py` | Resumable processing, reports, candidate construction |
| `processing/audit.py` | Read-only quality reports about dictionary and relationships |
| `processing/cli.py` | Small single CLI entry point |

From the project root on a machine with Python 3.11+ and the configured OpenCode CLI:

```bash
python3 -m processing.cli inventory --db /srv/data/ruslex/lexicon/lexicon.db
python3 -m processing.cli prepare --db /srv/data/ruslex/lexicon/lexicon.db --workspace /srv/data/ruslex/processing/run1
python3 -m processing.cli run --workspace /srv/data/ruslex/processing/run1 --stage lexemes --model YOUR_PROVIDER_MODEL --dry-run
python3 -m processing.cli report --workspace /srv/data/ruslex/processing/run1
```

To execute a real model call, remove `--dry-run` and configure OpenCode separately. A second run can process the `pages` stage. When finished, `python3 -m processing.cli build --workspace ... --out /path/to/CANDIDATE.db` produces a separate candidate; **it does not replace the installed dictionary**. See `--help` for controls such as batch size, max batches, timeout and verification model.

Offline success has been checked for inventory, prepare, report and dry-run. The external provider was not called in this environment, so **real OpenCode extraction and candidate promotion must be checked on your machine**. The pipeline expects OCR pages already present in the supplied v3 database; it does not magically transcribe PDFs.
