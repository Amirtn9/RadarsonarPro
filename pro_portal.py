"""Optional Telegram Mini App API.
Deploy behind an HTTPS reverse proxy; NEVER expose the API as an unauthenticated service.
Every request verifies signed Telegram initData and resource ownership.
Run: uvicorn pro_portal:app --host 127.0.0.1 --port 8090 --proxy-headers
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pro_auth import verify_init_data
from pro_store import ProStore
from database import Database

log=logging.getLogger(__name__)
BASE=Path(__file__).resolve().parent
app=FastAPI(title='Sonar Radar Pro',docs_url=None,redoc_url=None,openapi_url=None)
app.mount('/static',StaticFiles(directory=BASE/'pro_web'/'static'),name='static')
store=ProStore()


def get_bot_token():
    value=os.environ.get('SONAR_BOT_TOKEN','')
    if value:return value
    # Supports existing project config without publishing the token to the browser.
    with open(BASE/'sonar_config.json',encoding='utf-8') as f:return json.load(f).get('bot_token','')


async def actor(authorization:str=Header(default='')):
    if not authorization.startswith('tma '):raise HTTPException(status_code=401,detail='Telegram authentication required')
    try:uid=verify_init_data(authorization[4:],get_bot_token())
    except (PermissionError,ValueError,KeyError):raise HTTPException(status_code=401,detail='Invalid or expired Telegram authorization')
    try:
        allowed,_=await asyncio.to_thread(store.db.check_access,uid)
        if not allowed:raise HTTPException(status_code=403,detail='Inactive account')
    except HTTPException:raise
    except Exception:log.exception('Auth database failure');raise HTTPException(status_code=503,detail='Service unavailable')
    return uid


async def guarded(fn,*args,**kwargs):
    try:return await asyncio.to_thread(fn,*args,**kwargs)
    except PermissionError:raise HTTPException(status_code=403,detail='Not authorized')
    except ValueError:raise HTTPException(status_code=400,detail='Invalid request')


@app.middleware('http')
async def headers(request:Request,call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
    return response


@app.get('/')
async def index():return FileResponse(BASE/'pro_web'/'index.html')

@app.get('/healthz')
async def health():return {'ok':True}

@app.get('/api/summary')
async def summary(uid:int=Depends(actor),owner:int|None=None):return await guarded(store.summary,uid,owner)

@app.get('/api/resources/{kind}')
async def resources(kind:str,uid:int=Depends(actor),owner:int|None=None,q:str='',tag:str|None=None,favorites:bool=False,page:int=1):
    if kind not in ('server','config'):raise HTTPException(status_code=404)
    return await guarded(store.list_resources,uid,kind,owner, '' if q.startswith('#') else q, q[1:] if q.startswith('#') else tag, favorites,page)

@app.get('/api/rankings')
async def rankings(uid:int=Depends(actor),owner:int|None=None):return await guarded(store.rankings,uid,owner,30)

@app.get('/api/metrics/{config_id}')
async def metrics(config_id:int,uid:int=Depends(actor),owner:int|None=None,days:int=7):
    rows=await guarded(store.history,uid,config_id,owner,days)
    return [dict(r) for r in rows]

@app.get('/api/incidents')
async def incidents(uid:int=Depends(actor),owner:int|None=None,status:str='unresolved'):
    return await guarded(store.incidents,uid,owner,status)

@app.get('/api/audit')
async def audit(uid:int=Depends(actor),owner:int|None=None):return await guarded(store.audit_rows,uid,owner)

@app.get('/api/tags')
async def tags(uid:int=Depends(actor),owner:int|None=None):return await guarded(store.tags,uid,owner)

@app.get('/api/team')
async def team(uid:int=Depends(actor),owner:int|None=None):return await guarded(store.team,uid,owner)

@app.get('/api/preferences')
async def preferences(uid:int=Depends(actor),owner:int|None=None):return await guarded(store.preferences,uid,owner)

class Favorite(BaseModel):
    kind:str;rid:int=Field(gt=0);owner:int|None=None

class IncidentAction(BaseModel):
    incident_id:int=Field(gt=0);owner:int|None=None

class PreferencesUpdate(BaseModel):
    owner:int|None=None;key:str;value:bool|int|None

@app.post('/api/favorites')
async def toggle_fav(body:Favorite,uid:int=Depends(actor)):
    owner=body.owner or uid
    active=await guarded(store.toggle_favorite,uid,owner,body.kind,body.rid)
    return {'favorite':active}

@app.post('/api/incidents/ack')
async def acknowledge(body:IncidentAction,uid:int=Depends(actor)):
    return {'acknowledged':await guarded(store.acknowledge,uid,body.owner or uid,body.incident_id)}

@app.post('/api/preferences')
async def set_preferences(body:PreferencesUpdate,uid:int=Depends(actor)):
    await guarded(store.set_preference,uid,body.owner or uid,body.key,body.value)
    return {'ok':True}


@app.websocket('/api/terminal')
async def ssh_terminal(websocket: WebSocket):
    """Interactive SSH PTY. Auth and ownership are checked before SSH is opened."""
    await websocket.accept()
    client = None
    channel = None
    owner_id = None
    actor_id = None
    server_id = None
    try:
        # First frame carries signed Telegram initData; never put it in the URL.
        first = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        payload = json.loads(first)
        init_data = str(payload.get('init_data') or '')
        server_id = int(payload.get('server_id') or 0)
        actor_id = verify_init_data(init_data, get_bot_token())
        allowed, _ = await asyncio.to_thread(store.db.check_access, actor_id)
        if not allowed:
            await websocket.close(code=4403)
            return
        server = await asyncio.to_thread(Database().get_server_by_id, server_id)
        if not server:
            await websocket.close(code=4404)
            return
        owner_id = int(server.get('owner_id') or 0)
        await asyncio.to_thread(store.require, actor_id, owner_id, True)
        # Verify the resource belongs to the workspace before reading credentials.
        if not await asyncio.to_thread(store.resource, owner_id, 'server', server_id):
            await websocket.close(code=4404)
            return
        encrypted = server.get('password') or ''
        if not encrypted:
            await websocket.send_text(json.dumps({'type':'error','message':'برای این سرور رمز SSH ذخیره نشده است.'}))
            await websocket.close(code=4401)
            return
        ip = str(server.get('ip') or '')
        port = int(server.get('port') or 22)
        username = str(server.get('username') or 'root')
        if not ip or not (1 <= port <= 65535) or not username:
            await websocket.close(code=4400)
            return
        from core import ServerMonitor, sec
        password = await asyncio.to_thread(sec.decrypt, encrypted)
        client = await asyncio.to_thread(ServerMonitor.get_ssh_client, ip, port, username, password)
        transport = client.get_transport()
        if not transport or not transport.is_active():
            raise ConnectionError('SSH transport did not become active')
        channel = transport.open_session(timeout=10)
        channel.get_pty(term='xterm-256color', width=120, height=36)
        channel.invoke_shell()
        await asyncio.to_thread(store.audit, owner_id, actor_id, 'ssh_terminal_open', f'server:{server_id}', 'Interactive SSH session opened')
        await websocket.send_text(json.dumps({'type':'ready','server':str(server.get('name') or ip)}))
        while True:
            # Drain SSH output without blocking the ASGI event loop.
            if channel.recv_ready():
                chunk = await asyncio.to_thread(channel.recv, 65536)
                if not chunk:
                    break
                await websocket.send_text(chunk.decode('utf-8', 'replace'))
            if channel.recv_stderr_ready():
                chunk = await asyncio.to_thread(channel.recv_stderr, 16384)
                if chunk:
                    await websocket.send_text(chunk.decode('utf-8', 'replace'))
            try:
                incoming = await asyncio.wait_for(websocket.receive_text(), timeout=0.025)
            except asyncio.TimeoutError:
                if channel.exit_status_ready():
                    break
                continue
            try:
                message = json.loads(incoming)
            except (ValueError, TypeError):
                message = {'type':'input','data':incoming}
            kind = message.get('type')
            if kind == 'input':
                data = str(message.get('data') or '')
                if len(data) > 8192:
                    continue
                await asyncio.to_thread(channel.send, data)
            elif kind == 'resize':
                cols = max(40, min(300, int(message.get('cols') or 120)))
                rows = max(10, min(100, int(message.get('rows') or 36)))
                await asyncio.to_thread(channel.resize_pty, width=cols, height=rows)
            elif kind == 'close':
                break
    except WebSocketDisconnect:
        pass
    except (PermissionError, ValueError, KeyError, json.JSONDecodeError):
        try: await websocket.close(code=4403)
        except Exception: pass
    except Exception as exc:
        log.warning('SSH terminal failed for server_id=%s error_type=%s', server_id, type(exc).__name__)
        try:
            await websocket.send_text(json.dumps({'type':'error','message':'اتصال SSH برقرار نشد؛ تنظیمات دسترسی و Host Key را بررسی کنید.'}))
            await websocket.close(code=1011)
        except Exception: pass
    finally:
        try:
            if channel is not None: channel.close()
        except Exception: pass
        try:
            if client is not None: client.close()
        except Exception: pass
        if owner_id and actor_id and server_id:
            try:
                await asyncio.to_thread(store.audit, owner_id, actor_id, 'ssh_terminal_close', f'server:{server_id}', 'Interactive SSH session closed')
            except Exception:
                log.exception('SSH terminal audit failed')
