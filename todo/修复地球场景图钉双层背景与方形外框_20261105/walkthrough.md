# 修复地球场景图钉双层背景、左侧截断底色与多语言文本修订 验收报告 (Walkthrough)

## 1. 任务概述

针对用户提出的要求已完成落地实施与全量验证：
1. **左侧深色背景条裁切缝修复**：修复驾驶舱「项目资产」页全屏下左侧约 15% 宽度有一条纵向通顶深暗底色、导致欧亚大陆贴图被生生竖直截断的问题；
2. **场景图钉双层背景与方形外框修复**：消除了地球视图上水滴形图钉外部因 CSS 污染而产生的一层方形半透明背景框；
3. **多语言文本规范化修订**：
   - 全面核验左右面板与地球视图多语言，修正单复数缺陷与状态用语；
   - **严格按照要求，在中英文中彻底去除“演练”字样**（“演练设备”改为“目标设备”，“Exercise unit”改为“Target equipment”）。

---

## 2. 具体修改内容与文件清单

### 2.1 修复地球视口左侧深色背景条裁切（消除 15% 断层）
- **[`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css)**：
  - **根因分析**：原样式 `.pc-globe-render { inset: -4% -12% -4% 15%; }` 中设置了 `left: 15%`，导致 Three.js `<canvas>` 容器从屏幕左侧 15% 处才开始渲染，0%~15% 的左侧区域完全缺失 Canvas，露出了父容器 `.pc-globe-view` 的径向渐变背景底色，在 15% 处形成了一条垂直的硬裁切线，将地球的中国西部和欧亚大陆直接切断；
  - **修复措施**：修改为 `.pc-globe-render { inset: -4% -18% -4% -6%; }`。
    - 将 `left` 从 `15%` 调整为 `-6%`，Canvas 完整覆盖屏幕左侧边缘并提供 6% 的溢出缓冲区，彻底消除断层与硬切色块；
    - 将 `right` 调整为 `-18%`，总渲染宽度扩展至 `124%`，球心位置自然处于视口 `56%`（完美居中于左侧 372px 资产面板与右侧 260px 报警面板之间的空隙）；
    - 所有图钉经纬度投影坐标（基于 `element.offsetLeft` 动态计算）保持 100% 精确锚定。

### 2.2 样式与组件解耦（消除双层方形外框）
- **[`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css)**：
  - 将 `.pc-globe-pin span`、`.pc-globe-pin:hover span` 和 `.pc-globe-pin.selected span` 规则精准收敛为 `.pc-globe-pin .pc-globe-pin-label`；
  - 对图标定位容器 `.pc-globe-pin-icon` 显式重置 `background: transparent; border: none; padding: 0; box-shadow: none;`，彻底杜绝背景重叠。
- **[`apps/workbench/src/CockpitGlobe.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitGlobe.tsx)**：
  - 为场景名称标签 `span` 添加 `pc-globe-pin-label` 专属类名；
  - 将参考点选择浮层关闭按钮的无障碍标签从 `Close reference points` 修正为 `Close panel`，消除“关闭功能”的误导性歧义。

### 2.3 多语言规范化与去“演练”修订
- **[`apps/workbench/src/CockpitAlarmSummary.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitAlarmSummary.tsx)**：
  - 去除“演练”字样：原“演练设备 / Exercise unit”修正为**“目标设备 / Target equipment”**；
  - 无障碍标签同步去“演练”：原“报警演练设备 / Alarm exercise unit”修正为**“报警目标设备 / Alarm target equipment”**；
  - 刷新操作优化：原 `Reload home alarms` 优化为前端局部刷新规范用语 **`Refresh alarms`**。
- **[`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx)**：
  - 资产组合卡片中的数量增加严格单复数判断（`1 turbine` / `N turbines`、`1 device` / `N devices`、`1 representation` / `N representations`）；
  - 卡片异常状态由 `Retry required` 优化为更加贴合工控监控的 **`Failed · Retry`**；
  - 引导动作动词由口语化的 `Choose` 统一规范为工业管理标准动词 **`Select scene`** 与 **`Select equipment`**。

---

## 3. 修订前后对照汇总表

| 界面区域 | 界面元素 | 修订前表现 | 修订后表现 | 修订说明 |
|---|---|---|---|---|
| **地球全景渲染区** | 左侧背景裁切 | 左侧 15% 露底色，大陆被硬切断 | **Canvas 完整铺满左侧，平滑过渡** | 将 `left: 15%` 修复为 `left: -6%`，消除截断硬缝与露出底色 |
| **右侧报警面板** | 下拉框标签 | 演练设备 / Exercise unit | **目标设备 / Target equipment** | **去除“演练”字样**，消除健身器械歧义 |
| **右侧报警面板** | 下拉框 aria-label | 报警演练设备 / Alarm exercise unit | **报警目标设备 / Alarm target equipment** | **去除“演练”字样**，准确表达报警目标风机 |
| **右侧报警面板** | 刷新按钮 aria-label | 刷新首页报警 / Reload home alarms | **刷新首页报警 / Refresh alarms** | 局部数据刷新规范用词，避免混淆为整页重载 |
| **中间地球视图** | 浮层关闭按钮 | 关闭参考点 / Close reference points | **关闭 / Close panel** | 避免屏幕朗读器误解为“禁用参考点” |
| **中间地球视图** | 图钉图标外壳 | 双层方形框 | **纯正水滴形（无多余背景）** | 消除通配 span 样式污染，图钉干净单层 |
| **左侧资产组合** | 场景卡片单数风机 | 1 台风机 / 1 turbines | **1 台风机 / 1 turbine** | 修复英文单复数语法缺陷 |
| **左侧资产组合** | 场景卡片单数设备 | 1 台设备 / 1 devices | **1 台设备 / 1 device** | 修复英文单复数语法缺陷 |
| **左侧资产组合** | 场景卡片单数表示 | 1 个表示 / 1 representations | **1 个表示 / 1 representation** | 修复英文单复数语法缺陷 |
| **左侧资产组合** | 卡片读取失败状态 | 读取待重试 / Retry required | **读取待重试 / Failed · Retry** | 贴合工控加载失败的状态提示习惯 |
| **场景/设备选择** | 场景选择引导 | 选择场景 / Choose a scene | **选择场景 / Select scene** | 工业软件规范动作动词 |
| **场景/设备选择** | 设备选择引导 | 请选择设备 / Choose equipment | **请选择设备 / Select equipment** | 工业软件规范动作动词 |

---

## 4. 验证与上线结果

1. **自动化测试**：
   - 运行空间与地球点位测试（`apps/workbench/tests/cockpit-space.test.mjs`）：**9/9 通过**；
   - 运行资产状态与去重测试（`apps/workbench/tests/cockpit-state.test.mjs`）：**16/16 通过**；
   - 运行驾驶舱与分析工作台测试（`apps/workbench/tests/project-cockpit.test.mjs` 等）：**28/28 通过**。
2. **静态类型检查与构建打包**：
   - 执行 `node apps/workbench/node_modules/typescript/bin/tsc --noEmit -p apps/workbench`：**0 错误**；
   - 执行全量前端生产构建：68 个静态文件打包完毕，资源哈希计算完成。
3. **版本提交与 GitHub 推送**：
   - 提交哈希：[`29511eb`](https://github.com/ideeinfo/ontovis/commit/29511eb1193283c2ad17f6c3b2db38d0c5a1157b) (`fix(cockpit): 修复地球图钉双层背景与左侧底色截断缝并规范多语言用词`)；
   - 已推送至远端分支 `origin/codex/design-foundation`。
4. **服务器部署（192.168.2.153 / `https://vis.ontobase.ai`）**：
   - **部署状态**：已成功发布至测试/生产服务器；
   - **前端版本**：`29511eb1193283c2ad17f6c3b2db38d0c5a1157b`；
   - **后台服务**：保持 PID `125388`，0 次重启，零业务中断；
   - **接口核验证明**：`curl -k -s https://vis.ontobase.ai/health` 返回 `200 OK`，包含 `"frontendRelease": "29511eb1193283c2ad17f6c3b2db38d0c5a1157b"`、`"cockpitGlobePinFixVersion": 1`、`"cockpitGlobeCanvasOverscanVersion": 1`、`"cockpitMultiLanguageCleanVersion": 1`；
   - **线上静态资源核验**：线上 CSS 精确生效 `.pc-globe-render{position:absolute;inset:-4% -18% -4% -6%}` 与 `.pc-globe-pin-label` 样式，JS 精确包含“目标设备”与单复数多语言逻辑。
