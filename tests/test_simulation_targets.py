import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api import simulated_faults as sim
from apps.api.authority import PreviewError
from apps.api.simulation_targets import load_registrations, resolve_targets


class SimulationTargetTests(unittest.TestCase):
    def setUp(self):
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'registrations.json'
        self.reader=SimpleNamespace(project_code='Demo-PDS',connection_id='connection')
        self.replays=[sim.identity(code) for code in ('13002','13058')]
        self.registrations={}
        self.records={}
        for i,replay in enumerate(self.replays,1):
            root,device,definition=f'unit-{i}',f'cabinet-{i}',f'definition-{i}'
            installation=str(uuid4())
            row=dict(rootUid=root,entityUid=device,definitionUid=definition,installationContextId=installation,
                     sceneId=str(uuid4()),instanceId=str(uuid4()),datasetRevision=replay['datasetRevision'])
            self.registrations[replay['datasetId']]=row
            context=dict(rootEntityUid=root,installationContextId=installation,hierarchyRevision=installation+':1')
            selected=dict(entityUid=device,entityRevision='cabinet:1',equipmentState='active',
                          displayName='Same Cabinet Name',sourceTemplateEntityUid=definition)
            self.records[root]=dict(item=dict(entityUid=root,displayName=f'Unit {i}',equipmentState='active'),
                                    children=[selected],context=context.copy())
            self.records[device]=dict(item=selected.copy(),context=context.copy())
        self.write()
        self.equipment=self.enterContext(patch('apps.api.simulation_targets.EquipmentReader')).return_value
        self.equipment.resolve.return_value=self.records

    def write(self, project='Demo-PDS'):
        self.path.write_text(json.dumps(dict(schemaVersion=1,
            projectRef={'ontobaseConnectionId':'connection','projectCode':project},targets=self.registrations)))

    def test_two_replays_keep_separate_registered_units_regardless_of_display_names(self):
        values=resolve_targets(self.path,self.reader,self.replays)
        self.assertEqual([value['rootUid'] for value in values.values()],['unit-1','unit-2'])
        self.assertEqual([value['entityUid'] for value in values.values()],['cabinet-1','cabinet-2'])
        self.assertEqual([value['entityRevision'] for value in values.values()],['cabinet:1','cabinet:1'])
        self.equipment.resolve.assert_called_once_with(['unit-1','cabinet-1','unit-2','cabinet-2'])

    def test_retired_reassigned_unregistered_and_newly_revised_targets_do_not_locate(self):
        replay=self.replays[0]
        self.records['cabinet-1']['item']['sourceTemplateEntityUid']='other'
        self.assertNotIn(replay['datasetId'],resolve_targets(self.path,self.reader,self.replays))
        self.records['cabinet-1']['item']['sourceTemplateEntityUid']='definition-1'
        self.records['cabinet-1']['item']['equipmentState']='inactive'
        self.assertNotIn(replay['datasetId'],resolve_targets(self.path,self.reader,self.replays))
        self.records['cabinet-1']['item']['equipmentState']='active'
        self.records['cabinet-1']['context']['rootEntityUid']='unit-2'
        self.assertNotIn(replay['datasetId'],resolve_targets(self.path,self.reader,self.replays))
        self.assertEqual(resolve_targets(self.path,self.reader,[dict(replay,datasetRevision='b'*64)]),{})

    def test_current_source_permission_failure_and_wrong_project_do_not_expose_targets(self):
        self.equipment.resolve.side_effect=PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError) as denied:
            resolve_targets(self.path,self.reader,self.replays)
        self.assertEqual(denied.exception.status,403)
        self.write(project='different')
        with self.assertRaises(PreviewError) as mismatched:
            load_registrations(self.path,'connection','Demo-PDS')
        self.assertEqual(mismatched.exception.code,'SIMULATION_TARGETS_UNAVAILABLE')
        self.assertEqual(load_registrations(self.path.with_name('absent.json'),'connection','Demo-PDS'),{})
