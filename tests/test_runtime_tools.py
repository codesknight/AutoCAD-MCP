"""Exercise new tools through MCP validation and dispatch, without CAD."""
import asyncio
import json
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from autocad_mcp import state
from autocad_mcp.server import mcp
from autocad_mcp.cad.backends.com_backend import COMBackend
from autocad_mcp.config import Config

LINE={'id':'line-1','operation':'draw_line','args':{'start':[0,0,0],'end':[1,2,0]}}

def test_com_status_does_not_start_worker_or_cad():
    backend=COMBackend(Config(cad_type='AutoCAD',prog_id='unused'))
    try:
        status=backend.runtime_status()
        assert status['state']=='not_started'
        assert status['connection_state']=='not_probed'
        assert not status['capabilities']['atomic_batch']
        assert not status['capabilities']['query_pagination']
        assert backend._thread is None
    finally:
        backend.close()

def test_native_cleanup_waits_for_process_exit_and_preserves_originals():
    from scripts.verify_runtime_tools import wait_for_owned_exit
    snapshots=iter([{10,20},{10,20},{10},{10}])
    wait_for_owned_exit(20,{10},lambda:next(snapshots))
    with pytest.raises(AssertionError,match='original'):
        wait_for_owned_exit(20,{10},lambda:set())

@pytest.mark.parametrize('tool,args',[
    ('execute_atomic_batch',{'document_id':'doc-a','operations':[]}),
    ('execute_atomic_batch',{'document_id':'doc-a','operations':[LINE]*201}),
    ('execute_atomic_batch',{'document_id':'doc-a','operations':[LINE,LINE]}),
    ('execute_atomic_batch',{'document_id':'','operations':[LINE]}),
    ('execute_atomic_batch',{'document_id':'doc-a','operations':[dict(LINE,operation='save')]}),
    ('execute_atomic_batch',{'document_id':'doc-a','operations':[dict(LINE,args={'start':[0,0,0],'end':[0,0,0]})]}),
    ('execute_atomic_batch',{'document_id':'doc-a','operations':[dict(LINE,args={'start':[0,0],'end':[1,0,0]})]}),
    ('execute_atomic_batch',{'document_id':'doc-a','operations':[dict(LINE,args={'start':[0,0,0],'end':[1,0,0],'unexpected':1})]}),
    ('query_entities_page',{'document_id':'doc-a','limit':1001}),
    ('query_entities_page',{'document_id':'doc-a','fields':['not-supported']}),
    ('query_entities_page',{'document_id':'doc-a','fields':['type','type']}),
    ('get_job_status',{'request_id':'../unsafe'}),
])
def test_invalid_runtime_input_never_creates_backend(tool,args,monkeypatch):
    state.close_backend()
    def forbidden(*args):
        pytest.fail('Invalid runtime input reached backend creation')
    monkeypatch.setattr(state,'create_backend',forbidden)
    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            assert (await client.call_tool(tool,args)).isError
    asyncio.run(run())

def test_explicit_document_and_job_envelopes_over_mcp(monkeypatch):
    calls=[]
    envelope=dict(instance_id='instance-a',request_id='stable-request',status='succeeded',
                  document_id='explicit-doc',revision=7,result=[{'id':'line-1','result':42}])
    class Backend:
        def execute_batch_job(self,operations,**kwargs):
            calls.append((operations,kwargs))
            return envelope
        def get_job(self,request_id):
            assert request_id=='stable-request'
            return envelope
        def query_page(self,document_id,**kwargs):
            assert document_id=='explicit-doc'
            assert kwargs['cursor']=='opaque-cursor'
            return dict(document_id=document_id,revision=7,items=[{'object_id':42,'type':'AcDbLine','layer':'0'}],
                        count=1,has_more=False,next_cursor=None,unsupported_geometry_types=[])
        def close(self): pass
    state.close_backend()
    monkeypatch.setattr(state,'create_backend',lambda _:Backend())
    async def run():
        async with create_connected_server_and_client_session(mcp) as client:
            result=await client.call_tool('execute_atomic_batch',dict(document_id='explicit-doc',operations=[LINE],request_id='stable-request',expected_revision=6))
            assert not result.isError
            assert result.structuredContent['request_id']=='stable-request'
            assert result.structuredContent['revision']==7
            result=await client.call_tool('get_job_status',{'request_id':'stable-request'})
            assert not result.isError and result.structuredContent['document_id']=='explicit-doc'
            result=await client.call_tool('query_entities_page',{'document_id':'explicit-doc','cursor':'opaque-cursor','fields':['type'],'limit':1})
            assert not result.isError and result.structuredContent['count']==1
    try:
        asyncio.run(run())
        assert calls==[([LINE],dict(document_id='explicit-doc',request_id='stable-request',expected_revision=6))]
    finally:
        state.close_backend()
