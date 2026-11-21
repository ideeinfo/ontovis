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
        self.application['headRevisionId']=self.application['revisionId']
        self.adoption_id=str(uuid4())
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
        if '/equipment-applications/revisions/' in path and urlsplit(path).path.endswith('/equipment'):
            adopters=[dict(entityUid=engineering.ROOT,adoptionId=self.adoption_id)] if self.adopted else []
            return dict(projectCode=engineering.PROJECT,applicationRevisionId=self.application['revisionId'],
                        items=adopters,total=len(adopters),nextOffset=None,snapshotRevision='adopters:1')
        if '/equipment-applications/revisions/' in path:return copy.deepcopy(self.application)
        if urlsplit(path).path.endswith('/equipment/resolve'):
            return {'projectCode':engineering.PROJECT,'items':[
                {'item':source.objects[uid],'context':source.contexts[source.objects[uid]['installationContextId']],
                 'adoption':dict(self.source_ref,adoptionId=self.adoption_id) if self.adopted and uid==engineering.ROOT else None,
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

    def test_assistant_configuration_preview_is_fixed_read_only_and_role_checked(self):
        config=self.configure()
        candidate=self.upload_calibrated(self.version['modelAssetId'])
        self.authority().adopted=False
        scene=self.create()
        snapshot=copy.deepcopy(scene['snapshot'])
        snapshot['instances']=[self.item('Adopted current',engineering.ROOT),
                               self.item('Adopted candidate',engineering.ROOT,candidate),
                               self.item('Other device',engineering.OTHER_ROOT)]
        scene=self.saved(scene,snapshot);counts=self.counts()
        self.authority().adopted=True
        device=dict(entityUid=engineering.ROOT,entityRevision=self.authority().engineering.objects[engineering.ROOT]['entityRevision'])
        target=dict(configurationId=self.cid,configurationRevision=config['configurationRevision'])
        route=ROOT+'/configurations/detail'
        status,prior,_=self.request(route,target)
        self.assertEqual(200,status,prior);self.assertNotIn('impact',prior)
        preview={**target,'includeImpact':True,'device':device}
        status,value,_=self.request(route,preview)
        self.assertEqual(200,status,value);self.assertTrue(value['canPrepare'])
        self.assertEqual(1,value['impact']['total'])
        self.assertEqual('Adopted current',value['impact']['items'][0]['instanceName'])
        self.assertEqual([self.component_key],value['snapshot']['models'][0]['mappings'][0]['componentKeys'])
        proposed={**preview,'proposedModelVersionId':candidate['modelVersionId']}
        status,value,_=self.request(route,proposed)
        self.assertEqual(200,status,value)
        self.assertEqual(candidate['modelVersionId'],value['proposal']['modelVersionId'])
        self.assertEqual({'Adopted current','Adopted candidate'},{row['instanceName'] for row in value['impact']['items']})
        self.assertEqual(2,value['impact']['total'])
        self.assertEqual(prior,self.request(route,target)[1])
        self.authority().role='reader'
        status,value,_=self.request(route,preview)
        self.assertEqual(200,status,value);self.assertFalse(value['canPrepare'])
        self.expect(self.request(route,proposed),403,'SCENE_WRITE_FORBIDDEN')
        self.expect(self.request(route,{**preview,'requireCurrent':True}),403,'SCENE_WRITE_FORBIDDEN')
        self.authority().role='admin'
        self.expect(self.request(route,{**preview,'device':{**device,'entityRevision':'stale'}}),409,'ENGINEERING_CHANGED')
        next_profile=self.profile();next_profile['models'].append(dict(modelVersionId=candidate['modelVersionId'],mappings=[]))
        status,new,_=self.request(ROOT+'/configurations/save',dict(configurationId=self.cid,
            expectedConfigurationRevision=target['configurationRevision'],snapshot=next_profile,clientRequestId=str(uuid4()),
            requireCurrentApplication=True))
        self.assertEqual(200,status,new)
        self.assertNotEqual(target['configurationRevision'],new['configurationRevision'])
        self.assertEqual(prior,self.request(route,target)[1])
        self.expect(self.request(route,proposed),409,'REVISION_CONFLICT')
        status,historical,_=self.request(route,preview)
        self.assertEqual(200,status,historical);self.assertFalse(historical['canPrepare']);self.assertIsNone(historical['impact'])
        self.authority().application['headRevisionId']=str(uuid4())
        self.expect(self.request(ROOT+'/configurations/save',dict(configurationId=self.cid,
            expectedConfigurationRevision=new['configurationRevision'],snapshot=next_profile,clientRequestId=str(uuid4()),
            requireCurrentApplication=True)),409,'ENGINEERING_CHANGED')
        self.assertEqual(snapshot['instances'],self.open_ok(scene)['snapshot']['instances'])
        self.assertEqual(counts,self.counts())

    def test_configuration_preview_rechecks_project_access_after_read(self):
        config=self.configure();source=self.authority()
        original=self.sessions.project_models.fixed_version_metadata
        def revoke(version,authorize):
            value=original(version,authorize)
            source.allowed=False
            return value
        with patch.object(self.sessions.project_models,'fixed_version_metadata',side_effect=revoke):
            self.expect(self.request(ROOT+'/configurations/detail',dict(configurationId=self.cid,
                configurationRevision=config['configurationRevision'],includeImpact=True)),403,'FORBIDDEN')

    def test_adopted_instance_does_not_accept_a_private_mapping_override(self):
        self.configure();scene=self.create();snapshot=copy.deepcopy(scene['snapshot'])
        snapshot['instances']=[self.item('合成设备 A',engineering.ROOT)]
        scene=self.saved(scene,snapshot)
        changed=copy.deepcopy(scene['snapshot'])
        changed['instances'][0]['componentBindings']=[{'objectRef':self.ref(engineering.CABINET),'componentKeys':[self.component_key]}]
        status,result,_=self.check(scene,changed)
        self.assertEqual(status,409,result)
        self.assertEqual(result,{'code':'SHARED_CONFIGURATION_REQUIRED'})

    def inspection_scene(self):
        versions = []
        for kind in ('detailed', 'appearance'):
            status, raw, _ = self.upload(self.metadata(representationType=kind, modelCode='SYNTHETIC-COMPRESSOR'))
            self.assertEqual(status, 200, raw)
            status, model, _ = self.calibrate(self.calibration(raw))
            self.assertEqual(status, 200, model); versions.append(model)
        self.version, appearance = versions; self.component_key = self.version['components'][0]['componentKey']
        config = self.configure(); profile = self.profile()
        profile['models'].append({'modelVersionId': appearance['modelVersionId'], 'mappings': []})
        status, config, _ = self.request(ROOT+'/configurations/save', {'configurationId': self.cid,
            'expectedConfigurationRevision': config['configurationRevision'], 'snapshot': profile, 'clientRequestId': str(uuid4())})
        self.assertEqual(status, 200, config)
        scene = self.create(); snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'] = [self.item('合成压缩机', engineering.ROOT, appearance)]
        return self.saved(scene, snapshot), appearance

    def test_generic_hot_switch_uses_adopted_fixed_model_over_real_http_without_saving_scene(self):
        scene, appearance = self.inspection_scene(); before = self.counts()
        original = copy.deepcopy(scene['snapshot']['instances'][0])
        choice = {'sceneModelInstanceId': original['sceneModelInstanceId'], 'modelVersionId': appearance['modelVersionId']}
        ordinary = self.location(scene, engineering.CABINET, choice=choice)
        self.assertEqual(ordinary['modelVersionId'], appearance['modelVersionId'])
        self.assertNotIn('representation', ordinary)
        for uid in (engineering.CABINET, 'definition', engineering.ROOT):
            with self.subTest(uid=uid):
                located = self.location(scene, uid, choice=choice, preferDetailed=True)
                self.assertEqual(located['status'], 'located')
                self.assertEqual(located['modelVersionId'], self.version['modelVersionId'])
                self.assertEqual(located['selectedObject']['entityUid'], uid)
                representation = located['representation']
                self.assertEqual(representation['sourceModelVersionId'], appearance['modelVersionId'])
                self.assertEqual(representation['model']['representationType'], 'detailed')
                self.assertEqual(representation['modelRef']['sha256'], self.version['sha256'])
                self.assertEqual(representation['instance']['placement'], original['placement'])
                self.assertEqual(representation['instance']['rootBinding'], original['rootBinding'])
                self.assertEqual(representation['instance']['componentBindings'][0]['objectRef']['entityUid'], engineering.CABINET)
        self.assertEqual(self.open_ok(scene)['snapshot']['instances'][0], original)
        self.assertEqual(self.counts(), before)

    def test_hot_switch_discards_payload_if_access_is_revoked_during_detail_load(self):
        scene, appearance = self.inspection_scene(); before = self.counts()
        original = self.sessions.project_models.model
        def load(asset, version, authorize):
            value = original(asset, version, authorize)
            if version == self.version['modelVersionId']: self.authority().allowed = False
            return value
        choice = {'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId'], 'modelVersionId': appearance['modelVersionId']}
        with patch.object(self.sessions.project_models, 'model', side_effect=load):
            self.expect(self.locate(scene, engineering.CABINET, choice=choice, preferDetailed=True), 403, 'FORBIDDEN')
        self.assertEqual(self.counts(), before)

if __name__=='__main__':unittest.main()
