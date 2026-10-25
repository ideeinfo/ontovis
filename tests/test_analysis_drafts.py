"""Manual draft contract tests; these do not claim source or HTTP authorization."""
import copy
import json
import unittest
from uuid import uuid4

from apps.api.analysis_drafts import canonical, digest, identifier, validate_snapshot
from apps.api.authority import PreviewError

CONNECTION = 'synthetic-source'
PROJECT = 'SYNTHETIC-PROJECT'
OWNER = '4fa35241-f40b-4e49-8615-52d4c9a549c5'
OTHER = '1eed7829-4053-4095-8a87-b02b22727b79'


def snapshot():
    return {'schemaVersion': 1, 'ontobaseConnectionId': CONNECTION, 'projectCode': PROJECT,
            'title': '合成分析草稿', 'status': 'analyzing',
            'context': {'objectIds': [], 'timeFrom': '2026-10-26T00:00:00Z',
                        'timeTo': '2026-10-26T02:00:00Z', 'timezone': 'Asia/Shanghai'},
            'cards': [{'id': 'note-1', 'kind': 'analysis', 'title': '原因假设', 'x': 32, 'y': 40,
                       'width': 300, 'height': 210, 'pinned': False, 'note': '人工草稿，待核查。'}],
            'relations': [], 'viewport': {'x': 24, 'y': 24, 'zoom': 1}}


def create_body(value=None):
    return {'requestId': str(uuid4()), 'snapshot': value or snapshot()}


class AnalysisDraftContractTests(unittest.TestCase):
    def validate(self, value):
        return validate_snapshot(value, CONNECTION, PROJECT)

    def rejected(self, value, code=None):
        with self.assertRaises(PreviewError) as error:
            self.validate(value)
        if code:
            self.assertEqual(error.exception.code, code)

    def test_canonical_snapshot_preserves_chinese_and_note_whitespace(self):
        value = snapshot(); value['cards'][0]['note'] = '  先观察\n再核查。  '
        raw = self.validate(value)
        self.assertEqual(json.loads(raw), value)
        self.assertIn('先观察', raw)
        self.assertEqual(digest(value), digest(dict(reversed(list(value.items())))))

    def test_cross_connection_and_project_rejected(self):
        for field in ('projectCode', 'ontobaseConnectionId'):
            value = snapshot(); value[field] = 'another'
            self.rejected(value, 'ANALYSIS_SCOPE_MISMATCH')

    def test_client_cannot_supply_ownership_authority_or_revision(self):
        for field in ('ownerId', 'actorId', 'permissions', 'analysisRevision'):
            value = snapshot(); value[field] = OWNER
            self.rejected(value)

    def test_source_cards_and_source_context_are_not_connected(self):
        value = snapshot(); value['cards'][0]['source'] = {'id': 'claimed-evidence'}
        self.rejected(value, 'ANALYSIS_SOURCE_NOT_CONNECTED')
        value = snapshot(); value['cards'][0]['kind'] = 'photo'
        self.rejected(value, 'ANALYSIS_SOURCE_NOT_CONNECTED')
        value = snapshot(); value['context']['objectIds'] = ['claimed-engineering-object']
        self.rejected(value, 'ANALYSIS_SOURCE_NOT_CONNECTED')

    def test_technical_admin_cannot_encode_expert_conclusion_in_state(self):
        for state in ('concluded', 'archived', 'closed', None, []):
            value = snapshot(); value['status'] = state
            self.rejected(value, 'ANALYSIS_REVIEW_NOT_CONFIGURED')

    def test_nonfinite_boolean_and_out_of_bounds_layout_rejected(self):
        for field, bad in [('x', float('nan')), ('y', float('inf')), ('x', True), ('width', 239),
                           ('height', 961), ('x', 20001), ('pinned', 1)]:
            value = snapshot(); value['cards'][0][field] = bad; self.rejected(value)
        for bad in (.1, 2, True):
            value = snapshot(); value['viewport']['zoom'] = bad; self.rejected(value)

    def test_real_utc_dates_and_increasing_time_window_required(self):
        for bad in ('2026-02-31T00:00:00Z', '2026-10-26', '2026-10-26T00:00:00+08:00',
                    '2026-10-26T03:00:00Z', None, 0):
            value = snapshot(); value['context']['timeFrom'] = bad; self.rejected(value)
        value = snapshot(); value['context']['timeFrom'] = '2026-10-26T00:00:00.123Z'
        self.validate(value)

    def test_text_budget_counts_encoded_bytes(self):
        value = snapshot()
        value['cards'] = [{**value['cards'][0], 'id': f'note-{i}', 'note': '字'*4000} for i in range(50)]
        self.rejected(value, 'ANALYSIS_SIZE_LIMIT')

    def test_arbitrary_content_fields_not_persisted(self):
        for field in ('html', 'url', 'body', 'token'):
            value = snapshot(); value['cards'][0][field] = 'unexpected'
            self.rejected(value)

    def test_unencodable_or_null_text_is_rejected_before_database_write(self):
        for bad in ('bad\ud800', 'bad\x00'):
            value = snapshot(); value['cards'][0]['note'] = bad
            self.rejected(value)
        value = snapshot(); value['cards'][0]['note'] = r'literal \u0000'
        self.assertEqual(json.loads(self.validate(value)), value)

    def test_manual_links_need_distinct_valid_endpoints_and_reason(self):
        value = snapshot(); value['cards'].append({**value['cards'][0], 'id': 'note-2'})
        link = {'id': 'r1', 'from': 'note-1', 'to': 'note-2', 'kind': 'hypothesis',
                'origin': 'manual', 'reason': '仅为人工推断，待核查'}
        value['relations'] = [link]; self.validate(value)
        for change in ({'to': 'missing'}, {'to': 'note-1'}, {'reason': ''}, {'origin': 'source'}, {'kind': 'engineering'}):
            altered = copy.deepcopy(value); altered['relations'][0].update(change); self.rejected(altered)
        value['relations'].append({**link, 'id': 'r2'}); self.rejected(value)

    def test_card_ids_and_counts_are_bounded(self):
        value = snapshot(); value['cards'] *= 2; self.rejected(value)
        value = snapshot(); value['cards'] *= 51; self.rejected(value, 'ANALYSIS_SIZE_LIMIT')

    def test_ids_and_json_reject_ambiguous_or_nonfinite_input(self):
        self.assertEqual(identifier(OWNER), OWNER)
        for bad in (OWNER.upper(), 'not-a-uuid', 1, None):
            with self.assertRaises(PreviewError): identifier(bad)
        with self.assertRaises(PreviewError): canonical({'value': float('nan')})


if __name__ == '__main__':
    unittest.main()
