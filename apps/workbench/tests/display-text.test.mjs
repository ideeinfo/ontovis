import assert from 'node:assert/strict';
import test from 'node:test';
import {displayText} from '../src/displayText.ts';

test('earlier labels are presented with the current terminology',()=>{
  assert.equal(displayText('模拟报警对象 · 演练参照 · 模拟回放 · 演示安装'),
    '报警对象 · 建议检查 · 报警回放 · 测试安装');
  assert.equal(displayText('24VDC供电线缆 · 13033 演练排查清单'),'24VDC供电线缆 · 13033 排查清单');
  assert.equal(displayText('Simulation · Rehearsals · SIM'),'Test · Tests · TEST');
  assert.equal(displayText(undefined),'');
});

test('display wording preserves project, order and dataset IDs',()=>{
  const source='Demo-PDS · DEMO-PDS-WO-001 · SIM-PDS-13033 · https://demo.ontobase.ai';
  assert.equal(displayText(source),source);
});
