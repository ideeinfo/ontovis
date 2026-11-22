from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from tools.check_workbench_release import RECEIPT, build_identity, candidate, load_evidence_case, promote, record


class WorkbenchBrowserReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root/'dist'
        (self.dist/'assets').mkdir(parents=True)
        (self.dist/'index.html').write_text('<script src="/assets/index.js"></script>')
        (self.dist/'assets/index.js').write_text('console.info("synthetic workbench")')
        self.output = self.root/'checks'
        self.release = 'a'*40
        self.marker = self.root/'activation-ran'
        self.command = [sys.executable,'-c','import sys; from pathlib import Path; Path(sys.argv[1]).touch()',str(self.marker)]

    def receipt(self, **overrides):
        value = dict(mode='candidate',release=self.release,passed=True,**build_identity(self.dist),
                     results={'13002':{'tested':True},'assistantModelUsage':{'tested':True},
                              'analysisSaveRecovery':{'tested':True}})
        record(self.output/'candidate',{**value,**overrides})

    def test_failed_or_unrelated_receipts_never_run_activation(self):
        for bad in ({'passed':False},{'release':'b'*40},
                    {'results':{'13002':{'tested':True},'assistantModelUsage':{'tested':True}}}):
            self.receipt(**bad)
            with self.assertRaises(RuntimeError):
                promote(self.dist,self.release,self.output,self.command)
            self.assertFalse(self.marker.exists())

    def test_asset_change_blocks_activation_even_when_index_matches(self):
        self.receipt()
        (self.dist/'assets/index.js').write_text('console.info("other build")')
        with self.assertRaisesRegex(RuntimeError,'differs'):
            promote(self.dist,self.release,self.output,self.command)
        self.assertFalse(self.marker.exists())

    def test_matching_build_can_run_activation(self):
        self.receipt()
        value = promote(self.dist,self.release,self.output,self.command)
        self.assertEqual(build_identity(self.dist)['distSha256'],value['distSha256'])
        self.assertTrue(self.marker.exists())

    def test_failed_browser_run_replaces_a_previous_pass(self):
        self.receipt()
        browser = Mock()
        with patch('tools.check_workbench_release.assistant_model_usage',side_effect=RuntimeError('simulated failure')):
            with self.assertRaisesRegex(RuntimeError,'simulated failure'):
                candidate(browser,self.release,self.dist,self.output/'candidate')
        browser.close.assert_called_once_with()
        receipt = json.loads((self.output/'candidate'/RECEIPT).read_text())
        self.assertFalse(receipt['passed'])
        with self.assertRaises(RuntimeError):
            promote(self.dist,self.release,self.output,self.command)
        self.assertFalse(self.marker.exists())

    def evidence_case(self):
        uid = lambda index: str(UUID(int=index))
        cards = [dict(kind='document',pageNumber=page,documentId=uid(index),contentVersionId=uid(index+10),
                      knowledgeReleaseId=uid(index+20),sourceSha256='b'*64)
                 for index,page in enumerate((53,9),1)]
        cards.extend(dict(kind='drawing',pageNumber=page,drawingUid=f'Demo-PDS:drawing:{page}',contentSha256='c'*64)
                     for page in (89,189,228))
        cards.append(dict(kind='work_order',orderId='DEMO-SYNTHETIC-008',orderRevision=6))
        for index,card in enumerate(cards,40):
            card.update(cardId=f'card-{index}',evidenceRefId=uid(index),sourceRevision='d'*64)
        return dict(analysisSessionId=uid(10),analysisRevision=3,contentSha256='e'*64,datasetRevision='f'*64,cards=cards)

    def test_13001_manifest_preserves_source_pins(self):
        case = self.evidence_case()
        path = self.root/'13001.json'
        path.write_text(json.dumps(case))
        self.assertEqual(load_evidence_case(path),case)

    def test_13001_manifest_rejects_different_pages_and_duplicate_references(self):
        path = self.root/'13001.json'
        case = self.evidence_case()
        case['cards'][0]['pageNumber'] = 54
        path.write_text(json.dumps(case))
        with self.assertRaisesRegex(RuntimeError,'both manual pages'):
            load_evidence_case(path)
        case['cards'][0]['pageNumber'] = 53
        case['cards'][0]['evidenceRefId'] = case['cards'][1]['evidenceRefId']
        path.write_text(json.dumps(case))
        with self.assertRaisesRegex(RuntimeError,'13001'):
            load_evidence_case(path)
