# 修复地球场景图钉双层背景与多语言文本修订 实施方案

## 1. 背景与目标

### 1.1 问题一：地球场景图钉出现双层背景与方形外框
- **现象**：驾驶舱「项目资产」页面的地球视图中，场景点位图钉（Pin）外层被一个半透明圆角矩形背景框（选中态为橙金色边框）包裹，内部叠合水滴形气泡图钉，呈现双层重叠畸变。
- **根因**：[`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css) 中的 `.pc-globe-pin span`、`.pc-globe-pin:hover span` 和 `.pc-globe-pin.selected span` 规则使用了通配 `span` 后代选择器，导致同为 `span` 的图标容器 `<span className="pc-globe-pin-icon">` 错误继承了文本标签的背景色、边框、圆角（`border-radius: 7px`）、内边距（`padding: 4px 9px`）与发光阴影。

### 1.2 问题二：多语言文本在工业应用场景下的规范性修订
- **单复数语法与拼接缺陷**：
  - 左侧资产组合卡片中的风机数量、设备数量、模型表示数量直接拼接单数/复数单词，当数量为 1 时出现 `1 turbines`、`1 devices`、`1 representations`，需根据数量做单复数适配（`1 turbine` / `N turbines`、`1 device` / `N devices`、`1 representation` / `N representations`）。
- **去“演练”字样与工业术语优化**（按用户指示，中英文均彻底去掉“演练”字样）：
  - 右侧报警面板选择框：原中文“演练设备”修订为**“目标设备”**（英文由 `Exercise unit` 修订为 **`Target equipment`**）；
  - 无障碍属性：原中文“报警演练设备”修订为**“报警目标设备”**（英文由 `Alarm exercise unit` 修订为 **`Alarm target equipment`**）；
  - 右侧报警刷新操作：无障碍标签由 `Reload home alarms` 优化为规范的 **`Refresh alarms`**。
- **操作动词与状态优化**：
  - 左侧卡片异常状态由 `Retry required` 优化为 **`Failed · Retry`**；
  - 场景/设备选择动作动词由口语化的 `Choose` 优化为规范的 **`Select scene`** / **`Select equipment`**；
  - 地球参考点选择浮层关闭按钮无障碍属性由 `Close reference points` 优化为 **`Close panel`**，避免误解为关闭/禁用功能。

---

## 2. 详细修改方案

### 2.1 场景图钉样式与结构解耦
1. **[`apps/workbench/src/CockpitGlobe.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitGlobe.tsx)**：
   - 为场景名称标签 `span` 增加专属类名 `pc-globe-pin-label`；
   - 将参考点选择浮层关闭按钮的 `aria-label` 由 `en ? 'Close reference points' : '关闭参考点'` 修正为 `en ? 'Close panel' : '关闭'`。
2. **[`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css)**：
   - 将 `.pc-globe-pin span` 收敛为 `.pc-globe-pin .pc-globe-pin-label`；
   - 将 `.pc-globe-pin:hover span` 收敛为 `.pc-globe-pin:hover .pc-globe-pin-label`；
   - 将 `.pc-globe-pin.selected span` 收敛为 `.pc-globe-pin.selected .pc-globe-pin-label`；
   - 确保 `.pc-globe-pin-icon` 无额外背景、边框、padding 和阴影。

### 2.2 多语言文本修订（含彻底去除“演练”字样）
1. **[`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx)**：
   - 资产组合卡片中的风机/设备/表示数量格式化增加单复数判断；
   - 状态文案 `t('读取待重试','Retry required')` 调整为 `t('读取待重试','Failed · Retry')`；
   - 引导动词 `t('选择场景','Choose a scene')` 调整为 `t('选择场景','Select scene')`；
   - 引导动词 `t('请选择设备','Choose equipment')` 调整为 `t('请选择设备','Select equipment')`。
2. **[`apps/workbench/src/CockpitAlarmSummary.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitAlarmSummary.tsx)**：
   - 刷新按钮属性：`aria-label={en ? 'Refresh alarms' : '刷新首页报警'}`；
   - 去掉“演练”：`<span>{en ? 'Target equipment' : '目标设备'}</span>`；
   - 去掉“演练”：`<select aria-label={en ? 'Alarm target equipment' : '报警目标设备'} ...>`。

---

## 3. 涉及文件清单

| 文件路径 | 变更目的 |
|---|---|
| [`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css) | 将图钉标签样式收敛到 `.pc-globe-pin-label`，消除图钉外层方形背景边框 |
| [`apps/workbench/src/CockpitGlobe.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitGlobe.tsx) | 为图钉文本添加 `pc-globe-pin-label`；修正关闭按钮为 `Close panel` |
| [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 优化卡片单复数、卡片失败状态文本及选择引导动词 |
| [`apps/workbench/src/CockpitAlarmSummary.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitAlarmSummary.tsx) | 去掉“演练”字样，改为目标设备/Target equipment，优化刷新按钮无障碍标签 |

---

## 4. 验证计划

1. **自动化测试**：
   - 运行空间相关单元测试：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/cockpit-space.test.mjs
     ```
   - 运行驾驶舱与空间相关前端测试：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/project-cockpit.test.mjs
     ```
2. **类型检查与构建**：
   - 执行 TypeScript 静态类型检查：
     ```bash
     node apps/workbench/node_modules/typescript/bin/tsc --noEmit -p apps/workbench
     ```
3. **视觉与交互核验**：
   - 确认图钉呈现纯正单层水滴形，无多余方形背景；
   - 确认中英文模式下左侧列表、右侧报警面板和中间浮层的文本显示准确且地道，无“演练”字样。
