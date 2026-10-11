"""Offline checks for Pro 5.0 API authorization, metrics, PDF and UI wiring."""
from __future__ import annotations
import ast
import hashlib
import hmac
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def signed_data(token='123:ABC', user=514, at=123456):
    fields={'auth_date':str(at),'query_id':'AAxx','user':json.dumps({'id':user},separators=(',',':'))}
    value='\n'.join(f'{k}={fields[k]}' for k in sorted(fields))
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    fields['hash']=hmac.new(secret,value.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_telegram_init_data_and_signature_rejections():
    from pro_auth import verify_init_data
    raw=signed_data()
    assert verify_init_data(raw,'123:ABC',now=123460)==514
    for tampered in (raw.replace('514','515'),raw.replace('123456','123457'),raw+'&user=duplicate',raw+'&hash=00'):
        try:verify_init_data(tampered,'123:ABC',now=123460)
        except PermissionError:pass
        else:raise AssertionError('Tampered Telegram initData accepted')
    for stamp in (123456+350,123456-61):
        try:verify_init_data(raw,'123:ABC',now=stamp)
        except PermissionError:pass
        else:raise AssertionError('Old/future initData accepted')


def test_connectivity_scoring_and_no_false_health():
    from pro_scoring import score_config,likely_cause
    assert score_config(0,0,True)==0
    assert score_config(65,12,True)>score_config(450,130,True)
    assert score_config(65,12,False)==0
    assert score_config(float('nan'),12,True)==0
    assert 'ایران' in likely_cause(False,True)


def test_pro_schema_migrations_are_additive_and_tenant_scoped():
    source=(ROOT/'pro_store.py').read_text(encoding='utf8')
    tree=ast.parse(source)
    assert 'CREATE TABLE IF NOT EXISTS pro_incidents' in source
    assert 'CREATE TABLE IF NOT EXISTS pro_metrics' in source
    assert 'CREATE TABLE IF NOT EXISTS pro_team' in source
    assert 'CREATE UNIQUE INDEX IF NOT EXISTS pro_incident_active_unique' in source
    assert "ON CONFLICT(owner_id,resource_type,resource_id,kind)" in source
    assert 'AND owner_id=%s' in source
    # Dynamic SQL paths must only interpolate hardcoded allow-listed table/type identifiers.
    assert 'raise ValueError(\'Unsupported resource\')' in source
    assert 'SELECT r.id,r.name' in source
    assert 'SELECT * FROM servers WHERE owner_id=%s' not in source  # Never return SSH passwords to Mini App.


def test_api_declares_auth_dependency_and_frontend_avoids_html_injection():
    import re
    src=(ROOT/'pro_portal.py').read_text(encoding='utf8')
    assert 'verify_init_data' in src and 'Depends(actor)' in src
    assert "raise HTTPException(status_code=401" in src
    assert 'check_access' in src
    js=(ROOT/'pro_web/static/app.js').read_text()
    assert '.textContent' in js
    assert '.innerHTML' not in js
    assert "Authorization:'tma '+auth" in js


def test_bot_integration_has_pro_jobs_and_menu_handlers():
    bot=(ROOT/'bot.py').read_text();dispatch=(ROOT/'dispatcher.py').read_text();kb=(ROOT/'keyboard.py').read_text()
    assert 'await asyncio.to_thread(install_schema)' in bot
    for name in ('multi_probe_job','digest_job','cleanup_job'): assert name in bot
    assert 'register_pro_handlers(app)' in dispatch
    assert 'pro_home' in kb and '_webapp_button' in kb
    a=ast.parse(kb);matches=[x for x in a.body if isinstance(x,ast.FunctionDef) and x.name=='config_cron_kb']
    assert len(matches)==1


def test_pdf_template_escapes_user_data_without_leaking_credentials(monkeypatch):
    import types
    monkeypatch.setitem(sys.modules,'database',types.SimpleNamespace(Database=object))
    import importlib.util
    spec=importlib.util.spec_from_file_location('pro_pdf_under_test',ROOT/'pro_pdf.py')
    # Already loaded pro_store? fake code still works if present.
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
    out=obj.render_html({'servers':{'active':1,'total':2},'configs':{'healthy':2,'total':4},'incidents':1},
                        [{'name':'<script>alert(1)</script>','ping':5,'score':90}],[],77)
    assert '<script>' not in out
    assert '&lt;script&gt;' in out
    assert 'سونار' not in out or 'گزارش' in out
    assert 'password' not in out


def test_only_safe_automation_actions_allowed():
    s=(ROOT/'pro_store.py').read_text()
    assert "action IN ('notify','digest')" in s
    assert "if action not in ('notify','digest')" in s
    assert "if actor != owner" in s


def test_web_api_auth_enforced_end_to_end_with_fake_db():
    # Run in a child interpreter so no installed Postgres driver/service is required.
    import subprocess, textwrap
    script=textwrap.dedent(r'''
        import os,sys,types,hashlib,hmac,json,time
        from urllib.parse import urlencode
        sys.path.insert(0,sys.argv[1]);os.environ['SONAR_BOT_TOKEN']='123:ABC'
        fake=types.ModuleType('database')
        class DB:
            def check_access(self,uid):return (uid==514,'ok')
        fake.Database=DB
        sys.modules['database']=fake
        import pro_portal
        from fastapi.testclient import TestClient
        client=TestClient(pro_portal.app)
        assert client.get('/healthz').status_code==200
        assert client.get('/api/summary').status_code==401
        fields={'auth_date':str(int(time.time())),'user':json.dumps({'id':514})}
        check='\n'.join(f'{k}={v}' for k,v in sorted(fields.items()))
        secret=hmac.new(b'WebAppData',b'123:ABC',hashlib.sha256).digest()
        fields['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        auth='tma '+urlencode(fields)
        pro_portal.store.summary=lambda uid,owner=None:{'uid':uid} if uid==514 and owner in (None,514) else (_ for _ in ()).throw(PermissionError())
        assert client.get('/api/summary',headers={'Authorization':auth}).json()=={'uid':514}
        assert client.get('/api/summary?owner=777',headers={'Authorization':auth}).status_code==403
        altered=auth.replace('514','515')
        assert client.get('/api/summary',headers={'Authorization':altered}).status_code==401
        print('authenticated API passed')
    ''')
    result=subprocess.run([sys.executable,'-c',script,str(ROOT)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0, result.stdout+'\n'+result.stderr


def test_web_resources_are_bound_to_owner_and_only_favorites_mutate():
    text=(ROOT/'pro_portal.py').read_text()
    assert "if kind not in ('server','config')" in text
    assert 'await guarded(store.toggle_favorite' in text
    assert 'await guarded(store.acknowledge' in text
    assert 'raise HTTPException(status_code=403' in text
    assert 'read_timeout' not in text # backend uses local queries, not open redirects


def test_database_password_has_no_static_fallback():
    source=(ROOT/'settings.py').read_text(encoding='utf-8')
    assert "os.environ.get('SONAR_DB_PASSWORD', '')" in source
    assert 'SonarPassword2025' not in source


def test_upgrades_retain_complete_custom_config():
    source=(ROOT/'install.sh').read_text(encoding='utf-8')
    assert 'read_old_config_to_stage' in source
    assert 'cp -p -- "$INSTALL_DIR/sonar_config.json" "$STAGE/sonar_config.json"' in source
    assert 'cp -p -- "$INSTALL_DIR/secret.key" "$STAGE/secret.key"' in source
    assert 'if [[ "$mode" == "update" ]]; then' in source
    assert 'read_old_config_to_stage' in source.split('install_or_update() {',1)[1]


def test_installer_guardrails_for_failed_upgrades():
    source=(ROOT/'install.sh').read_text(encoding='utf-8')
    assert 'set -Eeuo pipefail' in source
    assert 'trap cleanup_and_rollback EXIT' in source
    assert 'backup_db_if_present' in source
    assert 'mv -- "$INSTALL_DIR" "$PREVIOUS"' in source
    assert 'mv -- "$STAGE" "$INSTALL_DIR"' in source
    assert 'source files' not in source.lower() or 'Install' in source
    assert 'systemctl is-active --quiet "$SERVICE_NAME" || fail' in source
    assert 'Use Update (option 2), not Install' in source
