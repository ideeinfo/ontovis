"""Formal HTTP routes with PostgreSQL Canvas and project SQLite work orders."""
from copy import deepcopy
from base64 import b64encode
from hashlib import sha256
from http.client import HTTPConnection
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_analysis_http_integration as fixture
from tests.test_analysis_drafts import OTHER

ROOT = '/api/workbench/work-orders'
ANALYSIS = '/api/workbench/analysis-sessions'


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set a disposable PG connection')
class WorkOrderWorkflowIntegrationTests(unittest.TestCase):
    request = fixture.AnalysisHttpIntegrationTests.request
    login = fixture.AnalysisHttpIntegrationTests.login
    account = fixture.AnalysisHttpIntegrationTests.account
    body = fixture.AnalysisHttpIntegrationTests.body
    start = fixture.AnalysisHttpIntegrationTests.start
    setUp = fixture.AnalysisHttpIntegrationTests.setUp
    setUpClass = classmethod(fixture.AnalysisHttpIntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.AnalysisHttpIntegrationTests.tearDownClass.__func__)

    def ok(self, suffix, body, client=None):
        path = suffix if suffix.startswith('/api/') else ROOT + '/' + suffix
        status, value, _ = self.request(path, self.body(**body), client=client)
        self.assertEqual(status, 200, value)
        return value

    def new(self, title):
        created = self.ok('create', {'title': title, 'issue': '隔离合成任务', 'faultCode': '13001',
                                    'faultSystem': 'fixture:codes', 'simulated': True, 'requestId': str(uuid4())})
        return self.ok('workflow-detail', {'orderId': created['orderId']})

    def update(self, order, action, client=None, **fields):
        return self.ok('workflow', {'orderId': order['orderId'], 'expectedOrderRevision': order['orderRevision'],
                                    'action': action, 'requestId': str(uuid4()), **fields}, client)

    def draft(self, order, title, client=None, **fields):
        return self.ok('analysis-draft', {'orderId': order['orderId'], 'expectedOrderRevision': order['orderRevision'],
                                         'title': title, 'requestId': str(uuid4()), **fields}, client)

    def fixed(self, analysis):
        return {**{k: analysis[k] for k in ('analysisSessionId', 'analysisRevision')},
                'analysisSha256': analysis['contentSha256']}

    def test_cockpit_can_read_but_cannot_write_with_an_admin_session(self):
        order = self.new('驾驶舱查询用合成工单')
        scoped = {'orderId': order['orderId'], 'workOrderView': 'cockpit'}
        shown = self.ok('workflow-detail', scoped)
        self.assertEqual(shown['snapshotSha256'], order['snapshotSha256'])
        self.assertFalse(shown['canManage'] or shown['canProcess'] or shown['canAttach'])
        for action in ('create', 'workflow', 'attachments/start', 'attachments/complete',
                       'analysis-draft', 'analysis-share', 'seed-demo', 'action'):
            status, value, _ = self.request(ROOT+'/'+action, self.body(**scoped))
            self.assertEqual((status, value['code']), (403, 'WORK_ORDER_QUERY_ONLY'))

    def test_two_orders_share_fixed_revision_and_handler_forks_independently(self):
        self.source.permissions['other']['SYNTHETIC-A'] = 'reviewer'
        original = self.source.request
        def request(source, method, path, body=None):
            if path.endswith('/members'):
                return {'items': [{'user_id': OTHER, 'username': 'other', 'role': 'reviewer', 'is_active': True}]}
            return original(source, method, path, body)
        with patch.object(self.source, 'request', request):
            first = self.update(self.new('模拟工单 A'), 'accept')
            second = self.update(self.new('模拟工单 B'), 'assign', handlerId=OTHER)
            reviewer = self.login('other')
            base = self.draft(first, '通用分析 A')
            base['snapshot']['reuse'].update(summary='合成分析摘要', advice='按编号核对后进行独立复测')
            saved = self.ok(ANALYSIS+'/save', {'analysisSessionId': base['analysisSessionId'],
                'expectedAnalysisRevision': base['analysisRevision'], 'requestId': str(uuid4()), 'snapshot': base['snapshot']})
            fixed = self.fixed(saved)
            self.assertEqual(self.ok('analyses', {'orderId': second['orderId']}, reviewer)['items'], [])
            self.assertEqual(self.request(ROOT+'/analysis-reference', self.body(**fixed), client=reviewer)[0], 404)
            self.ok('analysis-share', {**fixed, 'requestId': str(uuid4()), 'share': True})
            candidates = self.ok('analyses', {'orderId': second['orderId']}, reviewer)['items']
            self.assertEqual([item['analysisSessionId'] for item in candidates], [fixed['analysisSessionId']])
            first = self.update(first, 'adopt_analysis', **fixed)
            second = self.update(second, 'adopt_analysis', reviewer, **fixed)
            fork = self.draft(second, '独立分析 B', reviewer, base=fixed)
            self.assertNotEqual(fork['analysisSessionId'], saved['analysisSessionId'])
            snapshot = deepcopy(fork['snapshot'])
            self.assertEqual(snapshot['derivedFrom']['contentSha256'], fixed['analysisSha256'])
            self.assertEqual(snapshot['context']['workOrderId'], second['orderId'])
            self.assertTrue(snapshot['cards'][0]['historical'])
            snapshot['reuse']['advice'] = '本次另行核对第二通道'
            copied = self.ok(ANALYSIS+'/save', {'analysisSessionId': fork['analysisSessionId'],
                'expectedAnalysisRevision': fork['analysisRevision'], 'requestId': str(uuid4()), 'snapshot': snapshot}, reviewer)
            second = self.update(second, 'adopt_analysis', reviewer, **self.fixed(copied))
            second = self.update(second, 'record', reviewer, text='合成测试中已复测第二通道')
            second = self.update(second, 'complete', reviewer, recordId=second['workflow']['records'][0]['recordId'])
            archived = self.update(second, 'archive')
            self.assertEqual(archived['state'], 'archived')
            self.assertEqual(archived['workflow']['result']['text'], '合成测试中已复测第二通道')
            self.assertEqual(first['workflow']['adoptedAnalysis']['analysisSha256'], fixed['analysisSha256'])
            self.assertEqual(self.ok('analysis-reference', fixed, reviewer)['snapshot']['reuse']['advice'],
                             '按编号核对后进行独立复测')
            self.ok('analysis-share', {**fixed, 'requestId': str(uuid4()), 'share': False})
            self.assertEqual(self.request(ROOT+'/analysis-reference', self.body(**fixed), client=reviewer)[0], 404)
            self.assertEqual(self.ok(ANALYSIS+'/detail', {'analysisSessionId': copied['analysisSessionId']},
                                     reviewer)['snapshot']['reuse']['advice'], '本次另行核对第二通道')
            late = self.request(ANALYSIS+'/save', self.body(analysisSessionId=copied['analysisSessionId'],
                expectedAnalysisRevision=copied['analysisRevision'], requestId=str(uuid4()), snapshot=snapshot), client=reviewer)
            self.assertEqual((late[0], late[1]['code']), (403, 'ANALYSIS_WRITE_FORBIDDEN'))

    def test_attachment_upload_resumes_and_fixed_content_survives_detach(self):
        from apps.api.work_order_attachments import PART_BYTES
        from tests.test_scene_http import ORIGIN
        document, version, upload_id = (str(uuid4()) for _ in range(3))
        content = b'Isolated work order treatment fixture.'
        checksum = sha256(content).hexdigest()
        parts = {}
        source_document = {'id': document, 'project_code': 'SYNTHETIC-A', 'name': 'fixture.txt',
                           'status': 'active', 'kind': 'other', 'current_version_id': version}
        source_version = {'id': version, 'document_id': document, 'byte_size': len(content),
                          'source_sha256': checksum, 'original_filename': 'fixture.txt', 'version_number': 1,
                          'media_type': 'text/plain', 'preview_kind': 'text'}
        original = self.source.request

        def request(source, method, path, body=None):
            if path.endswith('/document-uploads') and method == 'POST':
                self.assertEqual((body['source_sha256'], body['byte_size']), (checksum, len(content)))
                return {'upload_id': upload_id, 'byte_size': len(content), 'part_size': PART_BYTES, 'parts': dict(parts)}
            if path.endswith('/document-uploads/'+upload_id+'/complete'):
                self.assertEqual(parts['0']['sha256'], checksum)
                return {'item': source_document, 'version_id': version}
            if path.endswith('/documents/'+document):
                return {'item': source_document}
            if path.endswith('/documents/'+document+'/versions/'+version):
                return {'item': source_version}
            return original(source, method, path, body)

        def part(_source, path, raw):
            self.assertTrue(path.endswith('/document-uploads/'+upload_id+'/parts/0'))
            self.assertEqual(raw, content)
            parts['0'] = {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
            return {'index': 0, 'received_bytes': len(raw)}

        def read(_source, path, types, *, max_bytes):
            self.assertIn('version_id='+version, path)
            self.assertIn('rendition=original', path)
            self.assertEqual((types, max_bytes), (('text/plain',), len(content)))
            return {'content': content, 'sha256': checksum, 'mediaType': 'text/plain'}

        with patch.object(self.source, 'request', request), \
                patch.object(self.source, 'document_upload_part', part, create=True), \
                patch.object(self.source, 'source_bytes', read, create=True):
            order = self.update(self.new('附件验收工单'), 'accept')
            order = self.update(order, 'record', text='已登记文件原件作为处置记录附件')
            scope = {'orderId': order['orderId'], 'expectedOrderRevision': order['orderRevision'], 'uploadId': upload_id}
            metadata = {**scope, 'filename': 'fixture.txt', 'byteSize': len(content), 'sourceSha256': checksum}
            self.assertEqual(self.ok('attachments/start', metadata)['parts'], {})
            header = self.body(**scope, index=0, expectedSessionRevision=self.admin['revision'])
            posted = self.request(ROOT+'/attachments/part', raw=content, headers={
                'Content-Type': 'application/octet-stream', 'X-Work-Order-Part': b64encode(json.dumps(header).encode()).decode(),
            })
            self.assertEqual(posted[0], 200, posted[1])
            self.assertEqual(self.ok('attachments/start', metadata)['parts'], parts)
            file = self.ok('attachments/complete', scope)
            self.assertEqual(self.ok('attachments/complete', scope), file)
            order = self.update(order, 'attach', documentId=file['documentId'], contentVersionId=file['contentVersionId'],
                                recordId=order['workflow']['records'][0]['recordId'])
            pinned = self.ok('workflow-detail', {'orderId': order['orderId']})
            attachment = pinned['workflow']['attachments'][0]
            newer = self.update(order, 'detach', attachmentId=attachment['attachmentId'])
            self.assertEqual(newer['workflow']['attachments'], [])
            client = HTTPConnection(*self.server.server_address, timeout=5)
            try:
                body = self.body(orderId=order['orderId'], orderRevision=order['orderRevision'],
                    snapshotSha256=pinned['snapshotSha256'], attachmentId=attachment['attachmentId'],
                    expectedSessionRevision=self.admin['revision'])
                client.request('POST', ROOT+'/attachments/content', json.dumps(body).encode(),
                    {'Host': '127.0.0.1:4180', 'Origin': ORIGIN, 'Cookie': self.admin['cookie'],
                     'Content-Type': 'application/json'})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('X-Content-SHA256'), checksum)
                self.assertEqual(response.read(), content)
            finally:
                client.close()
