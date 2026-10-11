"""Bounded multi-region probes, incident lifecycle and opt-in digest jobs.
Never executes remote shell commands. DB and scoring work run off asyncio loop.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
import hashlib
from datetime import datetime,timezone
from pro_store import ProStore
from pro_scoring import likely_cause,score_config
from tunnel_logic import tunnel_manager
from settings import SUPER_ADMIN_ID

log=logging.getLogger(__name__)
store=ProStore()
_RUNNING=set()
_CURSOR={}
_USER_CURSOR=0


def _snapshot():
    with store.db.get_connection() as(conn,cur):
        cur.execute('''SELECT s.id,s.ip,s.ws_port,s.password,s.name,s.location_type,s.owner_id
                       FROM servers s WHERE s.is_monitor_node=1 AND s.is_active=1
                       ORDER BY s.id LIMIT 8''')
        monitors=cur.fetchall()
        cur.execute('''SELECT p.owner_id FROM pro_preferences p JOIN users u ON u.user_id=p.owner_id
            WHERE p.multi_probe=TRUE AND u.is_banned=0 ORDER BY p.owner_id LIMIT 100''')
        users=[r['owner_id'] for r in cur.fetchall()]
        return monitors,users


def _select_configs(uid):
    with store.db.get_connection() as (conn,cur):
        cur.execute("SELECT COUNT(*) n FROM tunnel_configs WHERE owner_id=%s AND type IN ('single','sub_item')",(uid,));n=cur.fetchone()['n']
        if not n:return []
        limit=min(8,n);offset=_CURSOR.get(uid,0)%n
        cur.execute('''SELECT id,link FROM tunnel_configs
                       WHERE owner_id=%s AND type IN ('single','sub_item')
                       ORDER BY id LIMIT %s OFFSET %s''',(uid,limit,offset))
        rows=cur.fetchall()
        if len(rows)<limit:
            cur.execute('''SELECT id,link FROM tunnel_configs
                           WHERE owner_id=%s AND type IN ('single','sub_item')
                           ORDER BY id LIMIT %s''',(uid,limit-len(rows)))
            rows+=cur.fetchall()
        _CURSOR[uid]=(offset+len(rows))%n
        return rows


def _parse_speed(v):
    try:
        if isinstance(v,(int,float)):return max(0,float(v))
        m=re.match(r'^\s*(\d+(?:\.\d+)?)\s*(k|m|g)?bps',str(v),re.I)
        if not m:return None
        return float(m.group(1))*{'k':.001,'m':1,'g':1000,None:1}[m.group(2).lower() if m.group(2) else None]
    except (ValueError,OverflowError):return None


def _record(uid,cid,region,data):
    ok=isinstance(data,dict) and data.get('status')=='OK'
    try:ping=float(data.get('ping') or 0) if ok else None
    except (ValueError,TypeError):ping=None
    try:jitter=float(data.get('jitter') or 0) if ok else None
    except (ValueError,TypeError):jitter=None
    store.record_metric(uid,cid,region,ok,ping,jitter,
                        _parse_speed(data.get('down')) if ok else None,
                        _parse_speed(data.get('up')) if ok else None)
    with store.db.get_connection() as(conn,cur):
        cur.execute('''SELECT ok FROM pro_metrics WHERE owner_id=%s AND config_id=%s AND region=%s
                       ORDER BY id DESC LIMIT 2''',(uid,cid,region))
        latest=cur.fetchall()
    # Two consecutive failures required to raise; first success resolves.
    incident_key='probe_'+hashlib.sha256(region.encode()).hexdigest()[:12]
    if ok:
        return store.incident(uid,'config',cid,incident_key,f'اختلال کانفیگ #{cid}',active=False)
    if len(latest)>=2 and not latest[0]['ok'] and not latest[1]['ok']:
        return store.incident(uid,'config',cid,incident_key,f'اختلال کانفیگ #{cid} از {region}',severity='warning')
    return None


def quiet_now(prefs):
    a,b=prefs.get('quiet_start'),prefs.get('quiet_end')
    if a is None or b is None or a==b:return False
    hour=datetime.now(timezone.utc).hour
    return a<=hour<b if a<b else hour>=a or hour<b

async def _do_probe(uid,cfg,monitor,sem,user_sem,context=None):
    async with user_sem:
        async with sem:
            try:
                ok,data=await asyncio.wait_for(tunnel_manager._test_via_ws(monitor,cfg['link'],size=.25,timeout=25),timeout=32)
                result=data if ok and isinstance(data,dict) else {'status':'Fail'}
            except Exception:
                result={'status':'Fail'}
            region=f"{monitor.get('location_type') or 'unknown'}:{monitor.get('name') or monitor['id']}:{monitor['id']}"[:80]
            try:
                incident=await asyncio.to_thread(_record,uid,cfg['id'],region,result)
                if context and incident and (incident['occurrences']==1 or result.get('status')=='OK'):
                    pref=await asyncio.to_thread(store.preferences,uid)
                    event='recovery' if result.get('status')=='OK' else 'probe_failure'
                    notify=await asyncio.to_thread(store.should_notify,uid,event)
                    if not quiet_now(pref) and notify:
                        if result.get('status')=='OK':
                            await context.bot.send_message(uid,f'✅ بازیابی کانفیگ #{cfg["id"]} در {region} تأیید شد.')
                        else:
                            await context.bot.send_message(uid,f'🚨 هشدار سونار: کانفیگ #{cfg["id"]} دو بار متوالی از {region} ناموفق بود.')
            except Exception:log.exception('Probe persistence error user=%s config=%s',uid,cfg['id'])


async def multi_probe_job(context):
    if 'probe' in _RUNNING:return
    _RUNNING.add('probe')
    try:
        monitors,users=await asyncio.to_thread(_snapshot)
        if not monitors or not users:return
        # Bound backlog per cycle and rotate the owner batch for fairness.
        global _USER_CURSOR
        start=_USER_CURSOR%len(users)
        total=len(users)
        users=(users+users)[start:start+min(10,total)]
        _USER_CURSOR=(start+len(users))%total
        global_sem=asyncio.Semaphore(6)
        # Round robin users: don't let one owner's batch block every other owner.
        user_jobs=[]
        for uid in users:
            allowed,_=await asyncio.to_thread(store.db.check_access,uid)
            if not allowed:continue
            configs=await asyncio.to_thread(_select_configs,uid)
            if not configs:continue
            user_sem=asyncio.Semaphore(2)
            permitted=[m for m in monitors if m['owner_id'] in (uid,SUPER_ADMIN_ID)][:2]
            if not permitted:continue
            user_jobs.append((uid,configs,user_sem,permitted))
        # Limit to 2 regions for bounded cost; labels originate from configured monitor nodes.
        workers=[]
        for j in range(max((len(configs) for _,configs,_,_ in user_jobs),default=0)):
            for uid,configs,user_sem,permitted in user_jobs:
                if j<len(configs):
                    for monitor in permitted:
                        workers.append(asyncio.create_task(_do_probe(uid,configs[j],monitor,global_sem,user_sem,context)))
        if workers:await asyncio.gather(*workers,return_exceptions=True)
    except Exception:log.exception('Multi region probe job failed')
    finally:_RUNNING.remove('probe')


async def digest_job(context):
    if 'digest' in _RUNNING:return
    _RUNNING.add('digest')
    try:
        rows=await asyncio.to_thread(store.digest_due)
        for r in rows:
            uid=r['owner_id']
            try:
                allowed,_=await asyncio.to_thread(store.db.check_access,uid)
                if not allowed:continue
                pref=await asyncio.to_thread(store.preferences,uid)
                if quiet_now(pref):continue
                data=await asyncio.to_thread(store.summary,uid)
                c=data['configs'];s=data['servers']
                msg=(f'📊 گزارش روزانه سونار\n🖥 سرور: {s["active"]}/{s["total"]} فعال\n'
                     f'🧩 کانفیگ: {c["healthy"]}/{c["total"]} سالم\n'
                     f'🚨 رخداد باز: {data["incidents"]}')
                await context.bot.send_message(uid,msg)
                await asyncio.to_thread(store.mark_digest,uid)
            except Exception:log.exception('Daily digest failed for %s',uid)
    finally:_RUNNING.remove('digest')

async def cleanup_job(context):
    try:await asyncio.to_thread(store.cleanup)
    except Exception:log.exception('Pro retention cleanup failed')
