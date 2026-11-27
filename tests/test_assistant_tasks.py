"""Concrete project search, bounded orchestration and atomic draft actions."""
import copy
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
from tests import test_work_orders as orders_fixture
from tests.test_assistant import answer
from apps.api.assistant_service import AssistantRuntime
from apps.api.assistant_store import DEFAULT,digest
from apps.api.assistant_tasks import (PROTOCOL,ProjectTools,read_selected_evidence,related_object_add_request,
    related_object_answer,contextual_addition,canonical_additions,disposition_request,turn_requests,validate_plan,snapshot)
from apps.api.assistant_canvas_tasks import build,load,retain,acknowledge,validate_draft_plan
from apps.api.assistant_drawings import drawing_add_scope, drawing_answer, drawing_context, checked_drawing_results
from apps.api.assistant_alarm_materials import LinkedMaterials, checked_additions, linked_add_scope, linked_anchor, plan_addition
from apps.api.authority import PreviewError
from apps.api.scene_engineering import SceneEngineeringReader


def board():return dict(schemaVersion=2,ontobaseConnectionId='source',projectCode='Demo-PDS',title='Synthetic acceptance',status='analyzing',
    context=dict(objectIds=[],timeFrom='2026-01-01T00:00:00Z',timeTo='2026-01-02T00:00:00Z',timezone='UTC'),
    cards=[],relations=[],viewport=dict(x=0,y=0,zoom=1))


def action(kind,targets=None,text=''):return dict(kind=kind,targets=targets or [],text=text,x=None,y=None)


class LinkedMaterialIntentTests(unittest.TestCase):
    def test_mixed_add_finds_registered_descendant_drawings_and_checks_revision_on_apply(self):
        alarm = {'eventId':'event'}
        anchor = (dict(evidenceRefId='alarm', sourceKind='alarm', sourceRevision=digest(alarm)), alarm)
        draft = board()
        draft['cards'] = [dict(id='alarm', kind='alarm', source=dict(id='alarm'))]
        draft['context']['eventId'] = 'event'
        body = dict(focusCardIds=['alarm'])
        record = dict(item=dict(entityUid='cabinet', entityRevision='r1', displayName='合成柜体'))
        engineering = Mock(spec=SceneEngineeringReader, project_code='Demo-PDS', authority=SimpleNamespace(image=Mock()))
        reader = SimpleNamespace(read=Mock(return_value=dict(dataset={'primaryRds':'=TEST+CAB'})),
                                 _rds=Mock(return_value=record), reader=engineering)
        tools = ProjectTools(reader, lambda:None, {'alarm','object','drawing','photo'}, ())
        scope = linked_add_scope('加入工程对象、图纸、照片')
        plan = dict(intent='edit', actions=[])
        row = dict(drawingUid='child-page', title='下级接线图', availability='available', pageNumber=6,
                   sourceRevision='a'*64, contentSha256='b'*64, matchedObjects=[dict(relation='definition_descendant')])
        shared = dict(documentId=str(uuid4()), contentVersionId=str(uuid4()), title='柜体侧面', availability='available')
        reader.photos = SimpleNamespace(resolve=Mock(return_value={'items':[]}))
        reader.reader.prefix = '/api/v1/projects/Demo-PDS'
        reader.reader._request = Mock(return_value=dict(projectCode='Demo-PDS', items=[shared], nextCursor=None))
        with (patch('apps.api.scene_evidence.SceneEvidenceReader.resolve', return_value={'items':[]}),
              patch('apps.api.related_drawings.RelatedDrawingsReader.resolve',
                    return_value=dict(items=[row], nextCursor='more')) as related):
            plan_addition(tools, [anchor], draft, anchor, plan, set(), linked=scope)
            self.assertEqual(['object','drawing','photo'], [item['kind'] for item in tools.results])
            drawing = tools.results[1]
            self.assertEqual({'drawingUid':'child-page','expectedContentSha256':'b'*64}, drawing['selector'])
            self.assertIn('下级对象关联的图纸 · 整页', drawing['reason'])
            self.assertEqual('a'*64, drawing['version'])
            self.assertEqual([], plan['actions'])
            self.assertTrue(any(entry.get('truncated') for entry in tools.trace))
            requested = dict(actions=[action('add_results',[drawing['key']])])
            self.assertEqual({}, checked_additions(reader, [anchor], draft, body, tools.allowed, set(),
                requested, tools.results, linked=scope, anchor_ref='alarm'))
            self.assertTrue(all(call.args[0]['includeDescendants'] for call in related.call_args_list))
            row['sourceRevision'] = 'c'*64
            with self.assertRaises(PreviewError) as error:
                checked_additions(reader, [anchor], draft, body, tools.allowed, set(),
                                  requested, tools.results, linked=scope, anchor_ref='alarm')
            self.assertEqual('ASSISTANT_LINKED_MATERIALS_CHANGED', error.exception.code)

    def test_verified_batch_rule_is_independent_of_material_type(self):
        from apps.api.assistant_canvas_tasks import plan_candidate_additions
        for kind, count, complete, automatic in (
            ('object',3,True,True), ('drawing',3,True,True), ('photo',4,True,True),
            ('object',3,False,False), ('drawing',3,False,False), ('drawing',12,True,False),
        ):
            with self.subTest(kind=kind,count=count,complete=complete):
                plan=dict(intent='edit',actions=[])
                answer=dict(nextSteps=[],gaps=[])
                rows=[dict(kind=kind,key=f'R{i+1}') for i in range(count)]
                plan_candidate_additions(board(),plan,rows,answer,complete=complete)
                self.assertEqual([action('add_results',[row['key'] for row in rows])] if automatic else [],plan['actions'])
                if not automatic:
                    self.assertIn('全部加入',answer['nextSteps'][0]['text'])

    def test_photo_request_uses_the_fixed_object_of_a_focused_drawing(self):
        from apps.api.assistant_alarm_materials import _material_object_source
        draft=board()
        draft['cards']=[dict(id=kind,kind=kind,source=dict(id=kind)) for kind in ('alarm','drawing')]
        scope=dict(entityUid='module',expectedEntityRevision='r2',installationContextId=None,expectedHierarchyRevision=None)
        drawing=dict(evidenceRef='location:module',expectedSourceRevision='a'*64,expectedContentSha256='b'*64,**scope)
        fixed=[(dict(evidenceRefId=kind,sourceKind=kind),desc) for kind,desc in (('alarm',dict(eventId='event')),('drawing',drawing))]
        body=dict(focusCardIds=['drawing'])
        self.assertEqual(fixed[1],linked_anchor(fixed,draft,body,'canvas',{'photo'}))
        self.assertEqual(fixed[0],linked_anchor(fixed,draft,body,'alarm',{'photo'}))
        reader=SimpleNamespace(read=Mock())
        self.assertEqual(scope,_material_object_source(reader,'drawing',drawing,{'object'},lambda fn:fn()))
        reader.read.assert_called_once_with('drawing',drawing)
        self.assertIsNone(linked_anchor(fixed[:1]+[(fixed[1][0],dict(drawingUid='unscoped'))],draft,body,'canvas',{'photo'}))

    def test_material_lists_keep_the_requested_types_and_canvas_scope(self):
        pair=frozenset(('object','drawing'))
        all_types=pair|{'photo','document'}
        for question,scope in (
            ('添加工程对象和图纸','canvas'),
            ('请将与这条报警直接相关的工程对象及对应电气图纸一起加到当前画布','alarm'),
            ('把图纸、工程对象一并加入画布。','canvas'),
            ('加入工程对象，图纸','canvas'),
            ('Add the related engineering objects and their drawings for this alarm to the canvas.','alarm'),
            ('列出工程对象和图纸',None),
            ('不要添加工程对象和图纸',None),
            ('添加工程对象 +CN1-1U2 和图纸',None),
        ):
            with self.subTest(question=question):
                self.assertEqual(LinkedMaterials(scope,pair) if scope else None,linked_add_scope(question))
        for question in ('添加工程对象、图纸、文档、照片','请把照片和手册、工程对象以及电气图纸一起加入画布',
                         'Add photos, engineering objects, manuals, and drawings to the canvas.'):
            self.assertEqual(LinkedMaterials('canvas',all_types),linked_add_scope(question),question)
        self.assertEqual(LinkedMaterials('alarm',frozenset(('photo','document'))),
                         linked_add_scope('加入这次报警的照片和手册'))
        self.assertEqual(LinkedMaterials('alarm',all_types),linked_add_scope('请给当前报警一并添加工程对象、图纸、文档和照片'))
        self.assertEqual((None,None,LinkedMaterials('canvas',pair),True),contextual_addition('先加上工程对象和图纸，然后整理布局'))
        edit,advice=turn_requests('加入工程对象和图纸，再给出处置方案')
        self.assertTrue(advice)
        self.assertEqual((None,None,LinkedMaterials('canvas',pair),False),contextual_addition(edit))

    def test_operation_card_takes_priority_and_ambiguous_alarms_need_a_selection(self):
        draft=board()
        draft['cards']=[dict(id=name,kind=kind,source=dict(id=name)) for name,kind in (
            ('first','alarm'),('second','alarm'),('selected','object'))]
        fixed=[(dict(evidenceRefId=name,sourceKind=kind),dict(eventId=name)) for name,kind in (
            ('first','alarm'),('second','alarm'),('selected','object'))]
        self.assertIsNone(linked_anchor(fixed,draft,{},'canvas'))
        draft['context']['eventId']='first'
        self.assertEqual(fixed[0],linked_anchor(fixed,draft,{},'canvas'))
        choice=dict(focusCardIds=['selected'],preferSelectedEvidence=True,evidenceRefIds=['first'])
        self.assertEqual(fixed[2],linked_anchor(fixed,draft,choice,'canvas'))
        self.assertEqual(fixed[0],linked_anchor(fixed,draft,choice,'alarm'))
        self.assertIsNone(linked_anchor(fixed,draft,{'focusCardIds':['first','second']},'canvas'))


class DrawingTaskTests(unittest.TestCase):
    def setUp(self):
        self.board = board()
        self.board['context']['eventId'] = 'current-event'
        sources = [('alarm', 'alarm'), ('object', 'target'), ('object', 'other'),
                   ('drawing', 'retained'), ('document', 'manual'), ('object', 'past')]
        self.board['cards'] = [dict(kind=kind, title=ref, source=dict(id=ref), historical=ref=='past') for kind, ref in sources]
        self.body = dict(question='添加相关图纸', evidenceRefIds=['alarm'])
        self.target = dict(entityUid='protector', expectedEntityRevision='r1', installationContextId=None,
                           expectedHierarchyRevision=None)
        self.other = {**self.target, 'entityUid': 'other'}
        self.retained = dict(drawingUid='previous-evidence', expectedContentSha256='a'*64)
        descriptors = dict(alarm={'eventId': 'current-event'}, target=self.target, other=self.other, retained=self.retained)
        self.fixed = [(dict(evidenceRefId=ref, sourceKind=kind), descriptors[ref]) for kind, ref in sources if ref in descriptors]
        self.reader = SimpleNamespace(read=Mock(return_value={'dataset': {'primaryRds': '=WEC+CN1-1U2'}}),
            _rds=Mock(return_value={'item': {'entityUid': 'protector', 'entityRevision': 'r1'}, 'context': None}))
        self.tools = ProjectTools(self.reader, lambda: None,DEFAULT['allowedKinds'], ())
        self.plan = dict(intent='edit', queries=[], actions=[])

    def row(self, uid, page, content_hash='a'*64):
        return dict(drawingUid=uid, title=uid, pageNumber=page, availability='available', contentSha256=content_hash,
                    sourceRevision='b'*64, matchedObjects=[{'relation': 'self'}])

    def test_drawing_requests_and_context_are_specific_to_the_current_canvas(self):
        for question, scope in [('添加相关图纸', 'canvas'), ('请把本次报警相关的图纸加到画布', 'alarm'),
                                ('Add the related drawings to the canvas.', 'canvas'),
                                ('把图纸和照片都加上', None), ('列出与报警相关的图纸', None)]:
            self.assertEqual(scope, drawing_add_scope(question), question)
        self.assertEqual(['alarm', 'target', 'other', 'retained'], drawing_context(self.body, self.board)['evidenceRefIds'])
        self.assertEqual(['alarm'], self.body['evidenceRefIds'])
        self.assertEqual(('canvas', None, None, True),contextual_addition('先添加相关图纸，再整理画布布局'))
        self.assertEqual((None, 'alarm', None, True),contextual_addition('加入本次报警的工程对象并整理布局'))
        self.assertEqual((None, None, None, False),contextual_addition('添加笔记，正文是“添加相关图纸”'))

    def test_additions_use_the_alarm_object_and_deduplicate_fixed_pages(self):
        first = self.row('previous-evidence', 89)
        new = self.row('new-page', 90)
        with patch('apps.api.assistant_drawings._recorded_drawings', return_value={
                'items': [first, {**first, 'drawingUid': 'alias'}, new], 'nextCursor': None}) as read:
            drawing_answer(self.tools, self.fixed, self.board, self.body, 'canvas', self.plan)
            read.assert_called_once_with(self.reader, self.target)
            candidate, = self.tools.results
            self.assertEqual(('drawing', 'new-page', 'target'), (candidate['kind'], candidate['identifier'], candidate['drawingObjectRefId']))
            self.assertEqual([action('add_results', ['R1'])], self.plan['actions'])
            self.assertEqual([candidate], checked_drawing_results(self.reader, self.fixed, self.board, self.body,
                'canvas', self.tools.allowed, self.plan, self.tools.results))
            compound={**self.plan,'actions':self.plan['actions']+[action('arrange')]}
            self.assertEqual([candidate], checked_drawing_results(self.reader, self.fixed, self.board, self.body,
                'canvas', self.tools.allowed, compound, self.tools.results, compound=True))
            read.return_value = {'items': [first], 'nextCursor': None}
            with self.assertRaises(PreviewError) as changed:
                checked_drawing_results(self.reader, self.fixed, self.board, self.body,
                    'canvas', self.tools.allowed, self.plan, self.tools.results)
            self.assertEqual('ASSISTANT_DRAWING_REVIEW_REQUIRED', changed.exception.code)

    def test_explicit_object_and_incomplete_drawings_offer_only_verified_choices(self):
        body = {**self.body, 'preferSelectedEvidence': True, 'evidenceRefIds': ['other']}
        with patch('apps.api.assistant_drawings._recorded_drawings', return_value={
                'items': [self.row('other-drawing', 42, 'c'*64)], 'nextCursor': 'page-two'}) as read:
            answer = drawing_answer(self.tools, self.fixed, self.board, body, 'canvas', self.plan)
            read.assert_called_once_with(self.reader, self.other)
        self.reader._rds.assert_not_called()
        self.assertEqual([], self.plan['actions'])
        self.assertEqual(['drawing'], [row['kind'] for row in self.tools.results])
        self.assertTrue(answer['nextSteps'])

    def test_alarm_without_an_object_card_uses_the_registered_drawing_scope(self):
        fixed = [row for row in self.fixed if row[0]['sourceKind']=='alarm']
        draft = {**self.board, 'cards': self.board['cards'][:1]}
        with patch('apps.api.assistant_drawings._recorded_drawings', return_value={
                'items': [self.row('fixed-drawing', 42)], 'nextCursor': None}) as read:
            drawing_answer(self.tools, fixed, draft, self.body, 'canvas', self.plan)
            read.assert_called_once_with(self.reader, self.target)
            candidate, = self.tools.results
            self.assertEqual(('drawing', 'alarm'), (candidate['kind'], candidate['drawingObjectRefId']))
            self.assertEqual([action('add_results', ['R1'])], self.plan['actions'])
            # Adding the target object before application leaves the alarm-based result valid.
            self.assertEqual([candidate], checked_drawing_results(self.reader, self.fixed, self.board, self.body,
                'canvas', self.tools.allowed, self.plan, self.tools.results))

    def test_unresolved_alarm_object_does_not_search_the_project_catalogue(self):
        fixed = [row for row in self.fixed if row[0]['evidenceRefId']!='target']
        self.reader._rds.side_effect = PreviewError(409, 'DIAGNOSTIC_OBJECT_UNRESOLVED')
        with patch('apps.api.assistant_drawings._recorded_drawings') as read:
            answer = drawing_answer(self.tools, fixed, self.board, self.body, 'canvas', self.plan)
        read.assert_not_called()
        self.assertIn('暂未找到可加入的图纸', answer['observations'][0]['text'])
        self.assertEqual([], self.plan['actions'])
        self.assertEqual([], self.tools.results)


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.fixture=orders_fixture.WorkOrderTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.fixture.seed()
        self.orders=self.fixture.orders;self.library=self.fixture.library;self.actor=str(uuid4())
        self.reader=SimpleNamespace(orders=self.orders,reader=SimpleNamespace(prefix='/api/v1/projects/Demo-PDS'))
    def search(self,fault='13001',cursor=0,revision=None):
        return self.orders.assistant_search(dict(q='',faultCode=fault,cursor=cursor,limit=2,snapshotRevision=revision))

    def test_related_object_add_requests_do_not_replace_named_object_search(self):
        for question, scope in [('加入相关的工程对象', 'canvas'), ('请把当前报警涉及的工程对象加入画布。', 'alarm'),
                                ('添加本次报警的所有工程对象', 'alarm'), ('加入名为“浪涌保护”的工程对象', None),
                                ('加入相关工程对象并保存画布', None)]:
            self.assertEqual(scope, related_object_add_request(question), question)

    def test_related_objects_keep_selected_scope_and_do_not_auto_add_a_missing_source(self):
        from apps.api.simulated_faults import identity
        dataset = identity('13003')
        primary = dataset['primaryRds']
        def lookup(tag):
            if tag != primary:
                raise PreviewError(409,'DIAGNOSTIC_OBJECT_UNRESOLVED')
            return {'item':dict(entityUid=tag,entityRevision='r1',displayName=tag)}
        reader = SimpleNamespace(read=Mock(return_value={'dataset': dataset}),_rds=Mock(side_effect=lookup))
        ref = dict(sourceKind='alarm', evidenceRefId='fixed-alarm')
        fixed = [(ref, {'eventId': dataset['datasetId']+'-event-1'})]
        draft = board()
        draft['cards'] = [dict(source={'id': 'fixed-alarm'})]
        plan = dict(intent='edit', queries=[], actions=[])
        limited = ProjectTools(reader, lambda: None, ['alarm', 'object'], ())
        result = related_object_answer(limited, fixed, draft, 'canvas', plan)
        self.assertEqual([], plan['actions'])
        self.assertEqual(primary, limited.results[0]['selector']['entityUid'])
        self.assertEqual('unavailable', limited.trace[0]['state'])
        self.assertTrue(result['nextSteps'])
        self.assertTrue(related_object_answer(limited, [], draft, 'alarm', plan)['gaps'])
        self.assertGreater(limited.reads,2)
    def test_exact_filter_before_paging_and_snapshot_rejects_change(self):
        first=self.search();self.assertEqual(3,first['total']);self.assertTrue(all(r['faultCode']=='13001' for r in first['items']))
        second=self.search(cursor=first['nextCursor'],revision=first['snapshotRevision']);self.assertEqual(1,len(second['items']))
        self.assertFalse(set(r['orderId'] for r in first['items'])&set(r['orderId'] for r in second['items']))
        self.assertEqual(0,self.search('130')['total'])
        with self.assertRaises(PreviewError):self.search(cursor=2,revision='changed')
        row=first['items'][0]
        one=self.orders.assistant_search(dict(q='',faultCode='13001',orderId=row['orderId'],cursor=0,limit=6,snapshotRevision=None))
        self.assertEqual(1,one['total']);self.assertEqual(row['orderId'],one['items'][0]['orderId'])

    def test_model_prose_does_not_narrow_an_exact_fault_or_order_filter(self):
        tools=ProjectTools(self.reader,lambda:None,DEFAULT['allowedKinds'],())
        tools.query(dict(tool='work_orders',query='查找本项目所有故障代码为13001的历史工单，仅限模拟记录，不限制历史时间，不确认相同根因。',faultCode='13001',orderId=''))
        self.assertEqual(3,len(tools.results));self.assertEqual('',tools.trace[0]['filters']['query'])
        selected=tools.results[0]['identifier'];other=ProjectTools(self.reader,lambda:None,DEFAULT['allowedKinds'],())
        other.query(dict(tool='work_orders',query='只加入这一个编号，不确认同根因',faultCode='13001',orderId=selected))
        self.assertEqual([selected],[r['identifier'] for r in other.results])
    def test_removed_card_still_found_fixed_identity_and_duplicate_are_preserved(self):
        tools=ProjectTools(self.reader,lambda:None,DEFAULT['allowedKinds'],())
        tools.query(dict(tool='work_orders',query='',faultCode='13001'))
        self.assertEqual(3,len(tools.results));self.assertEqual(3,tools.reads)
        self.assertIn('orderId',tools.sources[1]['summary']);self.assertIn('测试',tools.sources[1]['summary'])
        target=tools.results[0];calls=[]
        def register(row,index):calls.append(row);return dict(evidenceRefId=str(uuid4()),sourceRevision='a'*64)
        plan=dict(actions=[action('add_results',[target['key']])])
        original=board();added,receipts,_=build(original,plan,tools.results,register,str(uuid4()),'source','Demo-PDS')
        self.assertFalse(original['cards']);self.assertEqual('added',receipts[0]['status']);self.assertTrue(receipts[0]['simulated'])
        same,receipts,_=build(added,plan,tools.results,register,str(uuid4()),'source','Demo-PDS')
        self.assertEqual(1,len(same['cards']));self.assertEqual('already_present',receipts[0]['status'])
        removed=copy.deepcopy(added);removed['cards']=[]
        restored,_,_=build(removed,plan,tools.results,register,str(uuid4()),'source','Demo-PDS');self.assertEqual(1,len(restored['cards']))
    def test_bad_action_is_atomic_and_historical_notes_not_editable(self):
        original=board();plan=dict(actions=[action('add_note',text='kept only in candidate'),action('remove_cards',['invented'])])
        with self.assertRaises(PreviewError):build(original,plan,[],None,str(uuid4()),'source','Demo-PDS')
        self.assertFalse(original['cards'])
        original['cards']=[dict(id='old',kind='analysis',title='old',note='n',x=0,y=0,width=300,height=200,pinned=False,historical=True)]
        with self.assertRaises(PreviewError):build(original,dict(actions=[action('remove_cards',['C1'])]),[],None,str(uuid4()),'source','Demo-PDS')

    def test_ordered_edits_can_address_new_cards_and_stale_targets_fail_before_execution(self):
        original=board()
        run=str(uuid4())
        plan=dict(actions=[action('add_note',text='供电核查'),action('copy_card',['C1']),
            action('rename_card',['C2'],'现场记录'),action('append_note',['C2'],'。待现场复核'),
            action('group_cards',['C1','C2'],'核查依据'),action('pin_cards',['C1']),
            action('add_reference',['C1','C2'],'人工核对依据')])
        validate_draft_plan(original,plan,[],[],{},0,run,'source','Demo-PDS')
        draft,receipts,save=build(original,plan,[],None,run,'source','Demo-PDS')
        self.assertFalse(save or original['cards'])
        self.assertEqual(7,len(receipts))
        first,second=draft['cards']
        self.assertTrue(first['pinned'])
        self.assertEqual(first['frameId'],second['frameId'])
        self.assertEqual(('现场记录','供电核查。待现场复核'),(second['title'],second['note']))
        self.assertEqual((first['id'],second['id']), (draft['relations'][0]['from'],draft['relations'][0]['to']))
        with self.assertRaises(PreviewError) as stale:
            validate_draft_plan(original,{**plan,'actions':plan['actions']+[action('remove_cards',['C9'])]},
                [],[],{},0,run,'source','Demo-PDS')
        self.assertEqual('ASSISTANT_TARGET_AMBIGUOUS',stale.exception.code)

    def test_additions_require_a_literal_match_or_exact_identity_and_never_use_a_wildcard(self):
        results=[dict(key='R1',identifier='object-one',kind='object',title='+CN1-1U2',selector={'entityUid':'object-one'}),
                 dict(key='R2',identifier='document-two',kind='document',title='工程手册',selector={'documentId':'document-two'})]
        plan=dict(actions=[action('add_results'),action('arrange')])
        canonical_additions(plan,results,'将 +CN1-1U2 加入画布，再整理布局')
        self.assertEqual(['R1'],plan['actions'][0]['targets'])
        for question,keys in [('加一些相关资料',[]),('添加建议的资料',['R2']),('添加工程手册的图纸',['document-two'])]:
            with self.subTest(question=question),self.assertRaises(PreviewError):
                canonical_additions(dict(actions=[action('add_results',keys)]),[results[0],{**results[1], 'title':'供电图'}],
                                    question if keys!=['document-two'] else '添加供电图纸')
        register=Mock()
        with self.assertRaises(PreviewError):
            build(board(),dict(actions=[action('add_results')]),results,register,str(uuid4()),'source','Demo-PDS')
        register.assert_not_called()

    def test_disposition_intent_distinguishes_advice_from_note_edits(self):
        for question in ('基于当前画布生成整体处置建议','结合历史工单和手册给出完整的处置流程','这次故障该怎么处理？',
                         'Generate an overall response plan from this canvas'):
            self.assertTrue(disposition_request(question),question)
        for question in ('新增笔记，内容为生成整体处置建议','把「整体处置建议」移到左侧','查询相关工单'):
            self.assertFalse(disposition_request(question),question)
        self.assertEqual(('',True),turn_requests('基于当前画布，生成整体处置建议'))
        self.assertEqual(('加入报警相关资料卡片',True),turn_requests('加入报警相关资料卡片，再分析处置方案'))
        self.assertEqual(('新增笔记「核查后，再记录」',True),turn_requests('新增笔记「核查后，再记录」，并分析处置方案'))
    def test_foreign_scope_query_write_injection_and_arbitrary_tools_rejected(self):
        with self.assertRaises(PreviewError):snapshot(dict(snapshotJson=json.dumps(board())),'other','Demo-PDS')
        for plan in [dict(intent='query',queries=[],actions=[action('save')]),dict(intent='edit',queries=[dict(tool='http',query='x',faultCode='')],actions=[]),
                     dict(intent='edit',queries=[],actions=[action('run_sql')])]:
            with self.assertRaises(PreviewError):validate_plan(plan)

    def test_scene_directory_needs_an_advertised_read_only_tool(self):
        entry = dict(tool='scenes', query='Crystal Rig', faultCode='', orderId='')
        plan = dict(intent='query', queries=[entry], actions=[])
        with self.assertRaises(PreviewError):
            validate_plan(plan)
        self.assertEqual(plan, validate_plan(plan, scene_directory=True))
        for invalid in ({**plan, 'intent': 'edit'},
                        {**plan, 'queries': [{**entry, 'faultCode': '13001'}]}):
            with self.assertRaises(PreviewError):
                validate_plan(invalid, scene_directory=True)

    def test_scene_directory_returns_one_bounded_authorized_read(self):
        entry = dict(tool='scenes', query='Crystal Rig', faultCode='', orderId='')
        scene_id, revision = str(uuid4()), 'scene:' + str(uuid4())
        listing = self.reader.scene_listing = Mock(return_value={
            'items': [dict(sceneId=scene_id, displayName='Crystal Rig', headRevision=revision, instanceCount=91)],
            'snapshotRevision': 'directory:1', 'nextCursor': 'more-scenes',
        })
        denied = ProjectTools(self.reader, lambda: None, ['work_order'], ())
        with self.assertRaises(PreviewError):
            denied.query(entry)
        listing.assert_not_called()
        guard = Mock()
        allowed = ProjectTools(self.reader, guard,['model'], ())
        allowed.query(entry)
        listing.assert_called_once_with('Crystal Rig')
        self.assertEqual(2, guard.call_count)
        self.assertEqual(1, allowed.reads)
        result = allowed.results[0]
        self.assertEqual(('scene', scene_id, revision, 91),
                         (result['kind'], result['identifier'], result['version'], result['instanceCount']))
        self.assertNotIn('selector', result)
        self.assertTrue(allowed.trace[0]['truncated'])
        self.assertNotIn('nextCursor', allowed.trace[0])
        self.assertEqual('directory:1', allowed.sources[0]['retrievalRevision'])
        summary = allowed.sources[0]['summary']
        self.assertNotIn(scene_id, summary)
        self.assertNotIn(revision, summary)
        self.assertEqual([dict(name='Crystal Rig', version=revision[6:14], instances=91)],
                         json.loads(summary)['items'])

    def test_project_knowledge_enters_fixed_release_and_keeps_pages_and_edge_provenance(self):
        from tests.test_assistant_knowledge import response
        from apps.api.analysis_preview import OB
        graph=dict(project_code='P',nodes=[dict(kind='FaultDefinition',payload=dict(properties={OB+'fault_code':[dict(value='13002')],
            OB+'title':[dict(value='机舱柜温度低')]}),source=dict(document=dict(id='document'),version=dict(id='version'),release_id='release',local_id='root'))],relations=[],next_cursor=None)
        reader=SimpleNamespace(reader=SimpleNamespace(prefix='/api/v1/projects/P',project_code='P',_request=lambda *_:graph))
        tools=ProjectTools(reader,lambda:None,['document'],())
        with patch('apps.api.fixed_documents.FixedDocuments.metadata',return_value=dict(sourceSha256='a'*64)),\
             patch('apps.api.analysis_preview.node_evidence',return_value=dict(items=[dict(selector=dict(page=49))])),\
             patch('apps.api.assistant_knowledge.read_neighborhood',return_value=response()):
            tools.query(dict(tool='knowledge',query='',faultCode='13002'))
        self.assertEqual(4,tools.reads);self.assertIn('检查',tools.sources[-1]['summary'])
        edge=tools.graphs[-1]['graph']['relations'][0]
        self.assertEqual(49,edge['provenance']['pageNumber']);self.assertEqual('release/a',edge['provenance']['recordId'])
        graph['next_cursor']=1
        paged=ProjectTools(reader,lambda:None,['document'],())
        with patch('apps.api.fixed_documents.FixedDocuments.metadata',return_value=dict(sourceSha256='a'*64)),\
             patch('apps.api.analysis_preview.node_evidence',return_value=dict(items=[dict(selector=dict(page=49))])),\
             patch('apps.api.assistant_knowledge.read_neighborhood',return_value=response()):
            paged.query(dict(tool='knowledge',query='',faultCode='13002'))
        self.assertEqual(2,len(paged.graphs));self.assertEqual(1,paged.trace[0]['nextCursor'])
        self.assertIn('其他分页未读取',paged.trace[-1]['scope'])

    def test_graph_resolves_exact_project_identifier_before_fuzzy_children(self):
        from urllib.parse import parse_qs,urlsplit
        from tests.test_assistant_graph import graph
        row=dict(entityUid='root',entityRevision='i:1',displayName='柜体',identifiers=[dict(value='=WEC+CN1',role='primary',
            status='accepted',scheme='RDS',scopeType='project',scopeKey='P')])
        calls=[]
        def request(method,path):
            calls.append(parse_qs(urlsplit(path).query))
            return dict(projectCode='P',items=[row],nextCursor=None)
        source=SimpleNamespace(prefix='/api/v1/projects/P',project_code='P',_request=request,
            context_for_object=lambda *_:dict(item=row,context=None))
        tools=ProjectTools(SimpleNamespace(reader=source),lambda:None,['object'],())
        with patch('apps.api.assistant_graph.read_graph',return_value=graph()):
            tools.query(dict(tool='graph',query='=WEC+CN1',faultCode=''))
        self.assertEqual([{'primaryIdentifier':['=WEC+CN1'],'limit':['6']}],calls)
        self.assertEqual(3,tools.reads);self.assertEqual('engineering',tools.graphs[0]['kind'])
        self.assertEqual('primary_identifier',tools.trace[0]['match'])
        calls.clear()
        source._request=lambda method,path: calls.append(parse_qs(urlsplit(path).query)) or dict(projectCode='P',
            items=[] if 'primaryIdentifier=' in path else [row,row],nextCursor=None)
        fallback=ProjectTools(SimpleNamespace(reader=source),lambda:None,['object'],())
        fallback.query(dict(tool='graph',query='柜体',faultCode=''))
        self.assertEqual(2,len(calls));self.assertEqual(['柜体'],calls[1]['q']);self.assertEqual([],fallback.graphs)
        source._request=lambda *_:dict(projectCode='other',items=[row],nextCursor=None)
        with self.assertRaises(PreviewError):fallback.query(dict(tool='objects',query='=WEC+CN1',faultCode=''))
    def test_operation_receipt_replays_and_rejects_different_ack(self):
        run=str(uuid4());self.assertIsNone(load(self.library,run,'s'))
        retain(self.library,run,'s','base',dict(snapshot=board()))
        self.assertEqual('base',load(self.library,run,'s')['base_digest'])
        receipt=dict(state='applied_draft');self.assertEqual(receipt,acknowledge(self.library,run,'s',receipt))
        self.assertEqual(receipt,acknowledge(self.library,run,'s',receipt))
        with self.assertRaises(PreviewError):acknowledge(self.library,run,'s',dict(state='saved'))
    def test_empty_unsaved_canvas_runs_real_search_without_evidence_and_two_calls(self):
        runtime=AssistantRuntime(self.library,'source');self.addCleanup(runtime.close)
        runtime.store.publish('Demo-PDS',self.actor,dict(requestId=str(uuid4()),expectedRevision=0,policy={**DEFAULT,'enabled':True}),lambda:None)
        b=dict(protocol=PROTOCOL,mode='workbench',analysisSessionId=str(uuid4()),expectedAnalysisRevision=0,evidenceRefIds=[],
            requestId=str(uuid4()),question='查找同故障工单',snapshotJson=json.dumps(board()),taskId='analysis')
        calls=[]
        def source(data,*_):
            calls.append(data);common=dict(usage=dict(total_tokens=10),modelCalls=1,engineeringConfirmation=False)
            if data['workflow']['phase']=='plan':return dict(**common,plan=dict(intent='query',queries=[dict(tool='work_orders',query='',faultCode='13001')],actions=[]))
            return dict(**common,answer=answer())
        initial=runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),b,runtime.store.policy('Demo-PDS'),
            dict(serviceRevision='a'*64,accessRevision='g',taskId='analysis',settings=dict()),lambda _: ([],self.reader),lambda *_:None,source)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=runtime.store.public(runtime.store.run('Demo-PDS',self.actor,initial['runId']))
            if result['state'] not in ('reading','model','validating'):break
            time.sleep(.01)
        self.assertEqual('complete',result['state'],result);self.assertEqual(3,len(result['result']['task']['results']))
        self.assertEqual(2,len(calls));self.assertEqual([],calls[0]['evidence']);self.assertEqual(20,result['result']['usage']['total_tokens'])
        self.assertEqual(initial['runId'],runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),b,runtime.store.policy('Demo-PDS'),
            dict(serviceRevision='a'*64),None,None,None)['runId']);self.assertEqual(2,len(calls))

        from tests.test_assistant import Reader
        reader=Reader();reader.orders=self.orders;reader.reader=self.reader.reader
        fixed=[(dict(evidenceRefId=str(uuid4()),sourceKind='alarm',sourceRevision='a'*64),{'fixture':i}) for i in range(9)]
        second={**b,'requestId':str(uuid4()),'analysisSessionId':str(uuid4()),'evidenceRefIds':[r['evidenceRefId'] for r,_ in fixed]}
        started=runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),second,runtime.store.policy('Demo-PDS'),
            dict(serviceRevision='a'*64,accessRevision='g',taskId='analysis',settings={}),lambda _:(fixed,reader),lambda *_:None,source)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=runtime.store.public(runtime.store.run('Demo-PDS',self.actor,started['runId']))
            if result['state'] not in ('reading','model','validating'):break
            time.sleep(.01)
        self.assertEqual('complete',result['state'],result)
        task=result['result']['task']
        self.assertEqual(12,task['reads'])
        self.assertEqual(9,len(task['selectedReads']))
        self.assertTrue(all(item['state']=='complete' for item in task['selectedReads']))
        self.assertEqual([8,4],[len(data['evidence']) for data in calls[-2:]])
        self.assertTrue(any(row['refs']==['E9'] for row in result['result']['answer']['observations']))

    def test_explicitly_selected_cards_keep_their_reads_in_both_modes(self):
        from tests.test_assistant import Reader
        runtime=AssistantRuntime(self.library,'source');self.addCleanup(runtime.close)
        runtime.store.publish('Demo-PDS',self.actor,dict(requestId=str(uuid4()),expectedRevision=0,
            policy={**DEFAULT,'enabled':True}),lambda:None)
        reader=Reader();reader.orders=self.orders;reader.reader=self.reader.reader
        fixed=[(dict(evidenceRefId=str(uuid4()),sourceKind=kind,sourceRevision='a'*64),{'fixture':i})
               for i,kind in enumerate(('alarm','alarm','alarm','alarm','alarm','drawing'))]
        ids=[ref['evidenceRefId'] for ref,_ in fixed]
        for mode in ('workbench','cockpit_query'):
            with self.subTest(mode=mode):
                body=dict(protocol=PROTOCOL,mode=mode,analysisSessionId=str(uuid4()),expectedAnalysisRevision=2,
                    evidenceRefIds=ids,preferSelectedEvidence=True,requestId=str(uuid4()),
                    question='比较勾选的资料，并查找同码工单',snapshotJson=json.dumps(board()),taskId='query')
                calls=[]
                def source(data,*_):
                    calls.append(data)
                    common=dict(usage={},modelCalls=1,engineeringConfirmation=False)
                    if data['workflow']['phase']=='plan':
                        return dict(**common,plan=dict(intent='query',queries=[dict(tool='work_orders',query='',faultCode='13001')],actions=[]))
                    return dict(**common,answer=answer())
                start=runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),body,runtime.store.policy('Demo-PDS'),
                    dict(serviceRevision='a'*64,accessRevision='g',taskId='query',settings={}),lambda _:(fixed,reader),lambda *_:None,source)
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    run=runtime.store.public(runtime.store.run('Demo-PDS',self.actor,start['runId']))
                    if run['state'] not in ('reading','model','validating'):break
                    time.sleep(.01)
                self.assertEqual(ids,[row['evidenceRefId'] for row in run['sources'] if row['evidenceRefId']])
                task=run['result']['task']
                self.assertEqual(9,task['reads'])
                self.assertEqual(3,len(task['results']))
                self.assertEqual(ids,[row['evidenceRefId'] for row in task['selectedReads']])
                self.assertTrue(all(row['state']=='complete' and row['sourceKey'] for row in task['selectedReads']))
                self.assertTrue(task['selectedReads'][-1]['metadataOnly'])
                self.assertEqual(3,len(calls))
                self.assertEqual('query_only' if mode=='cockpit_query' else 'query',task['execution'])

    def test_every_selected_card_reports_why_it_was_or_was_not_read(self):
        kinds=['document','trend','photo','alarm','drawing']
        fixed=[(dict(evidenceRefId=str(uuid4()),sourceKind=kind,sourceRevision='a'*64),{})
               for kind in kinds]
        reader=SimpleNamespace(read=lambda *args:{})
        tools=ProjectTools(reader,lambda:None,['document','trend','alarm','drawing'],())
        def material(reader,kind,descriptor,private):
            if kind=='trend':
                raise PreviewError(409,'SOURCE_CHANGED')
            return dict(summary='Selected document metadata')
        with patch('apps.api.assistant_graph.material_summary',side_effect=material) as read:
            result=read_selected_evidence(tools,fixed)
        self.assertEqual(kinds,[row['kind'] for row in result])
        self.assertEqual(['complete','unavailable','policy_excluded','complete','complete'],
                         [row['state'] for row in result])
        self.assertEqual(['SOURCE_CHANGED','ASSISTANT_TOOL_NOT_ALLOWED'],
                         [row['reason'] for row in result if 'reason' in row])
        self.assertTrue(result[0]['metadataOnly'])
        self.assertEqual('E1',result[0]['sourceKey'])
        self.assertEqual(3,read.call_count)


    def test_edit_only_has_pending_receipt_message_without_false_evidence_gap(self):
        runtime=AssistantRuntime(self.library,'source');self.addCleanup(runtime.close)
        runtime.store.publish('Demo-PDS',self.actor,dict(requestId=str(uuid4()),expectedRevision=0,policy={**DEFAULT,'enabled':True}),lambda:None)
        for mode,intent in [('workbench','edit'),('cockpit_query','edit'),('workbench','query')]:
            b=dict(protocol=PROTOCOL,mode=mode,analysisSessionId=str(uuid4()),expectedAnalysisRevision=0,evidenceRefIds=[],
                requestId=str(uuid4()),question='新增笔记并分组' if intent=='edit' else '查询资料',snapshotJson=json.dumps(board()),taskId='analysis')
            calls=[]
            def source(data,*_):
                calls.append(data)
                self.assertEqual('plan',data['workflow']['phase'])
                self.assertEqual(['C'+str(i) for i in range(1,9)],json.loads(data['workflow']['context'])['newCardKeys'])
                return dict(usage={},modelCalls=1,engineeringConfirmation=False,
                    plan=dict(intent=intent,queries=[],actions=[action('add_note',text='待核验')] if intent=='edit' else []))
            initial=runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),b,runtime.store.policy('Demo-PDS'),
                dict(serviceRevision='a'*64,accessRevision='g',taskId='analysis',settings={}),lambda _:([],self.reader),lambda *_:None,source)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                result=runtime.store.public(runtime.store.run('Demo-PDS',self.actor,initial['runId']))
                if result['state'] not in ('reading','model','validating'):break
                time.sleep(.01)
            self.assertEqual('complete',result['state'],result);self.assertEqual(1,len(calls))
            reply=result['result']['answer']
            self.assertEqual(intent=='query',bool(reply['gaps']))
            if intent=='edit':
                self.assertIn('尚未执行' if mode=='workbench' else '驾驶舱未修改',reply['observations'][0]['text'])
