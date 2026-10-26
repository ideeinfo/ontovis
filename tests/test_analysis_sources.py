"""Bounded source handles, full work-order history and explicit simulated data."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
import sqlite3
from unittest.mock import Mock, patch
from uuid import uuid4

from apps.api import simulated_faults as sim
from apps.api.analysis_evidence import validate_descriptor
from apps.api.analysis_source_reader import AnalysisSourceReader
from apps.api.authority import PreviewError
from tests import test_work_orders as orders


class SourceContractTests(unittest.TestCase):
    def test_simulated_fault_lifecycle_and_deterministic_history_have_separate_identity(self):
        result=sim.catalogue('Demo-PDS');self.assertEqual(len(result['items']),4)
        self.assertEqual(result['sourceKind'],'simulated');self.assertEqual(result['mode'],'replay')
        for item in result['items']:
            first=sim.alarms(item['datasetId']);self.assertEqual(first,sim.alarms(item['datasetId']))
            active,cleared=first['items'];self.assertEqual(active['sourceEventId'],cleared['sourceEventId'])
            self.assertEqual((active['state'],cleared['state']),('active','cleared'))
            self.assertLess(active['sequence'],cleared['sequence']);self.assertNotEqual(active['sourceRevision'],cleared['sourceRevision'])
            self.assertEqual(active['acknowledgement'],'unknown');self.assertFalse(active['engineeringConfirmation'])
            self.assertTrue(all('X91' in row['reason'] for row in result['negativeCases'] if row['faultCode'] in ('13001','13002')))

    def test_quality_gap_is_null_and_never_interpolated_or_measured(self):
        value=sim.trend('SIM-PDS-13004','device_feedback',sim.START,sim.END)
        self.assertEqual(len(value['samples']),181)
        self.assertEqual(value['samples'][90]['quality'],'bad');self.assertIsNone(value['samples'][90]['value'])
        self.assertEqual([value['samples'][i]['value'] for i in (0,30,149,150)],[0,1,1,0])
        self.assertEqual(value['sourceKind'],'simulated');self.assertEqual(value['mode'],'replay')
        for row in value['samples']:self.assertLess(row['sourceTime'],row['receivedAt'])

    def test_other_projects_unknown_faults_versions_and_times_are_rejected(self):
        for call in (lambda:sim.catalogue('B'),lambda:sim.identity('13999'),lambda:sim.dataset('SIM-PDS-13004','bad'),
                     lambda:sim.trend('SIM-PDS-13004','arbitrary',sim.START,sim.END),
                     lambda:sim.trend('SIM-PDS-13004','overcurrent',sim.END,sim.START)):
            with self.assertRaises(PreviewError):call()

    def test_temperature_bias_branches_keep_independent_reference_and_cross_page_gap(self):
        for code, expected in (('13001', 72), ('13002', -18)):
            dataset='SIM-PDS-'+code
            sensor=sim.trend(dataset,'sensor_temperature',sim.START,sim.END)
            reference=sim.trend(dataset,'reference_temperature',sim.START,sim.END)
            self.assertEqual(sensor['samples'][50]['value'],expected)
            self.assertAlmostEqual(reference['samples'][50]['value'],23.9)
            self.assertEqual(sensor['unit'],'degC');self.assertIsNone(sensor['samples'][90]['value'])
            self.assertIn('X91',sensor['dataset']['retainedEvidenceGap'])
            self.assertFalse(sensor['dataset']['wholeFaultDiagnosisComplete'])

    def test_descriptors_reject_urls_owner_fields_and_false_versions(self):
        value={'modelAssetId':str(uuid4()),'modelVersionId':str(uuid4()),'contentRevision':'fixed:1','sha256':'a'*64}
        validate_descriptor('model',value)
        for key in ('url','ownerId','sourceKind','sourceBody'):
            with self.assertRaises(PreviewError):validate_descriptor('model',{**value,key:'client value'})
        with self.assertRaises(PreviewError):validate_descriptor('model',{**value,'sha256':'bad'})
        with self.assertRaises(PreviewError):validate_descriptor('work_order',{'orderId':'A','orderRevision':True,'snapshotSha256':'a'*64})


class FullWorkOrderHistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=orders.WorkOrderTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.seed();self.orders=self.fixture.orders

    def reference(self):
        return self.orders.capture({'orderId':'DEMO-PDS-WO-001','expectedOrderRevision':1},'synthetic-admin',lambda:None)

    def test_capture_keeps_complete_order_events_rules_and_investigation_after_change(self):
        ref=self.reference();before=self.orders.fixed_snapshot(ref)
        self.fixture.action(self.fixture.first(),'accept')
        self.assertEqual(self.orders.fixed_snapshot(ref),before)
        self.assertEqual(before['state'],'open');self.assertEqual(len(before['events']),1)
        self.assertIn('investigation',before);self.assertIn('targets',before);self.assertIn('diagnosis',before)
        self.assertEqual(self.orders.capture({'orderId':before['orderId'],'expectedOrderRevision':2},'synthetic-admin',lambda:None)['orderRevision'],2)

    def test_capture_authorization_failure_rolls_back_without_revising_order(self):
        calls=[]
        def guard():
            calls.append(1)
            if len(calls)==2:raise PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.orders.capture({'orderId':'DEMO-PDS-WO-001','expectedOrderRevision':1},'synthetic-admin',guard)
        with self.orders.library.connect() as db:self.assertEqual(db.execute('select count(*) from work_order_snapshots').fetchone()[0],0)
        self.assertEqual(self.fixture.first()['orderRevision'],1)

    def test_missing_history_and_changed_hash_do_not_return_current_order(self):
        ref=self.reference()
        for body in ({**ref,'orderRevision':2},{**ref,'snapshotSha256':'b'*64}):
            with self.assertRaises(PreviewError):self.orders.fixed_snapshot(body)
        with self.orders.library.connect() as db:
            for sql in ('update work_order_snapshots set actor=actor','delete from work_order_snapshots'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    def test_fixed_analysis_link_is_idempotent_and_does_not_flow_order_state(self):
        body={'requestId':str(uuid4()),'orderId':'DEMO-PDS-WO-001','expectedOrderRevision':1,
              'analysisSessionId':str(uuid4()),'analysisRevision':1,'analysisSha256':'a'*64}
        check=Mock();first=self.orders.link_analysis(body,'synthetic-admin',lambda:None,check)
        self.assertEqual(self.orders.link_analysis(body,'synthetic-admin',lambda:None,check),first)
        current=self.fixture.first();self.assertEqual((current['state'],current['orderRevision']),('open',2))
        self.assertEqual(current['analysisLinks'][0]['analysisRevision'],1)
        self.assertEqual(len(current['events']),2);self.assertGreaterEqual(check.call_count,4)
        with self.assertRaises(PreviewError):self.orders.link_analysis({**body,'requestId':str(uuid4())},'synthetic-admin',lambda:None,check)
        with self.assertRaises(PreviewError):self.orders.link_analysis(body,'synthetic-admin',lambda:None,lambda:(_ for _ in ()).throw(PreviewError(403,'FORBIDDEN')))


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.reader=SimpleNamespace(project_code='Demo-PDS')
        self.source=AnalysisSourceReader(self.reader,None,None,lambda:None,'synthetic-admin')
        def object_for(rds):
            return {'item':{'entityUid':rds,'entityRevision':'object:1','objectScope':'definition','objectKind':'cabinet' if rds=='=WEC+CN1' else 'device',
                'installationContextId':None,'definitionParentEntityUid':None if rds=='=WEC+CN1' else '=WEC+CN1'},'context':None}
        self.source._rds=Mock(side_effect=object_for)
        self.photo={'evidenceRef':'photo:synthetic','displayAvailability':'not_checked','selector':{'displayRevision':'a'*64}}
        self.source.photos.resolve=Mock(return_value={'items':[self.photo]})
        patcher=patch('apps.api.analysis_source_reader.SceneEvidenceReader');self.drawing=patcher.start();self.addCleanup(patcher.stop)
        self.drawing.return_value.resolve.return_value={'items':[{'availability':'available','evidenceRef':'drawing:synthetic'}]}

    def test_eligible_requires_all_components_parentage_drawing_and_real_photo_region(self):
        value=self.source.qualify('13004');self.assertTrue(value['eligible']);self.assertEqual(len(value['components']),3)
        self.assertEqual(value['locationGranularity'],'source_label');self.assertFalse(value['engineeringConfirmation'])
        self.assertEqual(value['sourceKind'],'simulated');self.assertIsNotNone(value['photo'])
        channel=value['components'][1]
        self.assertEqual(channel['referenceKind'],'module_channel');self.assertEqual(channel['channelAddress'],'IX.1')
        self.assertEqual(channel['selection'],value['components'][2]['selection'])
        self.assertFalse(channel['channelIdentityConfirmed'])

    def test_missing_component_or_wrong_cabinet_is_not_relabelled_complete(self):
        original=self.source._rds.side_effect
        def wrong(rds):
            value=original(rds)
            if rds.endswith('105A3'):value['item']['definitionParentEntityUid']='other-cabinet'
            return value
        self.source._rds.side_effect=wrong
        value=self.source.qualify('13004');self.assertFalse(value['eligible']);self.assertEqual(value['gaps'],['CABINET_MEMBERSHIP_UNRESOLVED'])
        self.source._rds.side_effect=PreviewError(409,'DIAGNOSTIC_OBJECT_UNRESOLVED')
        self.assertFalse(self.source.qualify('13003')['eligible'])

    def test_no_photo_region_or_drawing_is_a_gap(self):
        self.photo['selector']=None
        self.assertFalse(self.source.qualify('13003')['eligible'])
        self.photo['selector']={'displayRevision':'a'*64};self.drawing.return_value.resolve.return_value={'items':[]}
        self.assertFalse(self.source.qualify('13003')['eligible'])

    def test_source_revocation_propagates_without_cached_object_details(self):
        self.source._rds.side_effect=PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.source.qualify('13004')

    def test_rehearsal_reads_do_not_repeat_photo_qualification_or_hide_missing_evidence_cases(self):
        self.source.qualify=Mock(side_effect=AssertionError('Unnecessary photo prerequisite'))
        dataset=sim.identity('13003')
        selector={'datasetId':dataset['datasetId'],'datasetRevision':dataset['datasetRevision'],'eventId':dataset['datasetId']+'-event-1'}
        descriptor=self.source.resolve('alarm',selector)
        value=self.source.read('alarm',descriptor)
        self.assertEqual(value['mappingKind'],'simulated_reference');self.assertEqual(len(value['items']),2)
        self.source.qualify.assert_not_called()
