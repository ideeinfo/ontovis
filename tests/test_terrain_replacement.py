"""Real synthetic GIS tests for fixed-version terrain replacement previews."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

import numpy as np
from rasterio.warp import transform

from apps.api.scene_geometry import (GeometryError, TrustedTerrain, anchor_preview,
    geometry_check, terrain_replacement_preview)
from tests import test_scene_geometry as geometry_fixtures


class TerrainReplacementTests(unittest.TestCase):
    def setUp(self):
        self.fixture=geometry_fixtures.SceneGeometryTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.terrains={}

    def resource(self,values=None,datum='EGM2008',reference=None):
        self.fixture.version=str(uuid4())
        value=self.fixture.resource(values,datum,reference)
        self.terrains[value.version_id]=value
        return value

    def anchored(self,*,datum='EGM2008',reference=None,values=None):
        self.old=self.resource(values,datum,reference)
        result=anchor_preview(self.fixture.snapshot,self.old.version_id,self.fixture.anchor,self.terrains)
        self.snapshot=result['snapshot']
        return self.snapshot

    def preview(self,new,strategy='resample_ground',snapshot=None):
        return terrain_replacement_preview(self.snapshot if snapshot is None else snapshot,
                                            new.version_id,strategy,self.terrains)

    def expect(self,code,call):
        with self.assertRaises(GeometryError) as caught:call()
        self.assertEqual(caught.exception.code,code)

    def manifest(self):
        return [{'terrainVersionId':value.version_id,'contentRevision':value.content_revision,
                 'sha256':value.sha256,'reportSha256':value.report_sha256}
                for value in self.terrains.values()]

    def cli(self,request):
        path=self.fixture.root/'replacement-request.json'
        path.write_text(json.dumps(request),encoding='utf-8')
        result=subprocess.run([sys.executable,'-m','apps.api.scene_geometry',str(path),
                               '--terrain-root',str(self.fixture.root)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.stderr,'')
        return result.returncode,json.loads(result.stdout)

    def test_resample_changes_only_ground_height_and_frame_encoding(self):
        self.anchored();before=copy.deepcopy(self.snapshot)
        second=copy.deepcopy(self.snapshot['instances'][0]);second['sceneModelInstanceId']=str(uuid4())
        second['displayName']='指定高程设备';second['placement']['height']={
            'mode':'absolute','valueM':123,'verticalDatum':'EGM2008','sourceNote':'Synthetic declared height'}
        self.snapshot['instances'].append(second);before=copy.deepcopy(self.snapshot)
        new=self.resource(np.full((32,32),110,dtype='float32'))
        result=self.preview(new);value=result['snapshot'];old_frame=before['coordinateFrame'];frame=value['coordinateFrame']
        self.assertNotEqual(frame['frameRevision'],old_frame['frameRevision'])
        for key in ('horizontalCrs','verticalDatum','transformId','originEasting','originNorthing','originHeight','convergenceRuleId'):
            self.assertEqual(frame[key],old_frame[key])
        self.assertEqual(value['initialView'],before['initialView'])
        for old,item in zip(before['instances'],value['instances']):
            self.assertEqual(item['placement']['headingDeg'],old['placement']['headingDeg'])
            for key in ('longitude','latitude','transformId'):
                self.assertEqual(item['placement']['position'][key],old['placement']['position'][key])
            self.assertEqual(item['placement']['position']['frameRevision'],frame['frameRevision'])
            for key in ('sceneModelInstanceId','modelVersionId','displayName','visible','positionLocked','rootBinding','componentBindings'):
                self.assertEqual(item[key],old[key])
        ground=value['instances'][0]['placement']['height']
        self.assertEqual((ground['terrainVersionId'],ground['sampledHeightM'],ground['offsetM']),(new.version_id,110,5))
        self.assertEqual(value['instances'][1]['placement']['height'],second['placement']['height'])
        changes=result['impact']['instances']
        self.assertEqual(changes[0]['sampledHeightDeltaM'],10)
        self.assertEqual(changes[0]['heightDeltaM'],10)
        self.assertEqual(changes[1]['heightDeltaM'],0)
        self.assertEqual(result['resourceRefs']['terrains'],[result['impact']['newTerrainRef']])
        self.assertEqual(result['impact']['oldTerrainRef']['reportSha256'],self.old.report_sha256)
        self.assertEqual(result['impact']['sampleIssues'],[])
        self.assertEqual(geometry_check(value,self.terrains)['snapshot'],value)
        self.assertEqual(self.snapshot,before)

    def test_keep_height_known_becomes_absolute_and_retains_estimate_source(self):
        self.anchored();before=copy.deepcopy(self.snapshot)
        new=self.resource(np.full((32,32),125,dtype='float32'))
        result=self.preview(new,'keep_height');height=result['snapshot']['instances'][0]['placement']['height']
        self.assertEqual(height['mode'],'absolute');self.assertEqual(height['valueM'],105)
        self.assertIn(self.old.version_id,height['sourceNote']);self.assertIn('not a surveyed',height['sourceNote'])
        note=result['heightProvenance'][0]
        self.assertEqual(note['kind'],'terrain_estimate_preserved_as_absolute')
        self.assertEqual(note['previousHeight']['sampledHeightM'],100)
        self.assertEqual(note['previousHeight']['offsetM'],5)
        self.assertEqual(note['previousTerrainRef']['sha256'],self.old.sha256)
        self.assertEqual(note['previousAnchorHeight'],before['coordinateFrame']['anchor']['anchorHeight'])
        self.assertEqual(result['impact']['instances'][0]['heightDeltaM'],0)
        self.assertEqual(result['impact']['instances'][0]['sampledHeightDeltaM'],25)
        self.assertEqual(result['snapshot']['coordinateFrame']['anchor']['anchorHeight']['valueM'],102)
        self.assertEqual(self.snapshot,before)

    def test_keep_height_unknown_uses_same_reference_new_offset_and_origin(self):
        self.anchored(datum='UNKNOWN_RELATIVE',reference='synthetic-relative-A')
        new=self.resource(np.full((32,32),112,dtype='float32'),'UNKNOWN_RELATIVE','synthetic-relative-A')
        result=self.preview(new,'keep_height');value=result['snapshot'];height=value['instances'][0]['placement']['height']
        self.assertEqual(height['mode'],'terrain_ground');self.assertEqual(height['terrainVersionId'],new.version_id)
        self.assertEqual(height['sampledHeightM'],112);self.assertEqual(height['offsetM'],-7)
        self.assertEqual(value['coordinateFrame']['originHeight'],102)
        self.assertEqual(value['coordinateFrame']['anchor']['anchorHeight']['offsetM'],-10)
        self.assertEqual(value['coordinateFrame']['relativeReferenceId'],'synthetic-relative-A')
        self.assertEqual(result['heightProvenance'][0]['relativeReferenceId'],'synthetic-relative-A')
        self.assertEqual(result['displayPlacements'][0]['heightM'],105)
        self.assertEqual(result['displayPlacements'][0]['position'][1],3)
        self.assertEqual(geometry_check(value,self.terrains)['snapshot'],value)

    def test_resample_unknown_preserves_reference_without_creating_absolute(self):
        self.anchored(datum='UNKNOWN_RELATIVE',reference='synthetic-relative-A')
        new=self.resource(np.full((32,32),112,dtype='float32'),'UNKNOWN_RELATIVE','synthetic-relative-A')
        result=self.preview(new)
        self.assertEqual(result['snapshot']['instances'][0]['placement']['height']['mode'],'terrain_ground')
        self.assertEqual(result['displayPlacements'][0]['heightM'],117)
        self.assertEqual(result['snapshot']['coordinateFrame']['originHeight'],102)

    def test_different_vertical_datum_is_never_implicitly_converted(self):
        self.anchored();new=self.resource(datum='WGS84_ELLIPSOIDAL')
        for strategy in ('keep_height','resample_ground'):
            self.expect('VERTICAL_DATUM_CONFLICT',lambda:self.preview(new,strategy))

    def test_different_unknown_references_are_rejected(self):
        self.anchored(datum='UNKNOWN_RELATIVE',reference='synthetic-relative-A')
        new=self.resource(datum='UNKNOWN_RELATIVE',reference='synthetic-relative-B')
        for strategy in ('keep_height','resample_ground'):
            self.expect('VERTICAL_DATUM_CONFLICT',lambda:self.preview(new,strategy))

    def test_required_new_ground_nodata_rejects_entire_preview(self):
        self.anchored();before=copy.deepcopy(self.snapshot)
        values=np.full((32,32),110,dtype='float32');values[14:18,14:18]=-9999
        new=self.resource(values)
        self.expect('NO_DATA',lambda:self.preview(new));self.assertEqual(self.snapshot,before)

    def test_required_new_ground_outside_coverage_rejects_entire_preview(self):
        self.anchored();new=self.resource(np.full((8,8),110,dtype='float32'))
        self.expect('OUTSIDE_COVERAGE',lambda:self.preview(new))

    def test_known_keep_height_does_not_require_new_coverage(self):
        self.anchored();new=self.resource(np.full((8,8),110,dtype='float32'))
        result=self.preview(new,'keep_height');impact=result['impact']
        self.assertEqual(result['snapshot']['instances'][0]['placement']['height']['mode'],'absolute')
        self.assertIsNone(impact['instances'][0]['newSampledHeightM'])
        self.assertIsNone(impact['instances'][0]['sampledHeightDeltaM'])
        self.assertEqual(impact['sampleIssues'],[{'sceneModelInstanceId':self.fixture.instance,
            'terrainVersionId':new.version_id,'role':'new','code':'OUTSIDE_COVERAGE'}])

    def test_known_keep_height_reports_nodata_without_blocking_absolute(self):
        self.anchored();values=np.full((32,32),110,dtype='float32');values[14:18,14:18]=-9999
        result=self.preview(self.resource(values),'keep_height')
        self.assertEqual(result['impact']['sampleIssues'][0]['code'],'NO_DATA')
        self.assertIsNone(result['impact']['instances'][0]['newSampledHeightM'])
        self.assertEqual(result['displayPlacements'][0]['heightM'],105)

    def test_absolute_outside_both_coverages_is_unchanged_and_diagnostic_only(self):
        self.anchored();placement=self.snapshot['instances'][0]['placement']
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[503000],[3699840])
        placement['position']['longitude']=longitude[0];placement['position']['latitude']=latitude[0]
        placement['height']={'mode':'absolute','valueM':124,'verticalDatum':'EGM2008','sourceNote':'Synthetic specified height'}
        height=copy.deepcopy(placement['height']);new=self.resource(np.full((32,32),110,dtype='float32'))
        for strategy in ('keep_height','resample_ground'):
            result=self.preview(new,strategy);impact=result['impact']
            self.assertEqual(result['snapshot']['instances'][0]['placement']['height'],height)
            self.assertIsNone(impact['instances'][0]['oldSampledHeightM'])
            self.assertIsNone(impact['instances'][0]['newSampledHeightM'])
            self.assertEqual([issue['role'] for issue in impact['sampleIssues']],['old','new'])
            self.assertEqual(impact['instances'][0]['heightDeltaM'],0)

    def test_unknown_keep_height_requires_valid_new_anchor_sample(self):
        self.anchored(datum='UNKNOWN_RELATIVE',reference='synthetic-relative-A')
        new=self.resource(np.full((8,8),110,dtype='float32'),'UNKNOWN_RELATIVE','synthetic-relative-A')
        self.expect('OUTSIDE_COVERAGE',lambda:self.preview(new,'keep_height'))

    def test_unknown_keep_height_rejects_missing_instance_even_with_valid_anchor(self):
        self.old=self.resource(datum='UNKNOWN_RELATIVE',reference='synthetic-relative-A')
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[500080],[3699920])
        self.fixture.anchor['geographicAnchor']=[longitude[0],latitude[0]]
        self.fixture.anchor['trueNorthHeadingDeg']=0
        self.fixture.snapshot['instances'][0]['placement']['position'].update(xM=80,zM=80)
        self.snapshot=anchor_preview(self.fixture.snapshot,self.old.version_id,self.fixture.anchor,self.terrains)['snapshot']
        values=np.full((32,32),110,dtype='float32');values[14:18,14:18]=-9999
        new=self.resource(values,'UNKNOWN_RELATIVE','synthetic-relative-A')
        self.expect('NO_DATA',lambda:self.preview(new,'keep_height'))

    def test_locked_actual_height_change_is_blocked_but_encoding_only_is_allowed(self):
        self.anchored();self.snapshot['instances'][0]['positionLocked']=True
        new=self.resource(np.full((32,32),110,dtype='float32'))
        self.expect('INSTANCE_POSITION_LOCKED',lambda:self.preview(new))
        result=self.preview(new,'keep_height')
        self.assertTrue(result['snapshot']['instances'][0]['positionLocked'])
        self.assertEqual(result['impact']['instances'][0]['heightDeltaM'],0)

    def test_strict_old_sample_is_checked_before_candidate_derivation(self):
        self.anchored();new=self.resource();self.snapshot['instances'][0]['placement']['height']['sampledHeightM']+=.01
        (new.directory/'positions.f32').write_bytes(b'changed')
        self.expect('TERRAIN_SAMPLE_CHANGED',lambda:self.preview(new))

    def test_fixed_candidate_artifact_and_report_hash_are_rechecked(self):
        self.anchored();new=self.resource();path=new.directory/'positions.f32';original=path.read_bytes()
        path.write_bytes(bytes(len(original)))
        self.expect('RESOURCE_CHANGED',lambda:self.preview(new))
        path.write_bytes(original)
        self.terrains[new.version_id]=TrustedTerrain(new.version_id,new.content_revision,new.sha256,'f'*64,new.directory)
        self.expect('RESOURCE_CHANGED',lambda:self.preview(new))

    def test_replacement_rejects_local_same_version_wrong_strategy_and_extra_manifest(self):
        self.old=self.resource();self.snapshot=self.fixture.snapshot
        new=self.resource()
        self.expect('SCENE_SCOPE_UNSUPPORTED',lambda:self.preview(new))
        self.snapshot=anchor_preview(self.fixture.snapshot,self.old.version_id,{
            **self.fixture.anchor,'anchorHeight':{'mode':'terrain_ground','terrainVersionId':self.old.version_id,'offsetM':2}},self.terrains)['snapshot']
        self.expect('INVALID_REQUEST',lambda:self.preview(self.old))
        self.expect('INVALID_REQUEST',lambda:self.preview(new,'automatic'))
        extra=self.resource()
        self.expect('INVALID_REQUEST',lambda:self.preview(new))
        self.terrains.pop(extra.version_id)
        self.terrains.pop(self.old.version_id)
        self.expect('NOT_FOUND_OR_FORBIDDEN',lambda:self.preview(new))

    def test_cli_real_two_terrain_chain_and_exact_request_shape(self):
        self.anchored();new=self.resource(np.full((32,32),110,dtype='float32'))
        request={'kind':'terrain_replacement','snapshot':self.snapshot,'trustedTerrains':self.manifest(),
                 'candidateTerrainVersionId':new.version_id,'strategy':'resample_ground'}
        code,value=self.cli(request)
        self.assertEqual(code,0);self.assertEqual(value,self.preview(new))
        for extra in ({'anchor':{}},{'expectedFrame':self.snapshot['coordinateFrame']},{'resampleGround':True}):
            code,value=self.cli({**request,**extra})
            self.assertEqual((code,value),(2,{'code':'INVALID_REQUEST'}))
        duplicate=copy.deepcopy(request);duplicate['trustedTerrains'][1]=duplicate['trustedTerrains'][0]
        self.assertEqual(self.cli(duplicate),(2,{'code':'INVALID_REQUEST'}))

    def test_new_integral_anchor_height_survives_browser_number_roundtrip(self):
        self.anchored();new=self.resource(np.full((32,32),105,dtype='float32'))
        result=self.preview(new,'keep_height');value=result['snapshot']
        def browser_number(item):
            if type(item) is float and item.is_integer():return int(item)
            if type(item) is dict:return {key:browser_number(child) for key,child in item.items()}
            if type(item) is list:return [browser_number(child) for child in item]
            return item
        browser=browser_number(value)
        self.assertIs(type(value['coordinateFrame']['anchor']['anchorHeight']['valueM']),int)
        checked=geometry_check(browser,self.terrains,expected_frame=value['coordinateFrame'])
        self.assertEqual(checked['snapshot']['coordinateFrame']['frameRevision'],value['coordinateFrame']['frameRevision'])
        self.assertEqual(checked['snapshot'],value)

    def test_unknown_decimal_origin_survives_replacement_reopen_and_browser_roundtrip(self):
        self.old=self.resource(np.zeros((32,32),dtype='float32'),'UNKNOWN_RELATIVE','synthetic-relative-A')
        self.fixture.anchor['anchorHeight']['offsetM']=.1
        self.snapshot=anchor_preview(self.fixture.snapshot,self.old.version_id,self.fixture.anchor,self.terrains)['snapshot']
        old_frame=copy.deepcopy(self.snapshot['coordinateFrame'])
        new=self.resource(np.full((32,32),100,dtype='float32'),'UNKNOWN_RELATIVE','synthetic-relative-A')
        for strategy in ('keep_height','resample_ground'):
            result=self.preview(new,strategy);value=result['snapshot'];height=value['coordinateFrame']['anchor']['anchorHeight']
            self.assertEqual(value['coordinateFrame']['originHeight'],.1)
            self.assertEqual(value['initialView'],self.snapshot['initialView'])
            self.assertGreater(abs(height['offsetCompensationM']),0)
            self.assertLess(abs(height['offsetCompensationM']),1e-12)
            reopened=json.loads(json.dumps(value))
            checked=geometry_check(reopened,self.terrains,expected_frame=value['coordinateFrame'])
            self.assertEqual(checked['snapshot']['coordinateFrame'],value['coordinateFrame'])
            self.assertEqual(value['coordinateFrame']['originEasting'],old_frame['originEasting'])
            self.assertEqual(value['coordinateFrame']['originNorthing'],old_frame['originNorthing'])
        # The legacy anchor's exact digest is unchanged, even after replacements.
        self.assertEqual(geometry_check(self.snapshot,self.terrains)['snapshot']['coordinateFrame'],old_frame)

    def test_origin_compensation_is_not_a_client_height_or_loose_tolerance(self):
        self.anchored(datum='UNKNOWN_RELATIVE',reference='synthetic-relative-A')
        anchor=copy.deepcopy(self.fixture.anchor);anchor['anchorHeight']['offsetCompensationM']=0
        self.expect('INVALID_REQUEST',lambda:anchor_preview(self.fixture.snapshot,self.old.version_id,anchor,self.terrains))
        new=self.resource(np.full((32,32),112,dtype='float32'),'UNKNOWN_RELATIVE','synthetic-relative-A')
        value=self.preview(new,'keep_height')['snapshot']
        value['coordinateFrame']['anchor']['anchorHeight']['offsetCompensationM']=1e-7
        self.expect('INVALID_COORDINATE',lambda:geometry_check(value,self.terrains))


if __name__=='__main__':unittest.main()
