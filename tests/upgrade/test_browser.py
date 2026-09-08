"""Real Chromium + in-process service adapter, with a synthetic PNG baker.

The real HTTP adapter is tested separately. This verifies browser logic and either WebGL availability or its fallback.
It does not certify WebGL shading, browser networking, or native rendering.
"""
import io
import json
import os
from pathlib import Path
import shutil
import zipfile
import pytest

@pytest.mark.browser
def test_browser_inprocess_edit_export_matches_shared_state(http_service,tmp_path):
    sync=pytest.importorskip('playwright.sync_api')
    executable=os.environ.get('MM_TEST_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:pytest.skip('Chromium executable unavailable; set MM_TEST_CHROMIUM')
    server,token,app=http_service;errors=[]
    with sync.sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=executable,headless=True,args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1440,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        # The runner blocks browser network navigation by administrator policy.
        # Do not change that policy. Exercise the same UI through an in-process
        # test adapter instead; the actual HTTP contract has independent tests.
        import base64
        from urllib.parse import urlsplit,parse_qs
        from mm_mcp.core import ServiceError
        from mm_mcp.play.sliders import derive_sliders
        def transport(path,method,body):
            parts=urlsplit(path);route=parts.path;query=parse_qs(parts.query)
            try:
                if method=='GET':
                    if route=='/api/capabilities':result=app.capabilities()
                    elif route=='/api/materials':result={'ok':True,'materials':app.recipes.search((query.get('q') or [''])[0],limit=100)}
                    elif route=='/api/projects':result={'ok':True,'projects':app.graphs.list()}
                    elif route.startswith('/api/projects/'):
                        result=app.graphs.read(route.rsplit('/',1)[1]);result['controls']=derive_sliders(result['graph'],app.catalog)
                    elif route.startswith('/api/jobs/'):result=app.jobs.get(route.rsplit('/',1)[1])
                    elif '/files/' in route:
                        _,_,_,bid,_,name=route.split('/')
                        return {'status':200,'base64':base64.b64encode(app.builds.artifact(bid,name).read_bytes()).decode(),'mime':'image/png'}
                    elif route=='/api/export':
                        return {'status':200,'base64':base64.b64encode(app.builds.export(query['build_id'][0])).decode(),'mime':'application/zip'}
                    else:raise ServiceError('NOT_FOUND','Unsupported test adapter route.')
                else:
                    if route=='/api/projects':result=app.instantiate(body['recipe_id'])
                    elif route=='/api/patch':result=app.patch(**body)
                    elif route=='/api/jobs':result=app.jobs.submit(body)
                    elif route.endswith('/cancel'):result=app.jobs.cancel(route.split('/')[-2])
                    else:raise ServiceError('NOT_FOUND','Unsupported test adapter route.')
                return {'status':200,'json':result}
            except ServiceError as exc:return {'status':409 if 'CONFLICT' in exc.code else 400,'json':exc.result()}
        page.expose_function('fixtureTransport',transport)
        static=Path(__file__).resolve().parents[2]/'src/mm_mcp/play/static'
        html=(static/'index.html').read_text()
        import re
        html=re.sub(r'<script[^>]*src=[^>]+></script>','',html)
        html=re.sub(r'<link[^>]*>','',html)
        page.set_content(html)
        page.add_style_tag(content=(static/'style.css').read_text())
        page.evaluate("""() => {
            for (const name of ['localStorage','sessionStorage']) {
              const data={}; Object.defineProperty(window,name,{value:{getItem:k=>data[k]||null,setItem:(k,v)=>data[k]=v}});
            }
            window.fetch=async (path,options={})=>{
              const out=await window.fixtureTransport(path,options.method||'GET',options.body?JSON.parse(options.body):null);
              const body=out.base64?Uint8Array.from(atob(out.base64),c=>c.charCodeAt(0)):JSON.stringify(out.json);
              return new Response(body,{status:out.status,headers:{'Content-Type':out.mime||'application/json'}});
            };
        }""")
        page.add_script_tag(content=(static/'three.min.js').read_text())
        page.add_script_tag(content=(static/'app.js').read_text())
        page.locator('.recipe-row button').first.click()
        page.wait_for_function("document.getElementById('material-name').textContent === 'fixture'")
        page.locator('#size').select_option('128')
        row=page.locator('.control').filter(has=page.locator('code',has_text='surface/param0'))
        number=row.locator('input[type=number]');number.fill('13');number.dispatch_event('change')
        page.wait_for_function("!document.getElementById('download').disabled",timeout=20000)
        assert page.locator('#evidence img').count()>=3
        if os.environ.get('MM_REQUIRE_WEBGL_TEST')=='1':
            assert page.locator('#viewport canvas').count()==1, page.locator('#viewport').inner_text()
        else:
            assert page.locator('#viewport canvas').count()==1 or 'WebGL context' in page.locator('#viewport').inner_text()
        page.wait_for_function("[...document.querySelectorAll('#evidence img')].every(img=>img.naturalWidth>0)")
        with page.expect_download() as event:page.locator('#download').click()
        downloaded=event.value;destination=tmp_path/'download.zip';downloaded.save_as(destination)
        with zipfile.ZipFile(destination) as z:
            graph=json.loads(z.read('material.ptex'))
            assert next(n for n in graph['nodes'] if n['name']=='surface')['parameters']['param0']==13
        assert not errors,errors
        screenshot=os.environ.get('MM_BROWSER_EVIDENCE')
        if screenshot:page.screenshot(path=screenshot,full_page=True)
        # A shared MCP-style edit makes a stale browser patch fail rather than overwrite.
        pid=app.graphs.list()[0]['id'];revision=app.graphs.read(pid)['revision']
        app.patch(pid,revision,[{'op':'set_controls','values':{'surface/param0':18}}],'external-client')
        number=page.locator('.control').filter(has=page.locator('code',has_text='surface/param0')).locator('input[type=number]')
        number.fill('14');number.dispatch_event('change')
        page.wait_for_function("document.getElementById('status').classList.contains('error')")
        assert app.graphs.read(pid)['revision']==revision+1
        assert page.locator('#download').is_disabled()
        browser.close()
