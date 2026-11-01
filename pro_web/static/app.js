'use strict';
const tg=window.Telegram?.WebApp;
const auth=tg?.initData||'';
const $=id=>document.getElementById(id);
const state={page:'servers',index:1,term:'',items:[]};
const titles={servers:'سرورها',configs:'کانفیگ‌ها',rankings:'رتبه‌بندی کیفیت',incidents:'مرکز هشدارها'};
function node(tag,txt,cl){const el=document.createElement(tag);if(txt!=null)el.textContent=String(txt);if(cl)el.className=cl;return el;}
function notice(message){$('toast').textContent=message;$('toast').classList.add('visible');window.setTimeout(()=>$('toast').classList.remove('visible'),2500);}
async function api(path,options={}){if(!auth)throw Error('پنل را از داخل ربات تلگرام باز کنید.');const result=await fetch(path,{...options,headers:{Authorization:'tma '+auth,'Content-Type':'application/json'},cache:'no-store'});if(!result.ok)throw Error('خطای دسترسی یا ارتباط: '+result.status);return result.json();}
async function summary(){const d=await api('/api/summary');$('srv').textContent=`${d.servers.active}/${d.servers.total}`;$('cfg').textContent=`${d.configs.healthy}/${d.configs.total}`;$('inc').textContent=d.incidents;}
function addRow(item){const wrap=node('article',null,'item'),details=node('div');const label=node('strong',item.name||item.title||item.kind||'مورد');details.append(label);let small;
if(state.page==='servers')small=`#${item.id} • ${item.last_status||'Unknown'} • ${item.location_type||'?'}`;
if(state.page==='configs')small=`#${item.id} • ${item.last_status||'Unknown'} • ${item.last_ping??0} ms`;
if(state.page==='rankings')small=`#${item.id} • پینگ ${item.ping??'?'} ms • جیتر ${item.jitter??'?'} ms`;
if(state.page==='incidents')small=`#${item.id} • ${item.status} • ${item.occurrences} بار`;
details.append(node('small',small));wrap.append(details);
if(state.page==='servers'){
 const term=node('button','SSH','terminal-button');term.type='button';
 term.setAttribute('aria-label','اتصال SSH به '+(item.name||'سرور'));
 term.onclick=()=>openTerminal(item);wrap.append(term);
}
if(['servers','configs'].includes(state.page)){const b=node('button',item.favorite?'★':'☆','favorite');b.type='button';b.setAttribute('aria-label','تغییر علاقه‌مندی');b.onclick=async()=>{try{const v=await api('/api/favorites',{method:'POST',body:JSON.stringify({kind:state.page==='servers'?'server':'config',rid:item.id})});item.favorite=v.favorite;b.textContent=v.favorite?'★':'☆';notice('علاقه‌مندی بروزرسانی شد');}catch(e){notice(e.message)}};wrap.append(b);}
if(state.page==='rankings'){wrap.append(node('b',(item.score||0)+'/100','score'));const chart=node('button','📈','favorite');chart.type='button';chart.setAttribute('aria-label','مشاهده تاریخچه پینگ');chart.onclick=()=>trend(item);wrap.append(chart);}
if(state.page==='incidents'&&item.status==='open'){const b=node('button','تأیید');b.onclick=async()=>{try{await api('/api/incidents/ack',{method:'POST',body:JSON.stringify({incident_id:item.id})});await load();}catch(e){notice(e.message)}};wrap.append(b);}
return wrap;}
async function load(){const holder=$('content');holder.replaceChildren(node('p','در حال دریافت اطلاعات...','muted'));$('section-title').textContent=titles[state.page];$('search').hidden=!['servers','configs'].includes(state.page);$('previous').disabled=state.index===1;try{
let path;if(['servers','configs'].includes(state.page)){path=`/api/resources/${state.page==='servers'?'server':'config'}?page=${state.index}&q=${encodeURIComponent(state.term)}`;}else{path=state.page==='rankings'?'/api/rankings':'/api/incidents?status=unresolved';}
const list=await api(path);state.items=list;holder.replaceChildren();if(!list.length)holder.append(node('p','اطلاعاتی برای نمایش پیدا نشد.','muted'));list.forEach(r=>holder.append(addRow(r)));$('next').disabled=!['servers','configs'].includes(state.page)||list.length<12;$('page-number').textContent=state.index.toLocaleString('fa-IR');$('connection').textContent='● متصل';
}catch(e){holder.replaceChildren(node('p',e.message,'bad'));$('connection').textContent='● خطا';}}
function choose(page){state.page=page;state.index=1;state.term='';$('search').querySelector('input').value='';document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('selected',b.dataset.page===page));load();}
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>choose(b.dataset.page)));
$('previous').onclick=()=>{state.index=Math.max(1,state.index-1);load()};$('next').onclick=()=>{state.index++;load()};$('refresh').onclick=()=>{summary().catch(e=>notice(e.message));load()};
let debounce;$('search').querySelector('input').addEventListener('input',e=>{clearTimeout(debounce);debounce=setTimeout(()=>{state.term=e.target.value;state.index=1;load()},350)});
if(tg){tg.ready();tg.expand();}summary().then(load).catch(e=>{$('connection').textContent='● خطا';$('content').replaceChildren(node('p',e.message,'bad'))});


let terminalSocket=null;
function terminalAppend(text){
 const out=$('terminal-output');out.textContent+=String(text);
 if(out.textContent.length>200000)out.textContent=out.textContent.slice(-160000);
 out.scrollTop=out.scrollHeight;
}
async function openTerminal(server){
 if(!auth){notice('پنل را از داخل تلگرام باز کنید.');return;}
 $('terminal-title').textContent='SSH · '+(server.name||('Server #'+server.id));
 $('terminal-output').textContent='';
 $('terminal-state').textContent='در حال برقراری اتصال امن...';
 $('terminal').showModal();
 const scheme=location.protocol==='https:'?'wss':'ws';
 terminalSocket=new WebSocket(`${scheme}://${location.host}/api/terminal`);
 terminalSocket.addEventListener('open',()=>{
   terminalSocket.send(JSON.stringify({init_data:auth,server_id:Number(server.id)}));
 });
 terminalSocket.addEventListener('message',ev=>{
   try{
     const msg=JSON.parse(ev.data);
     if(msg.type==='ready'){$('terminal-state').textContent='متصل به '+msg.server;terminalAppend('Connected to '+msg.server+'\\r\\n');return;}
     if(msg.type==='error'){terminalAppend('\\r\\n[ERROR] '+msg.message+'\\r\\n');$('terminal-state').textContent='خطا در اتصال';return;}
   }catch(_){}
   terminalAppend(ev.data);
 });
 terminalSocket.addEventListener('close',()=>{$('terminal-state').textContent='اتصال بسته شد';});
 terminalSocket.addEventListener('error',()=>{$('terminal-state').textContent='خطای ارتباط SSH';});
}
function sendTerminal(data){
 if(terminalSocket&&terminalSocket.readyState===WebSocket.OPEN)terminalSocket.send(JSON.stringify({type:'input',data}));
}
$('terminal-send').addEventListener('click',()=>{
 const el=$('terminal-input');if(el.value){sendTerminal(el.value);el.value='';}
 sendTerminal('\\r');el.focus();
});
$('terminal-input').addEventListener('input',e=>{
 const value=e.target.value;if(value){sendTerminal(value);e.target.value='';}
});
$('terminal-input').addEventListener('keydown',e=>{
 const keys={ArrowUp:'\\x1b[A',ArrowDown:'\\x1b[B',ArrowRight:'\\x1b[C',ArrowLeft:'\\x1b[D',Tab:'\\t',Backspace:'\\x7f',Escape:'\\x1b',Home:'\\x1b[H',End:'\\x1b[F',Delete:'\\x1b[3~'};
 if(e.key==='Enter'){e.preventDefault();sendTerminal('\\r');}
 else if(e.key==='c'&&e.ctrlKey){e.preventDefault();sendTerminal('\\x03');}
 else if(keys[e.key]){e.preventDefault();sendTerminal(keys[e.key]);}
});
$('terminal-copy').addEventListener('click',async()=>{
 try{await navigator.clipboard.writeText($('terminal-output').textContent);notice('خروجی کپی شد');}
 catch(_){notice('کپی خودکار در این مرورگر مجاز نیست');}
});
function closeTerminal(){
 if(terminalSocket&&terminalSocket.readyState===WebSocket.OPEN)terminalSocket.send(JSON.stringify({type:'close'}));
 if(terminalSocket)terminalSocket.close();
 terminalSocket=null;
 $('terminal').close();
}
$('terminal-close').addEventListener('click',closeTerminal);
$('terminal').addEventListener('click',e=>{if(e.target===$('terminal'))closeTerminal();});

$('trend-close').addEventListener('click',()=>$('trend').close());
async function trend(item){
 try{
 const points=await api('/api/metrics/'+Number(item.id)+'?days=7');
 $('trend-title').textContent='تاریخچه پینگ: '+item.name;
 const vals=points.filter(x=>x.ok&&Number.isFinite(Number(x.ping))&&Number(x.ping)>0).slice(0,80).reverse();
 const canvas=$('trend-canvas'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
 ctx.clearRect(0,0,w,h);ctx.fillStyle='#15243a';ctx.fillRect(0,0,w,h);
 if(!vals.length){$('trend-info').textContent='داده تست موفقی برای این بازه ثبت نشده است.';$('trend').showModal();return;}
 const samples=vals.map(x=>Number(x.ping)),max=Math.max(...samples,100)*1.1,min=0;
 ctx.strokeStyle='#364f6f';ctx.lineWidth=1;
 for(let i=0;i<5;i++){const y=16+i*(h-36)/4;ctx.beginPath();ctx.moveTo(35,y);ctx.lineTo(w-10,y);ctx.stroke();}
 ctx.strokeStyle='#67adff';ctx.lineWidth=3;ctx.beginPath();
 samples.forEach((v,i)=>{const x=35+i*(w-55)/Math.max(samples.length-1,1),y=h-20-(v-min)*(h-40)/(max-min);
 if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();
 ctx.font='14px sans-serif';ctx.fillStyle='#d8eafd';ctx.fillText(Math.round(max)+' ms',5,16);
 $('trend-info').textContent=`${vals.length} تست موفق | کمترین: ${Math.min(...samples)}ms | بیشترین: ${Math.max(...samples)}ms`;
 $('trend').showModal();
 }catch(err){notice(err.message)}
}
