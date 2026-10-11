"""Sonar Radar Pro data layer. All queries are owner-scoped and parameterized.
Schema changes are additive; no legacy user or config data is modified.
Call using asyncio.to_thread() from Telegram/web async handlers.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import re
from database import Database

SCHEMA = (
 """CREATE TABLE IF NOT EXISTS pro_favorites (
 owner_id BIGINT NOT NULL, resource_type VARCHAR(12) NOT NULL CHECK(resource_type IN ('server','config')),
 resource_id INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(owner_id,resource_type,resource_id))""",
 """CREATE TABLE IF NOT EXISTS pro_tags (
 owner_id BIGINT NOT NULL,resource_type VARCHAR(12) NOT NULL CHECK(resource_type IN ('server','config')),
 resource_id INTEGER NOT NULL,tag VARCHAR(40) NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW(),
 PRIMARY KEY(owner_id,resource_type,resource_id,tag))""",
 """CREATE TABLE IF NOT EXISTS pro_metrics (
 id BIGSERIAL PRIMARY KEY,owner_id BIGINT NOT NULL,config_id INTEGER NOT NULL,
 region VARCHAR(80) NOT NULL,ok BOOLEAN NOT NULL,ping DOUBLE PRECISION,jitter DOUBLE PRECISION,
 down_mbps DOUBLE PRECISION,up_mbps DOUBLE PRECISION,measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
 """CREATE INDEX IF NOT EXISTS pro_metrics_lookup ON pro_metrics(owner_id,config_id,measured_at DESC)""",
 """CREATE TABLE IF NOT EXISTS pro_incidents (
 id BIGSERIAL PRIMARY KEY,owner_id BIGINT NOT NULL,resource_type VARCHAR(12) NOT NULL,
 resource_id INTEGER NOT NULL,kind VARCHAR(50) NOT NULL,title VARCHAR(240) NOT NULL,
 severity VARCHAR(12) NOT NULL DEFAULT 'warning',status VARCHAR(12) NOT NULL DEFAULT 'open',
 occurrences INTEGER NOT NULL DEFAULT 1,opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),resolved_at TIMESTAMPTZ,ack_by BIGINT)""",
 """CREATE UNIQUE INDEX IF NOT EXISTS pro_incident_active_unique
 ON pro_incidents(owner_id,resource_type,resource_id,kind) WHERE status <> 'resolved'""",
 """CREATE INDEX IF NOT EXISTS pro_incident_owner_status ON pro_incidents(owner_id,status,updated_at DESC)""",
 """CREATE TABLE IF NOT EXISTS pro_audit (
 id BIGSERIAL PRIMARY KEY,owner_id BIGINT NOT NULL,actor_id BIGINT NOT NULL,
 event VARCHAR(60) NOT NULL,target VARCHAR(120) NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
 """CREATE INDEX IF NOT EXISTS pro_audit_owner ON pro_audit(owner_id,created_at DESC)""",
 """CREATE TABLE IF NOT EXISTS pro_team (
 owner_id BIGINT NOT NULL,member_id BIGINT NOT NULL,role VARCHAR(10) NOT NULL
 CHECK(role IN ('manager','viewer')),created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(owner_id,member_id),CHECK(owner_id<>member_id))""",
 """CREATE INDEX IF NOT EXISTS pro_team_member ON pro_team(member_id)""",
 """CREATE TABLE IF NOT EXISTS pro_rules (
 id BIGSERIAL PRIMARY KEY,owner_id BIGINT NOT NULL,event VARCHAR(30) NOT NULL,
 action VARCHAR(30) NOT NULL CHECK(action IN ('notify','digest')),
 enabled BOOLEAN NOT NULL DEFAULT TRUE,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
 """CREATE TABLE IF NOT EXISTS pro_preferences (
 owner_id BIGINT PRIMARY KEY,quiet_start SMALLINT,quiet_end SMALLINT,
 daily_digest BOOLEAN NOT NULL DEFAULT FALSE,multi_probe BOOLEAN NOT NULL DEFAULT FALSE,
 last_digest_date DATE, CHECK(quiet_start IS NULL OR quiet_start BETWEEN 0 AND 23),
 CHECK(quiet_end IS NULL OR quiet_end BETWEEN 0 AND 23))""",
 """CREATE TABLE IF NOT EXISTS pro_migrations (version INTEGER PRIMARY KEY,applied_at TIMESTAMPTZ DEFAULT NOW())""",
)


def install_schema(db=None):
    db = db or Database()
    with db.get_connection() as (conn, cur):
        for stmt in SCHEMA:
            cur.execute(stmt)
        cur.execute('INSERT INTO pro_migrations(version) VALUES (5) ON CONFLICT DO NOTHING')
        conn.commit()


def _resource_table(kind):
    if kind == 'server': return 'servers'
    if kind == 'config': return 'tunnel_configs'
    raise ValueError('Unsupported resource')


class ProStore:
    def __init__(self, db=None): self.db = db or Database()

    def role(self, user_id, owner_id):
        user_id,owner_id=int(user_id),int(owner_id)
        if user_id==owner_id: return 'owner'
        row=self.db.execute('SELECT role FROM pro_team WHERE owner_id=%s AND member_id=%s',
                            (owner_id,user_id),fetch='one')
        return row['role'] if row else None

    def require(self, actor, owner, write=False):
        role=self.role(actor,owner)
        if role not in (('owner','manager') if write else ('owner','manager','viewer')):
            raise PermissionError('Not authorized for this workspace')
        return role

    def workspace(self, actor, owner=None):
        owner=int(owner or actor)
        self.require(actor,owner)
        return owner

    def resource(self,owner,kind,rid):
        table=_resource_table(kind)
        return self.db.execute(f'SELECT id,name FROM {table} WHERE owner_id=%s AND id=%s',
                               (owner,int(rid)),fetch='one')

    def summary(self, actor, owner=None):
        owner=self.workspace(actor,owner)
        with self.db.get_connection() as (conn,cur):
            cur.execute("""SELECT COUNT(*) total,COUNT(*) FILTER(WHERE is_active=1) active,
                COUNT(*) FILTER(WHERE LOWER(last_status) IN ('offline','down','fail')) failed
                FROM servers WHERE owner_id=%s""",(owner,)); servers=cur.fetchone()
            cur.execute("""SELECT COUNT(*) total,COUNT(*) FILTER(WHERE last_status='OK') healthy,
                COUNT(*) FILTER(WHERE last_status='Fail') failed
                FROM tunnel_configs WHERE owner_id=%s AND type IN ('single','sub_item')""",(owner,)); configs=cur.fetchone()
            cur.execute("SELECT COUNT(*) n FROM pro_incidents WHERE owner_id=%s AND status<>'resolved'",(owner,))
            inc=cur.fetchone()['n']
            cur.execute("SELECT MAX(measured_at) last FROM pro_metrics WHERE owner_id=%s",(owner,))
            stamp=cur.fetchone()['last']
        return {'owner_id':owner,'servers':dict(servers),'configs':dict(configs),
                'incidents':inc,'last_test_at':stamp.isoformat() if stamp else None}

    def list_resources(self,actor,kind,owner=None,term='',tag=None,favorites=False,page=1,per_page=12):
        owner=self.workspace(actor,owner)
        table=_resource_table(kind)
        page=max(1,min(int(page),10000));per_page=max(1,min(int(per_page),50))
        sql=f"SELECT r.id,r.name,r.last_status,{'r.ip,r.is_active,r.location_type' if kind=='server' else 'r.type,r.last_ping,r.last_jitter,r.quality_score'}, EXISTS(SELECT 1 FROM pro_favorites f WHERE f.owner_id=r.owner_id AND f.resource_type=%s AND f.resource_id=r.id) favorite FROM {table} r WHERE r.owner_id=%s"
        params=[kind,owner]
        if kind=='config':sql+=" AND r.type IN ('single','sub_item','sub_source')"
        if term:
            sql+=' AND (r.name ILIKE %s'+(' OR r.ip ILIKE %s' if kind=='server' else '')+')'
            needle='%'+term[:80].replace('%',r'\%').replace('_',r'\_')+'%'
            params.extend([needle]* (2 if kind=='server' else 1))
        if favorites:
            sql+=' AND EXISTS (SELECT 1 FROM pro_favorites f WHERE f.owner_id=r.owner_id AND f.resource_type=%s AND f.resource_id=r.id)'
            params.append(kind)
        if tag:
            sql+=' AND EXISTS (SELECT 1 FROM pro_tags t WHERE t.owner_id=r.owner_id AND t.resource_type=%s AND t.resource_id=r.id AND t.tag=%s)'
            params.extend([kind,tag[:40]])
        sql+=' ORDER BY favorite DESC,r.id DESC LIMIT %s OFFSET %s'
        params.extend([per_page,(page-1)*per_page])
        return [dict(r) for r in self.db.execute(sql,params,fetch='all')]

    def toggle_favorite(self,actor,owner,kind,rid):
        self.require(actor,owner,write=True)
        if not self.resource(owner,kind,rid):raise ValueError('Resource not found')
        with self.db.get_connection() as (conn,cur):
            cur.execute('DELETE FROM pro_favorites WHERE owner_id=%s AND resource_type=%s AND resource_id=%s RETURNING resource_id',(owner,kind,rid))
            was=cur.fetchone() is not None
            if not was:
                cur.execute('INSERT INTO pro_favorites(owner_id,resource_type,resource_id) VALUES (%s,%s,%s)',(owner,kind,rid))
            conn.commit()
        self.audit(owner,actor,'favorite_changed',f'{kind}:{rid}',str(not was))
        return not was

    def add_tag(self,actor,owner,kind,rid,tag):
        self.require(actor,owner,write=True)
        tag=tag.strip().lower()
        if not 1<=len(tag)<=32 or not re.fullmatch(r'[\w\-\u0600-\u06ff ]+',tag):raise ValueError('Invalid tag')
        if not self.resource(owner,kind,rid):raise ValueError('Resource not found')
        self.db.execute('INSERT INTO pro_tags(owner_id,resource_type,resource_id,tag) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(owner,kind,rid,tag))
        self.audit(owner,actor,'tag_added',f'{kind}:{rid}',tag)

    def tags(self,actor,owner=None):
        owner=self.workspace(actor,owner)
        return self.db.execute('SELECT tag,count(*) n FROM pro_tags WHERE owner_id=%s GROUP BY tag ORDER BY n DESC,tag LIMIT 40',(owner,),fetch='all')

    def record_metric(self,owner,config_id,region,ok,ping=None,jitter=None,down=None,up=None):
        # FK-equivalent owner validation prevents cross-tenant metric injection.
        if not self.resource(owner,'config',config_id):return False
        self.db.execute('''INSERT INTO pro_metrics(owner_id,config_id,region,ok,ping,jitter,down_mbps,up_mbps)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
                        (owner,config_id,str(region)[:80],bool(ok),ping,jitter,down,up))
        return True

    def history(self,actor,config_id,owner=None,days=7):
        owner=self.workspace(actor,owner)
        if not self.resource(owner,'config',config_id):raise PermissionError('Unknown config')
        days=max(1,min(int(days),30))
        return self.db.execute('''SELECT region,ok,ping,jitter,down_mbps,up_mbps,measured_at
          FROM pro_metrics WHERE owner_id=%s AND config_id=%s AND measured_at>NOW()-(%s*INTERVAL '1 day')
          ORDER BY measured_at DESC LIMIT 600''',(owner,config_id,days),fetch='all')

    def rankings(self,actor,owner=None,limit=10):
        owner=self.workspace(actor,owner)
        # Latest observation per region; use conservative values if no probe exists.
        q='''SELECT c.id,c.name,c.last_status,c.last_ping,c.last_jitter,c.quality_score,
           m.region,m.ok,m.ping measured_ping,m.jitter measured_jitter
           FROM tunnel_configs c LEFT JOIN LATERAL (
             SELECT region,ok,ping,jitter FROM pro_metrics
             WHERE owner_id=c.owner_id AND config_id=c.id ORDER BY measured_at DESC LIMIT 1
           ) m ON TRUE WHERE c.owner_id=%s AND c.type IN ('single','sub_item')
           ORDER BY c.id DESC LIMIT 300'''
        rows=self.db.execute(q,(owner,),fetch='all')
        from pro_scoring import score_config
        results=[]
        for r in rows:
            ok=r['ok'] if r['ok'] is not None else r['last_status']=='OK'
            ping=r['measured_ping'] if r['measured_ping'] is not None else r['last_ping']
            jitter=r['measured_jitter'] if r['measured_jitter'] is not None else r['last_jitter']
            value=score_config(ping,jitter,ok)
            results.append({'id':r['id'],'name':r['name'],'score':value,'ping':ping,'jitter':jitter,
                            'status':r['last_status'],'region':r['region'] or 'legacy'})
        return sorted(results,key=lambda r:r['score'],reverse=True)[:max(1,min(30,int(limit)))]

    def incident(self,owner,kind,rid,event,title,severity='warning',active=True):
        _resource_table(kind)
        if not self.resource(owner,kind,rid):return None
        with self.db.get_connection() as (conn,cur):
            if active:
                cur.execute('''INSERT INTO pro_incidents(owner_id,resource_type,resource_id,kind,title,severity)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,resource_type,resource_id,kind)
                WHERE status <> 'resolved' DO UPDATE SET occurrences=pro_incidents.occurrences+1,
                updated_at=NOW(),severity=EXCLUDED.severity RETURNING id,occurrences''',
                (owner,kind,rid,event,title[:240],severity))
            else:
                cur.execute('''UPDATE pro_incidents SET status='resolved',resolved_at=NOW(),updated_at=NOW()
                     WHERE owner_id=%s AND resource_type=%s AND resource_id=%s AND kind=%s
                     AND status<>'resolved' RETURNING id,occurrences''',(owner,kind,rid,event))
            row=cur.fetchone();conn.commit();return dict(row) if row else None

    def incidents(self,actor,owner=None,status='open',limit=20):
        owner=self.workspace(actor,owner)
        sql='SELECT id,resource_type,resource_id,kind,title,severity,status,occurrences,opened_at,updated_at FROM pro_incidents WHERE owner_id=%s'
        params=[owner]
        if status in ('open','acknowledged','resolved'):sql+=' AND status=%s';params.append(status)
        elif status!='all':sql+=" AND status<>'resolved'"
        sql+=' ORDER BY updated_at DESC LIMIT %s';params.append(max(1,min(100,int(limit))))
        return self.db.execute(sql,params,fetch='all')

    def acknowledge(self,actor,owner,incident_id):
        self.require(actor,owner,write=True)
        result=self.db.execute("UPDATE pro_incidents SET status='acknowledged',ack_by=%s,updated_at=NOW() WHERE id=%s AND owner_id=%s AND status='open' RETURNING id",(actor,incident_id,owner),fetch='one')
        if result:self.audit(owner,actor,'incident_ack',str(incident_id))
        return bool(result)

    def audit(self,owner,actor,event,target='',detail=''):
        # Do not store credentials, links or full command text in audit details.
        self.db.execute('INSERT INTO pro_audit(owner_id,actor_id,event,target,detail) VALUES(%s,%s,%s,%s,%s)',(owner,actor,event[:60],str(target)[:120],str(detail)[:200]))

    def audit_rows(self,actor,owner=None):
        owner=self.workspace(actor,owner)
        return self.db.execute('SELECT actor_id,event,target,detail,created_at FROM pro_audit WHERE owner_id=%s ORDER BY id DESC LIMIT 40',(owner,),fetch='all')

    def preferences(self,actor,owner=None):
        owner=self.workspace(actor,owner)
        row=self.db.execute('SELECT * FROM pro_preferences WHERE owner_id=%s',(owner,),fetch='one')
        return dict(row) if row else {'owner_id':owner,'daily_digest':False,'multi_probe':False,'quiet_start':None,'quiet_end':None}

    def set_preference(self,actor,owner,key,val):
        self.require(actor,owner,write=True)
        if key not in ('daily_digest','multi_probe','quiet_start','quiet_end'):raise ValueError('Unknown setting')
        if key in ('quiet_start','quiet_end'):
            if val is not None and not 0<=int(val)<=23:raise ValueError('Hour range: 0-23')
            val=None if val is None else int(val)
        else: val=bool(val)
        self.db.execute(f'''INSERT INTO pro_preferences(owner_id,{key}) VALUES(%s,%s)
                            ON CONFLICT(owner_id) DO UPDATE SET {key}=EXCLUDED.{key}''',(owner,val))
        self.audit(owner,actor,'preference',key,str(val))

    def digest_due(self):
        return self.db.execute('''SELECT owner_id FROM pro_preferences WHERE daily_digest=TRUE
            AND (last_digest_date IS NULL OR last_digest_date<CURRENT_DATE)''',fetch='all')

    def mark_digest(self,owner):
        self.db.execute('UPDATE pro_preferences SET last_digest_date=CURRENT_DATE WHERE owner_id=%s',(owner,))

    def team(self,actor,owner=None):
        owner=self.workspace(actor,owner)
        return self.db.execute('SELECT member_id,role,created_at FROM pro_team WHERE owner_id=%s ORDER BY member_id LIMIT 50',(owner,),fetch='all')

    def set_member(self,actor,owner,member,role):
        self.require(actor,owner)
        if actor != owner: raise PermissionError('Only workspace owner can manage team')
        member=int(member)
        if member==owner:raise ValueError('Owner cannot be added as a member')
        if role not in ('manager','viewer','remove'):raise ValueError('Role invalid')
        if role=='remove':
            self.db.execute('DELETE FROM pro_team WHERE owner_id=%s AND member_id=%s',(owner,member))
        else:
            if not self.db.get_user(member):raise ValueError('Member must start the bot first')
            self.db.execute('''INSERT INTO pro_team(owner_id,member_id,role) VALUES(%s,%s,%s)
                ON CONFLICT(owner_id,member_id) DO UPDATE SET role=EXCLUDED.role''',(owner,member,role))
        self.audit(owner,actor,'team_member',str(member),role)

    def rules(self,actor,owner=None):
        owner=self.workspace(actor,owner)
        return self.db.execute('SELECT id,event,action,enabled FROM pro_rules WHERE owner_id=%s ORDER BY id DESC LIMIT 40',(owner,),fetch='all')

    def set_rule(self,actor,owner,event,action,enabled):
        self.require(actor,owner,write=True)
        if event not in ('probe_failure','server_down','recovery'):raise ValueError('Unsupported event')
        if action not in ('notify','digest'):raise ValueError('Unsupported action')
        # Independent named rule; fail safe. No SSH or destructive operations.
        with self.db.get_connection() as(conn,cur):
            cur.execute('SELECT id FROM pro_rules WHERE owner_id=%s AND event=%s AND action=%s FOR UPDATE',
                        (owner,event,action))
            rows=cur.fetchall()
            if rows:
                cur.execute('UPDATE pro_rules SET enabled=%s WHERE owner_id=%s AND id=%s',
                            (bool(enabled),owner,rows[0]['id']))
            else:
                cur.execute('INSERT INTO pro_rules(owner_id,event,action,enabled) VALUES(%s,%s,%s,%s)',
                            (owner,event,action,bool(enabled)))
            conn.commit()
        self.audit(owner,actor,'rule',event,f'{action}:{enabled}')
        if action=='digest' and enabled:
            self.set_preference(actor,owner,'daily_digest',True)

    def should_notify(self,owner,event):
        rows=self.db.execute('SELECT action,enabled FROM pro_rules WHERE owner_id=%s AND event=%s',
                             (owner,event),fetch='all')
        if not rows:return True  # legacy notification behavior
        return any(r['action']=='notify' and r['enabled'] for r in rows)

    def cleanup(self,metrics_days=30,audit_days=90):
        with self.db.get_connection() as (conn,cur):
            cur.execute("DELETE FROM pro_metrics WHERE measured_at < NOW()-(%s*INTERVAL '1 day')",(metrics_days,))
            cur.execute("DELETE FROM pro_audit WHERE created_at < NOW()-(%s*INTERVAL '1 day')",(audit_days,))
            cur.execute("DELETE FROM pro_favorites f WHERE (resource_type='server' AND NOT EXISTS(SELECT 1 FROM servers s WHERE s.id=f.resource_id AND s.owner_id=f.owner_id)) OR (resource_type='config' AND NOT EXISTS(SELECT 1 FROM tunnel_configs c WHERE c.id=f.resource_id AND c.owner_id=f.owner_id))")
            cur.execute("DELETE FROM pro_tags t WHERE (resource_type='server' AND NOT EXISTS(SELECT 1 FROM servers s WHERE s.id=t.resource_id AND s.owner_id=t.owner_id)) OR (resource_type='config' AND NOT EXISTS(SELECT 1 FROM tunnel_configs c WHERE c.id=t.resource_id AND c.owner_id=t.owner_id))")
            conn.commit()
