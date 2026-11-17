"""Metadata routes retain model-resource HTTP permission and session boundaries."""
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.model_resource_metadata import MAX_METADATA_REQUEST_BYTES
from tests import test_project_model_http as project
from tests.test_model_resource_metadata import record


READ = '/api/workbench/resources/model/metadata'
SAVE = READ + '/save'


class ModelResourceMetadataHttpTests(unittest.TestCase):
    def setUp(self):
        self.http = project.ProjectModelHttpTests()
        self.http.setUp(); self.addCleanup(self.http.doCleanups)
        self.version = self.http.new_version()
        self.ids = {key: self.version[key] for key in ('modelAssetId', 'modelVersionId')}

    def body(self, **changes):
        return {**self.ids, 'expectedMetadataRevision': None, 'clientRequestId': str(uuid4()),
                'metadata': record(), **changes}

    def test_read_and_save_are_private_no_store_and_do_not_append_geometry_versions(self):
        original = self.http.listing()[1]
        status, value, headers = self.http.request(READ, self.ids)
        self.assertEqual((status, value['item'], headers['Cache-Control']), (200, None, 'no-store'))
        self.assertTrue(value['capabilities']['canWriteMetadata'])
        self.assertEqual(value['limits']['maxResourceMetadataRequestBytes'], MAX_METADATA_REQUEST_BYTES)
        status, saved, headers = self.http.request(SAVE, self.body())
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved['item']['metadata'], record())
        self.assertEqual(saved['item']['modelSha256'], self.version['sha256'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.http.request(READ, self.ids)[1]['item'], saved['item'])
        self.assertEqual(self.http.listing()[1], original)
        self.assertEqual(self.http.model(self.version)[0], 200)

    def test_readers_can_read_but_not_save_and_denied_sessions_receive_no_metadata(self):
        saved = self.http.request(SAVE, self.body())[1]['item']
        reader = self.http.login('fixture-reader'); self.http.authority(reader).role = 'reader'
        status, value, _ = self.http.request(READ, self.ids, client=reader)
        self.assertEqual((status, value['item']), (200, saved))
        self.assertFalse(value['capabilities']['canWriteMetadata'])
        self.http.expect(self.http.request(SAVE, self.body(), client=reader), 403, 'MODEL_WRITE_FORBIDDEN')
        self.http.authority(reader).allowed = False
        self.http.expect(self.http.request(READ, self.ids, client=reader), 403, 'FORBIDDEN')
        self.http.expect(self.http.request(READ, self.ids, client=False), 401, 'SESSION_EXPIRED')
        self.http.expect(self.http.request(SAVE, self.body(), client=False), 401, 'SESSION_EXPIRED')

    def test_origin_session_revision_and_fixed_url_guards_apply_to_both_paths(self):
        for path, body in ((READ, self.ids), (SAVE, self.body())):
            self.http.expect(self.http.request(path, body, headers={'Origin': 'https://attacker.test'}), 403, 'FORBIDDEN')
            self.http.expect(self.http.request(path, body, headers={'Origin': None}), 403, 'FORBIDDEN')
            self.http.expect(self.http.request(path, {**body, 'expectedSessionRevision': 'stale'}), 409, 'SESSION_CHANGED')
            self.http.expect(self.http.request(path, body, headers={'Sec-Fetch-Site': 'cross-site'}), 403, 'FORBIDDEN')
            self.http.expect(self.http.request(path + '?modelAssetId=x', body), 404, 'NOT_FOUND')
            self.http.expect(self.http.request(path, method='GET'), 404, 'NOT_FOUND')

    def test_large_but_bounded_source_record_uses_its_own_json_limit(self):
        body = self.body(); body['metadata']['modelBasis']['rawText'] = 'a' * 15000
        body['metadata']['modelBasis']['summary'] = 'b' * 3000
        self.assertGreater(len(json.dumps(body).encode()), 16384)
        status, saved, _ = self.http.request(SAVE, body)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved['item']['metadata'], body['metadata'])
        self.http.expect(self.http.request(SAVE, raw=b' ' * (MAX_METADATA_REQUEST_BYTES + 1)), 413, 'INVALID_REQUEST')
        self.http.expect(self.http.request(READ, raw=b' ' * 16385), 413, 'INVALID_REQUEST')

    def test_unknown_keys_duplicates_and_nonfinite_input_are_rejected_without_writes(self):
        for body in (self.body(extra='no'), self.body(modelAssetId=str(uuid4())), self.body(modelVersionId=str(uuid4()))):
            status, value, _ = self.http.request(SAVE, body)
            self.assertIn(status, (404, 422), value)
        invalid = self.body(); invalid['metadata']['fields']['hubHeightM'][0]['value'] = float('nan')
        self.http.expect(self.http.request(SAVE, invalid), 422, 'INVALID_REQUEST')
        revision = self.http.admin['revision']
        duplicate = json.dumps({'expectedSessionRevision': revision, **self.body()})[:-1] + ',"clientRequestId":"different"}'
        self.http.expect(self.http.request(SAVE, raw=duplicate.encode()), 422, 'INVALID_REQUEST')
        self.assertIsNone(self.http.request(READ, self.ids)[1]['item'])

    def test_role_or_access_revision_loss_during_transaction_rolls_back(self):
        original = self.http.sessions.model_metadata._identity
        def revoke(*args):
            value = original(*args); self.http.authority().role = 'reader'; return value
        with patch.object(self.http.sessions.model_metadata, '_identity', side_effect=revoke):
            self.http.expect(self.http.request(SAVE, self.body()), 403, 'MODEL_WRITE_FORBIDDEN')
        self.http.authority().role = 'admin'
        self.assertIsNone(self.http.request(READ, self.ids)[1]['item'])
        def change(*args):
            value = original(*args); self.http.authority().grant = 'grant:2'; return value
        with patch.object(self.http.sessions.model_metadata, '_identity', side_effect=change):
            self.http.expect(self.http.request(SAVE, self.body()), 409, 'ACCESS_CHANGED')
        self.assertIsNone(self.http.request(READ, self.ids)[1]['item'])

    def test_source_metadata_revision_never_self_asserts_installed_equipment_properties(self):
        body = self.body(); body['metadata']['installationContextId'] = str(uuid4())
        self.http.expect(self.http.request(SAVE, body), 422, 'INVALID_REQUEST')
        first = self.http.request(SAVE, self.body())[1]['item']
        changed = self.body(expectedMetadataRevision=first['metadataRevision'])
        changed['metadata']['cautions'].append('Second annotation')
        second = self.http.request(SAVE, changed)[1]['item']
        self.assertEqual(self.http.request(READ, {**self.ids, 'metadataRevision': first['metadataRevision']})[1]['item'], first)
        self.assertEqual(self.http.request(READ, self.ids)[1]['item'], second)
        self.http.expect(self.http.request(READ, {**self.ids, 'metadataRevision': 'metadata:' + str(uuid4())}), 404, 'NOT_FOUND_OR_FORBIDDEN')

    def test_distributable_source_metadata_omits_local_paths_but_retains_public_provenance(self):
        def without_local(value):
            if isinstance(value, dict):return {key:without_local(item) for key,item in value.items() if key != 'localSnapshot'}
            if isinstance(value, list):return [without_local(item) for item in value]
            return value
        metadata = without_local(record())
        status, saved, _ = self.http.request(SAVE, self.body(metadata=metadata))
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved['item']['metadata'], metadata)
        self.assertEqual(self.http.request(READ, self.ids)[1]['item'], saved['item'])
        invalid = without_local(record())
        invalid['fields']['hubHeightM'][0]['source']['unknownLocalFile'] = '/private/not-accepted'
        body = self.body(metadata=invalid, expectedMetadataRevision=saved['item']['metadataRevision'])
        self.http.expect(self.http.request(SAVE, body), 422, 'INVALID_REQUEST')


if __name__ == '__main__':
    unittest.main()
