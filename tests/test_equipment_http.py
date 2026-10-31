"""Equipment configuration API, source scope and inherited scene location over real HTTP."""
import copy
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4
from tests.test_scene_evidence import PNG

from tests import test_scene_bindings_http as bindings
from tests import test_scene_engineering as engineering
from tests import test_scene_location_http as locations

ROOT='/api/workbench/equipment'

class EquipmentAuthority(bindings.BindingAuthority):
    def __init__(self, base):
        super().__init__(base)
        self.engineering.objects[engineering.CABINET]['sourceTemplateEntityUid']='definition'
        self.engineering.objects['definition']['objectKind']='cabinet'
        self.adopted=False
        self.application={'applicationId':str(uuid4()),'revisionId':str(uuid4()),'projectCode':engineering.PROJECT,
            'specification':{'objectKind':'equipment'},'snapshot':{'name':'源端合成共享规格',
                'specificationRevisionId':str(uuid4()),'rootDefinition':None,
                'mappings':[{'roleKey':'cabinet','entityUid':'definition','expectedEntityRevision':self.engineering.objects['definition']['entityRevision']}]}}
        self.source_ref={'applicationId':self.application['applicationId'],'applicationRevisionId':self.application['revisionId'],
            'specificationRevisionId':self.application['snapshot']['specificationRevisionId']}
        self.source_calls=[]
        self.specification={'revisionId':self.source_ref['specificationRevisionId'],
            'snapshot':{'templateRevisionId':str(uuid4()),'classificationRef':{'code':'PUMP'}}}

    def request(self,method,path,body=None):
        source=self.engineering
        self.source_calls.append((method,path,body))
        if urlsplit(path).path.endswith('/equipment-applications'):return {'items':[self.application],'total':1,'offset':0,'limit':50}
        if '/equipment-catalog/specification-revisions/' in path:return copy.deepcopy(self.specification)
        if '/equipment-catalog/template-revisions/' in path:return {'fields':[]}
        if path.endswith('/equipment/shared-photos/query'):return {'items':[],'nextCursor':None}
        if path.endswith('/equipment/shared-photos/regions'):return {'items':[],'nextCursor':None}
        if '/equipment-applications/revisions/' in path:return copy.deepcopy(self.application)
        if urlsplit(path).path.endswith('/equipment/resolve'):
            return {'projectCode':engineering.PROJECT,'items':[
                {'item':source.objects[uid],'context':source.contexts[source.objects[uid]['installationContextId']],
                 'adoption':dict(self.source_ref,adoptionId=str(uuid4())) if self.adopted else None,
                 'children':[row for row in source.objects.values() if row['entityUid']!=uid
                     and row['installationContextId']==source.objects[uid]['installationContextId']]}
                for uid in body['entityUids']]}
        if urlsplit(path).path.endswith('/equipment'):
            return {'projectCode':engineering.PROJECT,'items':[source.objects[engineering.ROOT],source.objects[engineering.OTHER_ROOT]],'nextCursor':None,'snapshotRevision':'equipment:1'}
        return super().request(method,path,body)

    def photo(self,path,body,digest):
        self.source_calls.append(('POST',path,body))
        return {'content':PNG,'mediaType':'image/png','sha256':'fixture-digest'}

class EquipmentHttpTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(bindings,'BindingAuthority',EquipmentAuthority))
        bindings.SceneBindingsHttpTests.setUp(self)
        self.cid=str(uuid4())

    request = locations.SceneLocationHttpTests.request
    login = locations.SceneLocationHttpTests.login
    authority = locations.SceneLocationHttpTests.authority
    listing = locations.SceneLocationHttpTests.listing
    metadata = locations.SceneLocationHttpTests.metadata
    upload = locations.SceneLocationHttpTests.upload
    calibration = locations.SceneLocationHttpTests.calibration
    calibrate = locations.SceneLocationHttpTests.calibrate
    upload_calibrated = locations.SceneLocationHttpTests.upload_calibrated
    expect = locations.SceneLocationHttpTests.expect
    item = locations.SceneLocationHttpTests.item
    create = locations.SceneLocationHttpTests.create
    opened = locations.SceneLocationHttpTests.opened
    open_ok = locations.SceneLocationHttpTests.open_ok
    check = locations.SceneLocationHttpTests.check
    checked_body = locations.SceneLocationHttpTests.checked_body
    saved = locations.SceneLocationHttpTests.saved
    counts = locations.SceneLocationHttpTests.counts
    location_body = locations.SceneLocationHttpTests.location_body
    locate = locations.SceneLocationHttpTests.locate
    location = locations.SceneLocationHttpTests.location
    ref = staticmethod(locations.SceneLocationHttpTests.ref)

    def profile(self):
        item=self.authority().engineering.objects['definition']
        return {'projectApplicationRef':self.authority().source_ref,'models':[
            {'modelVersionId':self.version['modelVersionId'],'mappings':[{'objectRef':self.ref('definition'),
                'expectedEntityRevision':item['entityRevision'],'componentKeys':[self.component_key]}]}]}

    def configure(self):
        body={'configurationId':self.cid,'expectedConfigurationRevision':None,'snapshot':self.profile(),'clientRequestId':str(uuid4())}
        status,config,_=self.request(ROOT+'/configurations/save',body)
        self.assertEqual(status,200,config)
        status,items,_=self.request(ROOT+'/resolve',{'entityUids':[engineering.ROOT]})
        self.assertEqual(status,200,items)
        row=items['items'][0]
        status,assigned,_=self.request(ROOT+'/configurations/assign',{'configurationId':self.cid,
            'expectedConfigurationRevision':config['configurationRevision'],'clientRequestId':str(uuid4()),'equipment':[
            {'entityUid':engineering.ROOT,'expectedEntityRevision':row['item']['entityRevision'],
             'expectedHierarchyRevision':row['context']['hierarchyRevision'],'expectedAssignmentRevision':None}]})
        self.assertEqual(status,409,assigned);self.assertEqual(assigned['code'],'SOURCE_MANAGED')
        self.authority().adopted=True
        return config

    def test_routes_roundtrip_and_enforce_source_permissions(self):
        status,devices,_=self.request(ROOT,{'rootsOnly':True,'limit':50})
        self.assertEqual(status,200,devices);self.assertEqual(len(devices['items']),2)
        config=self.configure()
        status,values,_=self.request(ROOT+'/configurations',{})
        self.assertEqual(status,200,values)
        self.assertIsNone(values['items'][0]['equipmentCount'])
        self.assertEqual(values['objects'][0]['entityUid'],'definition')
        self.assertEqual(values['models'][0]['modelVersionId'],self.version['modelVersionId'])
        self.authority().role='reader'
        self.assertEqual(self.request(ROOT+'/configurations',{})[0],200)
        body={'configurationId':self.cid,'expectedConfigurationRevision':config['configurationRevision'],
            'snapshot':self.profile(),'clientRequestId':str(uuid4())}
        self.expect(self.request(ROOT+'/configurations/save',body),403,'SCENE_WRITE_FORBIDDEN')
        self.expect(self.request(ROOT+'/configurations',{'source':'http://arbitrary.invalid'}),422,'INVALID_REQUEST')

    def test_source_details_and_shared_photos_use_bounded_fixed_routes(self):
        source=self.authority();source.source_calls.clear()
        status,value,_=self.request(ROOT+'/applications',{'offset':0,'limit':50})
        self.assertEqual(status,200,value)
        status,value,_=self.request(ROOT+'/applications/detail',{'applicationRevisionId':source.application['revisionId']})
        self.assertEqual(status,200,value);self.assertEqual(value['specification']['revisionId'],source.specification['revisionId'])
        self.assertEqual(len(value['objects']),1)
        selection={'entityUid':engineering.ROOT,'expectedEntityRevision':'fixed:1','installationContextId':engineering.CTX,
            'expectedHierarchyRevision':'tree:1'}
        before=len(source.source_calls)
        self.assertEqual(self.request(ROOT+'/shared-photos/query',{**selection,'limit':12,'cursor':None})[0],200)
        self.assertEqual(self.request(ROOT+'/shared-photos/regions',{**selection,'limit':50,'cursor':None})[0],200)
        self.assertEqual(self.request(ROOT+'/shared-photos/content',{**selection,'representation':'thumbnail'})[0],200)
        self.assertEqual(len([call for call in source.source_calls[before:] if '/equipment/shared-photos/' in call[1]]),3)
        self.expect(self.request(ROOT+'/applications',{'source':'http://arbitrary.invalid'}),422,'INVALID_REQUEST')
        self.expect(self.request(ROOT+'/photos/associate',{}),409,'SOURCE_MANAGED')

    def test_shared_definition_locates_actual_child_and_preserves_scene_snapshot(self):
        self.configure();scene=self.create();snapshot=copy.deepcopy(scene['snapshot'])
        snapshot['instances']=[self.item('合成设备 A',engineering.ROOT)]
        scene=self.saved(scene,snapshot)
        choice={'sceneModelInstanceId':scene['snapshot']['instances'][0]['sceneModelInstanceId'],
                'modelVersionId':self.version['modelVersionId']}
        located=self.location(scene,'definition',choice=choice)
        self.assertEqual(located['status'],'located')
        self.assertEqual(located['selectedObject']['entityUid'],'definition')
        self.assertEqual(located['hostObject']['entityUid'],engineering.CABINET)
        self.assertEqual(located['componentKeys'],[self.component_key])
        self.assertEqual(located['sharedConfiguration']['configurationId'],self.cid)
        self.assertEqual(self.open_ok(scene)['snapshot']['instances'][0]['componentBindings'],[])
        with self.sessions.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from scene_equipment_configuration_uses').fetchone()[0],1)

    def test_adopted_instance_does_not_accept_a_private_mapping_override(self):
        self.configure();scene=self.create();snapshot=copy.deepcopy(scene['snapshot'])
        snapshot['instances']=[self.item('合成设备 A',engineering.ROOT)]
        scene=self.saved(scene,snapshot)
        changed=copy.deepcopy(scene['snapshot'])
        changed['instances'][0]['componentBindings']=[{'objectRef':self.ref(engineering.CABINET),'componentKeys':[self.component_key]}]
        status,result,_=self.check(scene,changed)
        self.assertEqual(status,409,result)
        self.assertEqual(result,{'code':'SHARED_CONFIGURATION_REQUIRED'})

if __name__=='__main__':unittest.main()
