'use strict';
const $ = id => document.getElementById(id);
const PREF_DEFAULTS={showCommunication:true,showScores:true,showMessages:false,showPeek:true};
function loadPrefs(){try{return Object.assign({},PREF_DEFAULTS,JSON.parse(localStorage.getItem('apart-prefs')||'{}'));}catch{return Object.assign({},PREF_DEFAULTS);}}
function savePrefs(){try{localStorage.setItem('apart-prefs',JSON.stringify(ui.prefs));}catch{}}
const ui = {data:null, batch:null, task:'locked-database', step:0, repeat:0, view:'compare', live:true, key:null, replay:null, busy:false, prefs:loadPrefs(), selectedRun:null, projectionToken:0};
const names = {C0:'Full isolation',C1:'Shared from start',C2:'Scheduled unlock'};
const colors = {C0:'#73849b',C1:'#087f78',C2:'#9063c5'};
const ASYMMETRIC_TASKS = ['database-insider','cache-incident','campus-security'];
const example = {run_id:'external-001', task_id:'inventory',condition_id:'C0',step:0,agent_id:'A',response_text:'27 kits remain: 24 + 18 - 15.',answer_class:'27',model:'your-model',messages:[{role:'user',content:'24 kits + 18 received - 15 issued. How many remain?'}]};
function el(tag, className, text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;}
function notice(text){$('notice').textContent=text;$('notice').hidden=!text;}
function format(value){return typeof value==='number'?value.toLocaleString():'—';}
function cfg(){return ui.data?.batch?.config||{};}
function updates(){return (ui.data?.events||[]).filter(e=>e.kind==='task_update');}
const VIEW_TITLES={compare:'Compare conditions',inspect:'Run inspector',export:'Research handoff',sharedlog:'Shared log'};
function applyView(){
 document.body.dataset.workspaceView=ui.view;
 for(const view of Object.keys(VIEW_TITLES))$(view+'-view').hidden=view!==ui.view;
 document.querySelectorAll('[data-view]').forEach(button=>{const selected=button.dataset.view===ui.view;button.classList.toggle('active',selected);if(selected)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
 $('workspace-title').textContent=VIEW_TITLES[ui.view];
}
function chooseView(view){
 if(!Object.hasOwn(VIEW_TITLES,view))return;
 ui.view=view;applyView();
 if(ui.data){if(view==='inspect')renderLog();if(view==='sharedlog')renderSharedLog();if(view==='export')renderExportStatus();}
 const section=$(view+'-view');section.tabIndex=-1;section.focus({preventScroll:true});section.scrollIntoView({block:'start'});
}
async function load(){
 if(ui.busy)return;ui.busy=true;
 try{
  let data;
  if(ui.live){const r=await fetch('/api/state'+(ui.batch?'?batch='+encodeURIComponent(ui.batch):''));if(!r.ok)throw new Error('Live server unavailable');data=await r.json();}
  else return;
  const switched=ui.data?.batch?.id!==data.batch?.id;
  ui.key=data.session_key;ui.data=data;ui.batch=data.batch?.id||ui.batch;
  if(switched&&data.runs?.length&&!data.runs.some(run=>run.task_id===ui.task)){ui.task=data.live_activity?.run?.task_id||data.runs[0].task_id;ui.selectedRun=null;ui.step=0;}
  render();
 }catch(err){
  if(!ui.data){try{const r=await fetch('demo.json');if(!r.ok)throw err;ui.data=await r.json();ui.live=false;ui.batch=ui.data.batch?.id;render();notice('Portable snapshot. Browse recorded results and download responses. Start the local panel to launch experiments or import output.');}catch{notice('No data available. Start the local panel with the command in README.md.');$('connection').textContent='Not connected';}}
  else{if(ui.data.batch?.status==='running'){ui.data.execution={state:'unverified',explanation:'Panel connection interrupted; worker activity cannot be verified.'};LiveActivityPanel.render(ui.data,ui.live);}$('connection').textContent='Connection interrupted';}
 }finally{ui.busy=false;}
}
function renderLiveShowcase(){
 const host=$('live-grid'); if(!host)return; const steps=cfg().steps||5;const condition=(cfg().conditions||[])[0];$('recorded-condition-label').textContent=`${condition||'No condition'} · first configured condition`; host.replaceChildren();
 for(const agent of ['A','B']){const card=el('div','live-agent');card.append(el('h3','',`Agent ${agent}`));const row=el('div','live-minutes');
  for(let s=0;s<steps;s++){const u=updates().find(e=>e.payload.task_id===ui.task&&e.payload.condition_id===condition&&e.payload.agent_id===agent&&e.payload.step===s&&((e.payload.repeat??0)===ui.repeat));const p=u?.payload;const score=evaluator(u);const chip=el('div','live-minute '+(u?'submitted':'missing'));chip.append(el('strong','',`t${s+1}`),el('span','',p?.answer_class||(u?'stalled':'pending')),el('small','',p?(p.upload_within_deadline?'on time':'late'):'—'));if(score)chip.title=`score ${score.score}`;row.append(chip);}card.append(row);host.append(card);}
 const layers=$('communication-layers');if(layers){layers.replaceChildren(el('strong','',`Communication layers · unlock marker at checkpoint ${(cfg().unlock_step??3)+1}`));for(const c of (cfg().conditions||[]))layers.append(el('span','layer '+c,`${c}: ${names[c]}`));}
 const dm=$('difficulty-metrics');if(dm){dm.replaceChildren(el('strong','', 'Accuracy and entropy by difficulty'));for(const m of (ui.data.difficulty_metrics||[])){dm.append(el('span','metric-chip',`D${m.difficulty}: ${m.accuracy==null?'—':(m.accuracy*100).toFixed(0)+'%'} · H ${m.mean_entropy_bits==null?'—':m.mean_entropy_bits.toFixed(2)}`));}}
}
function render(){
 const d=ui.data,b=d.batch;
 LiveActivityPanel.render(d,ui.live);
 $('connection').textContent=ui.live?'Local observer · live':'Recorded snapshot';
 $('batch-select').replaceChildren(...(d.batches||[]).map(b=>{const o=el('option','',`${b.id} · ${b.source} · ${b.status}`);o.value=b.id;o.selected=b.id===ui.batch;return o;}));
 $('batch-select').disabled=!ui.live;
 const source=b?.source||'No batch';$('source-badge').textContent=source==='fixture'?'SYNTHETIC FIXTURE · NOT LLM':source==='imported'?'IMPORTED · UNVERIFIED':source==='local_model'?'REAL LOCAL MODEL':source==='remote_model'?'REAL REMOTE MODEL':source;
 $('source-badge').className='badge '+(['local_model','remote_model'].includes(source)?'real':'fixture');
 $('batch-state').textContent=b?.status?.replaceAll('_',' ')||'No runs yet';
 const us=updates(),runs=d.runs||[];
 $('stat-updates').textContent=format(us.length);$('stat-progress').textContent=`${cfg().expected_updates||'?'} expected · ${cfg().model||'external model'}`;
 $('stat-runs').textContent=`${runs.filter(r=>r.status==='completed').length} / ${runs.length}`;
 $('stat-conditions').textContent=(cfg().conditions||[]).map(c=>c+' '+names[c]).join(' · ');
 $('stat-messages').textContent=format(d.events.filter(e=>e.kind==='communication_delivery').length);
 const generations=d.events.filter(e=>e.kind==='generation_result');let tokenCount=0,hasTokens=false;
 for(const e of generations){if(typeof e.payload.input_tokens==='number'||typeof e.payload.output_tokens==='number'){hasTokens=true;tokenCount+=(e.payload.input_tokens||0)+(e.payload.output_tokens||0);}}
 $('stat-tokens').textContent=hasTokens?format(tokenCount):'—';
 $('stat-cost').textContent=source==='local_model'?'Local inference · API cost $0':source==='fixture'?'Fixture data · no inference':'Cost not verified';
 const active=Boolean(d.can_stop);const unresolved=(d.batches||[]).some(x=>x.status==='running');const staleServer=ui.live&&d.server?.api_version!=='response-panel-v6';$('start').disabled=!ui.live||active||unresolved||staleServer;$('stop').hidden=!d.can_stop;
 if(staleServer){$('connection').textContent='Panel restart required';notice('This panel server is older than the interface. Stop it with Ctrl+C, restart the panel from this checkout, and reload this page. Recorded data remains available.');}
 const banner=$('active-run-banner');if(banner){if(active){banner.textContent=`ACTIVE WORKER · ${cfg().study_id||'response dynamics'} · ${(cfg().conditions||[]).join(' / ')} · ${cfg().steps||5} checkpoints · ${cfg().deadline_seconds||300}s per task run · ${cfg().repeats||1} repeat(s)`;banner.className='active-run-banner active';}else if(unresolved){banner.textContent='UNRESOLVED RUN · no worker verified by this server. Export the partial log and inspect terminal events. To run a fresh pilot, use a separate database.';banner.className='active-run-banner';}else{banner.textContent=`${b?'BATCH ENDED · '+b.status:'No active run'} · next-run controls do not change recorded experiments.`;banner.className='active-run-banner';}}
 $('import-file').disabled=!ui.live;
 if(!$('task-select').dataset.filled){for(const t of d.tasks||[]){const o=el('option','',t.title);o.value=t.id;$('task-select').append(o);}$('task-select').dataset.filled='true';}
 const knownTasks=[...(d.tasks||[])];for(const r of runs){if(!knownTasks.some(t=>t.id===r.task_id))knownTasks.push({id:r.task_id,title:r.task_id,difficulty:'?',category:'Imported task',question:'Original task definition was not supplied.',design:'External responses; context and visibility may be incomplete.'});}
 if(!knownTasks.some(t=>t.id===ui.task))ui.task=knownTasks[0]?.id;
 $('task-tabs').replaceChildren(...knownTasks.map(t=>{const button=el('button','task-tab'+(t.id===ui.task?' selected':''));button.type='button';button.setAttribute('aria-pressed',String(t.id===ui.task));const top=el('span','task-number',String(t.difficulty).padStart(2,'0'));top.append(el('span','',typeof t.difficulty==='number'?'▰'.repeat(t.difficulty):'EXTERNAL'));button.append(top,el('strong','',t.title));button.onclick=()=>{ui.task=t.id;ui.repeat=0;render();};return button;}));
 const task=knownTasks.find(t=>t.id===ui.task)||{};$('task-category').textContent=task.category||'';$('task-title').textContent=task.title||'Choose a task';$('task-question').textContent=task.question||'';$('difficulty').textContent=`Difficulty ${task.difficulty||'?'} / 5`;$('task-design').textContent=task.design||'';
 const repeats=[...new Set(runs.filter(r=>r.task_id===ui.task).map(r=>r.repeat??0))].sort((a,b)=>a-b);
 if(!repeats.includes(ui.repeat))ui.repeat=repeats[0]??0;
 $('repeat-select').replaceChildren(...(repeats.length?repeats:[0]).map(r=>{const o=el('option','',String(r+1));o.value=r;o.selected=r===ui.repeat;return o;}));
 ui.step=Math.min(ui.step,(cfg().steps||3)-1);renderToggles();renderMinuteBar();renderComparison();renderChart();renderEntropy();renderLiveShowcase();renderAudit();renderExportStatus();applyView();if(ui.view==='inspect')renderLog();if(ui.view==='sharedlog')renderSharedLog();
 $('last-updated').textContent=`${ui.live?'OBSERVED':'RECORDED'} ${d.events.length?new Date(d.events.at(-1).timestamp).toLocaleTimeString():'—'} · ${d.events.length} EVENTS`;
}
function renderTimeline(){const steps=cfg().steps||3;$('timeline').replaceChildren(...Array.from({length:steps},(_,i)=>{const unlock=(cfg().conditions||[]).includes('C2')&&cfg().unlock_step===i;const b=el('button','step'+(i===ui.step?' selected':'')+(unlock?' intervention':''),String(i).padStart(2,'0'));b.setAttribute('aria-pressed',String(i===ui.step));b.append(el('span','',unlock?'C2 UNLOCK':i===0?'INITIAL':'UPDATE'));b.onclick=()=>{ui.step=i;render();};return b;}));}
function currentRun(condition){return (ui.data.runs||[]).find(r=>r.task_id===ui.task&&r.condition_id===condition&&(r.repeat??0)===ui.repeat);}
function currentUpdate(run,agent){return updates().find(e=>e.run_id===run?.id&&e.payload.agent_id===agent&&e.payload.step===ui.step);}
function evaluator(event){return ui.data.events.find(e=>e.kind==='evaluator_result'&&e.payload.update_id===event?.event_id)?.payload;}
function renderComparison(){
 const conditions=cfg().conditions||['C0','C1'];$('comparison').replaceChildren(...conditions.map(condition=>{
  const run=currentRun(condition),box=el('section','condition '+condition.toLowerCase()),header=el('div','condition-header'),title=el('div');
  title.append(el('h3','',names[condition]),el('p','',condition==='C0'?'Own history only':condition==='C1'?'Earlier peer updates are visible':`Earlier history unlocks at step ${cfg().unlock_step}`));header.append(title,el('span','condition-marker',condition));box.append(header);
  for(const agent of ['A','B']){const e=currentUpdate(run,agent),p=e?.payload,score=evaluator(e);const card=el('button','agent-card');card.type='button';const top=el('div','agent-top');top.append(el('span','avatar',agent),el('strong','',`Agent ${agent}`));if(score&&ui.prefs.showScores!==false)top.append(el('span','answer-score '+(score.score?'correct':'incorrect'),score.score?'✓ Correct option':'× Incorrect option'));card.append(top);
   if(p){card.append(el('span','answer-label',p.answer_class??'Unclassified response'),el('p','answer-text',p.response_text));const meta=el('div','agent-meta');
    if(ui.prefs.showCommunication!==false)meta.append(el('span','comm '+(p.communication_available?'on':'off'),p.communication_available===null?'Visibility unknown':p.communication_available?'Peer channel available':'Isolated context'));
    if(ui.prefs.showMessages)meta.append(el('span','',`${p.visible_message_ids?.length||0} peer updates`));
    meta.append(el('span','',p.latency_ms!==undefined?`${(p.latency_ms/1000).toFixed(1)}s`:''));card.append(meta);
    if(ui.prefs.showMessages&&p.visible_message_ids?.length){const mail=el('div','mailbox');for(const id of p.visible_message_ids.slice(-4)){const peer=updates().find(u=>u.event_id===id);if(peer)mail.append(el('span','mail-item',`t${peer.payload.step} ${peer.payload.agent_id} · ${(peer.payload.response_text||'').slice(0,48)}`));}card.append(mail);}
    card.onclick=()=>detail(e);}
   else{const errors=ui.data.events.filter(e=>e.run_id===run?.id&&e.kind==='run_error');card.append(el('div','empty-answer',errors.length?'Run incomplete: '+errors.at(-1).payload.message:run?'Waiting for this checkpoint. No response has been filled in.':'This task / condition has not run yet.'));card.disabled=true;}
   box.append(card);
  }return box;
 }));
}
function svg(tag,attrs,text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;}
function renderChart(){const chart=svg('svg',{viewBox:'0 0 540 170',role:'img','aria-label':'Mean scored answer accuracy by checkpoint, with conditions kept separate'});const steps=cfg().steps||3,x=i=>45+i*450/Math.max(1,steps-1),y=v=>133-v*100;
 for(const v of [0,.5,1]){chart.append(svg('line',{x1:45,y1:y(v),x2:505,y2:y(v),stroke:'#e0e7ef','stroke-dasharray':v===0?'0':'3 4'}),svg('text',{x:0,y:y(v)+4},`${v*100}%`));}
 for(let i=0;i<steps;i++)chart.append(svg('text',{x:x(i),y:159,'text-anchor':'middle'},`t${i}`));
 for(const condition of cfg().conditions||[]){let points=[];for(let i=0;i<steps;i++){const runIds=new Set(ui.data.runs.filter(r=>r.task_id===ui.task&&r.condition_id===condition).map(r=>r.id));const scores=ui.data.events.filter(e=>e.kind==='evaluator_result'&&runIds.has(e.run_id)&&e.payload.step===i).map(e=>e.payload.score);if(scores.length){const value=scores.reduce((a,b)=>a+b,0)/scores.length;points.push(`${x(i)},${y(value)}`);const point=svg('circle',{cx:x(i),cy:y(value),r:4,fill:colors[condition]});point.append(svg('title',{},`${condition}, step ${i}: ${(100*value).toFixed(0)}%, ${scores.length} scored updates`));chart.append(point);}}
  if(points.length)chart.append(svg('polyline',{points:points.join(' '),fill:'none',stroke:colors[condition],'stroke-width':2}));}
 $('score-chart').replaceChildren(chart);
}
function renderEntropy(){const rows=(ui.data.metrics||[]).filter(m=>m.task_id===ui.task&&m.step===ui.step);if(!rows.length){$('entropy-panel').replaceChildren(el('p','muted','Awaiting classified responses at this checkpoint.'));return;}
 $('entropy-panel').replaceChildren(...rows.map(m=>{const row=el('div','distribution-row'),left=el('div','',`${m.condition_id} · Agent ${m.agent_id}`);left.append(el('small','',`${m.sample_count} classified sample${m.sample_count===1?'':'s'} · ${Object.keys(m.counts).length} observed classes`));const value=el('div','',m.entropy_bits===null?'More repeats needed':`${m.entropy_bits.toFixed(3)} bits`);value.title=m.entropy_bits===null?'At least two samples are needed even for this descriptive proxy. Small-sample uncertainty remains substantial.':JSON.stringify(m.probabilities);row.append(left,value);return row;}));
}
function renderLog(){const filter=$('event-filter').value;const runIds=new Set(ui.data.runs.filter(r=>r.task_id===ui.task).map(r=>r.id));const events=ui.data.events.filter(e=>(!e.run_id||runIds.has(e.run_id))&&(filter==='all'||e.kind===filter));$('event-log').replaceChildren(...events.slice().reverse().map(e=>{const row=el('details','event'),summary=el('summary');summary.append(el('code','',`#${e.seq}`),el('strong','',e.kind.replaceAll('_',' ')),el('span','muted',`${e.payload.agent_id||e.payload.recipient||''} ${Number.isInteger(e.payload.step)?'· t'+e.payload.step:''}`),el('span','muted',new Date(e.timestamp).toLocaleTimeString()));row.append(summary);row.ontoggle=()=>{if(row.open&&!row.querySelector('pre'))row.append(el('pre','',JSON.stringify(e,null,2)));};return row;}));}
function renderToggles(){for(const t of document.querySelectorAll('[data-pref]'))t.checked=!!ui.prefs[t.dataset.pref];}
function renderMinuteBar(){
 const activity=ui.data.live_activity;const run=activity?.run;const steps=cfg().steps||3,us=updates().filter(e=>!run||e.run_id===run.id),bar=$('minute-bar');let current=-1;
 const b=ui.data.batch||{};
 if(ui.live&&ui.data.execution?.state==='verified_worker'&&b.status==='running'&&run?.status==='running'&&Number.isInteger(activity.step))current=activity.step;
 bar.replaceChildren(...Array.from({length:steps},(_,i)=>{const agents=new Set(us.filter(e=>e.payload.step===i).map(e=>e.payload.agent_id));const both=agents.size>=2;
  const chip=el('button','minute-chip'+(both?' done':agents.size?' partial':'')+(i===ui.step?' selected':'')+(current===i?' live':''));chip.type='button';
  chip.append(el('span','',`t${i+1}`),el('small','',both?'both':agents.size?[...agents].join('&'):'—'));
  chip.title=`Checkpoint ${i+1}: ${both?'both agents submitted':agents.size?'1 of 2 submitted':'no submission'}${current===i?' · live now':''}`;
  chip.onclick=()=>{ui.step=i;render();};return chip;}));
 const state=$('minute-state');if(state)state.textContent=current>=0?`checkpoint ${current+1} of ${steps} running`:b.status==='running'?'Worker unverified · recorded checkpoints':`${steps} checkpoints per run`;
 const clock=$('run-clock');if(clock){if(current>=0&&activity.run_started_at){const elapsed=Math.max(0,(Date.now()-new Date(activity.run_started_at).getTime())/1000);clock.textContent=`task run elapsed ${Math.floor(elapsed/60)}:${String(Math.floor(elapsed%60)).padStart(2,'0')}`;}else clock.textContent='run idle';}
}
function renderAudit(){const list=$('audit-list');if(!list)return;const trail=ui.data.audit||[];list.replaceChildren(...trail.slice().reverse().map(a=>{const li=el('li','');li.append(el('code','',a.action.replaceAll('_',' ')),el('span','muted',new Date(a.timestamp).toLocaleTimeString()));const detail={...a};delete detail.action;delete detail.timestamp;delete detail.seq;delete detail.event_id;li.append(el('span','',JSON.stringify(detail).slice(0,200)));return li;}));if(!trail.length)list.append(el('li','muted','No researcher actions recorded yet.'));
}
function projectionLocal(events,step,agentOrder=['A','B']){
 const up=events.filter(e=>{const s=e.payload.step;return s===undefined||s===null||s<=step;});
 const agents={},comm={};
 for(const agent of agentOrder){
  const obs=events.find(e=>e.kind==='agent_observation'&&e.payload.agent_id===agent&&e.payload.step===step);
  const visible=new Set((obs||{payload:{}}).payload.visible_event_ids||[]);
  for(const e of events){if(e.kind==='task_update'&&e.payload.agent_id===agent&&e.payload.step===step)for(const id of (e.payload.visible_event_ids||[]))visible.add(id);}
  agents[agent]={visible_event_ids:[...visible].sort(),visible_events:up.filter(e=>visible.has(e.event_id)),observation:obs?obs.payload:null};
  comm[agent]=obs?!!obs.payload.communication_available:null;
 }
 return {step,minute:step+1,global:up,agents,communication_available:comm,note:'Global includes private evidence and evaluator truth that no agent sees.'};
}
function runSummary(e){const p=e.payload||{};const bits=[p.agent_id||p.recipient||'',Number.isInteger(p.step)?'t'+p.step:''];if(p.answer_class)bits.push(p.answer_class);if(p.score!==undefined)bits.push('score '+p.score);return bits.filter(Boolean).join(' · ');}
function renderPane(host,events){host.replaceChildren(...events.map(e=>{const row=el('div','event-row');row.title=JSON.stringify(e,null,2).slice(0,800);row.append(el('code','',`#${e.seq}`),el('strong','',e.kind.replaceAll('_',' ')),el('span','muted',runSummary(e)));return row;}));if(!events.length)host.append(el('p','muted','No events at this minute.'));}
function renderPanes(proj){
 const unlock=(cfg().conditions||[]).includes('C2')&&ui.step>=cfg().unlock_step;
 const mark=$('projection-unlock');if(mark)mark.textContent=unlock?`C2 UNLOCK ACTIVE · minute ${cfg().unlock_step+1}`:'';
 renderPane($('pane-global'),proj.global);
 for(const agent of ['A','B']){const a=proj.agents[agent];renderPane($('pane-'+agent),a.visible_events);const st=$('pane-'+agent+'-state');if(st)st.textContent=`${a.visible_event_ids.length} events visible${a.observation?' · '+(a.observation.communication_available?'channel open':'isolated'):''}`;}
 const note=$('projection-note');if(note)note.textContent=proj.note;
}
async function renderSharedLog(){
 if(ui.view!=='sharedlog')return;
 const token=++ui.projectionToken;
 const sel=$('projection-run');const runs=ui.data.runs.filter(r=>r.task_id===ui.task);
 sel.replaceChildren(...runs.map(r=>{const o=el('option','',`${r.condition_id} · repeat ${(r.repeat??0)+1} · ${r.status}`);o.value=r.id;o.selected=r.id===ui.selectedRun;return o;}));
 if(!runs.length){renderPane($('pane-global'),[]);renderPane($('pane-A'),[]);renderPane($('pane-B'),[]);$('projection-unlock').textContent='';$('projection-note').textContent='';return;}
 const runId=sel.value||runs[0].id;ui.selectedRun=runId;
 const scoped=ui.data.events.filter(e=>e.run_id===runId||!e.run_id);
 let proj;
 if(ui.live){try{const r=await fetch('/api/projections?batch='+encodeURIComponent(ui.batch||'')+'&step='+ui.step+'&run='+encodeURIComponent(runId));if(!r.ok)throw new Error('projection fetch failed');proj=await r.json();}catch{proj=projectionLocal(scoped,ui.step);}}
 else proj=projectionLocal(scoped,ui.step);
 if(token!==ui.projectionToken)return;
 renderPanes(proj);
}
function detail(event){const p=event.payload,obs=ui.data.events.find(e=>e.event_id===p.observation_id)?.payload,score=evaluator(event);$('detail-eyebrow').textContent=`${p.condition_id} / CHECKPOINT ${p.step} / ${p.source}`;$('detail-title').textContent=`Agent ${p.agent_id} · ${p.task_id}`;const body=$('detail-body');body.replaceChildren(el('p','detail-answer',p.response_text));const grid=el('div','detail-grid');for(const [k,v] of Object.entries({'Answer class':p.answer_class??'Not supplied','Selected-option score':score?String(score.score):'Not evaluated','Peer events delivered':p.visible_message_ids?.length||0,'Event ID':event.event_id,'Model':p.model||'Unknown','Prompt version':p.prompt_version||'Unknown'})){const cell=el('div');cell.append(el('small','',k),el('span','',String(v)));grid.append(cell);}body.append(grid,el('h3','','Exact supplied context'));
 if(obs?.messages)for(const m of obs.messages){body.append(el('span','badge',m.role),el('pre','',m.content));}else body.append(el('p','muted','Context was not supplied. It has not been inferred or fabricated.'));
 body.append(el('h3','','Delivered peer event IDs'),el('pre','',JSON.stringify(p.visible_message_ids||[],null,2)),el('h3','','Full TaskUpdate'),el('pre','',JSON.stringify(p,null,2)));$('detail-dialog').showModal();}
async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Session-Key':ui.key},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(data.error||'Request failed');return data;}
function downloadBlob(name,blob){const url=URL.createObjectURL(blob);const a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
function download(name,text,type='application/json'){downloadBlob(name,new Blob([text],{type}));}
function responseRecords(){const es=ui.data.events;return updates().map(e=>({...e.payload,event_id:e.event_id,timestamp:e.timestamp,observation:es.find(o=>o.event_id===e.payload.observation_id)?.payload||null,evaluator:evaluator(e)||null}));}
let exportBusy=false;
let exportMessage='';
function renderExportStatus(){
 const batch=ui.data?.batch;const available=Boolean(batch&&ui.batch);
 for(const id of ['export-top','download-bundle','download-responses','download-report']){const button=$(id);button.disabled=!available||exportBusy;button.setAttribute('aria-busy',String(exportBusy));}
 const status=$('export-status');if(!status)return;
 status.textContent=exportMessage||(available?`${batch.id} · ${batch.source} · ${batch.status}. ${ui.live?'ZIP includes report.md, events, responses, metrics, and provenance.':'Portable snapshot: JSON and JSONL downloads; start the local panel for a ZIP.'} ${batch.status==='running'?'Download now for a partial snapshot of recorded events; download again after completion.':''}`:'Select a recorded batch or launch an experiment to export its traces.');
 $('download-bundle').textContent=ui.live?'↓ Download research bundle · ZIP':'↓ Download batch snapshot · JSON';
 $('export-top').textContent=ui.live?'↓ Export traces · ZIP':'↓ Export snapshot · JSON';
}
async function downloadExport(route,name,type){
 if(exportBusy)return;
 if(!ui.data?.batch||!ui.batch){notice('No batch selected. Launch or select an experiment before exporting.');return;}
 const batch=ui.batch;const partial=ui.data.batch.status==='running';exportBusy=true;exportMessage='Preparing download…';renderExportStatus();
 try{
  const response=await fetch('/api/'+route+'?batch='+encodeURIComponent(batch),{cache:'no-store'});
  if(!response.ok){let message='Export failed ('+response.status+').';try{message=(await response.json()).error||message;}catch{}throw new Error(message);}
  if(!(response.headers.get('Content-Type')||'').includes(type))throw new Error('The panel returned an unexpected file type. Restart the local panel and retry.');
  const blob=await response.blob();downloadBlob(name,blob);
  exportMessage=`Downloaded ${name} for ${batch}${partial?' · partial snapshot; later events are excluded':''}.`;
  notice(exportMessage);
 }catch(error){exportMessage='Download failed: '+error.message;notice(exportMessage);}
 finally{exportBusy=false;renderExportStatus();}
}
async function exportResponses(){if(ui.live)return downloadExport('responses','responses.jsonl','application/x-ndjson');if(!ui.data?.batch)return notice('No batch available.');download('responses.jsonl',responseRecords().map(r=>JSON.stringify(r)).join('\n')+'\n','application/x-ndjson');}
async function exportBundle(){if(ui.live)return downloadExport('export','apart-research-bundle.zip','application/zip');if(!ui.data?.batch)return notice('No batch available.');download('apart-research-snapshot.json',JSON.stringify(ui.data,null,2));}
async function exportReport(){if(ui.live)return downloadExport('report','experiment-report.md','text/markdown');notice('Start the local panel for the Markdown report; the snapshot and response JSONL can be downloaded here.');}
function selectedTaskIds(){const value=$('task-select').value;return value==='all'?ui.data.tasks.map(t=>t.id):value==='asymmetric'?ASYMMETRIC_TASKS:value==='experiment1'?['locked-database']:[value];}
function estimate(){const count=$('task-select').value==='all'?(ui.data?.tasks?.length||7):$('task-select').value==='asymmetric'?ASYMMETRIC_TASKS.length:1;const n=count*$('conditions').value.split(',').length*Number($('steps').value)*Number($('repeats').value)*2;$('run-estimate').textContent=`${n} requested updates · ${$('steps').value} checkpoints × ${$('repeats').value} repeats · ${$('adapter').value==='fixture'?'fixture, no LLM':'local inference'}`;}
$('run-form').onchange=estimate;
$('run-form').onsubmit=async e=>{e.preventDefault();try{const taskIds=selectedTaskIds();const data=await post('/api/run',{task_ids:taskIds,conditions:$('conditions').value.split(','),steps:Number($('steps').value),repeats:Number($('repeats').value),unlock_step:Number($('unlock').value),adapter:$('adapter').value,model:$('model').value,logprobs:$('logprobs').checked,engagement_mode:$('engagement').value,shared_context_mode:$('shared-context').value,study_id:taskIds.includes('locked-database')?'locked_database_v1':'asymmetric_evidence_v1'});ui.batch=data.batch_id;ui.task=taskIds[0];ui.step=0;ui.repeat=0;notice('Batch started. Checkpoint updates, peer visibility, key insights, and audit events are being recorded.');setTimeout(load,200);}catch(err){notice(err.message);}};
$('stop').onclick=async()=>{try{await post('/api/stop',{});notice('Stop requested. The in-flight response will be retained; no next request will start.');}catch(err){notice(err.message);}};
$('batch-select').onchange=()=>{ui.batch=$('batch-select').value;ui.repeat=0;load();};$('repeat-select').onchange=()=>{ui.repeat=Number($('repeat-select').value);renderComparison();};$('event-filter').onchange=renderLog;
$('close-detail').onclick=()=>$('detail-dialog').close();
$('play').onclick=()=>{if(ui.replay){clearInterval(ui.replay);ui.replay=null;$('play').textContent='▶ Replay';}else{ui.step=0;render();$('play').textContent='Ⅱ Pause';ui.replay=setInterval(()=>{ui.step=(ui.step+1)%(cfg().steps||3);render();},1800);}};
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>chooseView(b.dataset.view);
for(const t of document.querySelectorAll('[data-pref]'))t.onchange=()=>{ui.prefs[t.dataset.pref]=t.checked;savePrefs();render();};
$('projection-run').onchange=()=>{ui.selectedRun=$('projection-run').value;renderSharedLog();};
$('export-top').onclick=exportBundle;$('download-bundle').onclick=exportBundle;$('download-responses').onclick=exportResponses;$('sample-download').onclick=()=>download('input-example.jsonl',JSON.stringify(example)+'\n','application/x-ndjson');
const reportButton=el('button','button light','↓ Download Markdown report');reportButton.id='download-report';reportButton.onclick=exportReport;$('download-bundle').after(reportButton);
const exportStatus=el('p','export-status');exportStatus.id='export-status';exportStatus.setAttribute('role','status');exportStatus.setAttribute('aria-live','polite');$('export-view').prepend(exportStatus);
$('import-file').onchange=async()=>{const file=$('import-file').files[0];if(!file)return;try{if(file.size>10_000_000)throw new Error('File must be under 10 MB');const data=await post('/api/import',{jsonl:await file.text()});ui.batch=data.batch_id;ui.repeat=0;ui.step=0;notice('Output imported with external, unverified provenance. Missing contexts and scores stay unknown.');await load();}catch(err){notice(err.message);}finally{$('import-file').value='';}};
applyView();renderExportStatus();estimate();load();setInterval(load,1800);
