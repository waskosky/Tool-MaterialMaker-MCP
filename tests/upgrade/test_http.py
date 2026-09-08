import http.client
import io
import json
import zipfile
import pytest

def call(fixture,path,body=None,headers=None,raw=None):
    server,token,_=fixture
    connection=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
    default={'X-MM-Token':token}
    data=raw if raw is not None else json.dumps(body) if body is not None else None
    if data is not None:default['Content-Type']='application/json'
    default.update(headers or {})
    connection.request('POST' if data is not None else 'GET',path,body=data,headers=default)
    response=connection.getresponse();blob=response.read();status=response.status;meta=dict(response.getheaders());connection.close()
    return status,meta,json.loads(blob) if 'application/json' in meta.get('Content-Type','') else blob

def test_auth_required_and_static_has_security_headers(http_service):
    code,headers,body=call(http_service,'/api/capabilities',headers={'X-MM-Token':''})
    assert code==401 and body['code']=='AUTH_REQUIRED'
    code,headers,body=call(http_service,'/',headers={'X-MM-Token':''})
    assert code==200 and b'Material Workshop' in body
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert 'Access-Control-Allow-Origin' not in headers

@pytest.mark.parametrize('header,value',[('Host','evil.example'),('Origin','https://evil.example'),('Sec-Fetch-Site','cross-site')])
def test_cross_origin_and_dns_rebinding_rejected(http_service,header,value):
    code,_,_=call(http_service,'/api/capabilities',headers={header:value});assert code==403

@pytest.mark.parametrize('path',['/static/../config.py','/static/%2e%2e','/api/builds/../files/live.json','/api/comparisons/../../state.sqlite3'])
def test_paths_are_not_filesystem_proxies(http_service,path):
    code,_,_=call(http_service,path);assert code in (400,404)

@pytest.mark.parametrize('raw',['{"recipe_id":"fixture","recipe_id":"x"}','{"size":NaN}','{"size":1e9999}','[]'])
def test_malformed_body_is_structured_error(http_service,raw):
    code,_,body=call(http_service,'/api/jobs',raw=raw);assert code==400 and body['ok'] is False

def test_wrong_content_type_rejected(http_service):
    code,_,body=call(http_service,'/api/jobs',body={},headers={'Content-Type':'text/plain'});assert code==400

def test_shared_revision_patch_and_export(http_service):
    code,_,p=call(http_service,'/api/projects',{'recipe_id':'fixture'});assert code==200
    pid=p['project_id'];request={'project_id':pid,'expected_revision':0,'operations':[{'op':'set_controls','values':{'surface/param0':13}}],'idempotency_key':'http-change-1'}
    code,_,a=call(http_service,'/api/patch',request);assert code==200 and a['revision']==1
    assert call(http_service,'/api/patch',request)[2]==a
    code,_,_=call(http_service,'/api/patch',{**request,'idempotency_key':'http-other'});assert code==409
    code,_,built=call(http_service,'/api/render',{'project_id':pid,'revision':1,'size':32});assert code==200,built
    bid=built['build_id']
    code,_,image=call(http_service,f'/api/builds/{bid}/files/material_albedo.png');assert code==200 and image.startswith(b'\x89PNG')
    code,headers,data=call(http_service,'/api/export?build_id='+bid);assert code==200
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        graph=json.loads(z.read('material.ptex'))
        assert next(n for n in graph['nodes'] if n['name']=='surface')['parameters']['param0']==13
    code,_,_=call(http_service,'/api/export?material_id=fixture');assert code==400

def test_unknown_endpoint_rejected(http_service):
    assert call(http_service,'/api/arbitrary_file')[0]==404
