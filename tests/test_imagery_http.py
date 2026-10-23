"""Actual session HTTP -> imagery/GIS -> scene revision retention."""
import base64
import copy
import hashlib
import json
import unittest
from uuid import uuid4

import tests.test_scene_spatial_http as spatial
from tests.test_imagery_library import image_bytes,metadata


class ImageryHttpTests(unittest.TestCase):
    def upload_image(self, *, client=None, data=None, payload=None, headers=None):
        client=self.admin if client is None else client
        payload={**(payload or metadata()),'expectedSessionRevision':client['revision']}
        return self.request('/api/workbench/imagery/upload',client=client,
            raw=data if data is not None else image_bytes(self.root/'imagery.tif'),
            headers={'Content-Type':'image/tiff','X-Imagery-Metadata':base64.b64encode(json.dumps(payload).encode()).decode(),**(headers or {})})

    def test_upload_content_no_store_reader_and_revocation(self):
        status,value,headers=self.upload_image();self.assertEqual(status,200,value);self.assertEqual(headers['Cache-Control'],'no-store')
        body={'imageryVersionId':value['imageryVersionId'],'expectedContentRevision':value['contentRevision'],'expectedSha256':value['texture']['sha256']}
        status,content,headers=self.request('/api/workbench/imagery/content',body)
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'image/png');self.assertEqual(headers['X-Content-SHA256'],hashlib.sha256(content).hexdigest())
        reader=self.login('synthetic-reader');self.authority(reader).role='reader'
        self.assertEqual(self.request('/api/workbench/imagery',client=reader)[0],200)
        self.assertEqual(self.request('/api/workbench/imagery/content',body,client=reader)[0],200)
        status,error,_=self.upload_image(client=reader);self.assertEqual((status,error['code']),(403,'IMAGERY_WRITE_FORBIDDEN'))
        self.authority(reader).allowed=False
        self.assertEqual(self.request('/api/workbench/imagery/content',body,client=reader)[0],403)
        self.assertEqual(self.request('/api/workbench/imagery/content',body,client=False)[0],401)

    def test_scene_history_pins_image_and_retains_references_when_hidden_replaced_or_removed(self):
        scene=self.anchored();status,image,_=self.upload_image();self.assertEqual(status,200,image)
        snapshot=copy.deepcopy(scene['snapshot']);snapshot['imagery']={'imageryVersionId':image['imageryVersionId'],
            'expectedContentRevision':image['contentRevision'],'expectedReportSha256':image['expectedReportSha256'],'visible':True}
        # A four-pixel fixture covers the NW corner of the 32x32 terrain only.
        status,checked,_=self.check(self.validate_body(scene,snapshot));self.assertEqual(status,200,checked)
        self.assertEqual(checked['proposedSnapshot']['instances'],scene['snapshot']['instances'])
        body=self.save_body(scene,checked['proposedSnapshot']);status,saved,_=self.save(body);self.assertEqual(status,200,saved)
        self.assertEqual(self.save(body)[1]['sceneRevision'],saved['sceneRevision'])
        pinned=self.opened(scene);self.assertEqual(pinned['snapshot']['imagery'],snapshot['imagery'])
        self.assertNotIn('imagery',self.opened(scene,scene['sceneRevision'])['snapshot'])
        status,second,_=self.upload_image(payload=metadata(displayName='Synthetic replacement',acquiredAt='2026-10-14'));self.assertEqual(status,200,second)
        replaced=copy.deepcopy(pinned['snapshot']);replaced['imagery']={'imageryVersionId':second['imageryVersionId'],
            'expectedContentRevision':second['contentRevision'],'expectedReportSha256':second['expectedReportSha256'],'visible':True}
        status,newer,_=self.save(self.save_body(pinned,replaced));self.assertEqual(status,200,newer)
        replacement=self.opened(scene);self.assertEqual(replacement['snapshot']['instances'],scene['snapshot']['instances'])
        hidden=copy.deepcopy(replacement['snapshot']);hidden['imagery']['visible']=False
        status,newer,_=self.save(self.save_body(replacement,hidden));self.assertEqual(status,200,newer)
        removed=self.opened(scene);removed_snapshot=copy.deepcopy(removed['snapshot']);removed_snapshot['imagery']=None
        self.assertEqual(self.save(self.save_body(removed,removed_snapshot))[0],200)
        self.assertTrue(self.opened(scene,pinned['sceneRevision'])['snapshot']['imagery']['visible'])
        with self.sessions.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from scene_imagery_uses').fetchone()[0],3)
            self.assertEqual(db.execute('select count(distinct imagery_version_id) from scene_imagery_uses').fetchone()[0],2)

    def test_local_reference_unknown_revision_no_overlap_and_bad_header_do_not_advance_head(self):
        scene=self.anchored();status,image,_=self.upload_image(data=image_bytes(self.root/'outside.tif',x=800000,y=4000000));self.assertEqual(status,200,image)
        image_ref={'imageryVersionId':image['imageryVersionId'],'expectedContentRevision':image['contentRevision'],
            'expectedReportSha256':image['expectedReportSha256'],'visible':True}
        proposed={**scene['snapshot'],'imagery':image_ref}
        status,error,_=self.check(self.validate_body(scene,proposed));self.assertEqual((status,error['code']),(409,'IMAGERY_OUTSIDE_TERRAIN'))
        proposed['imagery']={**image_ref,'expectedContentRevision':'old'}
        self.assertEqual(self.check(self.validate_body(scene,proposed))[1]['code'],'RESOURCE_CHANGED')
        local=self.local_scene();local_snapshot={**local['snapshot'],'imagery':image_ref}
        self.assertEqual(self.save(self.save_body(local,local_snapshot))[0],422)
        self.assertEqual(self.opened(scene)['sceneRevision'],scene['sceneRevision'])
        self.assertEqual(self.upload_image(headers={'X-Imagery-Metadata':'not-base64'})[0],422)
        self.assertEqual(self.upload_image(headers={'Origin':'http://invalid.example'})[0],403)


for name in ('setUp','request','login','authority','listing','metadata','upload','new_version','calibration','calibrate','expect',
             'lonlat','terrain','item','save_body','save','opened','local_scene','anchor_body','check','checked','anchored','validate_body'):
    setattr(ImageryHttpTests,name,getattr(spatial.SceneSpatialHttpTests,name))


if __name__=='__main__':unittest.main()
