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
        routes = [path for paths in groups.values() for path in paths] + list(legacy)
        for path in routes:
            with self.subTest(path=path):
                body = location_for(path)
                self.assertIn('client_max_body_size ' + ('1m' if path in large else '16k') + ';', body)
                self.assertIn('proxy_buffering off;', body)
                if path.startswith('/api/workbench/scenes'):
                    self.assertIn('proxy_read_timeout 120s;', body)
        for path in ('/api/workbench/models/upload', '/api/workbench/resources/model/upload'):
            body = location_for(path)
            self.assertIn('client_max_body_size 20m;', body)
            self.assertIn('proxy_request_buffering off;', body)
        for path in ('/api/workbench/scenes/delete', '/api/workbench/resources/secret',
                     '/api/workbench/terrains/upload/extra', '/api/workbench/scenes/open/',
                     '/api/workbench/imagery/delete', '/api/workbench/imagery/upload/extra',
                     '/api/workbench/imagery/content/'):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                location_for(path)

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
                            'RestrictAddressFamilies=AF_INET AF_UNIX', 'TasksMax=64', 'LimitNOFILE=256'):
            self.assertIn(restriction, service)
        self.assertIn('location ^~ /api/demo/ { default_type application/json; return 410', nginx)
        for path in ('data', 'sources', 'models', 'textures'):
            self.assertIn('location /' + path + '/ { return 404; }', nginx)
        self.assertIn('location /api/ { return 404; }', nginx)


if __name__ == '__main__':
    unittest.main()
