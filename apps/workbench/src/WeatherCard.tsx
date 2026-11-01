import {
  CloudSun, CloudRain, CloudSnow, CloudFog, Cloud, Sun,
  Compass, Wind, Droplets, Gauge, AlertTriangle, CheckCircle2,
  Clock, MapPin, ShieldAlert, Activity
} from 'lucide-react';
import { weatherMessage, weatherUsable, type WeatherView } from './weather';
import {
  getBeaufortInfo,
  getWindDirectionInfo,
  getPrecipitationInfo,
  getCloudCoverageInfo,
  getOperationAdvice,
  type BeaufortInfo,
  type WindDirectionInfo
} from './weatherCardLogic';

export {
  getBeaufortInfo,
  getWindDirectionInfo,
  getPrecipitationInfo,
  getCloudCoverageInfo,
  getOperationAdvice,
  type BeaufortInfo,
  type WindDirectionInfo
};

export function WindCompass({ degrees, en = false }: { degrees: number | null; en?: boolean }) {
  const hasValue = degrees !== null && Number.isFinite(degrees);
  const rot = hasValue ? ((degrees! % 360) + 360) % 360 : 0;
  return (
    <div className="wx-compass-container" aria-label={en ? `Wind compass: ${hasValue ? `${rot}°` : 'unknown'}` : `风向罗盘：${hasValue ? `${rot}°` : '未知'}`}>
      <svg className="wx-compass-svg" viewBox="0 0 120 120" width="104" height="104">
        {/* 背景环刻度 */}
        <circle cx="60" cy="60" r="54" className="wx-compass-dial-ring" />
        <circle cx="60" cy="60" r="44" className="wx-compass-dial-inner" />
        {/* 16 方位刻度线 */}
        {Array.from({ length: 16 }).map((_, i) => {
          const a = (i * 22.5 * Math.PI) / 180;
          const isMajor = i % 4 === 0;
          const r1 = isMajor ? 44 : 48;
          const r2 = 54;
          return (
            <line
              key={i}
              x1={60 + r1 * Math.sin(a)}
              y1={60 - r1 * Math.cos(a)}
              x2={60 + r2 * Math.sin(a)}
              y2={60 - r2 * Math.cos(a)}
              className={isMajor ? 'wx-compass-tick-major' : 'wx-compass-tick-minor'}
            />
          );
        })}
        {/* 四正方位文字 */}
        <text x="60" y="20" className="wx-compass-cardinal" textAnchor="middle">N</text>
        <text x="104" y="64" className="wx-compass-cardinal" textAnchor="middle">E</text>
        <text x="60" y="108" className="wx-compass-cardinal" textAnchor="middle">S</text>
        <text x="16" y="64" className="wx-compass-cardinal" textAnchor="middle">W</text>

        {/* 旋转指针组 */}
        {hasValue ? (
          <g transform={`rotate(${rot} 60 60)`} className="wx-compass-needle-group">
            {/* 来风箭头：从外向中心，或指向来风方位 */}
            <polygon points="60,18 64,48 56,48" className="wx-compass-needle-head" />
            <polygon points="60,82 63,52 57,52" className="wx-compass-needle-tail" />
            <circle cx="60" cy="60" r="10" className="wx-compass-pivot" />
            <circle cx="60" cy="60" r="4" className="wx-compass-pivot-center" />
          </g>
        ) : (
          <g>
            <circle cx="60" cy="60" r="8" className="wx-compass-pivot" />
            <text x="60" y="64" className="wx-compass-unknown-text" textAnchor="middle">—</text>
          </g>
        )}
      </svg>
    </div>
  );
}

export function WeatherCard({
  value,
  en = false,
  loading = false,
  error,
  now = Date.now()
}: {
  value: WeatherView | null;
  en?: boolean;
  loading?: boolean;
  error?: unknown;
  now?: number;
}) {
  const t = (zh: string, eng: string) => (en ? eng : zh);
  const f = value?.forecast;
  const usable = weatherUsable(value, now);
  const kind = f?.condition;

  const names = {
    clear: t('晴', 'Clear'),
    cloud: t('多云', 'Cloudy'),
    rain: t('雨', 'Rain'),
    snow: t('雪', 'Snow'),
    sleet: t('雨夹雪', 'Sleet'),
    fog: t('雾', 'Fog'),
    unknown: t('天气类型未知', 'Unknown weather')
  };

  const Icon =
    kind === 'rain'
      ? CloudRain
      : kind === 'snow' || kind === 'sleet'
      ? CloudSnow
      : kind === 'fog'
      ? CloudFog
      : kind === 'clear'
      ? Sun
      : kind === 'cloud'
      ? Cloud
      : CloudSun;

  const date = (s: string) =>
    new Date(s).toLocaleString(en ? 'en-GB' : 'zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });

  const n = (v: number | null | undefined) => (v === null || v === undefined ? '—' : String(v));

  const states = {
    unconfigured: t('尚未配置天气', 'Weather not configured'),
    disabled: t('项目天气已停用', 'Project weather disabled'),
    unavailable: t('暂无可用预报', 'Forecast unavailable'),
    stale: t('预报暂不可用', 'Forecast not current'),
    available: t('微气象监测看板', 'Microclimate Dashboard')
  };

  // 辅助参数计算
  const beaufort = getBeaufortInfo(f?.windSpeedMs, en);
  const direction = getWindDirectionInfo(f?.windFromDeg, en);
  const precip = getPrecipitationInfo(f?.precipitationMm, f?.intervalHours ?? 1, en);
  const cloud = getCloudCoverageInfo(f?.cloudPercent, en);
  const advice = getOperationAdvice(f?.condition || '', f?.windSpeedMs, f?.precipitationMm, en);

  // 轮毂高度(约100m)风速推算：基于风切变指数 alpha=0.14
  const hubHeightSpeed =
    f?.windSpeedMs !== null && f?.windSpeedMs !== undefined
      ? (f.windSpeedMs * Math.pow(100 / 10, 0.14)).toFixed(1)
      : null;

  return (
    <section className="wx-weather-card wx-dashboard" aria-label={t('微气象监测看板', 'Microclimate Dashboard')}>
      {/* 头部标题与状态栏 */}
      <header className="wx-dashboard-header">
        <div className="wx-title-group">
          <Icon size={20} className="wx-header-icon" />
          <h3>{loading ? t('正在读取天气预报…', 'Loading forecast…') : states[value?.status || 'unavailable']}</h3>
          <span className="wx-label wx-badge-glow">{t('数值模式预报', 'Model Forecast')}</span>
        </div>
        {value?.point && (
          <div className="wx-location-badge" title={t('当前场景地理定位参考点', 'Current scene geographic anchor')}>
            <MapPin size={13} />
            <span>
              {value.point.latitude.toFixed(4)}°N, {value.point.longitude.toFixed(4)}°E
            </span>
          </div>
        )}
      </header>

      {/* 错误提示或有效性提示 */}
      {!!error && (
        <div className="wx-alert-box error" role="alert">
          <AlertTriangle size={15} />
          <span>{weatherMessage(error, en)}</span>
        </div>
      )}
      {value?.error && (
        <div className="wx-alert-box warning" role="status">
          <AlertTriangle size={15} />
          <span>{weatherMessage(value.error, en)}</span>
        </div>
      )}
      {value?.status === 'available' && !usable && (
        <div className="wx-alert-box stale" role="status">
          <Clock size={15} />
          <span>{t('当前预报时段已结束，三维环境特效已切换为保底光照。', 'Forecast period ended; 3D effects fallback active.')}</span>
        </div>
      )}

      {/* 核心气象预报展开 */}
      {f && (
        <>
          {/* 主看板（Hero Banner） */}
          <div className="wx-hero-banner">
            <div className="wx-hero-left">
              <div className="wx-hero-icon-wrap" data-condition={f.condition}>
                <Icon size={46} />
              </div>
              <div className="wx-hero-temp">
                <strong>
                  {n(f.temperatureC)}
                  <small>°C</small>
                </strong>
                <div className="wx-hero-tags">
                  <span className="wx-condition-pill">{names[f.condition]}</span>
                  <span className="wx-sub-tag">{cloud.lighting}</span>
                </div>
              </div>
            </div>

            <div className="wx-hero-right">
              <div className="wx-valid-pill">
                <span className={`wx-status-dot ${usable ? 'active' : 'inactive'}`} />
                <span>{usable ? t('预报实时生效中', 'Forecast Active') : t('时效已过期', 'Period Expired')}</span>
              </div>
              <div className="wx-timing-meta">
                <p>
                  <strong>{t('有效时段', 'Valid')}:</strong> {date(f.validFrom)} – {date(f.validTo)}
                </p>
                <p>
                  <span>{t('发布时间', 'Issued')}: {date(f.updatedAt)}</span>
                  {value.fetchedAt && <span> · {t('同步', 'Fetched')}: {date(value.fetchedAt)}</span>}
                </p>
              </div>
            </div>
          </div>

          {/* 两列布局：左侧风况专属Deck，右侧环境指标Deck */}
          <div className="wx-body-grid">
            {/* 左侧：风电核心风况 Deck */}
            <div className="wx-deck wx-wind-deck">
              <div className="wx-deck-head">
                <Wind size={16} />
                <h4>{t('风况与机组运行工况', 'Wind Dynamics & Turbine States')}</h4>
                <small>{t('10m 气象基准', '10m ref')}</small>
              </div>

              <div className="wx-wind-visual">
                <WindCompass degrees={f.windFromDeg} en={en} />
                <div className="wx-wind-stats">
                  <div className="wx-wind-stat-row">
                    <span className="wx-stat-label">{t('来风风向', 'Wind from')}</span>
                    <strong className="wx-stat-value">
                      {direction.name} ({direction.code}) · {direction.degrees !== null ? `${direction.degrees}°` : '—'}
                    </strong>
                  </div>
                  <div className="wx-wind-stat-row">
                    <span className="wx-stat-label">{t('10m 风速', '10m speed')}</span>
                    <strong className="wx-stat-value highlight">
                      {n(f.windSpeedMs)} <small>m/s</small>
                      <span className="wx-scale-badge">{beaufort.name}</span>
                    </strong>
                  </div>
                  <div className="wx-stage-badge" data-stage={beaufort.stage}>
                    <Activity size={13} />
                    <span>{beaufort.stageLabel}</span>
                  </div>
                  <p className="wx-deck-note">{beaufort.description}</p>
                </div>
              </div>

              {/* 风速能量进度条 */}
              <div className="wx-speed-meter">
                <div className="wx-meter-track">
                  <div
                    className="wx-meter-fill"
                    data-stage={beaufort.stage}
                    style={{ width: `${Math.min(100, ((f.windSpeedMs ?? 0) / 30) * 100)}%` }}
                  />
                  {/* 标记关键风速点 */}
                  <span className="wx-marker" style={{ left: '10%' }} title={t('切入风速约 3m/s', 'Cut-in ~3m/s')} />
                  <span className="wx-marker" style={{ left: '38.3%' }} title={t('额定风速约 11.5m/s', 'Rated ~11.5m/s')} />
                  <span className="wx-marker" style={{ left: '83.3%' }} title={t('切出风速约 25m/s', 'Cut-out ~25m/s')} />
                </div>
                <div className="wx-meter-labels">
                  <span>0</span>
                  <span>{t('切入 3', 'Cut-in 3')}</span>
                  <span>{t('额定 11.5', 'Rated 11.5')}</span>
                  <span>{t('切出 25', 'Cut-out 25')}</span>
                  <span>30+ m/s</span>
                </div>
              </div>
            </div>

            {/* 右侧：环境气象多维指标 Deck */}
            <div className="wx-deck wx-metrics-deck">
              <div className="wx-deck-head">
                <Gauge size={16} />
                <h4>{t('环境气象多维指标', 'Atmospheric Metrics')}</h4>
                <small>{t('场区微气象', 'Site weather')}</small>
              </div>

              <div className="wx-metrics-list">
                {/* 降水指标 */}
                <div className="wx-metric-row-card">
                  <div className="wx-metric-row-head">
                    <div className="wx-metric-icon-title">
                      <Droplets size={15} className="wx-metric-icon text-cyan" />
                      <span>{f.intervalHours}h {t('降水量', 'Precipitation')}</span>
                    </div>
                    <span className="wx-metric-pill">{precip.label}</span>
                  </div>
                  <div className="wx-metric-row-body">
                    <div className="wx-metric-number">
                      <strong>{n(f.precipitationMm)}</strong>
                      <small>mm</small>
                    </div>
                    <span className="wx-metric-sub">{precip.desc}</span>
                  </div>
                </div>

                {/* 云量覆盖率 */}
                <div className="wx-metric-row-card">
                  <div className="wx-metric-row-head">
                    <div className="wx-metric-icon-title">
                      <Cloud size={15} className="wx-metric-icon text-indigo" />
                      <span>{t('云量覆盖率', 'Cloud Cover')}</span>
                    </div>
                    <span className="wx-metric-pill">{cloud.label}</span>
                  </div>
                  <div className="wx-metric-row-body">
                    <div className="wx-metric-number">
                      <strong>{f.cloudPercent !== null && f.cloudPercent !== undefined ? f.cloudPercent : '—'}</strong>
                      <small>%</small>
                    </div>
                    <span className="wx-metric-sub">{cloud.lighting}</span>
                  </div>
                </div>

                {/* 高空风切变参考 */}
                <div className="wx-metric-row-card">
                  <div className="wx-metric-row-head">
                    <div className="wx-metric-icon-title">
                      <Compass size={15} className="wx-metric-icon text-teal" />
                      <span>{t('轮毂高度风切变', 'Hub Wind Shear')}</span>
                    </div>
                    <span className="wx-metric-pill">{t('~100m 轮毂高度', '~100m Hub')}</span>
                  </div>
                  <div className="wx-metric-row-body">
                    <div className="wx-metric-number">
                      <strong>{hubHeightSpeed ?? '—'}</strong>
                      <small>m/s</small>
                    </div>
                    <span className="wx-metric-sub">{t('基于切变指数α=0.14推算', 'Est. by wind shear α=0.14')}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* 横跨两栏：现场运维作业适宜度通栏横幅 Banner */}
            <div className={`wx-advice-banner ${advice.status}`}>
              <div className="wx-advice-badge">
                {advice.status === 'good' ? (
                  <CheckCircle2 size={18} className="wx-advice-icon text-green" />
                ) : advice.status === 'danger' ? (
                  <ShieldAlert size={18} className="wx-advice-icon text-red" />
                ) : (
                  <AlertTriangle size={18} className="wx-advice-icon text-amber" />
                )}
                <div className="wx-advice-badge-text">
                  <span className="wx-advice-tag">{t('现场作业适宜度', 'Operations Window')}</span>
                  <strong className="wx-advice-title">{advice.title}</strong>
                </div>
              </div>
              <div className="wx-advice-divider" />
              <div className="wx-advice-content">
                <p>{advice.desc}</p>
              </div>
            </div>
          </div>
        </>
      )}

      {/* 未配置或停用状态时的专属引导 */}
      {value?.status === 'unconfigured' && (
        <div className="wx-empty-state">
          <CloudSun size={38} className="wx-empty-icon" />
          <h4>{t('尚未配置气象接口', 'Weather API Not Configured')}</h4>
          <p>
            {t(
              '在工作台“数据与告警 → 天气接口”中启用天气接口，并确保当前场景已完成地理定位锚点绑定。',
              'Enable Weather API in "Data & alarms → Weather API" and ensure this scene has a geographic anchor.'
            )}
          </p>
        </div>
      )}

      {value?.status === 'disabled' && (
        <div className="wx-empty-state">
          <CloudSun size={38} className="wx-empty-icon" />
          <h4>{t('项目天气功能已停用', 'Project Weather Disabled')}</h4>
          <p>{t('项目管理员已停用天气接口。如需启用请进入设置开启。', 'Project administrator has disabled weather integration.')}</p>
        </div>
      )}

      {/* 底部数据凭证与免责说明 */}
      <footer className="wx-dashboard-footer">
        <div className="wx-source-info">
          <a href="https://api.met.no/" target="_blank" rel="noreferrer">
            MET Norway · Locationforecast 2.0
          </a>
          <span>·</span>
          <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">
            CC BY 4.0
          </a>
        </div>
        <p className="wx-disclaimer">
          {t(
            '全球数值气象模式预报按时段归一化驱动；不替代风电场现场测风塔或机舱激光雷达实测遥测数据。',
            'Normalized global numerical forecast; does not substitute on-site met mast or turbine lidar telemetry.'
          )}
        </p>
      </footer>
    </section>
  );
}
