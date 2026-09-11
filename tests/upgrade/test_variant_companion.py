"""Browser adoption uses real project/job/build HTTP contracts and synthetic PNGs."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.upgrade.test_hosting import hosted_service, token_file  # Shared private HTTP fixtures.


@pytest.mark.parametrize('scenario', ['complete', 'superseded'])
def test_adopted_variant_handoff_is_bound_to_the_saved_project(hosted_service, scenario):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the browser/service boundary check')
    server, token, app = hosted_service
    source = Path(__file__).resolve().parents[2] / 'src/mm_mcp/play/static'
    initial = app.instantiate('fixture')
    other = app.instantiate('fixture', {'surface/param0': 21}, 'Other material')
    harness = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8')),fields=new Map(),storage=new Map(),navigated=[];
let nativeReady=false, boundJob=null, boundRequest=null, heldResult=null, releaseResult=null;
function element(){return {children:[],dataset:{},value:'',hidden:false,disabled:false,
  classList:{toggle(){}},appendChild(child){this.children.push(child);},
  replaceChildren(...children){this.children=children;},add(child){this.children.push(child);},
  querySelector(){return element();},setAttribute(){},addEventListener(){}};}
const context={URLSearchParams,URL,setTimeout,clearTimeout,crypto:{},
  location:{pathname:input.mount,search:'?project='+input.initial,hash:'#token='+input.token,
    assign(url){navigated.push(url);}},
  history:{replaceState(){}},sessionStorage:{setItem(k,v){storage.set(k,v);},getItem(k){return storage.get(k);}},
  localStorage:{getItem(){return '[]';}},console:{...console,warn(){}},
  Option:function(text,value){this.text=text;this.value=value;},
  document:{getElementById(id){
    if(!fields.has(id)){const item=element();item.value=({target:'godot','physical-size':'2.5','family-count':'2','family-seed':'17'})[id]||'';fields.set(id,item);}
    return fields.get(id);
  },createElement:element},
  fetch:async(path,options)=>{
    assert.ok(path.startsWith(input.mount+'api/'),path);
    const response=await fetch(new URL(path,input.origin),options);
    if(path===input.mount+'api/jobs' && options.method==='POST'){
      const request=JSON.parse(options.body);
      if(request.project_id && !boundJob){
        boundRequest=request;boundJob=(await response.clone().json()).job_id;
      }
    }
    if(boundJob && path===input.mount+'api/jobs/'+boundJob && options.method==='GET'){
      const result=await response.clone().json();
      if(result.state==='complete' && !heldResult){
        heldResult=result;await new Promise(resolve=>releaseResult=resolve);
      }
    }
    return response;
  },window:{
    WorkshopLibrary:class{constructor(request){this.request=request;}async refresh(){await this.request('/api/materials');}},
    WorkshopSetup:class{
      constructor(request,changed){this.changed=changed;}
      ready(){return nativeReady;}label(){return 'Synthetic test renderer';}
      async load(){await this.changed({catalog_available:true,settings:{}});}
    }
  }
};
vm.createContext(context);
const evaluate=text=>vm.runInContext(text,context);
async function until(predicate){
  const deadline=Date.now()+6000;
  while(!predicate() && Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,10));
  assert.ok(predicate(),'Expected the saved-project build response to be pending');
}
(async()=>{
  evaluate(fs.readFileSync(process.argv[1]+'/variations.js','utf8'));
  await evaluate(fs.readFileSync(process.argv[1]+'/app.js','utf8'));
  assert.equal(evaluate('current.project_id'),input.initial);
  nativeReady=true;
  evaluate("$('size').value='32';familyPanel.bind(current,recipeId,locked,true);");
  await fields.get('family').onclick();
  assert.equal(evaluate('familyPanel.candidates.length'),2);
  assert.equal(evaluate('familyPanel.candidates[0].state'),'complete');
  const candidate=JSON.parse(evaluate('JSON.stringify(familyPanel.candidates[0])'));
  const candidateId=candidate.result.build_id;
  const original=await evaluate(`request('/api/builds/${candidateId}/files/request.json')`);
  assert.equal(original.provenance.project_id,undefined);
  assert.equal(original.provenance.revision,undefined);
  let adoptionFinished=false;
  const adoption=evaluate('useVariant(familyPanel.candidates[0],copy(familyPanel.context))')
    .finally(()=>adoptionFinished=true);
  await until(()=>releaseResult || adoptionFinished);
  assert.ok(releaseResult,'A matching recipe preview must still build the newly saved project');
  const adopted=JSON.parse(evaluate('JSON.stringify(current)'));
  assert.equal(adopted.graph_hash,candidate.graph_hash);
  assert.notEqual(adopted.project_id,input.initial);
  assert.equal(boundRequest.project_id,adopted.project_id);
  assert.equal(boundRequest.revision,adopted.revision);
  assert.equal(evaluate('selectedBuild'),null,'The unbound recipe build must not become the selected handoff');
  assert.equal(fields.get('send-foundry').hidden,true);
  fields.get('send-foundry').onclick();assert.deepEqual(navigated,[]);
  assert.ok(fields.get('evidence').children.length,'Keep the candidate images visible while its project build completes');
  let expectedProject=adopted,expectedBuild=heldResult.result.build_id;
  if(input.scenario==='superseded'){
    await evaluate(`openProject('${input.other}')`);
    await evaluate('build()');
    expectedProject=JSON.parse(evaluate('JSON.stringify(current)'));
    expectedBuild=evaluate('selectedBuild.build_id');
    assert.equal(expectedProject.project_id,input.other);
    assert.notEqual(expectedBuild,heldResult.result.build_id);
  }
  releaseResult();await adoption;
  const selected=JSON.parse(evaluate('JSON.stringify(selectedBuild)'));
  assert.equal(selected.build_id,expectedBuild);
  assert.notEqual(selected.build_id,candidateId);
  assert.equal(selected.manifest.material_id,expectedProject.project_id);
  const request=await evaluate(`request('/api/builds/${selected.build_id}/files/request.json')`);
  assert.equal(request.provenance.project_id,expectedProject.project_id);
  assert.equal(request.provenance.revision,expectedProject.revision);
  assert.deepEqual(request.graph,expectedProject.graph);
  assert.deepEqual(await evaluate(`request('/api/builds/${selected.build_id}/files/material.ptex')`),expectedProject.graph);
  assert.deepEqual(await evaluate(`request('/api/builds/${candidateId}/files/request.json')`),original,
    'The immutable recipe build must retain its original provenance');
  assert.equal(fields.get('send-foundry').hidden,false);
  fields.get('send-foundry').onclick();
  assert.deepEqual(navigated,['/shadermaker/?workshop_build='+selected.build_id+'#token='+input.token]);
  await evaluate('familyPanel.clear()');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', harness, str(source)], input=json.dumps({
        'origin': f'http://127.0.0.1:{server.server_address[1]}', 'mount': '/shadermaker/workshop/',
        'token': token, 'initial': initial['project_id'], 'other': other['project_id'], 'scenario': scenario,
    }), capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
