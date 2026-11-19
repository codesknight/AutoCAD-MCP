"""Offline verification of the shared, byte-pinned Cader revision-2 bundle.

This checks data shapes, operation-specific job identities and exact audit bytes.
It does not provide the managed MCP profile, connect to CAD, or verify a DWG.
"""
import argparse
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT/'schemas/cader-cad-v1'

def load_bundle(bundle):
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle/'configs/contracts/cader-v1.manifest.json').read_text(encoding='utf-8'))
    if manifest['contract_version'] != 'cader-cad/1' or manifest['draft_revision'] != 2:
        raise ValueError('Unsupported shared contract revision')
    values = {}
    for kind in ['schema','examples']:
        path = (bundle/manifest[kind]['path']).resolve()
        if not path.is_relative_to(bundle):raise ValueError('Bundle path escapes its root')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest[kind]['sha256']:
            raise ValueError(f'{kind} exact-byte hash mismatch')
        if not raw.endswith(b'\n') or b'\r\n' in raw:raise ValueError('Bundle must preserve UTF-8/LF export bytes')
        values[kind] = json.loads(raw)
    return manifest, values['schema']['schemas'], values['examples']

def job_matches_intent(job, intent, schema):
    if not Draft202012Validator(schema).is_valid(job):return False
    same = all(job[key] == intent[key] for key in [
        'instance_id','request_id','operation','request_document_id','source_artifact_id'])
    result = job['result_document_id']
    if intent['operation'] in {'execute_atomic_batch','save_document_as'}:
        output_valid = result == intent['request_document_id'] or (job['status'] != 'succeeded' and result is None)
    else:
        output_valid = job['status'] != 'succeeded' if result is None else (
            result != intent['prior_working_document_id'] and result not in intent['existing_document_ids'])
    return same and output_valid

def check_audit(vector):
    raw = vector['request_json'].encode('utf-8')
    if hashlib.sha256(raw).hexdigest() != vector['request_sha256']:return False
    envelope = json.loads(raw)
    return envelope == {'operation':vector['operation'],'arguments':vector['args']}

def verify(bundle=DEFAULT_BUNDLE):
    manifest, schemas, examples = load_bundle(bundle)
    checks = []
    for case in examples['schema_cases']:
        valid = Draft202012Validator(schemas[case['schema']]).is_valid(case['value'])
        checks.append(dict(kind='schema',name=case['name'],passed=valid == case['valid']))
    for case in examples['reconciliation_cases']:
        valid = job_matches_intent(case['job'],case['intent'],schemas['job'])
        checks.append(dict(kind='job_identity',name=case['name'],passed=valid == case['valid']))
    for index, vector in enumerate(examples['audit_vectors']):
        checks.append(dict(kind='request_audit',name=f'vector-{index+1}',passed=check_audit(vector)))
    return dict(contract_version='cader-cad/1',draft_revision=2,
        schema_sha256=manifest['schema']['sha256'],examples_sha256=manifest['examples']['sha256'],
        passed=all(row['passed'] for row in checks),checks=checks,
        managed_profile_implemented=False,cad_connected=False,dwg_acceptance='not_run')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=DEFAULT_BUNDLE)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args(); result = verify(args.bundle)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],checks=len(result['checks']),dwg_acceptance='not_run')))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
