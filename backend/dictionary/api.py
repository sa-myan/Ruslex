"""Plain Django JSON endpoints mirroring v3's public API.

Use native Django session authentication, CSRF middleware, permission groups,
ORM transactions and Admin instead of a second authentication framework.
"""
import json
from functools import wraps

from django.db import connections, IntegrityError
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from accounts.api import has_edit, has_review
from . import services, queries
from .catalog import PARTS_OF_SPEECH, RELATIONS, ASPECTS, ANIMACIES


def data(request):
    try:
        value=json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise services.BadRequest("Invalid JSON")
    if not isinstance(value,dict): raise services.BadRequest("Expected a JSON object")
    return value


def respond(value, status=200):
    response=JsonResponse(value,safe=not isinstance(value,list),status=status)
    response["Cache-Control"]="no-store"
    return response


def api_errors(func):
    @wraps(func)
    def wrapper(request,*args,**kwargs):
        try:
            return func(request,*args,**kwargs)
        except (services.BadRequest, ValueError, ValidationError) as exc:
            return respond({"detail":str(exc)},400)
        except LookupError as exc:
            return respond({"detail":str(exc)},404)
        except IntegrityError:
            return respond({"detail":"Database constraint conflict"},409)
    return wrapper


def require(request,permission):
    user=request.user
    granted=has_review(user) if permission=="review" else has_edit(user)
    if not granted:
        return respond({"detail":"Sign in with the appropriate permission"},403)


def paging(request,limit=100):
    try:
        page=int(request.GET.get("page",1));size=int(request.GET.get("page_size",40))
        if page<1 or not (1<=size<=limit):raise ValueError
    except (ValueError,TypeError):
        raise services.BadRequest("Invalid pagination")
    return page,size


@require_http_methods(["GET","HEAD"])
def health(request):
    # This confirms both database aliases are reachable; startup separately
    # validates the lexicon schema and admin migrations.
    for alias in ("default","lexicon"):
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    return HttpResponse("ok\n",content_type="text/plain")


@api_errors
@require_http_methods(["GET","POST"])
def lexemes(request):
    if request.method=="GET":
        return respond(queries.search(request.GET,allow_review=has_review(request.user)))
    denied=require(request,"edit")
    if denied:return denied
    return respond(services.create_word(data(request)),201)


@api_errors
@require_http_methods(["GET","PATCH"])
def lexeme(request,word_id):
    if request.method=="GET":
        result=queries.detail(word_id,private_notes=request.user.is_authenticated)
        if result["human_status"]=="hidden" and not has_review(request.user):
            return respond({"detail":"Entry not available"},404)
        return respond(result)
    changes=data(request)
    level="review" if changes and set(changes)=={"human_status"} else "edit"
    denied=require(request,level)
    if denied:return denied
    return respond(services.update_word(word_id,changes))


@api_errors
@require_http_methods(["GET"])
def meta(request):
    return respond({"parts_of_speech":[{"code":a,"label":b} for a,b in PARTS_OF_SPEECH],
       "tag_categories":["grammatical","semantic","usage"],
       "entry_types":["word","expression"], "aspects":sorted(ASPECTS),
       "animacies":sorted(ANIMACIES),"relation_types":sorted(RELATIONS)})


@api_errors
@require_http_methods(["GET"])
def books(request):return respond(queries.books())


@api_errors
@require_http_methods(["GET"])
def tags(request):return respond(queries.tags())


@api_errors
@require_http_methods(["GET"])
def stats(request):return respond(queries.stats())


@api_errors
@require_http_methods(["GET"])
def next_review(request):
    denied=require(request,"review")
    if denied:return denied
    try:after=int(request.GET.get("after",0))
    except ValueError:raise services.BadRequest("Invalid after cursor")
    if after<0:raise services.BadRequest("Invalid after cursor")
    return respond(queries.next_review(request.GET.get("filter","unreviewed"),after))


@api_errors
@require_http_methods(["GET"])
def refs(request,word_id):
    if not has_review(request.user) and queries.detail(word_id)["human_status"]=="hidden":
        return respond({"detail":"Entry not available"},404)
    page,size=paging(request)
    try:
        book=int(request.GET["book_id"]) if request.GET.get("book_id") else None
        pdf=int(request.GET["pdf_page"]) if request.GET.get("pdf_page") else None
    except ValueError:raise services.BadRequest("Invalid reference filter")
    return respond(queries.references(word_id,page,size,book,pdf))


@api_errors
@require_http_methods(["GET"])
def ref_pages(request,word_id):
    if not has_review(request.user) and queries.detail(word_id)["human_status"]=="hidden":
        return respond({"detail":"Entry not available"},404)
    page,size=paging(request)
    return respond(queries.reference_pages(word_id,page,size))


def edit_allowed(request):
    denied=require(request,"edit")
    if denied:return denied
    return None


@api_errors
@require_http_methods(["POST","PUT","DELETE"])
def relations(request,word_id,record_id=None):
    if (denied:=edit_allowed(request)):return denied
    if request.method=="DELETE":
        if record_id is None:raise services.BadRequest("Relationship ID required")
        return respond(services.remove_relation(word_id,record_id))
    if request.method=="POST" and record_id is not None or request.method=="PUT" and record_id is None:
        raise services.BadRequest("Incorrect relationship URL")
    return respond(services.save_relation(word_id,data(request),record_id),201 if record_id is None else 200)


@api_errors
@require_http_methods(["POST","PUT","DELETE"])
def components(request,word_id,record_id=None):
    if (denied:=edit_allowed(request)):return denied
    if request.method=="DELETE":
        if record_id is None:raise services.BadRequest("Constituent ID required")
        return respond(services.remove_component(word_id,record_id))
    if (request.method == "POST") != (record_id is None):
        raise services.BadRequest("Incorrect constituent URL")
    return respond(services.save_component(word_id,data(request),record_id),201 if record_id is None else 200)


@api_errors
@require_http_methods(["POST","PUT","DELETE"])
def external_links(request,word_id,record_id=None):
    if (denied:=edit_allowed(request)):return denied
    if request.method=="DELETE":
        if record_id is None:raise services.BadRequest("Link ID required")
        return respond(services.remove_external_link(word_id,record_id))
    if (request.method == "POST") != (record_id is None):
        raise services.BadRequest("Incorrect link URL")
    return respond(services.save_external_link(word_id,data(request),record_id),201 if record_id is None else 200)


@api_errors
@require_http_methods(["POST","PUT"])
def records(request,word_id,table,sense_id=None,record_id=None):
    if (denied:=edit_allowed(request)):return denied
    if (request.method == "POST") != (record_id is None):
        raise services.BadRequest("Incorrect record URL")
    return respond(services.save_record(word_id,table,data(request),record_id=record_id,sense_id=sense_id),
                   201 if record_id is None else 200)


@api_errors
@require_http_methods(["PATCH"])
def activation(request,word_id,table,record_id):
    if (denied:=edit_allowed(request)):return denied
    payload=data(request)
    services.fields(payload,{"active"})
    return respond(services.set_active(word_id,table,record_id,payload.get("active")))


@api_errors
@require_http_methods(["POST","DELETE"])
def sense_tags(request,word_id,sense_id,tag_id=None):
    if (denied:=edit_allowed(request)):return denied
    if request.method=="POST":
        if tag_id is not None:raise services.BadRequest("Unexpected tag ID")
        return respond(services.attach_tag(word_id,sense_id,data(request)),201)
    if tag_id is None:raise services.BadRequest("Tag ID required")
    return respond(services.detach_tag(word_id,sense_id,tag_id))
