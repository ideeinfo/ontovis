"""Versioned fault rehearsals, separate from measured alarms and field truth."""
from __future__ import annotations

from datetime import timedelta

from .analysis_drafts import digest, require, text, utc
from .demo_faults import diagnosis

SOURCE_ID = 'ontovis-simulated-faults'
EPOCH = 'pds-electrical-rehearsal-v1'
START = '2026-10-25T00:00:00Z'
END = '2026-10-25T00:03:00Z'
PROFILES = {
    '13001': {'cabinet': 'CN1', 'title': '柜温高报警 · 传感器读数偏高演练',
              'preset': '模拟柜温读数偏高而独立参照温度正常，仅验证测量链偏差分支；X91之后仍缺证。',
              'primaryRds': '=WEC+CN1-1B4', 'severity': 'warning', 'branch': 'sensor_bias_high'},
    '13002': {'cabinet': 'CN1', 'title': '柜温低报警 · 传感器读数偏低演练',
              'preset': '模拟柜温读数偏低而独立参照温度正常，仅验证测量链偏差分支；X91之后仍缺证。',
              'primaryRds': '=WEC+CN1-1B4', 'severity': 'warning', 'branch': 'sensor_bias_low'},
    '13003': {'cabinet': 'CN1', 'title': '浪涌保护状态接点异常演练',
              'preset': '模拟浪涌保护器状态接点断开；不模拟或认定实际雷击。',
              'primaryRds': '=WEC+CN1-1U2', 'severity': 'warning',
              'channel': {'rds': '=WEC+CN1-105A3/IX.2', 'moduleRds': '=WEC+CN1-105A3', 'address': 'IX.2'}},
    '13004': {'cabinet': 'CN1', 'title': '主断路器断开与反馈演练',
              'preset': '模拟人工断开主断路器，过流信号保持未动作；不认定实际跳闸原因。',
              'primaryRds': '=WEC+CN1-1Q1', 'severity': 'critical',
              'channel': {'rds': '=WEC+CN1-105A3/IX.1', 'moduleRds': '=WEC+CN1-105A3', 'address': 'IX.1'}},
}


def catalogue(project_code):
    require(project_code == 'Demo-PDS', 'SIMULATION_PROJECT_REQUIRED', 404)
    return {'sourceConnectionId': SOURCE_ID, 'sourceKind': 'simulated', 'mode': 'replay',
        'engineeringConfirmation': False, 'items': [identity(code) for code in PROFILES] + [identity('13001', recurrence=True)],
        'negativeCases': [{'faultCode': code, 'branch': 'unresolved_reference_chain', 'reason': diagnosis(code)['gap']}
                          for code in ('13001', '13002', '13033', '13035', '13058')]}


def browser_catalogue(project_code, body):
    require(type(body) is dict and set(body) in (set(), {'includeDetail'}, {'includeDetail', 'datasetId'}))
    value = catalogue(project_code)
    if body:
        require(body['includeDetail'] is True)
        selected = body.get('datasetId', value['items'][0]['datasetId'])
        item = next((row for row in value['items'] if row['datasetId'] == selected), None)
        require(item is not None, 'SIMULATION_DATASET_UNAVAILABLE', 404)
        value['initialDetail'] = detail(project_code, {key: item[key] for key in ('datasetId', 'datasetRevision')})
    return value


def identity(code, *, recurrence=False):
    require(type(code) is str and code in PROFILES, 'SIMULATION_FAULT_UNSUPPORTED', 422)
    profile = PROFILES[code]
    revision = digest({'epoch': EPOCH, 'faultCode': code, 'profile': profile, 'start': START, 'end': END})
    value = {'datasetId': 'SIM-PDS-'+code, 'datasetRevision': revision, 'faultCode': code,
            'sourceKind': 'simulated', 'sourceConnectionId': SOURCE_ID, 'epoch': EPOCH,
            'title': profile['title'], 'presetCause': profile['preset'], 'cabinet': profile['cabinet'],
            'primaryRds': profile['primaryRds'], 'timeFrom': START, 'timeTo': END,
            'branch': profile.get('branch', 'status_feedback'), 'retainedEvidenceGap': diagnosis(code)['gap'],
            'wholeFaultDiagnosisComplete': False, 'engineeringConfirmation': False, 'testChainQualification': 'separate'}
    if recurrence:
        require(code == '13001')
        value.update(datasetId='SIM-PDS-13001-recurrence-1', timeFrom='2026-10-26T00:00:00Z', timeTo='2026-10-26T00:03:00Z',
                     title='柜温高报警 · 独立复发演练')
        value['datasetRevision'] = digest({'originalRevision': revision, 'recurrence': 1,
            'start': value['timeFrom'], 'end': value['timeTo']})
    return value


def dataset(dataset_id, revision=None):
    text(dataset_id)
    code = dataset_id.removeprefix('SIM-PDS-')
    value = identity('13001', recurrence=True) if code == '13001-recurrence-1' else identity(code)
    require(dataset_id == value['datasetId'], 'SIMULATION_DATASET_UNAVAILABLE', 404)
    require(revision is None or revision == value['datasetRevision'], 'SIMULATION_DATASET_CHANGED', 409)
    return value


def stamp(seconds, start=START):
    return (utc(start) + timedelta(seconds=seconds)).isoformat(timespec='seconds').replace('+00:00', 'Z')


def alarms(dataset_id, revision=None):
    value = dataset(dataset_id, revision); code = value['faultCode']; profile = PROFILES[code]
    at = lambda seconds: stamp(seconds, value['timeFrom'])
    return {'dataset': value, 'watermark': 180, 'items': [{
        'sourceConnectionId': SOURCE_ID, 'sourceKind': 'simulated', 'sourceEventId': dataset_id+'-event-1',
        'sourceRevision': str(index+1), 'epoch': EPOCH, 'sequence': second,
        'externalAssetId': profile['primaryRds'], 'faultCode': code, 'severityRaw': profile['severity'],
        'severity': profile['severity'], 'severityMappingRevision': 'sim-severity:1',
        'state': state, 'acknowledgement': 'unknown', 'occurredAt': at(30),
        'updatedAt': at(second), 'clearedAt': at(second) if state == 'cleared' else None,
        'sourceTime': at(second), 'receivedAt': at(second+1), 'quality': 'good',
        'engineeringConfirmation': False,
    } for index, (second, state) in enumerate(((30, 'active'), (150, 'cleared')))]}


def detail(project_code, body):
    catalogue(project_code)
    require(type(body) is dict and set(body) == {'datasetId', 'datasetRevision'})
    value = dataset(body['datasetId'], body['datasetRevision'])
    metrics = ['device_feedback', 'supply_voltage', 'overcurrent']
    if value['faultCode'] in ('13001', '13002'):
        metrics = ['sensor_temperature', 'reference_temperature', *metrics]
    return {'dataset': value, 'alarms': alarms(value['datasetId'], value['datasetRevision'])['items'],
            'trends': [trend(value['datasetId'], metric, value['timeFrom'], value['timeTo'], value['datasetRevision']) for metric in metrics]}


def trend(dataset_id, metric, time_from, time_to, revision=None):
    value = dataset(dataset_id, revision)
    require(metric in ('device_feedback', 'supply_voltage', 'overcurrent', 'sensor_temperature', 'reference_temperature'), 'SIMULATION_METRIC_UNAVAILABLE', 404)
    require(metric not in ('sensor_temperature', 'reference_temperature') or value['faultCode'] in ('13001', '13002'), 'SIMULATION_METRIC_UNAVAILABLE', 404)
    start, end = utc(time_from), utc(time_to)
    require(utc(value['timeFrom']) <= start < end <= utc(value['timeTo']))
    at = lambda seconds: stamp(seconds, value['timeFrom'])
    samples = []
    for second in range(181):
        time = utc(at(second))
        if not start <= time <= end:
            continue
        # A fixed quality gap exercises missing data rather than interpolating it.
        quality = 'bad' if second == 90 else 'good'
        number = (24 + (second % 5-2)*.03) if metric == 'supply_voltage' else int(30 <= second < 150) if metric == 'device_feedback' else 0
        if metric == 'reference_temperature': number = 24 + (second % 5-2)*.05
        if metric == 'sensor_temperature': number = (72 if value['faultCode'] == '13001' else -18) if 30 <= second < 150 else 24
        samples.append({'sourceTime': at(second), 'receivedAt': at(second+1), 'sequence': second,
                        'value': round(number, 2) if quality == 'good' else None, 'quality': quality})
    return {'dataset': value, 'metricId': metric, 'unit': 'degC' if metric.endswith('_temperature') else 'V' if metric == 'supply_voltage' else '1',
            'valueType': 'number', 'epoch': EPOCH, 'sourceKind': 'simulated', 'mode': 'replay',
            'timeFrom': time_from, 'timeTo': time_to, 'watermark': 180, 'samples': samples,
            'engineeringConfirmation': False}
