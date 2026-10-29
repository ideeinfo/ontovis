import copy
import json
from types import SimpleNamespace
import unittest
from apps.api import assistant_graph as api
from apps.api.authority import PreviewError


def graph():
    return dict(format='ontobase-engineering-neighborhood-v1',projectCode='P',root='object:root',depth=2,
        relationTypes=list(api.TYPES),engineeringConfirmation=False,revision='a'*64,truncated=False,gaps=['接线待复核。'],
        nodes=[dict(id='object:root',kind='object',title='传感器',entityUid='root',entityRevision='i:1',installationContextId=None),
               dict(id='object:other',kind='object',title='端子排')],
        relations=[dict(id='connection',source='object:root',target='object:other',type='CANDIDATE_CONNECTION',status='needs_review',
            provenance=dict(recordId='source',recordRevision='b'*64))])


class GraphSummaryTests(unittest.TestCase):
    def read(self,value):
        seen=[]
        reader=SimpleNamespace(reader=SimpleNamespace(project_code='P',prefix='/api/v1/projects/P',_request=lambda *args:seen.append(args) or value))
        result=api.read_graph(reader,dict(entityUid='root',expectedEntityRevision='i:1',installationContextId=None,expectedHierarchyRevision=None))
        self.assertEqual('POST',seen[0][0]);self.assertEqual(24,seen[0][2]['nodeLimit']);return result

    def test_exact_root_identity_scope_candidate_status_and_provenance_are_required(self):
        self.read(graph())
        for change in (dict(projectCode='Q'),dict(root='object:other'),dict(revision='bad'),dict(engineeringConfirmation=True)):
            with self.subTest(change=change),self.assertRaises(PreviewError):self.read({**graph(),**change})
        for where,key,value in (('nodes','entityUid','same label different uid'),('relations','status','confirmed')):
            data=graph();data[where][0][key]=value
            with self.assertRaises(PreviewError):self.read(data)

    def test_dangling_detached_and_oversize_graphs_are_rejected(self):
        data=graph();data['relations'][0]['target']='missing'
        with self.assertRaises(PreviewError):self.read(data)
        data=graph();data['nodes'].append(dict(id='detached',kind='drawing',title='unrelated'))
        with self.assertRaises(PreviewError):self.read(data)
        data=graph();data['nodes']*=13
        with self.assertRaises(PreviewError):self.read(data)

    def test_text_summary_keeps_candidate_status_and_omits_internal_ids(self):
        data=graph();saved=copy.deepcopy(data);text=api.graph_summary(data,lambda s:s)
        result=json.loads(text);self.assertIn('待复核',text);self.assertEqual('needs_review',result['associations'][0]['status'])
        self.assertNotIn('object:root',text);self.assertNotIn('recordId',text);self.assertLessEqual(len(text),1000);self.assertEqual(saved,data)

    def test_selected_root_precedes_second_hop_and_parallel_wires_are_not_repeated_in_summary(self):
        data=graph();data['nodes'].append(dict(id='remote',kind='object',title='跨柜端子'))
        direct=data['relations'][0];data['relations']=[{**direct,'id':'a-remote','source':'object:other','target':'remote'},
            {**direct,'id':'b-root'},{**direct,'id':'c-parallel'}]
        value=json.loads(api.graph_summary(data,lambda s:s))
        self.assertEqual('端子排',value['associations'][0]['target']);self.assertIn('传感器',value['associations'][0]['source'])
        self.assertEqual(2,len(value['associations']))
