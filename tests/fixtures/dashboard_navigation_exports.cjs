const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const elements=new Map(), clicks=[], requests=[];
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.hidden=false;this.classList={toggle:(key,on)=>{this.attributes[key]=on;}};}
 set id(id){this._id=id;elements.set(id,this);} get id(){return this._id;}
 append(...children){this.children.push(...children);}
 prepend(...children){this.children.unshift(...children);}
 after(child){child.parent=this;}
 remove(){this.removed=true;}
 setAttribute(key,value){this.attributes[key]=value;}
 removeAttribute(key){delete this.attributes[key];}
 focus(options){this.focused=options;}
 scrollIntoView(options){this.scrolled=options;}
 click(){clicks.push(this);}
}
const html=fs.readFileSync('dashboard/dist/index.html','utf8');
for(const match of html.matchAll(/\bid="([^"]+)"/g)){const n=new Element('div');n.id=match[1];}
const buttons=['compare','inspect','export','sharedlog'].map(view=>{const n=new Element('button');n.dataset.view=view;return n;});
const body=new Element('body');
const document={body,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),querySelectorAll:selector=>selector==='[data-view]'?buttons:[]};
let nextError=null;
const fetch=async url=>{
 requests.push(url);
 if(nextError){const message=nextError;nextError=null;return {ok:false,status:404,json:async()=>({error:message})};}
 const type=url.startsWith('/api/export')?'application/zip':url.startsWith('/api/report')?'text/markdown':'application/x-ndjson';
 return {ok:true,headers:{get:()=>type},blob:async()=>new Blob(['trace data'],{type})};
};
const context=vm.createContext({document,fetch,Blob,URL,JSON,Date,localStorage:{getItem:()=>null},setTimeout:()=>0,setInterval:()=>0,LiveActivityPanel:{render:()=>{}}});
let source=fs.readFileSync('dashboard/dist/app.js','utf8');
source=source.replace('applyView();renderExportStatus();estimate();load();setInterval(load,1800);','');
vm.runInContext(source,context);
vm.runInContext("ui.data={batch:{id:'batch-live',source:'local_model',status:'running'},events:[],runs:[],metrics:[]};ui.batch='batch-live';renderLog=()=>{};renderSharedLog=()=>{};",context);
async function main(){
 for(const button of buttons){
  button.onclick();
  const view=button.dataset.view;
  assert.equal(body.dataset.workspaceView,view);
  assert.equal(elements.get('workspace-title').textContent,{compare:'Compare conditions',inspect:'Run inspector',export:'Research handoff',sharedlog:'Shared log'}[view]);
  for(const other of buttons)assert.equal(elements.get(other.dataset.view+'-view').hidden,other!==button);
  assert.equal(button.attributes['aria-current'],'page');
  assert.ok(elements.get(view+'-view').focused);
  assert.ok(elements.get(view+'-view').scrolled);
 }
 await elements.get('export-top').onclick();
 assert.equal(requests.at(-1),'/api/export?batch=batch-live');
 assert.equal(clicks.at(-1).download,'apart-research-bundle.zip');
 assert.match(elements.get('export-status').textContent,/partial snapshot/);
 assert.equal(elements.get('export-top').disabled,false);
 await elements.get('download-responses').onclick();
 assert.equal(requests.at(-1),'/api/responses?batch=batch-live');
 assert.equal(clicks.at(-1).download,'responses.jsonl');
 await elements.get('download-report').onclick();
 assert.equal(requests.at(-1),'/api/report?batch=batch-live');
 assert.equal(clicks.at(-1).download,'experiment-report.md');
 const downloads=clicks.length;
 nextError='Batch not found';await elements.get('export-top').onclick();
 assert.equal(clicks.length,downloads);
 assert.match(elements.get('export-status').textContent,/Download failed: Batch not found/);
 vm.runInContext('ui.live=false;',context);
 await elements.get('export-top').onclick();
 assert.equal(clicks.at(-1).download,'apart-research-snapshot.json');
 vm.runInContext('ui.live=true;ui.data=null;ui.batch=null;',context);
 await elements.get('export-top').onclick();
 assert.match(elements.get('notice').textContent,/No batch selected/);
 for(const [id,value] of Object.entries({'task-select':'experiment1',conditions:'C0,C2',steps:'5',repeats:'2',unlock:'3',adapter:'ollama',model:'gemma2:2b',engagement:'neutral','shared-context':'key_insights_plus_history'}))elements.get(id).value=value;
 elements.get('logprobs').checked=true;
 vm.runInContext("post=async (route,config)=>{globalThis.launched={route,config};return {batch_id:'scheduled-batch'};};",context);
 await elements.get('run-form').onsubmit({preventDefault(){}});
 const cfg=JSON.parse(vm.runInContext('JSON.stringify(launched)',context));
 assert.equal(cfg.route,'/api/run');
 assert.deepEqual(cfg.config.conditions,['C0','C2']);
 assert.deepEqual(cfg.config.task_ids,['locked-database']);
 assert.equal(cfg.config.unlock_step,3);
 assert.equal(cfg.config.logprobs,true);
 assert.equal(cfg.config.repeats,2);
 assert.equal(cfg.config.deadline_seconds,900);
 assert.equal(cfg.config.request_timeout_seconds,120);
 assert.equal(cfg.config.max_output_tokens,512);
 elements.get('pilot-preset').value='calibration';
 elements.get('pilot-preset').onchange();
 const pilot=JSON.parse(vm.runInContext('JSON.stringify(requestedConfig())',context));
 assert.deepEqual(pilot.conditions,['C2']);
 assert.deepEqual(pilot.task_ids,['sensor-fusion']);
 assert.equal(pilot.steps,5);
 assert.equal(pilot.repeats,2);
 assert.equal(pilot.batch_timeout_seconds,1860);
 console.log('Navigation focus, direct live ZIP/JSONL/Markdown downloads, errors and offline fallback passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
