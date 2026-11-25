#!/usr/bin/env python3
"""Run integration tests against disposable copies of both Ruslex databases.

Invoked by ``./manage.sh test`` inside the Docker image. The mounted live
lexicon is read only for backup; all test writes occur under a temporary
DATA_DIR, and the admin database is created from scratch.
"""

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS {message}")


def copy_database(source: Path, destination: Path) -> None:
    """Use SQLite's backup API, not a potentially inconsistent file copy."""
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as backup:
            original.backup(backup)


def csrf_headers(client) -> dict:
    return {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}


def json_request(client, method: str, path: str, payload) -> object:
    return getattr(client, method.lower())(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        **csrf_headers(client),
    )


def validation_unit_tests() -> None:
    suite = unittest.defaultTestLoader.discover(
        str(PROJECT_ROOT / "tests"), pattern="test_backend_validation.py"
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    check(result.wasSuccessful(), "Pure backend validation unit tests")


def check_database_isolation(connections) -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE name='lexemes'")
        check(not cursor.fetchone(), "Lexicon tables absent from admin database")
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE name='auth_user'")
        check(not cursor.fetchone(), "Auth tables absent from lexicon database")


def check_public_search(anonymous, queries, connections) -> None:
    from django.http import QueryDict

    all_words = queries.search(QueryDict("status=all"), allow_review=True)
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM lexemes")
        current_count = cursor.fetchone()[0]
    check(all_words["total"] == current_count, "Full search includes all entries")

    hidden_id = next(
        row["id"]
        for row in queries.legacy_rows(
            "SELECT id FROM lexemes WHERE human_status='hidden' ORDER BY id"
        )
    )
    check(
        anonymous.get(f"/api/lexemes/{hidden_id}").status_code == 404,
        "Hidden entry inaccessible anonymously",
    )
    check(
        anonymous.get(f"/api/lexemes/{hidden_id}/references").status_code == 404,
        "Hidden entry references inaccessible anonymously",
    )

    search_response = anonymous.get("/api/lexemes?q=read")
    check(search_response.status_code == 200, "English search succeeds")
    check(search_response.json()["total"] > 0, "English search returns matches")
    default_items = anonymous.get("/api/lexemes").json()["items"]
    check(
        all(item["human_status"] != "hidden" for item in default_items),
        "Hidden entries excluded from default search",
    )

    fixtures = json.loads((PROJECT_ROOT / "tests" / "v3_search_fixtures.json").read_text())
    # The original fixtures represent an immutable v3 corpus snapshot, not
    # merely every database that happens to contain 1,710 lexemes. Review
    # status changes can alter visible counts without changing total lexemes.
    # Keep search invariants on the current snapshot, and run historical
    # ID/order parity only when the fixture's visible corpus still matches.
    actual_visible = queries.search(QueryDict(""))
    fixture_visible = fixtures[""]["total"]
    check(
        actual_visible["total"] == sum(
            1 for row in queries.legacy_rows(
                "SELECT human_status FROM lexemes"
            ) if row["human_status"] != "hidden"
        ),
        "Default search matches current non-hidden dictionary records",
    )
    check(
        [row["id"] for row in actual_visible["items"]]
        == sorted(row["id"] for row in actual_visible["items"]),
        "Unfiltered search retains lexeme-ID order",
    )
    if current_count != 1710 or actual_visible["total"] != fixture_visible:
        print(
            "SKIP historical v3 search ID fixtures: live corpus differs "
            f"(lexemes={current_count}, visible={actual_visible['total']}; "
            f"fixture lexemes=1710, visible={fixture_visible}). "
            "Current-database invariants were checked."
        )
        return

    for query, expected in fixtures.items():
        params = QueryDict("", mutable=True)
        params["q"] = query
        result = queries.search(params)
        check(
            result["total"] == expected["total"]
            and [entry["id"] for entry in result["items"][:15]] == expected["ids"],
            f"v3 search parity {query!r}",
        )


def check_permissions(anonymous, reviewer, editor) -> None:
    check(
        json_request(anonymous, "patch", "/api/lexemes/1", {"notes": "bad"}).status_code == 403,
        "Anonymous editing rejected",
    )
    missing_csrf = editor.patch(
        "/api/lexemes/1",
        data=json.dumps({"notes": "must not save"}),
        content_type="application/json",
    )
    check(missing_csrf.status_code == 403, "Editing requires a CSRF token")
    check(
        json_request(
            anonymous,
            "post",
            "/api/auth/signup",
            {"username": "guest1", "email": "g@example.org", "password": "StrongPassword!49"},
        ).status_code == 403,
        "Registration defaults disabled",
    )
    check(
        json_request(reviewer, "patch", "/api/lexemes/1", {"notes": "no"}).status_code == 403,
        "Reviewer cannot edit notes",
    )
    check(
        json_request(
            reviewer, "patch", "/api/lexemes/1", {"human_status": "followup"}
        ).status_code == 200,
        "Reviewer can update review status",
    )

    check(
        json_request(editor, "patch", "/api/lexemes/1", {"notes": "smoke test"}).status_code == 200,
        "Editor can edit entry",
    )
    public_entry = anonymous.get("/api/lexemes/1")
    check(
        public_entry.status_code == 200 and public_entry.json()["notes"] == "smoke test",
        "Entry notes are visible to anonymous readers",
    )


def check_bad_input(editor) -> None:
    invalid_json = editor.patch(
        "/api/lexemes/1",
        data='{"notes":',
        content_type="application/json",
        **csrf_headers(editor),
    )
    check(invalid_json.status_code == 400, "Malformed dictionary JSON returns 400")

    invalid_shape = editor.patch(
        "/api/lexemes/1",
        data="[1, 2]",
        content_type="application/json",
        **csrf_headers(editor),
    )
    check(invalid_shape.status_code == 400, "Dictionary payload must be an object")
    check(
        json_request(editor, "patch", "/api/lexemes/1", {"unknown": True}).status_code == 400,
        "Unknown entry fields rejected",
    )
    check(
        json_request(editor, "patch", "/api/lexemes/1", {"human_status": []}).status_code == 400,
        "Malformed review status rejected",
    )


def check_existing_tag_reuse(anonymous, editor, connections) -> None:
    with connections["lexicon"].cursor() as cursor:
        cursor.execute(
            "SELECT id FROM senses WHERE lexeme_id=1 AND active=1 ORDER BY id LIMIT 1"
        )
        sense_id = cursor.fetchone()[0]
        cursor.execute(
            """SELECT t.id, t.name, t.category FROM tags t
               WHERE NOT EXISTS (
                   SELECT 1 FROM sense_tags st
                   WHERE st.sense_id=%s AND st.tag_id=t.id
               ) ORDER BY t.id LIMIT 1""",
            [sense_id],
        )
        tag_id, name, category = cursor.fetchone()

    attached = json_request(
        editor,
        "post",
        f"/api/lexemes/1/senses/{sense_id}/tags",
        {"name": name, "category": category},
    )
    check(
        attached.status_code == 201 and attached.json()["id"] == tag_id,
        "Adding an existing tag reuses its dictionary ID",
    )
    check(
        any(
            tag["id"] == tag_id
            for sense in anonymous.get("/api/lexemes/1").json()["senses"]
            for tag in sense["tags"]
        ),
        "Existing tag visible on the updated sense",
    )


def check_editing_workflow(anonymous, editor) -> None:
    """Exercise important editor operations without touching production data."""
    first = json_request(editor, "post", "/api/lexemes", {
        "lemma": "тестоваялексема", "pos": "NOUN"
    })
    second = json_request(editor, "post", "/api/lexemes", {
        "lemma": "тестоваяединица", "pos": "NOUN"
    })
    check(
        first.status_code == 201 and second.status_code == 201,
        "Create two isolated test entries",
    )
    first_id, second_id = first.json()["id"], second.json()["id"]

    first_sense = json_request(
        editor, "post", f"/api/lexemes/{first_id}/senses",
        {"meaning": "first sense", "description": "for testing"},
    )
    second_sense = json_request(
        editor, "post", f"/api/lexemes/{second_id}/senses",
        {"meaning": "second sense"},
    )
    check(
        first_sense.status_code == 201 and second_sense.status_code == 201,
        "Create senses beneath their own entries",
    )
    first_sid, second_sid = first_sense.json()["id"], second_sense.json()["id"]

    example_path = f"/api/lexemes/{first_id}/senses/{first_sid}/examples"
    pattern_path = f"/api/lexemes/{first_id}/senses/{first_sid}/patterns"
    example = json_request(
        editor, "post", example_path,
        {"russian": "Пример.", "english": "Example."},
    )
    pattern = json_request(
        editor, "post", pattern_path, {"pattern": "что + падеж"},
    )
    check(
        example.status_code == 201 and pattern.status_code == 201,
        "Create sense-specific examples and patterns",
    )
    wrong_parent = json_request(
        editor, "post", f"/api/lexemes/{first_id}/senses/{second_sid}/examples",
        {"russian": "Wrong parent", "english": "Invalid"},
    )
    check(wrong_parent.status_code == 404, "Child records cannot cross entries")

    activation_path = (
        f"/api/lexemes/{first_id}/records/examples/{example.json()['id']}/active"
    )
    invalid_activation = json_request(
        editor, "patch", activation_path, {"active": 1}
    )
    check(invalid_activation.status_code == 400, "Activation requires a JSON boolean")
    disabled = json_request(
        editor, "patch", activation_path, {"active": False}
    )
    check(
        disabled.status_code == 200 and disabled.json()["active"] == 0,
        "Sense example activation remains functional",
    )

    link_path = f"/api/lexemes/{first_id}/external-links"
    rejected_link = json_request(
        editor, "post", link_path,
        {"label": "unsafe", "url": "https://user@example.org"},
    )
    check(rejected_link.status_code == 400, "Credential-bearing external URLs rejected")
    added_link = json_request(
        editor, "post", link_path,
        {"label": "Reference", "url": "https://example.org/word"},
    )
    check(added_link.status_code == 201, "External reference links work")

    relation = json_request(
        editor, "post", f"/api/lexemes/{first_id}/relations",
        {
            "target_lexeme_id": second_id,
            "relation_type": "derivation",
            "source_sense_id": first_sid,
            "target_sense_id": second_sid,
            "notes": "editor-only explanation",
        },
    )
    check(relation.status_code == 201, "Create a sense-scoped derivation")
    relation_id = relation.json()["id"]

    public_relations = anonymous.get(f"/api/lexemes/{first_id}").json()["relations"]
    editor_relations = editor.get(f"/api/lexemes/{first_id}").json()["relations"]
    public_note = next(
        item["notes"] for item in public_relations if item["id"] == relation_id
    )
    private_note = next(
        item["notes"] for item in editor_relations if item["id"] == relation_id
    )
    check(
        public_note == "" and private_note == "editor-only explanation",
        "Relation notes remain private while entry notes are public",
    )

    updated = json_request(
        editor, "put", f"/api/lexemes/{second_id}/relations/{relation_id}",
        {
            "target_lexeme_id": first_id,
            "relation_type": "derivation",
            "source_sense_id": second_sid,
            "target_sense_id": first_sid,
            "notes": "updated editor-only explanation",
        },
    )
    relation_data = updated.json() if updated.status_code == 200 else {}
    check(
        updated.status_code == 200
        and relation_data["source_lexeme_id"] == first_id
        and relation_data["target_lexeme_id"] == second_id
        and relation_data["source_sense_id"] == first_sid
        and relation_data["target_sense_id"] == second_sid,
        "Editing an incoming derivation preserves direction and sense links",
    )


def check_signup(anonymous, User, SiteOptions) -> None:
    SiteOptions.objects.filter(pk=1).update(registration_open=True)
    signup = json_request(
        anonymous, "post", "/api/auth/signup",
        {
            "username": "guest1",
            "email": "g@example.org",
            "password": "StrongPassword!49",
        },
    )
    check(signup.status_code == 201, "Admin-controlled registration switch")
    check(
        not User.objects.get(username="guest1").groups.exists(),
        "Signup receives no editing roles",
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ruslex-test-") as temporary:
        temp_root = Path(temporary)
        (temp_root / "lexicon").mkdir()
        (temp_root / "admin").mkdir()

        source = Path(os.environ.get("DATA_DIR", "/data")) / "lexicon" / "lexicon.db"
        copy_database(source, temp_root / "lexicon" / "lexicon.db")
        os.environ["DATA_DIR"] = str(temp_root)
        os.environ["DJANGO_ALLOWED_HOSTS"] = "testserver,localhost"
        os.environ["HTTPS_ENABLED"] = "0"
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "siteconf.settings")
        os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-never-production")

        import django
        django.setup()
        from django.contrib.auth.models import Group, User
        from django.core.management import call_command
        from django.db import connections
        from django.test import Client
        from accounts.models import SiteOptions
        from dictionary import queries

        validation_unit_tests()
        call_command("migrate", database="default", interactive=False, verbosity=0)
        call_command("initialize_roles", verbosity=0)
        call_command("check_lexicon", verbosity=0)
        check_database_isolation(connections)

        anonymous = Client(enforce_csrf_checks=True)
        check(anonymous.get("/api/auth/me").status_code == 200, "Auth handshake")
        check_public_search(anonymous, queries, connections)

        reviewer_user = User.objects.create_user("reviewer", password="StrongPassword!49")
        reviewer_user.groups.add(Group.objects.get(name="Reviewer"))
        editor_user = User.objects.create_user("editor", password="StrongPassword!49")
        editor_user.groups.add(Group.objects.get(name="Editor"))

        reviewer = Client(enforce_csrf_checks=True)
        reviewer.force_login(reviewer_user)
        reviewer.get("/api/auth/me")  # Issue a CSRF cookie.
        editor = Client(enforce_csrf_checks=True)
        editor.force_login(editor_user)
        editor.get("/api/auth/me")

        check_permissions(anonymous, reviewer, editor)
        check_bad_input(editor)
        check_existing_tag_reuse(anonymous, editor, connections)
        check_editing_workflow(anonymous, editor)
        check_signup(anonymous, User, SiteOptions)
        print("ALL DJANGO SMOKE TESTS PASSED; live databases were not touched")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
