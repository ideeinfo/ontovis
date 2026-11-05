"""Validated, atomic draft changes. Registration does not assert engineering facts."""
import copy
import json
from uuid import UUID,uuid5
from .assistant_store import require,digest,encoded,now
from .analysis_drafts import validate_snapshot


def operation_id(run_id,label):return str(uuid5(UUID(run_id),label))


def build(snapshot,plan,results,register,run_id,connection,project):
    board=copy.deepcopy(snapshot);receipts=[];aliases={'C'+str(i+1):c['id'] for i,c in enumerate(snapshot['cards'])}
    def targets(action):
        ids=[aliases.get(k) for k in action['targets']]
        require(ids and all(ids) and len(ids)==len(set(ids)),'ASSISTANT_TARGET_AMBIGUOUS',409)
        cards=[next(c for c in board['cards'] if c['id']==key) for key in ids]
        require(not any(c.get('historical') for c in cards),'ANALYSIS_HISTORY_READ_ONLY',409)
        return cards
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
        elif kind=='arrange':
            for n,card in enumerate(c for c in board['cards'] if not c['pinned']):card.update(x=40+n%3*400,y=40+n//3*400)
        elif kind=='rename':
            require(0<len(action['text'].strip())<=120);board['title']=action['text'].strip()
        elif kind=='save':save=True
        elif kind=='set_window':
            from .analysis_drafts import utc
            dates=action['text'].split('|');require(len(dates)==2 and utc(dates[0])<utc(dates[1]))
            # Fixed trend evidence cannot be silently relabelled as a new window.
            require(not any(c['kind']=='trend' for c in board['cards']),'ASSISTANT_FIXED_TREND_WINDOW',409)
            board['context'].update(timeFrom=dates[0],timeTo=dates[1])
        elif kind=='add_relation':
            cards=targets(action);require(len(cards)==2 and action['text'].strip())
            relation=dict(id=operation_id(run_id,'relation:'+str(index)),**{'from':cards[0]['id'],'to':cards[1]['id']},
                kind='hypothesis',origin='manual',reason=action['text'][:1000])
            if not any(all(r[k]==relation[k] for k in ('from','to','kind')) for r in board['relations']):board['relations'].append(relation)
            else:receipt['status']='already_present'
        elif kind in ('move_card','resize_card'):
            cards=targets(action);require(len(cards)==1 and action['x'] is not None and action['y'] is not None)
            cards[0].update(dict(x=action['x'],y=action['y']) if kind=='move_card' else dict(width=action['x'],height=action['y']))
        else:require(False,'ASSISTANT_TOOL_NOT_ALLOWED',403)
        receipts.append(receipt)
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
