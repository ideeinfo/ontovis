# 风机实体化包含风叶并精简下移底部模型工具条 实施方案

## 1. 背景与目标

用户在测试服务器体验三维视口最新版本后，提出了两项明确的视觉与交互优化要求：
1. **实体化时，需要连风叶一起实体化**：当前在内部构件选中/隔离模式下，点击“实体”时，机舱恢复为白色实体外壳，但风叶（叶片、叶轮、轮毂）依然呈现半透明灰色，没有与机舱同步实体化；
2. **去掉下方提示信息，工具条下移**：当前底部控制坞下方堆叠了“外壳半透明 · 显示模型内部”的说明框以及“模拟 · 运行中”的药丸按钮，不仅遮挡视口，还将“实体/透视/爆炸示意”工具栏顶得过高，需要去除这两行信息并将工具条下移居底。

---

## 2. 根因剖析与详细改造设计

### 2.1 需求一：风叶实体化逻辑改造
#### 根因：
在 [`apps/workbench/src/sceneCabinetAppearance.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneCabinetAppearance.ts) 中：
- 外壳遮挡集合目前定义为 `const shells = new Set(['tower', 'nacelle', 'rotor_cover']);`，未将叶片（`blade`）、叶轮/转子（`rotor`）、轮毂（`hub`）等风机外部气动总成纳入；
- 当构件隔离（`isolate === true`）或者非选中材质转换时，非 `shells` 的构件一律被判定为内部构件（`role: 'interior'`），并在材质 clone 中被强制赋上 `opacity: 0.5`（半透明）。
- 因此，当用户选择“实体化”（`fadeShell === false`）时，系统仅将 `shells` 恢复了实体材质，风叶因为被误判为“内部构件”而被渲染为半透明。

#### 方案：
1. **统一风机外表总成定义**：
   - 建立外部外观构件集合：`['tower', 'nacelle', 'rotor_cover', 'blade', 'rotor', 'hub']`，以及对节点名称和 TU-3000 结构树的叶片节点（Node 2、143~175）进行统一的外表构件判定；
2. **实体模式完全不透明**：
   - 在实体化模式（`fadeShell === false`）下，只要网格不属于当前被高亮的目标内部构件（`!highlight`），所有属于机舱、塔筒、风叶、轮毂的外表总成部件，一律直接保留或恢复为原始不透明实体材质（`return material;`）；
   - 保证实体化时，整台风机从塔架、机舱到旋转叶片完全浑然一体、皆为实体。

---

### 2.2 需求二：去除多余提示并下移工具条
#### 根因：
- [`apps/workbench/src/CockpitModelView.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitModelView.tsx) 中在按钮组下方渲染了 `<p role="status">`，展示“外壳半透明 · 显示模型内部”等辅助文字；
- [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) 的 `.pc-model-dock` 容器内包含了 `<button className="pc-demo-button"><Rotate3D .../>{selectedMotionText}</button>`（展示“模拟 · 运行中”）；
- [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) 中 `.pc-model-dock` 的定位写为 `bottom: 52px`，由于下方有提示信息支撑，导致工具条被向上顶高。

#### 方案：
1. **精简组件结构**：
   - 在 `CockpitModelView.tsx` 中移除 `<p role="status">` 说明文案；
   - 在 `ProjectCockpit.tsx` 的 `.pc-model-dock` 容器中移除下方挂载的 `pc-demo-button`（“模拟 · 运行中”）；
2. **工具条下移**：
   - 修改 `projectCockpit.css`，将 `.pc-model-dock` 的 `bottom` 从 `52px` 下调为 `20px`（容器查询中响应式断点同步从 `50px` 调整为 `18px`~`20px`）；
   - 移除 `.pc-model-dock .pc-model-view > p` 相关的多余 CSS；
   - 整体呈现为视口底部居中、精美悬浮的极简三态胶囊控制坞：`[ 实体 | 透视 | 爆炸示意 ]`。

---

## 3. 涉及文件清单

| 文件路径 | 变更目的 |
|---|---|
| [`apps/workbench/src/sceneCabinetAppearance.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneCabinetAppearance.ts) | 扩充外表总成判定逻辑，确保实体化模式下风叶、轮毂与机舱同步保持不透明实体 |
| [`apps/workbench/src/CockpitModelView.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitModelView.tsx) | 移除底部说明文字标签 `<p role="status">` |
| [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 在模型查看坞中移除“模拟 · 运行中”的常驻药丸按钮 |
| [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) | 将 `.pc-model-dock` 的 `bottom` 从 `52px` 调整为 `20px`，下移工具条 |
| [`apps/workbench/tests/scene-cabinet-appearance.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/scene-cabinet-appearance.test.mjs) | 补充实体化模式下风叶（blade/rotor）保持实体的断言测试 |

---

## 4. 验证计划

1. **自动化测试**：
   - 运行构件外观测试套件：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/scene-cabinet-appearance.test.mjs apps/workbench/tests/cockpit-model-view.test.mjs
     ```
   - 运行全量测试套件（769+ 项用例）：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/*.test.mjs
     ```
2. **静态检查与前端构建**：
   - TypeScript 类型核验：
     ```bash
     node apps/workbench/node_modules/typescript/bin/tsc --noEmit -p apps/workbench
     ```
   - 生产打包构建：
     ```bash
     ONTOVIS_LOGIN_MEDIA_PUBLIC_DIR=... npm --prefix apps/workbench run build
     ```
3. **用户界面效果对照**：
   - 对比用户上传的截图 `media_1793857655412_c91cf0ba.jpg`，确认下方提示卡片彻底消失，工具条平滑居中下移贴近底边；
   - 验证选中“发电机”或“动力柜”并切换“实体”时，风机叶片与机舱、塔筒全部恢复为不透明实体白壳。
