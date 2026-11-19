"""Controlled lifecycle contracts through MCP and HTTP; no native CAD in these tests."""
import asyncio
import json
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from autocad_mcp import state
from autocad_mcp.server import mcp
from autocad_mcp.cad.backends.http_backend import BridgeRemoteError
from autocad_mcp.cad.errors import UnsupportedOperationError
from test_http_backend import setup_backend  # Shared authenticated fake transport.

DOCUMENT = dict(document_id='new-doc',name='Drawing2.dwg',revision=4,
                units=dict(code=4,name='Millimeters'),managed=True,read_only=False,
                output_directory='D:/outputs',source_artifact_id=None)
ARTIFACT = dict(artifact_id='artifact-a',file_path='D:/outputs/fixture.dwg',source_document_id='new-doc',
                saved_revision=4,sha256='a'*64,bytes=1234,saved_at='2026-11-19T12:00:00Z',units_code=4,state='saved')

def response(bridge, data, result):
    return dict(instance_id=bridge.instance,request_id=data['request_id'],status='succeeded',
                document_id=result.get('document_id',result.get('source_document_id')),revision=4,result=result)

def enable(bridge):
    bridge.operations += ['create_working_document','get_document_info','save_document','reopen_artifact']
    # Capabilities are normally assembled by the fixture's handler. Add this
    # additive capability at the HTTP response boundary via the mock instance.
    bridge.controlled_documents = True

def test_lifecycle_identity_and_legacy_binding(setup_backend):
    backend,bridge=setup_backend
    enable(bridge)
    bridge.post_response=lambda data:response(bridge,data,DOCUMENT)
    job=backend.document_job('create_working_document',{'units':'millimeters','output_directory':'D:/outputs'},
                             instance_id='instance-a',request_id='new-work')
    assert job['result']['document_id']=='new-doc' and job['result']['managed']
    sent=json.loads(bridge.calls[-1].content)
    assert sent['instance_id']=='instance-a' and sent['document_id'] is None
    assert backend.runtime_status()['bound_document_id']=='doc-a'
    bridge.post_response=lambda data:response(bridge,data,ARTIFACT)
    saved=backend.document_job('save_document',{'file_name':'fixture.dwg'},instance_id='instance-a',
                               document_id='new-doc',request_id='save-work',expected_revision=4)
    assert saved['result']['sha256']=='a'*64
    readonly={**DOCUMENT,'document_id':'reopened','managed':False,'read_only':True,
              'source_artifact_id':'artifact-a','output_directory':None,'artifact':ARTIFACT}
    bridge.post_response=lambda data:response(bridge,data,readonly)
    reopened=backend.document_job('reopen_artifact',{'artifact_id':'artifact-a'},
                                  instance_id='instance-a',request_id='reopen-work')
    assert reopened['document_id']=='reopened' and not reopened['result']['managed']
    assert backend.runtime_status()['bound_document_id']=='doc-a'

def test_old_instance_is_rejected_before_post(setup_backend):
    backend,bridge=setup_backend
    enable(bridge)
    with pytest.raises(BridgeRemoteError,match='INSTANCE_MISMATCH'):
        backend.document_job('create_working_document',{},instance_id='old-instance',request_id='create')
    assert not any(x.method=='POST' for x in bridge.calls)

def test_older_bridge_lifecycle_is_not_silently_emulated(setup_backend):
    backend,bridge=setup_backend
    with pytest.raises(UnsupportedOperationError,match='no fallback'):
        backend.document_job('create_working_document',{},instance_id='instance-a',request_id='create')
    assert not any(x.method=='POST' for x in bridge.calls)

@pytest.mark.parametrize('fault',['id','revision','managed','artifact'])
def test_invalid_reopened_result_cannot_grant_write_access(setup_backend,fault):
    backend,bridge=setup_backend;enable(bridge)
    result={**DOCUMENT,'managed':False,'read_only':True,'source_artifact_id':'artifact-a','artifact':ARTIFACT}
    def bad(data):
        value=response(bridge,data,result)
        if fault=='id':value['document_id']='wrong'
        if fault=='revision':value['revision']=100
        if fault=='managed':value['result']={**result,'managed':True,'read_only':False}
        if fault=='artifact':value['result']={**result,'source_artifact_id':'wrong'}
        return value
    bridge.post_response=bad
    with pytest.raises(BridgeRemoteError) as e:
        backend.document_job('reopen_artifact',{'artifact_id':'artifact-a'},instance_id='instance-a',request_id='reopen')
    assert e.value.outcome=='outcome_unknown'
    assert sum(x.method=='POST' for x in bridge.calls)==1

def test_lost_save_response_is_not_replayed(setup_backend):
    backend,bridge=setup_backend;enable(bridge);bridge.timeout_post=True
    with pytest.raises(BridgeRemoteError) as e:
        backend.document_job('save_document',{'file_name':'fixture.dwg'},instance_id='instance-a',
                             document_id='new-doc',request_id='save-stable',expected_revision=4)
    assert e.value.request_id=='save-stable' and e.value.outcome=='outcome_unknown'
    assert sum(x.method=='POST' for x in bridge.calls)==1

@pytest.mark.parametrize('tool,args',[
    ('create_working_drawing',dict(instance_id='i',request_id='',units='millimeters')),
    ('create_working_drawing',dict(instance_id='i',request_id='r',units='guess')),
    ('save_working_drawing',dict(instance_id='i',document_id='d',request_id='r',expected_revision=-1,file_name='x.dwg')),
    ('save_working_drawing',dict(instance_id='i',document_id='d',request_id='r',expected_revision=1,file_name='../x.dwg')),
    ('save_working_drawing',dict(instance_id='i',document_id='d',request_id='r',expected_revision=1,file_name='bad?.dwg')),
    ('reopen_saved_drawing',dict(instance_id='i',artifact_id='',request_id='r')),
])
def test_bad_lifecycle_args_do_not_create_backend(monkeypatch,tool,args):
    state.close_backend()
    monkeypatch.setattr(state,'create_backend',lambda _:pytest.fail('Invalid input reached backend'))
    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            assert (await client.call_tool(tool,args)).isError
    asyncio.run(run())

def test_com_never_emulates_controlled_lifecycle():
    from autocad_mcp.cad.backends.com_backend import COMBackend
    from autocad_mcp.config import Config
    backend=COMBackend(Config(cad_type='AutoCAD',prog_id='unused'))
    state.close_backend()
    state._backend=backend
    try:
        with pytest.raises(UnsupportedOperationError,match='no fallback'):
            state.document_job('create_working_document',{},instance_id='i',request_id='r')
        assert backend._thread is None
    finally:state.close_backend()

def test_mcp_typed_document_and_artifact_results(monkeypatch):
    class Backend:
        def document_job(self,operation,args,**identity):
            result=ARTIFACT if operation=='save_document' else DOCUMENT
            return dict(instance_id='instance-a',request_id=identity.get('request_id','read'),status='succeeded',
                        document_id='new-doc',revision=4,result=result)
        def close(self):pass
    state.close_backend();monkeypatch.setattr(state,'create_backend',lambda _:Backend())
    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            new=await client.call_tool('create_working_drawing',dict(instance_id='instance-a',request_id='create'))
            assert not new.isError and new.structuredContent['result']['units']['code']==4
            saved=await client.call_tool('save_working_drawing',dict(instance_id='instance-a',document_id='new-doc',
                expected_revision=4,request_id='save',file_name='fixture.dwg'))
            assert not saved.isError and saved.structuredContent['result']['artifact_id']=='artifact-a'
    try:asyncio.run(run())
    finally:state.close_backend()
