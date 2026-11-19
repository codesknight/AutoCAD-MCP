"""Pinned cader-cad/1 revision-2 data contract; independent of MCP transport."""
import hashlib
import json
import math
from pathlib import Path
from jsonschema import Draft202012Validator

VERSION = 'cader-cad/1'
SCHEMA_SHA256 = 'e239266ee97ccd64284f6a6b5896eb57532b0f18eb5769dad3899e614191dd28'
_raw = (Path(__file__).resolve().parents[1]/'contracts/cader-v1.schemas.json').read_bytes()
if hashlib.sha256(_raw).hexdigest() != SCHEMA_SHA256:
    raise RuntimeError('Managed contract schema bytes differ from the accepted revision')
SCHEMAS = json.loads(_raw)['schemas']
VALIDATORS = {name:Draft202012Validator(value) for name,value in SCHEMAS.items()}

class ManagedContractError(ValueError):
    pass

def validate(name, value):
    def finite(item):
        if isinstance(item,float) and not math.isfinite(item):raise ManagedContractError('INVALID_ARGUMENT: nonfinite number')
        if isinstance(item,dict):
            for child in item.values():finite(child)
        if isinstance(item,(list,tuple)):
            for child in item:finite(child)
    finite(value)
    error = next(VALIDATORS[name].iter_errors(value),None)
    if error is not None:
        location = '/'.join(map(str,error.absolute_path))
        raise ManagedContractError(f'MANAGED_DTO_INVALID: {name}/{location}')
    return value
