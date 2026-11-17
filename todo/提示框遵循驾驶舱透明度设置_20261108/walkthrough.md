# 驾驶舱提示框遵循透明度与毛玻璃设置完成报告

## 1. 任务概述

用户反馈：
> “这类提示框也应遵循驾驶舱的透明度设置”
> 并附截图（`media_1794112053309_2cb4c63c.jpg`），指出三维场景准备与资源加载过程中的居中进度提示框呈现为纯黑/实心深灰色块，没有毛玻璃效果，也无法响应用户在“显示设置”中选择的透明度档位。

本次优化彻底将场景资源准备加载框（`.sw-loading`）、三维视口状态提示框（`.ov-scene-viewport-state`）、地表交互信息卡（`.sw-ground-cursor-badge`）、视口操作与说明条等全部驾驶舱前景悬浮提示元素统一接入了驾驶舱毛玻璃与透明度系统。

---

## 2. 核心问题定位与技术实现

### 2.1 根因分析
1. **作用域选择器过于狭窄导致回退**：
   原有样式中仅声明了 `.pc-spatial[aria-busy=true] .sw-loading`。但在进入普通场景、切换模型、重新加载视口时，由于不属于跨场景连续运镜飞行，`.pc-spatial` 并不携带 `[aria-busy=true]` 属性，直接回退为底层组件的深灰实心样式（`background: var(--surface); border-radius: 4px;`）。
2. **多层背景叠加导致通透感丧失**：
   外层视口状态居中容器 `.pc-viewport .ov-scene-viewport-state` 自带底层实色背景，在包含 `.sw-loading` 时未清除背景层，阻碍了内层毛玻璃透光。

### 2.2 解决方案与重构要点
1. **全局加载提示框毛玻璃化与透明度联动**：
   - 在 [`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css) 中，将选择器全面提升为覆盖所有驾驶舱视口与外壳：
     `.pc-app .sw-loading, .pc-scene-shell .sw-loading, .pc-viewport .sw-loading, .pc-spatial .sw-loading`；
   - 统一切换至 `background: var(--pc-panel); backdrop-filter: var(--pc-blur); border: 1px solid var(--pc-border); border-radius: 12px;`，并具备 `box-shadow: 0 16px 44px rgba(0,0,0,.3)` 深空阴影；
   - 实时响应用户在驾驶舱“显示设置”中调节的 **超高通透 (35%)**、**高通透 (50%)**、**标准 (65%)**、**微透 (85%)**、**实心 (100%)** 档位。
2. **视口状态容器多层融合**：
   - 当 `.ov-scene-viewport-state` 内部渲染 `.sw-loading` 时，外层重置为全透无边框与无阴影，完全由内层卡片独立呈现清爽通透的毛玻璃；
   - 当视口遇到错误需要提示重试按钮时，外层容器自身呈现精致通透的毛玻璃卡片（`border-radius: 12px; background: var(--pc-panel)`）。
3. **返回按钮与配套浮动指示框统一收敛**：
   - 强化下方的“返回资产组合/重试”按钮组（`.pc-entry-actions button`），加入微动悬浮阴影与 hover 呼吸高亮；
   - 在 [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) 中，为三维地表光标指示框（`.sw-ground-cursor-badge`）、三维视口工具条（`.ov-scene-viewport-tools`）、影像来源（`.ov-scene-imagery-attribution`）及环境状态条（`.ev-status`）统一注入 `var(--pc-panel)` 与 `var(--pc-blur)`。

---

## 3. 代码变更清单

| 文件路径 | 变更说明 |
| :--- | :--- |
| [`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css) | 移除针对 `aria-busy` 的狭窄选择器限制；支持驾驶舱内所有 `.sw-loading` 绑定 `var(--pc-panel)`、`var(--pc-blur)` 和 12px 圆角；消除 `.ov-scene-viewport-state:has(.sw-loading)` 的双层背景叠加；提升返回按钮 `.pc-entry-actions button` 的通透毛玻璃质感与交互悬浮态。 |
| [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) | 为三维地表光标悬浮卡片 `.sw-ground-cursor-badge`、视口顶部工具条 `.ov-scene-viewport-tools`、底部影像归属 `.ov-scene-imagery-attribution` 及环境状态 `.ev-status` 增加驾驶舱统一的毛玻璃与透明度支持。 |
| [`apps/workbench/tests/cockpit-space.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/cockpit-space.test.mjs) | 增加对场景准备加载框、视口居中状态框与视口浮层提示遵循毛玻璃和透明度规则的自动化回归测试。 |

---

## 4. 自动化测试与部署验证

1. **测试与类型检查**：
   - 运行 `npm --prefix apps/workbench run check`；
   - 全量 **776 项单元测试 100% 全部通过**；
   - TypeScript 类型检查 0 报错，Vite 构建打包顺利通过。
2. **代码提交与推送**：
   - Commit: `dfe0cb9` (`feat(cockpit): 场景准备加载框及各类视口浮动提示元素支持毛玻璃与透明度设置`)；
   - 已推送到远端分支 `origin codex/design-foundation`。
3. **测试服务器发布验证**：
   - 发布主机：`192.168.2.153` (`root@192.168.2.153`)；
   - 部署路径：`/data/ontovis/workbench-releases/dfe0cb9852ab3e61a2b09536874e292ca556c660/`；
   - 软链接已原子切换至最新 release；
   - 服务已平滑重启（`systemctl restart workbench-instance`，状态 `active (running)`）；
   - 外部公网访问 `curl -fsSI https://vis.ontobase.ai` 返回 `HTTP/2 200`，所有前端静态资源已更新生效。
