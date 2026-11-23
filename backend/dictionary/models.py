"""Mapping of the supplied v3 SQLite schema. Django NEVER migrates these tables.

Only tables with a real integer primary key are mapped here; composite-key
occurrence and tagging tables are accessed through narrowly scoped queries.
"""
from django.db import models

class LegacyModel(models.Model):
    class Meta:
        abstract = True
        managed = False


class Book(LegacyModel):
    title = models.TextField()
    edition = models.TextField()
    class Meta:
        managed = False
        db_table = "books"


class Page(LegacyModel):
    book = models.ForeignKey(Book, on_delete=models.DO_NOTHING, db_column="book_id")
    pdf_page = models.IntegerField()
    printed_page = models.IntegerField()
    markdown = models.TextField()
    source = models.TextField()
    class Meta:
        managed = False
        db_table = "pages"


class Lexeme(LegacyModel):
    lemma = models.TextField()
    pos = models.TextField()
    human_status = models.TextField(default="unreviewed")
    notes = models.TextField(default="")
    created_at = models.TextField()
    entry_type = models.TextField(default="word")
    aspect = models.TextField(null=True)
    animacy = models.TextField(null=True)
    class Meta:
        managed = False
        db_table = "lexemes"


class Sense(LegacyModel):
    lexeme = models.ForeignKey(Lexeme, on_delete=models.DO_NOTHING, db_column="lexeme_id", related_name="senses")
    meaning = models.TextField()
    active = models.IntegerField(default=1)
    description = models.TextField(default="")
    class Meta:
        managed = False
        db_table = "senses"


class Example(LegacyModel):
    sense = models.ForeignKey(Sense, on_delete=models.DO_NOTHING, db_column="sense_id", related_name="examples")
    russian = models.TextField()
    english = models.TextField(default="")
    active = models.IntegerField(default=1)
    class Meta:
        managed = False
        db_table = "examples"


class Pattern(LegacyModel):
    sense = models.ForeignKey(Sense, on_delete=models.DO_NOTHING, db_column="sense_id", related_name="patterns")
    pattern = models.TextField()
    active = models.IntegerField(default=1)
    class Meta:
        managed = False
        db_table = "patterns"


class Tag(LegacyModel):
    name = models.TextField()
    category = models.TextField()
    class Meta:
        managed = False
        db_table = "tags"


class Relation(LegacyModel):
    source_lexeme = models.ForeignKey(Lexeme, on_delete=models.DO_NOTHING, db_column="source_lexeme_id", related_name="outgoing_relations")
    target_lexeme = models.ForeignKey(Lexeme, on_delete=models.DO_NOTHING, db_column="target_lexeme_id", related_name="incoming_relations")
    relation_type = models.TextField()
    source_sense = models.ForeignKey(Sense, on_delete=models.DO_NOTHING, db_column="source_sense_id", null=True, related_name="+")
    target_sense = models.ForeignKey(Sense, on_delete=models.DO_NOTHING, db_column="target_sense_id", null=True, related_name="+")
    notes = models.TextField(default="")
    class Meta:
        managed = False
        db_table = "lexeme_relations"


class ExpressionComponent(LegacyModel):
    expression = models.ForeignKey(Lexeme, on_delete=models.DO_NOTHING, db_column="expression_id", related_name="constituents")
    word = models.ForeignKey(Lexeme, on_delete=models.DO_NOTHING, db_column="word_id", related_name="used_in_expressions")
    position = models.IntegerField()
    surface = models.TextField(default="")
    notes = models.TextField(default="")
    class Meta:
        managed = False
        db_table = "expression_components"


class ExternalLink(LegacyModel):
    lexeme = models.ForeignKey(Lexeme, on_delete=models.DO_NOTHING, db_column="lexeme_id", related_name="external_links")
    label = models.TextField()
    url = models.TextField()
    class Meta:
        managed = False
        db_table = "external_links"


class Review(LegacyModel):
    book = models.ForeignKey(Book, on_delete=models.DO_NOTHING, db_column="book_id")
    surface = models.TextField()
    analyses_json = models.TextField(default="[]")
    status = models.TextField(default="pending")
    entries_json = models.TextField(default="[]")
    reason = models.TextField(default="")
    model = models.TextField(default="")
    updated_at = models.TextField()
    class Meta:
        managed = False
        db_table = "reviews"
