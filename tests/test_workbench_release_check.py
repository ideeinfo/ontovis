from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tools.check_workbench_release import RECEIPT, build_identity, candidate, promote, record


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
                     results={'13002':{'tested':True},'assistantModelUsage':{'tested':True}})
        record(self.output/'candidate',{**value,**overrides})

    def test_failed_or_unrelated_receipts_never_run_activation(self):
        for bad in ({'passed':False},{'release':'b'*40},{'results':{'13002':{'tested':True}}}):
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
