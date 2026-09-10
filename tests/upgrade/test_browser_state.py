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
