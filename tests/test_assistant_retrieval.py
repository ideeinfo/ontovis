import copy,json,unittest
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
from apps.api.assistant_retrieval import plan,retrieve
from apps.api.authority import PreviewError
from tests.test_assistant_knowledge import response,DESCRIPTOR

class Reader:
 def __init__(self):
  self.calls=[];self.graph={'document_id':'document','content_version_id':'version','available_for_analysis':True,'state':'published',
   'nodes':[{'local_id':'root','kind':'FaultDefinition','payload':{'properties':{'urn:ontobase:document-knowledge:1:fault_code':[{'value':'13002'}]}}}], 'next_cursor':None}
  self.reader=SimpleNamespace(prefix='/projects/P',project_code='P',_request=self.request)
 def request(self,method,path):
  self.calls.append((method,path));self.last=path
  if urlsplit(path).path.endswith('/graph'):return copy.deepcopy(self.graph)
  return response()
 def read(self,*args):raise AssertionError('No binary or unselected source read')

class RetrievalTests(unittest.TestCase):
 def setUp(self):self.reader=Reader();self.fixed=[({'sourceKind':'document'},DESCRIPTOR)]
 def test_question_directs_one_exact_fault_lookup_in_the_fixed_release(self):
  selected=plan(self.fixed,'请核对13002的触发条件',8)[0]
  self.assertEqual(selected,{'tool':'selected_manual','faultCode':'13002','operations':2})
  value=retrieve(self.reader,'document',DESCRIPTOR,selected)
  self.assertEqual(value['retrieval']['anchor'],{'nodeId':'root','pageNumber':49})
  self.assertEqual(len(self.reader.calls),2)
  query=parse_qs(urlsplit(self.reader.calls[0][1]).query)
  self.assertEqual(query['q'],['13002']);self.assertEqual(query['limit'],['12'])
  self.assertIn('/knowledge-releases/release/',self.reader.calls[0][1])
  self.assertEqual(json.loads(value['summary'])['selectedNode']['faultCode'],'13002')
 def test_tool_budget_reserves_one_read_for_every_selected_material(self):
  self.assertEqual(sum(p['operations'] for p in plan(self.fixed*7,'13002',8)),8)
  self.assertTrue(all(p['faultCode'] is None for p in plan(self.fixed*8,'13002',8)))
  with self.assertRaises(PreviewError):plan(self.fixed*9,'13002',8)
 def test_query_text_never_becomes_a_url_or_unbounded_search(self):
  value=plan(self.fixed,'13002; DELETE / https://attacker.invalid/?secret=private',8)[0]
  retrieve(self.reader,'document',DESCRIPTOR,value)
  self.assertTrue(all('attacker' not in path and 'DELETE' not in path for _,path in self.reader.calls))
  self.assertIsNone(plan(self.fixed,'1130029 arbitrary SQL',8)[0]['faultCode'])
 def test_foreign_or_withdrawn_release_stops_before_using_knowledge(self):
  for changes in ({'content_version_id':'other'},{'document_id':'other'},{'available_for_analysis':False}):
   self.reader.graph.update(changes)
   with self.assertRaises(PreviewError):retrieve(self.reader,'document',DESCRIPTOR,plan(self.fixed,'13002',8)[0])
 def test_no_match_or_ambiguous_match_is_a_gap_not_a_demo_fallback(self):
  for nodes in ([],self.reader.graph['nodes']*2):
   self.reader.graph['nodes']=nodes;self.reader.calls=[]
   value=retrieve(self.reader,'document',DESCRIPTOR,plan(self.fixed,'13002',8)[0])
   self.assertIn('gaps',json.loads(value['summary']));self.assertEqual(len(self.reader.calls),1)
   self.assertIsNone(value['retrieval']['anchor'])
 def test_incomplete_search_results_are_not_treated_as_unique(self):
  self.reader.graph['next_cursor']=12
  value=retrieve(self.reader,'document',DESCRIPTOR,plan(self.fixed,'13002',8)[0])
  self.assertTrue(value['retrieval']['tools'][0]['truncated']);self.assertIsNone(value['retrieval']['anchor'])
 def test_fixed_material_question_free_mode_preserves_legacy_summary_hash(self):
  from apps.api.assistant_graph import material_summary
  value=retrieve(self.reader,'document',DESCRIPTOR,plan(self.fixed,'',8)[0])
  self.assertEqual(value['summaryHash'],material_summary(self.reader,'document',DESCRIPTOR)['summaryHash'])
 def test_a_question_cannot_select_another_tool(self):
  with self.assertRaises(PreviewError):retrieve(self.reader,'document',DESCRIPTOR,{'tool':'arbitrary_url','faultCode':None,'operations':1})
