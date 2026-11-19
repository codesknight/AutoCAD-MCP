"""Shared synthetic contract vectors, independent of Cader runtime and CAD."""
import hashlib
import shutil
import pytest
from jsonschema import Draft202012Validator
from scripts.verify_cader_vectors import DEFAULT_BUNDLE, load_bundle, job_matches_intent, check_audit

MANIFEST, SCHEMAS, EXAMPLES = load_bundle(DEFAULT_BUNDLE)

def test_shared_manifest_is_the_accepted_exact_byte_pair():
    assert MANIFEST['schema']['sha256']=='e239266ee97ccd64284f6a6b5896eb57532b0f18eb5769dad3899e614191dd28'
    assert MANIFEST['examples']['sha256']=='9e33ab75c054e0b49d60c0616914f497d584aa284e7ff3898a643fa50caa0e41'

@pytest.mark.parametrize('case',EXAMPLES['schema_cases'],ids=lambda c:c['name'])
def test_shared_schema_cases(case):
    assert Draft202012Validator(SCHEMAS[case['schema']]).is_valid(case['value']) == case['valid']

@pytest.mark.parametrize('case',EXAMPLES['reconciliation_cases'],ids=lambda c:c['name'])
def test_shared_job_identity_cases(case):
    assert job_matches_intent(case['job'],case['intent'],SCHEMAS['job']) == case['valid']

@pytest.mark.parametrize('vector',EXAMPLES['audit_vectors'])
def test_shared_exact_request_audit_bytes(vector):
    assert check_audit(vector)
    assert hashlib.sha256((vector['request_json']+'\n').encode()).hexdigest()!=vector['request_sha256']

def test_changed_bundle_is_rejected_before_vectors_are_trusted(tmp_path):
    for entry in [MANIFEST['schema']['path'],MANIFEST['examples']['path'],'configs/contracts/cader-v1.manifest.json']:
        target=tmp_path/entry;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(DEFAULT_BUNDLE/entry,target)
    with (tmp_path/MANIFEST['examples']['path']).open('ab') as output:output.write(b'\n')
    with pytest.raises(ValueError,match='exact-byte hash mismatch'):load_bundle(tmp_path)
