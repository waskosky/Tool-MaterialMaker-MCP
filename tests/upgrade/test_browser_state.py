"""Exercise request-order races in the actual frontend without a GPU or browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('phase, preferences', [
    ('complete', '[]'), ('cancelled', '[]'), ('submission', '[]'),
    ('complete', '{broken'), ('complete', '{"wrong":"shape"}'),
])
def test_stale_build_response_cannot_replace_current_selection(phase, preferences):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the lightweight frontend state check')
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static/app.js'
    harness = r'''
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8').split('$("search").oninput')[0];
const phase = process.argv[2], preferences = process.argv[3], fields = new Map();
const context = {
  URLSearchParams, location: {hash: ''},
  sessionStorage: {getItem() {return null;}}, localStorage: {getItem() {return preferences;}},
  document: {getElementById(id) {
    if (!fields.has(id)) fields.set(id, {
      value: ({size:'32', target:'generic', 'physical-size':'1'})[id] || '',
      disabled:false, classList:{toggle() {}}, replaceChildren() {}
    });
    return fields.get(id);
  }},
  crypto: {randomUUID: () => 'fixture'}, setTimeout, clearTimeout, URL, console, phase
};
vm.createContext(context); vm.runInContext(source, context);
(async () => {
  vm.runInContext(`
    current = {project_id:'project_a', revision:0}; let respond;
    request = async (path, body) => {
      if (path.endsWith('/cancel')) return {ok:true};
      if (path === '/api/jobs' && phase !== 'submission') return {job_id:'job_a'};
      return new Promise(resolve => respond = resolve);
    };
    globalThis.pending = build().catch(() => {});
  `, context);
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext(`
    invalidate(); current = {project_id:'project_b', revision:0};
    activeJob = 'job_b'; $('cancel').disabled = false;
    respond(phase === 'submission' ? {job_id:'job_a'} : {
      state:phase, result:{build_id:'build_a', manifest:{build_id:'build_a', maps:[]}}
    });
  `, context);
  await context.pending;
  const state = JSON.parse(vm.runInContext(`JSON.stringify({
    project:current.project_id, selected:selectedBuild?.build_id ?? null,
    active:activeJob, downloadDisabled:$('download').disabled,
    cancelDisabled:$('cancel').disabled
  })`, context));
  assert.deepEqual(state, {project:'project_b', selected:null, active:'job_b',
                          downloadDisabled:true, cancelDisabled:false});
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, '-e', harness, str(source), phase, preferences],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('phase', ['submission', 'completion', 'retry_cancel', 'rejection'])
def test_old_family_work_is_cancelled_without_replacing_new_selection(phase):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the frontend state check')
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static/variations.js'
    harness = r'''
const fs=require('fs'), vm=require('vm'), assert=require('node:assert/strict');
const fields=new Map(), calls=[]; let respond, reject;
const context={window:{}, document:{getElementById(id){
  if(!fields.has(id)) fields.set(id,{value:id==='family-count'?'3':'1'});
  return fields.get(id);
}}, setTimeout, clearTimeout, URL, console,
copy:value=>JSON.parse(JSON.stringify(value)), humanize:value=>value};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const panel=new context.window.WorkshopVariations(async (path,body)=>{
  calls.push(path);if(path.endsWith('/cancel'))return {ok:true};
  return new Promise((resolve,fail)=>{respond=resolve;reject=fail;});
},async()=>{},()=>{},error=>{throw error;});
panel.draw=panel.buttons=()=>{};
panel.ranges=new Map([['gain',{enabled:true,min:1,max:3}]]);panel.locked=new Set();
const input={recipe_id:'old_recipe',values:{gain:2},locked:[],settings:{size:128,target:'generic',physical_size_m:2}};
const old={job:{job_id:'old_job'},state:'queued',values:{gain:2}};
(async()=>{
  let pending;
  if(['submission','rejection'].includes(process.argv[2])) pending=panel.start(input);
  else {
    panel.context=input;panel.candidates=[old];
    pending=process.argv[2]==='retry_cancel'?panel.retry(old):panel.poll(old,panel.epoch);
  }
  await new Promise(resolve=>setImmediate(resolve));
  if(process.argv[2]==='retry_cancel') await panel.cancel(); else await panel.clear();
  panel.context={recipe_id:'new_recipe'};
  panel.candidates=[{state:'complete',result:{build_id:'new_build'}}];
  if(process.argv[2]==='rejection') reject(new Error('Obsolete family failed'));
  else if(process.argv[2]==='submission') respond({candidates:[{job:{job_id:'late_job'}}]});
  else if(process.argv[2]==='retry_cancel') respond({job_id:'late_job'});
  else respond({state:'complete',result:{build_id:'old_build',manifest:{maps:[]}}});
  await pending;
  assert.equal(panel.context.recipe_id,'new_recipe');
  assert.equal(panel.candidates.length,1);assert.equal(panel.candidates[0].result.build_id,'new_build');
  if(process.argv[2]!=='rejection')assert(calls.includes('/api/jobs/'+(process.argv[2]==='completion'?'old_job':'late_job')+'/cancel'));
  assert(!calls.some(path=>path.includes('/api/builds/')),'stale completion must not fetch/select images');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness, str(source), phase], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('collection', ['snapshots', 'projects'])
def test_older_collection_response_cannot_hide_newly_saved_items(collection):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the frontend state check')
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static/app.js'
    harness = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');const fields=new Map(),respond=[];
function node(){return {children:[],value:'',textContent:'',appendChild(child){this.children.push(child);},
replaceChildren(...children){this.children=children;},add(child){this.children.push(child);}};}
const context={URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null;}},localStorage:{getItem(){return '[]';}},
document:{getElementById(id){if(!fields.has(id))fields.set(id,node());return fields.get(id);},createElement:node},
Option:function(textContent,value){return {textContent,value};},crypto:{},setTimeout,clearTimeout,console};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8').split('$("search").oninput')[0],context);
context.respond=respond;context.collection=process.argv[2];
vm.runInContext(`current={project_id:'p'};request=()=>new Promise(resolve=>respond.push(resolve));
globalThis.oldRead=collection==='snapshots'?snapshots():projects();
globalThis.newRead=collection==='snapshots'?snapshots():projects();`,context);
(async()=>{
const newer=process.argv[2]==='snapshots'?{snapshots:[{name:'Saved now',revision:2}]}:{projects:[{id:'p',title:'Saved now',revision:2}]};
respond[1](newer);await context.newRead;
respond[0](process.argv[2]==='snapshots'?{snapshots:[]}:{projects:[]});await context.oldRead;
if(process.argv[2]==='snapshots')assert.equal(fields.get('snapshot-count').textContent,1);
else assert.equal(fields.get('projects').children.length,2);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness, str(source), collection], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_search_does_not_cancel_scheduled_material_preview():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the frontend state check')
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static/app.js'
    harness = r'''
const fs=require('fs'), vm=require('vm'), assert=require('node:assert/strict');
const fields=new Map(), timers=new Map();let timerId=0;
const context={URLSearchParams, location:{hash:''}, sessionStorage:{getItem(){return null;}},
localStorage:{getItem(){return '[]';}}, document:{getElementById(id){
  if(!fields.has(id))fields.set(id,{value:''});return fields.get(id);
}}, crypto:{}, console,
setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8').split('$("category").onchange')[0],context);
vm.runInContext(`globalThis.built=0;globalThis.searched=0;build=async()=>{built++;};gallery=async()=>{searched++;};
current={project_id:'p'};setupPanel={ready:()=>true};schedulePreview();$('search').oninput();`,context);
(async()=>{for(const fn of timers.values())await fn();await new Promise(resolve=>setImmediate(resolve));
assert.equal(context.built,1);assert.equal(context.searched,1);})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness, str(source)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('operation', ['open', 'edit', 'undo', 'restore', 'reload'])
def test_old_project_continuation_cannot_rebuild_new_selection(operation):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the frontend state check')
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static/app.js'
    harness = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const fields=new Map();let respond;
function element(){return {children:[],value:'',classList:{toggle(){}},
  appendChild(child){this.children.push(child);},replaceChildren(...children){this.children=children;}};}
const context={URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null;}},
  localStorage:{getItem(){return '[]';}},document:{getElementById(id){
    if(!fields.has(id))fields.set(id,element());return fields.get(id);
  },createElement:element},crypto:{randomUUID:()=> 'request'},setTimeout,clearTimeout,URL,console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8').split('\n(async () => {')[0],context);
const operation=process.argv[2], oldProject={project_id:'a',revision:1,controls:[]};
context.send=async(path,body)=>{
  if((operation==='open'&&path==='/api/projects/a/snapshots')||
     (operation!=='open'&&path==='/api/projects/a'))return new Promise(resolve=>respond=resolve);
  if(path.endsWith('/snapshots'))return {snapshots:[{name:'Saved',revision:0}]};
  if(path==='/api/projects/a')return oldProject;
  return {ok:true,revision:1};
};
vm.runInContext(`current={project_id:'a',revision:0,controls:[]};request=send;
  setupPanel={ready:()=>true};familyPanel={clear:async()=>{}};clearPreview=drawControls=()=>{};
  projects=async()=>{};globalThis.scheduled=0;globalThis.messages=[];
  schedulePreview=()=>{scheduled++;};status=message=>messages.push(message);`,context);
(async()=>{
  if(operation==='open')vm.runInContext("globalThis.pending=openProject('a');",context);
  else if(operation==='edit')vm.runInContext("setControls({gain:9});globalThis.pending=queue;",context);
  else if(operation==='undo')context.pending=fields.get('undo').onclick();
  else if(operation==='reload')context.pending=fields.get('refresh').onclick();
  else {
    await vm.runInContext('snapshots()',context);
    context.pending=fields.get('snapshot-list').children[0].children[1].onclick();
  }
  await new Promise(resolve=>setImmediate(resolve));assert(respond,'old request reached held read');
  vm.runInContext(`invalidate();current={project_id:'b',revision:0};
    selectedBuild={build_id:'exact_candidate_b'};messages=[];scheduled=0;`,context);
  respond(operation==='open'?{snapshots:[]}:oldProject);await context.pending;
  assert.equal(context.scheduled,0,'an obsolete action must not rebuild the selected candidate');
  assert.deepEqual(Array.from(context.messages),[],'an obsolete action must not change current status');
  assert.equal(vm.runInContext('selectedBuild.build_id',context),'exact_candidate_b');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness, str(source), operation], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('operation', ['undo', 'restore'])
@pytest.mark.parametrize('phase', ['mutation', 'refresh'])
def test_history_acknowledgment_precedes_preview_after_settings_change(operation, phase):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the frontend state check')
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static/app.js'
    harness = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const fields=new Map(), revisions=[];let respond;
function element(){return {children:[],value:'',classList:{toggle(){}},
  appendChild(child){this.children.push(child);},replaceChildren(...children){this.children=children;}};}
const context={URLSearchParams,location:{hash:''},sessionStorage:{getItem(){return null;}},
  localStorage:{getItem(){return '[]';}},document:{getElementById(id){
    if(!fields.has(id)){const node=element();node.value=({size:'128',target:'generic','physical-size':'1'})[id]||'';fields.set(id,node);}
    return fields.get(id);
  },createElement:element},crypto:{},setTimeout,clearTimeout,URL,console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8').split('\n(async () => {')[0],context);
context.send=async(path,body)=>{
  if(['/api/history','/api/restore'].includes(path))return process.argv[3]==='mutation'?new Promise(resolve=>respond=resolve):{ok:true,revision:2};
  if(path==='/api/projects/a')return process.argv[3]==='refresh'?new Promise(resolve=>respond=resolve):{project_id:'a',revision:2,controls:[{id:'gain',value:3}]};
  if(path.endsWith('/snapshots'))return {snapshots:[{name:'Saved',revision:0}]};
  if(path==='/api/jobs'){revisions.push(body.revision);return {job_id:'new_preview'};}
  if(path==='/api/jobs/new_preview')return {state:'cancelled'};
  return {ok:true};
};
vm.runInContext(`current={project_id:'a',revision:1,controls:[{id:'gain',value:7}]};request=send;
  setupPanel={ready:()=>true};drawControls=()=>{};projects=async()=>{};
  schedulePreview=status=()=>{};`,context);
(async()=>{
  let pending;
  if(process.argv[2]==='undo')pending=fields.get('undo').onclick();
  else {await vm.runInContext('snapshots()',context);pending=fields.get('snapshot-list').children[0].children[1].onclick();}
  await new Promise(resolve=>setImmediate(resolve));assert(respond);
  fields.get('target').value='godot';fields.get('target').onchange();
  const preview=vm.runInContext('build().catch(()=>{})',context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(revisions,[],'preview must wait for the in-flight graph mutation');
  respond(process.argv[3]==='mutation'?{ok:true,revision:2}:{project_id:'a',revision:2,controls:[{id:'gain',value:3}]});await pending;await preview;
  assert.equal(vm.runInContext('current.revision',context),2,'same-project acknowledgment must survive setting changes');
  assert.equal(vm.runInContext('current.controls[0].value',context),3,'accepted controls must survive a build setting change during refresh');
  assert.deepEqual(revisions,[2],'preview must use the acknowledged revision');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness, str(source), operation, phase], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
