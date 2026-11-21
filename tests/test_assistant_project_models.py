import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from apps.api.assistant_project_models import catalogue, device_catalogue, summary
from apps.api.assistant_tasks import ProjectTools, equipment_configuration_question, validate_plan
from apps.api.authority import PreviewError


class AssistantProjectModelsTests(unittest.TestCase):
    def setUp(self):
        self.guard = Mock()
        self.reader = SimpleNamespace(prefix='/api/v1/projects/P',project_code='P')
        self.adopted, self.stale, self.shared_only = (str(uuid4()) for _ in range(3))
        self.application = dict(applicationId='a',revisionId='latest',specificationRevisionId='spec',
                                name='Current installation',specificationName='Model 3000')
        def config(revision, name, version):
            return dict(configurationId='id-'+revision,configurationRevision='cfg-'+revision,snapshot=dict(displayName=name,
                models=[dict(modelVersionId=version)],projectApplicationRef=dict(applicationId='a',
                    applicationRevisionId=revision,specificationRevisionId='spec')))
        self.configs = [config('latest','Current configuration',self.adopted),
                        config('former','Historical configuration',self.stale)]
        self.configurations = SimpleNamespace(catalogue=Mock(return_value=dict(items=self.configs)))
        self.models = SimpleNamespace(fixed_version_metadata=Mock(return_value=dict(displayName='Fixed model',
            modelAssetId='asset',representationType='detailed',assetState='active')))
        self.scenes = SimpleNamespace(uses=Mock(return_value=dict(currentInstanceCount=2,
            items=[dict(displayName='First scene',currentInstanceCount=2)],snapshotRevision='scene-list:1',nextCursor=None)),
            listing=Mock(return_value=dict(snapshotRevision='scene-list:1')))

    def read(self, term='model 3000'):
        return catalogue(self.reader,self.configurations,self.scenes,self.models,'actor',self.guard,'P-grant',term)

    def test_reports_only_current_project_configurations_and_fixed_saved_scene_uses(self):
        with patch('apps.api.assistant_project_models.current_applications',return_value=[self.application]):
            value = self.read()
            self.assertFalse(self.read('Historical configuration')['items'])
        self.assertEqual(1,len(value['items']))
        self.assertEqual(1,value['total'])
        row = value['items'][0]
        self.assertEqual(self.adopted,row['version'])
        self.assertEqual('detailed',row['representation'])
        self.assertEqual([dict(title='First scene',instanceCount=2)],row['scenes'])
        self.scenes.uses.assert_called_once_with(self.adopted,'actor',self.guard,access_revision='P-grant',scope='current',limit=4)
        self.assertNotIn(self.adopted,summary(value,()))
        self.assertNotIn(self.shared_only,json.dumps(value))

    def test_changed_catalogue_cannot_return_mixed_revisions(self):
        self.scenes.listing.return_value = dict(snapshotRevision='scene-list:2')
        with patch('apps.api.assistant_project_models.current_applications',return_value=[self.application]):
            with self.assertRaises(PreviewError) as changed:
                self.read()
        self.assertEqual('SNAPSHOT_CHANGED',changed.exception.code)

    def test_read_only_negotiation_uses_the_model_budget_and_bounded_summary(self):
        query = dict(tool='adopted_models',query='',faultCode='',orderId='')
        plan = dict(intent='query',queries=[query],actions=[])
        with self.assertRaises(PreviewError):
            validate_plan(plan,scene_directory=True)
        with self.assertRaises(PreviewError):
            validate_plan({**plan,'intent':'edit'},adopted_models=True)
        self.assertEqual(plan,validate_plan(plan,adopted_models=True))
        row = dict(configuration='"'*90,title='\\'*90,version=self.adopted,representation='detailed',
                   state='active',instanceCount=100,scenes=[dict(title='"'*90)]*4,moreScenes=True)
        value = dict(items=[row]*4,total=43,snapshotRevision='fixed',truncated=True,sceneUsageTruncated=True)
        reader = SimpleNamespace(reader=self.reader,adopted_model_listing=Mock(return_value=value))
        for budget,kinds in ((0,['model']),(8,['document'])):
            with self.assertRaises(PreviewError):
                ProjectTools(reader,self.guard,budget,kinds,()).query(query)
        reader.adopted_model_listing.assert_not_called()
        tools=ProjectTools(reader,self.guard,1,['model'],())
        tools.query(query)
        self.assertEqual(1,tools.reads)
        self.assertEqual(4,len(tools.results))
        self.assertTrue(tools.trace[0]['truncated'])
        self.assertEqual(43,tools.trace[0]['total'])
        self.assertLessEqual(len(tools.sources[0]['summary']),1000)
        self.assertNotIn('R1',tools.sources[0]['summary'])

    def test_same_name_devices_keep_exact_identities_and_current_source_adoptions(self):
        items=[dict(entityUid=uid,entityRevision=uid+':1',equipmentState='active',displayName='Same machine',identifiers=[])
               for uid in ('A','B')]
        rows={item['entityUid']:dict(item=item,context=dict(displayName='Site '+item['entityUid']),adoption=dict(
            applicationId='a',applicationRevisionId=revision,specificationRevisionId='spec'))
            for item,revision in zip(items,('latest','former'))}
        with (
            patch('apps.api.assistant_project_models.current_applications',return_value=[self.application]),
            patch('apps.api.assistant_project_models.EquipmentReader.catalogue',
                  return_value=dict(items=items,nextCursor='opaque',snapshotRevision='stable')) as listing,
            patch('apps.api.assistant_project_models.EquipmentReader.resolve',return_value=rows),
        ):
            value=device_catalogue(self.reader,self.configurations,self.guard,'Same machine')
            self.assertEqual(dict(q='Same machine',limit=4,rootsOnly=True),listing.call_args.args[0])
        self.assertTrue(value['truncated'])
        self.assertEqual([('A','Site A','id-latest','cfg-latest'),('B','Site B',None,None)],
                         [(row['identifier'],row['installation'],row['configurationId'],row['configurationRevision']) for row in value['items']])

    def test_explicit_equipment_route_does_not_capture_compound_question(self):
        for question, expected in [('查看设备配置',''),('查询示例风机的设备配置？','示例风机'),
                                   ('显示设备配置：示例风机','示例风机'),
                                   ('View device configurations for Example','Example'),
                                   ('查看设备配置，并更新构件绑定',None)]:
            self.assertEqual(expected,equipment_configuration_question(question))
