PRAGMA foreign_keys=ON;

CREATE TABLE books (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, edition TEXT NOT NULL DEFAULT '',
  UNIQUE(title, edition)
);

CREATE TABLE examples (
  id INTEGER PRIMARY KEY,sense_id INTEGER NOT NULL REFERENCES senses(id),
  russian TEXT NOT NULL,english TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE expression_components (
        id INTEGER PRIMARY KEY,
        expression_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
        word_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
        position INTEGER NOT NULL CHECK(position > 0),
        surface TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        UNIQUE(expression_id,position),
        CHECK(expression_id != word_id)
    );

CREATE TABLE external_links (
        id INTEGER PRIMARY KEY,
        lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        url TEXT NOT NULL,
        UNIQUE(lexeme_id, url)
    );

CREATE TABLE lexeme_pages (
  lexeme_id INTEGER NOT NULL REFERENCES lexemes(id),
  page_id INTEGER NOT NULL REFERENCES pages(id),
  surface TEXT NOT NULL, context TEXT NOT NULL, count INTEGER NOT NULL,
  PRIMARY KEY(lexeme_id,page_id,surface)
);

CREATE TABLE lexeme_relations (
        id INTEGER PRIMARY KEY,
        source_lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
        target_lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
        relation_type TEXT NOT NULL CHECK(relation_type IN
            ('aspect_pair','synonym','antonym','derivation','related')),
        source_sense_id INTEGER REFERENCES senses(id) ON DELETE CASCADE,
        target_sense_id INTEGER REFERENCES senses(id) ON DELETE CASCADE,
        notes TEXT NOT NULL DEFAULT '',
        CHECK(source_lexeme_id != target_lexeme_id)
    );

CREATE TABLE lexemes (
  id INTEGER PRIMARY KEY, lemma TEXT NOT NULL, pos TEXT NOT NULL,
  human_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK(human_status IN ('unreviewed','kept','hidden','followup')),
  notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, entry_type TEXT NOT NULL DEFAULT 'word'
                CHECK(entry_type IN ('word','expression')), aspect TEXT DEFAULT NULL
                CHECK(aspect IN ('imperfective','perfective','biaspectual')), animacy TEXT DEFAULT NULL
                CHECK(animacy IS NULL OR (pos='NOUN' AND
                    animacy IN ('animate','inanimate','variable'))),
  UNIQUE(lemma,pos)
);

CREATE TABLE pages (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
  pdf_page INTEGER NOT NULL, printed_page INTEGER NOT NULL,
  markdown TEXT NOT NULL, source TEXT NOT NULL,
  UNIQUE(book_id,pdf_page)
);

CREATE TABLE patterns (
        id INTEGER PRIMARY KEY,
        sense_id INTEGER NOT NULL REFERENCES senses(id),
        pattern TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );

CREATE TABLE reviews (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
  surface TEXT NOT NULL, analyses_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','admitted','excluded','needs_review')),
  entries_json TEXT NOT NULL DEFAULT '[]', reason TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(book_id,surface)
);

CREATE TABLE sense_tags (
        sense_id INTEGER NOT NULL REFERENCES senses(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY(sense_id,tag_id)
    );

CREATE TABLE senses (
  id INTEGER PRIMARY KEY,lexeme_id INTEGER NOT NULL REFERENCES lexemes(id),
  meaning TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1
, description TEXT NOT NULL DEFAULT '');

CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE surface_pages (
  page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  surface TEXT NOT NULL, count INTEGER NOT NULL, context TEXT NOT NULL,
  PRIMARY KEY(page_id,surface)
);

CREATE TABLE "tags" (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL CHECK(category IN ('semantic','grammatical','usage')),
                UNIQUE(category,name));
