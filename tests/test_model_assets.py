import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from apps.api.authority import PreviewError
from apps.api.model_assets import ModelAsset

class ModelAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.document={'asset':{'version':'2.0'},'buffers':[{'byteLength':0}],'images':[]}
        self.config={'schemaVersion':1,'projectCode':'fixture','installationContextId':'context','rootEntityUid':'root','bindings':[
            {'entityUid':key,'entityRevision':'r1','componentKey':key,'geometryQuality':'source_candidate' if key=='CN' else 'proxy_schematic','bounds':[[0,0,0],[1,2,1]]} for key in ('CT','CN','CN1')]}
        self.write()
    def write(self):
        raw=json.dumps(self.document).encode();raw+=b' '*(-len(raw)%4)
        content=struct.pack('<4sIIII',b'glTF',2,20+len(raw),len(raw),0x4e4f534a)+raw
        (self.root/'model.glb').write_bytes(content);self.config['sha256']=hashlib.sha256(content).hexdigest()
        (self.root/'model.json').write_text(json.dumps(self.config))
    def load(self):return ModelAsset(self.root,'fixture','context')
    def objects(self):return [{'resolution':'exact','object':{'entityUid':key,'entityRevision':'r1','installationContextId':'context','objectKind':'cabinet','lifecycle':'active'}} for key in ('CT','CN','CN1')]
    def context(self):return {'purpose':'demonstration','engineeringUseAllowed':False,'rootEntityUid':'root','installationContextId':'context'}
    def test_metadata_preserves_unverified_quality_and_excludes_private_configuration(self):
        data=self.load().metadata(self.objects(),self.context());self.assertFalse(data['engineeringUseAllowed']);self.assertEqual(len(data['bindings']),3);self.assertNotIn('licenceBasis',data)
    def test_an_external_resource_is_never_loaded_by_the_browser(self):
        self.document['images']=[{'uri':'https://example.invalid/track.png'}];self.write()
        with self.assertRaises(ValueError):self.load()
    def test_replaced_glb_cannot_be_read_using_the_old_fingerprint(self):
        asset=self.load();(self.root/'model.glb').write_bytes(b'changed')
        with self.assertRaises(PreviewError) as caught:asset.content()
        self.assertEqual(caught.exception.code,'MODEL_CHANGED')
    def test_changed_identity_revision_or_context_refuses_the_mapping(self):
        for field,value in [('entityRevision','r2'),('installationContextId','foreign'),('lifecycle','merged'),('objectKind','unknown')]:
            rows=self.objects();rows[0]['object'][field]=value
            with self.subTest(field=field),self.assertRaises(PreviewError):self.load().metadata(rows,self.context())
    def test_demonstration_cannot_be_promoted_or_moved_to_a_different_root(self):
        for field,value in [('purpose','engineering'),('engineeringUseAllowed',True),('rootEntityUid','foreign')]:
            with self.subTest(field=field),self.assertRaises(PreviewError):self.load().metadata(self.objects(),{**self.context(),field:value})
    def test_ambiguous_mapping_and_nonfinite_bounds_fail_configuration(self):
        self.config['bindings'][0]['bounds'][0][0]=float('nan');self.write()
        with self.assertRaises(ValueError):self.load()
