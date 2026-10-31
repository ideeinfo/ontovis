"""Fixed photo projection and protected byte reads using a bounded synthetic source."""
import copy
import hashlib
from email.message import Message
import io
import unittest
from unittest.mock import patch

from apps.api.authority import Authority, PreviewError
from apps.api.scene_engineering import SceneEngineeringReader
from apps.api.scene_photos import ScenePhotoReader
from tests import test_scene_engineering as engineering
from tests.test_scene_evidence import PNG


class PhotoAuthority(engineering.SyntheticAuthority):
    def __init__(self):
        super().__init__()
        self.edit = None
        self.after_photo = None

    def metadata(self, body):
        return {'entityUid': body['entityUid'], 'entityRevision': body['expectedEntityRevision'],
            'installationContextId': body['installationContextId'], 'hierarchyRevision': body['expectedHierarchyRevision'],
            'complete': True, 'scope': 'stored_object_photo_locations', 'versionMode': 'fixed_content_version',
            'items': [{'evidenceRef': 'photo:synthetic-location', 'sourceRevision': 'a' * 64,
                'sourceRelation': 'direct', 'sourceEntityUid': body['entityUid'],
                'sourceEntityRevision': body['expectedEntityRevision'], 'sourceTemplateRevision': None,
                'documentId': 'synthetic-document', 'contentVersionId': 'synthetic-fixed-version', 'title': '合成照片',
                'sourceSha256': 'b' * 64, 'versionNumber': 1, 'newerVersionAvailable': True,
                'documentStatus': 'active', 'unavailableReason': None, 'anchorUnavailableReason': None,
                'displayAvailability': 'not_checked', 'contentAvailability': 'not_checked',
                'engineeringConfirmation': False, 'versionMode': 'fixed_content_version',
                'verificationState': 'association_record_only', 'applicabilityState': 'recorded_unverified',
                'anchorAppliesTo': 'display_rendition',
                'selector': {'kind': 'image_bbox', 'renditionId': 'synthetic-display',
                    'displayRevision': hashlib.sha256(PNG).hexdigest(), 'regionKind': 'device_region',
                    'coordinateSpace': 'oriented_display_normalized', 'bbox': {'x': .1, 'y': .2, 'width': .3, 'height': .4}},
                'storage_uri': '/private/not-public'}]}

    def selection(self, body):
        self.guard()
        item = self.objects.get(body['entityUid'])
        if not item or item['installationContextId'] != body['installationContextId']:
            raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
        if item['entityRevision'] != body['expectedEntityRevision']:
            raise PreviewError(409, 'ENGINEERING_CHANGED')
        if body['installationContextId'] and self.contexts[body['installationContextId']]['hierarchyRevision'] != body['expectedHierarchyRevision']:
            raise PreviewError(409, 'ENGINEERING_CHANGED')

    def request(self, method, path, body=None):
        if not path.endswith('/object-evidence/photos/resolve'):
            return super().request(method, path, body)
        self.calls.append((method, path, copy.deepcopy(body)))
        self.selection(body)
        value = self.metadata(body)
        if self.edit: self.edit(value)
        self.selection(body)
        return value

    def photo(self, path, body, display_sha256):
        assert path.endswith('/photos/content') and body['representation'] == 'display'
        assert 'expectedDisplayRevision' not in body
        self.calls.append(('POST', path, copy.deepcopy(body)))
        self.selection(body)
        value = self.metadata(body)
        if self.edit: self.edit(value)
        item = next((row for row in value['items'] if row['evidenceRef'] == body['evidenceRef']), None)
        if not item or item['sourceRevision'] != body['expectedSourceRevision']:
            raise PreviewError(409, 'SOURCE_CHANGED')
        if item['sourceSha256'] != body['expectedSourceSha256'] or item['contentVersionId'] != body['expectedContentVersionId']:
            raise PreviewError(409, 'CONTENT_CHANGED')
        if not item['selector']: raise PreviewError(409, 'RENDITION_UNAVAILABLE')
        if display_sha256 != item['selector']['displayRevision']:
            raise PreviewError(409, 'CONTENT_CHANGED')
        if self.after_photo: self.after_photo(self)
        self.selection(body)
        return {'content': PNG, 'mediaType': 'image/png', 'sha256': display_sha256}


class ScenePhotoTests(unittest.TestCase):
    def setUp(self):
        self.authority = PhotoAuthority()
        self.reader = ScenePhotoReader(SceneEngineeringReader(self.authority, engineering.CONNECTION,
                                                             engineering.PROJECT, self.authority.guard))

    def body(self):
        item = self.authority.objects[engineering.CABINET]
        return {'entityUid': item['entityUid'], 'expectedEntityRevision': item['entityRevision'],
                'installationContextId': engineering.CTX,
                'expectedHierarchyRevision': self.authority.contexts[engineering.CTX]['hierarchyRevision']}

    def content_body(self):
        row = self.authority.metadata(self.body())['items'][0]
        return {**self.body(), 'evidenceRef': row['evidenceRef'], 'expectedSourceRevision': row['sourceRevision'],
                'expectedContentVersionId': row['contentVersionId'], 'expectedSourceSha256': row['sourceSha256'],
                'expectedDisplayRevision': row['selector']['displayRevision']}

    def error(self, code, function, *args):
        with self.assertRaises(PreviewError) as result: function(*args)
        self.assertEqual(result.exception.code, code)

    def test_preview_reuses_pixels_but_rechecks_the_device_association(self):
        from collections import OrderedDict
        from apps.api import analysis_media
        body=self.content_body()
        with patch.object(analysis_media,'_cache',OrderedDict()):
            first=self.reader.content(body|{'representation':'preview'})
            second=self.reader.content(body|{'representation':'preview'})
            self.assertEqual(first,second);self.assertEqual(first['mediaType'],'image/jpeg')
            self.assertEqual(sum(path.endswith('/photos/content') for _,path,_ in self.authority.calls),1)
            self.authority.allowed=False
            with self.assertRaises(PreviewError):self.reader.content(body|{'representation':'preview'})

    def test_metadata_keeps_fixed_version_region_and_separate_source_digest(self):
        row = self.reader.resolve(self.body())['items'][0]
        self.assertEqual(row['contentVersionId'], 'synthetic-fixed-version')
        self.assertTrue(row['newerVersionAvailable'])
        self.assertFalse(row['engineeringConfirmation'])
        self.assertNotIn('storage_uri', row)
        self.assertNotEqual(row['sourceSha256'], row['selector']['displayRevision'])
        self.assertEqual(self.reader.content(self.content_body())['content'], PNG)

    def test_ancestor_substitution_and_changed_version_or_display_are_rejected(self):
        self.authority.edit = lambda value: value['items'][0].update(sourceEntityUid=engineering.ROOT)
        self.error('SOURCE_CHANGED', self.reader.resolve, self.body())
        self.authority.edit = None
        for key in ('expectedSourceRevision', 'expectedSourceSha256', 'expectedDisplayRevision'):
            body = self.content_body(); body[key] = 'c' * 64
            self.error('SOURCE_CHANGED' if key == 'expectedSourceRevision' else 'CONTENT_CHANGED', self.reader.content, body)

    def test_empty_unavailable_invalid_or_duplicate_regions_are_honest(self):
        self.authority.edit = lambda value: value.update(items=[])
        self.assertEqual(self.reader.resolve(self.body())['items'], [])
        self.authority.edit = lambda value: value['items'][0].update(selector=None, anchorAppliesTo=None, anchorUnavailableReason='HISTORY_UNAVAILABLE')
        self.assertIsNone(self.reader.resolve(self.body())['items'][0]['selector'])
        self.error('RENDITION_UNAVAILABLE', self.reader.content, self.content_body())
        self.authority.edit = lambda value: value['items'][0]['selector']['bbox'].update(width=1.)
        self.error('SOURCE_UNAVAILABLE', self.reader.resolve, self.body())
        self.authority.edit = lambda value: value['items'].append(copy.deepcopy(value['items'][0]))
        self.error('SOURCE_UNAVAILABLE', self.reader.resolve, self.body())

    def test_revoke_or_object_change_while_reading_does_not_release_photo(self):
        self.authority.after_photo = lambda source: setattr(source, 'allowed', False)
        self.error('FORBIDDEN', self.reader.content, self.content_body())
        self.authority.allowed = True
        self.authority.after_photo = lambda source: source.objects[engineering.CABINET].update(entityRevision='changed:2')
        self.error('ENGINEERING_CHANGED', self.reader.content, self.content_body())

    def test_content_uses_one_protected_source_read_without_duplicate_metadata_or_identity(self):
        with patch.object(self.reader, '_selected', side_effect=AssertionError('Redundant object read')) as selected:
            self.assertEqual(self.reader.content(self.content_body())['content'], PNG)
        self.assertEqual(selected.call_count, 0)
        self.assertEqual([path.rsplit('/', 1)[-1] for _, path, _ in self.authority.calls], ['content'])

    def test_identity_change_during_metadata_still_prevents_releasing_bytes(self):
        self.authority.edit = lambda _: self.authority.objects[engineering.CABINET].update(entityRevision='changed:2')
        self.error('ENGINEERING_CHANGED', self.reader.content, self.content_body())

    def test_project_photo_relies_on_current_source_guards_without_duplicate_identity_reads(self):
        item = self.authority.objects['definition']
        body = {'entityUid': item['entityUid'], 'expectedEntityRevision': item['entityRevision'],
                'installationContextId': None, 'expectedHierarchyRevision': None}
        row = self.authority.metadata(body)['items'][0]
        payload = {**body, 'evidenceRef': row['evidenceRef'], 'expectedSourceRevision': row['sourceRevision'],
                   'expectedContentVersionId': row['contentVersionId'], 'expectedSourceSha256': row['sourceSha256'],
                   'expectedDisplayRevision': row['selector']['displayRevision']}
        with patch.object(self.reader.reader, '_resolve', wraps=self.reader.reader._resolve) as resolve:
            self.assertEqual(self.reader.content(payload)['content'], PNG)
        self.assertEqual(resolve.call_count, 0)
        self.authority.after_photo = lambda source: setattr(source, 'allowed', False)
        self.error('FORBIDDEN', self.reader.content, payload)
        self.authority.allowed = True
        self.authority.after_photo = lambda source: source.objects['definition'].update(entityRevision='changed')
        self.error('ENGINEERING_CHANGED', self.reader.content, payload)

    def test_real_transport_checks_fixed_version_digest_mime_and_region_header(self):
        source = Authority('http://127.0.0.1:1234'); source.token = 'synthetic-token'
        headers = {'Content-Type': 'image/png', 'X-Content-SHA256': hashlib.sha256(PNG).hexdigest(),
                   'X-Document-Content-Version': 'synthetic-fixed-version', 'X-Anchor-Applies-To': 'display_rendition'}
        data = PNG
        class Response(io.BytesIO): pass
        class Opener:
            def open(_self, request, timeout):
                self.assertEqual((request.full_url, timeout), ('http://127.0.0.1:1234/fixed-photo', 30))
                result = Response(data); result.headers = Message()
                for key, value in headers.items(): result.headers[key] = value
                return result
        source.opener = Opener()
        body = {'expectedContentVersionId': 'synthetic-fixed-version'}
        sha = hashlib.sha256(PNG).hexdigest()
        self.assertEqual(source.photo('/fixed-photo', body, sha)['content'], PNG)
        for key, value in (('Content-Type', 'text/html'), ('X-Content-SHA256', 'a' * 64),
                           ('X-Document-Content-Version', 'latest-version'), ('X-Anchor-Applies-To', 'none')):
            original = headers[key]; headers[key] = value
            self.error('CONTENT_CHANGED', source.photo, '/fixed-photo', body, sha)
            headers[key] = original
        data = PNG + b'changed'
        self.error('CONTENT_CHANGED', source.photo, '/fixed-photo', body, sha)

    def test_aggregate_renditions_accept_only_image_bytes_from_the_fixed_endpoint(self):
        source=Authority('http://127.0.0.1:1234');source.token='synthetic-token'
        class Response(io.BytesIO): pass
        data=PNG;mime='image/png';seen=[]
        class Opener:
            def open(_self,request,timeout):
                seen.append(request.full_url)
                result=Response(data);result.headers=Message();result.headers['Content-Type']=mime
                return result
        source.opener=Opener();path='/api/v1/projects/P/equipment/shared-photos/content'
        self.assertEqual(source.photo(path,{'representation':'thumbnail'},None)['sha256'],hashlib.sha256(PNG).hexdigest())
        self.error('INVALID_REQUEST',source.photo,'/unrelated',{},None)
        self.assertEqual(len(seen),1)
        mime='text/html';self.error('CONTENT_CHANGED',source.photo,path,{},None)
        mime='image/png';data=b'not an image';self.error('CONTENT_CHANGED',source.photo,path,{},None)
        data=PNG+bytes(20*1024*1024);self.error('CONTENT_CHANGED',source.photo,path,{},None)


if __name__ == '__main__': unittest.main()
