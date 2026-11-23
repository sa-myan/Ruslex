# Dictionary and AI pipeline

The authoritative, up-to-date VPS workflow is
[BOOK_PROCESSING.md](BOOK_PROCESSING.md). It covers OCR import, morphology,
AI review, checkpointed enrichment, audit, additive promotion and recovery.

Important: legacy replacement-style database assembly has been retired from
the public CLI. Do **not** use old `processing.workflow.build` instructions or
copy a generated database over `/srv/data/ruslex/lexicon/lexicon.db`.
