import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getBeaufortInfo,
  getWindDirectionInfo,
  getPrecipitationInfo,
  getCloudCoverageInfo,
  getOperationAdvice
} from '../src/weatherCardLogic.ts';

test('getBeaufortInfo correctly calculates Beaufort wind scale and turbine operational stages', () => {
  // 空值或无效值
  const nullResult = getBeaufortInfo(null);
  assert.equal(nullResult.scale, null);
  assert.equal(nullResult.stage, 'unknown');

  // 0 级 Calm (0.1 m/s)
  const calm = getBeaufortInfo(0.1);
  assert.equal(calm.scale, 0);
  assert.equal(calm.stage, 'idle');

  // 2 级 Light breeze (2.0 m/s) - 低于切入风速 3m/s 处于待机状态
  const breeze = getBeaufortInfo(2.0);
  assert.equal(breeze.scale, 2);
  assert.equal(breeze.stage, 'idle');

  // 4 级 Moderate breeze (6.5 m/s) - 切入发电爬坡段
  const mod = getBeaufortInfo(6.5);
  assert.equal(mod.scale, 4);
  assert.equal(mod.stage, 'generating');
  assert.match(mod.name, /4级 和风/);

  // 6 级 Strong breeze (12.0 m/s) - 额定满发恒功段 (11.5~25)
  const strong = getBeaufortInfo(12.0);
  assert.equal(strong.scale, 6);
  assert.equal(strong.stage, 'rated');

  // 10 级 Storm (26.0 m/s) - 达到或超出切出风速 (>=25)
  const storm = getBeaufortInfo(26.0);
  assert.equal(storm.scale, 10);
  assert.equal(storm.stage, 'cutout');

  // 英文自适应
  const enMod = getBeaufortInfo(6.5, true);
  assert.equal(enMod.name, '4 Moderate breeze');
  assert.match(enMod.stageLabel, /Cut-in/);
});

test('getWindDirectionInfo correctly maps 360-degree angles to 16 cardinal points', () => {
  // 无效值
  const nullDir = getWindDirectionInfo(null);
  assert.equal(nullDir.code, '—');
  assert.equal(nullDir.degrees, null);

  // 正北 (0° 或 360°)
  const north0 = getWindDirectionInfo(0);
  assert.equal(north0.code, 'N');
  assert.equal(north0.name, '北风');
  assert.equal(north0.oppositeCode, 'S');

  const north360 = getWindDirectionInfo(360);
  assert.equal(north360.code, 'N');

  // 正东 (90°)
  const east = getWindDirectionInfo(90);
  assert.equal(east.code, 'E');
  assert.equal(east.name, '东风');

  // 东南偏东 (112.5°)
  const ese = getWindDirectionInfo(112.5);
  assert.equal(ese.code, 'ESE');
  assert.equal(ese.name, '东南偏东风');

  // 东南风 (135°)
  const se = getWindDirectionInfo(135);
  assert.equal(se.code, 'SE');
  assert.equal(se.name, '东南风');
  assert.equal(se.oppositeCode, 'NW');

  // 正南 (180°)
  const south = getWindDirectionInfo(180);
  assert.equal(south.code, 'S');
  assert.equal(south.name, '南风');

  // 西北偏西 (292.5°)
  const wnw = getWindDirectionInfo(292.5);
  assert.equal(wnw.code, 'WNW');
  assert.equal(wnw.name, '西北偏西风');

  // 英文模式
  const seEn = getWindDirectionInfo(135, true);
  assert.equal(seEn.name, 'Southeast');
});

test('getPrecipitationInfo evaluates rain levels accurately', () => {
  // 无雨
  const dry = getPrecipitationInfo(0);
  assert.equal(dry.label, '无雨干爽');

  // 小雨 (1.5mm)
  const light = getPrecipitationInfo(1.5);
  assert.equal(light.label, '小雨淅沥');

  // 中雨 (5.0mm)
  const mod = getPrecipitationInfo(5.0);
  assert.equal(mod.label, '中雨');

  // 大雨 (10.0mm)
  const heavy = getPrecipitationInfo(10.0);
  assert.equal(heavy.label, '大雨');

  // 暴雨 (20.0mm)
  const storm = getPrecipitationInfo(20.0);
  assert.equal(storm.label, '暴雨预警');
});

test('getCloudCoverageInfo describes cloud fractions and lighting types', () => {
  // 晴空少云 (10%)
  const clear = getCloudCoverageInfo(10);
  assert.equal(clear.label, '晴朗透亮');
  assert.match(clear.lighting, /直射光照/);

  // 晴间多云 (40%)
  const partly = getCloudCoverageInfo(40);
  assert.equal(partly.label, '晴间多云');

  // 多云遮蔽 (75%)
  const cloudy = getCloudCoverageInfo(75);
  assert.equal(cloudy.label, '多云遮蔽');
  assert.match(cloudy.lighting, /漫射天光/);

  // 阴天浓云 (95%)
  const overcast = getCloudCoverageInfo(95);
  assert.equal(overcast.label, '浓云密布');
  assert.match(overcast.lighting, /天空高散射漫射光/);
});

test('getOperationAdvice gives accurate safety recommendations for wind farm tasks', () => {
  // 极端大风 (20 m/s)
  const danger = getOperationAdvice('clear', 20.0, 0);
  assert.equal(danger.status, 'danger');
  assert.match(danger.title, /大风高危预警/);

  // 阴雨天气 (rain, 4.0 m/s)
  const rain = getOperationAdvice('rain', 4.0, 2.0);
  assert.equal(rain.status, 'warning');
  assert.match(rain.title, /阴雨湿滑警告/);

  // 浓雾天气 (fog)
  const fog = getOperationAdvice('fog', 3.0, 0);
  assert.equal(fog.status, 'warning');
  assert.match(fog.title, /浓雾能见度受限/);

  // 强风警惕 (14.0 m/s)
  const strong = getOperationAdvice('clear', 14.0, 0);
  assert.equal(strong.status, 'caution');
  assert.match(strong.title, /强风巡检提示/);

  // 良好气象 (6.0 m/s, clear)
  const good = getOperationAdvice('clear', 6.0, 0);
  assert.equal(good.status, 'good');
  assert.match(good.title, /气象窗口良好/);
});
