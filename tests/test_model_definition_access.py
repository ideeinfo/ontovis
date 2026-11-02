"""Real project dispatch and model writes, with synthetic authoritative HTTP shapes."""
import copy
import io
from unittest import TestCase
from uuid import uuid4
from urllib.parse import unquote

from apps.api.authority import PreviewError
from tests import test_project_workspaces as projects
from tests.test_scene_engineering import SyntheticAuthority
from tests.test_model_upload import glb


class ModelDefinitionAccessTests(TestCase):
    def setUp(self):
        self.fixture = projects.ProjectWorkspaceTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.sessions, self.sid = self.fixture.sessions, self.fixture.sid
        self.uid, self.other = 'entity:' + str(uuid4()), 'entity:' + str(uuid4())
        self.objects = {'A': {self.uid: SyntheticAuthority.object(self.uid, None, 'definition')},
                        'B': {self.other: SyntheticAuthority.object(self.other, None, 'definition')}}
        row = self.sessions.current(self.sid, authenticated=True)
        original = row.authority.request
        def request(method, path, body=None):
            if method=='GET' and '/equipment-applications?' in path:
                return {'items':[],'total':0,'offset':0,'limit':50}
            if method == 'POST' and path.endswith('/objects/resolve'):
                code = unquote(path.split('/')[4])
                if code not in projects.ProjectsAuthority.permissions['member']: raise PreviewError(403, 'FORBIDDEN')
                items = []
                for uid in body['entityUids']:
                    obj = copy.deepcopy(self.objects.get(code, {}).get(uid))
                    items.append(dict(requestedEntityUid=uid, canonicalEntityUid=uid if obj else None,
                                      resolution='exact' if obj else 'unavailable', object=obj, canonicalObject=obj))
                return dict(projectCode=code, resolutionMode='live', items=items)
            return original(method, path, body)
        row.authority.request = request
        self.raw = glb(self.fixture.root / 'model.glb').read_bytes()

    def upload(self, uid):
        library = self.sessions.shared.library
        body = self.fixture.payload(expectedLibraryRevision=library.listing()['libraryRevision'],
                                    clientRequestId=str(uuid4()), displayName='Synthetic model', purpose='equipment',
                                    sourceNote='Synthetic test only', rightsDeclared=True, definitionEntityUid=uid,
                                    modelCode='synthetic', representationType='detailed')
        return self.sessions.resource_upload(self.sid, body, io.BytesIO(self.raw), len(self.raw))

    def test_unresolvable_or_installation_identity_cannot_be_saved_as_a_definition(self):
        with self.assertRaises(PreviewError) as caught: self.upload('entity:' + str(uuid4()))
        self.assertEqual(caught.exception.status, 404)
        self.objects['A'][self.uid] = SyntheticAuthority.object(self.uid, str(uuid4()))
        with self.assertRaises(PreviewError) as caught: self.upload(self.uid)
        self.assertEqual(caught.exception.code, 'MODEL_DEFINITION_REQUIRED')
        self.assertEqual(self.sessions.shared.project_models.listing('member', lambda: None, access_revision='test')['items'], [])

    def test_source_revision_and_project_grant_are_rechecked_before_commit(self):
        check = self.sessions._model_definition_guard(self.sid, self.uid)
        self.objects['A'][self.uid]['entityRevision'] = 'new-source-revision'
        with self.assertRaises(PreviewError) as caught: check()
        self.assertEqual(caught.exception.code, 'ENGINEERING_CHANGED')
        check = self.sessions._model_definition_guard(self.sid, self.uid)
        del projects.ProjectsAuthority.permissions['member']['A']
        with self.assertRaises(PreviewError) as caught: check()
        self.assertEqual(caught.exception.status, 403)

    def test_project_catalogue_filters_shared_metadata_by_authoritative_project_membership(self):
        self.upload(self.uid); self.upload(self.other)
        def catalogue(project, **changes):
            return self.sessions.resource_request(self.sid, '/api/workbench/project-turbine-definitions',
                                                  self.fixture.payload(project, projectCode=project, **changes))
        a, b = catalogue('A'), catalogue('B')
        self.assertEqual([item['definitionEntityUid'] for item in a['items']], [self.uid])
        self.assertEqual([item['definitionEntityUid'] for item in b['items']], [self.other])
        self.assertEqual(a['projectCode'], 'A'); self.assertEqual(a['pairMap'], {})
        with self.assertRaises(PreviewError) as caught:
            self.sessions.resource_request(self.sid, '/api/workbench/project-turbine-definitions', self.fixture.payload('B', projectCode='A'))
        self.assertEqual(caught.exception.code, 'PROJECT_SCOPE_MISMATCH')
        del projects.ProjectsAuthority.permissions['member']['A']
        with self.assertRaises(PreviewError) as caught: catalogue('A')
        self.assertEqual(caught.exception.status, 403)
