from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="SiteOptions",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("registration_open", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "site options", "verbose_name_plural": "site options",
                     "permissions": [("review_lexicon", "Review lexicon entries"),
                                     ("edit_lexicon", "Edit lexicon entries"),
                                     ("run_pipeline", "Run lexicon processing pipelines")]},
        ),
    ]
