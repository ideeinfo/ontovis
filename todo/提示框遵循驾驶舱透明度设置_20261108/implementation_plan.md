# 驾驶舱各类提示框遵循透明度与毛玻璃设置实施方案

## 1. 背景与目标

用户反馈：
> “这类提示框也应遵循驾驶舱的透明度设置”
> 并附截图（`media_1794112053309_2cb4c63c.jpg`），红圈标出三维场景准备过程中居中显示的提示框：
> “正在准备场景资源 0/4 · 0% · 准备步骤”及下方“返回资产组合”操作区。

**问题诊断**：
1. **作用域选择器过于严苛导致失效**：
   在 `apps/workbench/src/cockpitSpace.css` 中，原本仅对 `.pc-spatial[aria-busy=true] .sw-loading` 设置了毛玻璃样式。但当用户进入普通场景资源加载、视口内切换模型或刷新场景时，`.pc-spatial` 并不带 `[aria-busy=true]`（该属性仅在跨场景连续运镜飞行导航期间存在）。因此降级回退到 `sceneLoading.css` 基础的实心背景（`background: var(--surface); border-radius: 4px;`），表现为一块纯黑/实心深灰小方块，未能呈现毛玻璃效果，也无法响应用户在“显示设置”中调节的面板透明度。
2. **三维视口状态框多层嵌套背景污染**：
   外层状态容器 `.pc-viewport .ov-scene-viewport-state` 具备自身基础背景，未与内层加载框完全融合；在错误重试、准备中等不同状态切换时容易出现背景生硬、圆角割裂。
3. **驾驶舱浮动提示类元素样式未统一收敛**：
   除 `.sw-loading` 外，三维视口内的状态提示（重试/错误）、地表高程放置提示卡片（`.sw-ground-cursor-badge`）、影像来源说明（`.ov-scene-imagery-attribution`）、环境水纹流云状态条（`.ev-status`）、空间返回/重试操作按钮（`.pc-entry-actions button`）等浮动提示类元素，均属于驾驶舱前景悬浮层，应统一遵循驾驶舱的设计语言，实时继承当前配置的透明度档位（35% ~ 100%）。

**本次改造目标**：
- 让三维场景资源加载框（`.sw-loading`）、视口状态提示（`.ov-scene-viewport-state`）、地表交互信息卡（`.sw-ground-cursor-badge`）及各类浮动提示框彻底接入驾驶舱毛玻璃与透明度系统（`var(--pc-panel)`、`var(--pc-blur)`、`var(--pc-border)`）；
- 用户在“显示设置”弹窗中无论选择**超高通透 (35%)**、**高通透 (50%)**、**标准 (65%)**、**微透 (85%)** 还是 **实心 (100%)**，此类提示框均能实时、无缝自适应改变半透明度；
- 视觉风格对齐驾驶舱现代工业质感：采用 12px 雅致圆角、立体悬浮阴影、通透微边框与精细文本排版。

---

## 2. 详细改造范围与设计

### 2.1 样式重构点（[`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css)）
1. **全局加载提示框收敛**：
   移除针对 `[aria-busy=true]` 的限定条件，提升选择器为：
   ```css
   /* 驾驶舱内所有资源准备与加载提示框 */
   .pc-app .sw-loading,
   .pc-scene-shell .sw-loading,
   .pc-viewport .sw-loading {
     width: min(360px, calc(100% - 32px));
     border-radius: 12px;
     background: var(--pc-panel);
     backdrop-filter: var(--pc-blur);
     -webkit-backdrop-filter: var(--pc-blur);
     border: 1px solid var(--pc-border);
     box-shadow: 0 16px 44px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.08);
     padding: 18px 22px;
     color: var(--pc-text);
   }
   .pc-app .sw-loading strong {
     color: var(--pc-text);
     font-size: 14px;
     font-weight: 500;
   }
   .pc-app .sw-loading small {
     color: var(--pc-muted);
     font-size: 11px;
   }
   ```
2. **三维视口居中状态框与背景剔除**：
   - 当 `.pc-viewport .ov-scene-viewport-state` 包含 `.sw-loading` 时，外层容器重置为无边框、无背景、无内边距，完全由内层 `.sw-loading` 负责毛玻璃呈现；
   - 当包含错误信息、重试按钮时，外层容器自身呈现精致毛玻璃卡片（`border-radius: 12px; background: var(--pc-panel); backdrop-filter: var(--pc-blur); border: 1px solid var(--pc-border); box-shadow: 0 16px 44px rgba(0, 0, 0, 0.3);`）。
3. **返回操作按钮与进入动作（`.pc-entry-actions`）**：
   - 强化 `.pc-entry-actions button` 的通透毛玻璃感，增加悬浮投影和 hover 呼吸高亮；
   - 确保其位置居中并与上方加载框保持舒适间距。

### 2.2 其他视口内悬浮提示框适配（[`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) / [`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css)）
1. **三维地表光标指示框（`.sw-ground-cursor-badge`）**：
   - 在驾驶舱视口中，放置提示框应用 `background: var(--pc-panel); backdrop-filter: var(--pc-blur); border: 1px solid var(--pc-border); border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.25);`；
2. **视口底部环境与属性提示（`.ov-scene-imagery-attribution`、`.ev-status`）**：
   - 应用 `background: var(--pc-panel); backdrop-filter: var(--pc-blur); border: 1px solid var(--pc-border); border-radius: 8px;`，消除原生深黑实底。

---

## 3. 验证与部署步骤

1. **功能与交互验证**：
   - 在驾驶舱中切换场景、进入风机或刷新三维视口，验证“正在准备场景资源”提示框呈现通透毛玻璃；
   - 打开右上角“显示设置”，在“面板透明度”中切换不同档位（超高通透、高通透、标准、微透、实心），观察加载提示框背景是否实时联动改变通透度；
   - 验证深色主题与浅色主题下的背景色对比度与文字清晰度；
   - 检查视口错误重试状态、“返回资产组合”按钮等配套提示框是否一致保持毛玻璃效果。
2. **自动化测试与编译构建**：
   - 在 `apps/workbench/tests/` 中编写或完善提示框样式的回归单测；
   - 运行 `npm --prefix apps/workbench run check`，确保全部测试、TypeScript 类型与 Vite 编译 100% 通过。
3. **提交与测试服务器发布**：
   - 提交代码并推送到 `origin codex/design-foundation`；
   - 将最新产物同步部署至 `https://vis.ontobase.ai`（`192.168.2.153`），验证公网在线体验并归档 `walkthrough.md`。
