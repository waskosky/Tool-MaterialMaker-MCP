import base64
import inspect
import io
import sys
import time
import zipfile

from mm_mcp import tools
from test_blender_mesh import triangle_glb
from test_blender_service import synthetic_worker
from test_http import call


def test_blender_http_requires_existing_session_auth(http_service):
    status, _, body = call(http_service, '/api/blender/capabilities', headers={'X-MM-Token': ''})
    assert status == 401 and body['code'] == 'AUTH_REQUIRED'
    status, _, body = call(http_service, '/api/blender/capabilities')
    assert status == 200 and body['configured'] is False
    status, _, body = call(http_service, '/api/blender/jobs', {'operation': 'inspect'})
    assert status == 400 and body['code'] == 'BLENDER_DISABLED'


def test_blender_http_upload_job_result_and_export(http_service):
    _, _, app = http_service
    app.cfg.blender_binary = sys.executable
    app.blender.runner = synthetic_worker
    app.cfg.base_path = '/workshop/'
    raw = triangle_glb()
    status, _, uploaded = call(http_service, '/workshop/api/blender/meshes', {'name': 'triangle.glb', 'data_base64': base64.b64encode(raw).decode()})
    assert status == 200, uploaded
    status, _, job = call(http_service, '/api/blender/jobs', {'operation': 'inspect', 'mesh_id': uploaded['mesh']['mesh_id']})
    assert status == 200, job
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = call(http_service, '/workshop/api/jobs/' + job['job_id'])[2]
        if state['state'] in ('complete', 'failed'):
            break
        time.sleep(.02)
    assert state['state'] == 'complete', state
    rid = state['result']['result_id']
    assert call(http_service, '/api/blender/results/' + rid)[2]['manifest']['operation'] == 'inspect'
    status, _, downloaded = call(http_service, f'/api/blender/results/{rid}/files/source_mesh.glb')
    assert status == 200 and downloaded == raw
    status, _, archive = call(http_service, f'/workshop/api/blender/results/{rid}/export')
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert bundle.read('source_mesh.glb') == raw
    assert call(http_service, f'/api/blender/results/{rid}/files/../private')[0] in (400, 404)
    assert call(http_service, '/api/blender/meshes', {'name': 'bad', 'data_base64': '', 'path': '/tmp/private'})[0] == 400


def test_typed_blender_mcp_tools_use_shared_service(app, monkeypatch):
    monkeypatch.setattr(tools, 'get_service', lambda: app)
    assert tools.blender_capabilities()['configured'] is False
    names = {fn.__name__ for fn in tools.TOOLS}
    assert {'blender_capabilities', 'blender_mesh_upload', 'blender_job_submit', 'blender_job_get', 'blender_job_cancel', 'blender_result_get', 'blender_result_file', 'blender_result_export'} <= names
    signature = inspect.signature(tools.blender_job_submit)
    assert list(signature.parameters) == ['operation', 'build_id', 'mesh_id', 'specimen', 'resolution', 'unwrap', 'uv_scale']
    assert tools.blender_job_submit('inspect')['code'] == 'BLENDER_DISABLED'


def test_typed_mcp_artifact_download_verifies_bytes(blender_app, monkeypatch):
    # Reuse the real service fixture exported by the sibling module.
    app = blender_app
    monkeypatch.setattr(tools, 'get_service', lambda: app)
    result = app.blender.execute(app.blender.prepare({'operation': 'inspect'}))
    file = tools.blender_result_file(result['result_id'], 'request.json')
    assert file['ok'] is True and file['bytes'] == len(base64.b64decode(file['data_base64']))
    exported = tools.blender_result_export(result['result_id'])
    assert exported['ok'] is True and exported['bytes'] > 0


from test_blender_service import blender_app
