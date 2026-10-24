"""Visual settings share real revision, authority and trusted GIS boundaries."""
import copy
import json
from pathlib import Path
import unittest
from uuid import uuid4
from apps.api.authority import PreviewError
from apps.api.scene_environment import validate_environment, environment_write
from apps.api.scene_geometry import geometry_check, GeometryError
from tests import test_scene_library as library_fixture, test_scene_geometry as geometry_fixture, test_scene_http as http_fixture, test_scene_replacement as replacement_fixture


def environment():
    return json.loads((Path(__file__).parent/'fixtures/scene-environment-v1.json').read_text())


class EnvironmentTests(unittest.TestCase):
    def test_surroundings_optional_strict_and_not_inserted_into_old_environment(self):
        old = {'environment': environment()}
        before = copy.deepcopy(old)
        validate_environment(old)
        self.assertEqual(old, before)
        for profile in ('land', 'offshore'):
            for mode in ('auto', 'off'):
                value = copy.deepcopy(old)
                value['environment']['surroundings'] = {'mode': mode, 'profile': profile}
                validate_environment(value)
        for setting in (None, 'auto', {'mode': True, 'profile': 'land'},
                        {'mode': 'auto', 'profile': 'earth'}, {'mode': 'other', 'profile': 'land'},
                        {'mode': 'auto', 'profile': 'land', 'url': 'https://example.com/terrain'},
                        {'mode': 'auto'}):
            with self.subTest(setting=setting), self.assertRaises(PreviewError):
                validate_environment({'environment': {**environment(), 'surroundings': setting}})

    def test_old_writer_cannot_omit_surroundings_but_explicit_off_and_legacy_are_supported(self):
        old = {'environment': {**environment(), 'surroundings': {'mode': 'auto', 'profile': 'land'}}}
        with self.assertRaises(PreviewError) as caught:
            environment_write({'environmentWriteVersion': 1, 'snapshot': {'environment': environment()}}, old)
        self.assertEqual(caught.exception.code, 'SURROUNDING_BACKGROUND_FIELD_REQUIRED')
        for value in (None, {**environment(), 'surroundings': {'mode': 'off', 'profile': 'land'}}):
            environment_write({'environmentWriteVersion': 1, 'snapshot': {'environment': value}}, old)

    def test_surroundings_http_roundtrip_preserves_geometry_history_permission_and_replay(self):
        f = http_fixture.SceneHttpTests('test_real_http_create_save_open_and_fixed_old_revision')
        f.setUp(); self.addCleanup(f.doCleanups)
        scene = f.create(); request = f.save_body(scene, [f.item()])
        status, initial, _ = f.save(request); self.assertEqual(status, 200, initial)
        old = copy.deepcopy(f.open(initial)[1]['snapshot'])
        request = f.save_body(f.open(initial)[1]); request['snapshot']['environment'] = {**environment(), 'surroundings': {'mode': 'auto', 'profile': 'land'}}
        request['environmentWriteVersion'] = 1
        status, saved, _ = f.save(request); self.assertEqual(status, 200, saved)
        self.assertEqual(f.save(request)[1]['sceneRevision'], saved['sceneRevision'])
        opened = f.open(saved)[1]
        self.assertEqual(opened['capabilities']['surroundingBackgroundModes'], ['auto', 'off'])
        self.assertEqual(opened['snapshot']['environment'], request['snapshot']['environment'])
        for key in ('coordinateFrame', 'terrain', 'imagery', 'instances', 'initialView'):
            self.assertEqual(opened['snapshot'].get(key), old.get(key))
        self.assertEqual(f.open(initial, initial['sceneRevision'])[1]['snapshot'], old)
        member = f.login('fixture-bg-reader'); f.account(member).role = 'reader'
        denied = f.save_body(opened); denied['environmentWriteVersion'] = 1
        denied['snapshot']['environment']['surroundings']['mode'] = 'off'
        f.assert_response(f.save(denied, client=member), 403, 'SCENE_WRITE_FORBIDDEN')
        self.assertEqual(f.open(saved)[1]['sceneRevision'], saved['sceneRevision'])
        stale = f.save_body(opened); stale['environmentWriteVersion'] = 1
        del stale['snapshot']['environment']['surroundings']
        f.assert_response(f.save(stale), 409, 'SURROUNDING_BACKGROUND_FIELD_REQUIRED')

    def test_surroundings_do_not_extend_ground_coverage_or_change_terrain_sampling(self):
        f = self.geometry(); f.resource()
        snapshot = f.preview()['snapshot']; original = copy.deepcopy(snapshot)
        snapshot['environment'] = {**environment(), 'surroundings': {'mode': 'auto', 'profile': 'land'}}
        checked = geometry_check(snapshot, f.terrains)['snapshot']
        for key in ('coordinateFrame', 'terrain', 'instances'):
            self.assertEqual(checked[key], original[key])
        for profile in ('land', 'offshore'):
            outside = copy.deepcopy(snapshot); outside['environment']['surroundings']['profile'] = profile
            position = outside['instances'][0]['placement']['position']; position['longitude'] += .02
            outside['instances'][0]['placement']['height']['sampleLongitude'] = position['longitude']
            with self.assertRaises(GeometryError) as caught:
                geometry_check(outside, f.terrains)
            self.assertEqual(caught.exception.code, 'OUTSIDE_COVERAGE')

    def test_actual_http_environment_write_guard_permissions_and_old_history(self):
        f=http_fixture.SceneHttpTests('test_real_http_create_save_open_and_fixed_old_revision');f.setUp();self.addCleanup(f.doCleanups)
        scene=f.create();request=f.save_body(scene,[f.item()]);request['snapshot']['environment']=environment()
        self.assertEqual(f.request('/api/workbench/scenes')[1]['capabilities']['environmentSchemaVersions'],[1])
        f.assert_response(f.save(request),409,'ENVIRONMENT_WRITE_VERSION_REQUIRED')
        request['environmentWriteVersion']=1;status,saved,_=f.save(request);self.assertEqual(status,200,saved)
        opened=f.open(scene)[1];self.assertEqual(opened['snapshot']['environment'],environment())
        self.assertNotIn('environment',f.open(scene,scene['sceneRevision'])[1]['snapshot'])
        check={'kind':'validate','sceneId':scene['sceneId'],'expectedSceneRevision':saved['sceneRevision'],'snapshot':opened['snapshot']}
        f.assert_response(f.request('/api/workbench/scenes/check',check),409,'ENVIRONMENT_WRITE_VERSION_REQUIRED')
        check['environmentWriteVersion']=1;self.assertEqual(f.request('/api/workbench/scenes/check',check)[0],200)
        replacement={'kind':'model','sceneId':scene['sceneId'],'expectedSceneRevision':saved['sceneRevision'],
          'snapshot':opened['snapshot'],'sceneModelInstanceId':request['snapshot']['instances'][0]['sceneModelInstanceId'],
          'candidateModelVersionId':f.version['versionId']}
        f.assert_response(f.request('/api/workbench/scenes/replacement-check',replacement),409,'ENVIRONMENT_WRITE_VERSION_REQUIRED')
        member=f.login('fixture-reader');f.account(member).role='reader'
        f.assert_response(f.save(f.save_body(opened),client=member),403,'SCENE_WRITE_FORBIDDEN')
        stale=f.save_body(scene);stale['environmentWriteVersion']=1;stale['snapshot']['environment']=None
        f.assert_response(f.save(stale),409,'SCENE_CHANGED')
        self.assertEqual(f.open(scene)[1]['sceneRevision'],saved['sceneRevision'])

    def library(self):
        f=library_fixture.SceneLibraryTests('test_invalid_organization_does_not_create_partial_revision_or_audit');f.setUp();self.addCleanup(f.doCleanups);return f

    def geometry(self):
        f=geometry_fixture.SceneGeometryTests('test_local_placements_do_not_require_gis_or_claim_geography');f.setUp();self.addCleanup(f.doCleanups);return f

    def test_old_snapshot_roundtrip_adoption_replay_reset_and_old_writer_rejection(self):
        f=self.library();scene=f.create();body=f.body(scene,[f.item()]);before=copy.deepcopy(body['snapshot'])
        old=f.save(body);self.assertNotIn('environment',f.opened(scene)['snapshot'])
        opened=f.opened(scene);request=f.body(opened);request['snapshot']['environment']=environment()
        counts=f.counts()
        f.expect('ENVIRONMENT_WRITE_VERSION_REQUIRED',lambda:f.save(request));self.assertEqual(f.counts(),counts)
        request['environmentWriteVersion']=1;saved=f.save(request);self.assertEqual(f.save(request)['sceneRevision'],saved['sceneRevision'])
        self.assertEqual(f.opened(scene)['snapshot']['environment'],environment())
        self.assertNotIn('environment',f.opened(scene,old['sceneRevision'])['snapshot'])
        self.assertEqual(f.opened(scene)['snapshot']['instances'],before['instances'])
        opened=f.opened(scene);reset=f.body(opened);reset['snapshot'].pop('environment')
        f.expect('ENVIRONMENT_WRITE_VERSION_REQUIRED',lambda:f.save(reset))
        reset['environmentWriteVersion']=1;f.expect('ENVIRONMENT_FIELD_REQUIRED',lambda:f.save(reset))
        reset['snapshot']['environment']=None;f.save(reset)
        self.assertIn('environment',f.opened(scene)['snapshot']);self.assertIsNone(f.opened(scene)['snapshot']['environment'])
        self.assertEqual(f.opened(scene,old['sceneRevision'])['snapshot'],before)

    def test_strict_numeric_fields_modes_and_unknown_programs_rejected(self):
        good={'environment':environment()};validate_environment(good)
        mutations=[('color','exposure',True),('color','exposure',float('nan')),('color','exposure',10**1000),('color','exposure',3),
          ('lighting','hemisphereIntensity',float('inf')),('surface','textureSet','https://example.com/map.hdr'),
          ('water','amplitudeM',1),('water','seed',False),('water','travelHeadingDeg',360),('water','roughness',0),
          ('water','reflection','planar'),('shadows','quality','unbounded')]
        for section,key,value in mutations:
            bad=copy.deepcopy(good);bad['environment'][section][key]=value
            with self.subTest(section=section,key=key,value=value):
                with self.assertRaises(PreviewError):validate_environment(bad)
        for section in ['color','lighting','atmosphere','shadows','surface','water','animation']:
            bad=copy.deepcopy(good);bad['environment'][section]['shader']='alert(1)'
            with self.assertRaises(PreviewError):validate_environment(bad)
        bad=copy.deepcopy(good);bad['environment']['schemaVersion']=2
        with self.assertRaises(PreviewError) as caught:validate_environment(bad)
        self.assertEqual(caught.exception.code,'UNSUPPORTED_SCENE_ENVIRONMENT')
        bad=copy.deepcopy(good);bad['environment']['atmosphere']['fog']['farM']=1
        with self.assertRaises(PreviewError):validate_environment(bad)
        bad=copy.deepcopy(good);bad['environment']['water']['enabled']=True;bad['coordinateFrame']=[]
        with self.assertRaises(PreviewError):validate_environment(bad)

    def test_authorization_and_conflict_leave_settings_and_scene_history_unchanged(self):
        f=self.library();scene=f.create();body=f.body(scene);body.update(environmentWriteVersion=1);body['snapshot']['environment']=environment();counts=f.counts()
        f.allowed=False;f.expect('SCENE_WRITE_FORBIDDEN',lambda:f.save(body));self.assertEqual(f.counts(),counts)
        f.allowed=True;f.save(body);body['clientRequestId']=str(uuid4());f.expect('SCENE_CHANGED',lambda:f.save(body))
        request=f.body(f.opened(scene));request['environmentWriteVersion']=True
        f.expect('ENVIRONMENT_WRITE_VERSION_REQUIRED',lambda:f.save(request))

    def test_geometry_anchor_preserves_static_environment_and_actual_flat_water(self):
        f=self.geometry();f.snapshot['environment']=environment();local_before=copy.deepcopy(f.snapshot)
        self.assertEqual(geometry_check(f.snapshot,{})['snapshot'],local_before)
        f.resource(datum='UNKNOWN_RELATIVE',relative_reference='synthetic-plane')
        snapshot=f.preview()['snapshot'];self.assertEqual(snapshot['environment'],local_before['environment'])
        snapshot['environment']['water']['enabled']=True
        before=copy.deepcopy(snapshot)
        self.assertEqual(geometry_check(snapshot,f.terrains)['snapshot'],before)
        snapshot['environment']=None;self.assertIn('environment',geometry_check(snapshot,f.terrains)['snapshot'])

    def test_water_rejects_local_known_datum_and_uneven_relative_surface(self):
        f=self.geometry();f.snapshot['environment']=environment();f.snapshot['environment']['water']['enabled']=True
        with self.assertRaises(GeometryError) as caught:geometry_check(f.snapshot,{})
        self.assertEqual(caught.exception.code,'WATER_SURFACE_NOT_SUPPORTED')
        f.snapshot['environment']['water']['enabled']=False
        f.resource(datum='UNKNOWN_RELATIVE',relative_reference='synthetic-slope',values=[[100+i/32 for i in range(32)] for _ in range(32)])
        snapshot=f.preview()['snapshot'];snapshot['environment']['water']['enabled']=True
        with self.assertRaises(GeometryError) as caught:geometry_check(snapshot,f.terrains)
        self.assertEqual(caught.exception.code,'WATER_SURFACE_NOT_SUPPORTED')
        snapshot['coordinateFrame']['verticalDatum']='EGM2008'
        with self.assertRaises(PreviewError):validate_environment(snapshot)

    def test_old_writer_cannot_drop_environment_in_check_or_replacement(self):
        for previous in [{'environment':None},{'environment':environment()}]:
            with self.assertRaises(PreviewError):environment_write({'snapshot':{}},previous)
            with self.assertRaises(PreviewError):environment_write({'snapshot':{},'environmentWriteVersion':1},previous)
            environment_write({'snapshot':{'environment':None},'environmentWriteVersion':1},previous)

    def test_model_and_terrain_replacement_keep_adopted_environment_and_old_revision(self):
        for kind in ('model','terrain'):
            f=replacement_fixture.SceneReplacementTests('test_replacement_preserves_camera_targets_and_metadata_as_repairable_history');f.setUp();self.addCleanup(f.doCleanups)
            scene=f.geographic();body=f.f.body(scene);body['snapshot']['environment']=environment();body['environmentWriteVersion']=1;f.save(body);scene=f.f.opened(scene)
            request=f.check_body(scene,kind);request['environmentWriteVersion']=1;checked=f.check(request)
            self.assertEqual(checked['proposedSnapshot']['environment'],environment())
            save=f.request(scene,checked);save['environmentWriteVersion']=1;saved=f.save(save)
            self.assertEqual(f.f.opened(saved)['snapshot']['environment'],environment())
            self.assertEqual(f.f.opened(scene,scene['sceneRevision'])['snapshot']['environment'],environment())


# Fixture classes are helpers, not a second run of their test suites.
