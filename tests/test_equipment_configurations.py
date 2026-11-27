import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.equipment_configurations import EquipmentConfigurations
from apps.api.model_library import ModelLibrary


class EquipmentConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.library=ModelLibrary(Path(self.temp.name),'A',None)
        self.store=EquipmentConfigurations(self.library,'source','A')
        self.cid=str(uuid4());self.version=str(uuid4())
        self.ref={'ontobaseConnectionId':'source','projectCode':'A','entityUid':'shared-cabinet'}
        self.snapshot={'displayName':'同型号配置','objectKind':'turbine','rootDefinition':None,
            'models':[{'modelVersionId':self.version,'mappings':[{'objectRef':self.ref,'expectedEntityRevision':'definition:1','componentKeys':['cabinet']}]}]}

    @staticmethod
    def authorize():pass

    @staticmethod
    def objects(uid):
        return {'item':{'entityUid':uid,'installationContextId':None,'entityRevision':'definition:1','objectKind':'cabinet'}}

    def save(self,revision=None,**changes):
        body={'configurationId':self.cid,'expectedConfigurationRevision':revision,'snapshot':copy.deepcopy(self.snapshot),'clientRequestId':str(uuid4()),**changes}
        return self.store.save(body,'user',self.authorize,self.objects,lambda _: [{'componentKey':'cabinet'},{'componentKey':'generator'}])

    @staticmethod
    def equipment(uids):
        return {uid:{'item':{'entityUid':uid,'equipmentState':'active','entityRevision':uid+':1','objectKind':'turbine'},
            'context':{'rootEntityUid':uid,'hierarchyRevision':uid+':tree1'}} for uid in uids}

    def assignment(self, revision, uids=('unit7','unit18')):
        return {'configurationId':self.cid,'expectedConfigurationRevision':revision,'clientRequestId':str(uuid4()),
            'equipment':[{'entityUid':uid,'expectedEntityRevision':uid+':1','expectedHierarchyRevision':uid+':tree1','expectedAssignmentRevision':None} for uid in uids]}

    def source_application(self):
        return {'applicationId':str(uuid4()),'revisionId':str(uuid4()),'projectCode':'A',
            'specification':{'objectKind':'turbine'},'snapshot':{'name':'源端教学规格 · 已采用配置',
                'specificationRevisionId':str(uuid4()),'rootDefinition':None,
                'mappings':[{'roleKey':'cabinet','entityUid':'shared-cabinet','expectedEntityRevision':'definition:1'}]}}

    def source_save(self, application, revision=None, **changes):
        ref={'applicationId':application['applicationId'],'applicationRevisionId':application['revisionId'],
             'specificationRevisionId':application['snapshot']['specificationRevisionId']}
        body={'configurationId':self.cid,'expectedConfigurationRevision':revision,'clientRequestId':str(uuid4()),
              'snapshot':{'projectApplicationRef':ref,'models':copy.deepcopy(self.snapshot['models'])},**changes}
        return self.store.save(body,'user',self.authorize,self.objects,lambda _:[{'componentKey':'cabinet'}],application=application)

    def test_source_adoption_selects_binding_without_private_equipment_assignments(self):
        app=self.source_application();saved=self.source_save(app)
        ref=saved['snapshot']['projectApplicationRef']
        self.assertEqual(saved['snapshot']['displayName'],app['snapshot']['name'])
        self.assertEqual(self.store.for_equipment('unit7',lambda u:{'unit7':{'adoption':ref}})['configurationId'],self.cid)
        self.assertIsNone(self.store.for_equipment('unit7',lambda u:{'unit7':{'adoption':None}}))
        with self.library.connect() as db:self.assertEqual(db.execute('select count(*) from equipment_configuration_assignments').fetchone()[0],0)
        with self.assertRaisesRegex(PreviewError,'APPLICATION_BINDING_EXISTS'):
            self.source_save(app,configurationId=str(uuid4()))

    def test_source_roles_and_fixed_revisions_cannot_be_overridden(self):
        app=self.source_application();saved=self.source_save(app)
        changed=copy.deepcopy(app);changed['revisionId']=str(uuid4())
        with self.assertRaisesRegex(PreviewError,'SOURCE_APPLICATION_MISMATCH'):
            self.source_save(changed,saved['configurationRevision'])
        self.snapshot['models'][0]['mappings'][0]['expectedEntityRevision']='definition:2'
        with self.assertRaisesRegex(PreviewError,'DEFINITION_NOT_IN_APPLICATION'):self.source_save(app,saved['configurationRevision'])

    def test_legacy_attachment_preserves_bindings_and_fixed_history(self):
        old=self.save();app=self.source_application();saved=self.source_save(app,old['configurationRevision'])
        self.assertEqual(saved['snapshot']['models'],old['snapshot']['models'])
        self.assertNotIn('projectApplicationRef',self.store.detail(self.cid,old['configurationRevision'],self.authorize)['snapshot'])
        other=self.source_application();self.cid=str(uuid4());old=self.save()
        self.snapshot['models'][0]['mappings'][0]['componentKeys']=[]
        with self.assertRaisesRegex(PreviewError,'LEGACY_MAPPING_CHANGED'):self.source_save(other,old['configurationRevision'])

    def test_current_scene_uses_source_adoption_and_history_keeps_legacy_revision(self):
        first,scene,equipment=self.populated_scene();app=self.source_application()
        with self.library.connect() as db:
            db.execute('create table scene_revisions(revision text primary key)');db.execute("insert into scene_revisions values('r1')")
            for uid in ('unit7','unit18'):db.execute('insert into scene_equipment_configuration_uses values(?,?,?,?,?)',('r1',uid,self.cid,first['configurationRevision'],uid))
        saved=self.source_save(app,first['configurationRevision'])
        def current(uids):
            rows=equipment(uids)
            for row in rows.values():row['adoption']=saved['snapshot']['projectApplicationRef']
            return rows
        _,uses=self.store.resolve_scene(scene,current,self.authorize)
        self.assertTrue(all(u['configurationRevision']==saved['configurationRevision'] for u in uses));self.assertEqual(len(uses),2)
        _,old=self.store.resolve_scene(dict(scene,sceneRevision='r1',headRevision='new'),current,self.authorize)
        self.assertTrue(all(u['configurationRevision']==first['configurationRevision'] for u in old))

    def test_one_configuration_update_is_shared_and_history_is_immutable(self):
        first=self.save();body=self.assignment(first['configurationRevision'])
        adopted=self.store.assign(body,'user',self.authorize,self.equipment)
        self.assertEqual(self.store.assign(body,'user',self.authorize,self.equipment),adopted)
        changed=copy.deepcopy(self.snapshot);changed['displayName']='共享配置新名称'
        second=self.save(first['configurationRevision'],snapshot=changed)
        catalogue=self.store.catalogue(self.authorize)
        self.assertEqual(len(catalogue['items']),1);self.assertEqual(catalogue['items'][0]['equipmentCount'],2)
        self.assertEqual(catalogue['items'][0]['configurationRevision'],second['configurationRevision'])
        self.assertEqual({x['configuration_id'] for x in catalogue['assignments']},{self.cid})
        with self.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from equipment_configuration_revisions').fetchone()[0],2)
            self.assertIn('同型号配置',db.execute('select snapshot from equipment_configuration_revisions where revision=?',(first['configurationRevision'],)).fetchone()[0])

    def test_stale_write_and_concurrent_edits_never_overwrite(self):
        first=self.save()
        def update(name):
            snapshot=copy.deepcopy(self.snapshot);snapshot['displayName']=name
            try:self.save(first['configurationRevision'],snapshot=snapshot);return 200
            except PreviewError as error:return error.status
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(update,['A','B'])),[200,409])

    def test_cross_project_or_installed_mapping_is_rejected(self):
        snapshot=copy.deepcopy(self.snapshot);snapshot['models'][0]['mappings'][0]['objectRef']['projectCode']='B'
        with self.assertRaises(PreviewError):self.save(snapshot=snapshot)
        with self.assertRaises(PreviewError):
            self.store.save({'configurationId':self.cid,'expectedConfigurationRevision':None,'snapshot':self.snapshot,'clientRequestId':str(uuid4())},'user',self.authorize,
                lambda uid:{'item':{'installationContextId':'unit7'}},lambda _:[{'componentKey':'cabinet'}])

    def test_duplicate_component_and_unknown_component_are_rejected(self):
        for keys in (['cabinet','cabinet'],['missing']):
            snapshot=copy.deepcopy(self.snapshot);snapshot['models'][0]['mappings'][0]['componentKeys']=keys
            with self.assertRaises(PreviewError):self.save(snapshot=snapshot)

    def test_assignment_versions_and_permissions_are_checked_even_on_replay(self):
        first=self.save();body=self.assignment(first['configurationRevision'])
        self.store.assign(body,'user',self.authorize,self.equipment)
        def denied():raise PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.store.assign(body,'user',denied,self.equipment)
        with self.assertRaises(PreviewError):self.store.assign(body|{'clientRequestId':str(uuid4())},'user',self.authorize,self.equipment)

    def test_idempotency_key_does_not_accept_different_content(self):
        request=str(uuid4());self.save(clientRequestId=request)
        snapshot=copy.deepcopy(self.snapshot);snapshot['displayName']='different'
        with self.assertRaises(PreviewError):self.save(clientRequestId=request,snapshot=snapshot)

    def populated_scene(self):
        first=self.save();self.store.assign(self.assignment(first['configurationRevision']),'user',self.authorize,self.equipment)
        scene={'sceneRevision':'r1','headRevision':'r1','snapshot':{'instances':[
            {'sceneModelInstanceId':uid,'modelVersionId':self.version,'rootBinding':{'objectRef':{**self.ref,'entityUid':uid}},'componentBindings':[]} for uid in ('unit7','unit18')]},
            'validation':{'engineeringExpectations':[]}}
        def equipment(uids):
            result=self.equipment(uids)
            for uid,row in result.items():
                row['context']['installationContextId']=uid+'-context'
                row['children']=[{'entityUid':uid+'-cabinet','sourceTemplateEntityUid':'shared-cabinet','entityRevision':uid+'-cabinet:1'}]
            return result
        return first,scene,equipment

    def test_runtime_expands_one_shared_mapping_to_distinct_devices_without_mutating_scene(self):
        first,scene,equipment=self.populated_scene();before=copy.deepcopy(scene)
        projected,uses=self.store.resolve_scene(scene,equipment,self.authorize)
        self.assertEqual(scene,before)
        self.assertEqual([i['componentBindings'][0]['objectRef']['entityUid'] for i in projected['snapshot']['instances']],['unit7-cabinet','unit18-cabinet'])
        self.assertEqual({u['configurationRevision'] for u in uses},{first['configurationRevision']})
        self.assertEqual(len(projected['validation']['engineeringExpectations']),2)

    def test_saved_scene_history_keeps_its_configuration_revision(self):
        first,scene,equipment=self.populated_scene()
        with self.library.connect() as db:
            db.execute('create table scene_revisions(revision text primary key)');db.execute("insert into scene_revisions values('r1')")
            for uid in ('unit7','unit18'):db.execute('insert into scene_equipment_configuration_uses values(?,?,?,?,?)',('r1',uid,self.cid,first['configurationRevision'],uid))
        snapshot=copy.deepcopy(self.snapshot);snapshot['models'][0]['mappings'][0]['componentKeys']=['generator']
        self.save(first['configurationRevision'],snapshot=snapshot)
        current,_=self.store.resolve_scene(scene,equipment,self.authorize)
        self.assertEqual(current['snapshot']['instances'][0]['componentBindings'][0]['componentKeys'],['generator'])
        historical=copy.deepcopy(scene);historical['headRevision']='r2'
        old,uses=self.store.resolve_scene(historical,equipment,self.authorize)
        self.assertEqual(old['snapshot']['instances'][0]['componentBindings'][0]['componentKeys'],['cabinet'])
        self.assertEqual(uses[0]['configurationRevision'],first['configurationRevision'])

    def test_conflicting_old_instance_mapping_is_reported_and_preserved(self):
        _,scene,equipment=self.populated_scene()
        original={'objectRef':{**self.ref,'entityUid':'different-device'},'componentKeys':['cabinet']}
        scene['snapshot']['instances'][0]['componentBindings']=[original]
        projected,uses=self.store.resolve_scene(scene,equipment,self.authorize)
        self.assertEqual(projected['snapshot']['instances'][0]['componentBindings'],[original])
        self.assertEqual(uses[0]['conflicts'],['shared-cabinet'])


if __name__=='__main__':unittest.main()
