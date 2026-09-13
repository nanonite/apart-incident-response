// Renderer regression: disclosure state survives polling without pointer input.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.isConnected=true;this._text='';}
 set id(v){this._id=v;elements.set(v,this);}
 get id(){return this._id;}
 set textContent(v){this._text=String(v);this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join(' ');}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;this._text='';}
 removeAttribute(name){delete this[name];}
}
const ids=['live-header-summary','live-progress','live-batch-progress','live-run-clock',
 'live-agent-A','live-agent-B','live-shared-history','live-key-insights','live-event-feed',
 'live-last-event','download-completed-bundle','download-completed-responses'];
for(const id of ids){const n=new Element('div');n.id=id;}
const data={events:[],batch:{config:{shared_context_mode:'key_insights_plus_history'}},live_activity:{
 batch_status:'running',run:{id:'run-1',task_id:'locked-database',condition_id:'C1'},step:1,
 agents:{A:{state:'submitted',observation:{step:1,agent_role:'feedback_only',messages:[]},
 updates:[{event_id:'a-1',step:0,timestamp:new Date().toISOString(),agent_role:'feedback_only',
 response_text:'Here is useful feedback',key_insights:['Synthetic key clue']}]},
 B:{state:'generating',state_since:new Date().toISOString(),observation:{step:1,messages:[]},updates:[]}},
 shared_history:[],shared_key_insights:[{text:'Synthetic key clue',agent:'A',step:0,source_event_id:'a-1',visible_to:['B']}],
 feed:[],exports:{ready:false}}};
const document={getElementById:id=>elements.get(id),createElement:tag=>new Element(tag)};
const context=vm.createContext({document,URL,Blob,Date,JSON,setInterval:()=>0,data});
vm.runInContext(fs.readFileSync('dashboard/dist/activity.js','utf8'),context);
const render=()=>vm.runInContext('LiveActivityPanel.render(data,true)',context);
const find=(host,cls)=>{for(const child of host.children){if(child.className===cls)return child;const n=find(child,cls);if(n)return n;}};
render();
for(const cls of ['live-context','live-source']){let detail=find(elements.get('live-agent-A'),cls);detail.open=true;detail.ontoggle();render();detail=find(elements.get('live-agent-A'),cls);assert.equal(detail.open,true,cls+' should stay open after polling');detail.open=false;detail.ontoggle();render();assert.equal(find(elements.get('live-agent-A'),cls).open,false);}
assert.match(elements.get('live-agent-A').textContent,/Feedback only/);
assert.match(elements.get('live-key-insights').textContent,/Synthetic key clue/);
assert.match(elements.get('live-key-insights').textContent,/delivered to B/);
assert.equal(elements.get('download-completed-bundle').hidden,true);
console.log('Disclosure polling and delivered-insight renderer regression passed.');
