# 工程助手面板收起、展开与拖放移动完成报告

## 1. 任务概述

用户需求：
> “让工程助手面板可以收起、展开、拖放移动”
> 针对分析工作台（`CockpitAnalysis`）右侧的“工程助手”侧边栏面板。

本轮优化实现了工程助手面板的自由交互体系，解决了固定侧边栏挤占全景分析画布视野的问题，允许用户在沉浸式全屏图谱排查与多窗口自由对照分析之间灵活切换。

---

## 2. 核心功能与技术实现

### 2.1 收起与一键全宽展开（Collapse & Expand）
1. **收起控制（`PanelRightClose`）**：
   - 在工程助手标题栏右上侧新增收起按钮（带工具提示 `收起工程助手`）；
   - 点击后，工程助手面板平滑收起，主分析画布（`.pa-evidence`）自动撑满 100% 宽度，享受无遮挡的全景图谱与资料排布体验；
   - 记录用户的收起偏好至 `localStorage`（键名 `ontovis.cockpit.assistant_collapsed`），跨会话与刷新后保持一致。
2. **轻量毛玻璃呼出胶囊（`pa-assistant-launcher`）**：
   - 收起后，工作区右上侧呈现轻量毛玻璃呼出入口（`✨ 工程助手 ⇥`）；
   - 悬浮具备呼吸微动与高亮反馈，点击即可一键展开工程助手；
   - 外部业务联动：用户在主画布点击“基于当前资料提问”时，若助手处于收起状态，将自动展开并无缝聚焦输入框。

### 2.2 原生平滑拖拽与视口防越界（Drag & Drop Move）
1. **Pointer Capture 原生手势拖动**：
   - 标题栏采用原生 `PointerEvent` 与 `setPointerCapture`，按住标题栏即可平滑拖拽；
   - 智能识别点击目标：排除控制按钮（`closest('button')`），避免点击收起/复位时发生误拖；
   - 微动死区防抖（4px 阈值）：轻微点击不破坏默认停靠布局，超过阈值后自然脱离并转化为自由浮动窗口（Floating Window）。
2. **视口边界防护（Boundary Clamping）**：
   - 依据 `.pa-content` 实际可用工作区计算边缘约束；
   - 限制坐标在 `[8px, parentWidth - panelWidth - 8px]` 及 `[8px, parentHeight - 60px]`，保证面板永不拖飞出屏幕可视范围，始终可触达。
3. **浮动视觉与双击复位停靠（Docking & Reset）**：
   - 浮动状态下面板呈现独立立体悬浮阴影（`box-shadow: 0 18px 48px rgba(0,0,0,.45)`）与精致微边框，拖动过程中具备光标 `grabbing` 与聚焦轮廓；
   - 浮动面板标题栏右上侧显式提供“恢复停靠至右侧”（`RotateCcw`）按钮；
   - 支持**双击标题栏**（`onDoubleClick`）一键复位停靠回默认右侧网格栏。

---

## 3. 代码与样式变更清单

| 文件路径 | 变更说明 |
| :--- | :--- |
| [`apps/workbench/src/CockpitAnalysis.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitAnalysis.tsx) | 引入 `PanelRightClose`, `PanelRightOpen`, `GripHorizontal` 图标；添加 `assistantCollapsed`, `assistantFloating`, `assistantDragging` 状态与 `assistantDrag` 指针捕获拖拽逻辑；支持标题栏拖动、双击复位、收起/展开呼出胶囊联动及状态持久化。 |
| [`apps/workbench/src/cockpitAnalysis.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitAnalysis.css) | `.pa-content` 启用相对定位；当 `[data-assistant-collapsed]` 或 `[data-assistant-floating]` 时网格列自适应为单列全宽（`1fr`）；增加浮动窗口尺寸、高层级（`z-index: 20`）、立体悬浮阴影、抓手图标、控制按钮及毛玻璃悬浮启动胶囊（`pa-assistant-launcher`）。 |
| [`apps/workbench/tests/cockpit-analysis.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/cockpit-analysis.test.mjs) | 增加工程助手收起、展开胶囊、拖拽浮动及边界保护专项回归测试。 |

---

## 4. 验证与部署结果

1. **本地单元测试与构建**：
   - 运行 `npm --prefix apps/workbench run check`；
   - 775 项单元测试 100% 全部通过；
   - TypeScript 类型检查 0 报错；
   - Vite 生产打包顺利完成。
2. **代码提交与推送**：
   - Commit: `37b0eec` (`feat(analysis): 工程助手面板支持收起展开与拖拽浮动移动`)；
   - 已推送至远程分支 `origin codex/design-foundation`。
3. **生产/测试环境发布**：
   - 目标主机：`192.168.2.153` (`root@192.168.2.153`)；
   - 部署路径：`/data/ontovis/workbench-releases/37b0eec4254a5bc0785f3b8173a5bb067ad659c8/`；
   - 软链接已原子切换：`/data/ontovis/workbench-current -> /data/ontovis/workbench-releases/37b0eec4254a5bc0785f3b8173a5bb067ad659c8`；
   - 服务已平滑重启：`workbench-instance.service` 状态为 `active (running)`；
   - 外部公网访问验证：`curl -fsSI https://vis.ontobase.ai` 返回 `HTTP/2 200`，静态资源加载正常。
