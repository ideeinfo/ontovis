"""Bounded teaching scenarios derived from the existing RCA manual catalogue.

The source catalogue belongs to ON-SHORE. These rules are explicitly a Demo-PDS
exercise, not a transfer of its confirmed engineering relationships.
"""
from __future__ import annotations

from copy import deepcopy

DEMO_PROJECT = 'Demo-PDS'
BATCH = 'pds-cabinet-exercise-v1'
RULE_REVISION = 'pds-diagnostic-rules:2'

# Code, manual name/page, candidate circuit objects, and unresolved evidence.
FAULTS = (
    ('13001', '机舱柜温度高', 47, (('1B4', '温度传感器'), ('1W4', '监测线缆'), ('X91', '跨页连接器')), 'X91后的跨页源点未闭合'),
    ('13002', '机舱柜温度低', 48, (('1B4', '温度传感器'), ('1W4', '监测线缆'), ('X91', '跨页连接器')), 'X91后的跨页源点未闭合'),
    ('13003', '机舱柜防雷故障', 48, (('1U2', '浪涌保护器'), ('105A3/IX.2', '状态输入通道'), ('105A3', '输入模块')), '报警不能单独证明雷击或器件失效'),
    ('13004', '机舱柜400V主空开跳闸', 48, (('1Q1', '400V主断路器'), ('105A3/IX.1', '状态输入通道'), ('105A3', '输入模块')), '短路、过流或手动断开尚需区分'),
    ('13033', '机舱柜内24V空开', 54, (('80W1', '24VDC供电线缆'), ('XP1', '供电接口'), ('X91', '跨页连接器')), '源断路器及输入通道缺证，不推定位号'),
    ('13035', '机舱柜24V开关电源', 54, (('80W1', '24VDC供电线缆'), ('XP1', '供电接口'), ('X91', '跨页连接器')), '电源本体及输入通道缺证，不确认根因'),
    ('13058', '机舱低压柜供电开关跳闸', 59, (('2Q1', '信号柜供电开关候选'), ('105A3/IX.3', '状态输入通道'), ('105A3', '输入模块')), '低压柜与信号柜术语等价性未确认'),
)


def scenarios():
    result = []
    for index in range(20):
        code, name, page, parts, gap = FAULTS[index % len(FAULTS)]
        cabinet = 'CN2' if code == '13058' or code in ('13033', '13035') and index >= 7 else 'CN1'
        result.append({'ordinal': index + 1, 'code': code, 'title': name,
                       'cabinet': cabinet, 'round': index // len(FAULTS) + 1})
    return result


def diagnosis(code):
    definition = next(item for item in FAULTS if item[0] == code)
    _, name, page, parts, gap = definition
    nodes = [{'id': 'alarm', 'kind': 'alarm', 'label': code + ' · ' + name, 'state': 'simulated'},
             {'id': 'hypothesis', 'kind': 'hypothesis', 'label': '供电、器件或信号链异常候选', 'state': 'hypothesis'}]
    edges = [{'source': 'alarm', 'target': 'hypothesis', 'label': '排查候选'}]
    for index, (suffix, label) in enumerate(parts):
        key = 'part-' + str(index)
        nodes.append({'id': key, 'kind': 'component', 'label': label, 'rds': '=WEC+CN1-' + suffix,
                      'state': 'reference_only', 'locateKey': key})
        edges.append({'source': 'hypothesis' if index == 0 else 'part-' + str(index - 1),
                      'target': key, 'label': '参照链路'})
    for key, label in (('CN1', '机舱动力柜'), ('CN2', '机舱信号柜')):
        nodes.append({'id': key, 'kind': 'cabinet', 'label': key + ' · ' + label,
                      'state': 'demonstration', 'locateKey': key})
        edges.append({'source': 'part-0', 'target': key, 'label': '演示排查目标'})
    nodes.append({'id': 'gap', 'kind': 'gap', 'label': gap, 'state': 'unverified'})
    edges.append({'source': 'hypothesis', 'target': 'gap', 'label': '保留缺口'})
    return deepcopy({'revision': RULE_REVISION, 'mode': 'demonstration_rules', 'engineeringConfirmation': False,
        'source': {'projectCode': 'ON-SHORE', 'catalogue': 'OntoBase RCA_FAULT_CATALOG',
                   'manualPages': [page], 'applicability': 'reference_only'},
        'nodes': nodes, 'edges': edges, 'gap': gap,
        'checks': [{'id': 'alarm-context', 'label': '核对演示报警代码、时间与所选对象'},
                   {'id': 'circuit', 'label': '沿参照链核对器件、接口及图纸，记录缺口'},
                   {'id': 'photo-location', 'label': '查看固定版本照片并记录对象区域或缺口'},
                   {'id': 'review', 'label': '记录演示处理与复核依据；现场事实保持待核实'}]})
