import copy
import json
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit
from apps.api.authority import PreviewError
from apps.api.assistant_knowledge import read_neighborhood
from apps.api.assistant_summaries import summarize

DESCRIPTOR=dict(documentId='document', contentVersionId='version', knowledgeReleaseId='release', knowledgeNodeId='root', pageNumber=49)

def response():
    def node(local,kind,text):return dict(id=local,kind=kind,title=text,statement=text,faultCode='13002' if local=='root' else '',evidenceIds=['proof'],evidenceComplete=True)
    def edge(local,source,target,predicate):return dict(id=local,source=source,target=target,predicate=predicate,evidenceIds=['proof'],evidenceComplete=True)
    return dict(format='ontobase-document-neighborhood-v1',scope='published_document_knowledge',projectCode='P',releaseId='release',
        documentId='document',contentVersionId='version',root='root',depth=2,engineeringConfirmation=False,availableForAnalysis=True,state='published',
        nodes=[node('root','FaultDefinition','机舱柜温度低'),node('cause','PossibleCause','温度测量链偏差待检查'),node('step','CheckStep','比较独立参照温度')],
        relations=[edge('a','root','cause','hasPossibleCause'),edge('b','root','step','hasCheckStep')],
        evidence=[dict(id='proof',page=49,bbox=None,text='原手册检查依据')],truncated=False,missingEvidenceCount=0)

class Reader:
    def __init__(self,value):self.value=value;self.calls=[];self.reader=SimpleNamespace(project_code='P',prefix='/api/v1/projects/P',_request=self.request)
    def request(self,method,path):self.calls.append((method,path));return copy.deepcopy(self.value)
    def read(self,*_):raise AssertionError('unbounded document read')
    def content(self,*_):raise AssertionError('binary read')

class AssistantKnowledgeTests(unittest.TestCase):
    def test_exact_fixed_scope_is_sent_once_without_mapping_or_image_requests(self):
        reader=Reader(response());result=read_neighborhood(reader,DESCRIPTOR)
        self.assertEqual('root',result['root']);self.assertEqual(1,len(reader.calls));method,path=reader.calls[0]
        self.assertEqual('GET',method);self.assertEqual('/api/v1/projects/P/knowledge-releases/release/neighborhood',urlsplit(path).path)
        self.assertEqual({'root':['root'],'version_id':['version'],'depth':['2'],'node_limit':['12'],'edge_limit':['18']},parse_qs(urlsplit(path).query))

    def test_cross_scope_withdrawn_wrong_version_or_root_are_rejected(self):
        for change in [dict(projectCode='other'),dict(releaseId='other'),dict(documentId='other'),dict(contentVersionId='other'),
            dict(root='other'),dict(depth=3),dict(scope='engineering'),dict(engineeringConfirmation=True),dict(state='withdrawn'),dict(availableForAnalysis=False)]:
            with self.subTest(change=change),self.assertRaises(PreviewError):read_neighborhood(Reader(response()|change),DESCRIPTOR)

    def test_missing_endpoints_evidence_and_disconnected_nodes_are_rejected(self):
        for change in ('endpoint','predicate','evidence','duplicate','disconnected','unhashable','empty-complete'):
            data=response()
            if change=='endpoint':data['relations'][0]['target']='missing'
            if change=='predicate':data['relations'][0]['predicate']='cypher'
            if change=='evidence':data['nodes'][1]['evidenceIds']=['foreign']
            if change=='duplicate':data['nodes'].append(data['nodes'][0])
            if change=='disconnected':data['relations']=[]
            if change=='unhashable':data['nodes'][0]['evidenceIds']=[{}]
            if change=='empty-complete':data['nodes'][0]['evidenceIds']=[]
            with self.subTest(change=change),self.assertRaises(PreviewError):read_neighborhood(Reader(data),DESCRIPTOR)

    def test_related_causes_and_steps_keep_path_direction_and_page(self):
        data=json.loads(summarize(Reader(response()),'document',DESCRIPTOR))
        self.assertEqual(['PossibleCause','CheckStep'],[row['kind'] for row in data['relatedKnowledge']])
        self.assertEqual(['out:hasPossibleCause'],data['relatedKnowledge'][0]['path']);self.assertEqual([49],data['relatedKnowledge'][0]['pages'])
        self.assertEqual('原手册检查依据',data['relatedKnowledge'][1]['quote']);self.assertEqual([],data['gaps'])
        source=response();source['relations'][0]['source']='cause';source['relations'][0]['target']='root'
        reversed_value=json.loads(summarize(Reader(source),'document',DESCRIPTOR))
        self.assertEqual(['in:hasPossibleCause'],reversed_value['relatedKnowledge'][0]['path'])

    def test_missing_proofs_and_count_limits_remain_visible(self):
        source=response();source['nodes'][1].update(evidenceIds=[],evidenceComplete=False);source['missingEvidenceCount']=1;source['truncated']=True
        result=json.loads(summarize(Reader(source),'document',DESCRIPTOR))
        self.assertEqual(['CheckStep'],[r['kind'] for r in result['relatedKnowledge']]);self.assertEqual(2,len(result['gaps']))

    def test_summary_budget_is_valid_json_and_private_identity_is_redacted(self):
        source=response();source['nodes'][0]['statement']='P /Users/person/private password=hidden '+'温度定义'*80
        for n in range(6):
            source['nodes'].append(dict(id=f'c{n}',kind='PossibleCause',title='原因'*50,statement='原因'*200,faultCode='',evidenceIds=['proof'],evidenceComplete=True))
            source['relations'].append(dict(id=f'r{n}',source='root',target=f'c{n}',predicate='hasPossibleCause',evidenceIds=['proof'],evidenceComplete=True))
        result=summarize(Reader(source),'document',DESCRIPTOR,('P',))
        self.assertLessEqual(len(result),1000);parsed=json.loads(result);self.assertLessEqual(len(parsed['relatedKnowledge']),4)
        self.assertNotIn('hidden',result);self.assertNotIn('/Users/',result);self.assertTrue(parsed['gaps'])
        self.assertIn('CheckStep',[row['kind'] for row in parsed['relatedKnowledge']])

    def test_non_object_response_has_a_stable_source_error(self):
        with self.assertRaises(PreviewError):read_neighborhood(Reader([]),DESCRIPTOR)

    def test_fault_with_only_a_trigger_does_not_invent_causes_or_checks(self):
        source=response();source['nodes']=source['nodes'][:2];source['nodes'][1]['kind']='TriggerCondition'
        source['relations']=source['relations'][:1];source['relations'][0]['predicate']='hasTrigger'
        result=json.loads(summarize(Reader(source),'document',DESCRIPTOR))
        self.assertEqual(['TriggerCondition'],[row['kind'] for row in result['relatedKnowledge']])
        self.assertEqual(['所读知识中没有故障原因条目。','所读知识中没有检查步骤条目。'],result['gaps'])

    def test_too_many_nodes_or_invalid_source_pages_fail_before_summary(self):
        for field in ('nodes','page'):
            source=response()
            if field=='nodes':source['nodes']*=5
            else:source['evidence'][0]['page']=0
            with self.subTest(field=field),self.assertRaises(PreviewError):summarize(Reader(source),'document',DESCRIPTOR)
