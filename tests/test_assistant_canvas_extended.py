import copy
import unittest
from uuid import uuid4

from apps.api.assistant_canvas_tasks import build
from apps.api.assistant_tasks import validate_plan
from apps.api.authority import PreviewError
from tests.test_assistant_tasks import board, action


def note(index, **extra):
    return dict(id='note'+str(index), kind='analysis', title='笔记'+str(index), note='原始内容',
                x=index*400, y=40, width=340, height=250, pinned=False, **extra)


class ExtendedCanvasTests(unittest.TestCase):
    def apply(self, original, actions, **kwargs):
        return build(original, dict(actions=actions), [], None, str(uuid4()), 'source', 'Demo-PDS', **kwargs)

    def test_edit_group_pin_and_relation_are_one_atomic_draft(self):
        original=board();original['cards']=[note(1),note(2)]
        actions=[action('update_note',['C1'],'已核对的人工记录'), action('rename_card',['C1'],'温度核对'),
                 action('group_cards',['C1','C2'],'本次证据'), action('pin_cards',['C2']),
                 action('add_support',['C1','C2'],'仅表示本次分析支持依据')]
        validate_plan(dict(intent='edit',queries=[],actions=actions))
        updated,receipts,save=self.apply(original,actions)
        self.assertEqual('原始内容',original['cards'][0]['note'])
        self.assertEqual('已核对的人工记录',updated['cards'][0]['note'])
        self.assertEqual('温度核对',updated['cards'][0]['title'])
        self.assertTrue(updated['cards'][1]['pinned'])
        self.assertEqual(updated['cards'][0]['frameId'],updated['cards'][1]['frameId'])
        self.assertEqual('本次证据',updated['frames'][0]['title'])
        self.assertEqual('supports',updated['relations'][0]['kind'])
        self.assertEqual(5,len(receipts));self.assertFalse(save)

    def test_relation_edit_ungroup_and_source_relation_protection(self):
        original=board();original['cards']=[note(1),note(2)]
        grouped,_,_=self.apply(original,[action('group_cards',['C1','C2'],'Group'),action('add_relation',['C1','C2'],'待核验')])
        updated,_,_=self.apply(grouped,[action('rename_group',['G1'],'新分组'),action('update_relation',['L1'],'补充依据'),action('ungroup',['G1'])])
        self.assertEqual([],updated['frames']);self.assertNotIn('frameId',updated['cards'][0])
        self.assertEqual('补充依据',updated['relations'][0]['reason'])
        removed,_,_=self.apply(updated,[action('remove_relations',['L1'])]);self.assertFalse(removed['relations'])
        updated['relations'][0].update(origin='source',kind='engineering')
        for kind in ('update_relation','remove_relations'):
            with self.assertRaises(PreviewError):self.apply(updated,[action(kind,['L1'],'不得改权威关系')])

    def test_limits_historical_targets_and_ambiguous_targets_leave_original_intact(self):
        original=board();original['cards']=[note(1),note(2,historical=True)]
        for final in [action('update_note',['C2'],'no'),action('pin_cards',['C9']),action('rename_card',['C1','C2'],'no')]:
            before=copy.deepcopy(original)
            with self.assertRaises(PreviewError):self.apply(original,[action('update_note',['C1'],'candidate'),final])
            self.assertEqual(before,original)
        with self.assertRaises(PreviewError):self.apply(original,[action('update_note',['C1'],'x'*4001)])

    def test_arrangement_keeps_pinned_cards_and_expands_groups(self):
        original=board();original['cards']=[note(1),note(2),note(3)]
        original['cards'][0].update(pinned=True,x=32,y=40,width=700,height=600)
        updated,_,_=self.apply(original,[action('arrange')])
        self.assertEqual(original['cards'][0],updated['cards'][0])
        for card in updated['cards'][1:]:
            anchor=updated['cards'][0]
            self.assertFalse(card['x']<anchor['x']+anchor['width']+24 and card['x']+card['width']+24>anchor['x']
                             and card['y']<anchor['y']+anchor['height']+24 and card['y']+card['height']+24>anchor['y'])

    def test_history_is_exclusive_except_explicit_save_and_validated(self):
        original=board();original['cards']=[note(1)]
        prior=board();prior['title']='先前草稿'
        def special(kind, request, current, index):return copy.deepcopy(prior)
        restored,_,save=self.apply(original,[action('undo'),action('save')],special=special)
        self.assertEqual('先前草稿',restored['title']);self.assertTrue(save)
        with self.assertRaises(PreviewError):self.apply(original,[action('undo'),action('rename',text='not atomic')],special=special)
        prior['projectCode']='foreign'
        with self.assertRaises(PreviewError):self.apply(original,[action('restore_revision',text='r1')],special=special)

    def test_fixed_trends_need_registration_and_historical_trends_remain_fixed(self):
        original=board();original['cards']=[dict(id='trend',kind='trend',title='趋势',x=0,y=0,width=340,height=250,pinned=False,
            source=dict(system='ontovis',ontobaseConnectionId='source',projectCode='Demo-PDS',id='ref',revision='a'*64))]
        with self.assertRaises(PreviewError):self.apply(original,[action('set_window',text='2026-01-01T00:00:00Z|2026-01-01T01:00:00Z')])
