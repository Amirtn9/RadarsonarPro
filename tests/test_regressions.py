"""Offline regression tests for the critical 4.3.1 fixes.

Run: python -m pytest -q tests
Full Telegram/Postgres/SSH integration still requires a deployed staging system.
"""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import textwrap
import types

ROOT = Path(__file__).resolve().parents[1]


def test_handlers_and_source_compile():
    for f in ROOT.rglob('*.py'):
        compile(f.read_text(encoding='utf-8'), str(f), 'exec')
    from_module = ast.parse((ROOT/'dispatcher.py').read_text())
    assert any(isinstance(n, ast.ImportFrom) and n.module == 'bot_logic_mod'
               and any(a.name == 'servers' for a in n.names) for n in from_module.body)
    module = ast.parse((ROOT/'bot_logic_mod'/'servers.py').read_text())
    assert any(isinstance(n, ast.AsyncFunctionDef) and n.name == 'get_custom_ws_port'
               for n in module.body)


def test_ssh_failure_returns_false_and_closes_client():
    module = ast.parse((ROOT/'core.py').read_text())
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name=='ServerMonitor')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name=='_run_ssh_command')
    class FakeStream:
        channel = types.SimpleNamespace(recv_exit_status=lambda: 17)
        def read(self): return b'unexpected failure'
    class FakeClient:
        def __init__(self): self.closed = False
        def exec_command(self, command, timeout): return None, FakeStream(), FakeStream()
        def close(self): self.closed = True
    c = FakeClient()
    source = 'class ServerMonitor:\n    get_ssh_client = staticmethod(lambda *args: CLIENT)\n'
    source += textwrap.indent(ast.unparse(fn), '    ')
    scope = {'CLIENT':c, 'paramiko':types.SimpleNamespace(AuthenticationException=Exception)}
    exec(source, scope)
    ok, detail = scope['ServerMonitor']._run_ssh_command('127.0.0.1',22,'u','p','false')
    assert not ok and 'exit=17' in detail and c.closed


def _load_isolated_tunnel(monkeypatch):
    def fake_module(name, **bindings):
        m = types.ModuleType(name)
        vars(m).update(bindings)
        monkeypatch.setitem(sys.modules, name, m)
        return m
    fake_module('psycopg2')
    fake_module('psycopg2.extras', execute_values=lambda *args:None)
    fake_module('telegram', Update=object, InlineKeyboardButton=object, InlineKeyboardMarkup=object)
    fake_module('telegram.ext', ContextTypes=types.SimpleNamespace(DEFAULT_TYPE=object),
                ConversationHandler=types.SimpleNamespace(END=-1))
    fake_module('keyboard')
    fake_module('database', Database=lambda: object())
    fake_module('core', extract_safe_json=None, sec=types.SimpleNamespace(decrypt=lambda x:x), ServerMonitor=object)
    async def direct_call(fn,*args): return fn(*args)
    fake_module('runtime', run_sync=direct_call)
    fake_module('settings', AGENT_PORT=8181)
    spec = importlib.util.spec_from_file_location('sonar_isolated_test_tunnel', ROOT/'tunnel_logic.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_subscription_fetch_keeps_previous_items(monkeypatch):
    mod = _load_isolated_tunnel(monkeypatch)
    t = mod.TunnelLogic()
    calls = []
    async def failed_fetch(*args): return False, 'connection refused', None
    t._fetch_sub_links = failed_fetch
    t._bulk_save_sub_items = lambda *args: calls.append(args)
    result = asyncio.run(t.process_sub_async(10,{'name':'same','link':'https://sub.example','id':101}, {}))
    assert result[0].startswith('❌') and not calls


def test_successful_subscription_swap_has_parent_and_owner(monkeypatch):
    mod = _load_isolated_tunnel(monkeypatch)
    t = mod.TunnelLogic()
    saved=[]
    t._bulk_save_sub_items=lambda uid, parent, rows:(saved.append((uid,parent,rows)) or True)
    t._save_sub_info=lambda *args:None
    async def fetch(*args):return True, [{'name':'one', 'link':'vless://example'}], {'total':1}
    async def tested(*args, **kwargs):return True, {'status':'OK','ping':22,'score':8}
    t._fetch_sub_links=fetch
    t._test_via_ws=tested
    async def run():
        return await t.process_sub_async(13, {'name':'identical','link':'https://sub.example','id':71}, {})
    report=asyncio.run(run())
    assert len(saved)==1 and saved[0][0:2]==(13,71)
    assert saved[0][2][0][0:3]==(13,71,'sub_item')
    assert len(report)==1


def test_fair_semaphore_never_reserves_global_slots_while_waiting_for_user(monkeypatch):
    mod=_load_isolated_tunnel(monkeypatch)
    t=mod.TunnelLogic()
    t._bulk_save_sub_items=lambda *args:True
    events=[]
    active={1:0,2:0}
    async def fetch(*args):
        return True,[{'name':str(x),'link':'vless://'+str(x)} for x in range(20)],None
    async def test(_monitor, link, **kw):
        uid=int(_monitor['uid'])
        active[uid]+=1
        events.append((uid, active[uid]))
        assert active[uid] <= mod.PER_USER_TEST_LIMIT
        await asyncio.sleep(.002)
        active[uid]-=1
        return True,{'status':'OK','ping':17,'score':9}
    t._fetch_sub_links=fetch
    t._test_via_ws=test
    async def run():
        await asyncio.gather(t.process_sub_async(1, {'name':'n','link':'https://a','id':1},{'uid':1}),
                             t.process_sub_async(2, {'name':'n','link':'https://b','id':2},{'uid':2}))
    asyncio.run(run())
    # Both users get time before the first user's whole 20-item backlog drains.
    assert events[0][0] == 1
    assert any(uid == 2 for uid, _ in events[:10])


def test_authenticated_agent_disables_remote_shell():
    import websockets
    import monitor_agent
    async def run():
        monitor_agent.AGENT_TOKEN = 'a'*48
        async with websockets.serve(monitor_agent.ws_handler,'127.0.0.1',0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f'ws://127.0.0.1:{port}') as ws:
                await ws.send('wrong token')
                try:
                    await ws.recv()
                except websockets.exceptions.ConnectionClosed as e:
                    assert e.rcvd.code == 4001
                else:
                    raise AssertionError('Invalid token accepted')
            async with websockets.connect(f'ws://127.0.0.1:{port}') as ws:
                await ws.send('a'*48)
                await ws.send(json.dumps({'action':'run_cmd','cmd':'id'}))
                assert json.loads(await ws.recv()) == {'error':'remote_shell_disabled'}
    asyncio.run(run())


def test_forged_admin_and_foreign_resource_callbacks_denied(monkeypatch):
    fake_tg=types.ModuleType('telegram.ext')
    fake_tg.CallbackQueryHandler=type('CallbackQueryHandler',(),{})
    fake_tg.MessageHandler=type('MessageHandler',(),{})
    fake_tg.CommandHandler=type('CommandHandler',(),{})
    monkeypatch.setitem(sys.modules,'telegram.ext',fake_tg)
    fake_settings=types.ModuleType('settings')
    fake_settings.SUPER_ADMIN_ID=777
    monkeypatch.setitem(sys.modules,'settings',fake_settings)
    class FakeDB:
        def check_access(self, uid, *args):return True, 'ok'
        def owns_resource(self, table, rid, uid):return (table,rid,uid)==('servers',4,15)
    fake_database=types.ModuleType('database')
    fake_database.Database=lambda:FakeDB()
    monkeypatch.setitem(sys.modules,'database',fake_database)
    spec=importlib.util.spec_from_file_location('sonar_secure_under_test',ROOT/'secure_handlers.py')
    sec=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sec)
    assert not sec._access_sync(15,'admin_u_ban_20','admin_user_actions')
    assert not sec._access_sync(15,'act_reboot_5','server_actions')
    assert sec._access_sync(15,'act_reboot_4','server_actions')
    assert not sec._access_sync(15,'get_sub_links_12','get_sub_links_action')
    assert sec._access_sync(777,'admin_u_ban_20','admin_user_actions')
