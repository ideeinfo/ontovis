"""Validated, atomic draft changes. Registration does not assert engineering facts."""
import copy
import json
from uuid import UUID,uuid5
from .assistant_store import require,digest,encoded,now
from .analysis_drafts import validate_snapshot

ACTIONS = ('add_results','remove_cards','add_note','arrange','rename','save','set_window','add_relation','move_card','resize_card',
           'update_note','append_note','rename_card','copy_card','pin_cards','unpin_cards','group_cards','rename_group','ungroup',
           'update_relation','remove_relations','add_support','add_contradiction','add_reference','replace_source',
           'undo','redo','restore_revision','reset_card_view')


def frame_bounds(board):
    for frame in board.get('frames',[]):
        members=[c for c in board['cards'] if c.get('frameId')==frame['id']]
        if not members:continue
        x=max(-20000,min(c['x'] for c in members)-20);y=max(-20000,min(c['y'] for c in members)-38)
        frame.update(x=x,y=y,width=max(280,min(20000,max(c['x']+c['width'] for c in members)-x+20)),
                     height=max(220,min(20000,max(c['y']+c['height'] for c in members)-y+20)))
    return board


def arrange(board):
    """Same grouping and pinned-obstacle layout as the manual Canvas arrange action."""
    placed=[c for c in board['cards'] if c['pinned']]
    step_x=max([300]+[c['width'] for c in board['cards']])+40
    step_y=max([200]+[c['height'] for c in board['cards']])+40
    groups=list(dict.fromkeys(c.get('frameId','') for c in board['cards']));start=0
    def overlaps(a,b):
        return a['x']<b['x']+b['width']+24 and a['x']+a['width']+24>b['x'] and a['y']<b['y']+b['height']+24 and a['y']+a['height']+24>b['y']
    for group in groups:
        last=start
        for card in (c for c in board['cards'] if not c['pinned'] and c.get('frameId','')==group):
            found=None
            for row in range(start,120):
                for column in range(3):
                    candidate={**card,'x':32+column*step_x,'y':40+row*step_y}
                    if not any(overlaps(candidate,p) for p in placed):found=candidate;last=row;break
                if found:break
            if found and found['y']<=20000:card.update(x=found['x'],y=found['y']);placed.append(card)
        start=last+2
    return frame_bounds(board)

def operation_id(run_id,label):return str(uuid5(UUID(run_id),label))


def build(snapshot,plan,results,register,run_id,connection,project,special=None):
    board=copy.deepcopy(snapshot);receipts=[];aliases={'C'+str(i+1):c['id'] for i,c in enumerate(snapshot['cards'])}
    groups={'G'+str(i+1):g['id'] for i,g in enumerate(snapshot.get('frames',[]))}
    links={'L'+str(i+1):r['id'] for i,r in enumerate(snapshot['relations'])}
    history=[a for a in plan['actions'] if a['kind'] in ('undo','redo','restore_revision')]
    require(not history or len(history)==1 and all(a['kind'] in (history[0]['kind'],'save') for a in plan['actions']),
            'ASSISTANT_HISTORY_EXCLUSIVE',409)
    def targets(action):
        ids=[aliases.get(k) for k in action['targets']]
        require(ids and all(ids) and len(ids)==len(set(ids)),'ASSISTANT_TARGET_AMBIGUOUS',409)
        cards=[next((c for c in board['cards'] if c['id']==key),None) for key in ids]
        require(all(cards),'ASSISTANT_TARGET_AMBIGUOUS',409)
        require(not any(c.get('historical') for c in cards),'ANALYSIS_HISTORY_READ_ONLY',409)
        return cards
    def named(action,lookup,items):
        ids=[lookup.get(k) for k in action['targets']]
        require(ids and all(ids) and len(ids)==len(set(ids)),'ASSISTANT_TARGET_AMBIGUOUS',409)
        found=[next((v for v in items if v['id']==key),None) for key in ids]
        require(all(found),'ASSISTANT_TARGET_AMBIGUOUS',409)
        return found
    def one(action):
        cards=targets(action);require(len(cards)==1,'ASSISTANT_TARGET_AMBIGUOUS',409);return cards[0]
    save=False
    for index,action in enumerate(plan['actions']):
        kind=action['kind'];receipt=dict(operationId=operation_id(run_id,'action:'+str(index)),kind=kind,status='prepared')
        if kind=='add_results':
            rows=[r for r in results if not action['targets'] or r['key'] in action['targets'] or r['identifier'] in action['targets']]
            require(rows and (not action['targets'] or all(any(k in (r['key'],r['identifier']) for r in rows) for k in action['targets'])),
                    'ASSISTANT_TARGET_AMBIGUOUS',409)
            for row in rows:
                ref=register(row,index)
                existing=next((c for c in board['cards'] if not c.get('historical') and c.get('source',{}).get('revision')==ref['sourceRevision']
                               and c['kind']==('model3d' if row['kind']=='model' else row['kind'])),None)
                if existing:card_id=existing['id'];status='already_present'
                else:
                    require(len(board['cards'])<50,'ANALYSIS_SIZE_LIMIT',413)
                    card_id=operation_id(run_id,'card:'+row['key']);n=len(board['cards'])
                    board['cards'].append(dict(id=card_id,kind='model3d' if row['kind']=='model' else row['kind'],title=row['title'][:120],
                        x=40+(n%3)*380,y=40+(n//3)*300,width=340,height=250,pinned=False,
                        source=dict(system='ontobase' if row['kind'] in ('object','drawing','document','photo') else 'ontovis',
                            ontobaseConnectionId=connection,projectCode=project,id=ref['evidenceRefId'],revision=ref['sourceRevision'])))
                    status='added'
                receipts.append(dict(operationId=operation_id(run_id,'source:'+row['key']),kind='add_results',status=status,
                    cardId=card_id,identifier=row['identifier'],sourceRevision=ref['sourceRevision'],sourceVersion=row['version'],simulated=row.get('simulated',False)))
            continue
        elif kind=='remove_cards':
            ids={c['id'] for c in targets(action)}
            board['cards']=[c for c in board['cards'] if c['id'] not in ids]
            board['relations']=[r for r in board['relations'] if not ids.intersection((r['from'],r['to']))]
            receipt['cardIds']=sorted(ids)
        elif kind=='add_note':
            require(0<len(action['text'].strip())<=4000 and len(board['cards'])<50)
            board['cards'].append(dict(id=operation_id(run_id,'note:'+str(index)),kind='analysis',title='助手笔记 · 待核验',note=action['text'],
                x=40,y=40+len(board['cards'])*30,width=340,height=260,pinned=False))
            aliases['C'+str(len(aliases)+1)]=board['cards'][-1]['id']
            receipt.update(cardId=board['cards'][-1]['id'])
        elif kind in ('update_note','append_note'):
            card=one(action);require(card['kind']=='analysis','ASSISTANT_TOOL_NOT_ALLOWED',403)
            card['note']=(card.get('note','') if kind=='append_note' else '')+action['text'];receipt.update(cardId=card['id'],label=card['title'])
        elif kind=='rename_card':
            card=one(action);card['title']=action['text'].strip();receipt.update(cardId=card['id'],label=card['title'])
        elif kind=='copy_card':
            card=copy.deepcopy(one(action));card.update(id=operation_id(run_id,'copy:'+str(index)),x=card['x']+48,y=card['y']+48,pinned=False)
            board['cards'].append(card);aliases['C'+str(len(aliases)+1)]=card['id'];receipt.update(cardId=card['id'],label=card['title'])
        elif kind in ('pin_cards','unpin_cards','reset_card_view'):
            cards=targets(action)
            for card in cards:
                if kind=='reset_card_view':card.pop('view',None)
                else:card['pinned']=kind=='pin_cards'
            receipt['cardIds']=[c['id'] for c in cards]
        elif kind=='group_cards':
            cards=targets(action);require(len(cards)>=2 and len(board.get('frames',[]))<10,'ANALYSIS_SIZE_LIMIT',413)
            group=dict(id=operation_id(run_id,'group:'+str(index)),title=action['text'].strip(),x=0,y=0,width=280,height=220)
            board.setdefault('frames',[]).append(group);groups['G'+str(len(groups)+1)]=group['id']
            for card in cards:card['frameId']=group['id']
            receipt.update(groupId=group['id'],label=group['title'],cardIds=[c['id'] for c in cards])
        elif kind in ('rename_group','ungroup'):
            selected=named(action,groups,board.get('frames',[]));require(kind=='ungroup' or len(selected)==1,'ASSISTANT_TARGET_AMBIGUOUS',409)
            ids={g['id'] for g in selected}
            if kind=='rename_group':selected[0]['title']=action['text'].strip()
            else:
                board['frames']=[g for g in board.get('frames',[]) if g['id'] not in ids]
                for card in board['cards']:
                    if card.get('frameId') in ids:card.pop('frameId')
            receipt['groupIds']=sorted(ids)
        elif kind=='arrange':
            arrange(board)
        elif kind=='rename':
            require(0<len(action['text'].strip())<=120);board['title']=action['text'].strip()
        elif kind=='save':save=True
        elif kind in ('undo','redo','restore_revision','replace_source'):
            require(special is not None,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            board=special(kind,action,board,index)
            if kind in ('undo','redo'):receipt['historyDirection']=kind
            if kind=='restore_revision':receipt['restoredFrom']=action['text']
        elif kind=='set_window':
            from .analysis_drafts import utc
            dates=action['text'].split('|');require(len(dates)==2 and utc(dates[0])<utc(dates[1]))
            # Fixed trend evidence cannot be silently relabelled as a new window.
            if any(c['kind']=='trend' and not c.get('historical') for c in board['cards']):
                require(special is not None,'ASSISTANT_FIXED_TREND_WINDOW',409)
                board=special(kind,action,board,index)
            board['context'].update(timeFrom=dates[0],timeTo=dates[1])
        elif kind in ('add_relation','add_support','add_contradiction','add_reference'):
            cards=targets(action);require(len(cards)==2 and action['text'].strip())
            relation=dict(id=operation_id(run_id,'relation:'+str(index)),**{'from':cards[0]['id'],'to':cards[1]['id']},
                kind={'add_relation':'hypothesis','add_support':'supports','add_contradiction':'contradicts','add_reference':'reference'}[kind],origin='manual',reason=action['text'].strip())
            if not any(all(r[k]==relation[k] for k in ('from','to','kind')) for r in board['relations']):
                board['relations'].append(relation);links['L'+str(len(links)+1)]=relation['id']
            else:receipt['status']='already_present'
        elif kind in ('update_relation','remove_relations'):
            selected=named(action,links,board['relations'])
            require(all(r['origin']=='manual' and r['kind']!='engineering' for r in selected),'ASSISTANT_SOURCE_RELATION_READ_ONLY',403)
            require(kind=='remove_relations' or len(selected)==1,'ASSISTANT_TARGET_AMBIGUOUS',409)
            if kind=='update_relation':selected[0]['reason']=action['text'].strip()
            else:board['relations']=[r for r in board['relations'] if r not in selected]
            receipt['relationIds']=[r['id'] for r in selected]
        elif kind in ('move_card','resize_card'):
            cards=targets(action);require(len(cards)==1 and action['x'] is not None and action['y'] is not None)
            cards[0].update(dict(x=action['x'],y=action['y'],pinned=False) if kind=='move_card' else dict(width=action['x'],height=action['y'],pinned=False))
        else:require(False,'ASSISTANT_TOOL_NOT_ALLOWED',403)
        receipts.append(receipt)
    if not history:frame_bounds(board)
    validate_snapshot(board,connection,project)
    return board,receipts,save


def schema(library):
    with library.connect() as db:
        db.execute('''create table if not exists assistant_canvas_operations (
            run_id text not null,selection text not null,base_digest text not null,prepared_json text not null,
            ack_json text,created_at text not null,primary key(run_id,selection))''')


def load(library,run_id,selection):
    schema(library)
    with library.connect() as db:
        row=db.execute('select * from assistant_canvas_operations where run_id=? and selection=?',(run_id,selection)).fetchone()
    return dict(row) if row else None


def retain(library,run_id,selection,base,value):
    with library.connect() as db:
        db.execute('insert into assistant_canvas_operations values(?,?,?,?,?,?)',
                   (run_id,selection,base,encoded(value),None,now()))


def acknowledge(library,run_id,selection,value):
    with library.connect() as db:
        db.execute('begin immediate')
        row=db.execute('select ack_json from assistant_canvas_operations where run_id=? and selection=?',(run_id,selection)).fetchone()
        require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        if row['ack_json']:
            old=json.loads(row['ack_json']);require(old==value,'ASSISTANT_REQUEST_CONFLICT',409);return old
        db.execute('update assistant_canvas_operations set ack_json=? where run_id=? and selection=?',(encoded(value),run_id,selection))
    return value
