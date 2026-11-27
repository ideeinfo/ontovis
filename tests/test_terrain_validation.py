"""Synthetic private GeoTIFF validation, fixed-mesh sampling and rejection cases.

Requires the explicitly provisioned GIS runtime; missing dependencies fail the
suite rather than silently skipping terrain acceptance.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform

from apps.api.terrain_coordinates import sample_bilinear
from apps.api.terrain_validation import (MAX_TRIANGLES, PLACEMENT_SAMPLING_RULE,
    TerrainError, prepare_mesh, sample_mesh, validate)


class TerrainValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.affine=Affine(10,0,500000,0,-10,3700000)

    def raster(self,name='source.tif',values=None,**changes):
        path=self.root/name
        values=np.arange(16*16,dtype='float32').reshape(16,16) if values is None else np.asarray(values)
        if values.ndim==2: values=values[None,:,:]
        options={'driver':'GTiff','height':values.shape[1],'width':values.shape[2],
                 'count':values.shape[0],'dtype':str(values.dtype),'crs':'EPSG:32649','transform':self.affine,**changes}
        with rasterio.open(path,'w',**options) as dataset:
            dataset.write(values)
        return path

    def run_validation(self,path=None,**kwargs):
        output=self.root/('result-'+str(len(list(self.root.glob('result-*')))))
        return output, validate(path or self.raster(),output,vertical_datum='EGM2008',
                               source_note='Synthetic elevation fixture',license_note='Synthetic test data',**kwargs)

    def expect(self,code,fn):
        with self.assertRaises(TerrainError) as caught: fn()
        self.assertEqual(caught.exception.code,code)

    def test_valid_private_mesh_is_fixed_masked_and_has_no_private_path(self):
        path=self.raster(); output,report=self.run_validation(path)
        self.assertEqual(report['state'],'ready'); self.assertEqual(report['source']['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report['source']['verticalDatum'],'EGM2008'); self.assertEqual(report['source']['validPixels'],256)
        self.assertEqual(report['externalResourcesFetched'],0); self.assertFalse(report['verticalConversionApplied']); self.assertFalse(report['fieldAccuracyVerified'])
        self.assertLessEqual(report['mesh']['triangles'],MAX_TRIANGLES)
        self.assertEqual(report['mesh']['placementSamplingRule'],PLACEMENT_SAMPLING_RULE)
        self.assertLessEqual(report['mesh']['displayContactMaxErrorM'],.02)
        self.assertIsNone(report['mesh']['sourceSurfaceApproximationErrorM'])
        self.assertNotIn(str(self.root),json.dumps(report))
        self.assertEqual(json.loads((output/'report.json').read_text()),report)
        for artifact in report['artifacts']:
            target=output/artifact['artifactId']
            self.assertEqual(target.stat().st_size,artifact['bytes'])
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),artifact['sha256'])
            self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_mesh_sampling_uses_same_fixed_triangle_not_bilinear(self):
        output,report=self.run_validation(self.raster(values=np.arange(16*16,dtype='float32').reshape(16,16)**2))
        grid=report['mesh']; rows,columns=grid['rows'],grid['columns']
        heights=np.fromfile(output/'positions.f32',dtype='<f4').reshape(rows,columns,3)[:,:,1].astype('float64')+grid['frame']['originHeight']
        positions=np.fromfile(output/'positions.f32',dtype='<f4').reshape(rows,columns,3)
        mask=np.fromfile(output/'mask.u8',dtype='uint8').reshape(rows,columns)
        row,column=next((r,c) for r in range(1,rows-2) for c in range(1,columns-2) if mask[r:r+2,c:c+2].all())
        for tx,ty in ((.2,.3),(.8,.6),(0.,0.)):
            x=grid['frame']['originEasting']+float(positions[row,column,0])+tx*(float(positions[row,column+1,0])-float(positions[row,column,0]))
            y=grid['frame']['originNorthing']-float(positions[row,column,2])-ty*(float(positions[row+1,column,2])-float(positions[row,column,2]))
            a,b,c,d=heights[row,column],heights[row,column+1],heights[row+1,column],heights[row+1,column+1]
            expected=a+tx*(b-a)+ty*(c-a) if tx+ty<=1 else d+(1-tx)*(c-d)+(1-ty)*(b-d)
            self.assertAlmostEqual(sample_mesh(output,x,y),expected,places=7)

    def test_source_vertex_sampling_matches_pixel_centre_contract(self):
        values=np.arange(16*16,dtype='float32').reshape(16,16)
        output,report=self.run_validation(self.raster(values=values))
        grid=report['mesh']; rows,columns=grid['rows'],grid['columns']
        heights=np.fromfile(output/'heights.f64',dtype='<f8').reshape(rows,columns)
        mask=np.fromfile(output/'mask.u8',dtype='uint8').reshape(rows,columns)
        checked=0
        for row,column in np.argwhere(mask):
            if row%3 or column%3: continue
            east=grid['eastingMinM']+column*grid['stepEastingM']; north=grid['northingMaxM']-row*grid['stepNorthingM']
            expected=sample_bilinear(values,tuple(self.affine)[:6],east,north)
            self.assertAlmostEqual(heights[row,column],expected,places=6); checked+=1
        self.assertGreater(checked,5)

    def test_nodata_and_declared_nan_keep_holes_and_omit_surface(self):
        values=np.ones((16,16),dtype='float32')*100; values[6:10,6:10]=np.nan
        output,report=self.run_validation(self.raster(values=values,nodata=float('nan')))
        self.assertEqual(report['source']['missingPixels'],16)
        grid=report['mesh']; rows,columns=grid['rows'],grid['columns']
        mask=np.fromfile(output/'mask.u8',dtype='uint8').reshape(rows,columns)
        heights=np.fromfile(output/'heights.f64',dtype='<f8').reshape(rows,columns)
        self.assertTrue(np.isnan(heights[mask==0]).all())
        row,column=next((r,c) for r in range(4,rows-4) for c in range(4,columns-4) if not mask[r:r+2,c:c+2].all())
        east=grid['eastingMinM']+(column+.5)*grid['stepEastingM']; north=grid['northingMaxM']-(row+.5)*grid['stepNorthingM']
        self.expect('NO_DATA',lambda:sample_mesh(output,east,north))
        self.assertLess(grid['triangles'],2*(rows-1)*(columns-1))

    def test_downsampling_cannot_bridge_a_hole_between_valid_mesh_vertices(self):
        values=np.full((64,64),100,dtype='float32'); values[31:33,31:33]=-9999
        output,report=self.run_validation(self.raster(values=values,nodata=-9999),grid_side=10)
        self.assertEqual(report['source']['missingPixels'],4)
        grid=report['mesh']; rows,columns=grid['rows'],grid['columns']
        vertices=np.fromfile(output/'mask.u8',dtype='uint8').reshape(rows,columns)
        cells=np.fromfile(output/'cells.u8',dtype='uint8').reshape(rows-1,columns-1)
        self.assertTrue(vertices[4:6,4:6].all()) # Corner samples alone cannot reveal this hole.
        self.assertEqual(cells[4,4],0)
        self.expect('NO_DATA',lambda:sample_mesh(output,500320,3699680))
        triangles=np.fromfile(output/'triangles.u32',dtype='<u4').reshape(-1,3)
        top_left=4*columns+4
        self.assertFalse(np.any(np.all(triangles==[top_left,top_left+columns,top_left+1],axis=1)))

    def test_coarse_grid_with_no_remaining_surface_does_not_publish_ready(self):
        values=np.full((32,32),100,dtype='float32'); values[14:18,14:18]=-9999
        path=self.raster(values=values,nodata=-9999)
        self.expect('NO_DATA',lambda:self.run_validation(path,grid_side=4))
        self.assertEqual(list(self.root.glob('result-*')),[])

    def test_downsampling_does_not_erase_untouched_valid_surface(self):
        values=np.full((64,64),100,dtype='float32'); values[29:35,29:35]=-9999
        output,report=self.run_validation(self.raster(values=values,nodata=-9999),grid_side=10)
        self.assertGreater(report['mesh']['validCells'],0)
        self.assertEqual(sample_mesh(output,500100,3699900),100)
        self.expect('NO_DATA',lambda:sample_mesh(output,500320,3699680))

    def test_unmasked_nan_and_infinity_fail_without_ready_output(self):
        for invalid in (float('nan'),float('inf')):
            values=np.ones((16,16),dtype='float32'); values[3,4]=invalid
            path=self.raster('nonfinite.tif',values)
            self.expect('INVALID_TERRAIN',lambda:self.run_validation(path))
            self.assertEqual(list(self.root.glob('result-*')),[])
            self.assertEqual(list(self.root.glob('.terrain-*')),[])

    def test_all_missing_never_creates_a_ready_mesh(self):
        path=self.raster(values=np.full((16,16),-9999,dtype='int16'),nodata=-9999)
        self.expect('NO_DATA',lambda:self.run_validation(path))
        self.assertEqual(list(self.root.glob('result-*')),[])

    def test_missing_crs_and_multiband_are_rejected(self):
        self.expect('CRS_REQUIRED',lambda:self.run_validation(self.raster('no-crs.tif',crs=None)))
        self.expect('UNSUPPORTED_TERRAIN',lambda:self.run_validation(self.raster('multi.tif',np.ones((2,16,16),dtype='float32'))))

    def test_rotated_affine_and_wrong_axis_are_explicitly_rejected(self):
        for affine in (Affine(10,1,500000,0,-10,3700000),Affine(10,0,500000,1,-10,3700000),Affine(-10,0,500000,0,-10,3700000),Affine(10,0,500000,0,10,3700000)):
            with self.subTest(affine=affine):
                self.expect('UNSUPPORTED_TERRAIN',lambda:self.run_validation(self.raster('affine.tif',transform=affine)))

    def test_unsupported_crs_units_and_missing_vertical_declaration(self):
        self.expect('UNSUPPORTED_CRS',lambda:self.run_validation(self.raster('mercator.tif',crs='EPSG:3857')))
        self.expect('UNSUPPORTED_TERRAIN',lambda:self.run_validation(self.raster(),height_unit='ft'))
        path=self.raster(); target=self.root/'bad-vertical'
        self.expect('VERTICAL_DATUM_CONFLICT',lambda:validate(path,target,vertical_datum='WGS84',source_note='fixture',license_note='fixture'))

    def test_embedded_vertical_declaration_cannot_be_overridden_or_ignored(self):
        path=self.raster()
        with rasterio.open(path,'r+') as dataset:
            dataset.update_tags(VERTICAL_DATUM='EGM2008 (EPSG:3855), metres')
        output,report=self.run_validation(path)
        self.assertEqual(report['source']['embeddedVerticalDatums'],['EGM2008'])
        self.assertEqual(report['source']['verticalDeclarationSource'],'embedded_and_operator')
        self.expect('VERTICAL_DATUM_CONFLICT',lambda:validate(path,self.root/'conflict',vertical_datum='WGS84_ELLIPSOIDAL',source_note='fixture',license_note='fixture'))
        with rasterio.open(path,'r+') as dataset:
            dataset.update_tags(VERTICAL_DATUM='Unknown local datum which has not been verified')
        self.expect('VERTICAL_DATUM_CONFLICT',lambda:self.run_validation(path))

    def test_tampered_spacing_and_origin_report_fail_structurally(self):
        output,_=self.run_validation()
        report_file=output/'report.json'; original=json.loads(report_file.read_text())
        for key,value in (('stepEastingM',0),('stepNorthingM',-1),('stepEastingM',float('nan'))):
            report=json.loads(json.dumps(original)); report['mesh'][key]=value; report_file.write_text(json.dumps(report))
            self.expect('INVALID_TERRAIN',lambda:sample_mesh(output,500000,3700000))
        report=json.loads(json.dumps(original)); report['mesh']['frame']['originHeight']=float('inf'); report_file.write_text(json.dumps(report))
        self.expect('INVALID_TERRAIN',lambda:sample_mesh(output,500000,3700000))
        report=json.loads(json.dumps(original)); report['mesh']['frame']['originHeight']=100; report_file.write_text(json.dumps(report))
        self.expect('INVALID_TERRAIN',lambda:sample_mesh(output,500080,3699920))
        report=json.loads(json.dumps(original)); report['mesh']['stepEastingM']*=2; report_file.write_text(json.dumps(report))
        self.expect('INVALID_TERRAIN',lambda:sample_mesh(output,500080,3699920))

    def test_trusted_report_digest_rejects_modified_self_reported_metadata(self):
        output,_=self.run_validation()
        report_file=output/'report.json'; trusted=hashlib.sha256(report_file.read_bytes()).hexdigest()
        sample_mesh(output,500080,3699920,expected_report_sha256=trusted)
        changed=json.loads(report_file.read_text()); changed['mesh']['frame']['originHeight']=100
        report_file.write_text(json.dumps(changed))
        self.expect('RESOURCE_CHANGED',lambda:sample_mesh(output,500080,3699920,expected_report_sha256=trusted))

    def test_triangle_corruption_and_self_rehashed_wrong_topology_are_rejected(self):
        output,_=self.run_validation()
        target=output/'triangles.u32'; original=target.read_bytes(); target.write_bytes(b'\x00'*len(original))
        self.expect('RESOURCE_CHANGED',lambda:sample_mesh(output,500080,3699920))
        report_file=output/'report.json'; report=json.loads(report_file.read_text())
        item=next(item for item in report['artifacts'] if item['artifactId']=='triangles.u32')
        item['sha256']=hashlib.sha256(target.read_bytes()).hexdigest(); report_file.write_text(json.dumps(report))
        self.expect('INVALID_TERRAIN',lambda:sample_mesh(output,500080,3699920))

    def test_cell_mask_corruption_and_false_valid_cell_are_rejected(self):
        values=np.full((64,64),100,dtype='float32'); values[31:33,31:33]=-9999
        output,report=self.run_validation(self.raster(values=values,nodata=-9999),grid_side=10)
        target=output/'cells.u8'; cells=np.fromfile(target,dtype='uint8'); cells[4*9+4]=1; target.write_bytes(cells.tobytes())
        self.expect('RESOURCE_CHANGED',lambda:sample_mesh(output,500320,3699680))
        report_file=output/'report.json'; changed=json.loads(report_file.read_text())
        item=next(item for item in changed['artifacts'] if item['artifactId']=='cells.u8')
        item['sha256']=hashlib.sha256(target.read_bytes()).hexdigest(); report_file.write_text(json.dumps(changed))
        self.expect('INVALID_TERRAIN',lambda:sample_mesh(output,500320,3699680))

    def test_unknown_vertical_is_relative_with_explicit_reference_only(self):
        path=self.raster()
        self.expect('VERTICAL_DATUM_CONFLICT',lambda:validate(path,self.root/'unknown',vertical_datum='UNKNOWN_RELATIVE',source_note='fixture',license_note='fixture'))
        report=validate(path,self.root/'relative',vertical_datum='UNKNOWN_RELATIVE',relative_reference_id='fixture-relative-origin',source_note='fixture',license_note='fixture')
        self.assertEqual(report['source']['relativeReferenceId'],'fixture-relative-origin')
        self.assertEqual(report['mesh']['frame']['verticalDatum'],'UNKNOWN_RELATIVE')
        self.assertFalse(report['mesh']['frame']['isStrictEnu'])

    def test_pixel_file_and_grid_budgets_are_checked_before_processing(self):
        path=self.root/'large.tif'
        with rasterio.open(path,'w',driver='GTiff',width=4001,height=4001,count=1,dtype='uint8',crs='EPSG:32649',transform=self.affine): pass
        with patch('apps.api.terrain_validation._scan') as scan:
            self.expect('TERRAIN_LIMIT_EXCEEDED',lambda:self.run_validation(path)); scan.assert_not_called()
        path=self.raster()
        with patch('apps.api.terrain_validation.MAX_BYTES',8): self.expect('TERRAIN_LIMIT_EXCEEDED',lambda:self.run_validation(path))
        self.expect('TERRAIN_LIMIT_EXCEEDED',lambda:self.run_validation(path,grid_side=513))

    def test_501_grid_is_under_triangle_budget_and_no_dimension_is_upsampled(self):
        output,report=self.run_validation(self.raster(values=np.ones((510,510),dtype='float32')))
        self.assertEqual((report['mesh']['rows'],report['mesh']['columns']),(501,501))
        self.assertLessEqual(report['mesh']['triangles'],500000)
        self.assertEqual((output/'triangles.u32').stat().st_size,report['mesh']['triangles']*3*4)

    def test_explicit_aoi_is_bounded_and_source_tile_needs_regional_crop(self):
        affine=Affine(1/32,0,113,0,-1/32,34)
        path=self.raster(values=np.ones((32,32),dtype='float32'),crs='EPSG:4326',transform=affine)
        self.expect('OUTSIDE_COVERAGE',lambda:self.run_validation(path))
        output,report=self.run_validation(path,aoi=(113.2,33.4,113.4,33.6))
        self.assertEqual(report['source']['requestedAoiWgs84'],[113.2,33.4,113.4,33.6])
        self.assertEqual(report['source']['validPixels'],1024) # Entire source was inspected, not only the AOI.
        self.expect('OUTSIDE_COVERAGE',lambda:self.run_validation(path,aoi=(111,33,112,34)))
        self.expect('INVALID_REQUEST',lambda:self.run_validation(path,aoi=(114,34,113,33)))

    def test_non_tiff_vrt_archive_url_and_symlink_never_open_a_driver(self):
        for filename,data in (('external.vrt',b'<VRTDataset><SourceFilename>https://invalid.example/private</SourceFilename></VRTDataset>'),('archive.zip',b'PK'+b'x'*12)):
            path=self.root/filename; path.write_bytes(data)
            with patch('rasterio.open') as opener:
                self.expect('INVALID_TERRAIN',lambda:self.run_validation(path)); opener.assert_not_called()
        self.expect('INVALID_TERRAIN',lambda:self.run_validation(Path('/vsicurl/https://invalid.example/private.tif')))
        self.expect('INVALID_TERRAIN',lambda:self.run_validation(Path('https://invalid.example/private.tif')))
        target=self.raster(); link=self.root/'linked.tif'; link.symlink_to(target)
        self.expect('INVALID_TERRAIN',lambda:self.run_validation(link))

    def test_pam_sidecar_cannot_supply_missing_crs_or_height_metadata(self):
        path=self.raster(crs=None)
        Path(str(path)+'.aux.xml').write_text('<PAMDataset><SRS>EPSG:4326</SRS><Metadata><MDI key="VERTICAL_DATUM">EGM2008</MDI></Metadata></PAMDataset>')
        self.expect('CRS_REQUIRED',lambda:self.run_validation(path))

    def test_failure_during_artifact_write_cannot_publish_ready_report(self):
        path=self.raster()
        with patch('apps.api.terrain_validation.os.replace',side_effect=OSError('synthetic disk failure')):
            self.expect('INVALID_TERRAIN',lambda:self.run_validation(path))
        self.assertEqual(list(self.root.glob('result-*')),[]); self.assertEqual(list(self.root.glob('.terrain-*')),[])

    def test_changed_source_and_tampered_mesh_are_rejected(self):
        path=self.raster(); original_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        with patch('apps.api.terrain_validation._hash',side_effect=[original_hash,'different']):
            self.expect('RESOURCE_CHANGED',lambda:self.run_validation(path))
        output,report=self.run_validation(path)
        (output/'heights.f64').write_bytes(b'\x00'*(output/'heights.f64').stat().st_size)
        grid=report['mesh']
        self.expect('RESOURCE_CHANGED',lambda:sample_mesh(output,grid['eastingMinM'],grid['northingMaxM']))

    def test_prepared_mesh_owns_read_only_hashed_bytes_and_samples_without_reopening_files(self):
        output,report=self.run_validation()
        digest=hashlib.sha256((output/'report.json').read_bytes()).hexdigest()
        prepared=prepare_mesh(output,expected_report_sha256=digest)
        self.assertFalse(prepared.positions.flags.writeable);self.assertFalse(prepared.cells.flags.writeable)
        with self.assertRaises(ValueError):prepared.positions.setflags(write=True)
        with self.assertRaises(ValueError):prepared.cells.setflags(write=True)
        point=(report['mesh']['eastingMinM']+50,report['mesh']['northingMaxM']-50)
        expected=sample_mesh(output,*point,expected_report_sha256=digest)
        with patch.object(Path,'open',side_effect=AssertionError('Prepared samples must not reopen a resource')):
            for _ in range(20):self.assertEqual(prepared.sample(*point),expected)

    def test_prepared_view_cannot_follow_disk_changes_and_next_independent_sample_rejects_them(self):
        output,report=self.run_validation();digest=hashlib.sha256((output/'report.json').read_bytes()).hexdigest()
        point=(report['mesh']['eastingMinM']+50,report['mesh']['northingMaxM']-50)
        prepared=prepare_mesh(output,expected_report_sha256=digest);expected=prepared.sample(*point)
        target=output/'positions.f32';raw=bytearray(target.read_bytes());raw[0]^=1;target.write_bytes(raw)
        self.assertEqual(prepared.sample(*point),expected,'An operation owns its already-verified immutable bytes')
        self.expect('RESOURCE_CHANGED',lambda:sample_mesh(output,*point,expected_report_sha256=digest))
        self.expect('RESOURCE_CHANGED',lambda:prepare_mesh(output,expected_report_sha256=digest))

    def test_outside_mesh_and_nonfinite_coordinates_do_not_return_zero(self):
        output,report=self.run_validation()
        grid=report['mesh']
        self.expect('OUTSIDE_COVERAGE',lambda:sample_mesh(output,grid['eastingMinM']-1,grid['northingMaxM']))
        self.expect('INVALID_COORDINATE',lambda:sample_mesh(output,float('nan'),grid['northingMaxM']))


if __name__=='__main__': unittest.main()
