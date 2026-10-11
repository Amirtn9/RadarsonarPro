"""Telegram UI for Sonar Radar Pro. Uses existing secure boundary plus scoped store checks."""
from __future__ import annotations
import asyncio
import csv
import html
import io
import os
import ssl
import socket
import time
from datetime import datetime
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, InputFile
from telegram.ext import CommandHandler, CallbackQueryHandler
from secure_handlers import SecureCommandHandler, SecureCallbackQueryHandler
from pro_store import ProStore
from pro_scoring import likely_cause
from settings import SUPER_ADMIN_ID

store=ProStore()
_LAST_ACTION={}


def e(s):return html.escape(str(s),quote=False)

def kb(*rows):return M([list(row) for row in rows])

async def invoke(fn,*args,**kw):return await asyncio.to_thread(fn,*args,**kw)

async def display(update,text,markup=None):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text,reply_markup=markup,parse_mode='HTML')
        except Exception as exc:
            if 'Message is not modified' not in str(exc):raise
    else:
        await update.effective_message.reply_text(text,reply_markup=markup,parse_mode='HTML')


def nav():return [B('🏠 خانه',callback_data='main_menu'),B('📊 پیشرفته',callback_data='pro_home')]


def owned_context(update,context):
    # Workspace switch is an explicit command; default always own workspace.
    return int(context.user_data.get('pro_workspace') or update.effective_user.id)

async def safe_call(update,context,fn,*args,write=False):
    actor=update.effective_user.id;owner=owned_context(update,context)
    try:
        await invoke(store.require,actor,owner,write)
        return await invoke(fn,*args)
    except (PermissionError,ValueError) as exc:
        await display(update,'⛔ '+e(str(exc)),kb(nav()))
        return None


async def home(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    data=await safe_call(update,context,store.summary,actor,owner)
    if data is None:return
    s=data['servers'];c=data['configs'];total=s['total'] or 0;healthy=s['active'] or 0
    text=(f'📡 <b>SONAR RADAR | Pro Center</b>\n'
          f'👤 فضای کاری: <code>{owner}</code>\n'
          f'━━━━━━━━━━━━━━━━━━━━\n'
          f'🖥 سرورها: <b>{total}</b> | فعال: <b>{healthy}</b> | خطادار: <b>{s["failed"]}</b>\n'
          f'🧩 کانفیگ‌ها: <b>{c["total"]}</b> | سالم: <b>{c["healthy"]}</b>\n'
          f'🚨 رخدادهای باز: <b>{data["incidents"]}</b>\n'
          f'🕒 آخرین تست جدید: {e(data["last_test_at"] or "هنوز ثبت نشده")}\n'
          '━━━━━━━━━━━━━━━━━━━━\n'
          'از دکمه‌های زیر برای مشاهده جزئیات استفاده کنید.')
    rows=[
        [B('🖥 سرورها',callback_data='pro_list_server_1'),B('🧩 کانفیگ‌ها',callback_data='pro_list_config_1')],
        [B('⭐ علاقه‌مندی‌ها',callback_data='pro_favorites'),B('🏆 رتبه‌بندی',callback_data='pro_rank')],
        [B('🚨 مرکز رخدادها',callback_data='pro_incidents'),B('📈 گزارش کیفیت',callback_data='pro_report')],
        [B('🧠 تحلیل اختلالات',callback_data='pro_insights'),B('⚙️ قوانین',callback_data='pro_rules')],
        [B('🏷 برچسب‌ها',callback_data='pro_tags'),B('⚙️ تنظیمات هشدار',callback_data='pro_prefs')],
        [B('🔎 جست‌وجو /find',callback_data='pro_find_help'),B('👥 اعضای تیم',callback_data='pro_team')],
        [B('📜 فعالیت‌ها',callback_data='pro_audit'),B('🏠 منوی اصلی',callback_data='main_menu')],
    ]
    await display(update,text,M(rows))


async def resources(update,context):
    parts=update.callback_query.data.split('_')
    kind,page=parts[2],int(parts[3]);actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,store.list_resources,actor,kind,owner,page=page)
    if rows is None:return
    txt='🖥 <b>سرورها</b>' if kind=='server' else '🧩 <b>کانفیگ‌ها</b>'
    txt+=f' | صفحه {page}\n\n'
    buttons=[]
    for item in rows:
        icon='⭐ ' if item['favorite'] else ''
        status='🟢' if str(item['last_status']).lower() in ('online','ok') else '⚪'
        txt+=f'{status} {icon}<b>{e(item["name"][:45])}</b> #{item["id"]}\n'
        buttons.append([B(f'{"★" if item["favorite"] else "☆"} {item["id"]} | {str(item["name"])[:22]}',callback_data=f'pro_fav_{kind}_{item["id"]}_{page}')])
    if not rows:txt+='موردی ثبت نشده است.\n'
    paging=[]
    if page>1:paging.append(B('◀️ قبلی',callback_data=f'pro_list_{kind}_{page-1}'))
    if len(rows)==12:paging.append(B('بعدی ▶️',callback_data=f'pro_list_{kind}_{page+1}'))
    if paging:buttons.append(paging)
    buttons.append(nav())
    await display(update,txt,M(buttons))


async def favorite(update,context):
    _,_,kind,rid,page=update.callback_query.data.split('_');actor=update.effective_user.id;owner=owned_context(update,context)
    value=await safe_call(update,context,store.toggle_favorite,actor,owner,kind,int(rid),write=True)
    if value is None:return
    # Return to previous list without modifying Telegram's read-only callback_data.
    rows=await invoke(store.list_resources,actor,kind,owner,page=int(page))
    buttons=[]
    for item in rows:
        buttons.append([B(f'{"★" if item["favorite"] else "☆"} {item["id"]} | {str(item["name"])[:24]}',callback_data=f'pro_fav_{kind}_{item["id"]}_{page}')])
    buttons.append([B('⬅️ لیست کامل',callback_data=f'pro_list_{kind}_{page}')]);buttons.append(nav())
    await display(update,f'{"⭐ افزوده شد" if value else "☆ حذف شد"} | فهرست به‌روز شد',M(buttons))


async def favorites(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    servers=await safe_call(update,context,store.list_resources,actor,'server',owner,favorites=True,per_page=15)
    if servers is None:return
    configs=await invoke(store.list_resources,actor,'config',owner,favorites=True,per_page=15)
    txt='⭐ <b>علاقه‌مندی‌های شما</b>\n\n'
    txt+='🖥 سرورها: '+(', '.join(e(r['name'][:28]) for r in servers) if servers else 'ندارد')+'\n'
    txt+='🧩 کانفیگ‌ها: '+(', '.join(e(r['name'][:28]) for r in configs) if configs else 'ندارد')
    await display(update,txt,kb(nav()))


async def rank(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,store.rankings,actor,owner,10)
    if rows is None:return
    txt='🏆 <b>بهترین کانفیگ‌ها</b>\n'
    txt+='امتیاز تخمینی از آخرین تأخیر، جیتر و وضعیت اتصال.\n\n'
    for i,r in enumerate(rows,1):
        txt+=f'{i}. <b>{e(r["name"][:40])}</b> | {r["score"]}/100 | {r["ping"]}ms\n'
    if not rows:txt+='کانفیگی برای مقایسه وجود ندارد.'
    await display(update,txt,kb([B('📥 گزارش CSV',callback_data='pro_export_rank')],nav()))


async def incidents(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,store.incidents,actor,owner,'unresolved',20)
    if rows is None:return
    txt='🚨 <b>مرکز رخدادها</b>\n\n';buttons=[]
    for r in rows:
        txt+=f'#{r["id"]} {"🔴" if r["severity"]=="critical" else "🟠"} {e(r["title"])} | {e(r["status"])}\n'
        if r['status']=='open':buttons.append([B(f'✅ تأیید رخداد #{r["id"]}',callback_data=f'pro_ack_{r["id"]}')])
    if not rows:txt+='✅ رخداد حل‌نشده‌ای وجود ندارد.'
    buttons.append(nav())
    await display(update,txt,M(buttons))


async def ack(update,context):
    iid=int(update.callback_query.data.split('_')[-1]);actor=update.effective_user.id;owner=owned_context(update,context)
    result=await safe_call(update,context,store.acknowledge,actor,owner,iid,write=True)
    if result is None:return
    await display(update,('✅ رخداد تأیید شد.' if result else 'این رخداد قبلاً بررسی شده است.'),kb([B('🚨 بازگشت رخدادها',callback_data='pro_incidents')],nav()))


async def tags(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,store.tags,actor,owner)
    if rows is None:return
    txt='🏷 <b>برچسب‌ها</b>\n\n'+('\n'.join(f'• {e(r["tag"])} ({r["n"]})' for r in rows) if rows else 'برچسبی ندارید.')
    txt+='\n\nافزودن برچسب: <code>/tag server 12 iran</code>\nیا <code>/tag config 5 stable</code>'
    await display(update,txt,kb(nav()))


async def tag_command(update,context):
    args=context.args or []
    if len(args)<3 or args[0] not in ('server','config') or not args[1].isdigit():
        await display(update,'راهنما: <code>/tag server 12 iran</code>');return
    actor=update.effective_user.id;owner=owned_context(update,context)
    try:
        await invoke(store.add_tag,actor,owner,args[0],int(args[1]),' '.join(args[2:]))
        await display(update,'✅ برچسب با موفقیت ذخیره شد.')
    except (PermissionError,ValueError) as exc:
        await display(update,'⛔ '+e(exc))


async def prefs(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    p=await safe_call(update,context,store.preferences,actor,owner)
    if p is None:return
    text=('⚙️ <b>هشدارها و برنامه زمانی</b>\n\n'
          f'📨 گزارش روزانه: {"روشن" if p["daily_digest"] else "خاموش"}\n'
          f'🌍 بررسی چندنقطه‌ای: {"روشن" if p["multi_probe"] else "خاموش"}\n'
          f'🌙 سکوت اعلان: {p["quiet_start"] if p["quiet_start"] is not None else "ندارد"} تا '
          f'{p["quiet_end"] if p["quiet_end"] is not None else "ندارد"} (UTC)\n'
          'برای ساعت سکوت: <code>/quiet 22 7</code> و لغو: <code>/quiet off</code>')
    await display(update,text,kb(
        [B('🔔 تغییر گزارش روزانه',callback_data='pro_toggle_daily_digest')],
        [B('🌐 تغییر بررسی چندنقطه‌ای',callback_data='pro_toggle_multi_probe')],nav()))


async def toggle_pref(update,context):
    key=update.callback_query.data.removeprefix('pro_toggle_');actor=update.effective_user.id;owner=owned_context(update,context)
    if key not in ('daily_digest','multi_probe'):return
    current=await safe_call(update,context,store.preferences,actor,owner)
    if current is None:return
    # Avoid displaying repeated messages on deny. Explicitly check role here.
    try:await invoke(store.set_preference,actor,owner,key,not current[key])
    except PermissionError:await display(update,'⛔ فقط صاحب یا مدیر می‌تواند تنظیمات را تغییر دهد.');return
    await prefs(update,context)


async def quiet(update,context):
    args=context.args or [];actor=update.effective_user.id;owner=owned_context(update,context)
    try:
        if len(args)==1 and args[0]=='off':
            await invoke(store.set_preference,actor,owner,'quiet_start',None)
            await invoke(store.set_preference,actor,owner,'quiet_end',None)
        elif len(args)==2:
            start,end=int(args[0]),int(args[1]);
            if not 0<=start<=23 or not 0<=end<=23:raise ValueError('Hour must be 0..23')
            await invoke(store.set_preference,actor,owner,'quiet_start',start)
            await invoke(store.set_preference,actor,owner,'quiet_end',end)
        else:raise ValueError('Use /quiet 22 7 or /quiet off (UTC)')
        await display(update,'✅ ساعت سکوت اعلان ذخیره شد.')
    except (ValueError,PermissionError) as exc:await display(update,e(exc))


async def find_help(update,context):
    await display(update,'🔎 <b>جست‌وجو</b>\nبرای نام سرور/IP یا کانفیگ بنویسید:\n'
                  '<code>/find nginx</code>\n<code>/find 192.0</code>\n<code>/find #iran</code>\n\nاز دستور <code>/tag</code> هم برای افزودن برچسب استفاده کنید.',kb(nav()))


async def find(update,context):
    term=' '.join(context.args or []).strip()
    if not 1<=len(term)<=80:await display(update,'نمونه: <code>/find berlin</code> (حداکثر ۸۰ کاراکتر)');return
    actor=update.effective_user.id;owner=owned_context(update,context)
    search={'tag':term[1:]} if term.startswith('#') else {'term':term}
    servers=await safe_call(update,context,store.list_resources,actor,'server',owner,per_page=15,**search)
    if servers is None:return
    configs=await invoke(store.list_resources,actor,'config',owner,per_page=15,**search)
    txt=f'🔎 نتایج برای <b>{e(term)}</b>\n\n🖥 سرورها:\n'
    txt+='\n'.join(f'#{r["id"]} {e(r["name"])}' for r in servers) or 'موردی یافت نشد.'
    txt+='\n🧩 کانفیگ‌ها:\n'+('\n'.join(f'#{r["id"]} {e(r["name"])}' for r in configs) or 'موردی یافت نشد.')
    await display(update,txt[:3900],kb(nav()))


async def team(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,store.team,actor,owner)
    if rows is None:return
    txt='👥 <b>اعضای فضای کاری</b>\n\n'
    txt+='\n'.join(f'{r["member_id"]}: {e(r["role"])}' for r in rows) or 'شما تنها عضو فضای کاری هستید.'
    txt+='\n\nفقط مالک می‌تواند اعضا را مدیریت کند:\n<code>/member 123456 viewer</code>\n<code>/member 123456 manager</code>\n<code>/member 123456 remove</code>\n<code>/workspace 123456</code> برای مشاهده فضای کاری دعوت‌شده.'
    await display(update,txt,kb(nav()))


async def member(update,context):
    args=context.args or [];actor=update.effective_user.id;owner=owned_context(update,context)
    if len(args)!=2 or not args[0].isdigit():await display(update,'مثال: <code>/member 123456 viewer</code>');return
    try:await invoke(store.set_member,actor,owner,int(args[0]),args[1]);await display(update,'✅ عضویت بروزرسانی شد.')
    except (ValueError,PermissionError) as exc:await display(update,'⛔ '+e(exc))


async def workspace(update,context):
    actor=update.effective_user.id;args=context.args or []
    if not args:context.user_data.pop('pro_workspace',None);await display(update,'✅ فضای کاری شخصی فعال شد.');return
    if len(args)!=1 or not args[0].isdigit():await display(update,'مثال: <code>/workspace 123456</code>');return
    owner=int(args[0]);
    try:await invoke(store.require,actor,owner);context.user_data['pro_workspace']=owner
    except PermissionError:await display(update,'⛔ دسترسی به این فضای کاری ندارید.');return
    await home(update,context)


async def audit(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,store.audit_rows,actor,owner)
    if rows is None:return
    txt='📜 <b>تاریخچه فعالیت‌ها</b>\n\n'
    for r in rows[:20]:txt+=f'• {e(r["event"])} | {r["actor_id"]} | {e(r["target"])}\n'
    await display(update,txt or 'رکوردی موجود نیست.',kb(nav()))


async def report(update,context):
    await display(update,'📈 <b>گزارش تحلیلی</b>\nبرای دانلود گزارش کانفیگ‌ها و سرورها از CSV استفاده کنید.\n'
                  'تاریخچه کیفیت کانفیگ با دستور <code>/history ID</code> قابل مشاهده است.\n'
                  'برای تست ایمن اتصال سرور: <code>/diagnose ID</code>\nبرای تست کانفیگ: <code>/probe ID</code>',
                  kb([B('📥 دانلود گزارش کانفیگ‌ها',callback_data='pro_export_rank')],
                     [B('🖥 دریافت فهرست سرورها',callback_data='pro_export_server')],
                     [B('📄 گزارش PDF',callback_data='pro_export_pdf')],nav()))


def csv_bytes(rows,cols):
    buf=io.StringIO();wr=csv.DictWriter(buf,fieldnames=cols,extrasaction='ignore');wr.writeheader()
    for row in rows:
        wr.writerow({k: "'"+str(row.get(k,'')) if str(row.get(k,'')).lstrip().startswith(('=','+','-','@')) else row.get(k,'') for k in cols})
    return io.BytesIO(buf.getvalue().encode('utf-8-sig'))


async def export(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    kind=update.callback_query.data.removeprefix('pro_export_')
    if kind=='pdf':await pdf_report(update,context);return
    if kind=='rank':rows=await safe_call(update,context,store.rankings,actor,owner,30);cols=['id','name','score','ping','jitter','status','region']
    elif kind=='server':rows=await safe_call(update,context,store.list_resources,actor,'server',owner,per_page=50);cols=['id','name','last_status','is_active','location_type']
    else:return
    if rows is None:return
    file=csv_bytes(rows,cols)
    await update.callback_query.answer()
    await context.bot.send_document(chat_id=update.effective_chat.id,document=InputFile(file,filename=f'sonar-{kind}-{owner}.csv'),caption='📥 گزارش خروجی SONAR')


async def history(update,context):
    args=context.args or []
    if len(args)!=1 or not args[0].isdigit():await display(update,'راهنما: <code>/history 25</code>');return
    actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,store.history,actor,int(args[0]),owner,7)
    if rows is None:return
    if not rows:await display(update,'هنوز داده‌ای برای این کانفیگ ثبت نشده است.');return
    n=len(rows);ok=sum(bool(r['ok']) for r in rows)
    txt=f'📈 <b>تاریخچه ۷ روزه #{args[0]}</b>\n✅ {ok}/{n} تست موفق\n\n'
    for r in rows[:16]:
        txt+=f'{"✅" if r["ok"] else "❌"} {e(r["region"])} | {r["ping"] or "?"}ms | {r["measured_at"].strftime("%m/%d %H:%M")}\n'
    await display(update,txt,kb(nav()))


async def diagnose(update,context):
    args=context.args or []
    if len(args)!=1 or not args[0].isdigit():await display(update,'راهنما: <code>/diagnose 25</code>');return
    actor=update.effective_user.id;owner=owned_context(update,context)
    try:await invoke(store.require,actor,owner)
    except PermissionError:await display(update,'⛔ دسترسی مجاز نیست.');return
    srv=await invoke(store.db.execute,'SELECT id,name,ip,port FROM servers WHERE owner_id=%s AND id=%s',(owner,int(args[0])),fetch='one')
    if not srv:await display(update,'سرور پیدا نشد.');return
    now=time.monotonic()
    if now-_LAST_ACTION.get(('diagnose',actor),0)<30:await display(update,'⏳ حداکثر هر ۳۰ ثانیه یک تست اتصال مجاز است.');return
    _LAST_ACTION[('diagnose',actor)]=now
    results=[]
    try:
        addresses=await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(srv['ip'],int(srv['port']),type=socket.SOCK_STREAM),timeout=4)
        ips=sorted({addr[4][0] for addr in addresses})[:3]
        results.append('✅ DNS/Resolve: '+', '.join(ips))
    except (OSError,asyncio.TimeoutError):
        results.append('❌ DNS/Resolve ناموفق')
    try:
        start=time.monotonic()
        reader,writer=await asyncio.wait_for(asyncio.open_connection(srv['ip'],int(srv['port'])),timeout=5)
        elapsed=round((time.monotonic()-start)*1000)
        writer.close();await writer.wait_closed()
        results.append(f'✅ پورت TCP قابل اتصال است | {elapsed}ms')
    except (OSError,asyncio.TimeoutError) as exc:
        results.append(f'❌ اتصال TCP ناموفق: {type(exc).__name__}')
    if int(srv['port']) in (443,8443):
        try:
            ssl_ctx=ssl.create_default_context()
            _,writer=await asyncio.wait_for(asyncio.open_connection(srv['ip'],int(srv['port']),ssl=ssl_ctx,server_hostname=srv['ip']),timeout=6)
            tls=writer.get_extra_info('ssl_object')
            results.append('🔐 TLS: '+(tls.version() if tls else 'نامشخص'))
            writer.close();await writer.wait_closed()
        except (OSError,ssl.SSLError,asyncio.TimeoutError):
            results.append('❌ TLS یا اعتبار گواهی ناموفق')
    msg='\n'.join(results)
    await invoke(store.audit,owner,actor,'tcp_diagnostic',str(srv['id']))
    await display(update,f'🩺 <b>عیب‌یابی اتصال سرور</b>\n{e(srv["name"])}\n{e(msg)}\n\nاین بررسی، آزمایش اتصال است و علت قطعی اختلال را تعیین نمی‌کند.',kb(nav()))


async def probe(update,context):
    args=context.args or []
    if len(args)!=1 or not args[0].isdigit():
        await display(update,'راهنما: <code>/probe 25</code>');return
    uid=update.effective_user.id;owner=owned_context(update,context);cid=int(args[0]);now=time.monotonic()
    try:
        await invoke(store.require,uid,owner,write=True)
        cfg=await invoke(store.db.execute,"SELECT id,link FROM tunnel_configs WHERE owner_id=%s AND id=%s AND type IN ('single','sub_item')",(owner,cid),fetch='one')
        if not cfg:raise ValueError('کانفیگ پیدا نشد.')
    except (PermissionError,ValueError) as exc:
        await display(update,'⛔ '+e(exc));return
    if now-_LAST_ACTION.get(('probe',uid),0)<60:
        await display(update,'⏳ فاصله بین تست‌های دستی باید حداقل ۶۰ ثانیه باشد.');return
    _LAST_ACTION[('probe',uid)]=now
    monitors=await invoke(store.db.execute,'SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1 AND owner_id IN (%s,%s) ORDER BY id LIMIT 2',(owner,SUPER_ADMIN_ID),fetch='all')
    if not monitors:await display(update,'نود مانیتورینگ فعالی تنظیم نشده است.');return
    from tunnel_logic import tunnel_manager
    from pro_jobs import _record
    texts=[]
    for monitor in monitors:
        label=f"{monitor.get('location_type') or 'unknown'}:{monitor.get('name') or monitor['id']}:{monitor['id']}"[:80]
        try:
            ok,data=await asyncio.wait_for(tunnel_manager._test_via_ws(monitor,cfg['link'],size=.25,timeout=25),timeout=32)
            result=data if ok and isinstance(data,dict) else {'status':'Fail'}
        except Exception:
            result={'status':'Fail'}
        await invoke(_record,owner,cid,label,result)
        texts.append(f'{"✅" if result.get("status")=="OK" else "❌"} {e(label)} | {e(result.get("ping","?"))} ms')
    await invoke(store.audit,owner,uid,'manual_probe',f'config:{cid}')
    await display(update,'🌐 <b>تست چندنقطه‌ای کانفیگ</b>\n'+ '\n'.join(texts) +'\n\nتست موفق از یک منطقه، سلامت در همه مناطق را تضمین نمی‌کند.',kb(nav()))


def _insights_sync(actor,owner):
    store.require(actor,owner)
    with store.db.get_connection() as (conn,cur):
        cur.execute('''SELECT DISTINCT ON(config_id,region) config_id,region,ok
              FROM pro_metrics WHERE owner_id=%s AND measured_at>NOW()-INTERVAL '3 hours'
              ORDER BY config_id,region,measured_at DESC''',(owner,))
        rows=cur.fetchall()
    regions={}
    for r in rows:
        bucket=regions.setdefault(r['region'],{'total':0,'fail':0})
        bucket['total']+=1
        bucket['fail']+=not r['ok']
    return [{'region':k,**v} for k,v in regions.items()]


async def insights(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    rows=await safe_call(update,context,_insights_sync,actor,owner)
    if rows is None:return
    txt='🧠 <b>تحلیل الگوی اختلال در سه ساعت اخیر</b>\n\n'
    for r in rows:
        txt+=f'🌍 {e(r["region"])} | {r["fail"]}/{r["total"]} ناموفق\n'
    if not rows:txt+='داده کافی وجود ندارد؛ از /probe استفاده کنید.'
    txt+='\nاین تحلیل صرفاً همبستگی مشاهده‌شده را نشان می‌دهد، نه علت قطعی اختلال.'
    await display(update,txt,kb(nav()))


async def rules(update,context):
    actor=update.effective_user.id;owner=owned_context(update,context)
    data=await safe_call(update,context,store.rules,actor,owner)
    if data is None:return
    txt='⚙️ <b>قوانین امن اتوماسیون</b>\nفقط اعلان یا خلاصه؛ بدون اجرای دستور خودکار.\n\n'
    txt+='\n'.join(f'{"✅" if r["enabled"] else "⏸"} {e(r["event"])} → {e(r["action"])}' for r in data) or 'هنوز قانون سفارشی ندارید.'
    txt+='\n\nنمونه: <code>/rule probe_failure notify on</code>\n<code>/rule probe_failure notify off</code>'
    await display(update,txt,kb(nav()))


async def rule_command(update,context):
    args=context.args or []
    if len(args)!=3 or args[2] not in ('on','off'):
        await display(update,'راهنما: <code>/rule probe_failure notify on</code>');return
    actor=update.effective_user.id;owner=owned_context(update,context)
    try:await invoke(store.set_rule,actor,owner,args[0],args[1],args[2]=='on')
    except (PermissionError,ValueError) as exc:await display(update,'⛔ '+e(exc));return
    await display(update,'✅ قانون اتوماسیون ذخیره شد.')


async def pdf_report(update,context):
    if update.callback_query:
        await update.callback_query.answer()
    uid=update.effective_user.id;owner=owned_context(update,context)
    try:
        from pro_pdf import generate_pdf
        data=await invoke(generate_pdf,uid,owner)
    except PermissionError:
        await display(update,'⛔ اجازه دریافت گزارش ندارید.');return
    except ImportError:
        await display(update,'⛔ کتابخانه PDF نصب نیست؛ راهنمای نصب نسخه Pro را ببینید.');return
    await context.bot.send_document(chat_id=update.effective_chat.id,
                                   document=InputFile(io.BytesIO(data),filename=f'sonar-report-{owner}.pdf'),
                                   caption='📊 گزارش PDF سونار')


def register(app):
    handlers={'pro_home':home,'pro_favorites':favorites,'pro_rank':rank,'pro_incidents':incidents,
             'pro_tags':tags,'pro_prefs':prefs,'pro_find_help':find_help,'pro_team':team,
             'pro_audit':audit,'pro_report':report,'pro_insights':insights,'pro_rules':rules}
    for code,handler in handlers.items():app.add_handler(SecureCallbackQueryHandler(handler,pattern='^'+code+'$'))
    for pat,handler in (
        (r'^pro_list_(server|config)_\d+$',resources),
        (r'^pro_fav_(server|config)_\d+_\d+$',favorite),
        (r'^pro_ack_\d+$',ack),
        (r'^pro_toggle_(daily_digest|multi_probe)$',toggle_pref),
        (r'^pro_export_(rank|server|pdf)$',export)):
        app.add_handler(SecureCallbackQueryHandler(handler,pattern=pat))
    for cmd,handler in [('pro',home),('find',find),('tag',tag_command),('quiet',quiet),
                        ('member',member),('team',team),('workspace',workspace),
                        ('history',history),('diagnose',diagnose),('probe',probe),('insights',insights),('pdfreport',pdf_report),('rule',rule_command)]:
        app.add_handler(SecureCommandHandler(cmd,handler))
