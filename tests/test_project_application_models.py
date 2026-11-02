"""Project application placement over real model/configuration stores."""
import copy
import unittest
from urllib.parse import unquote
from uuid import uuid4

from apps.api.authority import PreviewError
from tests import test_model_definition_access as definitions


class ProjectApplicationModelTests(unittest.TestCase):
    def setUp(self):
        self.fixture=definitions.ModelDefinitionAccessTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.projects=self.fixture.fixture
        self.sessions,self.sid=self.fixture.sessions,self.fixture.sid
        self.projects.create('A')
        self.apps={'A':[],'B':[]}
        self.list_reads=0;self.application_reads=0;self.on_list=None;self.on_application=None
        authority=self.sessions.current(self.sid,authenticated=True).authority
        original=authority.request
        def request(method,path,body=None):
            code=unquote(path.split('/')[4]) if path.startswith('/api/v1/projects/') else None
            if method=='GET' and '/equipment-applications?' in path:
                self.list_reads+=1
                if self.on_list:self.on_list(self.list_reads)
                items=[{'applicationId':x['applicationId'],'revisionId':x['revisionId']} for x in self.apps[code]]
                return {'items':items,'total':len(items),'offset':0,'limit':50}
            if method=='GET' and '/equipment-applications/revisions/' in path:
                self.application_reads+=1
                if self.on_application:self.on_application(self.application_reads)
                app=next((x for x in self.apps[code] if x['revisionId']==path.rsplit('/',1)[1]),None)
                if app is None:raise PreviewError(404,'NOT_FOUND_OR_FORBIDDEN')
                return copy.deepcopy(app)
            return original(method,path,body)
        authority.request=request
        raw=self.fixture.upload(self.fixture.uid)
        self.version=self.sessions.resource_request(self.sid,'/api/workbench/resources/model/calibrate',
            self.projects.payload(modelVersionId=raw['modelVersionId'],expectedContentRevision=raw['contentRevision'],
                expectedLibraryRevision=self.sessions.shared.library.listing()['libraryRevision'],clientRequestId=str(uuid4()),
                calibration={'unit':'m','axes':'Y_UP_RIGHT_HANDED','basePoint':[0,0,0],'forward':[0,0,-1]}))

    def application(self,project='A'):
        revision,spec=str(uuid4()),str(uuid4())
        app={'applicationId':str(uuid4()),'revisionId':revision,'headRevisionId':revision,'projectCode':project,
             'snapshot':{'name':'Source project application','specificationRevisionId':spec,'rootDefinition':None,'mappings':[]},
             'specification':{'revisionId':spec,'code':'FIXTURE-1','name':'Synthetic turbine specification',
                              'objectKind':'turbine','manufacturer':'Fixture only','status':'active'}}
        self.apps[project].append(app);return app

    def configure(self,app,version=None):
        body=self.projects.payload(app['projectCode'],configurationId=str(uuid4()),expectedConfigurationRevision=None,
            clientRequestId=str(uuid4()),snapshot={'projectApplicationRef':{'applicationId':app['applicationId'],
                'applicationRevisionId':app['revisionId'],'specificationRevisionId':app['snapshot']['specificationRevisionId']},
                'models':[{'modelVersionId':(version or self.version)['modelVersionId'],'mappings':[]}]})
        return self.sessions.equipment_request(self.sid,'/api/workbench/equipment/configurations/save',body)

    def catalogue(self,project='A'):
        self.list_reads=0;self.application_reads=0
        return self.sessions.resource_request(self.sid,'/api/workbench/project-turbine-definitions',
            self.projects.payload(project,projectCode=project))

    def test_application_configuration_restores_type_after_legacy_object_disappears(self):
        app=self.application();saved=self.configure(app)
        del self.fixture.objects['A'][self.fixture.uid]
        result=self.catalogue();self.assertEqual(len(result['items']),1)
        item=result['items'][0]
        self.assertIsNone(item['definitionEntityUid'])
        self.assertEqual(item['projectApplicationRef'],saved['snapshot']['projectApplicationRef'])
        self.assertEqual(item['configurationRevision'],saved['configurationRevision'])
        self.assertEqual(item['detailedModel']['modelVersionId'],self.version['modelVersionId'])
        self.assertEqual(item['detailedModel']['sha256'],self.version['sha256'])
        self.assertEqual(result['pairMap'],{});self.assertEqual(result['pairingStatus'],'unverified')

    def test_shared_model_application_does_not_leak_into_another_project(self):
        self.configure(self.application())
        self.assertFalse(self.catalogue('B')['items'])

    def test_two_applications_without_object_ids_have_distinct_catalogue_keys(self):
        first,second=self.application(),self.application();second['specification']['code']='FIXTURE-2'
        self.configure(first);self.configure(second)
        del self.fixture.objects['A'][self.fixture.uid]
        items=self.catalogue()['items']
        self.assertEqual(len(items),2);self.assertEqual(len({x['catalogueKey'] for x in items}),2)

    def test_historical_configuration_is_not_offered_as_current_application(self):
        app=self.application();self.configure(app)
        app['revisionId']=app['headRevisionId']=str(uuid4())
        del self.fixture.objects['A'][self.fixture.uid]
        self.assertFalse(self.catalogue()['items'])

    def test_source_listing_change_during_projection_is_rejected(self):
        self.configure(self.application())
        def change(count):
            if count==2:self.apps['A'].clear()
        self.on_list=change
        with self.assertRaises(PreviewError) as error:self.catalogue()
        self.assertEqual(error.exception.code,'ENGINEERING_CHANGED')

    def test_configuration_head_change_during_projection_is_rejected(self):
        app=self.application();saved=self.configure(app)
        def change(count):
            if count!=1:return
            self.sessions.equipment_request(self.sid,'/api/workbench/equipment/configurations/save',
                self.projects.payload('A',configurationId=saved['configurationId'],expectedConfigurationRevision=saved['configurationRevision'],
                    clientRequestId=str(uuid4()),snapshot={'projectApplicationRef':saved['snapshot']['projectApplicationRef'],
                                                          'models':saved['snapshot']['models']}))
        self.on_application=change
        with self.assertRaises(PreviewError) as error:self.catalogue()
        self.assertEqual(error.exception.code,'REVISION_CONFLICT')

    def test_deleted_asset_is_not_an_application_placement_candidate(self):
        self.configure(self.application())
        self.sessions.resource_request(self.sid,'/api/workbench/resources/model/delete',self.projects.payload(
            modelAssetId=self.version['modelAssetId'],modelVersionId=self.version['modelVersionId'],expectedAssetRevision=self.version['assetRevision'],
            expectedLifecycleRevision=0,clientRequestId=str(uuid4())))
        self.assertFalse(self.catalogue()['items'])

    def test_model_asset_change_after_projection_is_rejected(self):
        self.configure(self.application())
        def change(count):
            if count!=2:return
            self.sessions.resource_request(self.sid,'/api/workbench/resources/model/delete',self.projects.payload(
                modelAssetId=self.version['modelAssetId'],modelVersionId=self.version['modelVersionId'],expectedAssetRevision=self.version['assetRevision'],
                expectedLifecycleRevision=0,clientRequestId=str(uuid4())))
        self.on_application=change
        with self.assertRaises(PreviewError) as error:self.catalogue()
        self.assertEqual(error.exception.code,'MODEL_ASSET_CHANGED')

    def test_permission_revoked_while_reading_application_stops_catalogue(self):
        self.configure(self.application())
        def revoke(count):
            if count==1:
                from tests.test_project_workspaces import ProjectsAuthority
                del ProjectsAuthority.permissions['member']['A']
        self.on_application=revoke
        with self.assertRaises(PreviewError) as error:self.catalogue()
        self.assertEqual(error.exception.status,403)

    def test_specification_identity_mismatch_is_not_treated_as_a_type(self):
        app=self.application();self.configure(app)
        app['specification']['revisionId']=str(uuid4())
        with self.assertRaises(PreviewError) as error:self.catalogue()
        self.assertEqual(error.exception.code,'SOURCE_UNAVAILABLE')
