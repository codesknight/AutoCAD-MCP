"""Opt-in MCP -> HTTP -> AutoCAD controlled drawing/file qualification.

Requires an already-started dedicated CAD process and loaded Bridge. Never launches
CAD, changes the default backend, opens user DWGs, retries unknown writes, or cleans
up a process. The operator closes only the recorded owned process afterwards.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = [
    dict(id='layer',operation='create_layer',args=dict(name='Controlled',color=3)),
    dict(id='line',operation='draw_line',args=dict(start=[0,0,0],end=[10,0,0],layer='Controlled')),
    dict(id='circle',operation='draw_circle',args=dict(center=[20,0,0],radius=2,layer='Controlled')),
    dict(id='arc',operation='draw_arc',args=dict(center=[30,0,0],radius=3,start_angle=0,end_angle=90,layer='Controlled')),
    dict(id='rect',operation='draw_rectangle',args=dict(corner1=[0,10,0],corner2=[10,15,0],layer='Controlled')),
    dict(id='poly',operation='draw_polyline',args=dict(points=[[20,10,0],[25,10,0],[25,15,0]],closed=True,layer='Controlled')),
    dict(id='text',operation='draw_text',args=dict(position=[0,20,0],text='受控 MCP 文字',height=2.5,rotation=30,layer='Controlled')),
    dict(id='mtext',operation='draw_mtext',args=dict(position=[20,20,0],text='第一行\\P第二行',width=40,height=3,layer='Controlled')),
    dict(id='dim',operation='add_dimension',args=dict(start=[0,0,0],end=[10,0,0],text_position=[5,5,0])),
]

def canonical(items):
    # Aliases belong to one document; handles/bounds are not geometry identities.
    def normalize(value):
        if isinstance(value,float):return round(value,7)
        if isinstance(value,list):return [normalize(x) for x in value]
        if isinstance(value,dict):return {k:normalize(v) for k,v in value.items() if k not in {'object_id','handle','bounding_box'}}
        return value
    return sorted(json.dumps(normalize(x),sort_keys=True,ensure_ascii=False) for x in items)

async def verify(args, result):
    settings=json.loads((args.bridge_dir/'bridge-settings.json').read_text(encoding='utf-8'))
    base=f"http://127.0.0.1:{settings.get('port',8765)}"
    token=settings['token']
    with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token},trust_env=False,timeout=10) as probe:
        health=probe.get('/v1/health').json()
        assert health['process_id']==args.owned_pid, 'Bridge belongs to another process'
        result.update(process_id=args.owned_pid,instance_id=health['instance_id'],
                      bridge_sha256=hashlib.sha256((args.bridge_dir/'AutoCADBridge.dll').read_bytes()).hexdigest())
    config=args.output/'http-test-config.json'
    config.write_text(json.dumps(dict(cad_type='AutoCAD',prog_id='unused-http',backend='http',http=dict(base_url=base))),encoding='utf-8')
    output=args.output/'dwg';output.mkdir()
    parameters=StdioServerParameters(command=sys.executable,args=['-m','autocad_mcp.server'],cwd=str(ROOT),
        env={'PYTHONPATH':str(ROOT/'src'),'AUTOCAD_MCP_CONFIG':str(config),'AUTOCAD_BRIDGE_TOKEN':token})
    with (args.output/'mcp-stderr.log').open('w',encoding='utf-8') as stderr:
        async with stdio_client(parameters,errlog=stderr) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                names={t.name for t in (await client.list_tools()).tools};assert len(names)==44
                async def call(name,arguments,expected=None):
                    response=await client.call_tool(name,arguments)
                    text=' '.join(getattr(b,'text','') for b in response.content)
                    event=dict(tool=name,arguments=arguments,is_error=bool(response.isError),expected_error=expected)
                    if expected:
                        event['matched']=bool(response.isError and expected in text)
                    else:
                        event['matched']=not response.isError
                        if not response.isError:event['result']=response.structuredContent
                    # Public tool output only; no credentials, prompts or hidden reasoning.
                    if response.isError:event['error_text']=text
                    with (args.output/'calls.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps(event,ensure_ascii=False)+'\n')
                    result['calls']+=1
                    assert event['matched'],(name,text)
                    return response.structuredContent
                async def status():return await call('get_backend_status',{})
                s=await status();instance=s['instance_id'];legacy=s['bound_document_id']
                assert s['capabilities']['controlled_documents'] and not s['capabilities']['file_overwrite']
                assert set(s['capabilities']['batch_operations'])=={x['operation'] for x in OPERATIONS}
                assert set(s['capabilities']['file_operations'])=={'save_document','reopen_artifact'}
                assert not s['capabilities']['file_operations_atomic_with_entities']
                assert all(Path(d['name']).name.startswith('Drawing') for d in s['documents']), 'Dedicated blank process required'
                rid=uuid4().hex
                newargs=dict(instance_id=instance,request_id=rid,units='millimeters',output_directory=str(output))
                created=await call('create_working_drawing',newargs);doc=created['document_id']
                assert created['result']['managed'] and created['result']['units']['code']==4
                assert (await call('create_working_drawing',newargs))==created
                assert (await status())['bound_document_id']==legacy
                async def info(d=doc):return (await call('get_working_drawing',dict(instance_id=instance,document_id=d)))['result']
                initial=await info();assert initial['model_space_count']==0
                await call('create_working_drawing',{**newargs,'request_id':uuid4().hex,'instance_id':'wrong-instance'},'INSTANCE_MISMATCH')
                # Server-side pre-admission instance check, independently of Python pinning.
                with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token},trust_env=False,timeout=10) as probe:
                    rejected=probe.post('/v1/execute',json=dict(instance_id='wrong-instance',request_id=uuid4().hex,
                        operation='create_working_document',args=dict(units='millimeters',output_directory=str(output))))
                    assert rejected.json()['error']['code']=='INSTANCE_MISMATCH'
                result['server_instance_guard']=True
                async def batch(operations,expected=None,revision=None,request_id=None,target=doc):
                    if revision is None:revision=(await info(target))['revision']
                    return await call('execute_atomic_batch',dict(instance_id=instance,document_id=target,
                        request_id=request_id or uuid4().hex,expected_revision=revision,operations=operations),expected)
                bad=dict(id='bad',operation='draw_line',args=dict(start=[0,0,0],end=[1,1,0],layer='MissingLayer'))
                for position in [0,5,len(OPERATIONS)]:
                    operations=OPERATIONS.copy();operations.insert(position,bad)
                    await batch(operations,'rolled_back')
                    after=await info()
                    assert after['model_space_count']==0
                    assert after['layer_names']==initial['layer_names'] and after['text_style_names']==initial['text_style_names']
                result['rollback_positions']=['first','middle','last']
                before_write=(await info())['revision']
                job=await batch(OPERATIONS,revision=before_write,request_id=uuid4().hex);assert len(job['result'])==9
                replay=await batch(OPERATIONS,revision=before_write,request_id=job['request_id'])
                # Expected revision is part of the request hash; explicitly use the
                # original pre-write revision for deduplication, saved in the call log.
                # The helper above used the actual revision before submitting.
                assert replay==job
                source=[];cursor=''
                while True:
                    page=await call('query_entities_page',dict(document_id=doc,limit=3,cursor=cursor))
                    assert not page['unsupported_geometry_types'];source+=page['items']
                    if not page['has_more']:break
                    cursor=page['next_cursor']
                assert len(source)==8 and all(x['geometry_complete'] for x in source)
                bytype={x['type']:x for x in source}
                arc=bytype['AcDbArc'];assert arc['radius']==3 and abs(arc['end_angle']-90)<1e-7
                assert abs(arc['arc_length']-3*3.141592653589793/2)<1e-7 and arc['normal']==[0,0,1]
                assert bytype['AcDbText']['text_string']=='受控 MCP 文字' and abs(bytype['AcDbText']['rotation']-30)<1e-7
                assert bytype['AcDbText']['layer_properties']['color_index']==3
                assert bytype['AcDbAlignedDimension']['measurement']==10
                assert len([x for x in source if x['type']=='AcDb2dPolyline' and x['closed']])==2
                result['source_entities']=source
                current=(await info())['revision']
                await batch([OPERATIONS[1]],'REVISION_CONFLICT',revision=max(0,current-1))
                saveargs=dict(instance_id=instance,document_id=doc,expected_revision=current,request_id=uuid4().hex,file_name='fixture.dwg')
                saved=await call('save_working_drawing',saveargs);artifact=saved['result'];file=Path(artifact['file_path'])
                assert file.parent==output and hashlib.sha256(file.read_bytes()).hexdigest()==artifact['sha256']
                assert file.stat().st_size==artifact['bytes']
                assert (await call('save_working_drawing',saveargs))==saved
                await call('save_working_drawing',{**saveargs,'request_id':uuid4().hex,'expected_revision':(await info())['revision']},'FILE_EXISTS')
                await call('save_working_drawing',{**saveargs,'request_id':uuid4().hex,'file_name':'../escape.dwg'},'validation')
                reopened=await call('reopen_saved_drawing',dict(instance_id=instance,artifact_id=artifact['artifact_id'],request_id=uuid4().hex))
                reopened_doc=reopened['document_id'];assert reopened_doc!=doc
                assert not reopened['result']['managed'] and reopened['result']['read_only'] and reopened['result']['units']['code']==4
                disk=await call('query_entities_page',dict(document_id=reopened_doc,limit=1000))
                assert canonical(disk['items'])==canonical(source)
                result['reopened_entities']=disk['items'];result['artifact']=artifact
                await batch([OPERATIONS[1]],'FORBIDDEN',target=reopened_doc)
                # A later source write must not alter the independent reopened file.
                await batch([dict(id='later',operation='draw_circle',args=dict(center=[99,99,0],radius=1))])
                assert (await info())['model_space_count']==9 and (await info(reopened_doc))['model_space_count']==8
                if legacy:
                    await call('save_working_drawing',dict(instance_id=instance,document_id=legacy,expected_revision=0,
                        request_id=uuid4().hex,file_name='forbidden.dwg'),'FORBIDDEN')
                tampered=await call('save_working_drawing',dict(instance_id=instance,document_id=doc,expected_revision=(await info())['revision'],
                    request_id=uuid4().hex,file_name='tampered.dwg'))
                with Path(tampered['result']['file_path']).open('ab') as f:f.write(b'fixture-tamper')
                await call('reopen_saved_drawing',dict(instance_id=instance,artifact_id=tampered['result']['artifact_id'],
                    request_id=uuid4().hex),'ARTIFACT_CHANGED')
                await call('reopen_saved_drawing',dict(instance_id=instance,artifact_id='unknown',request_id=uuid4().hex),'ARTIFACT_NOT_FOUND')
                result.update(geometry_reopen_equal=True,no_overwrite_verified=True,read_only_reopen_verified=True,
                    original_working_document_preserved=True,artifact_tamper_rejected=True)
                result['final_status']=await status()
                result['passed']=True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-dir',type=Path,required=True)
    parser.add_argument('--owned-pid',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    result=dict(passed=False,calls=0,completed=False)
    try:
        asyncio.run(verify(args,result));result['completed']=True
    except BaseException as error:
        result['failure_type']=type(error).__name__
        raise
    finally:
        (args.output/'qualification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:result[k] for k in ['passed','completed','calls']}))

if __name__=='__main__':main()
