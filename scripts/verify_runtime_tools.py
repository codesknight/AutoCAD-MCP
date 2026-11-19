"""Opt-in real stdio MCP checks against a dedicated, already-started CAD Bridge.

Never launches CAD, retries writes, saves files or closes an existing drawing.
An operator closes only the explicitly owned test process at the final checkpoint.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from uuid import uuid4
import httpx
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from autocad_mcp.config import load_config,HTTPConfig
from benchmarks.common import Records
from benchmarks.native import wait_for
from scripts.verify_http_bridge import cad_processes

ROOT=Path(__file__).resolve().parents[1]

def wait_for_owned_exit(owned_pid,originals,processes=cad_processes):
    # Process termination can return before tasklist stops reporting the PID.
    wait_for(lambda:owned_pid not in processes(),timeout=20)
    if not originals<=processes():
        raise AssertionError('An original CAD process disappeared')

async def verify(config_path,token,records,result,child_log):
    env={'PYTHONPATH':str(ROOT/'src'),'AUTOCAD_MCP_CONFIG':str(config_path),'AUTOCAD_BRIDGE_TOKEN':token}
    parameters=StdioServerParameters(command=sys.executable,args=['-m','autocad_mcp.server'],cwd=str(ROOT),env=env)
    async with stdio_client(parameters,errlog=child_log) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            assert len((await client.list_tools()).tools)==40
            async def call(name,args,expected_error=None):
                response=await client.call_tool(name,args)
                text=' '.join(getattr(c,'text','') for c in response.content)
                records.add('mcp_call',tool=name,ok=not response.isError,expected_error=expected_error)
                if expected_error:
                    assert response.isError and expected_error in text,(name,text)
                    return
                if response.isError:
                    records.add('unexpected_tool_error',tool=name,
                        code=next((c for c in ('OUTCOME_UNKNOWN','TRANSACTION_FAILED','INVALID_ARGUMENT') if c in text),'UNKNOWN'),
                        request_id=(re.search(r'request_id=([A-Za-z0-9._-]+)',text)[1] if re.search(r'request_id=([A-Za-z0-9._-]+)',text) else None))
                assert not response.isError,(name,text)
                return response.structuredContent
            await call('new_drawing',{})
            status=await call('get_backend_status',{})
            doc=status['bound_document_id']
            assert status['backend']=='http' and status['capabilities']['query_pagination']
            assert next(d for d in status['documents'] if d['document_id']==doc)['managed']
            assert all(re.fullmatch(r'Drawing\d+\.dwg',Path(d['name']).name) for d in status['documents'])
            await call('execute_atomic_batch',dict(document_id=doc,operations=[
                dict(id='layer-a',operation='create_layer',args=dict(name='RuntimeA',color=3)),
                dict(id='layer-b',operation='create_layer',args=dict(name='RuntimeB',color=4))]))
            first=None
            for offset in range(0,1205,200):
                ops=[dict(id=f'line-{i}',operation='draw_line',args=dict(start=[i,0,0],end=[i,2,0],layer='RuntimeA' if i%2==0 else 'RuntimeB')) for i in range(offset,min(offset+200,1205))]
                rid=uuid4().hex
                job=await call('execute_atomic_batch',dict(document_id=doc,operations=ops,request_id=rid))
                assert job['request_id']==rid and job['document_id']==doc and len(job['result'])==len(ops)
                if first is None:
                    first=(ops,rid,job)
            replay=await call('execute_atomic_batch',dict(document_id=doc,operations=first[0],request_id=first[1]))
            assert replay==first[2]
            journal=await call('get_job_status',dict(request_id=first[1]))
            assert journal==first[2]
            changed=json.loads(json.dumps(first[0]));changed[0]['args']['end']=[9999,2,0]
            await call('execute_atomic_batch',dict(document_id=doc,operations=changed,request_id=first[1]),'REQUEST_ID_CONFLICT')
            await call('query_entities',{},'RESULT_TOO_LARGE')
            query=dict(document_id=doc,entity_type='AcDbLine',fields=['start_point','end_point'],limit=400)
            items=[];cursor='';counts=[];first_cursor=None
            while True:
                page=await call('query_entities_page',dict(query,cursor=cursor))
                assert page['document_id']==doc and page['count']==len(page['items'])
                counts.append(page['count']);items.extend(page['items'])
                if first_cursor is None:first_cursor=page['next_cursor']
                if not page['has_more']:break
                cursor=page['next_cursor']
            assert counts==[400,400,400,5] and len({i['object_id'] for i in items})==1205
            assert {tuple(i['start_point']) for i in items}=={(i,0,0) for i in range(1205)}
            assert all(i['end_point']==[i['start_point'][0],2,0] and 'bounding_box' not in i and 'handle' not in i for i in items)
            result.update(pagination_items=1205,page_counts=counts,no_duplicate_ids=True,
                          geometry_sha256=hashlib.sha256(json.dumps(sorted((i['start_point'],i['end_point'],i['layer']) for i in items)).encode()).hexdigest(),
                          duplicate_batch_deduplicated=True,journal_identity_verified=True)
            filtered=await call('query_entities_page',dict(document_id=doc,entity_type='AcDbLine',layer='RuntimeA',fields=['handle'],limit=1000))
            assert filtered['count']==603 and not filtered['has_more']
            assert all(set(i)=={'object_id','type','layer','handle'} for i in filtered['items'])
            await call('query_entities_page',dict(query,cursor=first_cursor+'x'),'CURSOR_INVALID')
            await call('query_entities_page',dict(query,layer='RuntimeB',cursor=first_cursor),'CURSOR_INVALID')
            before=(await call('query_entities_page',dict(document_id=doc,limit=1000)))['revision']
            await call('execute_atomic_batch',dict(document_id=doc,expected_revision=before-1,operations=[dict(id='circle',operation='draw_circle',args=dict(center=[0,0,0],radius=1))]),'REVISION_CONFLICT')
            await call('execute_atomic_batch',dict(document_id=doc,operations=[
                dict(id='rollback-layer',operation='create_layer',args=dict(name='MustRollback')),
                dict(id='rollback-line',operation='draw_line',args=dict(start=[2000,0,0],end=[2000,2,0],layer='MustRollback')),
                dict(id='invalid-line',operation='draw_line',args=dict(start=[0,0,0],end=[1,1,0],layer='MissingLayer'))]),'rolled_back')
            assert 'MustRollback' not in json.loads((await call('list_layers',{}))['result'])
            assert (await call('query_entities_page',dict(document_id=doc,layer='MustRollback',limit=1000)))['count']==0
            await call('execute_atomic_batch',dict(document_id=doc,operations=[dict(id='circle',operation='draw_circle',args=dict(center=[-99,0,0],radius=1))]))
            await call('query_entities_page',dict(query,cursor=first_cursor),'CURSOR_STALE')
            await call('new_drawing',{})
            second=(await call('get_backend_status',{}))['bound_document_id']
            assert second!=doc
            await call('query_entities_page',dict(query,document_id=second,cursor=first_cursor),'CURSOR_INVALID')
            # The explicit target still addresses the first document after legacy rebind.
            assert (await call('query_entities_page',dict(query,limit=1000)))['count']==1000
            result.update(filter_projection_verified=True,cursor_errors_verified=True,rollback_reported=True)
            records.json('runtime-checkpoint.json',result)
            geometries=[
                ('draw_rectangle',dict(corner1_x=2,corner1_y=3,corner1_z=9,corner2_x=12,corner2_y=8,corner2_z=20)),
                ('draw_polyline',dict(points=[[0,0,7],[5,0,9],[5,4,2]],closed=True)),
                ('draw_text',dict(position_x=10,position_y=20,position_z=0,text='中文 MCP 文字',height=2.5,rotation=30)),
                ('draw_mtext',dict(position_x=20,position_y=30,position_z=0,text='第一行\\P第二行',width=40,height=3)),
                ('add_dimension',dict(start_x=0,start_y=0,start_z=0,end_x=10,end_y=0,end_z=0,text_x=5,text_y=5,text_z=0)),
            ]
            summaries=[]
            for name,args in geometries:
                response=await call(name,args)
                alias=int(re.search(r'object_id=(\d+)',response['result'])[1])
                summary=json.loads((await call('get_entity',dict(object_id=alias)))['result'])
                summaries.append(summary)
                records.json('geometry-checkpoint.json',summaries)
            rect,poly,text,mtext,dim=summaries
            assert rect['type']=='AcDb2dPolyline' and rect['closed'] and rect['points']==[[2,3,0],[12,3,0],[12,8,0],[2,8,0]]
            assert poly['type']=='AcDb2dPolyline' and poly['closed'] and poly['points']==[[0,0,0],[5,0,0],[5,4,0]]
            assert text['text_string']=='中文 MCP 文字' and text['text_style']=='MCP_CJK' and abs(text['rotation']-30)<1e-8 and text['height']==2.5
            assert text['insertion_point']==[10,20,0]
            assert mtext['text_style']=='MCP_CJK' and mtext['width']==40 and mtext['height']==3 and '第一行' in mtext['text_string'] and '第二行' in mtext['text_string']
            assert mtext['insertion_point']==[20,30,0]
            assert dim['type']=='AcDbAlignedDimension' and abs(dim['measurement']-10)<1e-8
            assert dim['start_point']==[0,0,0] and dim['end_point']==[10,0,0]
            # AutoCAD canonicalizes this point onto extension line 2. Its X
            # need not equal the input point; the horizontal dimension line
            # must pass through y=5 in the same plane.
            assert abs(dim['dimension_line_point'][1]-5)<1e-8 and abs(dim['dimension_line_point'][2])<1e-8
            result.update(geometry_tools=summaries,filter_projection_verified=True,cursor_errors_verified=True,rollback_reported=True)
            status=await call('get_backend_status',{})
            result['scratch_documents']=[Path(d['name']).name for d in status['documents']]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-dir',type=Path,required=True)
    parser.add_argument('--owned-pid',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--control-dir',type=Path,required=True)
    args=parser.parse_args()
    records=Records(args.output);args.control_dir.mkdir(parents=True,exist_ok=False)
    baseline=cad_processes();assert args.owned_pid in baseline
    originals=baseline-{args.owned_pid}
    settings=json.loads((args.bridge_dir/'bridge-settings.json').read_text(encoding='utf-8'))
    config=load_config().model_copy(update={'backend':'http','http':HTTPConfig(base_url=f"http://127.0.0.1:{settings['port']}")})
    result=dict(completed=False,passed=False,bridge_sha256=hashlib.sha256((args.bridge_dir/'AutoCADBridge.dll').read_bytes()).hexdigest())
    result['source_sha256']={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [*sorted((ROOT/'plugin/AutoCADBridge').glob('*.cs')),Path(__file__).resolve()]}
    records.json('plan.json',dict(mode='runtime_tools',transport='real stdio MCP',line_count=1205,owned_pid=args.owned_pid))
    try:
        with httpx.Client(base_url=config.http.base_url,headers={'Authorization':'Bearer '+settings['token']},trust_env=False,timeout=5) as client:
            health=client.get('/v1/health').json()
            assert health['process_id']==args.owned_pid and health['status']=='ready'
            result['instance_id']=health['instance_id']
        with tempfile.TemporaryDirectory(prefix='autocad-runtime-config-') as directory, (args.control_dir/'mcp-stderr.log').open('w',encoding='utf-8') as child_log:
            path=Path(directory)/'config.json';path.write_text(config.model_dump_json(),encoding='utf-8')
            asyncio.run(verify(path,settings['token'],records,result,child_log))
        result['tests_passed']=True
        records.json('verification.json',result)
        print('Native runtime checks passed. Close only owned CAD PID '+str(args.owned_pid)+'; write cleanup.json in the control directory.',flush=True)
        wait_for(lambda:(args.control_dir/'cleanup.json').exists(),timeout=900)
        wait_for_owned_exit(args.owned_pid,originals)
        result.update(completed=True,passed=True,owned_process_closed=True,original_processes_preserved=True)
    except BaseException as exc:
        result['error_type']=type(exc).__name__
        raise
    finally:
        records.json('qualification.json',result)

if __name__=='__main__':main()
