import copy
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from uuid import uuid4

from apps.api.assistant_store import AssistantStore, DEFAULT, digest, encoded
from apps.api.assistant_conversations import build_history
from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from tests.test_assistant import answer


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.library=ModelLibrary(Path(self.tmp.name)/'library','P',None)
        self.store=AssistantStore(self.library,'source');self.owner=str(uuid4());self.analysis=str(uuid4());self.ref=str(uuid4())

    def body(self,**changes):
        return dict(requestId=str(uuid4()),analysisSessionId=self.analysis,expectedAnalysisRevision=1,evidenceRefIds=[self.ref],
                    question='比较模拟资料',conversationId=None,expectedConversationVersion=0,parentRunId=None,**changes)

    def begin(self,body=None,owner=None,project='P'):
        return self.store.begin(project,owner or self.owner,body or self.body(),1,'s'*64)[0]

    def complete(self,row,sources=None):
        sources=sources or [dict(key='E1',kind='alarm',evidenceRefId=self.ref,sourceRevision='fixed',availability='available',summary='模拟',summaryHash=digest('模拟'))]
        self.store.update(row['id'],'complete',sources=sources,result=dict(answer=answer(),context={},partial=False))
        return self.store.run('P',self.owner,row['id'])

    def follow(self,row,**changes):
        body=self.body();body.update(conversationId=row['conversation_id'],expectedConversationVersion=row['turn_no'],parentRunId=row['id']);body.update(changes);return body

    def test_replay_persists_one_turn_and_refresh_keeps_exact_parent(self):
        body=self.body();first=self.complete(self.begin(body))
        self.assertFalse(self.store.begin('P',self.owner,body,1,'s'*64)[1])
        second=self.complete(self.begin(self.follow(first)))
        fresh=AssistantStore(self.library,'source');head,rows=fresh.conversation('P',self.owner,second['conversation_id'])
        self.assertEqual(2,head['version']);self.assertEqual([None,first['id']],[r['parent_run_id'] for r in rows])
        self.assertEqual(1,len(fresh.conversations('P',self.owner,self.analysis,1)))
        self.assertEqual(0,len(fresh.conversations('P',self.owner,self.analysis,2)))

    def test_owner_project_revision_stale_head_and_active_parent_are_refused(self):
        first=self.begin();body=self.follow(first)
        with self.assertRaises(PreviewError):self.begin(body)
        first=self.complete(first)
        for owner,project,change in ((str(uuid4()),'P',{}),(self.owner,'Q',{}),(self.owner,'P',{'expectedAnalysisRevision':2}),
            (self.owner,'P',{'parentRunId':str(uuid4())}),(self.owner,'P',{'expectedConversationVersion':0})):
            with self.subTest(change=change),self.assertRaises(PreviewError):self.begin({**body,**change},owner,project)
        second=self.complete(self.begin(body))
        with self.assertRaises(PreviewError) as conflict:self.begin({**body,'requestId':str(uuid4())})
        self.assertEqual('ASSISTANT_CONVERSATION_CHANGED',conflict.exception.code)
        head,rows=self.store.conversation('P',self.owner,second['conversation_id']);self.assertEqual(2,len(rows))

    def test_concurrent_followups_cannot_fork(self):
        first=self.complete(self.begin())
        def go(_):
            try:return self.begin(self.follow(first))['id']
            except PreviewError as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(go,range(2)))
        self.assertEqual(1,results.count('ASSISTANT_CONVERSATION_CHANGED'))
        head,rows=self.store.conversation('P',self.owner,first['conversation_id']);self.assertEqual(2,head['version'])

    def test_recent_pages_are_bounded_and_older_turns_still_addressable(self):
        current=self.complete(self.begin())
        for _ in range(6):current=self.complete(self.begin(self.follow(current)))
        _,last=self.store.conversation('P',self.owner,current['conversation_id']);self.assertEqual([4,5,6,7],[r['turn_no'] for r in last])
        _,earlier=self.store.conversation('P',self.owner,current['conversation_id'],4);self.assertEqual([1,2,3],[r['turn_no'] for r in earlier])

    def test_restart_marks_active_turn_interrupted_without_resending(self):
        first=self.begin();fresh=AssistantStore(self.library,'source');head,rows=fresh.conversation('P',self.owner,first['conversation_id'])
        self.assertEqual('interrupted',rows[0]['state']);second=self.begin(self.follow(rows[0]));self.assertEqual(2,second['turn_no'])

    def test_legacy_adoption_preserves_original_input_and_answer(self):
        first=self.complete(self.begin());before=(first['input_json'],first['result_json'])
        with self.library.connect() as db:
            db.execute('delete from assistant_conversation_turns');db.execute('delete from assistant_conversations')
        fresh=AssistantStore(self.library,'source');head,rows=fresh.conversation('P',self.owner,first['id'])
        self.assertEqual(before,(rows[0]['input_json'],rows[0]['result_json']));self.assertEqual(1,head['version'])

    def test_memory_remaps_reference_keys_by_stable_material_id(self):
        source=dict(key='E1',kind='object',evidenceRefId=self.ref,sourceRevision='r',summaryHash='hash',retrievalRevision='graph',availability='available')
        row=self.complete(self.begin(),[source]);changed={**source,'key':'E7'}
        context,skipped=build_history([row],[changed],'s'*64)
        self.assertFalse(skipped);self.assertEqual(['E7'],context[0]['refs']);self.assertNotIn('[E1]',context[0]['answer'])
        self.assertIn('待验证假设',context[0]['answer'])

    def test_memory_excludes_unselected_stale_or_unavailable_material_and_service(self):
        source=dict(key='E1',kind='object',evidenceRefId=self.ref,sourceRevision='r',summaryHash='hash',retrievalRevision='graph',availability='available')
        row=self.complete(self.begin(),[source])
        for current in ([],[{**source,'summaryHash':'changed'}],[{**source,'sourceRevision':'changed'}],
                        [{**source,'retrievalRevision':'new'}],[{**source,'availability':'unavailable'}]):
            history,skipped=build_history([row],current,'s'*64);self.assertFalse(history);self.assertEqual(1,len(skipped))
        self.assertFalse(build_history([row],[source],'changed')[0])

    def test_context_budget_is_four_turns_and_does_not_mutate_receipts(self):
        current=self.complete(self.begin());rows=[copy.deepcopy(current) for _ in range(8)];saved=copy.deepcopy(rows)
        history,_=build_history(rows,json.loads(current['sources_json']),'s'*64)
        self.assertEqual(4,len(history));self.assertLessEqual(sum(len(r['question'])+len(r['answer']) for r in history),6000)
        self.assertEqual(saved,rows)
