"""Real HTTP adapter + real MCP dispatch against a synthetic native transport.

These prove DTO/identity/no-replay behavior, never CAD geometry or DWG validity.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from autocad_mcp.cad.backends.http_backend import HTTPBackend, BridgeRemoteError
from autocad_mcp.cad.managed_contract import ManagedContractError, validate, SCHEMA_SHA256
from autocad_mcp.cad.managed_profile import ManagedCAD, entity_dto
from autocad_mcp.config import Config
import autocad_mcp.managed_server as server

OPS=[dict(id='line',operation='draw_line',args=dict(start=[0,0,0],end=[20,0,0],layer='0')),
     dict(id='circle',operation='draw_circle',args=dict(center=[10,10,0],radius=3,layer='0')),
     dict(id='label',operation='draw_text',args=dict(point=[0,15,0],text='CADER FIXTURE',height=2,layer='0'))]

def entity(kind='AcDbText'):
    row=dict(object_id=1,type=kind,layer='0',geometry_complete=True,visible=True,thickness=0,
        linetype='ByLayer',linetype_scale=1,lineweight=-1,color_index=256,
        layer_properties=dict(name='0',linetype='Continuous',color_index=7,lineweight=-3,is_off=False,is_frozen=False,is_locked=False))
    if kind=='AcDbLine':row.update(start_point=[0,0,0],end_point=[20,0,0])
    if kind=='AcDbCircle':row.update(center=[10,10,0],radius=3,normal=[0,0,1])
    if kind=='AcDbText':row.update(insertion_point=[0,15,0],height=2,text_string='CADER FIXTURE',normal=[0,0,1],rotation=0,
        width_factor=1,oblique=0,horizontal_mode=0,vertical_mode=0,mirrored_x=False,mirrored_y=False,text_style='MCP_CJK',
        font=dict(typeface='SimSun',bold=False,italic=False,big_font=''))
    return row

class NativeFixture:
    def __init__(self):
        self.instance='instance-1';self.calls=[];self.docs={};self.records={};self.entities=[];self.artifacts={}
        self.rollback=False;self.lose_response=False;self.posts=0
    def envelope(self,rid,**values):
        return dict(instance_id=self.instance,request_id=rid,status='succeeded',**values)
    def __call__(self,request):
        self.calls.append(request)
        assert request.headers['authorization']=='Bearer '+('fixture-token-'*4)
        path=request.url.path
        if path=='/v1/health':return httpx.Response(200,json=dict(instance_id=self.instance,protocol_version='1',status='ready'))
        if path=='/v1/capabilities':return httpx.Response(200,json=dict(instance_id=self.instance,protocol_version='1',
            operations=['create_working_document','get_document_info','save_document','reopen_artifact','query_entities_page'],
            controlled_documents=True,atomic_batch=True,batch_operations=['draw_line','draw_circle','draw_text'],
            request_records=True,failure_revision='cad_thread_observed',client_profiles=['cader-cad/1'],query_pagination=True,max_batch_operations=200))
        if path=='/v1/status':return httpx.Response(200,json=self.envelope('status',result=dict(documents=list(self.docs.values()),active_document_id=None,revision_mode='observed_database_events')))
        if path.startswith('/v1/requests/'):
            rid=path.split('/')[-1]
            if rid not in self.records:return httpx.Response(404,json=dict(instance_id=self.instance,error=dict(code='JOB_NOT_FOUND',outcome='not_executed')))
            return httpx.Response(200,json=self.records[rid])
        assert request.method=='POST'
        self.posts+=1;data=json.loads(request.content);rid=data['request_id'];op='_batch' if path=='/v1/batch' else data['operation']
        doc=data.get('document_id');args=data.get('args',{})
        assert data['instance_id']==self.instance
        result=None;revision=self.docs.get(doc,{}).get('revision');target=doc
        error=None
        if op=='create_working_document':
            target='work-1';revision=7
            result=dict(document_id=target,name='Drawing2.dwg',revision=revision,units=dict(code=0,name='Undefined'),managed=True,read_only=False,
                        output_directory=args['output_directory'],source_artifact_id=None)
            self.docs[target]=deepcopy(result)
        elif op=='get_document_info':result=deepcopy(self.docs[doc])
        elif data.get('expected_revision')!=revision:
            error=dict(code='REVISION_CONFLICT',message='stale',outcome='not_executed')
        elif op=='_batch':
            assert data['client_profile']=='cader-cad/1' and data['atomic']
            revision+=5;self.docs[doc]['revision']=revision
            if self.rollback:error=dict(code='INVALID_ARGUMENT',message='fixture rollback',outcome='rolled_back')
            else:
                assert data['operations'][2]['args']['position']==[0,15,0] and data['operations'][2]['args']['rotation']==0
                assert 'point' not in data['operations'][2]['args']
                self.entities=[entity('AcDbLine'),entity('AcDbCircle'),entity('AcDbText')]
                for i,row in enumerate(self.entities,1):row['object_id']=i
                result=[dict(id=step['id'],result=i) for i,step in enumerate(data['operations'],1)]
        elif op=='query_entities_page':
            result=dict(document_id=doc,revision=revision,items=deepcopy(self.entities),count=len(self.entities),has_more=False,next_cursor=None,unsupported_geometry_types=[])
        elif op=='save_document':
            output=Path(self.docs[doc]['output_directory'])/args['file_name'];output.write_bytes(b'AC1032-synthetic-not-a-real-dwg')
            result=dict(artifact_id='artifact-1',file_path=str(output),source_document_id=doc,saved_revision=revision,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest(),bytes=output.stat().st_size,saved_at='2026-11-19T00:00:00Z',units_code=0,state='saved')
            self.artifacts['artifact-1']=result
        elif op=='reopen_artifact':
            target='verification-1';revision=3
            result=dict(document_id=target,name='saved.dwg',revision=revision,units=dict(code=0,name='Undefined'),managed=False,read_only=True,
                        output_directory=None,source_artifact_id=args['artifact_id'],artifact=self.artifacts[args['artifact_id']])
            self.docs[target]=deepcopy(result)
        else:raise AssertionError(op)
        job=self.envelope(rid,document_id=target,revision=revision,result=result)
        if error:job.update(status='rolled_back' if error['outcome']=='rolled_back' else 'failed',result=None,error=error)
        if data.get('client_profile'):
            self.records[rid]=dict(instance_id=self.instance,request_id=rid,operation=op,request_document_id=doc,
                expected_revision=data.get('expected_revision'),source_artifact_id=args.get('artifact_id') if op=='reopen_artifact' else None,
                client_profile='cader-cad/1',native_request_hash='A'*64,job=deepcopy(job))
        if self.lose_response and op=='_batch':raise httpx.ReadTimeout('lost accepted response',request=request)
        return httpx.Response(200,json=job)

@pytest.fixture
def profile(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCAD_BRIDGE_TOKEN','fixture-token-'*4)
    native=NativeFixture();backends=[]
    def fresh():
        client=httpx.Client(base_url='http://127.0.0.1:8765',transport=httpx.MockTransport(native))
        backend=HTTPBackend(Config(cad_type='AutoCAD',prog_id='unused',backend='http'),client=client);backends.append(backend)
        return ManagedCAD(backend)
    output=tmp_path/'.cader/artifacts';output.mkdir(parents=True)
    service=fresh()
    yield service,native,output,fresh
    for backend in backends:backend.close()

def create(service,output):
    return service.create_working_document(instance_id='instance-1',request_id='create',units='unitless',managed=True,output_directory=str(output))

def test_full_dto_flow_over_real_mcp_dispatch(profile,monkeypatch):
    service,native,output,_=profile;monkeypatch.setattr(server,'_service',service)
    async def run():
        async with create_connected_server_and_client_session(server.mcp) as client:
            assert len((await client.list_tools()).tools)==7
            async def call(name,args,schema):
                result=await client.call_tool(name,args)
                assert not result.isError,result.content
                return validate(schema,result.structuredContent)
            await call('get_backend_status',{},'status')
            created=await call('create_working_document',dict(instance_id='instance-1',request_id='create',units='unitless',managed=True,output_directory=str(output)),'create')
            assert created['document']['revision']==7
            common=dict(instance_id='instance-1',document_id='work-1')
            job=await call('execute_atomic_batch',dict(**common,request_id='batch',expected_revision=7,operations=OPS),'job')
            assert job['revision']==12 and job['request_document_id']==job['result_document_id']=='work-1'
            page=await call('query_entities_page',dict(**common,expected_revision=12,cursor=None,limit=1000),'query')
            assert len(page['items'])==3 and not page['unsupported_geometry_types']
            saved=await call('save_document_as',dict(**common,request_id='save',expected_revision=12,output_path=str(output/'fixture.dwg'),overwrite=False),'save')
            reopened=await call('reopen_document',dict(instance_id='instance-1',request_id='reopen',artifact_id=saved['artifact']['artifact_id']),'reopen')
            assert reopened['document']['managed'] is False and reopened['document']['read_only'] is True
            observed=await call('get_job_status',dict(request_id='reopen'),'job')
            assert observed['request_document_id'] is None and observed['result_document_id']=='verification-1' and observed['source_artifact_id']=='artifact-1'
    asyncio.run(run())

def test_failed_batch_uses_authoritative_post_abort_revision(profile):
    service,native,output,_=profile;create(service,output);native.rollback=True
    job=service.execute_atomic_batch(instance_id='instance-1',request_id='rollback',document_id='work-1',expected_revision=7,operations=OPS)
    assert job['status']=='failed' and job['outcome']=='rolled_back' and job['revision']==12
    page=service.query_entities_page(instance_id='instance-1',document_id='work-1',expected_revision=12,cursor=None,limit=1000)
    assert page['items']==[]
    with pytest.raises(BridgeRemoteError,match='REVISION_CONFLICT'):
        service.query_entities_page(instance_id='instance-1',document_id='work-1',expected_revision=7,cursor=None,limit=1000)

def test_lost_post_response_is_queried_by_fresh_python_adapter_without_replay(profile):
    service,native,output,fresh=profile;create(service,output);native.lose_response=True
    before=native.posts
    with pytest.raises(BridgeRemoteError) as error:
        service.execute_atomic_batch(instance_id='instance-1',request_id='lost',document_id='work-1',expected_revision=7,operations=OPS)
    assert error.value.outcome=='outcome_unknown'
    # A read-only document preflight plus exactly one batch POST; no resubmission.
    assert native.posts-before==2
    new=fresh();reconciled=new.get_job_status('lost')
    assert reconciled['status']=='succeeded' and reconciled['operation']=='execute_atomic_batch' and reconciled['revision']==12
    assert native.posts-before==2

@pytest.mark.parametrize('field,value',[('rotation',30),('mirrored_x',True),('width_factor',2),('oblique',15),
    ('linetype','DASHED'),('normal',[0,1,0]),('visible',False),('thickness',1),('geometry_complete',False)])
def test_unsupported_geometry_attributes_are_not_silently_normalized(field,value):
    row=entity();row[field]=value;assert entity_dto(row) is None

def test_query_reports_unsupported_type_and_attributes(profile):
    service,native,output,_=profile;create(service,output)
    row=entity();row['rotation']=30;native.entities=[row]
    page=service.query_entities_page(instance_id='instance-1',document_id='work-1',expected_revision=7,cursor=None,limit=1000)
    assert page['items']==[] and page['unsupported_geometry_types']==['AcDbText']

def test_invalid_dto_never_posts(profile):
    service,native,output,_=profile
    with pytest.raises(ManagedContractError):
        service.create_working_document(instance_id='bad:instance',request_id='create',units='unitless',managed=True,output_directory=str(output))
    assert native.posts==0

def test_unmanaged_verification_document_cannot_be_used_for_saving(profile):
    service,native,output,_=profile;create(service,output)
    native.docs['read-only']={**native.docs['work-1'],'document_id':'read-only','managed':False,'read_only':True,'output_directory':None}
    with pytest.raises(ManagedContractError):
        service.save_document_as(instance_id='instance-1',request_id='save',document_id='read-only',expected_revision=7,output_path=str(output/'saved.dwg'),overwrite=False)
    assert not any('save_document' in request.content.decode() for request in native.calls if request.method=='POST')

def test_missing_or_foreign_request_metadata_is_unresolved(profile):
    service,native,output,_=profile;create(service,output)
    with pytest.raises(BridgeRemoteError) as missing:service.get_job_status('missing')
    assert missing.value.outcome=='outcome_unknown'
    native.records['create']['client_profile']=None
    with pytest.raises(BridgeRemoteError,match='PROTOCOL_ERROR'):service.get_job_status('create')

def test_runtime_schema_has_exact_approved_bytes():
    from autocad_mcp.cad import managed_contract
    raw=(Path(managed_contract.__file__).parents[1]/'contracts/cader-v1.schemas.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==SCHEMA_SHA256

def test_explicit_profile_rejects_default_com_without_connecting(monkeypatch):
    server.close_service()
    monkeypatch.setattr(server,'load_config',lambda:Config(cad_type='AutoCAD',prog_id='unused'))
    with pytest.raises(ManagedContractError,match='HTTP_BACKEND_REQUIRED'):server.service()

def test_multiple_clients_only_close_the_final_service(monkeypatch):
    closed=[]
    class Backend:
        def close(self):closed.append(True)
    class Service:
        backend=Backend()
    monkeypatch.setattr(server,'_service',Service());monkeypatch.setattr(server,'_sessions',2)
    server.stop_session();assert not closed and server._service is not None
    server.stop_session();assert closed==[True] and server._service is None

def test_noncanonical_save_path_is_rejected_before_save_post(profile):
    service,native,output,_=profile;create(service,output)
    with pytest.raises(ManagedContractError,match='OUTPUT_PATH_NOT_ALLOWED'):
        service.save_document_as(instance_id='instance-1',request_id='save',document_id='work-1',expected_revision=7,
            output_path=str(output/'other/../saved.dwg'),overwrite=False)
    assert not any('save_document' in request.content.decode() for request in native.calls if request.method=='POST')

def test_zero_length_existing_line_is_unsupported():
    row=entity('AcDbLine');row['end_point']=row['start_point'];assert entity_dto(row) is None
