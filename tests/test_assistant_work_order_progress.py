"""Selected fixed work-order progress is bounded, redacted and never a field conclusion."""
from copy import deepcopy
import json
import unittest
from apps.api.assistant_summaries import summarize

class Reader:
    def __init__(self, value): self.value, self.reads = value, []
    def read(self, kind, descriptor):
        self.reads.append((kind, descriptor))
        return self.value

class WorkOrderProgressSummaryTests(unittest.TestCase):
    def value(self):
        return {'faultCode':'13002','state':'diagnosing','orderRevision':4,'note':'do-not-send-note',
                'assistantTransfers':[{'originalText':'do-not-send-private-conversation'}],
                'investigation':{'hypotheses':[{'id':'h1','description':'温度链待核','status':'candidate','basis':''}],
                                 'steps':[{'id':'s1','title':'核对温度','outcome':'observed','result':'软件演练窗口已核对，未作现场测量'}],
                                 'conclusion':'do-not-send-conclusion','reviewBasis':'do-not-send-review'}}

    def test_fixed_revision_and_human_result_are_preserved_without_verified_conclusion(self):
        value=self.value();before=deepcopy(value);reader=Reader(value);descriptor={'orderRevision':4}
        result=json.loads(summarize(reader,'work_order',descriptor))
        self.assertEqual(reader.reads,[('work_order',descriptor)])
        self.assertEqual((result['revision'],result['state']),(4,'diagnosing'))
        self.assertFalse(result['engineeringConfirmation'])
        self.assertEqual(result['steps'][0]['state'],'observed');self.assertIn('未作现场测量',result['steps'][0]['record'])
        self.assertEqual(value,before)
        self.assertNotIn('do-not-send',json.dumps(result));self.assertIn('不是现场事实',result['meaning'])
        self.assertIn('不能据此断言现场未执行',result['meaning'])

    def test_redaction_precedes_excerpt_and_does_not_break_json(self):
        value=self.value();value['investigation']['steps'][0]['result']='password=fixture-secret https://private.invalid x@private.test /Users/example/doc 13812345678 '+'长'*2000
        raw=summarize(Reader(value),'work_order',{});result=json.loads(raw)
        self.assertLessEqual(len(raw),1000)
        for secret in ['fixture-secret','private.invalid','private.test','/Users','13812345678']:self.assertNotIn(secret,raw)
        self.assertIn('隐去',result['steps'][0]['record'])

    def test_long_records_are_omitted_explicitly_as_complete_json(self):
        value=self.value();plan=value['investigation'];template=plan['steps'][0]
        plan['steps']=[dict(template,id=str(i),title='题'*500,result='录'*2000) for i in range(12)]
        plan['hypotheses']=[{'id':str(i),'description':'因'*500,'status':'supported','basis':'据'*2000} for i in range(6)]
        raw=summarize(Reader(value),'work_order',{});result=json.loads(raw)
        self.assertLessEqual(len(raw),1000)
        self.assertEqual(len(result['steps'])+result['omittedSteps'],12)
        self.assertEqual(len(result['hypotheses'])+result['omittedHypotheses'],6)
        self.assertIn('不是现场事实',result['meaning'])

    def test_recorded_items_take_priority_and_retain_original_step_numbers(self):
        value=self.value();recorded=value['investigation']['steps'][0]
        value['investigation']['steps']=[{'title':'待排查','outcome':'pending','result':''} for _ in range(5)]+[recorded]
        result=json.loads(summarize(Reader(value),'work_order',{}))
        self.assertEqual(result['steps'][0]['number'],6)
        self.assertIn('未作现场测量',result['steps'][0]['record'])
        self.assertEqual(result['pendingStepNumbers'],[1,2,3,4,5])

    def test_legacy_order_without_structured_plan_is_not_given_fabricated_results(self):
        result=json.loads(summarize(Reader({'faultCode':'13002','orderRevision':1,'state':'closed'}),'work_order',{}))
        self.assertEqual(result['steps'],[]);self.assertEqual(result['hypotheses'],[])
        self.assertFalse(result['engineeringConfirmation']);self.assertEqual(result['omittedSteps'],0)
