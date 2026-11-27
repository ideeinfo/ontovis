"""Device-model reads follow their registered identity and verified installation."""
import copy
import unittest
from uuid import uuid4
from types import SimpleNamespace

from apps.api.authority import PreviewError
from apps.api.equipment_reader import EquipmentReader
from tests.test_equipment_materials import MODEL, specification_revision

FIELD={'propertyKey':'voltage','propertyRevisionId':'voltage:r1','definition':{'nameZh':'额定电压','nameEn':'Rated voltage','unit':'V'},'inherited':True}
SERIAL={**FIELD,'propertyKey':'serial','propertyRevisionId':'serial:r1'}
VALUE={'propertyKey':'voltage','propertyRevisionId':'voltage:r1','status':'known','value':690,'unit':'V'}

class Parameters(EquipmentReader):
    def __init__(self):
        self.calls=[];self.resolutions=[];self.after=None;self.failure=None
        self.current=copy.deepcopy(MODEL);self.values=[VALUE]
        adoption={key:str(uuid4()) for key in ('applicationId','applicationRevisionId','specificationRevisionId')}
        adoption['specificationRevisionId']=MODEL['revisionId']
        self.records={uid:{'item':{'entityUid':uid,'entityRevision':'fixed:1','displayName':uid},
            'context':{'installationContextId':'ctx','hierarchyRevision':'ctx:1','rootEntityUid':'root'},
            'model':copy.deepcopy(MODEL) if uid=='root' else None,'adoption':copy.deepcopy(adoption)} for uid in ('root','child')}
        super().__init__(SimpleNamespace(_request=self.request,prefix='/api/v1/projects/P'))
    def resolve(self,uids):
        self.resolutions.append(list(uids));return {uid:copy.deepcopy(self.records[uid]) for uid in uids}
    def request(self,method,path,body=None):
        self.calls.append((method,path,body))
        if path.endswith('/attribute-form'):
            return {'device':{'entityUid':path.split('/')[-2]},'available':True,'fields':[SERIAL],'values':[],'model':None}
        if self.failure:raise PreviewError(self.failure,'SOURCE_FAILURE')
        if '/specification-revisions/' in path:
            if self.after:self.after()
            return specification_revision(self.current,self.values)
        if '/template-revisions/' in path:return {'fields':[FIELD,SERIAL]}
        raise AssertionError(path)

class EquipmentParameterTests(unittest.TestCase):
    def read(self,service,uid='root',**changes):
        return service.attribute_form({'entityUid':uid,'expectedEntityRevision':'fixed:1','includeModel':True}|changes)
    def test_current_model_reads_only_its_specification_and_explicit_model_values(self):
        source=Parameters();result=self.read(source);model=result['modelAttributes']
        self.assertEqual(model['relation'],'equipment');self.assertEqual(model['model'],MODEL)
        self.assertEqual(model['fields'],[FIELD]);self.assertEqual(model['values'],[VALUE])
        self.assertTrue(any(path.endswith('/specification-revisions/'+MODEL['revisionId']) for _,path,_ in source.calls))
        self.assertTrue(all(method=='GET' for method,_,_ in source.calls))
    def test_rename_and_completed_parameters_follow_the_same_model_for_device_and_assembly(self):
        source=Parameters();head=str(uuid4());template=str(uuid4())
        source.records['root']['model']['headRevisionId']=head
        source.current.update(headRevisionId=head,revisionId=head,templateRevisionId=template,revision=2,name='Current equipment model')
        source.values=[VALUE,{'propertyKey':'serial','propertyRevisionId':'serial:r1','status':'known','value':'S2','unit':None}]
        for uid,relation in (('root','equipment'),('child','assembly')):
            study=self.read(source,uid)['modelAttributes']
            self.assertEqual(study['relation'],relation)
            self.assertEqual(study['model']['name'],'Current equipment model')
            self.assertEqual(study['model']['revisionId'],head)
            self.assertEqual(study['adoptedRevision'],1)
            self.assertEqual(study['values'],source.values)
        self.assertTrue(any('/template-revisions/'+template+'/effective' in path for _,path,_ in source.calls))
        self.assertFalse(any(path.endswith('/specification-revisions/'+MODEL['revisionId']) for _,path,_ in source.calls))
        self.assertEqual(source.records['root']['adoption']['specificationRevisionId'],MODEL['revisionId'])

    def test_another_model_or_a_newly_published_revision_is_not_mixed_with_current_parameters(self):
        for change in ('specificationId','headRevisionId'):
            source=Parameters();head=str(uuid4())
            source.records['root']['model']['headRevisionId']=head
            source.current.update(headRevisionId=head,revisionId=head,revision=2)
            source.current[change]=str(uuid4())
            with self.subTest(change=change),self.assertRaises(PreviewError) as error:self.read(source)
            self.assertEqual((error.exception.status,error.exception.code),(409,'ENGINEERING_CHANGED'))
    def test_child_assembly_context_is_explicit_and_does_not_replace_its_own_model(self):
        source=Parameters();result=self.read(source,'child')
        self.assertIsNone(result['model']);self.assertEqual(result['modelAttributes']['relation'],'assembly')
        self.assertEqual(result['modelAttributes']['equipmentName'],'root')
        self.assertEqual(source.resolutions[-1],['child','root'])
    def test_missing_model_and_missing_adoption_remain_empty_without_parent_guessing(self):
        source=Parameters();source.records['child']['adoption']=None
        self.assertEqual(self.read(source,'child')['modelAttributes']['reason'],'MODEL_NOT_REGISTERED')
        self.assertFalse(any('/specification-revisions/' in path for _,path,_ in source.calls));self.assertEqual(source.resolutions,[['child'],['child']])
    def test_invalid_bodies_and_stale_object_revision_never_read_parameters(self):
        source=Parameters()
        for body in ({'entityUid':'root','includeModel':True},{'entityUid':'root','expectedEntityRevision':'fixed:1','includeModel':'true'},
            {'entityUid':'root','expectedEntityRevision':'fixed:1','includeModel':True,'specificationRevisionId':MODEL['revisionId']}):
            with self.assertRaises(PreviewError) as error:source.attribute_form(body)
            self.assertEqual(error.exception.status,422)
        self.assertEqual(source.calls,[])
        with self.assertRaises(PreviewError) as error:self.read(source,expectedEntityRevision='old')
        self.assertEqual(error.exception.status,409);self.assertEqual(source.calls,[])
    def test_unrelated_installation_or_project_adoption_cannot_supply_a_model(self):
        for change in ('context','adoption'):
            source=Parameters()
            if change=='context':source.records['root']['context']['installationContextId']='other'
            else:source.records['root']['adoption']['applicationRevisionId']=str(uuid4())
            with self.assertRaises(PreviewError) as error:self.read(source,'child')
            self.assertEqual(error.exception.status,409)
    def test_changes_during_fixed_model_read_are_rejected(self):
        source=Parameters();source.after=lambda:source.records['root']['item'].update(entityRevision='fixed:2')
        with self.assertRaises(PreviewError) as error:self.read(source,'child')
        self.assertEqual(error.exception.status,409)
    def test_revocation_blocks_all_content_but_temporary_model_failure_keeps_device_fields(self):
        source=Parameters();source.failure=403
        with self.assertRaises(PreviewError) as error:self.read(source)
        self.assertEqual(error.exception.status,403)
        source=Parameters();source.failure=502;result=self.read(source)
        self.assertEqual(result['fields'],[SERIAL]);self.assertFalse(result['modelAttributes']['available'])
    def test_existing_device_only_contract_does_not_request_model_details(self):
        source=Parameters();result=source.attribute_form({'entityUid':'root'})
        self.assertNotIn('modelAttributes',result);self.assertEqual(source.resolutions,[]);self.assertEqual(len(source.calls),1)

if __name__=='__main__':unittest.main()
