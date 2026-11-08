# 驾驶舱前景面板毛玻璃效果与透明度优化实施方案

## 1. 背景与目标

用户反馈要求：
> “将驾驶舱所有前景面板元素都处理成毛玻璃效果，透明度比现在左右侧面板的透明度再提高一点”
> “在显示设置里提供透明度设置选项，其余可以方案执行”

根据用户提供的两张标注截图（驾驶舱“场景总览”页与“设备”页）及最新确认要求：
1. **毛玻璃与高通透视觉升级**：驾驶舱（Project Cockpit）中的所有前景面板与浮动交互控件统一实现通透细腻的**毛玻璃效果（Frosted Glass / `backdrop-filter: blur(...)`）**，默认透明度相比原有 `0.92` 不透明度进一步调高（默认标准通透为约 65% 不透明度 / 35% 透光率），使背后的三维场景、地形、天空、设备模型及地球画面能够清晰柔和地透出；
2. **显示设置中新增透明度设置项**：在右上角“显示设置”（Display settings）弹窗的“显示”面板中提供面板透明度设置选项（包含 `超高通透 (35%)`、`高通透 (50%)`、`标准通透 (65% · 推荐)`、`微透 (85%)`、`实心 (100%)` 预设，且持久化保存到当前浏览器 `localStorage`），允许用户随心按需调节驾驶舱面板通透度。

---

## 2. 现状根因与修改范围

1. **左右侧面板（`.pc-panel`）不透明度过高（92%）**：
   - 在 [`projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) 中，深色模式 `--pc-panel: rgba(29, 48, 54, .92)`、浅色模式 `--pc-panel: rgba(246, 251, 247, .92)` 的 alpha 值高达 `0.92`，视觉上接近实心纯色面板，毛玻璃通透感很弱。
2. **顶部导航栏（`.pc-header`）与面包屑栏（`.pc-breadcrumb`）缺乏毛玻璃效果且底层视口被截断**：
   - `.pc-header` 虽使用了 `background: var(--pc-panel)`，但未设置 `backdrop-filter`；
   - `.pc-breadcrumb` 完全没有背景和 `backdrop-filter`，直接裸露在 `.pc-app` 的实心底色 `--pc-bg: #15272e` 上；
   - **底层布局截断**：`.pc-assets` 设置了 `inset: 82px 0 0`，`.pc-spatial` 设置了 `inset: 132px 0 0`。导致三维视口（`.pc-viewport`）与地球画布（`.pc-globe-view`）在顶部 `132px`（或 `82px`）处被硬截断，顶部栏和面包屑栏下方只有死板的 `#15272e` 纯色背景。
3. **底部模型控制坞与视口浮动控件遗漏毛玻璃或使用了实心背景**：
   - `.pc-model-dock .pc-model-view > div`（底部“实体 / 透视 / 爆炸示意”工具坞）与提示条未设置 `backdrop-filter`；
   - `.pc-viewport .ov-scene-viewport-tools`（视口顶部中间的缩放/复位工具栏）使用的是实心 `background: var(--surface)`；
   - `.pc-space-status`（左下状态条）、`.pc-demo-button`（底部“模拟 · 15 台运行”按钮）、`.ov-scene-imagery-attribution`（右下影像来源）等未设置毛玻璃效果。
4. **缺少透明度偏好调节功能**：
   - 原设置弹窗只包含“界面缩放”、“视觉主题”、“暂停可视化”，没有面板透明度的控制选项。

---

## 3. 具体修改设计与代码清单

### 3.1 增加面板透明度数据模型与持久化（[`apps/workbench/src/cockpitState.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitState.ts)）
- 定义 `CockpitPanelOpacity` 联合类型：
  ```ts
  export type CockpitPanelOpacity = 'ultra' | 'high' | 'medium' | 'low' | 'solid';
  export const COCKPIT_OPACITY_VALUES: Record<CockpitPanelOpacity, {darkAlpha: number; lightAlpha: number}> = {
    ultra: {darkAlpha: 0.35, lightAlpha: 0.45},
    high: {darkAlpha: 0.50, lightAlpha: 0.60},
    medium: {darkAlpha: 0.66, lightAlpha: 0.72}, // 默认推荐标准通透
    low: {darkAlpha: 0.85, lightAlpha: 0.88},
    solid: {darkAlpha: 0.98, lightAlpha: 0.98},
  };
  export function cockpitSavedOpacity(): CockpitPanelOpacity { ... }
  ```

### 3.2 在显示设置弹窗中增加透明度配置项（[`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx)）
- 在 `ProjectCockpit` 中增加 `panelOpacity` 状态（初始化优先读取 `cockpitSavedOpacity()`，默认为 `'medium'`）；
- 将根据当前主题（`dark`/`light`）计算出的 `--pc-panel-alpha` 注入到 `.pc-root` 的 style 中；
- 在 `settingsTab === 'display'` 弹窗中增加透明度下拉选择控件：
  ```tsx
  <label>{t('面板透明度','Panel opacity')}
    <select aria-label={t('面板透明度','Panel opacity')} value={panelOpacity} onChange={e=>{
      const val=e.target.value as CockpitPanelOpacity;
      setPanelOpacity(val);
      try{localStorage.setItem('ontovis.cockpit.panel_opacity',val);}catch{}
    }}>
      <option value="ultra">{t('超高通透 (35%)','Ultra high transparency (35%)')}</option>
      <option value="high">{t('高通透 (50%)','High transparency (50%)')}</option>
      <option value="medium">{t('标准通透 (65% · 推荐)','Standard (65% · recommended)')}</option>
      <option value="low">{t('微透 (85%)','Low transparency (85%)')}</option>
      <option value="solid">{t('实心 (100%)','Solid (100%)')}</option>
    </select>
  </label>
  ```
- 在“恢复自动缩放”操作区支持一键重置透明度或说明。

### 3.3 样式重构与毛玻璃全局铺设（[`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css)）
- **CSS 变量与毛玻璃滤镜**：
  - 深色模式：`--pc-panel-alpha: .66;`、`--pc-panel: rgba(22, 40, 46, var(--pc-panel-alpha));`、`--pc-panel-strong: rgba(28, 50, 58, min(.96, calc(var(--pc-panel-alpha) + .12)));`、`--pc-blur: blur(20px) saturate(140%);`；
  - 浅色模式：`--pc-panel-alpha: .72;`、`--pc-panel: rgba(244, 250, 246, var(--pc-panel-alpha));`、`--pc-panel-strong: rgba(255, 255, 255, min(.98, calc(var(--pc-panel-alpha) + .15)));`；
- **视口铺满全屏与全域毛玻璃**：
  - 将 `.pc-assets` 和 `.pc-spatial` 调整为 `inset: 0`，使底层三维场景与地球画面延伸到屏幕最顶端；
  - 保持各前景面板及工具栏的绝对坐标定位与响应式断点位置不变；
  - 为 `.pc-header`、`.pc-breadcrumb`、`.pc-panel`、`.pc-model-dock`、`.ov-scene-viewport-tools`、`.pc-space-status`、`.pc-demo-button`、`.ov-scene-imagery-attribution`、`.pc-device-panel-tabs` 等全量应用 `background: var(--pc-panel); backdrop-filter: var(--pc-blur); -webkit-backdrop-filter: var(--pc-blur);`。

### 3.4 关联样式更新（[`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css) 与 [`apps/workbench/src/cockpitAnalysis.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitAnalysis.css)）
- 同步地球页和空间导航中的前景按钮与浮层（`.pc-globe-home`、`.pc-globe-pause`、`.pc-globe-credit`、`.pc-globe-choice`、`.pc-globe-pin-label`、`.pc-space-loading` 等）的毛玻璃与透明度支持；
- 同步分析画布相关前景浮动面板的通透度与毛玻璃滤镜。

---

## 4. 验证与部署流程

1. **本地单元测试与构建验证**：
   - 运行 `npm --prefix apps/workbench run check` 确保 774+ 项测试、TypeScript 静态检查和 Vite 生产打包零报错；
2. **Git 提交与测试环境发布**：
   - 提交更改并推送至远端分支；
   - 部署至测试服务器 `192.168.2.153`（`https://vis.ontobase.ai`）；
3. **完成任务归档**：
   - 生成 `walkthrough.md` 备份至 `todo/驾驶舱前景面板毛玻璃效果与透明度优化_20261108/` 目录。
