"""Fail fast if the mounted dictionary is missing or incompatible."""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import connections

REQUIRED = {
 "books":{"id","title"}, "pages":{"id","book_id","pdf_page","printed_page","markdown"},
 "lexemes":{"id","lemma","pos","human_status","notes","entry_type","aspect","animacy"},
 "senses":{"id","lexeme_id","meaning","active","description"},
 "examples":{"id","sense_id","russian","english","active"},
 "patterns":{"id","sense_id","pattern","active"},
 "lexeme_pages":{"lexeme_id","page_id","surface","context","count"},
 "sense_tags":{"sense_id","tag_id"}, "tags":{"id","category","name"},
 "lexeme_relations":{"id","source_lexeme_id","target_lexeme_id","source_sense_id","target_sense_id"},
 "expression_components":{"id","expression_id","word_id","position"},
 "external_links":{"id","lexeme_id","label","url"},
 "reviews":{"id","status"}, "surface_pages":{"page_id","surface"},
}

class Command(BaseCommand):
    help="Validate the existing lexicon schema without migrating or altering it"

    def handle(self,*args,**kwargs):
        if not settings.LEXICON_DB.is_file():
            raise CommandError(f"Missing lexicon database: {settings.LEXICON_DB}. Refusing to create an empty one")
        with connections["lexicon"].cursor() as cur:
            for name,fields in REQUIRED.items():
                cur.execute(f'PRAGMA table_info("{name}")')
                found={r[1] for r in cur.fetchall()}
                if missing:=fields-found:raise CommandError(f"{name}: missing {sorted(missing)}")
            cur.execute('PRAGMA integrity_check')
            if cur.fetchone()[0]!='ok':raise CommandError("Lexicon SQLite integrity check failed")
            cur.execute('PRAGMA foreign_key_check')
            if cur.fetchall():raise CommandError("Lexicon foreign key violations detected")
            cur.execute('SELECT count(*) FROM lexemes')
            count=cur.fetchone()[0]
        self.stdout.write(self.style.SUCCESS(f"Verified existing lexicon ({count:,} entries)"))
