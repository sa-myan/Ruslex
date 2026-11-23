"""Keep legacy dictionary tables and Django administration in separate SQLite files."""

class DatabaseRouter:
    def db_for_read(self, model, **hints):
        return "lexicon" if model._meta.app_label == "dictionary" else "default"

    def db_for_write(self, model, **hints):
        return "lexicon" if model._meta.app_label == "dictionary" else "default"

    def allow_relation(self, obj1, obj2, **hints):
        # Cross-database relations are never allowed.
        first = "lexicon" if obj1._meta.app_label == "dictionary" else "default"
        second = "lexicon" if obj2._meta.app_label == "dictionary" else "default"
        return first == second

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # No migrations, even Django auth migrations, are permitted on lexicon.db.
        return db == "default" and app_label != "dictionary"
