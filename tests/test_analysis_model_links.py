"""Relationship provenance and selected-object recommendations; no live engineering writes."""
import json
import sqlite3
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.api.analysis_model_links import object_names, scene_bindings
from apps.api.analysis_preview import relationships
from apps.api.analysis_queries import recommendations
from apps.api.authority import PreviewError


class ModelAssociationTests(TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.executescript('''
            create table scenes(id text,head_revision text,project_code text);
            create table scene_revisions(revision text,snapshot text);
            create table scene_spatial_validations(revision text,validation text);
            create table scene_lifecycle(scene_id text,state text);
            create table scene_resource_uses(revision text,model_version_id text);
            create table project_model_assets(id text primary key,name text,project_code text);
            create table project_model_versions(asset_id text,version_id text,content_revision text);
            create table versions(id text,sha256 text,components text,created_at text);
            create table project_model_lifecycle(asset_id text,state text);''')
        self.library = SimpleNamespace(connect=lambda: self.db)
        self.item = {'entityUid': 'definition-cabinet', 'entityRevision': 'r1', 'objectKind': 'cabinet', 'objectScope': 'definition',
            'identifiers': [{'value': '=PLANT+CB7', 'role': 'primary', 'scheme': 'RDS', 'status': 'accepted', 'scopeType': 'project', 'scopeKey': 'P'}]}
        self.reader = SimpleNamespace(reader=SimpleNamespace(project_code='P', connection_id='source',
            context_for_object=Mock(return_value={'item': self.item, 'context': None})),
            models=SimpleNamespace(library=self.library, project_code='shared-models', listing=Mock(side_effect=AssertionError('No full catalogue scan'))),
            authorize=Mock(), actor='synthetic-owner')
        self.components = [{'componentKey': 'cabinet-key', 'displayName': 'CB7'}]

    def model(self, asset='asset', version='version', name='Cabinet model', date='1', components=None, deleted=False):
        self.db.execute('insert or ignore into project_model_assets values(?,?,?)', (asset, name, 'shared-models'))
        self.db.execute('insert into project_model_versions values(?,?,?)', (asset, version, 'content-'+version))
        self.db.execute('insert into versions values(?,?,?,?)', (version, 'a'*64, json.dumps(self.components if components is None else components), date))
        if deleted: self.db.execute('insert into project_model_lifecycle values(?,?)', (asset, 'deleted'))

    def scene(self, uid='definition-cabinet', version='version', state='active', key='cabinet-key', *, name='scene', project='P', connection='source', blocking=False, whole=False):
        ref = {'entityUid': uid, 'projectCode': project, 'ontobaseConnectionId': connection}
        instance = {'modelVersionId': version, 'sceneModelInstanceId': 'instance', 'componentBindings': []}
        if whole: instance['rootBinding'] = {'objectRef': ref}
        else: instance['componentBindings'] = [{'objectRef': ref, 'componentKeys': [key]}]
        self.db.execute('insert into scenes values(?,?,?)', (name, name, 'P'))
        self.db.execute('insert into scene_revisions values(?,?)', (name, json.dumps({'instances': [instance]})))
        self.db.execute('insert into scene_lifecycle values(?,?)', (name, state))
        self.db.execute('insert into scene_resource_uses values(?,?)', (name, version))
        if blocking: self.db.execute('insert into scene_spatial_validations values(?,?)', (name, json.dumps({'bindingIssues': [{'blocking': True, 'sceneModelInstanceId': 'instance', 'objectRef': ref}]})))

    def recommended(self, **extra):
        body = {'entry': {'projectOnly': True}, 'section': 'models', 'entityUid': self.item['entityUid'], 'expectedEntityRevision': 'r1', **extra}
        return recommendations(self.reader, body, self.library)

    def linked(self):
        self.reader.read = Mock(side_effect=lambda kind, desc: {'item': self.item} if kind == 'object' else {'components': self.components})
        return relationships(self.reader, [({'evidenceRefId': 'object', 'sourceKind': 'object'}, {'entityUid': self.item['entityUid']}),
            ({'evidenceRefId': 'model', 'sourceKind': 'model'}, {'modelVersionId': 'version'})], self.library)

    def test_canvas_keeps_the_configuration_revision_captured_when_model_was_added(self):
        from apps.api.analysis_model_links import configuration_references, frozen_configuration_bindings
        self.db.executescript('create table equipment_configurations(id text,head_revision text,project_code text);'
            'create table equipment_configuration_revisions(configuration_id text,revision text,snapshot text);'
            'create table equipment_configuration_assignments(equipment_uid text,configuration_id text);')
        profile={'models':[{'modelVersionId':'version','mappings':[{'objectRef':{'entityUid':'definition-cabinet'},'componentKeys':['cabinet-key']}]}]}
        self.db.execute("insert into equipment_configurations values('configuration','r1','P')")
        self.db.execute('insert into equipment_configuration_revisions values(?,?,?)',('configuration','r1',json.dumps(profile)))
        self.db.execute("insert into equipment_configuration_assignments values('unit7','configuration')")
        captured=configuration_references(self.library,'version','P')
        profile['models'][0]['mappings'][0]['componentKeys']=['changed-key']
        self.db.execute('insert into equipment_configuration_revisions values(?,?,?)',('configuration','r2',json.dumps(profile)))
        self.db.execute("update equipment_configurations set head_revision='r2'")
        frozen=frozen_configuration_bindings(self.reader,self.library,'version',captured)
        self.assertEqual(frozen[0]['componentKeys'],['cabinet-key'])
        self.assertEqual(frozen[0]['configurationRevision'],'r1')
        self.assertEqual(frozen[0]['equipmentEntityUid'],'unit7')
        self.assertEqual(configuration_references(self.library,'version','other-project'),[])

    def test_source_adopters_drive_current_bindings_and_canvas_capture(self):
        from apps.api.analysis_model_links import configuration_references, shared_configuration_bindings, frozen_configuration_bindings
        self.db.executescript('create table equipment_configurations(id text,head_revision text,project_code text);'
            'create table equipment_configuration_revisions(configuration_id text,revision text,snapshot text);'
            'create table equipment_configuration_assignments(equipment_uid text,configuration_id text);')
        application='00000000-0000-4000-8000-000000000001'
        profile={'projectApplicationRef':{'applicationRevisionId':application},'models':[{'modelVersionId':'version',
            'mappings':[{'objectRef':{'entityUid':'definition-cabinet','projectCode':'P','ontobaseConnectionId':'source'},
                'expectedEntityRevision':'r1','componentKeys':['cabinet-key']}]}]}
        self.db.execute("insert into equipment_configurations values('configuration','r1','P')")
        self.db.execute('insert into equipment_configuration_revisions values(?,?,?)',('configuration','r1',json.dumps(profile)))
        self.db.execute("insert into equipment_configuration_assignments values('stale-private-adopter','configuration')")
        self.scene(uid='unit7',whole=True)
        self.reader.reader.prefix='/api/v1/projects/P'
        page={'projectCode':'P','applicationRevisionId':application,'total':1,'items':[{'entityUid':'unit7','adoptionId':application}],
            'snapshotRevision':'adopters:1','nextOffset':None}
        self.reader.reader._request=Mock(return_value=page)
        captured=configuration_references(self.library,'version','P',self.reader.reader)
        self.assertEqual(captured[0]['equipmentEntityUids'],['unit7'])
        rows,truncated=shared_configuration_bindings(self.reader,self.library,entity_uid='definition-cabinet',equipment_uid='unit7')
        self.assertFalse(truncated);self.assertEqual(rows[0]['equipmentEntityUid'],'unit7')
        self.assertEqual(rows[0]['componentKeys'],['cabinet-key'])
        self.reader.reader._request.return_value=page|{'total':0,'items':[],'snapshotRevision':'adopters:2'}
        self.assertEqual(shared_configuration_bindings(self.reader,self.library),([],False))
        self.assertEqual(frozen_configuration_bindings(self.reader,self.library,'version',captured)[0]['equipmentEntityUid'],'unit7')

    def test_source_adopter_capture_pages_and_rejects_changed_or_oversized_sets(self):
        from apps.api.equipment_reader import EquipmentReader
        application='00000000-0000-4000-8000-000000000001'
        page={'projectCode':'P','applicationRevisionId':application,'total':101,'items':[
            {'entityUid':'unit'+str(n),'adoptionId':application} for n in range(100)],'snapshotRevision':'adopters:1','nextOffset':100}
        source=SimpleNamespace(prefix='/api/v1/projects/P',project_code='P',_request=Mock(side_effect=[page,
            page|{'items':[{'entityUid':'unit100','adoptionId':application}],'nextOffset':None}]))
        self.assertEqual(len(EquipmentReader(source).application_equipment(application)),101)
        self.assertIn('expectedSnapshotRevision=adopters%3A1',source._request.call_args.args[1])
        source._request=Mock(side_effect=[page,page|{'snapshotRevision':'adopters:2','items':[],'nextOffset':None}])
        with self.assertRaisesRegex(PreviewError,'SNAPSHOT_CHANGED'):EquipmentReader(source).application_equipment(application)
        source._request=Mock(return_value=page|{'total':501})
        with self.assertRaisesRegex(PreviewError,'ANALYSIS_SOURCE_LIMIT'):EquipmentReader(source).application_equipment(application)
        self.assertEqual(source._request.call_count,1)

    def test_non_demo_project_uses_exact_binding_before_a_same_named_candidate(self):
        self.model(asset='candidate', version='candidate-v', name='A name-only model')
        self.model(asset='bound', version='version', name='Z bound model', components=[{'componentKey': 'cabinet-key', 'displayName': 'Different label'}])
        self.scene()
        with patch('apps.api.simulated_faults.catalogue', side_effect=AssertionError('No simulation profile needed')):
            rows = self.recommended()['items']
        self.assertEqual([row['matchType'] for row in rows], ['binding', 'name_candidate'])
        self.assertEqual(rows[0]['selector']['modelVersionId'], 'version')
        self.reader.models.listing.assert_not_called()
        self.reader.reader.context_for_object.assert_called_once_with('definition-cabinet', 'r1')

    def test_saved_binding_keeps_its_old_model_version(self):
        self.model(version='version', date='1'); self.model(version='new-version', date='2', components=[]); self.scene()
        rows = self.recommended()['items']; self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['selector']['modelVersionId'], rows[0]['matchType']), ('version', 'binding'))

    def test_recycled_binding_is_history_and_restoring_scene_restores_source_semantics(self):
        self.model(); self.scene(state='deleted')
        self.assertEqual(self.recommended()['items'][0]['matchType'], 'historical_binding')
        link = self.linked()['items'][0]
        self.assertEqual((link['kind'], link['origin'], link['anchor']['referenceKind']), ('model_binding_history', 'candidate', 'historical_binding'))
        self.db.execute("update scene_lifecycle set state='active'")
        self.assertEqual(self.recommended()['items'][0]['matchType'], 'binding')
        self.assertEqual(self.linked()['items'][0]['origin'], 'source')

    def test_same_name_different_identity_is_candidate_with_an_explanation(self):
        self.model(); self.scene(uid='different-installed-cabinet', state='deleted')
        self.assertEqual(self.recommended()['items'][0]['matchType'], 'name_candidate')
        value = self.linked(); link = value['items'][0]
        self.assertEqual((link['kind'], link['origin']), ('model_name_candidate', 'candidate'))
        self.assertEqual(link['anchor']['componentKeys'], ['cabinet-key'])
        self.assertIn('MODEL_BOUND_TO_DIFFERENT_OBJECT', [row['reason'] for row in value['gaps']])
        self.assertFalse(any(row['kind'] == 'model_binding' for row in value['items']))

    def test_cross_scope_blocking_and_missing_component_never_become_a_binding(self):
        self.model(); self.scene(project='OTHER', name='wrong-project'); self.scene(connection='OTHER', name='wrong-source')
        self.scene(blocking=True, name='blocked'); self.scene(key='missing-key', name='removed-component')
        self.assertEqual(self.recommended()['items'][0]['matchType'], 'name_candidate')
        self.assertTrue(all(row['origin'] == 'candidate' for row in self.linked()['items']))

    def test_root_binding_is_a_whole_model_relationship(self):
        self.model(components=[]); self.components = []; self.scene(whole=True)
        self.assertEqual(self.recommended()['items'][0]['matchType'], 'binding')
        link = self.linked()['items'][0]
        self.assertEqual((link['label'], link['anchor']['componentKeys']), ('模型整体绑定', []))

    def test_candidates_are_bounded_paged_and_deleted_assets_are_excluded(self):
        for n in range(15): self.model(asset=f'a{n:02}', version=f'v{n:02}', name=f'Model {n:02}')
        self.model(asset='deleted', version='deleted-v', deleted=True)
        first = self.recommended(); second = self.recommended(offset=first['nextOffset'])
        self.assertEqual((len(first['items']), len(second['items']), second['nextOffset']), (12, 3, None))
        self.assertEqual(len({row['key'] for row in first['items']+second['items']}), 15)

    def test_default_manual_model_category_does_not_load_the_whole_catalogue(self):
        value = recommendations(self.reader, {'entry': {'projectOnly': True}, 'section': 'models'}, self.library)
        self.assertEqual(value['items'], []); self.assertTrue(value['gaps']); self.reader.models.listing.assert_not_called()
        for query in (None, ['invalid']):
            with self.assertRaises(PreviewError): self.recommended(q=query)


class AlarmObjectMappingTests(TestCase):
    def value(self, *, duplicate=False, **identifier_changes):
        identifier = {'value': '=PLANT+CB7-B1', 'scheme': 'RDS', 'status': 'accepted', 'role': 'primary', 'scopeType': 'project', 'scopeKey': 'P', **identifier_changes}
        obj = {'item': {'identifiers': [identifier]}}
        reader = SimpleNamespace(reader=SimpleNamespace(project_code='P'), authorize=Mock(), read=Mock(side_effect=lambda kind, _: {'dataset': {'sourceKind': 'simulated', 'primaryRds': '=PLANT+CB7-B1'}} if kind == 'alarm' else obj))
        fixed = [({'evidenceRefId': 'alarm', 'sourceKind': 'alarm'}, {}), ({'evidenceRefId': 'object', 'sourceKind': 'object'}, {'entityUid': 'one'})]
        if duplicate: fixed.append(({'evidenceRefId': 'other', 'sourceKind': 'object'}, {'entityUid': 'two'}))
        value = relationships(reader, fixed, None)
        self.assertEqual(reader.read.call_count, len(fixed))
        return value

    def test_explicit_project_identifier_links_a_simulated_alarm_without_extra_source_reads(self):
        row = self.value()['items'][0]
        self.assertEqual((row['fromRef'], row['toRef'], row['kind'], row['label']), ('alarm', 'object', 'alarm_object_mapping', '模拟报警对象'))
        self.assertEqual(self.value(status='needs_review')['items'][0]['origin'], 'source')

    def test_alias_wrong_scope_status_and_ambiguous_identity_do_not_infer_an_alarm_target(self):
        for change in ({'role': 'alias'}, {'scopeType': 'installation'}, {'scopeKey': 'OTHER'}, {'status': 'rejected'}, {'value': 'same display name'}):
            self.assertEqual(self.value(**change)['items'], [])
        result = self.value(duplicate=True)
        self.assertEqual(result['items'], []); self.assertEqual(result['gaps'][0]['reason'], 'ALARM_OBJECT_MAPPING_AMBIGUOUS')
