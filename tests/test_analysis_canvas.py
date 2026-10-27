from copy import deepcopy
from types import SimpleNamespace
import os
import unittest
from uuid import uuid4
from apps.api import analysis_drafts as draft, simulated_faults as sim
from apps.api.analysis_canvas import validate_canvas
from apps.api.analysis_queries import start_analysis, copy_analysis, matching_history
from apps.api.authority import PreviewError
from tests.test_analysis_drafts import snapshot, CONNECTION, OWNER, OTHER
from tests import test_analysis_drafts_integration as base
from tools import analysis_draft_backup as backup


class CanvasContractTests(unittest.TestCase):
    def value(self):
        value=snapshot();value['schemaVersion']=2;return value

    def test_v2_all_kinds_use_only_fixed_project_references_and_bounded_layout(self):
        for kind in ('object','drawing','document','photo','model3d','trend','alarm','work_order'):
            value=self.value();card=value['cards'][0];card.pop('note');card['kind']=kind
            card['source']={'system':'ontobase' if kind in ('object','drawing','document','photo') else 'ontovis',
                'ontobaseConnectionId':CONNECTION,'projectCode':value['projectCode'],'id':str(uuid4()),'revision':'a'*64}
            card.update(width=1440,height=1200)
            validate_canvas(value,CONNECTION,value['projectCode'])
            for field,bad in (('url','https://example.invalid'),('html','<script>'),('height',1201)):
                changed=deepcopy(value);changed['cards'][0][field]=bad
                with self.assertRaises(PreviewError):validate_canvas(changed,CONNECTION,value['projectCode'])
            card['source']['projectCode']='OTHER'
            with self.assertRaises(PreviewError):validate_canvas(value,CONNECTION,value['projectCode'])

    def test_frames_check_state_and_historical_reference_are_bounded(self):
        value=self.value();value['cards'][0]['checkState']='not_started';value['cards'][0]['frameId']='group'
        value['frames']=[{'id':'group','title':'本次','x':0,'y':0,'width':900,'height':600}]
        validate_canvas(value,CONNECTION,value['projectCode'])
        value['cards'][0]['frameId']='missing'
        with self.assertRaises(PreviewError):validate_canvas(value,CONNECTION,value['projectCode'])


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'),'Disposable PG required')
class CanvasStorageTests(unittest.TestCase):
    setUpClass=classmethod(base.AnalysisDraftIntegrationTests.setUpClass.__func__)
    tearDownClass=classmethod(base.AnalysisDraftIntegrationTests.tearDownClass.__func__)
    setUp=base.AnalysisDraftIntegrationTests.setUp
    consumer=base.AnalysisDraftIntegrationTests.consumer

    def reader(self):
        selection={'entityUid':'synthetic-temperature-sensor','expectedEntityRevision':'fixed:1','installationContextId':None,'expectedHierarchyRevision':None}
        return SimpleNamespace(reader=SimpleNamespace(project_code='Demo-PDS',prefix='/api/v1/projects/Demo-PDS',_request=lambda *args: (_ for _ in ()).throw(PreviewError(404,'NOT_FOUND_OR_FORBIDDEN'))),
            _rds=lambda _: {'item':{'entityUid':selection['entityUid'],'entityRevision':'fixed:1'},'context':None},
            resolve=lambda kind,selector:selection if kind=='object' else selector)

    def start(self,store=None,recurrence=False,actor=OWNER):
        dataset=sim.identity('13001',recurrence=recurrence)
        return start_analysis(store or self.demo,actor,self.reader(),{'entry':{k:dataset[k] for k in ('datasetId','datasetRevision')},'requestId':str(uuid4())},lambda:None)

    def save(self,result,snapshot=None):
        return self.demo.write(OWNER,'admin','save',{'analysisSessionId':result['analysisSessionId'],
            'expectedAnalysisRevision':result['analysisRevision'],'requestId':str(uuid4()),'snapshot':snapshot or result['snapshot']},lambda:None)

    def test_manual_canvas_can_add_an_alarm_and_trend_then_reopen_fixed_sources(self):
        from apps.api.analysis_evidence import AnalysisEvidence
        from apps.api.analysis_queries import recommendations
        self.demo=self.consumer(project='Demo-PDS');reader=self.reader()
        value=snapshot();value.update(projectCode='Demo-PDS',schemaVersion=2,cards=[])
        created=self.demo.write(OWNER,'admin','create',{'requestId':str(uuid4()),'snapshot':value},lambda:None)
        alarm=recommendations(reader,{'entry':{'projectOnly':True},'section':'alarms','q':'13002'})['items'][0]
        dataset=alarm['preview']['dataset'];entry={key:dataset[key] for key in ('datasetId','datasetRevision')}
        trend=recommendations(reader,{'entry':entry,'section':'trends','q':'reference_temperature'})['items'][0]
        evidence=AnalysisEvidence(self.demo)
        for index,item in enumerate((alarm,trend)):
            ref=evidence.register(OWNER,{'analysisSessionId':created['analysisSessionId'],'expectedAnalysisRevision':1,
                'requestId':str(uuid4()),'sourceKind':item['kind'],'selector':item['selector']},lambda:None,reader.resolve)
            value['cards'].append({'id':str(uuid4()),'kind':item['kind'],'title':item['title'],'x':100+index*380,'y':80,'width':340,'height':260,'pinned':False,
                'source':{'system':'ontovis','ontobaseConnectionId':CONNECTION,'projectCode':'Demo-PDS','id':ref['evidenceRefId'],'revision':ref['sourceRevision']}})
        value['context'].update({key:dataset[key] for key in ('faultCode','sourceConnectionId','branch','datasetId','datasetRevision','timeFrom','timeTo')},eventId=alarm['selector']['eventId'])
        saved=self.save(created,value)
        reopened=self.demo.detail(OWNER,created['analysisSessionId'],lambda:None)
        self.assertEqual(saved['analysisRevision'],2);self.assertEqual(reopened['snapshot'],value)
        self.assertEqual(reopened['snapshot']['context']['faultCode'],'13002')
        wrong=deepcopy(value);wrong['context']['faultCode']='13001'
        with self.assertRaises(PreviewError):self.save(saved,wrong)

    def test_event_resume_recurrence_history_and_layout_are_independent(self):
        self.demo=self.consumer(project='Demo-PDS');a=self.start();self.assertEqual(len(a['snapshot']['cards']),5)
        self.assertEqual(self.start()['analysisSessionId'],a['analysisSessionId'])
        old=deepcopy(a['snapshot']);old['cards'][-1].update(note='记录：模拟温度偏差；现场尚需核实',checkState='done',width=960,height=700)
        saved=self.save(a,old);b=self.start(recurrence=True)
        self.assertNotEqual(a['analysisSessionId'],b['analysisSessionId']);self.assertTrue(b['historyImported'])
        historical=[c for c in b['snapshot']['cards'] if c.get('historical')]
        self.assertEqual(len(historical),5);self.assertEqual(historical[-1]['width'],960);self.assertEqual(historical[-1]['note'],old['cards'][-1]['note'])
        current=[c for c in b['snapshot']['cards'] if not c.get('historical')]
        self.assertEqual(current[-1]['checkState'],'not_started');self.assertEqual(current[-1]['note'],'')
        self.assertEqual(self.demo.detail(OWNER,a['analysisSessionId'],lambda:None)['contentSha256'],saved['contentSha256'])
        original_refs={c['source']['id'] for c in old['cards'] if c.get('source')}
        self.assertTrue(original_refs.isdisjoint({c['source']['id'] for c in historical if c.get('source')}))
        self.assertEqual(self.start(recurrence=True)['analysisSessionId'],b['analysisSessionId'])

    def test_foreign_handles_and_forged_fault_context_cannot_be_saved(self):
        self.demo=self.consumer(project='Demo-PDS');a=self.start();b=self.start(recurrence=True)
        altered=deepcopy(b['snapshot']);altered['cards'][0]['source']=a['snapshot']['cards'][0]['source']
        with self.assertRaises(PreviewError):self.save(b,altered)
        altered=deepcopy(b['snapshot']);altered['context']['faultCode']='13004'
        with self.assertRaises(PreviewError):self.save(b,altered)
        altered=deepcopy(b['snapshot']);next(c for c in altered['cards'] if c['kind']=='analysis' and c.get('historical'))['note']='forged history'
        with self.assertRaises(PreviewError):self.save(b,altered)
        other=self.start(actor=OTHER);self.assertNotEqual(other['analysisSessionId'],a['analysisSessionId']);self.assertFalse(other['historyImported'])

    def test_removing_context_cards_keeps_owned_citations_and_copy_survives_restore(self):
        self.demo=self.consumer(project='Demo-PDS');a=self.start();value=deepcopy(a['snapshot']);value['cards']=[value['cards'][-1]]
        self.save(a,value)
        body={'analysisSessionId':a['analysisSessionId'],'snapshot':value,'requestId':str(uuid4())}
        copied=copy_analysis(self.demo,OWNER,body,lambda:None)
        self.assertNotEqual(copied['analysisSessionId'],a['analysisSessionId'])
        self.assertEqual(copy_analysis(self.demo,OWNER,body,lambda:None),copied)
        receipt=backup.snapshot(self.urls[0],self.root/'canvas');backup.restore_new(self.root/'canvas',receipt['manifestSha256'],self.urls[1])
        recovered=self.consumer(self.urls[1],project='Demo-PDS').detail(OWNER,copied['analysisSessionId'],lambda:None)
        self.assertEqual(recovered['snapshot'],value)

    def test_no_source_context_without_registered_event_and_no_implicit_confirmation(self):
        self.demo=self.consumer(project='Demo-PDS');a=self.start();value=deepcopy(a['snapshot']);value['status']='concluded'
        with self.assertRaises(PreviewError):self.save(a,value)
        value=deepcopy(a['snapshot']);value['context']['eventId']='not-registered'
        with self.assertRaises(PreviewError):self.save(a,value)

    def test_import_choice_keeps_current_work_unsaved_and_blocks_other_owner(self):
        from apps.api.analysis_queries import import_history
        self.demo=self.consumer(project='Demo-PDS');first=self.start();current=self.start(recurrence=True)
        changed=deepcopy(current['snapshot']);next(c for c in changed['cards'] if c['kind']=='analysis' and not c.get('historical'))['note']='local unsaved work'
        body={'analysisSessionId':current['analysisSessionId'],'expectedAnalysisRevision':current['analysisRevision'],'snapshot':changed,
            'historySessionId':first['analysisSessionId'],'historyRevision':first['analysisRevision'],'requestId':str(uuid4())}
        loaded=import_history(self.demo,OWNER,body,lambda:None)
        self.assertEqual(next(c for c in loaded['snapshot']['cards'] if c['kind']=='analysis' and not c.get('historical'))['note'],'local unsaved work')
        self.assertEqual(self.demo.detail(OWNER,current['analysisSessionId'],lambda:None)['contentSha256'],current['contentSha256'])
        self.save(current,loaded['snapshot'])
        with self.assertRaises(PreviewError):import_history(self.demo,OTHER,body,lambda:None)

    def test_repeated_fixed_registration_reuses_owned_handle(self):
        from apps.api.analysis_evidence import AnalysisEvidence
        self.demo=self.consumer(project='Demo-PDS');value=self.start();card=value['snapshot']['cards'][0];sources=AnalysisEvidence(self.demo)
        _,selector=sources.descriptor(OWNER,{'analysisSessionId':value['analysisSessionId'],'evidenceRefId':card['source']['id']},lambda:None)
        registered=sources.register(OWNER,{'analysisSessionId':value['analysisSessionId'],'expectedAnalysisRevision':value['analysisRevision'],
            'requestId':str(uuid4()),'sourceKind':'alarm','selector':selector},lambda:None,lambda kind,selected:selected)
        self.assertEqual(registered['evidenceRefId'],card['source']['id'])

    def test_reused_alias_request_is_immutable_and_backup_validates_its_target(self):
        from apps.api.analysis_evidence import AnalysisEvidence
        self.demo=self.consumer(project='Demo-PDS');value=self.start();card=value['snapshot']['cards'][0];sources=AnalysisEvidence(self.demo)
        _,selector=sources.descriptor(OWNER,{'analysisSessionId':value['analysisSessionId'],'evidenceRefId':card['source']['id']},lambda:None)
        body={'analysisSessionId':value['analysisSessionId'],'expectedAnalysisRevision':value['analysisRevision'],'requestId':str(uuid4()),'sourceKind':'alarm','selector':selector}
        result=sources.register(OWNER,body,lambda:None,lambda kind,selected:selected)
        self.assertEqual(sources.register(OWNER,body,lambda:None,lambda *_:None),result)
        with self.assertRaises(PreviewError):sources.register(OWNER,{**body,'expectedAnalysisRevision':1},lambda:None,lambda *_:None)
        package=backup.export_package(self.urls[0]);backup.validate_package(package)
        invalid=deepcopy(package)
        import json
        row=next(row for row in invalid['tables']['analysis_requests'] if json.loads(row['result_json']).get('operation')=='evidence/register')
        data=json.loads(row['result_json']);data['evidenceRefId']=str(uuid4());row['result_json']=draft.canonical(data)
        with self.assertRaises(PreviewError):backup.validate_package(invalid)
