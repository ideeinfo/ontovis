# 驾驶舱前景面板毛玻璃效果与透明度优化 Walkthrough

## 1. 任务背景与目标

针对用户反馈：
> “将驾驶舱所有前景面板元素都处理成毛玻璃效果，透明度比现在左右侧面板的透明度再提高一点”
> “在显示设置里提供透明度设置选项，其余可以方案执行”

本次优化实现了以下核心成果：
1. **全域毛玻璃通透升级**：将驾驶舱内所有前景面板、浮动控件统一应用细腻的毛玻璃效果（`backdrop-filter: var(--pc-blur); -webkit-backdrop-filter: var(--pc-blur);`），默认透明度大幅提升（深色默认 alpha 调至 `0.66`，浅色调至 `0.72`）；
2. **顶部导航栏与面包屑栏真正透出三维背景**：重构了底层的三维与地球视口布局（`inset: 0` 贯通全屏），并将顶部导航栏（`.pc-header`）与面包屑栏（`.pc-breadcrumb`）整体毛玻璃化，彻底解决了过去视口被截断导致顶部背后纯黑实心的问题；
3. **显示设置中支持面板透明度调节**：在右上角“显示设置”（Display settings）中提供透明度下拉切换（包含 `超高通透 (35%)`、`高通透 (50%)`、`标准通透 (65% · 推荐)`、`微透 (85%)`、`实心 (100%)` 预设，并支持一键恢复推荐及 `localStorage` 跨会话持久化）。

---

## 2. 修改文件与核心变更清单

| 文件路径 | 修改类型 | 说明 |
| :--- | :--- | :--- |
| [`apps/workbench/src/cockpitState.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitState.ts) | 代码更新 | 定义 `CockpitPanelOpacity` 联合类型、`COCKPIT_OPACITY_VALUES` 预设映射以及读取持久化设置的 `cockpitSavedOpacity` 辅助函数 |
| [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 代码更新 | 引入透明度状态，动态向 `.pc-frame` 注入当前主题下的 `--pc-panel-alpha`，并在“显示设置”弹窗提供选择菜单与一键恢复默认 |
| [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) | 样式重构 | 1. 定义 `--pc-panel-base`、`--pc-panel`、`--pc-panel-strong` 联动 `--pc-panel-alpha`；<br>2. 统一定义 `--pc-blur: blur(20px) saturate(140%)`；<br>3. 视口 `.pc-assets` 与 `.pc-spatial` 铺满全屏 `inset: 0`；<br>4. 顶部栏与全宽面包屑栏整体毛玻璃化；<br>5. 左右侧面板、底部模型坞、视口工具、状态栏等统一配置毛玻璃与自适应布局 |
| [`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css) | 样式更新 | 地球与空间页浮动交互按钮（`.pc-globe-home`、`.pc-globe-pause`、`.pc-globe-credit`、`.pc-globe-choice`、`.pc-space-loading` 等）统一应用毛玻璃样式 |
| [`apps/workbench/src/cockpitAnalysis.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitAnalysis.css) | 样式更新 | 分析工作台相关前景工具栏（`.pa-context`、`.pa-card`、`.pa-query-launch`、`.pa-canvas-tools`、`.pa-relation-label` 等）应用毛玻璃样式 |
| [`apps/workbench/tests/cockpit-state.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/cockpit-state.test.mjs) | 单元测试 | 新增针对透明度预设与持久化回退逻辑的单元测试 |

---

## 3. 验证与部署结果

1. **自动化测试与静态检查**：
   - 运行 `npm --prefix apps/workbench run check`：
     - TypeScript 校验：零错误；
     - 单元测试：774+ 项测试全量通过（含 17 项 cockpit-state 测试）；
     - Vite 生产构建打包成功。
2. **Git 提交与推送**：
   - 提交 Commit：`ef94c2445c8152999d941610d334f3700ade7fa9`（`feat(cockpit): 驾驶舱前景面板毛玻璃效果与透明度偏好设置`）；
   - 推送至 `origin codex/design-foundation`。
3. **测试服务器部署**：
   - 测试服务器：`192.168.2.153` (`https://vis.ontobase.ai`)；
   - 发布目录：`/data/ontovis/workbench-releases/ef94c2445c8152999d941610d334f3700ade7fa9`；
   - 软链接切换：`/data/ontovis/workbench-current` 成功指向最新 release；
   - 服务状态：`workbench-instance.service` 正常运行，`curl -fsSI https://vis.ontobase.ai` 返回 `HTTP/2 200`，最新毛玻璃样式与透明度交互已在线生效。
