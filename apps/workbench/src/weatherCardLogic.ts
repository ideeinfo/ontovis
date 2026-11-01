export interface BeaufortInfo {
  scale: number | null;
  name: string;
  speedMs: number | null;
  stage: 'idle' | 'generating' | 'rated' | 'cutout' | 'unknown';
  stageLabel: string;
  description: string;
}

export function getBeaufortInfo(speed: number | null | undefined, en = false): BeaufortInfo {
  if (speed === null || speed === undefined || !Number.isFinite(speed)) {
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

  let stage: BeaufortInfo['stage'] = 'generating';
  let stageLabel = '';
  let description = '';

  if (s < 3.0) {
    stage = 'idle';
    stageLabel = en ? 'Below cut-in · Standby' : '低于切入风速 · 待机';
    description = en ? 'Below turbine cut-in (~3 m/s). Generators idle.' : '低于典型切入风速(~3 m/s)，风机微风空转待机。';
  } else if (s < 11.5) {
    stage = 'generating';
    stageLabel = en ? 'Cut-in reach · Ramp-up' : '达切入风速 · 发电爬坡';
    description = en ? 'Within power ramp-up curve. Normal generation.' : '处于典型功率爬升段，发电机组稳定并网发电。';
  } else if (s < 25.0) {
    stage = 'rated';
    stageLabel = en ? 'Rated zone · Full power' : '额定风速区 · 满发恒功';
    description = en ? 'Optimal rated output. Pitch control active.' : '进入额定风速满发段，智能变桨保持额定功率。';
  } else {
    stage = 'cutout';
    stageLabel = en ? 'Cut-out threshold · Defense' : '切出保护区 · 防御顺桨';
    description = en ? 'Exceeds cut-out (~25 m/s). Pitch to feather for safety.' : '达到或超出风机切出风速(~25 m/s)，机组执行顺桨停机保护。';
  }

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
  const v = Math.max(0, mm);
  if (v === 0) return { mm: v, label: en ? 'No rain' : '无雨干爽', desc: en ? 'Dry condition' : '无降水，环境干燥' };
  if (v <= 2.5) return { mm: v, label: en ? 'Light rain' : '小雨淅沥', desc: en ? 'Slight surface dampness' : '轻微降雨，机舱表面微湿' };
  if (v <= 8.0) return { mm: v, label: en ? 'Moderate rain' : '中雨', desc: en ? 'Noticeable rain showers' : '持续降雨，注意防滑与排水' };
  if (v <= 15.0) return { mm: v, label: en ? 'Heavy rain' : '大雨', desc: en ? 'Heavy rain showers' : '强降水，高空绝缘与接地防护' };
  return { mm: v, label: en ? 'Torrential rain' : '暴雨预警', desc: en ? 'Severe precipitation' : '极端暴雨，关注场区防汛' };
}

export function getCloudCoverageInfo(percent: number | null | undefined, en = false) {
  if (percent === null || percent === undefined || !Number.isFinite(percent)) {
    return { percent: null, label: en ? 'Unknown' : '云量未知', lighting: en ? 'Standard ambient' : '环境采光正常' };
  }
  const p = Math.min(100, Math.max(0, Math.round(percent)));
  if (p < 20) return { percent: p, label: en ? 'Clear sky' : '晴朗透亮', lighting: en ? 'Direct sunlight' : '直射光照充足，阴影清晰' };
  if (p < 60) return { percent: p, label: en ? 'Partly cloudy' : '晴间多云', lighting: en ? 'Intermittent sunlight' : '日照云影交错，局部漫射' };
  if (p < 85) return { percent: p, label: en ? 'Mostly cloudy' : '多云遮蔽', lighting: en ? 'Soft diffused skylight' : '柔和漫射天光，阴影浅淡' };
  return { percent: p, label: en ? 'Overcast' : '浓云密布', lighting: en ? 'Soft sky scattering' : '天空高散射漫射光，立体补光' };
}

export function getOperationAdvice(condition: string, windSpeed: number | null | undefined, precipitation: number | null | undefined, en = false) {
  const s = windSpeed ?? 0;
  const p = precipitation ?? 0;
  if (s >= 18) {
    return {
      status: 'danger',
      title: en ? 'High wind warning' : '大风高危预警',
      desc: en ? 'Wind exceeds 18 m/s. Prohibit climbing and nacelle roof works.' : '风速超过 18 m/s，严禁登塔、机舱顶部及叶片高空作业。'
    };
  }
  if (['rain', 'snow', 'sleet'].includes(condition) || p > 3) {
    return {
      status: 'warning',
      title: en ? 'Slippery rain/snow' : '阴雨湿滑警告',
      desc: en ? 'Rainy/snowy condition. Suspend external blade rope access.' : '雨雪天气导致风机表面湿滑，暂缓高空吊篮与叶片绳索巡检。'
    };
  }
  if (condition === 'fog') {
    return {
      status: 'warning',
      title: en ? 'Low visibility fog' : '浓雾能见度受限',
      desc: en ? 'Foggy condition. Not recommended for drone optical inspections.' : '大雾导致能见度受限，不建议进行无人机叶片外观航拍。'
    };
  }
  if (s >= 12) {
    return {
      status: 'caution',
      title: en ? 'Strong breeze caution' : '强风巡检提示',
      desc: en ? 'Wind 12~18 m/s. Drone inspection must counter wind gusts.' : '风速达 6 级强风，无人机巡检需注意阵风扰动及电池能耗。'
    };
  }
  return {
    status: 'good',
    title: en ? 'Favorable inspection window' : '气象窗口良好',
    desc: en ? 'Conditions ideal for routine patrols, drone inspections, and maintenance.' : '风向风速稳定，适宜开展无人机全自动航线巡检与例行维护。'
  };
}
