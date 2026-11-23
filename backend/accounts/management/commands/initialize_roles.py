"""Initialize permissions using Django's built-in Groups; safe to rerun."""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from accounts.models import SiteOptions


class Command(BaseCommand):
    help = "Create default reviewer, editor, and pipeline-operator groups"

    def handle(self, *args, **options):
        content_type = ContentType.objects.get_for_model(SiteOptions)
        mapping = {
            "Reviewer": ["review_lexicon"],
            "Editor": ["review_lexicon", "edit_lexicon"],
            "Pipeline Operator": ["run_pipeline"],
        }
        for name, codenames in mapping.items():
            group, _ = Group.objects.get_or_create(name=name)
            perms = Permission.objects.filter(content_type=content_type, codename__in=codenames)
            if perms.count() != len(codenames):
                raise RuntimeError("Permissions missing: run migrate first")
            group.permissions.set(perms)
            self.stdout.write(f"Configured group: {name}")
        SiteOptions.objects.get_or_create(pk=1, defaults={"registration_open": False})
