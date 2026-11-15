from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from apps.api.assistant_tasks import ProjectTools, validate_plan
from apps.api.authority import PreviewError


def identifier():
    return str(uuid4())


class AssistantDeviceAndProcessingTests(unittest.TestCase):
    def setUp(self):
        self.engineering=SimpleNamespace(prefix='/api/v1/projects/P',_request=Mock())
        self.tools=ProjectTools(SimpleNamespace(reader=self.engineering),Mock(),8,['object','document'],('Private Project',))
        self.a=dict(displayName='Machine 1',entityUid='e1',entityRevision='r4',equipmentState='active')
        self.b=dict(displayName='Machine 2',entityUid='e2',entityRevision='r3',equipmentState='active')
        self.context=dict(installationContextId='install',hierarchyRevision='install:r3')
        self.document=dict(title='Manual',documentId=identifier(),contentVersionId=identifier(),
            kind='pdf',versionNumber=4,availability='available')
        self.photo=dict(title='Private Photo',documentId=identifier(),contentVersionId=identifier(),
            kind='photo',versionNumber=2,availability='available')

    def ask(self, name, term):
        return self.tools.query(dict(tool=name,query=term,faultCode='',orderId=''))

    def test_unique_installed_equipment_uses_confirmed_context_and_fixed_material_versions(self):
        with patch('apps.api.assistant_device_materials.EquipmentReader') as reader:
            service=reader.return_value
            service.catalogue.return_value=dict(items=[self.a],nextCursor=None)
            service.resolve.return_value={'e1':dict(item=self.a,context=self.context)}
            service.material_devices.return_value=dict(items=[self.document,self.photo],revision=5,nextCursor=None)
            self.ask('equipment_materials','Machine 1')
        service.material_devices.assert_called_once_with(dict(entityUid='e1',expectedEntityRevision='r4',
            installationContextId='install',expectedHierarchyRevision='install:r3',limit=6))
        self.assertEqual(3,self.tools.reads)
        self.assertEqual(['equipment_material_scope','document'],[row['kind'] for row in self.tools.results])
        doc=self.tools.results[1]
        self.assertEqual(self.document['contentVersionId'],doc['documentPreview']['contentVersionId'])
        self.assertEqual(self.document['contentVersionId'],doc['selector']['contentVersionId'])
        self.assertEqual(4,doc['version'])
        self.assertNotIn('Private Photo',str(self.tools.sources))
        self.assertNotIn(self.document['documentId'],str(self.tools.sources))

    def test_ambiguous_equipment_and_changed_revision_never_open_material_catalogue(self):
        with patch('apps.api.assistant_device_materials.EquipmentReader') as reader:
            service=reader.return_value
            service.catalogue.return_value=dict(items=[self.a,self.b],nextCursor=None)
            self.ask('equipment_materials','Machine')
            service.resolve.assert_not_called()
            service.catalogue.return_value=dict(items=[self.a],nextCursor=None)
            service.resolve.return_value={'e1':dict(item={**self.a,'entityRevision':'latest'},context=self.context)}
            with self.assertRaises(PreviewError) as changed:
                self.ask('equipment_materials','Machine 1')
            self.assertEqual('ENGINEERING_CHANGED',changed.exception.code)
            service.material_devices.assert_not_called()

    def test_processing_progress_keeps_result_state_separate_and_omits_unavailable_titles_and_traces(self):
        doc=identifier()
        version=identifier()
        row=dict(title='Engineering manual',id=identifier(),kind='document_generation',state='completed',
                 result_state='pending_review',source_available=True,document_id=doc,version_id=version,
                 completed_units=81,total_units=81,summary=dict(error='private exception',model='private binding'))
        removed={**row,'id':identifier(),'source_available':False,'title':'Removed document'}
        photo={**row,'id':identifier(),'kind':'photo','title':'Hidden photo'}
        self.engineering._request.return_value=dict(items=[row,removed,photo],next_cursor=6)
        self.ask('processing_tasks','Engineering manual')
        self.engineering._request.assert_called_once_with('GET','/api/v1/projects/P/processing-tasks?q=Engineering+manual&cursor=0&limit=6')
        self.assertEqual(1,self.tools.reads)
        result,unavailable=self.tools.results
        self.assertEqual(('completed','pending_review',81,81),
            tuple(result[key] for key in ('state','resultState','completedUnits','totalUnits')))
        self.assertEqual(version,result['documentPreview']['contentVersionId'])
        self.assertNotIn('documentPreview',unavailable)
        evidence=str(self.tools.sources)+str(self.tools.results)
        for value in ('Hidden photo','Removed document','private binding','private exception'):
            self.assertNotIn(value,evidence)
        self.assertTrue(self.tools.trace[0]['truncated'])

    def test_negotiate_each_tool_and_reject_provider_mutation(self):
        for kind in ('equipment_materials','processing_tasks'):
            plan=dict(intent='query',queries=[dict(tool=kind,query='Machine 1',faultCode='',orderId='')],actions=[])
            with self.assertRaises(PreviewError):
                validate_plan(plan)
            self.assertEqual(plan,validate_plan(plan,**{kind:True}))
            with self.assertRaises(PreviewError):
                validate_plan({**plan,'intent':'edit'},**{kind:True})
