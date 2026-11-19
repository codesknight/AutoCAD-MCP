"""Opt-in real managed-profile qualification followed by the unmodified Cader CLI.

Requires an already started dedicated AutoCAD Bridge. Writes only new work
drawings and new .cader/artifacts files. Never starts CAD, edits Cader code/configs,
changes default backend, retries unknown writes, or cleans up a CAD process.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import httpx
from autocad_mcp.config import Config
from autocad_mcp.cad.backends.http_backend import HTTPBackend
from autocad_mcp.cad.managed_profile import ManagedCAD
from autocad_mcp.cad.managed_contract import SCHEMAS, SCHEMA_SHA256

ROOT=Path(__file__).resolve().parents[1]

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def tracked(root):
    names=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode('utf-8').split('\0')
    return {name:digest(root/name) for name in names if name and (root/name).is_file()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cader-root',type=Path,required=True)
    parser.add_argument('--bridge-dir',type=Path,required=True)
    parser.add_argument('--owned-pid',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cader=args.cader_root.resolve();before=tracked(cader)
    result=dict(passed=False,completed=False,cader_code_unchanged=False,owned_pid=args.owned_pid,
        cader_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=cader,text=True).strip(),
        mcp_base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),schema_sha256=SCHEMA_SHA256)
    (out/'cader-tracked-before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    node=cader/'.cader/tools/node-v24.9.0-win-x64/node.exe'
    try:
        exported=subprocess.run([str(node),'apps/cli/dist/index.js','cad-contract'],cwd=cader,capture_output=True,timeout=30,check=True)
        (out/'cader-contract.json').write_bytes(exported.stdout)
        compiled=json.loads(exported.stdout)
        assert compiled['draft_revision']==2 and compiled['schemas']==SCHEMAS,'Cader built CLI schema differs from approved revision'
        settings=json.loads((args.bridge_dir/'bridge-settings.json').read_text(encoding='utf-8'))
        token=settings['token'];base=f"http://127.0.0.1:{settings.get('port',8765)}"
        result['bridge_sha256']=digest(args.bridge_dir/'AutoCADBridge.dll')
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token},trust_env=False,timeout=10) as client:
            health=client.get('/v1/health').json();assert health['process_id']==args.owned_pid,'Bridge PID is not the dedicated owned process'
        os.environ['AUTOCAD_BRIDGE_TOKEN']=token
        config=Config(cad_type='AutoCAD',prog_id='unused-http',backend='http',http=dict(base_url=base))
        cfg=out/'http-config.json';cfg.write_text(config.model_dump_json(indent=2),encoding='utf-8')
        backend=HTTPBackend(config);profile=ManagedCAD(backend)
        native_calls=[]
        def call(name,**values):
            answer=getattr(profile,name)(**values)
            native_calls.append(dict(tool=name,arguments=values,result=answer))
            (out/'native-calls.json').write_text(json.dumps(native_calls,ensure_ascii=False,indent=2),encoding='utf-8')
            return answer
        def create(label):
            directory=out/label/'.cader/artifacts';directory.mkdir(parents=True)
            binding=call('create_working_document',instance_id=health['instance_id'],request_id=uuid4().hex,
                units='unitless',managed=True,output_directory=str(directory))['document']
            return binding,directory
        try:
            status=call('get_backend_status');instance=status['instance_id'];assert instance==health['instance_id']
            assert all(Path(d['output_directory']).name=='artifacts' for d in status['documents'])
            plan=json.loads((cader/'benchmark/fixtures/managed-geometry.plan.json').read_text(encoding='utf-8'))
            operations=plan['operations'];assert len(operations)==3 and all(op['args']['layer']=='0' for op in operations)
            binding,directory=create('native-success')
            target=dict(instance_id=instance,document_id=binding['document_id'])
            assert call('query_entities_page',**target,expected_revision=binding['revision'],cursor=None,limit=1000)['items']==[]
            job=call('execute_atomic_batch',**target,request_id=uuid4().hex,expected_revision=binding['revision'],operations=operations)
            assert job['status']=='succeeded' and job['revision']>binding['revision']
            source=call('query_entities_page',**target,expected_revision=job['revision'],cursor=None,limit=1000)
            (out/'raw-native-entities.json').write_text(json.dumps(backend.query_page_guarded(instance,binding['document_id'],job['revision']),ensure_ascii=False,indent=2),encoding='utf-8')
            assert len(source['items'])==3 and not source['unsupported_geometry_types'],source
            saved=call('save_document_as',**target,request_id=uuid4().hex,expected_revision=job['revision'],
                output_path=str(directory/'fixture.dwg'),overwrite=False)['artifact']
            assert digest(saved['path'])==saved['sha256'] and Path(saved['path']).stat().st_size==saved['byte_size']
            reopened=call('reopen_document',instance_id=instance,request_id=uuid4().hex,artifact_id=saved['artifact_id'])['document']
            assert reopened['read_only'] and not reopened['managed'] and reopened['document_id']!=binding['document_id']
            disk=call('query_entities_page',instance_id=instance,document_id=reopened['document_id'],expected_revision=reopened['revision'],cursor=None,limit=1000)
            normalize=lambda items:sorted(json.dumps({k:v for k,v in row.items() if k!='object_id'},sort_keys=True) for row in items)
            assert normalize(source['items'])==normalize(disk['items']) and not disk['unsupported_geometry_types']
            failure,_=create('native-rollback');failed_target=dict(instance_id=instance,document_id=failure['document_id'])
            before_info=backend.document_job('get_document_info',{},instance_id=instance,document_id=failure['document_id'])['result']
            # Distinct JSON endpoints satisfy shared shape rules but fall within
            # AutoCAD's geometric zero-length tolerance: force a real abort after text/style creation.
            bad=[deepcopy(operations[2]),dict(id='native-invalid',operation='draw_line',args=dict(start=[0,0,0],end=[1e-12,0,0],layer='0'))]
            failed=call('execute_atomic_batch',**failed_target,request_id=uuid4().hex,expected_revision=failure['revision'],operations=bad)
            assert failed['status']=='failed' and failed['outcome']=='rolled_back' and failed['revision']>=failure['revision']
            after_info=backend.document_job('get_document_info',{},instance_id=instance,document_id=failure['document_id'])['result']
            assert after_info['model_space_count']==0 and after_info['layer_names']==before_info['layer_names'] and after_info['text_style_names']==before_info['text_style_names']
            assert call('query_entities_page',**failed_target,expected_revision=failed['revision'],cursor=None,limit=1000)['items']==[]
            result['rollback_observation']=dict(before=failure['revision'],after=failed['revision'],no_entity_layer_style_residue=True)
            fresh_backend=HTTPBackend(config)
            try:
                recovered=ManagedCAD(fresh_backend).get_job_status(failed['request_id'])
                assert recovered==failed
                result['fresh_python_reconciliation']=recovered
            finally:fresh_backend.close()
            stale=call('execute_atomic_batch',**failed_target,request_id=uuid4().hex,expected_revision=max(0,failed['revision']-1),operations=operations)
            assert stale['status']=='failed' and stale['outcome']=='not_executed' and stale['revision']==failed['revision']
            result['native_profile_passed']=True
        finally:backend.close()
        # Runtime-only input; no Cader source, static config, reviewed policy or .env changes.
        mcp_path=cader/'.cader'/('joint-mcp-profile-'+uuid4().hex+'.json')
        mcp_path.parent.mkdir(exist_ok=True)
        mcp_path.write_text(json.dumps(dict(version=1,server_name='autocad',transport='stdio',command=sys.executable,
            args=['-m','autocad_mcp.managed_server'],cwd=str(ROOT),startup_timeout_ms=30000,tool_timeout_ms=90000,
            env_refs={'AUTOCAD_MCP_CONFIG':'CADER_TEST_MCP_HTTP_CONFIG','AUTOCAD_BRIDGE_TOKEN':'CADER_TEST_MCP_TOKEN',
                      'PYTHONPATH':'CADER_TEST_MCP_PYTHONPATH'}),indent=2),encoding='utf-8')
        env=os.environ.copy();env.update(CADER_TEST_MCP_HTTP_CONFIG=str(cfg),CADER_TEST_MCP_TOKEN=token,CADER_TEST_MCP_PYTHONPATH=str(ROOT/'src'))
        output_name='joint-mcp-'+uuid4().hex+'.dwg'
        command=[str(node),'apps/cli/dist/index.js','cad-test','--backend','http','--mcp',str(mcp_path.relative_to(cader)),
            '--plan','benchmark/fixtures/managed-geometry.plan.json','--output','.cader/artifacts/'+output_name,'--authorize-write']
        result['cli_arguments']=command[1:]
        run=subprocess.run(command,cwd=cader,env=env,capture_output=True,timeout=180)
        (out/'cader-stdout.json').write_bytes(run.stdout);(out/'cader-stderr.log').write_bytes(run.stderr)
        result['cader_exit_code']=run.returncode
        answer=json.loads(run.stdout);result['cader_report']=answer
        if run.returncode!=0 or answer['task_status']!='succeeded' or answer['verification']!='passed':
            raise AssertionError('Cader business acceptance did not pass; preserve the run and never replay automatically')
        artifact=answer['artifact'];assert digest(artifact['path'])==artifact['sha256'] and Path(artifact['path']).stat().st_size==artifact['byte_size']
        assert all(answer['stages'][key]=='succeeded' for key in ['execution','saving','reopening'])
        result['passed']=True;result['completed']=True
    finally:
        result['cader_code_unchanged']=before==tracked(cader)
        if not result['cader_code_unchanged']:result['passed']=False
        (out/'qualification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:result[key] for key in ['passed','completed','cader_code_unchanged']}))

if __name__=='__main__':main()
