"""Equipment configuration API, source scope and inherited scene location over real HTTP."""
import copy
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from tests import test_scene_bindings_http as bindings
from tests import test_scene_engineering as engineering
from tests import test_scene_location_http as locations

ROOT='/api/workbench/equipment'

class EquipmentAuthority(bindings.BindingAuthority):
    def __init__(self, base):
        super().__init__(base)
        self.engineering.objects[engineering.CABINET]['sourceTemplateEntityUid']='definition'
        self.engineering.objects['definition']['objectKind']='cabinet'

    def request(self,method,path,body=None):
        source=self.engineering
        if urlsplit(path).path.endswith('/equipment/resolve'):
            return {'projectCode':engineering.PROJECT,'items':[
                {'item':source.objects[uid],'context':source.contexts[source.objects[uid]['installationContextId']],
                 'children':[row for row in source.objects.values() if row['entityUid']!=uid
                     and row['installationContextId']==source.objects[uid]['installationContextId']]}
                for uid in body['entityUids']]}
        if urlsplit(path).path.endswith('/equipment'):
            return {'projectCode':engineering.PROJECT,'items':[source.objects[engineering.ROOT],source.objects[engineering.OTHER_ROOT]],'nextCursor':None,'snapshotRevision':'equipment:1'}
        return super().request(method,path,body)

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
        return {'displayName':'合成共享型号','objectKind':'equipment','rootDefinition':None,'models':[
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
        self.assertEqual(status,200,assigned)
        return config

    def test_routes_roundtrip_and_enforce_source_permissions(self):
        status,devices,_=self.request(ROOT,{'rootsOnly':True,'limit':50})
        self.assertEqual(status,200,devices);self.assertEqual(len(devices['items']),2)
        config=self.configure()
        status,values,_=self.request(ROOT+'/configurations',{})
        self.assertEqual(status,200,values)
        self.assertEqual(values['items'][0]['equipmentCount'],1)
        self.assertEqual(values['objects'][0]['entityUid'],'definition')
        self.assertEqual(values['models'][0]['modelVersionId'],self.version['modelVersionId'])
        self.authority().role='reader'
        self.assertEqual(self.request(ROOT+'/configurations',{})[0],200)
        body={'configurationId':self.cid,'expectedConfigurationRevision':config['configurationRevision'],
            'snapshot':self.profile(),'clientRequestId':str(uuid4())}
        self.expect(self.request(ROOT+'/configurations/save',body),403,'SCENE_WRITE_FORBIDDEN')
        self.expect(self.request(ROOT+'/configurations',{'source':'http://arbitrary.invalid'}),422,'INVALID_REQUEST')

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
