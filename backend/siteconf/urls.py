"""One explicit URL table. The SPA fallback never intercepts API or admin."""
from django.contrib import admin
from django.urls import path, re_path
from django.http import FileResponse, HttpResponse
from django.conf import settings
from accounts import api as accounts
from dictionary import api as dictionary


def spa(request):
    index = settings.BASE_DIR / "frontend_static" / "index.html"
    if not index.is_file():
        return HttpResponse("Frontend has not been built", status=503)
    return FileResponse(index.open("rb"),content_type="text/html")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", dictionary.health),
    path("api/auth/me", accounts.me),
    path("api/auth/login", accounts.sign_in),
    path("api/auth/logout", accounts.sign_out),
    path("api/auth/signup", accounts.sign_up),
    path("api/lexemes", dictionary.lexemes),
    path("api/lexemes/<int:word_id>", dictionary.lexeme),
    path("api/lexemes/<int:word_id>/pronunciations", dictionary.pronunciation_records),
    path("api/lexemes/<int:word_id>/pronunciations/<int:record_id>", dictionary.pronunciation_records),
    path("api/lexemes/<int:word_id>/relations", dictionary.relations),
    path("api/lexemes/<int:word_id>/relations/<int:record_id>", dictionary.relations),
    path("api/lexemes/<int:word_id>/external-links", dictionary.external_links),
    path("api/lexemes/<int:word_id>/external-links/<int:record_id>", dictionary.external_links),
    path("api/lexemes/<int:word_id>/components", dictionary.components),
    path("api/lexemes/<int:word_id>/components/<int:record_id>", dictionary.components),
    path("api/lexemes/<int:word_id>/senses", dictionary.records, {"table":"senses"}),
    path("api/lexemes/<int:word_id>/senses/<int:record_id>", dictionary.records, {"table":"senses"}),
    path("api/lexemes/<int:word_id>/senses/<int:sense_id>/examples", dictionary.records, {"table":"examples"}),
    path("api/lexemes/<int:word_id>/senses/<int:sense_id>/examples/<int:record_id>", dictionary.records, {"table":"examples"}),
    path("api/lexemes/<int:word_id>/senses/<int:sense_id>/patterns", dictionary.records, {"table":"patterns"}),
    path("api/lexemes/<int:word_id>/senses/<int:sense_id>/patterns/<int:record_id>", dictionary.records, {"table":"patterns"}),
    path("api/lexemes/<int:word_id>/senses/<int:sense_id>/tags", dictionary.sense_tags),
    path("api/lexemes/<int:word_id>/senses/<int:sense_id>/tags/<int:tag_id>", dictionary.sense_tags),
    path("api/lexemes/<int:word_id>/records/<str:table>/<int:record_id>/active", dictionary.activation),
    path("api/lexemes/<int:word_id>/references", dictionary.refs),
    path("api/lexemes/<int:word_id>/reference-pages", dictionary.ref_pages),
    path("api/review/next", dictionary.next_review),
    path("api/pronunciation-review/next", dictionary.pronunciation_review_next),
    path("api/pronunciation-review/<int:word_id>/defer", dictionary.pronunciation_review_defer),
    path("api/stats", dictionary.stats),
    path("api/books", dictionary.books),
    path("api/constructions", dictionary.construction_list),
    path("api/construction-review/next", dictionary.construction_review_next),
    path("api/constructions/<int:construction_id>/status", dictionary.construction_status),
    path("api/tags", dictionary.tags),
    path("api/meta", dictionary.meta),
    re_path(r"^(?!api(?:/|$)|admin(?:/|$)|static(?:/|$)).*$", spa),
]
