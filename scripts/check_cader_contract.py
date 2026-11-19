"""Read-only structural comparison against a supplied Cader contract snapshot.

Only tools/list and get_backend_status are called on the repository-default MCP.
HTTP response comparisons use explicitly identified historical synthetic fixtures;
they do not connect to CAD or establish a joint DWG acceptance result.
Exit 2 means the compared contracts are incompatible, not a failed drawing run.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

def errors(schema, value):
    return [dict(path='/'.join(str(v) for v in e.absolute_path),rule=e.validator,message=e.message)
            for e in Draft202012Validator(schema).iter_errors(value)]

async def discover():
    parameters=StdioServerParameters(command=sys.executable,args=['-m','autocad_mcp.server'],cwd=str(ROOT),
        env={'PYTHONPATH':str(ROOT/'src'),'AUTOCAD_MCP_CONFIG':str(ROOT/'src/autocad_mcp/config.json')})
    async with stdio_client(parameters) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            tools=await client.list_tools()
            status=await client.call_tool('get_backend_status',{})
            if status.isError:raise RuntimeError('Read-only default backend status failed')
            return {tool.name:tool.model_dump(mode='json',exclude_none=True) for tool in tools.tools},status.structuredContent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--recorded-calls',type=Path,default=ROOT/'docs/validation/controlled-documents-2026-11-19-01/calls.jsonl')
    args=parser.parse_args()
    raw=args.schema.read_bytes();contract=json.loads(raw);schemas=contract['schemas']
    common=dict(instance_id='fixture-instance',request_id='fixture-request')
    target=dict(document_id='fixture-document',expected_revision=0)
    requests={
        'get_backend_status':{},
        'create_working_document':{**common,'units':'unitless','managed':True},
        'execute_atomic_batch':{**common,**target,'operations':[
            dict(id='line',operation='draw_line',args=dict(start=[0,0,0],end=[20,0,0],layer='0')),
            dict(id='circle',operation='draw_circle',args=dict(center=[10,10,0],radius=3,layer='0')),
            dict(id='label',operation='draw_text',args=dict(point=[0,15,0],text='CADER FIXTURE',height=2,layer='0'))]},
        'get_job_status':dict(request_id='fixture-request'),
        'query_entities_page':dict(instance_id='fixture-instance',**target,cursor=None,limit=1000),
        'save_document_as':{**common,**target,'output_path':'D:/cader-artifacts/fixture.dwg','overwrite':False},
        'reopen_document':{**common,'artifact_id':'fixture-artifact'},
    }
    tools,status=asyncio.run(discover())
    request_checks=[]
    for name,value in requests.items():
        # Invalid fixture data must not be mislabeled as a provider mismatch.
        fixture_errors=errors(schemas[name+'_request'],value)
        if fixture_errors:raise ValueError((name,fixture_errors))
        if name not in tools:
            request_checks.append(dict(tool=name,available=False,compatible=False));continue
        tool_schema=tools[name]['inputSchema'];mismatches=errors(tool_schema,value)
        missing_guards=[key for key in value if key not in tool_schema.get('properties',{})]
        request_checks.append(dict(tool=name,available=True,compatible=not mismatches and not missing_guards,
            schema_errors=mismatches,fields_not_declared=missing_guards))
    calls=[json.loads(line) for line in args.recorded_calls.read_text(encoding='utf-8').splitlines()]
    mapping={'get_backend_status':'status','create_working_drawing':'create','execute_atomic_batch':'job',
             'save_working_drawing':'save','reopen_saved_drawing':'reopen','query_entities_page':'query'}
    response_checks=[]
    for name,kind in mapping.items():
        value=next(row['result'] for row in calls if row['tool']==name and not row['is_error'])
        mismatches=errors(schemas[kind],value)
        response_checks.append(dict(mcp_tool=name,cader_schema=kind,compatible=not mismatches,schema_errors=mismatches))
    cader_root=args.schema.resolve().parents[2]
    report=dict(contract_version=contract['contract_version'],schema_sha256=hashlib.sha256(raw).hexdigest(),
        mcp_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        cader_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=cader_root,text=True).strip(),
        actual_stdio=dict(config='repository_default',tool_count=len(tools),backend_status=status,
                          cader_status_schema_errors=errors(schemas['status'],status)),
        requests=request_checks,historical_http_responses=response_checks,
        historical_source=args.recorded_calls.name,historical_source_sha256=hashlib.sha256(args.recorded_calls.read_bytes()).hexdigest(),
        compatible=False,cad_calls_performed=status['backend']=='http',cad_writes_performed=False,dwg_acceptance='not_run')
    report['compatible']=all(row['compatible'] for row in request_checks+response_checks) and not report['actual_stdio']['cader_status_schema_errors']
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(compatible=report['compatible'],default_backend=status['backend'],tools=len(tools),
        missing_tools=[r['tool'] for r in request_checks if not r['available']],
        incompatible_recorded_response_shapes=sum(not r['compatible'] for r in response_checks),dwg_acceptance='not_run')))
    return 0 if report['compatible'] else 2

if __name__=='__main__':raise SystemExit(main())
