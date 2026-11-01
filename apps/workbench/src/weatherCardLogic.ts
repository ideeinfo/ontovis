export interface BeaufortInfo {
  scale: number | null;
  name: string;
  speedMs: number | null;
  stage: 'forecast' | 'unknown';
  stageLabel: string;
  description: string;
}

export function getBeaufortInfo(speed: number | null | undefined, en = false): BeaufortInfo {
  if (speed === null || speed === undefined || !Number.isFinite(speed) || speed < 0) {
    return {
      scale: null,
      name: '—',
      speedMs: null,
      stage: 'unknown',
      stageLabel: en ? 'Wind unknown' : '风况未知',
      description: en ? 'No wind telemetry or forecast.' : '暂无可用风速数据。'
    };
  }
  const s = Math.max(0, speed);
  let scale = 0;
  let zhName = '0级 无风';
  let enName = '0 Calm';

  if (s < 0.3) { scale = 0; zhName = '0级 无风'; enName = '0 Calm'; }
  else if (s < 1.6) { scale = 1; zhName = '1级 软风'; enName = '1 Light air'; }
  else if (s < 3.4) { scale = 2; zhName = '2级 轻风'; enName = '2 Light breeze'; }
  else if (s < 5.5) { scale = 3; zhName = '3级 微风'; enName = '3 Gentle breeze'; }
  else if (s < 8.0) { scale = 4; zhName = '4级 和风'; enName = '4 Moderate breeze'; }
  else if (s < 10.8) { scale = 5; zhName = '5级 清劲风'; enName = '5 Fresh breeze'; }
  else if (s < 13.9) { scale = 6; zhName = '6级 强风'; enName = '6 Strong breeze'; }
  else if (s < 17.2) { scale = 7; zhName = '7级 疾风'; enName = '7 Near gale'; }
  else if (s < 20.8) { scale = 8; zhName = '8级 大风'; enName = '8 Gale'; }
  else if (s < 24.5) { scale = 9; zhName = '9级 烈风'; enName = '9 Strong gale'; }
  else if (s < 28.5) { scale = 10; zhName = '10级 狂风'; enName = '10 Storm'; }
  else if (s < 32.7) { scale = 11; zhName = '11级 暴风'; enName = '11 Violent storm'; }
  else { scale = 12; zhName = '12级 飓风'; enName = '12 Hurricane'; }

  const stage: BeaufortInfo['stage'] = 'forecast';
  const stageLabel = en ? '10 m forecast reference' : '10 m 预报参考';
  const description = en ? 'Forecast wind does not determine turbine operating state.' : '预报风速不代表设备运行状态。';

  return {
    scale,
    name: en ? enName : zhName,
    speedMs: s,
    stage,
    stageLabel,
    description
  };
}

export interface WindDirectionInfo {
  code: string;
  name: string;
  degrees: number | null;
  oppositeCode: string;
}

const SECTORS = [
  { code: 'N', zh: '北风', en: 'North', opp: 'S' },
  { code: 'NNE', zh: '东北偏北风', en: 'North-Northeast', opp: 'SSW' },
  { code: 'NE', zh: '东北风', en: 'Northeast', opp: 'SW' },
  { code: 'ENE', zh: '东北偏东风', en: 'East-Northeast', opp: 'WSW' },
  { code: 'E', zh: '东风', en: 'East', opp: 'W' },
  { code: 'ESE', zh: '东南偏东风', en: 'East-Southeast', opp: 'WNW' },
  { code: 'SE', zh: '东南风', en: 'Southeast', opp: 'NW' },
  { code: 'SSE', zh: '东南偏南风', en: 'South-Southeast', opp: 'NNW' },
  { code: 'S', zh: '南风', en: 'South', opp: 'N' },
  { code: 'SSW', zh: '西南偏南风', en: 'South-Southwest', opp: 'NNE' },
  { code: 'SW', zh: '西南风', en: 'Southwest', opp: 'NE' },
  { code: 'WSW', zh: '西南偏西风', en: 'West-Southwest', opp: 'ENE' },
  { code: 'W', zh: '西风', en: 'West', opp: 'E' },
  { code: 'WNW', zh: '西北偏西风', en: 'West-Northwest', opp: 'ESE' },
  { code: 'NW', zh: '西北风', en: 'Northwest', opp: 'SE' },
  { code: 'NNW', zh: '西北偏北风', en: 'North-Northwest', opp: 'SSE' }
];

export function getWindDirectionInfo(deg: number | null | undefined, en = false): WindDirectionInfo {
  if (deg === null || deg === undefined || !Number.isFinite(deg)) {
    return { code: '—', name: en ? 'Unknown' : '方向未知', degrees: null, oppositeCode: '—' };
  }
  const normalized = ((deg % 360) + 360) % 360;
  const index = Math.round(normalized / 22.5) % 16;
  const sector = SECTORS[index];
  return {
    code: sector.code,
    name: en ? sector.en : sector.zh,
    degrees: Math.round(normalized),
    oppositeCode: sector.opp
  };
}

export function getPrecipitationInfo(mm: number | null | undefined, hours = 1, en = false) {
  if (mm === null || mm === undefined || !Number.isFinite(mm)) {
    return { mm: null, label: en ? 'No data' : '暂无数据', desc: en ? 'No precipitation record' : '无降水统计' };
  }
  if (mm < 0 || !Number.isFinite(hours) || hours <= 0) {
    return {mm:null,label:en?'No data':'暂无数据',desc:en?'Invalid forecast interval':'预报时段无效'};
  }
  return {mm,label:en?'Forecast accumulation':'预报累计',
    desc:en?`${hours} h forecast; not a surface observation`:`${hours} h 时段累计，非现场表面观测`};
}

export function getCloudCoverageInfo(percent: number | null | undefined, en = false) {
  if (percent === null || percent === undefined || !Number.isFinite(percent)) {
    return { percent: null, label: en ? 'Unknown' : '云量未知', lighting: en ? 'Cloud forecast unavailable' : '暂无云量预报' };
  }
  const p = Math.min(100, Math.max(0, Math.round(percent)));
  if (p < 20) return { percent: p, label: en ? 'Clear sky' : '晴朗透亮', lighting: en ? 'Low cloud fraction forecast' : '预报云量较少' };
  if (p < 60) return { percent: p, label: en ? 'Partly cloudy' : '晴间多云', lighting: en ? 'Partial cloud fraction forecast' : '预报局部有云' };
  if (p < 85) return { percent: p, label: en ? 'Mostly cloudy' : '多云遮蔽', lighting: en ? 'High cloud fraction forecast' : '预报云量较多' };
  return { percent: p, label: en ? 'Overcast' : '浓云密布', lighting: en ? 'Overcast forecast' : '预报云层覆盖' };
}

export function getOperationAdvice(condition: string, windSpeed: number | null | undefined, precipitation: number | null | undefined, en = false, usable = true) {
  if (!usable || windSpeed == null || precipitation == null || !Number.isFinite(windSpeed) || windSpeed < 0
      || !Number.isFinite(precipitation) || precipitation < 0 || !['clear','cloud','rain','snow','sleet','fog'].includes(condition)) {
    return {status:'unknown',title:en?'Current forecast unavailable':'当前预报不可用',
      desc:en?'No operations assessment is available.':'不提供作业适宜度判断。'};
  }
  if (windSpeed >= 12) return {status:'caution',title:en?'Higher wind forecast':'预报风速较高',
    desc:en?'10 m forecast reference; confirm conditions on site.':'10 m 预报参考，请核查现场风况。'};
  if (['rain','snow','sleet'].includes(condition) || precipitation > 3) return {status:'warning',
    title:en?'Precipitation forecast':'降水预报提示',
    desc:en?'Precipitation is forecast for this interval; confirm conditions on site.':'当前时段预报有降水，请核查现场天气。'};
  if (condition === 'fog') return {status:'warning',title:en?'Fog forecast':'雾预报提示',
    desc:en?'Visibility requires on-site verification.':'现场能见度需要核查。'};
  return {status:'neutral',title:en?'Weather reference':'天气参考',
    desc:en?'Forecast only. Operations require on-site checks and applicable procedures.':'仅供预报参考，作业条件以现场核查与适用规程为准。'};
}

export function formatWeatherCoordinates(latitude:number,longitude:number) {
  if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||Math.abs(latitude)>90||Math.abs(longitude)>180)return '—';
  return `${Math.abs(latitude).toFixed(4)}°${latitude<0?'S':'N'}, ${Math.abs(longitude).toFixed(4)}°${longitude<0?'W':'E'}`;
}
