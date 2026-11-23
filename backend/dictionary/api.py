"""HTTP endpoints for searching and editing Ruslex entries.

Views handle requests, authorization, and response codes only. Read-only
queries live in ``queries.py`` and transactional writes in ``services.py``.
The existing URL paths and JSON response shapes are deliberately unchanged.
"""

import json
import logging
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from accounts.api import has_edit, has_review

from . import queries, services
from .catalog import ANIMACIES, ASPECTS, PARTS_OF_SPEECH, RELATIONS


logger = logging.getLogger(__name__)


def data(request) -> dict:
    """Parse a JSON object; never allow a top-level array or JSON scalar."""
    try:
        value = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise services.BadRequest("Invalid JSON") from exc

    if not isinstance(value, dict):
        raise services.BadRequest("Expected a JSON object")
    return value


def respond(value, status: int = 200) -> JsonResponse:
    response = JsonResponse(value, safe=not isinstance(value, list), status=status)
    response["Cache-Control"] = "no-store"
    return response


def api_errors(view):
    """Map expected client/database conflicts to stable HTTP error shapes.

    Unexpected exceptions are intentionally left to Django's normal 500
    handler and error logging, rather than being hidden as successful saves.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except (services.BadRequest, ValueError, ValidationError) as exc:
            return respond({"detail": str(exc)}, 400)
        except LookupError as exc:
            return respond({"detail": str(exc)}, 404)
        except IntegrityError:
            # Do not log request bodies: entry notes and user data may be private.
            logger.warning("Dictionary constraint conflict at %s", request.path)
            return respond({"detail": "Database constraint conflict"}, 409)

    return wrapper


def require(request, permission: str) -> JsonResponse | None:
    allowed = has_review(request.user) if permission == "review" else has_edit(request.user)
    if not allowed:
        return respond({"detail": "Sign in with the appropriate permission"}, 403)
    return None


def paging(request, limit: int = 100) -> tuple[int, int]:
    try:
        page = int(request.GET.get("page", 1))
        size = int(request.GET.get("page_size", 40))
        if page < 1 or not 1 <= size <= limit:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise services.BadRequest("Invalid pagination") from exc
    return page, size


def _validate_collection_url(request, record_id: int | None, label: str) -> None:
    """Require POST on collections and PUT on specific existing records."""
    if (request.method == "POST") != (record_id is None):
        raise services.BadRequest(f"Incorrect {label} URL")


@require_http_methods(["GET", "HEAD"])
def health(request):
    """Check connectivity to both databases; schema checks run at startup."""
    for alias in ("default", "lexicon"):
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    return HttpResponse("ok\n", content_type="text/plain")


@api_errors
@require_http_methods(["GET", "POST"])
def lexemes(request):
    if request.method == "GET":
        return respond(queries.search(request.GET, allow_review=has_review(request.user)))

    denied = require(request, "edit")
    if denied is not None:
        return denied
    return respond(services.create_word(data(request)), 201)


@api_errors
@require_http_methods(["GET", "PATCH"])
def lexeme(request, word_id: int):
    if request.method == "GET":
        result = queries.detail(
            word_id,
            private_notes=request.user.is_authenticated,
        )
        if result["human_status"] == "hidden" and not has_review(request.user):
            return respond({"detail": "Entry not available"}, 404)
        return respond(result)

    changes = data(request)
    permission = "review" if changes and set(changes) == {"human_status"} else "edit"
    denied = require(request, permission)
    if denied is not None:
        return denied
    return respond(services.update_word(word_id, changes))


@api_errors
@require_http_methods(["GET"])
def meta(request):
    return respond(
        {
            "parts_of_speech": [
                {"code": code, "label": label} for code, label in PARTS_OF_SPEECH
            ],
            "tag_categories": ["grammatical", "semantic", "usage"],
            "entry_types": ["word", "expression"],
            "aspects": sorted(ASPECTS),
            "animacies": sorted(ANIMACIES),
            "relation_types": sorted(RELATIONS),
        }
    )


@api_errors
@require_http_methods(["GET"])
def books(request):
    return respond(queries.books())


@api_errors
@require_http_methods(["GET"])
def tags(request):
    return respond(queries.tags())


@api_errors
@require_http_methods(["GET"])
def stats(request):
    return respond(queries.stats())


@api_errors
@require_http_methods(["GET"])
def next_review(request):
    denied = require(request, "review")
    if denied is not None:
        return denied

    try:
        after = int(request.GET.get("after", 0))
    except (ValueError, TypeError) as exc:
        raise services.BadRequest("Invalid after cursor") from exc
    if after < 0:
        raise services.BadRequest("Invalid after cursor")
    return respond(queries.next_review(request.GET.get("filter", "unreviewed"), after))


def _public_entry_allowed(request, word_id: int) -> bool:
    """A hidden entry must not leak through its reference endpoints."""
    if has_review(request.user):
        return True
    return queries.detail(word_id)["human_status"] != "hidden"


@api_errors
@require_http_methods(["GET"])
def refs(request, word_id: int):
    if not _public_entry_allowed(request, word_id):
        return respond({"detail": "Entry not available"}, 404)

    page, size = paging(request)
    try:
        book = int(request.GET["book_id"]) if request.GET.get("book_id") else None
        pdf = int(request.GET["pdf_page"]) if request.GET.get("pdf_page") else None
    except (ValueError, TypeError) as exc:
        raise services.BadRequest("Invalid reference filter") from exc
    return respond(queries.references(word_id, page, size, book, pdf))


@api_errors
@require_http_methods(["GET"])
def ref_pages(request, word_id: int):
    if not _public_entry_allowed(request, word_id):
        return respond({"detail": "Entry not available"}, 404)
    page, size = paging(request)
    return respond(queries.reference_pages(word_id, page, size))


def edit_allowed(request):
    return require(request, "edit")


@api_errors
@require_http_methods(["POST", "PUT", "DELETE"])
def relations(request, word_id: int, record_id: int | None = None):
    denied = edit_allowed(request)
    if denied is not None:
        return denied

    if request.method == "DELETE":
        if record_id is None:
            raise services.BadRequest("Relationship ID required")
        return respond(services.remove_relation(word_id, record_id))

    _validate_collection_url(request, record_id, "relationship")
    return respond(
        services.save_relation(word_id, data(request), record_id),
        201 if record_id is None else 200,
    )


@api_errors
@require_http_methods(["POST", "PUT", "DELETE"])
def components(request, word_id: int, record_id: int | None = None):
    denied = edit_allowed(request)
    if denied is not None:
        return denied

    if request.method == "DELETE":
        if record_id is None:
            raise services.BadRequest("Constituent ID required")
        return respond(services.remove_component(word_id, record_id))

    _validate_collection_url(request, record_id, "constituent")
    return respond(
        services.save_component(word_id, data(request), record_id),
        201 if record_id is None else 200,
    )


@api_errors
@require_http_methods(["POST", "PUT", "DELETE"])
def external_links(request, word_id: int, record_id: int | None = None):
    denied = edit_allowed(request)
    if denied is not None:
        return denied

    if request.method == "DELETE":
        if record_id is None:
            raise services.BadRequest("Link ID required")
        return respond(services.remove_external_link(word_id, record_id))

    _validate_collection_url(request, record_id, "link")
    return respond(
        services.save_external_link(word_id, data(request), record_id),
        201 if record_id is None else 200,
    )


@api_errors
@require_http_methods(["POST", "PUT"])
def records(
    request,
    word_id: int,
    table: str,
    sense_id: int | None = None,
    record_id: int | None = None,
):
    denied = edit_allowed(request)
    if denied is not None:
        return denied

    _validate_collection_url(request, record_id, "record")
    return respond(
        services.save_record(
            word_id,
            table,
            data(request),
            record_id=record_id,
            sense_id=sense_id,
        ),
        201 if record_id is None else 200,
    )


@api_errors
@require_http_methods(["PATCH"])
def activation(request, word_id: int, table: str, record_id: int):
    denied = edit_allowed(request)
    if denied is not None:
        return denied

    payload = data(request)
    services.fields(payload, {"active"})
    return respond(services.set_active(word_id, table, record_id, payload.get("active")))


@api_errors
@require_http_methods(["POST", "DELETE"])
def sense_tags(request, word_id: int, sense_id: int, tag_id: int | None = None):
    denied = edit_allowed(request)
    if denied is not None:
        return denied

    if request.method == "POST":
        if tag_id is not None:
            raise services.BadRequest("Unexpected tag ID")
        return respond(services.attach_tag(word_id, sense_id, data(request)), 201)

    if tag_id is None:
        raise services.BadRequest("Tag ID required")
    return respond(services.detach_tag(word_id, sense_id, tag_id))
