"""Real synthetic GIS checks for the bounded scene geometry worker.

Missing GIS dependencies fail acceptance; these tests do not substitute a fake
processor for projection, fixed mesh sampling or NoData handling.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform

from apps.api.scene_geometry import (GeometryError, TrustedTerrain, anchor_preview,
    geometry_check)
from apps.api.terrain_coordinates import ProjectedFrame
from apps.api.terrain_validation import PLACEMENT_SAMPLING_RULE, validate


class SceneGeometryTests(unittest.TestCase):
    def test_organization_survives_geometry_and_anchor_without_retargeting_saved_cameras(self):
        from tests.test_scene_organization import organization
        self.snapshot['organization'] = organization([self.instance], self.model)
        before = copy.deepcopy(self.snapshot['organization'])
        self.assertEqual(geometry_check(self.snapshot, {})['snapshot']['organization'], before)
        self.resource()
        result = self.preview()
        self.assertEqual(result['snapshot']['organization'], before)
        self.assertNotEqual(result['snapshot']['coordinateFrame']['frameRevision'],
                            result['snapshot']['organization']['viewpoints'][0]['frameRevision'])
        self.assertEqual(geometry_check(result['snapshot'], self.terrains)['snapshot']['organization'], before)
        invalid = copy.deepcopy(self.snapshot)
        invalid['organization']['routes'][0]['steps'][0]['dwellSeconds'] = True
        self.expect('INVALID_SCENE_ORGANIZATION', lambda: geometry_check(invalid, {}))

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.version=str(uuid4());self.model=str(uuid4());self.instance=str(uuid4())
        self.snapshot={
            'displayName':'合成布置',
            'coordinateFrame':{'mode':'local_plane','frameRevision':'local-r1','origin':[0,0,0],
                               'unit':'m','axes':'X_EAST_Y_UP_Z_SOUTH'},
            'terrain':None,
            'instances':[{'sceneModelInstanceId':self.instance,'displayName':'设备 A',
                'modelVersionId':self.model,
                'placement':{'position':{'mode':'local','xM':0,'zM':0},
                             'height':{'mode':'local_relative','relativeHeightM':3},'headingDeg':30},
                'visible':True,'positionLocked':False,'rootBinding':None,'componentBindings':[]}],
            'initialView':{'eye':[80,60,90],'target':[0,15,0]},
            'defaults':{'background':'sky','lighting':'dusk','terrainMaterial':'solid'}}

    def resource(self,values=None,datum='EGM2008',relative_reference=None):
        source=self.root/(str(uuid4())+'.tif')
        values=np.full((32,32),100,dtype='float32') if values is None else np.asarray(values,dtype='float32')
        with rasterio.open(source,'w',driver='GTiff',width=values.shape[1],height=values.shape[0],
                           count=1,dtype='float32',crs='EPSG:32649',
                           transform=Affine(10,0,500000,0,-10,3700000),nodata=-9999) as dataset:
            dataset.write(values,1);dataset.update_tags(VERTICAL_DATUM=datum)
        directory=self.root/self.version/'derived'
        directory.parent.mkdir()
        report=validate(source,directory,vertical_datum=datum,source_note='Synthetic fixture',
                        license_note='Synthetic test data',relative_reference_id=relative_reference)
        trusted=TrustedTerrain(self.version,'content-r1',report['source']['sha256'],
                               hashlib.sha256((directory/'report.json').read_bytes()).hexdigest(),directory)
        self.report=report;self.trusted=trusted;self.terrains={self.version:trusted}
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[500160],[3699840])
        self.anchor={'localAnchor':[0,0],'geographicAnchor':[longitude[0],latitude[0]],
                     'trueNorthHeadingDeg':90,
                     'anchorHeight':{'mode':'terrain_ground','terrainVersionId':self.version,'offsetM':2},
                     'heightStrategy':'resample_each_ground'}
        return trusted

    def preview(self):
        return anchor_preview(self.snapshot,self.version,self.anchor,self.terrains)

    def expect(self,code,fn):
        with self.assertRaises(GeometryError) as caught:fn()
        self.assertEqual(caught.exception.code,code)

    def test_local_placements_do_not_require_gis_or_claim_geography(self):
        self.snapshot['instances'][0]['placement']['headingDeg']=-30
        result=geometry_check(self.snapshot,{})
        self.assertEqual(result['displayPlacements'][0]['position'],[0,3,0])
        self.assertAlmostEqual(result['displayPlacements'][0]['threeYawRad'],-math.radians(330))
        self.assertEqual(result['resourceRefs'],{'models':[self.model],'terrains':[]})
        self.assertFalse(result['geometrySummary']['fieldAccuracyVerified'])
        self.assertFalse(result['geometrySummary']['engineeringValidationPerformed'])
        self.assertEqual(self.snapshot['instances'][0]['placement']['headingDeg'],-30)

    def test_import_and_local_validation_without_importing_gis(self):
        code="""import builtins,json,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in ('numpy','rasterio'):raise ImportError('GIS disabled')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from apps.api.scene_geometry import geometry_check
print(json.dumps(geometry_check(json.loads(sys.argv[1]),{})['geometrySummary']))
"""
        result=subprocess.run([sys.executable,'-c',code,json.dumps(self.snapshot)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['mode'],'local_plane')

    def test_full_anchor_resamples_mesh_and_retains_anchor_offset(self):
        self.resource();before=copy.deepcopy(self.snapshot)
        result=self.preview();item=result['snapshot']['instances'][0]
        height=item['placement']['height']
        self.assertEqual(height['mode'],'terrain_ground');self.assertEqual(height['sampledHeightM'],100)
        self.assertEqual(height['offsetM'],5)
        self.assertEqual(height['samplingRule'],PLACEMENT_SAMPLING_RULE)
        self.assertAlmostEqual(result['displayPlacements'][0]['heightM'],105)
        self.assertAlmostEqual(result['displayPlacements'][0]['position'][1],3)
        self.assertEqual(result['snapshot']['coordinateFrame']['originHeight'],102)
        self.assertEqual(result['resourceRefs']['terrains'],[{
            'terrainVersionId':self.version,'contentRevision':'content-r1','sha256':self.trusted.sha256,
            'reportSha256':self.trusted.report_sha256}])
        self.assertEqual(result['impact']['kind'],'first_geographic_anchor')
        self.assertTrue(result['impact']['explicitConfirmationRequired'])
        self.assertEqual(result['anchorTransform']['verticalTransform'],'per_instance_fixed_mesh')
        self.assertEqual(self.snapshot,before)
        checked=geometry_check(result['snapshot'],self.terrains,expected_frame=result['snapshot']['coordinateFrame'])
        self.assertEqual(checked['snapshot'],result['snapshot'])

    def test_rigid_rotation_and_camera_use_verified_convergence(self):
        self.resource()
        self.snapshot['instances'][0]['placement']['position']['xM']=20
        result=self.preview();frame_data=result['snapshot']['coordinateFrame']
        frame=ProjectedFrame(*self.anchor['geographicAnchor'],102,'EGM2008',frame_data['frameRevision'])
        heading=frame.true_heading_to_grid(90,*self.anchor['geographicAnchor'])
        angle=math.radians(heading)
        position=result['displayPlacements'][0]['position']
        self.assertAlmostEqual(position[0],20*math.cos(angle),places=7)
        self.assertAlmostEqual(position[2],20*math.sin(angle),places=7)
        eye=result['snapshot']['initialView']['eye']
        self.assertAlmostEqual(eye[0],80*math.cos(angle)-90*math.sin(angle),places=7)
        self.assertAlmostEqual(eye[2],80*math.sin(angle)+90*math.cos(angle),places=7)
        self.assertAlmostEqual(eye[1],60)
        placed=result['snapshot']['instances'][0]['placement']
        longitude,latitude=placed['position']['longitude'],placed['position']['latitude']
        self.assertAlmostEqual(frame.true_heading_to_grid(placed['headingDeg'],longitude,latitude),(heading+30)%360)

    def test_nonzero_local_anchor_transforms_the_whole_layout(self):
        self.resource();self.anchor['localAnchor']=[12,-8]
        self.snapshot['instances'][0]['placement']['position']={'mode':'local','xM':12,'zM':-8}
        result=self.preview();position=result['displayPlacements'][0]['position']
        self.assertAlmostEqual(position[0],0,places=7);self.assertAlmostEqual(position[2],0,places=7)
        transform=result['anchorTransform'];angle=-transform['rotationYRad']
        self.assertAlmostEqual(12*math.cos(angle)+8*math.sin(angle)+transform['translationM'][0],0)
        self.assertAlmostEqual(12*math.sin(angle)-8*math.cos(angle)+transform['translationM'][2],0)

    def test_known_keep_relative_becomes_declared_absolute_with_source(self):
        self.resource();self.anchor['heightStrategy']='keep_relative_to_anchor'
        result=self.preview();height=result['snapshot']['instances'][0]['placement']['height']
        self.assertEqual(height['mode'],'absolute');self.assertEqual(height['valueM'],105)
        self.assertEqual(height['verticalDatum'],'EGM2008');self.assertIn('anchor',height['sourceNote'])
        self.assertEqual(result['heightProvenance'][0]['kind'],'relative_layout_from_anchor')
        self.assertEqual(result['heightProvenance'][0]['anchorSource'],self.anchor['anchorHeight'])
        result['heightProvenance'][0]['anchorSource']['offsetM']=10
        self.assertEqual(self.anchor['anchorHeight']['offsetM'],2)

    def test_unknown_keep_relative_remains_ground_on_same_reference(self):
        values=np.indices((32,32))[1].astype('float32')+100
        self.resource(values,'UNKNOWN_RELATIVE','survey-relative-A')
        self.anchor['heightStrategy']='keep_relative_to_anchor'
        self.snapshot['instances'][0]['placement']['position']['zM']=-30
        result=self.preview();height=result['snapshot']['instances'][0]['placement']['height']
        self.assertEqual(height['mode'],'terrain_ground')
        self.assertEqual(result['snapshot']['coordinateFrame']['relativeReferenceId'],'survey-relative-A')
        self.assertAlmostEqual(result['displayPlacements'][0]['heightM'],result['snapshot']['coordinateFrame']['originHeight']+3)
        self.assertEqual(result['heightProvenance'][0]['relativeReferenceId'],'survey-relative-A')
        self.assertEqual(result['heightProvenance'][0]['kind'],'relative_layout_from_anchor')

    def test_unknown_relative_never_accepts_absolute_height_or_anchor(self):
        self.resource(datum='UNKNOWN_RELATIVE',relative_reference='relative-A')
        result=self.preview();snapshot=result['snapshot']
        snapshot['instances'][0]['placement']['height']={'mode':'absolute','valueM':105,'verticalDatum':'UNKNOWN_RELATIVE','sourceNote':'claimed'}
        self.expect('VERTICAL_DATUM_CONFLICT',lambda:geometry_check(snapshot,self.terrains))
        self.anchor['anchorHeight']={'mode':'absolute','valueM':100,'verticalDatum':'UNKNOWN_RELATIVE','sourceNote':'claimed'}
        self.expect('VERTICAL_DATUM_CONFLICT',self.preview)

    def test_ordinary_absolute_height_can_be_outside_terrain_coverage(self):
        self.resource();result=self.preview();snapshot=result['snapshot']
        item=snapshot['instances'][0]['placement'];item['position']['longitude']+=.02
        item['height']={'mode':'absolute','valueM':123,'verticalDatum':'EGM2008','sourceNote':'Explicit synthetic height'}
        checked=geometry_check(snapshot,self.terrains,expected_frame=snapshot['coordinateFrame'])
        self.assertEqual(checked['displayPlacements'][0]['heightM'],123)
        self.assertEqual(checked['heightProvenance'][0]['kind'],'declared_absolute')
        preview=geometry_check(snapshot,self.terrains,expected_frame=snapshot['coordinateFrame'],resample_ground=True)
        self.assertEqual(preview,checked)

    def test_ground_outside_coverage_is_rejected_even_when_terrain_hidden(self):
        self.resource();snapshot=self.preview()['snapshot']
        item=snapshot['instances'][0];item['visible']=False
        placement=item['placement'];placement['position']['longitude']+=.02
        placement['height']['sampleLongitude']=placement['position']['longitude']
        self.expect('OUTSIDE_COVERAGE',lambda:geometry_check(snapshot,self.terrains))

    def test_unknown_keep_relative_requires_valid_new_samples(self):
        self.resource(datum='UNKNOWN_RELATIVE',relative_reference='relative-A')
        self.anchor['heightStrategy']='keep_relative_to_anchor'
        self.snapshot['instances'][0]['placement']['position']['xM']=2000
        self.expect('OUTSIDE_COVERAGE',self.preview)

    def test_nodata_hole_blocks_anchor_and_placement(self):
        values=np.full((32,32),100,dtype='float32');values[14:18,14:18]=-9999
        self.resource(values)
        self.expect('NO_DATA',self.preview)
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[500080],[3699920])
        self.anchor['geographicAnchor']=[longitude[0],latitude[0]]
        self.snapshot['instances'][0]['placement']['position']['xM']=80
        self.snapshot['instances'][0]['placement']['position']['zM']=80
        self.anchor['trueNorthHeadingDeg']=0
        self.expect('NO_DATA',self.preview)

    def test_returned_sample_and_location_are_conditions_not_truth(self):
        self.resource();snapshot=self.preview()['snapshot']
        snapshot['instances'][0]['placement']['height']['sampledHeightM']+=.01
        self.expect('TERRAIN_SAMPLE_CHANGED',lambda:geometry_check(snapshot,self.terrains))
        snapshot=self.preview()['snapshot']
        snapshot['instances'][0]['placement']['height']['sampleLongitude']+=.0001
        self.expect('TERRAIN_SAMPLE_CHANGED',lambda:geometry_check(snapshot,self.terrains))

    def test_moved_ground_preview_resamples_then_strict_save_accepts_canonical_result(self):
        row,column=np.indices((32,32))
        self.resource(100+column*2+row*.5)
        snapshot=self.preview()['snapshot'];before=copy.deepcopy(snapshot)
        placement=snapshot['instances'][0]['placement'];old_height=placement['height']['sampledHeightM']
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[500180],[3699840])
        placement['position']['longitude']=longitude[0];placement['position']['latitude']=latitude[0]
        self.expect('TERRAIN_SAMPLE_CHANGED',lambda:geometry_check(snapshot,self.terrains))
        checked=geometry_check(snapshot,self.terrains,expected_frame=before['coordinateFrame'],resample_ground=True)
        canonical=checked['snapshot'];height=canonical['instances'][0]['placement']['height']
        self.assertEqual(height['sampleLongitude'],longitude[0]);self.assertEqual(height['sampleLatitude'],latitude[0])
        self.assertGreater(height['sampledHeightM'],old_height+3.9);self.assertEqual(height['offsetM'],5)
        strict=geometry_check(canonical,self.terrains,expected_frame=before['coordinateFrame'])
        self.assertEqual(strict['snapshot'],canonical)
        self.assertEqual(strict['displayPlacements'],checked['displayPlacements'])
        self.assertEqual(strict['heightProvenance'],checked['heightProvenance'])
        self.assertEqual(snapshot['instances'][0]['placement']['height'],before['instances'][0]['placement']['height'])

    def test_ground_edit_preview_still_rejects_nodata_coverage_and_changed_resource(self):
        values=np.full((32,32),100,dtype='float32');values[14:18,14:18]=-9999
        self.resource(values)
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[500080],[3699920])
        self.anchor['geographicAnchor']=[longitude[0],latitude[0]]
        snapshot=self.preview()['snapshot'];placement=snapshot['instances'][0]['placement']
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[500160],[3699840])
        placement['position']['longitude']=longitude[0];placement['position']['latitude']=latitude[0]
        self.expect('NO_DATA',lambda:geometry_check(snapshot,self.terrains,resample_ground=True))
        placement['position']['longitude']+=.02
        self.expect('OUTSIDE_COVERAGE',lambda:geometry_check(snapshot,self.terrains,resample_ground=True))
        placement['height']['terrainSha256']='0'*64
        self.expect('RESOURCE_CHANGED',lambda:geometry_check(snapshot,self.terrains,resample_ground=True))

    def test_resampling_is_explicit_boolean_and_cannot_be_hidden_in_snapshot(self):
        self.resource();snapshot=self.preview()['snapshot']
        self.expect('INVALID_REQUEST',lambda:geometry_check(snapshot,self.terrains,resample_ground='true'))
        snapshot['resampleGround']=True
        self.expect('INVALID_REQUEST',lambda:geometry_check(snapshot,self.terrains))

    def test_scene_and_terrain_origins_can_differ_without_changing_surface(self):
        self.resource()
        longitude,latitude=transform('EPSG:32649','EPSG:4326',[500100],[3699900])
        self.anchor['geographicAnchor']=[longitude[0],latitude[0]]
        result=self.preview();frame=result['snapshot']['coordinateFrame'];translation=result['terrainDisplayTransform']['translation']
        resource=self.report['mesh']['frame']
        self.assertAlmostEqual(translation[0],resource['originEasting']-frame['originEasting'])
        self.assertAlmostEqual(translation[1],-102)
        self.assertAlmostEqual(translation[2],frame['originNorthing']-resource['originNorthing'])
        self.assertGreater(abs(translation[0]),50)

    def test_changed_frames_and_datum_are_rejected_before_accepting_positions(self):
        self.resource();snapshot=self.preview()['snapshot']
        for field,value,code in [('originHeight',103,'FRAME_CHANGED'),('transformId','another-runtime','FRAME_CHANGED'),
                                 ('verticalDatum','EGM96','FRAME_CHANGED')]:
            candidate=copy.deepcopy(snapshot);candidate['coordinateFrame'][field]=value
            self.expect(code,lambda:geometry_check(candidate,self.terrains))
        expected=copy.deepcopy(snapshot['coordinateFrame']);expected['frameRevision']='old-revision'
        self.expect('FRAME_CHANGED',lambda:geometry_check(snapshot,self.terrains,expected_frame=expected))
        snapshot['instances'][0]['placement']['height']['verticalDatum']='EGM96'
        self.expect('VERTICAL_DATUM_CONFLICT',lambda:geometry_check(snapshot,self.terrains))

    def test_fixed_resource_identity_and_authorized_manifest_are_required(self):
        self.resource();snapshot=self.preview()['snapshot']
        self.expect('NOT_FOUND_OR_FORBIDDEN',lambda:geometry_check(snapshot,{}))
        snapshot['terrain']['expectedContentRevision']='changed'
        self.expect('RESOURCE_CHANGED',lambda:geometry_check(snapshot,self.terrains))
        snapshot=self.preview()['snapshot'];snapshot['instances'][0]['placement']['height']['terrainSha256']='0'*64
        self.expect('RESOURCE_CHANGED',lambda:geometry_check(snapshot,self.terrains))

    def test_fixed_report_and_artifacts_cannot_change_under_trusted_sha(self):
        self.resource();snapshot=self.preview()['snapshot'];report=self.trusted.directory/'report.json'
        original=report.read_bytes();changed=json.loads(original);changed['mesh']['frame']['originHeight']=100
        report.write_text(json.dumps(changed))
        self.expect('RESOURCE_CHANGED',lambda:geometry_check(snapshot,self.terrains))
        report.write_bytes(original)
        artifact=self.trusted.directory/'positions.f32';raw=bytearray(artifact.read_bytes());raw[1]^=1;artifact.write_bytes(raw)
        self.expect('RESOURCE_CHANGED',lambda:geometry_check(snapshot,self.terrains))

    def test_symlink_artifact_is_rejected(self):
        self.resource();snapshot=self.preview()['snapshot'];path=self.trusted.directory/'cells.u8'
        outside=self.root/'outside.u8';outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
        self.expect('RESOURCE_CHANGED',lambda:geometry_check(snapshot,self.terrains))

    def test_symlink_version_directory_cannot_redirect_private_manifest(self):
        self.resource();snapshot=self.preview()['snapshot'];version_dir=self.trusted.directory.parent
        actual=self.root/'redirected';version_dir.rename(actual);version_dir.symlink_to(actual,target_is_directory=True)
        self.expect('RESOURCE_CHANGED',lambda:geometry_check(snapshot,self.terrains))

    def test_absolute_anchor_still_respects_resource_regional_radius(self):
        self.resource();self.anchor['heightStrategy']='keep_relative_to_anchor'
        self.anchor['anchorHeight']={'mode':'absolute','valueM':100,'verticalDatum':'EGM2008','sourceNote':'fixture'}
        self.anchor['geographicAnchor'][0]+=1
        self.expect('OUTSIDE_COVERAGE',self.preview)

    def test_domain_radius_and_cross_zone_remain_bounded_for_absolute(self):
        self.resource();snapshot=self.preview()['snapshot'];placement=snapshot['instances'][0]['placement']
        placement['height']={'mode':'absolute','valueM':100,'verticalDatum':'EGM2008','sourceNote':'fixture'}
        placement['position']['longitude']+=1
        self.expect('OUTSIDE_COVERAGE',lambda:geometry_check(snapshot,self.terrains))
        placement['position']['longitude']=114.1
        self.expect('OUTSIDE_PROJECTION_AREA',lambda:geometry_check(snapshot,self.terrains))

    def test_engineering_associations_are_preserved_but_not_claimed_validated(self):
        self.resource();item=self.snapshot['instances'][0]
        item['rootBinding']={'objectRef':{'entityUid':'synthetic-root'}}
        item['componentBindings']=[{'componentKeys':['local:1'],'objectRef':{'entityUid':'synthetic-cabinet'}}]
        result=self.preview()
        self.assertEqual(result['snapshot']['instances'][0]['rootBinding'],item['rootBinding'])
        self.assertEqual(result['snapshot']['instances'][0]['componentBindings'],item['componentBindings'])
        self.assertFalse(result['geometrySummary']['engineeringValidationPerformed'])

    def test_malformed_inputs_produce_structured_errors_and_no_matrix_acceptance(self):
        for field,value in [('coordinateFrame',None),('coordinateFrame',[]),('instances',[None])]:
            candidate=copy.deepcopy(self.snapshot);candidate[field]=value
            self.expect('INVALID_REQUEST',lambda:geometry_check(candidate,{}))
        for key,value in [('height',None),('position',[]),('matrix',[1]*16)]:
            candidate=copy.deepcopy(self.snapshot);candidate['instances'][0]['placement'][key]=value
            self.expect('INVALID_REQUEST',lambda:geometry_check(candidate,{}))
        candidate=copy.deepcopy(self.snapshot);candidate['instances'].append(copy.deepcopy(candidate['instances'][0]))
        self.expect('DUPLICATE_INSTANCE',lambda:geometry_check(candidate,{}))
        candidate=copy.deepcopy(self.snapshot);candidate['initialView']['eye'][0]=float('nan')
        self.expect('INVALID_REQUEST',lambda:geometry_check(candidate,{}))
        self.resource();self.anchor['anchorHeight']=None
        self.expect('INVALID_REQUEST',self.preview)

    def cli(self,request):
        path=self.root/'request.json';path.write_text(json.dumps(request))
        return subprocess.run([sys.executable,'-m','apps.api.scene_geometry',str(path),'--terrain-root',str(self.root)],
                              capture_output=True,text=True,timeout=20)

    def test_fixed_cli_anchor_manifest_outputs_no_private_path(self):
        self.resource()
        request={'kind':'anchor','snapshot':self.snapshot,'candidateTerrainVersionId':self.version,'anchor':self.anchor,
                 'trustedTerrains':[{'terrainVersionId':self.version,'contentRevision':'content-r1',
                    'sha256':self.trusted.sha256,'reportSha256':self.trusted.report_sha256}]}
        completed=self.cli(request);self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
        result=json.loads(completed.stdout)
        self.assertEqual(result['snapshot'],self.preview()['snapshot'])
        self.assertNotIn(str(self.root),completed.stdout)
        request={'kind':'validate','snapshot':result['snapshot'],
                 'expectedFrame':result['snapshot']['coordinateFrame'],'trustedTerrains':request['trustedTerrains']}
        completed=self.cli(request);self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['snapshot'],result['snapshot'])
        request['snapshot']['instances'][0]['placement']['position']['longitude']+=.0001
        completed=self.cli(request);self.assertEqual(completed.returncode,2)
        self.assertEqual(json.loads(completed.stdout)['code'],'TERRAIN_SAMPLE_CHANGED')
        request['resampleGround']=True
        completed=self.cli(request);self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
        canonical=json.loads(completed.stdout)['snapshot']
        self.assertNotEqual(canonical['instances'][0]['placement']['height']['sampleLongitude'],result['snapshot']['instances'][0]['placement']['height']['sampleLongitude'])
        geometry_check(canonical,self.terrains)
        request['resampleGround']=1
        completed=self.cli(request);self.assertEqual(completed.returncode,2)
        self.assertEqual(json.loads(completed.stdout)['code'],'INVALID_REQUEST')

    def test_cli_rejects_paths_remote_manifest_and_unbounded_json(self):
        self.resource()
        request={'kind':'validate','snapshot':self.snapshot,'trustedTerrains':[{
            'terrainVersionId':self.version,'contentRevision':'content-r1','sha256':self.trusted.sha256,
            'reportSha256':self.trusted.report_sha256,'directory':'https://invalid.example/private'}]}
        completed=self.cli(request);self.assertEqual(completed.returncode,2)
        self.assertEqual(json.loads(completed.stdout),{'code':'INVALID_REQUEST'})
        path=self.root/'request.json';path.write_text(' '*1048577)
        completed=subprocess.run([sys.executable,'-m','apps.api.scene_geometry',str(path)],capture_output=True,text=True,timeout=10)
        self.assertEqual(completed.returncode,2);self.assertNotIn(str(self.root),completed.stdout)
        path.write_text('[]')
        completed=subprocess.run([sys.executable,'-m','apps.api.scene_geometry',str(path)],capture_output=True,text=True,timeout=10)
        self.assertEqual(completed.returncode,2);self.assertEqual(json.loads(completed.stdout),{'code':'INVALID_REQUEST'})


if __name__=='__main__':unittest.main()
