"""Validated changes to the legacy dictionary, with one transaction per operation.

Django owns identity, permissions and transactions. The SQLite schema still
owns its foreign keys and uniqueness constraints; no legacy table migrations.
"""
import re
import unicodedata
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction, connections
from django.core.exceptions import ValidationError
from django.utils import timezone
from . import models
from .catalog import POS, STATUSES, ASPECTS, ANIMACIES, RELATIONS, SYMMETRIC, TAG_CATEGORIES


class BadRequest(ValueError):
    pass


def fail(message):
    raise BadRequest(message)


def fields(data, allowed):
    if not isinstance(data, dict) or set(data) - set(allowed):
        fail("Unknown or malformed fields")
    return data


def string(data, key, *, required=True, maxlen=3000):
    value = data.get(key)
    if value is None:
        if required: fail(f"{key} is required")
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value)>maxlen:
        fail(f"Invalid {key}")
    return value.strip()


def identifier(data, key, *, nullable=False):
    value=data.get(key)
    if nullable and value in (None, ""):
        return None
    if type(value) is not int or value <= 0:
        fail(f"Invalid {key}")
    return value


def word(word_id):
    obj=models.Lexeme.objects.using("lexicon").filter(pk=word_id).first()
    if not obj:
        raise LookupError("Entry not found")
    return obj


def sense(word_id, sense_id, active=False):
    q=models.Sense.objects.using("lexicon").filter(pk=sense_id,lexeme_id=word_id)
    if active: q=q.filter(active=1)
    obj=q.first()
    if obj is None:
        raise LookupError("Sense not found under this entry")
    return obj


def identity(data, current=None):
    fields(data,{"lemma","pos","entry_type","aspect","animacy","human_status","notes"})
    kind=data.get("entry_type", current.entry_type if current else "word")
    lemma=data.get("lemma",current.lemma if current else None)
    pos=data.get("pos",current.pos if current else None)
    if kind not in {"word","expression"}: fail("Invalid entry type")
    if not isinstance(lemma,str): fail("Lemma required")
    lemma=" ".join(lemma.split()).strip()
    lemma=unicodedata.normalize("NFC",lemma).replace("\u0301","").casefold()
    pattern=(r"[а-яё]+(?:[-‑][а-яё]+)*" if kind=="word" else
             r"[а-яё]+(?:[-‑][а-яё]+)*(?:[ ,]+[а-яё]+(?:[-‑][а-яё]+)*)+[.!?]?")
    if not re.fullmatch(pattern,lemma) or len(lemma)>120:
        fail("Enter a Russian word, or a multiword Russian expression")
    if not isinstance(pos,str) or pos not in POS:
        fail("Invalid part of speech")
    aspect=data.get("aspect",current.aspect if current else None)
    animacy=data.get("animacy",current.animacy if current else None)
    if pos not in {"VERB","INFN"} and "aspect" not in data: aspect=None
    if pos != "NOUN" and "animacy" not in data: animacy=None
    if aspect is not None and (aspect not in ASPECTS or pos not in {"VERB","INFN"}):
        fail("Only verbs and infinitives can have a valid aspect")
    if animacy is not None and (animacy not in ANIMACIES or pos != "NOUN"):
        fail("Only nouns can have animacy")
    return {"lemma":lemma,"pos":pos,"entry_type":kind,"aspect":aspect,"animacy":animacy}


@transaction.atomic(using="lexicon")
def create_word(data):
    values=identity(data)
    existing=models.Lexeme.objects.using("lexicon").filter(lemma=values["lemma"],pos=values["pos"]).first()
    if existing:
        if existing.entry_type!=values["entry_type"]: fail("Entry already exists with a different type")
        return {"id":existing.id,"lemma":existing.lemma,"pos":existing.pos}
    obj=models.Lexeme.objects.using("lexicon").create(
        **values, human_status="unreviewed", notes="", created_at=timezone.now().strftime("%Y-%m-%d %H:%M:%S"))
    return {"id":obj.id,"lemma":obj.lemma,"pos":obj.pos}


@transaction.atomic(using="lexicon")
def update_word(word_id,data):
    obj=word(word_id)
    fields(data,{"lemma","pos","entry_type","aspect","animacy","human_status","notes"})
    if not data: fail("Nothing to update")
    if {"lemma","pos","entry_type","aspect","animacy"} & set(data):
        values=identity(data,obj)
        if values["entry_type"] != obj.entry_type:
            if values["entry_type"]=="word" and models.ExpressionComponent.objects.using("lexicon").filter(expression_id=word_id).exists():
                fail("Remove constituents before converting expression into a word")
            if values["entry_type"]=="expression" and models.ExpressionComponent.objects.using("lexicon").filter(word_id=word_id).exists():
                fail("A word used by an expression cannot be converted")
        rels=models.Relation.objects.using("lexicon").filter(source_lexeme_id=word_id) | models.Relation.objects.using("lexicon").filter(target_lexeme_id=word_id)
        aspect_links=[r for r in rels if r.relation_type=="aspect_pair"]
        if aspect_links and values["pos"] not in {"VERB","INFN"}:
            fail("Remove aspect links before changing this verb's part of speech")
        for rel in aspect_links:
            other_id=rel.target_lexeme_id if rel.source_lexeme_id==word_id else rel.source_lexeme_id
            other=word(other_id)
            if values["aspect"] not in {"perfective","imperfective"} or {values["aspect"],other.aspect}!={"perfective","imperfective"}:
                fail("New aspect conflicts with an aspect pair")
        for key,value in values.items(): setattr(obj,key,value)
    if "human_status" in data:
        if data["human_status"] not in STATUSES: fail("Invalid review status")
        obj.human_status=data["human_status"]
    if "notes" in data:
        obj.notes=string(data,"notes",required=False,maxlen=5000)
        if obj.notes is None: fail("Notes cannot be null")
    obj.save(using="lexicon")
    return {"id":obj.id,"lemma":obj.lemma,"pos":obj.pos,"human_status":obj.human_status,
            "entry_type":obj.entry_type,"aspect":obj.aspect,"animacy":obj.animacy,"notes":obj.notes}


TABLE = {"senses":models.Sense,"examples":models.Example,"patterns":models.Pattern}
ALLOWED = {"senses":("meaning","description"),"examples":("russian","english"),"patterns":("pattern",)}


@transaction.atomic(using="lexicon")
def save_record(word_id,table,data,*,record_id=None,sense_id=None):
    word(word_id)
    if table not in TABLE: fail("Unknown record type")
    columns=ALLOWED[table]
    fields(data,columns)
    values={k:string(data,k,required=i==0) or "" for i,k in enumerate(columns)}
    if table=="senses":
        parent={"lexeme_id":word_id}
    else:
        if sense_id is None: fail("Parent sense required")
        sense(word_id,sense_id,active=True)
        parent={"sense_id":sense_id}
    q=TABLE[table].objects.using("lexicon")
    if record_id is not None:
        obj=q.filter(pk=record_id,**parent).first()
        if not obj: raise LookupError("Record not found under this sense")
        for k,v in values.items(): setattr(obj,k,v)
        obj.save(using="lexicon")
    else:
        obj=q.create(**parent,**values)
    return {"id":obj.id,**parent,**values,"active":obj.active}


@transaction.atomic(using="lexicon")
def set_active(word_id,table,record_id,active):
    if table not in TABLE: fail("Invalid record type")
    if type(active) is not bool: fail("active must be boolean")
    word(word_id)
    q=TABLE[table].objects.using("lexicon")
    if table=="senses": q=q.filter(lexeme_id=word_id)
    else: q=q.filter(sense_id__in=models.Sense.objects.using("lexicon").filter(lexeme_id=word_id).values("id"))
    if not q.filter(pk=record_id).update(active=int(active)):
        raise LookupError("Record not found under this entry")
    return {"id":record_id,"active":int(active)}


@transaction.atomic(using="lexicon")
def attach_tag(word_id,sense_id,data):
    sense(word_id,sense_id)
    fields(data,{"name","category"})
    category=string(data,"category",maxlen=30)
    if category not in TAG_CATEGORIES: fail("Invalid tag category")
    name=string(data,"name",maxlen=48).casefold()
    tag,_=models.Tag.objects.using("lexicon").get_or_create(name=name,category=category)
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("INSERT OR IGNORE INTO sense_tags(sense_id,tag_id) VALUES(%s,%s)",[sense_id,tag.id])
    return {"id":tag.id,"name":tag.name,"category":tag.category}


@transaction.atomic(using="lexicon")
def detach_tag(word_id,sense_id,tag_id):
    sense(word_id,sense_id)
    with connections["lexicon"].cursor() as cursor:
        cursor.execute("DELETE FROM sense_tags WHERE sense_id=%s AND tag_id=%s",[sense_id,tag_id])
        if not cursor.rowcount: raise LookupError("Tag not attached to this sense")
    return {"removed":True}


@transaction.atomic(using="lexicon")
def save_relation(word_id,data,relation_id=None):
    fields(data,{"target_lexeme_id","relation_type","source_sense_id","target_sense_id","notes"})
    own=word(word_id)
    other=word(identifier(data,"target_lexeme_id"))
    if own.id==other.id: fail("Cannot link an entry to itself")
    kind=string(data,"relation_type",maxlen=20)
    if kind not in RELATIONS: fail("Unknown relationship type")
    if kind=="aspect_pair" and not (own.pos in {"VERB","INFN"} and other.pos in {"VERB","INFN"}
           and {own.aspect,other.aspect}=={"perfective","imperfective"}):
        fail("Aspect pairs require verbs with opposite known aspects")
    own_sid=identifier(data,"source_sense_id",nullable=True)
    other_sid=identifier(data,"target_sense_id",nullable=True)
    if own_sid: sense(word_id,own_sid)
    if other_sid: sense(other.id,other_sid)
    old=None
    if relation_id is not None:
        old=models.Relation.objects.using("lexicon").filter(pk=relation_id).first()
        if old is None or word_id not in (old.source_lexeme_id,old.target_lexeme_id):
            raise LookupError("Relationship not attached to this entry")
    source,target=word_id,other.id
    if (old is not None and old.relation_type=="derivation" and kind=="derivation"
            and old.target_lexeme_id==word_id):
        source,target=target,source
        own_sid,other_sid=other_sid,own_sid
    if kind in SYMMETRIC and source>target:
        source,target=target,source
        own_sid,other_sid=other_sid,own_sid
    if old is None:
        obj=models.Relation.objects.using("lexicon").create(source_lexeme_id=source,
             target_lexeme_id=target, relation_type=kind,
             source_sense_id=own_sid,target_sense_id=other_sid,
             notes=string(data,"notes",required=False,maxlen=3000) or "")
    else:
        old.source_lexeme_id=source;old.target_lexeme_id=target;old.relation_type=kind
        old.source_sense_id=own_sid;old.target_sense_id=other_sid
        old.notes=string(data,"notes",required=False,maxlen=3000) or ""
        old.save(using="lexicon")
        obj=old
    return {"id":obj.id,"source_lexeme_id":obj.source_lexeme_id,
            "target_lexeme_id":obj.target_lexeme_id,"relation_type":obj.relation_type,
            "source_sense_id":obj.source_sense_id,"target_sense_id":obj.target_sense_id,"notes":obj.notes}


@transaction.atomic(using="lexicon")
def remove_relation(word_id,relation_id):
    obj=models.Relation.objects.using("lexicon").filter(pk=relation_id).first()
    if obj is None or word_id not in (obj.source_lexeme_id,obj.target_lexeme_id):
        raise LookupError("Relation not found under this entry")
    obj.delete(using="lexicon")
    return {"removed":True}


@transaction.atomic(using="lexicon")
def save_component(word_id,data,component_id=None):
    fields(data,{"word_id","position","surface","notes"})
    expression=word(word_id)
    target=word(identifier(data,"word_id"))
    if expression.entry_type!="expression" or target.entry_type!="word":
        fail("An expression can only contain word entries")
    position=identifier(data,"position")
    values={"expression_id":word_id,"word_id":target.id,"position":position,
            "surface":string(data,"surface",required=False,maxlen=120) or "",
            "notes":string(data,"notes",required=False,maxlen=3000) or ""}
    q=models.ExpressionComponent.objects.using("lexicon")
    if component_id is not None:
        obj=q.filter(pk=component_id,expression_id=word_id).first()
        if not obj: raise LookupError("Constituent not attached to this expression")
        for k,v in values.items(): setattr(obj,k,v)
        obj.save(using="lexicon")
    else: obj=q.create(**values)
    return {"id":obj.id,**values}


@transaction.atomic(using="lexicon")
def remove_component(word_id,component_id):
    obj=models.ExpressionComponent.objects.using("lexicon").filter(pk=component_id,expression_id=word_id).first()
    if not obj: raise LookupError("Constituent not attached to this expression")
    obj.delete(using="lexicon")
    return {"removed":True}


@transaction.atomic(using="lexicon")
def save_external_link(word_id,data,link_id=None):
    word(word_id)
    fields(data,{"label","url"})
    label=string(data,"label",maxlen=80)
    url=string(data,"url",maxlen=2048)
    if any(ch.isspace() or ord(ch)<32 or ord(ch)==127 for ch in url):
        fail("URL cannot contain spaces or controls")
    try:
        parsed=urlsplit(url)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        _port=parsed.port
    except ValueError:
        fail("Only absolute HTTP(S) URLs without credentials are allowed")
    q=models.ExternalLink.objects.using("lexicon")
    if link_id is None:
        obj=q.create(lexeme_id=word_id,label=label,url=url)
    else:
        obj=q.filter(pk=link_id,lexeme_id=word_id).first()
        if not obj: raise LookupError("Link not attached to entry")
        obj.label=label;obj.url=url;obj.save(using="lexicon")
    return {"id":obj.id,"lexeme_id":word_id,"label":label,"url":url}


@transaction.atomic(using="lexicon")
def remove_external_link(word_id,link_id):
    obj=models.ExternalLink.objects.using("lexicon").filter(pk=link_id,lexeme_id=word_id).first()
    if obj is None: raise LookupError("Link not attached to entry")
    obj.delete(using="lexicon")
    return {"removed":True}
