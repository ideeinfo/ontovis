"""Bounded memory over revalidated selected summaries; historical answers stay hypotheses."""
import json
from .assistant_summaries import redact


def build_history(records, summaries, service_revision, private=()):
    current={s['evidenceRefId']:s for s in summaries if s['availability']=='available'}
    retained=[];skipped=[]
    labels=dict(observations='观察',hypotheses='待验证假设',gaps='缺口',nextSteps='下一步核验')
    for row in records[-4:]:
        if row['state'] not in ('complete','partial') or not row['result_json']:continue
        previous=json.loads(row['sources_json']);mapping={}
        valid=row['service_revision']==service_revision and bool(previous)
        for source in previous:
            now=current.get(source['evidenceRefId'])
            if (source.get('availability')!='available' or not now
                    or source.get('sourceRevision')!=now.get('sourceRevision')
                    or not source.get('summaryHash') or source['summaryHash']!=now.get('summaryHash')
                    or source.get('retrievalRevision')!=now.get('retrievalRevision')):
                valid=False;break
            mapping[source['key']]=now['key']
        if not valid:
            skipped.append(dict(runId=row['id'],reason='ASSISTANT_HISTORY_SOURCES_CHANGED'));continue
        answer=json.loads(row['result_json'])['answer'];parts=[];refs=set()
        for group,label in labels.items():
            for item in answer[group]:
                if not all(key in mapping for key in item['refs']):valid=False;break
                mapped=[mapping[key] for key in item['refs']]
                line=label+'：'+redact(item['text'],private)+((' ['+','.join(mapped)+']') if mapped else '')
                if len('\n'.join(parts+[line]))>1000:continue
                parts.append(line);refs.update(mapped)
            if not valid:break
        if not valid or not refs or not parts:
            skipped.append(dict(runId=row['id'],reason='ASSISTANT_HISTORY_SOURCES_CHANGED'));continue
        retained.append(dict(question=redact(json.loads(row['input_json'])['question'],private)[:400],
                             answer='\n'.join(parts),refs=sorted(refs)))
    return retained,skipped
