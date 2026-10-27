from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.api.analysis_queries import recommendations
from apps.api import simulated_faults as sim
from apps.api.authority import PreviewError


class MaterialRecommendationTests(TestCase):
    def reader(self, project='Demo-PDS'):
        return SimpleNamespace(reader=SimpleNamespace(project_code=project, _request=Mock(side_effect=AssertionError('Unexpected engineering read'))))

    def entry(self, code='13001', recurrence=False):
        dataset=sim.identity(code,recurrence=recurrence)
        return {key:dataset[key] for key in ('datasetId','datasetRevision')}

    def test_alarm_candidates_prioritize_current_fixed_event_and_keep_recurrence_separate(self):
        reader=self.reader();entry=self.entry(recurrence=True)
        value=recommendations(reader,{'entry':entry,'section':'alarms'})
        self.assertEqual(len(value['items']),5);self.assertEqual(value['items'][0]['selector']['datasetId'],entry['datasetId'])
        self.assertEqual(len({row['key'] for row in value['items']}),5)
        for row in value['items']:
            descriptor=row['selector'];self.assertEqual(descriptor['eventId'],descriptor['datasetId']+'-event-1')
            self.assertEqual(row['preview']['dataset'],sim.dataset(descriptor['datasetId'],descriptor['datasetRevision']))
        reader.reader._request.assert_not_called()

    def test_manual_analysis_can_choose_an_alarm_and_filter_without_loading_trends(self):
        with patch.object(sim,'trend',side_effect=AssertionError('No sample prefetch')):
            value=recommendations(self.reader(),{'entry':{'projectOnly':True},'section':'alarms','q':'13002'})
        self.assertEqual(len(value['items']),1);self.assertEqual(value['items'][0]['preview']['dataset']['faultCode'],'13002')
        other=recommendations(self.reader('OTHER'),{'entry':{'projectOnly':True},'section':'alarms'})
        self.assertEqual(other['items'],[]);self.assertIn('SIMULATION_PROJECT_REQUIRED',other['gaps'])

    def test_trends_offer_fixed_descriptors_only_and_preserve_current_event_window(self):
        for code,count in (('13001',5),('13004',3)):
            with patch.object(sim,'trend',side_effect=AssertionError('No sample prefetch')):
                value=recommendations(self.reader(),{'entry':self.entry(code),'section':'trends'})
            self.assertEqual(len(value['items']),count)
            for row in value['items']:
                self.assertEqual(row['selector']['timeFrom'],value['dataset']['timeFrom'])
                self.assertEqual(row['selector']['datasetRevision'],value['dataset']['datasetRevision'])
        value=recommendations(self.reader(),{'entry':self.entry(),'section':'trends','q':'reference_temperature'})
        self.assertEqual([row['selector']['metricId'] for row in value['items']],['reference_temperature'])
        manual=recommendations(self.reader(),{'entry':{'projectOnly':True},'section':'trends'})
        self.assertEqual(manual['items'],[]);self.assertTrue(manual['gaps'])

    def test_versions_and_query_shape_cannot_bypass_source_checks(self):
        for body in ({'entry':{**self.entry(),'datasetRevision':'changed'},'section':'alarms'},
            {'entry':self.entry(),'section':'trends','q':['bad']},
            {'entry':self.entry(),'section':'alarms','url':'https://outside.invalid'}):
            with self.assertRaises(PreviewError):recommendations(self.reader(),body)

    def test_drawing_and_photo_categories_only_resolve_the_selected_material_type(self):
        reader=self.reader();reader._rds=Mock(return_value={'item':{'entityUid':'object','entityRevision':'r1'},'context':None})
        reader.photos=SimpleNamespace(resolve=Mock(return_value={'items':[{'title':'Photo','evidenceRef':'photo','selector':{'bbox':{} }}]}))
        with patch('apps.api.scene_evidence.SceneEvidenceReader') as drawing:
            drawing.return_value.resolve.return_value={'items':[{'title':'Drawing','evidenceRef':'drawing','availability':'available'}]}
            rows=recommendations(reader,{'entry':self.entry(),'section':'drawings'})['items']
            self.assertEqual([row['kind'] for row in rows],['drawing']);reader.photos.resolve.assert_not_called()
            drawing.return_value.resolve.reset_mock()
            rows=recommendations(reader,{'entry':self.entry(),'section':'photos'})['items']
            self.assertEqual([row['kind'] for row in rows],['photo']);drawing.return_value.resolve.assert_not_called()
