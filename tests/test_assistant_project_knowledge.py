import copy
import json
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

from apps.api.assistant_tasks import ProjectTools
from apps.api.authority import PreviewError
from apps.api.analysis_preview import OB
from tests.test_assistant_knowledge import response


def root(release):
    return dict(kind='FaultDefinition',payload=dict(properties={OB+'fault_code':[dict(value='13002')],OB+'title':[dict(value='柜温低')]}),
        source=dict(document=dict(id='doc-'+release,name=release),version=dict(id='v-'+release),release_id=release,local_id='root'))


class KnowledgeTests(unittest.TestCase):
    def setup_tools(self,pages,limit=8):
        calls=[]
        def request(_method,path):
            params=parse_qs(urlsplit(path).query);calls.append(params)
            return copy.deepcopy(pages[int(params.get('cursor',['0'])[0])])
        reader=SimpleNamespace(reader=SimpleNamespace(prefix='/api/v1/projects/P',project_code='P',_request=request))
        return ProjectTools(reader,lambda:None,limit,['document'],()),calls
    def page(self,nodes,cursor=None,token='a'*64):
        return dict(project_code='P',nodes=nodes,relations=[],next_cursor=cursor,scope_token=token)
    def run_query(self,tools,neighborhood=None):
        with patch('apps.api.fixed_documents.FixedDocuments.metadata',return_value=dict(sourceSha256='a'*64,title='手册')),\
             patch('apps.api.analysis_preview.node_evidence',return_value=dict(items=[dict(selector=dict(page=49))])),\
             patch('apps.api.assistant_knowledge.read_neighborhood',side_effect=neighborhood or (lambda *_:response())):
            tools.query(dict(tool='knowledge',query='',faultCode='13002'))
    def test_two_publications_preserve_pages_and_scoped_cursor(self):
        tools,calls=self.setup_tools([self.page([root('A')],1),self.page([root('B')])])
        self.run_query(tools)
        self.assertEqual(8,tools.reads);self.assertEqual(['a'*64],calls[1]['scope_token'])
        fixed=[s for s in tools.sources if s.get('descriptor')]
        self.assertEqual(['A','B'],[s['descriptor']['knowledgeReleaseId'] for s in fixed])
        self.assertTrue(all(json.loads(s['summary']) and len(s['summary'])<=1000 for s in tools.sources))
        self.assertTrue(all(49 in s['pageNumbers'] for s in fixed))
        graphs=[g for g in tools.graphs if g.get('sourceKey')]
        self.assertEqual(['E2','E3'],[g['sourceKey'] for g in graphs])
        self.assertEqual([49],graphs[0]['graph']['relations'][0]['provenance']['pageNumbers'])
    def test_failure_of_one_publication_does_not_erase_other_evidence(self):
        tools,_=self.setup_tools([self.page([root('A'),root('B')])])
        self.run_query(tools,neighborhood=[PreviewError(409,'KNOWLEDGE_RELEASE_UNAVAILABLE'),response()])
        self.assertEqual('B',tools.sources[-1]['descriptor']['knowledgeReleaseId'])
        self.assertTrue(any(t['state']=='unavailable' and t['releaseId']=='A' for t in tools.trace))
    def test_budget_and_multiple_matches_are_explicit(self):
        tools,_=self.setup_tools([self.page([root('A'),root('A'),root('B'),root('C')],1)],limit=4)
        self.run_query(tools)
        self.assertEqual(4,tools.reads)
        limited=[t for t in tools.trace if t['state']=='budget_limited']
        self.assertEqual(2,limited[0]['count'])
        self.assertEqual(1,tools.trace[0]['nextCursor'])
    def test_changed_page_scope_stops_before_fixed_read(self):
        tools,_=self.setup_tools([self.page([root('A')],1),self.page([root('B')],token='b'*64)])
        with self.assertRaises(PreviewError) as error:self.run_query(tools)
        self.assertEqual('SOURCE_CHANGED',error.exception.code)
