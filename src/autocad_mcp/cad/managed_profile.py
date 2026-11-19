"""Program-client DTO adapter over the existing HTTP backend and native journal.

No natural language, COM fallback, arbitrary file reopening or write retries.
Authoritative job identities survive Python-process restart within the native
journal's bounded lifetime; no Python cache invents operation/revision metadata.
"""
import math
import os
from pathlib import Path
import stat
from threading import RLock
from .managed_contract import VERSION, ManagedContractError, validate
from .models import WorkingDocumentJob, SavedArtifactJob

UNITS = {'unitless':('unitless',0),'mm':('millimeters',4),'cm':('centimeters',5),
         'm':('meters',6),'in':('inches',1),'ft':('feet',2)}
NAMES = {'create_working_document':'create_working_document','execute_atomic_batch':'_batch',
         'save_document_as':'save_document','reopen_document':'reopen_artifact'}
REVERSE = {native:public for public,native in NAMES.items()}
OPERATIONS = ['draw_line','draw_circle','draw_text']

def directory(value):
    if not os.path.isabs(value) or value.startswith(('\\\\','//')):
        raise ManagedContractError('OUTPUT_PATH_NOT_ALLOWED: absolute local directory required')
    path = Path(value).resolve(strict=True)
    if not path.is_dir() or os.path.normcase(str(path)) != os.path.normcase(os.path.normpath(value)):
        raise ManagedContractError('OUTPUT_PATH_NOT_ALLOWED: canonical existing directory required')
    # Same reparse boundary as native ArtifactFiles; inspect every ancestor.
    for part in [Path(os.path.abspath(value)),*Path(os.path.abspath(value)).parents]:
        attrs = part.lstat()
        if stat.S_ISLNK(attrs.st_mode) or getattr(attrs,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise ManagedContractError('OUTPUT_PATH_NOT_ALLOWED: reparse point')
    if path.name != 'artifacts' or path.parent.name != '.cader':
        raise ManagedContractError('OUTPUT_PATH_NOT_ALLOWED: this profile binds .cader/artifacts only')
    return str(path)

def alias(value):
    if type(value) is not int or value <= 0:
        raise ManagedContractError('PROTOCOL_ERROR: invalid native entity alias')
    return str(value)

def _close(value, expected):
    if isinstance(expected,list):return isinstance(value,list) and len(value)==len(expected) and all(_close(x,y) for x,y in zip(value,expected))
    return type(value) in (int,float) and math.isfinite(value) and abs(value-expected)<1e-9

def entity_dto(entity):
    """Only discard attributes after proving the profile's canonical defaults."""
    layer = entity.get('layer_properties',{})
    defaults = (entity.get('geometry_complete') is True and entity.get('visible') is True and entity.get('layer')=='0'
        and entity.get('linetype','').lower()=='bylayer' and _close(entity.get('linetype_scale'),1)
        and entity.get('lineweight')==-1 and entity.get('color_index')==256 and _close(entity.get('thickness'),0)
        and layer.get('name')=='0' and layer.get('linetype','').lower()=='continuous'
        and layer.get('color_index')==7 and layer.get('lineweight')==-3
        and all(layer.get(key) is False for key in ['is_off','is_frozen','is_locked']))
    if not defaults:return None
    kind = entity['type']
    if kind=='AcDbLine':
        if entity['start_point']==entity['end_point']:return None
        operation='draw_line'; args=dict(start=entity['start_point'],end=entity['end_point'],layer='0')
    elif kind=='AcDbCircle' and _close(entity.get('normal'),[0,0,1]):
        operation='draw_circle';args=dict(center=entity['center'],radius=entity['radius'],layer='0')
    elif kind=='AcDbText':
        font=entity.get('font',{})
        if not (_close(entity.get('normal'),[0,0,1]) and _close(entity.get('rotation'),0)
            and _close(entity.get('width_factor'),1) and _close(entity.get('oblique'),0)
            and entity.get('horizontal_mode')==0 and entity.get('vertical_mode')==0
            and entity.get('mirrored_x') is False and entity.get('mirrored_y') is False
            and entity.get('text_style')=='MCP_CJK' and font.get('typeface') in {'SimSun','宋体'}
            and font.get('bold') is False and font.get('italic') is False and font.get('big_font')==''):
            return None
        operation='draw_text';args=dict(point=entity['insertion_point'],text=entity['text_string'],height=entity['height'],layer='0')
    else:return None
    result=dict(object_id=alias(entity['object_id']),operation=operation,args=args)
    # The shared entity schema deliberately leaves args open; validate the full
    # corresponding operation as well, so unsupported values cannot pass through.
    validate('execute_atomic_batch_request',dict(instance_id='check',request_id='check',document_id='check',
        expected_revision=0,operations=[dict(id=result['object_id'],operation=operation,args=args)]))
    return result

class ManagedCAD:
    def __init__(self, backend):
        self.backend=backend
        self.lock=RLock()

    def _status(self):
        raw=self.backend.runtime_status();cap=raw['capabilities']
        required={'create_working_document','get_document_info','save_document','reopen_artifact','query_entities_page'}
        if (raw['backend']!='http' or raw.get('revision_mode')!='observed_database_events'
            or not cap.get('request_records') or cap.get('failure_revision')!='cad_thread_observed'
            or not cap.get('controlled_documents') or not cap.get('query_pagination') or not cap.get('atomic_batch')
            or not required.issubset(cap.get('operations',[])) or not set(OPERATIONS).issubset(cap.get('batch_operations',[]))
            or VERSION not in cap.get('client_profiles',[])):
            raise ManagedContractError('BRIDGE_UPGRADE_REQUIRED: revision-2 profile prerequisites are unavailable')
        return raw

    def _binding(self, raw, instance_id, verification=False):
        unit=next((name for name,(_,code) in UNITS.items() if code==raw['units']['code']),None)
        if unit is None:raise ManagedContractError('UNSUPPORTED_UNITS')
        value=dict(instance_id=instance_id,document_id=raw['document_id'],revision=raw['revision'],units=unit,
                   managed=raw['managed'],read_only=raw['read_only'])
        if verification:value['source_artifact_id']=raw['source_artifact_id']
        else:value['output_directory']=raw['output_directory']
        return validate('verification_binding' if verification else 'working_binding',value)

    def get_backend_status(self):
        with self.lock:
            raw=self._status()
            documents=[self._binding(doc,raw['instance_id']) for doc in raw['documents'] if doc.get('managed') and doc.get('output_directory')]
            return validate('status',dict(contract_version=VERSION,backend='http',instance_id=raw['instance_id'],
                revision_mode=raw['revision_mode'],documents=documents,capabilities=dict(managed_documents=True,
                atomic_operations=OPERATIONS,save_as=True,reopen=True,job_status=True,query_entities=True,
                max_batch_operations=min(100,raw['capabilities']['max_batch_operations']))))

    def _input(self, operation, arguments):
        validate(operation+'_request',arguments)
        self._status()  # Fail before POST on old DLLs or an incompatible revision mode.

    def _working(self, instance_id, document_id):
        job=self.backend.document_job('get_document_info',{},instance_id=instance_id,document_id=document_id)
        native=WorkingDocumentJob.model_validate(job)
        binding=self._binding(native.result.model_dump(),instance_id)
        directory(binding['output_directory'])
        return binding

    def _record_job(self, record):
        operation=REVERSE.get(record['operation'])
        if operation is None:raise ManagedContractError('UNSUPPORTED_JOB_OPERATION')
        job=record['job']; request_doc=record['request_document_id'];source=record['source_artifact_id']
        if (operation in {'create_working_document','reopen_document'}) != (request_doc is None):
            raise ManagedContractError('REQUEST_IDENTITY_MISMATCH')
        if (operation=='reopen_document') != (source is not None):raise ManagedContractError('ARTIFACT_IDENTITY_MISMATCH')
        success=job.status=='succeeded';pending=job.status in {'queued','running'}
        result=dict(contract_version=VERSION,instance_id=job.instance_id,request_id=job.request_id,operation=operation,
            request_document_id=request_doc,result_document_id=job.document_id if success else None,source_artifact_id=source,
            status='succeeded' if success else 'pending' if pending else 'failed',
            outcome='committed' if success else 'unknown' if pending else
                (job.error.outcome if job.error and job.error.outcome in {'rolled_back','not_executed'} else 'unknown'))
        if job.revision is not None:result['revision']=job.revision
        if success:
            if not job.document_id:raise ManagedContractError('RESULT_DOCUMENT_MISSING')
            if operation in {'execute_atomic_batch','save_document_as'} and job.document_id!=request_doc:
                raise ManagedContractError('RESULT_DOCUMENT_MISMATCH')
            if operation=='execute_atomic_batch':
                result['results']=[dict(id=step['id'],status='succeeded',object_id=alias(step['result'])) for step in job.result]
                if len({step['id'] for step in result['results']})!=len(result['results']) or len({step['object_id'] for step in result['results']})!=len(result['results']):
                    raise ManagedContractError('RESULT_ID_DUPLICATE')
        return validate('job',result)

    def _mutate(self, operation, arguments, native_args):
        native_op=NAMES[operation];request_doc=arguments.get('document_id');expected=arguments.get('expected_revision')
        job=self.backend.submit_managed(native_op,native_args,instance_id=arguments['instance_id'],
            request_id=arguments['request_id'],document_id=request_doc,expected_revision=expected)
        record=self.backend.request_record(arguments['request_id'])
        if (record['operation']!=native_op or record['request_document_id']!=request_doc
            or record['expected_revision']!=expected or record['source_artifact_id']!=arguments.get('artifact_id')
            or record['job'].model_dump()!=job.model_dump()):
            raise ManagedContractError('OUTCOME_UNKNOWN: authoritative request identity/result differs')
        return job,self._record_job(record)

    @staticmethod
    def _successful(job):
        if job.status!='succeeded':
            raise ManagedContractError(f'MANAGED_OPERATION_FAILED: request_id={job.request_id}; outcome={job.error.outcome if job.error else "unknown"}; query get_job_status')

    def create_working_document(self, **arguments):
        with self.lock:
            self._input('create_working_document',arguments)
            output=directory(arguments['output_directory'])
            job,_=self._mutate('create_working_document',arguments,dict(units=UNITS[arguments['units']][0],output_directory=output))
            self._successful(job); native=WorkingDocumentJob.model_validate(job.model_dump())
            binding=self._binding(native.result.model_dump(),job.instance_id)
            if binding['units']!=arguments['units'] or os.path.normcase(binding['output_directory'])!=os.path.normcase(output):
                raise ManagedContractError('WORKING_DOCUMENT_BINDING_MISMATCH')
            return validate('create',dict(contract_version=VERSION,request_id=job.request_id,status='succeeded',document=binding))

    def execute_atomic_batch(self, **arguments):
        with self.lock:
            self._input('execute_atomic_batch',arguments)
            operations=arguments['operations']
            if len({op['id'] for op in operations})!=len(operations):raise ManagedContractError('DUPLICATE_STEP_ID')
            normalized=[]
            for op in operations:
                args=dict(op['args'])
                if args['layer']!='0':raise ManagedContractError('UNSUPPORTED_LAYER: initial profile only supports layer 0')
                if op['operation']=='draw_line' and args['start']==args['end']:raise ManagedContractError('ZERO_LENGTH_LINE')
                if op['operation']=='draw_text':
                    if '\0' in args['text']:raise ManagedContractError('INVALID_TEXT')
                    args['position']=args.pop('point');args['rotation']=0
                normalized.append(dict(id=op['id'],operation=op['operation'],args=args))
            self._working(arguments['instance_id'],arguments['document_id'])
            _,result=self._mutate('execute_atomic_batch',arguments,dict(operations=normalized))
            if result['status']=='succeeded' and (len(result['results'])!=len(operations)
                or {r['id'] for r in result['results']}!={op['id'] for op in operations}
                or result.get('revision',-1)<=arguments['expected_revision']):raise ManagedContractError('WRITE_RESULT_MISMATCH')
            return result

    def get_job_status(self, request_id):
        with self.lock:
            validate('get_job_status_request',dict(request_id=request_id));self._status()
            return self._record_job(self.backend.request_record(request_id))

    def query_entities_page(self, **arguments):
        with self.lock:
            self._input('query_entities_page',arguments)
            page=self.backend.query_page_guarded(arguments['instance_id'],arguments['document_id'],arguments['expected_revision'],
                limit=arguments['limit'],cursor=arguments['cursor'] or '')
            items=[];unsupported=set(page['unsupported_geometry_types'])
            for raw in page['items']:
                entity=entity_dto(raw)
                if entity is None:unsupported.add(raw['type'])
                else:items.append(entity)
            if page['has_more']!=bool(page['next_cursor']):raise ManagedContractError('CURSOR_ENVELOPE_INVALID')
            return validate('query',dict(contract_version=VERSION,instance_id=arguments['instance_id'],document_id=page['document_id'],
                revision=page['revision'],items=items,next_cursor=page['next_cursor'],unsupported_geometry_types=sorted(unsupported)))

    def save_document_as(self, **arguments):
        with self.lock:
            self._input('save_document_as',arguments)
            binding=self._working(arguments['instance_id'],arguments['document_id'])
            output=Path(arguments['output_path'])
            if (not output.is_absolute() or os.path.normpath(str(output))!=str(output)
                or output.suffix.lower()!='.dwg' or directory(str(output.parent))!=directory(binding['output_directory'])):
                raise ManagedContractError('OUTPUT_PATH_NOT_ALLOWED')
            job,_=self._mutate('save_document_as',arguments,dict(file_name=output.name))
            self._successful(job);artifact=SavedArtifactJob.model_validate(job.model_dump()).result
            if os.path.normcase(artifact.file_path)!=os.path.normcase(str(output)) or artifact.saved_revision!=arguments['expected_revision']:
                raise ManagedContractError('ARTIFACT_BINDING_MISMATCH')
            return validate('save',dict(contract_version=VERSION,request_id=job.request_id,status='succeeded',artifact=dict(
                artifact_id=artifact.artifact_id,instance_id=job.instance_id,document_id=artifact.source_document_id,
                revision=artifact.saved_revision,path=artifact.file_path,sha256=artifact.sha256,byte_size=artifact.bytes)))

    def reopen_document(self, **arguments):
        with self.lock:
            self._input('reopen_document',arguments)
            job,_=self._mutate('reopen_document',arguments,dict(artifact_id=arguments['artifact_id']))
            self._successful(job);native=WorkingDocumentJob.model_validate(job.model_dump())
            binding=self._binding(native.result.model_dump(),job.instance_id,verification=True)
            if binding['source_artifact_id']!=arguments['artifact_id'] or native.result.artifact is None or native.result.artifact.artifact_id!=arguments['artifact_id'] or binding['document_id']==native.result.artifact.source_document_id:
                raise ManagedContractError('REOPEN_ARTIFACT_MISMATCH')
            return validate('reopen',dict(contract_version=VERSION,request_id=job.request_id,status='succeeded',
                source_artifact_id=arguments['artifact_id'],document=binding))
