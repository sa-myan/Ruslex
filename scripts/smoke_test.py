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

    # Validate current database behavior, not the historical state of v3.
    # An unchanged total lexeme count is not a dataset identity checksum:
    # human edits to visibility/senses legitimately change results and ranking.
    visible_count = queries.legacy_rows(
        "SELECT COUNT(*) AS n FROM lexemes WHERE human_status != 'hidden'"
    )[0]["n"]
    current = queries.search(QueryDict(""))
    check(current["total"] == visible_count,
          "Default search reflects current visible entries")
    check([item["id"] for item in current["items"]]
          == sorted(item["id"] for item in current["items"]),
          "Unfiltered results have stable lexeme-ID order")
    for search_term in ("read", "write", "book", "читать", "замок"):
        params = QueryDict("", mutable=True)
        params["q"] = search_term
        first = queries.search(params)
        second = queries.search(params)
        check(first == second, f"Search ranking deterministic for {search_term!r}")
        check(first["total"] >= len(first["items"]),
              f"Search paging total valid for {search_term!r}")
        check(all(item["human_status"] != "hidden" for item in first["items"]),
              f"Search excludes hidden entries for {search_term!r}")

    # Historical parity requires the identical original v3 corpus, including
    # senses and review decisions. The live 1,710-row dictionary is mutable.
    # Keep the fixture as an explicit opt-in regression for a known v3 snapshot.
    if os.environ.get("RUSLEX_TEST_V3_PARITY") != "1":
        print("SKIP historical v3 fixture parity (opt-in only on original v3 snapshot)")
        return

    fixtures = json.loads((PROJECT_ROOT / "tests" / "v3_search_fixtures.json").read_text())
    for query, expected in fixtures.items():
        params = QueryDict("", mutable=True)
        params["q"] = query
        result = queries.search(params)
        actual_ids = [entry["id"] for entry in result["items"][:15]]
        check(
            result["total"] == expected["total"] and actual_ids == expected["ids"],
            f"original v3 parity {query!r}: actual total={result['total']}, "
            f"ids={actual_ids}; expected total={expected['total']}, "
            f"ids={expected['ids']}",
        )


def check_word_forms(anonymous, connections) -> None:
    """Verify morphology form search and entry detail on a migrated snapshot."""
    from urllib.parse import quote
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE name='lexeme_forms'")
        if cursor.fetchone() is None:
            print("SKIP morphological forms tests: schema not installed in snapshot")
            return
        cursor.execute(
            """SELECT f.lexeme_id,f.form,f.form_key
               FROM lexeme_forms f JOIN lexemes l ON l.id=f.lexeme_id
               WHERE l.human_status!='hidden' AND f.form_key!=lower(l.lemma)
               ORDER BY length(f.form_key) DESC,f.lexeme_id LIMIT 1"""
        )
        row = cursor.fetchone()
    if row is None:
        print("SKIP morphology search test: no inflected forms in snapshot")
        return
    lexeme_id, form, _ = row
    entry = anonymous.get(f"/api/lexemes/{lexeme_id}")
    check(entry.status_code == 200 and
          any(candidate["form"] == form for candidate in
              entry.json()["word_forms"]),
          "Inflected forms are visible in dictionary entry")
    response = anonymous.get("/api/lexemes?q=" + quote(form))
    ids = [item["id"] for item in response.json()["items"]]
    check(response.status_code == 200 and lexeme_id in ids,
          "Search by inflected form finds its dictionary lemma")


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


def check_pronunciation(anonymous, reviewer, editor, connections) -> None:
    """Exercise the new API on a migrated, disposable dictionary."""
    with connections["lexicon"].cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE name='lexeme_pronunciations'"
        )
        if cursor.fetchone() is None:
            print("SKIP pronunciation API tests: source snapshot has no stress schema")
            return

    first = json_request(editor, "post", "/api/lexemes", {
        "lemma": "пробаслово", "pos": "NOUN",
    })
    check(first.status_code == 201, "Create isolated pronunciation test entry")
    word_id = first.json()["id"]
    sense = json_request(editor, "post", f"/api/lexemes/{word_id}/senses", {
        "meaning": "temporary pronunciation test",
    })
    check(sense.status_code == 201, "Create pronunciation test sense")
    sid = sense.json()["id"]
    url = f"/api/lexemes/{word_id}/pronunciations"
    payload = {"stressed": "про́баслово", "is_primary": True, "sense_ids": [sid]}
    denied = json_request(reviewer, "post", url, payload)
    check(denied.status_code == 403, "Reviewers cannot modify pronunciation")
    denied = json_request(anonymous, "post", url, payload)
    check(denied.status_code == 403, "Anonymous pronunciation editing denied")
    bad = json_request(editor, "post", url, {
        "stressed": "друго́еслово", "is_primary": True,
    })
    check(bad.status_code == 400, "Pronunciation cannot change lexical identity")
    added = json_request(editor, "post", url, payload)
    check(added.status_code == 201, "Editor can add stressed headword")
    reading_id = added.json()["id"]
    detail = anonymous.get(f"/api/lexemes/{word_id}").json()
    check(detail["stressed_lemma"] == "про́баслово",
          "Public entry displays selected stressed reading")
    check(detail["pronunciations"][0]["sense_ids"] == [sid],
          "Reading is attached to the correct sense")
    updated = json_request(editor, "put", f"{url}/{reading_id}", {
        "stressed": "проба́слово", "is_primary": True, "sense_ids": [],
    })
    check(updated.status_code == 200, "Editor can correct stress")
    check(anonymous.get(f"/api/lexemes/{word_id}").json()["stressed_lemma"]
          == "проба́слово", "Corrected pronunciation is shown")
    deleted = json_request(editor, "delete", f"{url}/{reading_id}", {})
    check(deleted.status_code == 200, "Editor can remove pronunciation")
    check(anonymous.get(f"/api/lexemes/{word_id}").json()["stressed_lemma"]
          == "пробаслово", "No reading falls back to original lemma")


def check_pronunciation_review_jump(anonymous, reviewer, editor, connections) -> None:
    """Navigate by exact headword or ID without editing the queue."""
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE name='pronunciation_review_queue'")
        if cursor.fetchone() is None:
            print("SKIP pronunciation jump API: optional queue schema not installed")
            return

    created = json_request(editor, "post", "/api/lexemes", {
        "lemma": "пробапереход", "pos": "NOUN", "entry_type": "word",
    })
    check(created.status_code == 201, "Create disposable pronunciation jump target")
    word_id = created.json()["id"]
    route = "/api/pronunciation-review/next"
    check(anonymous.get(route, {"queue": "all", "find": str(word_id)}).status_code == 403,
          "Anonymous pronunciation queue cannot be queried")
    check(reviewer.get(route, {"queue": "all", "find": str(word_id)}).status_code == 403,
          "General reviewers cannot access editor-only pronunciation queue")
    for target in (str(word_id), f"#{word_id}", "ПРОБАПЕРЕХОД"):
        response = editor.get(route, {"queue": "all", "find": target})
        check(response.status_code == 200 and response.json()["entry"]["id"] == word_id,
              "Jump finds exact unresolved entry by ID or casefolded lemma")
    missing = editor.get(route, {"queue": "all", "find": "not-a-real-lemma"})
    check(missing.status_code == 200 and missing.json()["entry"] is None,
          "Unknown jump target does not silently select another word")
    invalid = editor.get(route, {"queue": "all", "find": " "})
    check(invalid.status_code == 400, "Blank jump target is rejected")
    huge = editor.get(route, {"queue": "all", "find": "#" + "9" * 40})
    check(huge.status_code == 400, "Out-of-range ID is rejected")

    deferred = json_request(editor, "put", f"/api/pronunciation-review/{word_id}/defer",
                            {"deferred": True, "note": "test later"})
    check(deferred.status_code == 200, "Can defer test word")
    found = editor.get(route, {"queue": "all", "find": str(word_id)})
    check(found.status_code == 200 and found.json()["deferred"],
          "Jump includes deferred entries without clearing their notes")
    pending = editor.get(route, {"queue": "pending", "find": str(word_id)})
    check(pending.status_code == 200 and pending.json()["entry"] is None,
          "Jump honors explicit queue filter")
    json_request(editor, "put", f"/api/pronunciation-review/{word_id}/defer",
                 {"deferred": False, "note": ""})


def check_abbreviations(anonymous, editor, connections) -> None:
    """Abbreviations work as a third entry type on the migrated snapshot."""
    from django.http import QueryDict
    from dictionary import queries
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE name='lexemes'")
        ddl = cursor.fetchone()[0]
    if "'abbreviation'" not in ddl:
        print("SKIP abbreviation integration: dictionary has not been migrated")
        return
    metadata = anonymous.get("/api/meta").json()
    check("abbreviation" in metadata["entry_types"],
          "API advertises abbreviation category")

    created = json_request(editor, "post", "/api/lexemes", {
        "lemma": "РЖДПРИМЕР", "pos": "NOUN", "entry_type": "abbreviation",
    })
    check(created.status_code == 201, "Editor can create abbreviation")
    abbr_id = created.json()["id"]
    detail = anonymous.get(f"/api/lexemes/{abbr_id}").json()
    check(detail["entry_type"] == "abbreviation"
          and detail["stressed_lemma"] == "РЖДПРИМЕР",
          "Abbreviation retains kind and conventional uppercase display")
    listing = queries.search(QueryDict("entry_type=abbreviation&q=рждпример"))
    check(abbr_id in [entry["id"] for entry in listing["items"]],
          "Abbreviations are searchable independently")

    expression = json_request(editor, "post", "/api/lexemes", {
        "lemma": "сказать пример", "pos": "OTHER",
        "entry_type": "expression",
    })
    check(expression.status_code == 201, "Create temporary expression for abbreviation link")
    expr_id = expression.json()["id"]
    constituent = json_request(
        editor, "post", f"/api/lexemes/{expr_id}/components",
        {"word_id": abbr_id, "position": 1, "surface": "РЖДПРИМЕР", "notes": ""}
    )
    check(constituent.status_code == 201,
          "Expressions can contain abbreviation entries")
    check(anonymous.get(f"/api/lexemes/{expr_id}").status_code == 200,
          "Expression with abbreviation renders normally")


def check_constructions(anonymous, reviewer, editor, connections) -> None:
    """Construction review remains isolated from existing lexical expression data."""
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE name='constructions'")
        if cursor.fetchone() is None:
            print("SKIP construction API: optional schema not initialized")
            return
    listing = anonymous.get("/api/constructions")
    check(listing.status_code == 200 and listing.json()["installed"],
          "Public constructions endpoint responds")
    denied = json_request(anonymous, "patch", "/api/constructions/1/status",
                          {"human_status": "kept"})
    check(denied.status_code == 403, "Anonymous users cannot classify constructions")
    denied = json_request(editor, "patch", "/api/constructions/1/status",
                          {"human_status": "kept"})
    check(denied.status_code == 404, "Editor has reviewer rights; missing construction returns 404")
    invalid = json_request(reviewer, "patch", "/api/constructions/1/status",
                           {"human_status": "not-real"})
    check(invalid.status_code == 400, "Invalid construction status rejected")
    with connections["lexicon"].cursor() as cursor:
        cursor.execute(
            """INSERT INTO constructions(pattern,pattern_key,meaning,grammar,created_at)
               VALUES(%s,%s,%s,%s,datetime('now'))""",
            ["чем X, тем Y", "чем x, тем y", "the more, the more", "comparatives"])
        construction_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO construction_examples(construction_id,russian,english) VALUES(%s,%s,%s)",
            [construction_id, "Чем больше читаешь, тем больше узнаёшь.",
             "The more you read, the more you learn."])
    public = anonymous.get("/api/constructions").json()
    check(any(item["id"] == construction_id for item in public["items"]),
          "Public constructions include approved/pending visible entries")
    response = json_request(
        reviewer, "patch", f"/api/constructions/{construction_id}/status",
        {"human_status": "hidden"})
    check(response.status_code == 200, "Reviewer can hide a construction")
    check(not any(item["id"] == construction_id for item in
                  anonymous.get("/api/constructions").json()["items"]),
          "Hidden construction inaccessible to public list")
    check(any(item["id"] == construction_id for item in
              reviewer.get("/api/constructions?status=all").json()["items"]),
          "Reviewer can inspect hidden constructions")
    response = json_request(
        reviewer, "patch", f"/api/constructions/{construction_id}/status",
        {"human_status": "kept"})
    check(response.status_code == 200, "Reviewer can keep a construction")
    check(anonymous.get("/api/constructions?status=hidden").json()["total"] ==
          anonymous.get("/api/constructions").json()["total"],
          "Anonymous clients cannot force hidden status listing")


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

        source = Path(os.environ.get("RUSLEX_SMOKE_LEXICON_SOURCE") or (Path(os.environ.get("DATA_DIR", "/data")) / "lexicon" / "lexicon.db"))
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
        check_word_forms(anonymous, connections)

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
        check_pronunciation(anonymous, reviewer, editor, connections)
        check_pronunciation_review_jump(anonymous, reviewer, editor, connections)
        check_abbreviations(anonymous, editor, connections)
        check_constructions(anonymous, reviewer, editor, connections)
        check_signup(anonymous, User, SiteOptions)
        print("ALL DJANGO SMOKE TESTS PASSED; live databases were not touched")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
