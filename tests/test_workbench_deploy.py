"""Deployment boundaries for the implemented same-origin workbench routes."""
import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def proxy_locations():
    text = (ROOT / 'deploy/nginx-workbench.conf').read_text()
    return [(kind, path, body) for kind, path, body in
        re.findall(r'location\s+(=|~)\s+(\S+)\s*\{([^{}]*)\}', text)
        if 'proxy_pass http://127.0.0.1:18084;' in body]


def location_for(path):
    matches = [(kind, pattern, body) for kind, pattern, body in proxy_locations()
        if kind == '=' and path == pattern]
    if not matches:
        matches = [(kind, pattern, body) for kind, pattern, body in proxy_locations()
            if kind == '~' and re.search(pattern, path)]
    if len(matches) != 1:
        raise AssertionError(f'Expected one explicit proxy location for {path}: {len(matches)}')
    return matches[0][2]


class WorkbenchDeploymentTests(unittest.TestCase):
    def test_json_reads_are_compressed_without_enabling_api_caching(self):
        nginx = (ROOT / 'deploy/nginx-workbench.conf').read_text()
        self.assertIn('application/json', re.search(r'gzip_types\s+([^;]+);', nginx)[1].split())
        self.assertIn('gzip_vary on;', nginx)
        self.assertIn('default "no-store";', nginx)
        self.assertNotIn('proxy_cache ', nginx)

    def test_scene_delete_restore_are_bounded_and_purge_is_not_exposed(self):
        for action in ('delete', 'restore'):
            body = location_for('/api/workbench/scenes/'+action)
            self.assertIn('client_max_body_size 16k;', body)
            self.assertIn('proxy_read_timeout 120s;', body)
        for action in ('purge', 'delete/extra', 'restore/extra', 'restore/'):
            with self.assertRaises(AssertionError):location_for('/api/workbench/scenes/'+action)

    def test_analysis_drafts_have_bounded_routes_without_conclusion_or_sharing(self):
        for suffix in ('', '/create', '/save', '/detail', '/restore', '/revisions', '/trash', '/untrash'):
            body = location_for('/api/workbench/analysis-sessions'+suffix)
            self.assertIn('client_max_body_size '+('264k' if suffix in ('/create', '/save') else '16k')+';', body)
            self.assertIn('proxy_buffering off;', body)
        for suffix in ('/confirm', '/archive', '/share', '/purge', '/trash/extra', '/untrash/extra', '/save/extra', '/'):
            with self.assertRaises(AssertionError): location_for('/api/workbench/analysis-sessions'+suffix)

    def test_analysis_source_preparation_and_fixed_work_order_routes_are_exact(self):
        root = '/api/workbench/analysis-sessions/'
        for suffix in ('evidence/register', 'evidence/detail', 'evidence/content', 'link-work-order', 'simulation/catalogue', 'simulation/detail', 'simulation/qualify'):
            self.assertIn('client_max_body_size 16k;', location_for(root+suffix))
            for extra in ('/', '/extra'):
                with self.assertRaises(AssertionError): location_for(root+suffix+extra)
        self.assertIn('client_max_body_size 16k;', location_for('/api/workbench/work-orders/snapshot'))

    def test_canvas_routes_allow_bounded_snapshots_and_batches_only(self):
        root='/api/workbench/analysis-sessions/'
        large=('copy','import-history','evidence/register-batch')
        for suffix in (*large,'start','recommendations','history-candidates','evidence/batch','evidence/preview','evidence/relationships','evidence/preview-content'):
            self.assertIn('client_max_body_size '+('264k' if suffix in large else '16k')+';',location_for(root+suffix))
            for extra in ('/','/extra'):
                with self.assertRaises(AssertionError):location_for(root+suffix+extra)

    def test_only_successful_content_named_public_assets_are_cacheable(self):
        nginx = (ROOT / 'deploy/nginx-workbench.conf').read_text()
        block = nginx.split('map "$status:$uri" $ontovis_public_asset_cache_control {', 1)[1].split('\n}', 1)[0]
        self.assertIn('default "no-store";', block)
        rules = re.findall(r'"~([^"]+)"\s+"([^"]+)";', block)
        self.assertEqual(len(rules), 2)
        def policy(status, path):
            return next((value for pattern, value in rules if re.search(pattern, f'{status}:{path}')), 'no-store')
        assets = ('/assets/ONTOVis--04A_0H2.png', '/assets/index-CUFv3qG2.js',
                  '/assets/index-D70I8gPp.css', '/media/login-background-faa5494a30c25cb1.mp4',
                  '/media/login-background-poster-b484ba1164cbfbc5.webp')
        for path in assets:
            for status in (200, 206, 304):
                self.assertEqual(policy(status, path), 'public, max-age=31536000, immutable')
            for status in (301, 401, 403, 404, 500):
                self.assertEqual(policy(status, path), 'no-store')
        for path in ('/', '/index.html', '/health.json', '/api/session',
                     '/api/workbench/objects/photos/content', '/api/workbench/resources/model/content',
                     '/assets/current.js', '/assets/private/index-CUFv3qG2.js',
                     '/media/current.mp4', '/models/index-CUFv3qG2.js'):
            self.assertEqual(policy(200, path), 'no-store')
        # Keep all security headers at server scope; a location override would drop them.
        self.assertIn('add_header Cache-Control $ontovis_public_asset_cache_control always;', nginx)
        self.assertEqual(nginx.count('add_header Cache-Control'), 1)

    def test_embedded_model_images_can_be_fetched_without_allowing_external_connections(self):
        nginx = (ROOT / 'deploy/nginx-workbench.conf').read_text()
        policies = re.findall(r'add_header Content-Security-Policy "([^"]+)" always;', nginx)
        self.assertEqual(len(policies), 1)
        directives = {}
        for directive in policies[0].split(';'):
            tokens = directive.split()
            if tokens:
                self.assertNotIn(tokens[0], directives)
                directives[tokens[0]] = set(tokens[1:])
        # Three's ImageBitmapLoader uses fetch(blob:), governed by connect-src, not img-src.
        self.assertEqual(directives['connect-src'], {"'self'", 'blob:'})
        self.assertTrue({"'self'", 'blob:', 'data:'}.issubset(directives['img-src']))
        for name in ('default-src', 'script-src', 'media-src', 'base-uri'):
            self.assertEqual(directives[name], {"'self'"})
        for name in ('object-src', 'frame-ancestors'):
            self.assertEqual(directives[name], {"'none'"})

    def test_every_implemented_route_has_the_matching_bounded_proxy_location(self):
        tree = ast.parse((ROOT / 'apps/api/session_http.py').read_text())
        groups = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ('workbench_paths', 'scene_paths', 'scene_object_paths', 'terrain_paths', 'imagery_paths', 'resource_paths'):
                    groups[name] = ast.literal_eval(node.value)
        self.assertEqual(len(groups), 6)
        legacy = tuple('/api/workbench/scenes/legacy-migration/' + action for action in ('sources', 'check', 'activate', 'entry'))
        large = {'/api/workbench/scenes/' + action for action in ('save', 'check', 'replacement-check')}
        large.update('/api/workbench/scenes/legacy-migration/' + action for action in ('check', 'activate'))
        orders = tuple('/api/workbench/work-orders' + suffix for suffix in ('', '/seed-demo', '/detail', '/action', '/locate', '/diagnosis-history'))
        routes = [path for paths in groups.values() for path in paths] + list(legacy) + list(orders)
        for path in routes:
            with self.subTest(path=path):
                body = location_for(path)
                limit = '1m' if path in large else '72k' if path.endswith('/model/metadata/save') else '32k' if path.endswith('/work-orders/action') else '16k'
                self.assertIn('client_max_body_size ' + limit + ';', body)
                self.assertIn('proxy_buffering off;', body)
                if path.startswith('/api/workbench/scenes'):
                    self.assertIn('proxy_read_timeout 120s;', body)
        for path in ('/api/workbench/models/upload', '/api/workbench/resources/model/upload'):
            body = location_for(path)
            self.assertIn('client_max_body_size 20m;', body)
            self.assertIn('proxy_request_buffering off;', body)
        for path in ('/api/workbench/scenes/purge', '/api/workbench/resources/secret',
                     '/api/workbench/terrains/upload/extra', '/api/workbench/scenes/open/',
                     '/api/workbench/imagery/delete', '/api/workbench/imagery/upload/extra',
                     '/api/workbench/imagery/upload-result/extra',
                     '/api/workbench/imagery/uploads/chunk/extra', '/api/workbench/imagery/uploads/status/extra',
                     '/api/workbench/imagery/content/', '/api/workbench/resources/model/metadata/extra',
                     '/api/workbench/resources/model/inspection/extra', '/api/workbench/resources/model/inspection/',
                     '/api/workbench/resources/model/thumbnail/extra', '/api/workbench/resources/model/thumbnail/content/',
                     '/api/workbench/resources/model/thumbnail/ensure/extra',
                     '/api/workbench/resources/model/metadata/save/extra', '/api/workbench/resources/model/metadata/save/',
                     '/api/workbench/resources/model/info/save/extra', '/api/workbench/resources/model/info/save/',
                     '/api/workbench/resources/model/delete/extra', '/api/workbench/resources/model/restore/extra',
                     '/api/workbench/resources/model/delete/', '/api/workbench/resources/model/restore/', '/api/workbench/resources/model/purge',
                     '/api/workbench/work-orders/diagnosis-history/extra', '/api/workbench/work-orders/diagnosis-history/',
                     '/api/workbench/work-orders/action/extra', '/api/workbench/work-orders/action/'):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                location_for(path)

    def test_metadata_save_has_its_own_exact_json_limit_without_expanding_model_uploads(self):
        from apps.api.model_resource_metadata import MAX_METADATA_REQUEST_BYTES
        read = location_for('/api/workbench/resources/model/metadata')
        save = location_for('/api/workbench/resources/model/metadata/save')
        self.assertIn('client_max_body_size 16k;', read)
        self.assertEqual(MAX_METADATA_REQUEST_BYTES, 72 * 1024)
        self.assertIn('client_max_body_size 72k;', save)
        self.assertIn('proxy_buffering off;', save)
        self.assertIn('client_max_body_size 20m;', location_for('/api/workbench/resources/model/upload'))

    def test_public_acquisition_routes_are_exact_short_json_requests(self):
        for action in ('start', 'job', 'cancel'):
            body = location_for('/api/workbench/public-geodata/' + action)
            self.assertIn('client_max_body_size 16k;', body)
            self.assertIn('proxy_read_timeout 30s;', body)
            self.assertIn('proxy_buffering off;', body)
        for path in ('/api/workbench/public-geodata', '/api/workbench/public-geodata/download',
                     '/api/workbench/public-geodata/job/extra', '/api/workbench/public-geodata/start/'):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                location_for(path)

    def test_imagery_upload_has_the_same_bounded_limit_as_its_processor(self):
        from apps.api.imagery_validation import MAX_BYTES
        body = location_for('/api/workbench/imagery/upload')
        self.assertIn(f'client_max_body_size {MAX_BYTES};', body)
        self.assertIn('client_body_timeout 30s;', body)
        self.assertIn('proxy_read_timeout 60s;', body)
        self.assertIn('proxy_request_buffering off;', body)
        self.assertIn('proxy_buffering off;', body)

    def test_imagery_parts_have_separate_exact_bounded_proxy_locations(self):
        from apps.api.imagery_uploads import CHUNK_BYTES
        body=location_for('/api/workbench/imagery/uploads/chunk')
        self.assertIn(f'client_max_body_size {CHUNK_BYTES};',body)
        self.assertIn('proxy_request_buffering on;',body)
        self.assertIn('client_body_buffer_size 128k;',body)
        self.assertIn('client_body_timeout 30s;',body)
        for action in ('start','status','complete','cancel'):
            self.assertIn('client_max_body_size 16k;',location_for('/api/workbench/imagery/uploads/'+action))

    def test_terrain_service_and_proxy_share_exact_deployment_limit_and_trusted_runtime(self):
        nginx = (ROOT / 'deploy/nginx-workbench.conf').read_text()
        service = (ROOT / 'deploy/ontovis-workbench.service').read_text()
        terrain = location_for('/api/workbench/terrains/upload')
        self.assertIn('client_max_body_size 100000000;', terrain)
        self.assertIn('proxy_request_buffering off;', terrain)
        self.assertIn('proxy_buffering off;', terrain)
        self.assertIn('large_client_header_buffers 4 16k;', nginx)
        self.assertIn('ExecStart=/data/ontovis/runtime/gis-current/bin/python ', service)
        self.assertIn('--terrain-python /data/ontovis/runtime/gis-current/bin/python', service)
        self.assertIn('--terrain-max-upload-bytes 100000000', service)
        self.assertIn('MemoryMax=1536M', service)
        self.assertNotIn('IPAddressDeny=', service)
        self.assertNotIn('IPAddressAllow=', service)
        for restriction in ('User=ontovis', 'NoNewPrivileges=true', 'ProtectSystem=strict',
                            'ProtectHome=true', 'PrivateTmp=true', 'CapabilityBoundingSet=',
                            'RestrictAddressFamilies=AF_INET AF_UNIX', 'TasksMax=192', 'LimitNOFILE=256'):
            self.assertIn(restriction, service)
        self.assertIn('--thumbnail-renderer /data/ontovis/workbench-current/public/model-thumbnail-renderer.js', service)
        self.assertIn('--thumbnail-node /usr/local/bin/node --thumbnail-browser /opt/google/chrome/chrome', service)
        self.assertIn('location ^~ /api/demo/ { default_type application/json; return 410', nginx)
        for path in ('data', 'sources', 'models', 'textures', 'thumbnails'):
            self.assertIn('location /' + path + '/ { return 404; }', nginx)
        self.assertIn('location /api/ { return 404; }', nginx)


if __name__ == '__main__':
    unittest.main()
