"""Real GIS subprocess, private files and SQLite; only authority is synthetic."""
import hashlib
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from apps.api.authority import PreviewError
from apps.api.imagery_library import ImageryLibrary
from apps.api.model_library import ModelLibrary


def image_bytes(path, *, crs='EPSG:32649', x=500000, y=3700000, dtype='uint8', bands=4):
    pixels = np.full((bands, 4, 4), 100, dtype=dtype)
    if bands == 4: pixels[3] = 255; pixels[3, 0, 0] = 0
    with rasterio.open(path, 'w', driver='GTiff', width=4, height=4, count=bands, dtype=dtype,
                       crs=crs, transform=from_origin(x, y, 10, 10)) as target:
        target.write(pixels)
        target.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue) + ((ColorInterp.alpha,) if bands == 4 else ()) if bands in (3,4) else (ColorInterp.gray,)
    return path.read_bytes()


def metadata(**changes):
    return {'clientRequestId':str(uuid4()),'displayName':'合成概览影像','sourceNote':'Synthetic imagery',
            'licenseNote':'Synthetic test fixture','attribution':'Synthetic fixture','acquiredAt':'2026-10-13',
            'qualityNote':'Not field accuracy','rightsDeclared':True,**changes}


class ImageryLibraryTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.root=Path(directory.name)
        self.models=ModelLibrary(self.root/'private','fixture-project',str(uuid4()))
        self.images=ImageryLibrary(self.models,python_executable=sys.executable)
        self.data=image_bytes(self.root/'fixture.tif')

    def upload(self, payload=None, data=None, guard=lambda:None):
        data=self.data if data is None else data
        return self.images.upload(io.BytesIO(data),len(data),payload or metadata(),'synthetic-admin',guard)

    def expect(self, code, callback):
        with self.assertRaises(PreviewError) as caught:callback()
        self.assertEqual(caught.exception.code,code)

    def test_real_rgba_mask_and_native_pixel_grid_are_preserved_without_height(self):
        value=self.upload();self.assertEqual(value['sha256'],hashlib.sha256(self.data).hexdigest())
        report=value['report'];self.assertEqual(report['pixelCornerAffine'],[10,0,500000,0,-10,3700000])
        self.assertEqual(report['validPixels'],15);self.assertEqual(report['transparentPixels'],1)
        self.assertFalse(report['heightDataUsed']);self.assertFalse(report['fieldAccuracyVerified'])
        content=self.images.content(value['imageryVersionId'],value['contentRevision'],value['texture']['sha256'],lambda:None)
        with MemoryFile(content) as memory, memory.open() as png:
            self.assertEqual(png.read(4)[0,0],0);self.assertTrue((png.read((1,2,3))[:,0,0]==0).all())
            self.assertEqual(png.read(1)[1,1],100)
        self.assertNotIn(str(self.root),str(value));self.assertEqual(list((self.images.root/'temporary').iterdir()),[])

    def test_replay_checks_actor_payload_and_actual_bytes_without_duplicate_audit(self):
        payload=metadata();first=self.upload(payload)
        self.assertEqual(self.upload(payload)['imageryVersionId'],first['imageryVersionId'])
        self.expect('REQUEST_CONFLICT',lambda:self.upload({**payload,'displayName':'Changed'}))
        self.expect('REQUEST_CONFLICT',lambda:self.upload(payload,data=self.data[:-1]+bytes([self.data[-1]^1])))
        with self.models.connect() as db:
            self.assertEqual(db.execute('select count(*) from imagery_versions').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from imagery_audit').fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):db.execute("update imagery_versions set name='changed'")

    def test_unsupported_dtypes_bands_and_vrt_are_rejected_and_leave_no_output(self):
        for data in (image_bytes(self.root/'sixteen.tif',dtype='uint16'),image_bytes(self.root/'gray.tif',bands=1),
                     b'<VRTDataset rasterXSize="4" rasterYSize="4"></VRTDataset>'):
            self.expect('UNSUPPORTED_IMAGERY',lambda:self.upload(data=data))
        self.assertEqual(list((self.images.root/'versions').iterdir()),[])
        self.assertEqual(list((self.images.root/'temporary').iterdir()),[])

    def test_late_permission_loss_rolls_back_and_cleans_published_directory(self):
        calls=0
        def guard():
            nonlocal calls
            calls+=1
            if calls>=4:raise PreviewError(403,'IMAGERY_WRITE_FORBIDDEN')
        self.expect('IMAGERY_WRITE_FORBIDDEN',lambda:self.upload(guard=guard))
        with self.models.connect() as db:self.assertEqual(db.execute('select count(*) from imagery_versions').fetchone()[0],0)
        self.assertEqual(list((self.images.root/'versions').iterdir()),[])

    def test_revocation_is_checked_on_list_version_content_and_replay(self):
        payload=metadata();value=self.upload(payload)
        def deny():raise PreviewError(403,'FORBIDDEN')
        for action in (lambda:self.images.listing(deny),lambda:self.images.version(value['imageryVersionId'],deny),
                       lambda:self.images.content(value['imageryVersionId'],value['contentRevision'],value['texture']['sha256'],deny),
                       lambda:self.upload(payload,guard=deny)):
            self.expect('FORBIDDEN',action)

    def test_partial_overlap_is_allowed_but_no_intersection_or_changed_fixed_resource_is_refused(self):
        value=self.upload();reference={'imageryVersionId':value['imageryVersionId'],'expectedContentRevision':value['contentRevision'],
            'expectedReportSha256':value['expectedReportSha256'],'visible':False}
        bounds=value['report']['coverageWgs84'];terrain={'report':{'source':{'samplingCentreCoverageWgs84':bounds}}}
        self.images.validate_scene(reference,terrain,lambda:None)
        self.expect('RESOURCE_CHANGED',lambda:self.images.validate_scene({**reference,'expectedContentRevision':'changed'},terrain,lambda:None))
        terrain['report']['source']['samplingCentreCoverageWgs84']=[120,40,121,41]
        self.expect('IMAGERY_OUTSIDE_TERRAIN',lambda:self.images.validate_scene(reference,terrain,lambda:None))
        path=self.images.root/'versions'/value['imageryVersionId']/'texture.png';data=path.read_bytes();path.write_bytes(data[:-1]+bytes([data[-1]^1]))
        self.expect('RESOURCE_CHANGED',lambda:self.images.content(value['imageryVersionId'],value['contentRevision'],value['texture']['sha256'],lambda:None))

    def test_busy_rejects_before_reading_upload_and_declarations_are_strict(self):
        class NeverRead:
            def read(self,*_):raise AssertionError('Busy uploads must not be read')
        self.images.lock.acquire()
        try:self.expect('IMAGERY_BUSY',lambda:self.images.upload(NeverRead(),100,metadata(),'actor',lambda:None))
        finally:self.images.lock.release()
        self.expect('IMAGERY_RIGHTS_REQUIRED',lambda:self.upload(metadata(rightsDeclared=False)))
        self.expect('INVALID_REQUEST',lambda:self.upload(metadata(acquiredAt='2026-02-30')))

    def test_real_database_lock_returns_retryable_error_without_writes(self):
        with self.models.connect() as locker:
            locker.execute('begin exclusive')
            self.expect('IMAGERY_STORAGE_BUSY',lambda:self.images.listing(lambda:None))
        self.assertEqual(self.images.listing(lambda:None)['items'],[])


if __name__=='__main__':unittest.main()
