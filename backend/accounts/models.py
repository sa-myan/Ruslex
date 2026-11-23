"""Only administrative data lives here, on Django's default database."""
from django.db import models


class SiteOptions(models.Model):
    registration_open = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site options"
        verbose_name_plural = "site options"
        permissions = [
            ("review_lexicon", "Review lexicon entries"),
            ("edit_lexicon", "Edit lexicon entries"),
            ("run_pipeline", "Run lexicon processing pipelines"),
        ]

    @classmethod
    def current(cls):
        return cls.objects.first() or cls(registration_open=False)
