# 风机实体化包含风叶并精简下移底部模型工具条 验收报告

## 1. 任务概述

针对三维视口用户反馈的两项核心体验诉求进行了系统性优化：
1. **实体化时风叶同步实体化**：在构件查看模式下点击“实体”时，不仅塔筒和机舱恢复为实体不透明，风叶（叶片、叶轮/转子、轮毂）也同步作为风机外部外观总成恢复为实体，不再呈现半透明；
2. **去除堆叠提示并下移工具条**：移除了模型控制坞下方的 `<p role="status">` 说明文案标签以及常驻的“模拟 · 运行中”药丸按钮，将 `.pc-model-dock` 底部悬浮间距由 `52px` 调整为贴底 `20px`（断点同步适配），呈现清爽极简的底部悬浮三态胶囊按钮。

---

## 2. 变更文件与具体实施内容

| 文件路径 | 变更类型 | 核心改动说明 |
|---|---|---|
| [`apps/workbench/src/sceneCabinetAppearance.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneCabinetAppearance.ts) | 逻辑改造 | 1. 引入 `exteriorComponents` 外部外观集合（`tower`、`nacelle`、`rotor_cover`、`blade`、`blade_assembly`、`rotor`、`rotorAssembly`、`hub`）与 `isExteriorMesh` 统一判定函数（支持 TU-3000 叶片节点 2、143~175 与名称正则）；<br>2. 实体模式下（`!fadeShell`），凡是非当前高亮目标的外部总成部件（包含风叶与机舱），直接返回原材质（`return material;`），保证完全不透明实体；<br>3. 保持普通非隔离模式下 `enclosing` 仅包含 `shells` 的遮挡透光逻辑不变。 |
| [`apps/workbench/src/CockpitModelView.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitModelView.tsx) | 视图精简 | 移除底部说明文字标签 `<p role="status">`，仅在不支持爆炸透视的模型上保留小型 `<small>` 状态。 |
| [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 视图精简 | 在 `.pc-model-dock` 容器中移除下方堆叠的 `<button className="pc-demo-button">`（“模拟 · 运行中”），清理未引用的辅助状态计算。 |
| [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) | 样式优化 | 将主样式及容器查询响应式断点中的 `.pc-model-dock` 定位从 `bottom: 52px` / `50px` 调整为 `bottom: 20px`，贴底居中悬浮。 |
| [`apps/workbench/tests/scene-cabinet-appearance.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/scene-cabinet-appearance.test.mjs) | 测试断言 | 在 fixture 中扩充叶片网格，并在 `solid shell mode (fadeShell=false)` 用例中增加风叶同步保持实体的断言。 |

---

## 3. 验证与测试结果

1. **单元测试验证**：
   - 构件外观测试（17 项全部通过）：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/scene-cabinet-appearance.test.mjs
     # ✔ 17 tests passed, 0 failed
     ```
   - 模型查看组件测试（3 项全部通过）：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/cockpit-model-view.test.mjs
     # ✔ 3 tests passed, 0 failed
     ```
   - Workbench 全量测试套件（769 项全部通过）：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/*.test.mjs
     # ✔ 769 tests passed, 0 failed
     ```
2. **TypeScript 静态检查**：
   - 运行 `tsc --noEmit -p apps/workbench`，零类型错误。
3. **生产打包构建**：
   - 生产包构建成功，Chunk 体积正常，资源无缺失。
4. **服务器远程发布与健康检查**：
   - 线上服务通过远程热发布同步至 `192.168.2.153` (`https://vis.ontobase.ai`)；
   - 线上健康探针 `https://vis.ontobase.ai/health` 检查返回 200 OK。
