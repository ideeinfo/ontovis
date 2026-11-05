# 图纸端口绿色圆点样式与连接列表定位修复实施方案

## 1. 背景与问题定义

用户在分析画布的图纸证据查看器（例如查看图纸 `机舱信号柜供电`）中，发现了以下两处与 OntoBase 设计不一致及数据展示缺失的问题：

1. **端口显示样式不对**：
   - **现状**：在切换到「端口」标签时，图纸视口将所有端口渲染为带浅绿背景的方框/矩形热区（`ac-drawing-hotspot` 与 `wo-photo-region`），与工程图纸规范严重不符。
   - **目标**：与 OntoBase 官方样式保持高度一致，以**墨绿色圆点**（`#328079`、白色边框 `1.5px solid #ffffff`、微阴影、圆角 50%）固定居中于端口坐标中心；选中态时圆点微放大并外扩半透明绿色脉冲光晕环，未选中态圆点悬停响应清晰。

2. **连接列表显示完全不对，标题都是一样的“导线连接”，定位信息也找不到**：
   - **现状**：在切换到「连接」标签时，左侧列表中所有连接项的标题都显示为“导线连接”，副标题显示“未提供可定位区域”，点击连接项后右侧图纸无任何居中定位与高亮导线展示。
   - **根因分析**：
     - 后端 [`apps/api/analysis_preview.py`](file:///Users/diwei/项目2026/OntoVis/apps/api/analysis_preview.py) 中，`section == 'connections'` 分支硬编码了 `title = row.get('relationship_type_text') or '连接'`（导致标题全是“导线连接”），且将 `bbox = None` 硬编码写死（导致前端判定无定位区域）；
     - 数据库底层在同一图纸的 `result_relation_imports` 中记录了完备的连接数据，包含折线路径 `path.points`（例如 `[{x: 0.1499, y: 0.4243}, ...]`）以及两端端点 `endpoint_a` 与 `endpoint_b`（如 `doc-0001-p0090/PORT-0002` 与 `doc-0001-p0090/PORT-0005`）；
     - 未将端点端口映射到所属工程对象（如 `+CN1-105A3`、`-26U11`）及端口端号（如 `3`、`5`），导致未能组合出有辨识度的连接标题 `+CN1-105A3:3 ↔ -26U11:5`；
     - 未从折线顶点集合计算联合包围盒 `bbox`，导致前端无法平滑定位视口。

---

## 2. 涉及文件与具体修改内容

### 2.1 后端：连接端点解析、动态标题生成与折线包围盒计算

- **修改文件**：[`apps/api/analysis_preview.py`](file:///Users/diwei/项目2026/OntoVis/apps/api/analysis_preview.py)
- **修改说明**：
  1. **建立端口与对象名称映射索引**：
     - 在 `drawing_preview` 中，当 `section == 'connections'` 时，读取图纸的端口导入记录（`kind='ports'`）与对象定位记录（`object-locations`），建立 `port_lookup` 字典；
     - 解析每个端口的所属设备位号/显示名称（如 `+CN1-105A3`）和端子号（如 `3`），生成可读端点标识（例如 `+CN1-105A3:3`；若无位号则为 `端口 3` 或端口编号 `PORT-0002`）；
  2. **生成高辨识度连接标题与编号标识**：
     - 提取 `endpoint_a` 与 `endpoint_b`，计算其显示名称 `label_a` 和 `label_b`；
     - `title`: `f"{label_a} ↔ {label_b}"`（例如 `+CN1-105A3:3 ↔ -26U11:5`）；
     - `identifier`: 提取 `source_connection_id` 短号（例如 `CONN-0001`）并附加连接类型（`f"{conn_code} · {relation_type}"`）；
  3. **计算真实联合包围盒与折线路径点**：
     - 从 `row.get('path', {}).get('points', [])` 中提取坐标点；
     - 当 `current` 且 `points` 有效时，计算包含所有折线点的最小外接矩形 `(min_x, min_y, max_x, max_y)`，加入适当内边距（`padding`，防止贴边），生成归一化 `bbox: {x, y, width, height}`；
     - 在连接项字典中额外返回 `pathPoints: points`，供前端视口绘制导线走向。
  4. **完善属性字典**：
     - `properties` 中记录：`起点: label_a`、`终点: label_b`、`连接编号: conn_code`、`连接类型: relation_type`、`折线端点数: len(points)` 等。

### 2.2 前端：类型扩展与视口圆点/导线折线渲染

- **修改文件**：
  1. [`apps/workbench/src/analysisSources.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/analysisSources.ts)
     - 在 `PreviewRow` 类型中增加 `pathPoints?: Array<{x: number; y: number}>`。
  2. [`apps/workbench/src/WorkOrderPhotoViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/WorkOrderPhotoViewport.tsx)
     - 增加属性支持：
       - `isPort?: boolean`：当前是否处于端口展示模式；
       - `connectionPath?: Array<{x: number; y: number}> | null`：选中的连接折线坐标点；
     - 当 `isPort === true` 时：
       - **热区列表（`regions`）**：不再渲染为矩形方框，而是以中心坐标 `(bbox.x + bbox.width / 2, bbox.y + bbox.height / 2)` 居中渲染为**实心墨绿色圆点**（类名 `ac-drawing-port-point`）；
       - **选中标注（`boxes`）**：选中端口时，渲染为**选中态高亮圆点**（类名 `wo-photo-port-selected`），直径约 18px，带有半透明绿色脉冲光晕与白色边框，精准突出；
     - 当存在 `connectionPath` 时：
       - 在图像上层 SVG 容器中渲染该导线的 SVG 折线高亮（`<polyline points="..." stroke="#328079" strokeWidth="3" .../>`），并标出首尾端点。
  3. [`apps/workbench/src/AnalysisEvidenceViewer.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/AnalysisEvidenceViewer.tsx)
     - 传递 `isPort={!document && section === 'ports'}` 给 `WorkOrderPhotoViewport`；
     - 传递 `connectionPath={!document && section === 'connections' && chosen?.pathPoints ? chosen.pathPoints : null}` 给 `WorkOrderPhotoViewport`；
     - 连接项选中时，将 `chosen.bbox` 转换为 `selector` 传递给视口，使图纸平滑居中聚焦到该导线区域。
  4. [`apps/workbench/src/analysisMaterials.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/analysisMaterials.css) / [`apps/workbench/src/workOrders.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/workOrders.css)
     - 新增墨绿圆点端口样式：
       - `.wo-photo-frame .ac-drawing-port-point`: 宽 14px，高 14px，`border-radius: 50%`，背景 `#328079`，边框 `1.5px solid #ffffff`，阴影 `0 1px 3px rgba(0,0,0,0.3)`，鼠标悬浮放大至 16px 并增强对比；
       - `.wo-photo-frame .wo-photo-port-selected`: 宽 18px，高 18px，`border-radius: 50%`，背景 `#328079`，边框 `2px solid #ffffff`，发光外环 `box-shadow: 0 0 0 4px rgba(50, 128, 121, 0.45), 0 2px 8px rgba(0,0,0,0.35)`；
       - `.wo-photo-wire-path`: SVG 折线高亮层样式。

### 2.3 测试与回归保证

- **修改/新增测试**：
  1. [`tests/test_analysis_preview.py`](file:///Users/diwei/项目2026/OntoVis/tests/test_analysis_preview.py)
     - 新增连接数据解析测试：验证连接项的标题正确解析为 `端点A ↔ 端点B`，验证 `bbox` 从折线点正确计算，验证 `pathPoints` 完整保留。
  2. [`apps/workbench/tests/photo-viewport.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/photo-viewport.test.mjs)
     - 补充端口圆点渲染与导线折线渲染的单测断言。

---

## 3. 验证与部署计划

1. **本地单元测试与构建验证**：
   - 运行后端 Python 单元测试：`python3 -m unittest tests/test_analysis_preview.py`；
   - 运行前端检查与单测：`npm --prefix apps/workbench run check`（包含 TypeScript 检查及全部 770+ 项单元测试）；
2. **部署至测试服务器**：
   - 将变更推送至 `codex/design-foundation` 分支；
   - 部署到测试服务器 `root@192.168.2.153`（`https://vis.ontobase.ai`），热切换 workbench release 目录并重启服务；
3. **真实端到端核验**：
   - 打开测试环境分析画布中图纸 `机舱信号柜供电`；
   - 验证「端口」标签：所有端口均显示为 OntoBase 墨绿色圆点，点击任一端口，圆点呈现高亮外环光晕，视口居中聚焦；
   - 验证「连接」标签：左侧列表中连接项具有清晰的端点标题（例如 `+CN1-105A3:3 ↔ -26U11:5`）与编号（如 `CONN-0001 · 导线连接`），不再显示“未提供可定位区域”；点击连接项，右侧图纸平滑聚焦至导线折线区域并高亮显示折线；
4. **归档与总结**：
   - 确认无误后编写并归档 `walkthrough.md` 至 `todo/图纸端口绿色圆点样式与连接列表定位修复_20261105/`。
