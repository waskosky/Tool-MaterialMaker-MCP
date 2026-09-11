"""Run the real browser entry/selection code with controlled HTTP completion order."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('mount', ['/', '/shadermaker/workshop/'])
@pytest.mark.parametrize('scenario', ['linked', 'setup_race', 'project_race', 'standalone', 'invalid_link'])
def test_mounted_entry_project_and_exact_selected_build_navigation(mount, scenario):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the frontend state check')
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static/app.js'
    harness = r'''
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const mount = process.argv[2], scenario = process.argv[3], secret = 'a'.repeat(64);
const fields = new Map(), storage = new Map(), calls = [], navigated = [], replaced = [];
let releaseSetup, releaseProject;
function element() {return {children:[], value:'', hidden:false, disabled:false,
  classList:{toggle(){}}, appendChild(child){this.children.push(child);},
  replaceChildren(...children){this.children = children;}, add(option){this.children.push(option);},
  querySelector(){return element();}, setAttribute(){}, addEventListener(){}};}
const project = id => ({project_id:id, title:id, revision:3, recipe_id:'recipe_a', controls:[]});
const query = scenario === 'invalid_link' ? '?project=..%2Fsetup' : '?project=project_link&view=source';
const context = {URLSearchParams, URL, setTimeout, clearTimeout, crypto:{},
  location:{pathname:mount, search:query, hash:'#token=' + secret, assign(url){navigated.push(url);}},
  history:{replaceState(a,b,url){replaced.push(url);}},
  sessionStorage:{setItem(key,value){storage.set(key,value);}, getItem(key){return storage.get(key);}},
  localStorage:{getItem(){return '[]';}},
  console:{...console,warn(){}}, Option: function(text,value){this.text=text;this.value=value;},
  document:{getElementById(id){
    if (!fields.has(id)) {const node=element();node.value=({size:'256',target:'generic','physical-size':'1'})[id]||'';fields.set(id,node);}
    return fields.get(id);
  },createElement:element},
  fetch: async (url, options) => {
    calls.push({url, options});
    assert.ok(url.startsWith(mount + 'api/'), url);
    assert.equal(options.headers['X-MM-Token'], secret);
    assert.ok(!url.includes(secret), 'The bearer token must never be an HTTP path/query');
    const path = '/' + url.slice(mount.length);
    let body;
    if (path === '/api/capabilities') body={catalog_available:true, limits:{max_resolution:1024}};
    else if (path === '/api/companion') body={foundry_path:scenario==='standalone'?null:'/shadermaker/'};
    else if (path === '/api/setup') {
      if (scenario === 'setup_race') await new Promise(resolve => releaseSetup=resolve);
      body={catalog_available:true,settings:{}};
    } else if (path.startsWith('/api/materials')) body={materials:[]};
    else if (path === '/api/projects') {
      assert.equal(options.method, 'GET', 'Opening a project must not instantiate another recipe');
      body={projects:[{id:'project_link',title:'Linked',revision:3},{id:'project_manual',title:'Manual',revision:3}]};
    } else if (path.endsWith('/snapshots')) body={snapshots:[]};
    else if (path === '/api/projects/project_link') {
      if (scenario === 'project_race') await new Promise(resolve => releaseProject=resolve);
      body=project('project_link');
    } else if (path === '/api/projects/project_manual') body=project('project_manual');
    else throw new Error('Unexpected request ' + path);
    return {ok:true,json:async()=>body};
  }, window:{
    WorkshopLibrary: class {constructor(request){this.request=request;} async refresh(){await this.request('/api/materials');}},
    WorkshopVariations: class {constructor(request){this.request=request;} async clear(){} bind(){} buttons(){}},
    WorkshopSetup: class {
      constructor(request, changed){this.request=request;this.changed=changed;}
      ready(){return false;} label(){return 'Native tools unavailable';}
      async load(){await this.changed(await this.request('/api/setup'));}
    }
  }
};
vm.createContext(context);
const evaluate = text => vm.runInContext(text, context);
(async () => {
  const startup = evaluate(fs.readFileSync(process.argv[1], 'utf8'));
  if (scenario === 'setup_race' || scenario === 'project_race') {
    for (let tries=0;tries<30 && !(releaseSetup || releaseProject);tries++) await new Promise(resolve => setImmediate(resolve));
    assert.ok(releaseSetup || releaseProject, 'Expected the controlled old request to be pending');
    await evaluate("openProject('project_manual')");
    (releaseSetup || releaseProject)();
  }
  await startup;
  assert.deepEqual(replaced, [mount + query], 'Consuming the token fragment must preserve the project query');
  const expected = ['setup_race','project_race'].includes(scenario) ? 'project_manual' : 'project_link';
  if (scenario === 'invalid_link') {
    assert.equal(evaluate('current'), null);
    assert.match(fields.get('status').textContent, /project link is invalid/);
    assert.ok(!calls.some(call => call.url.includes('/api/projects/')));
  } else {
    assert.equal(evaluate('current.project_id'), expected);
    assert.equal(fields.get('projects').value, expected);
  }
  assert.ok(fields.get('size').children.some(option => option.value === '1024'));
  assert.ok(!fields.get('size').children.some(option => Number(option.value) > 1024));
  assert.equal(fields.get('send-foundry').hidden, true);
  evaluate("selectBuild({build_id:'chosen_build',manifest:{build_id:'chosen_build',resolution:128,target:'godot',renderer_kind:'native'}})");
  if (scenario === 'standalone') {
    assert.equal(fields.get('foundry-link').hidden, true);
    assert.equal(fields.get('send-foundry').hidden, true);
    fields.get('send-foundry').onclick();
    assert.deepEqual(navigated, []);
  } else {
    assert.equal(fields.get('foundry-link').hidden, false);
    assert.equal(fields.get('foundry-link').href, '/shadermaker/#token=' + secret);
    assert.equal(fields.get('send-foundry').hidden, false);
    fields.get('send-foundry').onclick();
    assert.deepEqual(navigated, ['/shadermaker/?workshop_build=chosen_build#token=' + secret]);
    evaluate('invalidate()');
    assert.equal(fields.get('send-foundry').hidden, true);
    fields.get('send-foundry').onclick();
    assert.equal(navigated.length, 1, 'A stale preview cannot be sent');
  }
  const before = calls.length;
  await assert.rejects(evaluate("request('https://other.example/api/setup')"), /local API/);
  assert.equal(calls.length, before, 'A request must not send the bearer token to another service');
})().catch(error => {console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness, str(source), mount, scenario],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
