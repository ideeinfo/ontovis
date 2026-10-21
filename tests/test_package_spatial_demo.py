from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from tools.package_spatial_demo import FILES, package


class SpatialPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/'source'
        self.output = self.root/'delivery'/'bundle'
        for name in FILES:
            path=self.source/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'{}' if name.endswith('.json') else b'synthetic-content')
        (self.source/'data/turbines.geojson').write_text('{}')

    def build(self):
        return package(self.source,self.output,'Synthetic authorization for test assets')

    def test_only_approved_files_and_public_summaries_are_exported(self):
        for name in ['_work/private.txt','session-manifest.json','assets/models/tu3000-geared-original.glb','sources/private-audit.json']:
            path=self.source/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('private input')
        result=self.build()
        files={str(path.relative_to(self.output)) for path in self.output.rglob('*') if path.is_file()}
        self.assertEqual(files,set(result['files'])|{'release.json'})
        self.assertNotIn('session-manifest.json',files)
        self.assertNotIn('assets/models/tu3000-geared-original.glb',files)
        self.assertFalse(result['engineeringServiceConnected'])

    def test_release_hashes_match_every_exported_artifact(self):
        result=self.build()
        for name,row in result['files'].items():
            data=(self.output/name).read_bytes()
            self.assertEqual(row,{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        self.assertEqual(result,json.loads((self.output/'release.json').read_text()))

    def test_model_authorization_records_assertion_without_open_license(self):
        self.build()
        value=json.loads((self.output/'sources/model-authorization.json').read_text())
        self.assertEqual(value['evidenceStatus'],'user_statement_recorded_reference_pending')
        self.assertFalse(value['openLicenseClaimed'])
        self.assertEqual(len(value['artifacts']),2)

    def test_missing_authorization_is_refused_before_creating_output(self):
        with self.assertRaises(ValueError): package(self.source,self.output,' ')
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_replaced(self):
        self.output.mkdir(parents=True)
        sentinel=self.output/'keep'
        sentinel.write_text('keep')
        with self.assertRaises(FileExistsError): self.build()
        self.assertEqual(sentinel.read_text(),'keep')

    def test_missing_required_runtime_file_is_refused(self):
        (self.source/'app.js').unlink()
        with self.assertRaisesRegex(ValueError,'app.js'): self.build()
        self.assertFalse(self.output.exists())

    def test_symlink_cannot_include_an_unreviewed_file(self):
        path=self.source/'app.js'
        path.unlink()
        target=self.root/'private.js'
        target.write_text('private')
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'app.js'): self.build()

    def test_private_paths_are_refused(self):
        (self.source/'data/turbines.geojson').write_text('{"path":"/Users/example/private"}')
        with self.assertRaisesRegex(ValueError,'Local/private path'): self.build()
        self.assertFalse(self.output.exists())

    def test_public_copy_explains_disconnected_engineering_service(self):
        (self.source/'index.html').write_text('本机数据包')
        (self.source/'authority-preview.js').write_text('本机登录会话尚未启动。此页没有可读取的安装对象。')
        self.build()
        self.assertEqual((self.output/'index.html').read_text(),'测试数据包')
        self.assertIn('工程服务尚未连接',(self.output/'authority-preview.js').read_text())

    def test_session_bundle_uses_maintained_modules_without_private_manifest(self):
        (self.source/'index.html').write_text('<link rel="stylesheet" href="./styles.css">')
        result = package(self.source,self.output,'Synthetic authorization',user_sessions=True)
        self.assertEqual(result['engineeringSessionMode'],'per_user')
        self.assertIn('session.css',(self.output/'index.html').read_text())
        self.assertIn("./session.js",(self.output/'authority-preview.js').read_text())
        self.assertNotIn('session-manifest.json',result['files'])
        self.assertIn('credentials:',(self.output/'session.js').read_text())

    def test_current_locations_summary_follows_dataset_without_renumbering(self):
        locations = {'metadata':{'currentTurbineCount':2,'excludedPlanLabels':['2','3']},
                     'features':[{'properties':{'label':'1'}},{'properties':{'label':'4'}}]}
        (self.source/'data/turbines.geojson').write_text(json.dumps(locations))
        self.build()
        self.assertIn('当前保留2个图示机位',(self.output/'README.md').read_text())
        self.assertEqual(json.loads((self.output/'data/turbines.geojson').read_text()), locations)

    def test_entry_and_module_graph_change_version_between_frontend_releases(self):
        (self.source/'index.html').write_text('<script src="./app.js"></script><link rel="stylesheet" href="./styles.css">')
        (self.source/'app.js').write_text("import { InstallationAuthorityPanel } from './authority-preview.js';")
        first=package(self.source,self.output,'Synthetic authorization',user_sessions=True)
        version=first['frontendVersion']
        self.assertIn('app.js?v='+version,(self.output/'index.html').read_text())
        self.assertIn('authority-preview.js?v='+version,(self.output/'app.js').read_text())
        self.assertIn('session.js?v='+version,(self.output/'authority-preview.js').read_text())
        (self.source/'app.js').write_text((self.source/'app.js').read_text()+'\n// changed frontend\n')
        second=package(self.source,self.output.parent/'second','Synthetic authorization',user_sessions=True)
        self.assertNotEqual(version,second['frontendVersion'])


if __name__ == '__main__':
    unittest.main()
