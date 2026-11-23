#!/usr/bin/env python3
"""Run a disposable, full-stack Django/SQLite regression test.

Run inside the deployed image: `./manage.sh test`. It snapshots the mounted
lexicon through SQLite backup() into /tmp, creates a NEW admin database,
then tests authentication, permission boundaries, and dictionary APIs there.
Never writes to /data/lexicon or /data/admin.
"""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import sys


def copy_db(source, dest):
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro",uri=True) as original:
        with sqlite3.connect(dest) as target: original.backup(target)


def main():
    with tempfile.TemporaryDirectory(prefix='ruslex-test-') as temp:
        root=Path(temp)
        (root/'lexicon').mkdir()
        (root/'admin').mkdir()
        source=Path(os.environ.get('DATA_DIR','/data'))/'lexicon'/'lexicon.db'
        copy_db(source,root/'lexicon'/'lexicon.db')
        os.environ['DATA_DIR']=str(root)
        os.environ['DJANGO_ALLOWED_HOSTS']='testserver,localhost'
        os.environ['HTTPS_ENABLED']='0'
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','siteconf.settings')
        os.environ.setdefault('DJANGO_SECRET_KEY','test-only-never-production')
        import django
        django.setup()
        from django.core.management import call_command
        from django.contrib.auth.models import Group,User
        from django.test import Client
        from accounts.models import SiteOptions
        from dictionary import queries
        from django.db import connections
        call_command('migrate',database='default',interactive=False,verbosity=0)
        call_command('initialize_roles',verbosity=0)
        call_command('check_lexicon',verbosity=0)

        def check(condition,message):
            if not condition:raise AssertionError(message)
            print('PASS',message)
        with connections['default'].cursor() as cur:
            cur.execute("SELECT name FROM sqlite_master WHERE name='lexemes'")
            check(not cur.fetchone(),'Lexicon tables absent from admin database')
        with connections['lexicon'].cursor() as cur:
            cur.execute("SELECT name FROM sqlite_master WHERE name='auth_user'")
            check(not cur.fetchone(),'Auth tables absent from lexicon database')

        anon=Client(enforce_csrf_checks=True)
        response=anon.get('/api/auth/me')
        check(response.status_code==200,'Auth handshake')
        token=anon.cookies['csrftoken'].value
        def csrf(c):return {'HTTP_X_CSRFTOKEN':c.cookies['csrftoken'].value}
        from django.http import QueryDict
        hidden=queries.search(QueryDict('status=all'),allow_review=True)
        with connections['lexicon'].cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM lexemes')
            current_count=cur.fetchone()[0]
        check(hidden['total']==current_count,'Full search includes all entries')
        unauth=anon.patch('/api/lexemes/1',data=json.dumps({'notes':'bad'}),content_type='application/json',**csrf(anon))
        check(unauth.status_code==403,'Anonymous editing rejected')
        no_signup=anon.post('/api/auth/signup',data=json.dumps({'username':'guest1','email':'g@example.org','password':'StrongPassword!49'}),content_type='application/json',**csrf(anon))
        check(no_signup.status_code==403,'Registration defaults disabled')
        hidden_id=next(x['id'] for x in queries.legacy_rows("SELECT id FROM lexemes WHERE human_status='hidden' ORDER BY id"))
        check(anon.get(f'/api/lexemes/{hidden_id}').status_code==404,'Hidden entry inaccessible anonymously')
        public=anon.get('/api/lexemes?q=read')
        check(public.status_code==200,'English search succeeds')
        check(public.json()['total']>0,'English search returns matches')
        clean=anon.get('/api/lexemes').json()
        check(all(i['human_status']!='hidden' for i in clean['items']),'Hidden entries excluded from default search')
        fixtures=json.loads((Path(__file__).resolve().parents[1]/'tests'/'v3_search_fixtures.json').read_text())
        if current_count != 1710:
            print('SKIP original v3 search fixtures: installed dictionary count differs from reference')
        for query,expected in (fixtures.items() if current_count == 1710 else []):
            params=QueryDict('',mutable=True); params['q']=query
            result=queries.search(params)
            # Compare observed top results and totals with the v3 reference implementation.
            check(result['total']==expected['total'] and [x['id'] for x in result['items'][:15]]==expected['ids'],f'v3 search parity {query!r}')
        reviewer=User.objects.create_user('reviewer',password='StrongPassword!49')
        reviewer.groups.add(Group.objects.get(name='Reviewer'))
        editor=User.objects.create_user('editor',password='StrongPassword!49')
        editor.groups.add(Group.objects.get(name='Editor'))
        client=Client(enforce_csrf_checks=True);client.force_login(reviewer);client.get('/api/auth/me')
        check(client.patch('/api/lexemes/1',data=json.dumps({'notes':'no'}),content_type='application/json',**csrf(client)).status_code==403,'Reviewer cannot edit notes')
        check(client.patch('/api/lexemes/1',data=json.dumps({'human_status':'followup'}),content_type='application/json',**csrf(client)).status_code==200,'Reviewer can update review status')
        edit=Client(enforce_csrf_checks=True);edit.force_login(editor);edit.get('/api/auth/me')
        check(edit.patch('/api/lexemes/1',data=json.dumps({'notes':'smoke test'}),content_type='application/json',**csrf(edit)).status_code==200,'Editor can edit entry')
        public_note=anon.get('/api/lexemes/1')
        check(public_note.status_code==200 and public_note.json()['notes']=='smoke test',
              'Entry notes are visible to anonymous readers')
        with connections['lexicon'].cursor() as cur:
            cur.execute("SELECT s.id FROM senses s WHERE s.lexeme_id=1 AND s.active=1 ORDER BY s.id LIMIT 1")
            sense_id=cur.fetchone()[0]
            cur.execute("""SELECT t.id,t.name,t.category FROM tags t
                WHERE NOT EXISTS (SELECT 1 FROM sense_tags st WHERE st.sense_id=%s AND st.tag_id=t.id)
                ORDER BY t.id LIMIT 1""", [sense_id])
            tag_id, tag_name, tag_category=cur.fetchone()
        tagged=edit.post(f'/api/lexemes/1/senses/{sense_id}/tags',
            data=json.dumps({'name':tag_name,'category':tag_category}),
            content_type='application/json',**csrf(edit))
        check(tagged.status_code==201 and tagged.json()['id']==tag_id,
              'Adding an existing tag reuses its dictionary ID')
        check(any(tag['id']==tag_id for sense in anon.get('/api/lexemes/1').json()['senses']
                  for tag in sense['tags']), 'Existing tag visible on the updated sense')
        SiteOptions.objects.filter(pk=1).update(registration_open=True)
        signup=anon.post('/api/auth/signup',data=json.dumps({'username':'guest1','email':'g@example.org','password':'StrongPassword!49'}),content_type='application/json',**csrf(anon))
        check(signup.status_code==201,'Admin-controlled registration switch')
        check(not User.objects.get(username='guest1').groups.exists(),'Signup receives no editing roles')
        print('ALL DJANGO SMOKE TESTS PASSED; the live databases were not touched')

if __name__=='__main__':
    try:main()
    except Exception as err:
        import traceback
        traceback.print_exc()
        sys.exit(1)
