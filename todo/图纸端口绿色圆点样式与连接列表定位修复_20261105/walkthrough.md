# 图纸端口绿色圆点样式与连接列表定位修复完成总结 (Walkthrough)

## 1. 任务概述

针对用户在分析画布图纸证据查看器（例如查看图纸 `机舱信号柜供电`）中反馈的两个核心问题进行了彻底排查与修复：
1. **端口显示样式不对**：原先渲染为方框矩形，现已与 OntoBase 官方视觉对齐，展示为**墨绿色实心圆点**（白色高对比外边框、阴影与居中定位；选中态带脉冲光晕外环）；
2. **连接列表标题均显示“导线连接”，且“未提供可定位区域”**：后端从图纸端口导入与设备位号动态解析连接两端端点生成工程级语义标题（如 `+CN1-105A3:3 ↔ -26U11:5`、`+CN1-2Q1:T1 ↔ +CN1-X11:5`），并从折线顶点集合准确计算联合外接矩形 `bbox` 和 `pathPoints`，使前端具有清晰的端点标识、平滑居中聚焦以及 SVG 导线折线高亮。

---

## 2. 修改文件清单

| 文件 | 模块 | 核心修改说明 |
| :--- | :--- | :--- |
| [`apps/api/analysis_preview.py`](file:///Users/diwei/项目2026/OntoVis/apps/api/analysis_preview.py) | 后端 API | 1. 在 `section in ('ports', 'connections')` 时读取 ports 导入与设备位号建立端点解析映射；<br>2. 动态生成端点对应标题 `f"{label_a} ↔ {label_b}"` 与识别编号（如 `CONN-0001 · 导线连接`）；<br>3. 从折线点 `path.points` 计算联合外接矩形 `bbox`（带视口安全内边距）并返回 `pathPoints`。 |
| [`apps/workbench/src/analysisSources.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/analysisSources.ts) | 前端类型 | 在 `PreviewRow` 中增加 `pathPoints?: Array<{x: number; y: number}> \| null` 字段支持。 |
| [`apps/workbench/src/WorkOrderPhotoViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/WorkOrderPhotoViewport.tsx) | 前端组件 | 1. 增加 `isPort` 与 `connectionPath` 支持；<br>2. 端口模式下，所有端口热区渲染为 `.ac-drawing-port-point` 墨绿圆点，精准居中于 `(cx, cy)`；<br>3. 选中态渲染为 `.wo-photo-port-selected` 选中态圆点；<br>4. 传入连接路径时，上层 SVG 绘制导线折线与两端端点圆珠。 |
| [`apps/workbench/src/AnalysisEvidenceViewer.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/AnalysisEvidenceViewer.tsx) | 前端组件 | 1. 传递 `isPort={!document && section === 'ports'}` 给视口；<br>2. 传递 `connectionPath` 给视口；<br>3. 优化视口 key 确保连接切换时即时重绘。 |
| [`apps/workbench/src/analysisMaterials.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/analysisMaterials.css) | 样式定义 | 补充 `.ac-drawing-port-point`（14px 墨绿 `#328079`、白边、投影）、`.wo-photo-port-selected`（18px 墨绿、2px 白边、脉冲发光光晕）及 `.wo-photo-wire-line` SVG 样式。 |
| [`tests/test_analysis_preview.py`](file:///Users/diwei/项目2026/OntoVis/tests/test_analysis_preview.py) | 后端单测 | 新增 `test_drawing_connections_resolve_labels_and_compute_bbox`，断言端点标题解析、编号及包围盒计算正确。 |
| [`apps/workbench/tests/photo-viewport.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/photo-viewport.test.mjs) | 前端单测 | 新增端口圆点渲染、选中圆点居中以及连接导线 SVG 渲染断言。 |

---

## 3. 测试与验证结果

### 3.1 单元测试与构建验证
- **后端测试**：`python3 -m unittest tests/test_analysis_preview.py`
  - 结果：**22 项测试全部通过**（0 错误，0 失败）。
- **前端视口测试**：`node --test apps/workbench/tests/photo-viewport.test.mjs`
  - 结果：**12 项测试全部通过**（包含端口绿色圆点定位断言与导线折线 SVG 断言）。
- **前端全量检查与构建**：`npm --prefix apps/workbench run check`
  - 结果：TypeScript 类型检查通过，全量 770+ 项测试全部通过，Vite 生产包顺利构建。

### 3.2 测试服务器端到端实测验证
在测试服务器 `root@192.168.2.153` (`https://vis.ontobase.ai`) 上部署最新 commit `4bfe834` 并重新加载后端服务：
- 真实调用图纸 `Demo-PDS:5c94936f-eed5-5d32-bd98-34a1e6d9d327:doc-0001-p0090`（机舱信号柜供电）：
  - **连接列表**：
    - `[1] +CN1-2Q1:T1 ↔ +CN1-X11:5`（编号 `CONN-0001 · 导线连接`，bbox 存在，4 个折线点）
    - `[2] +CN1-2Q1:T2 ↔ +CN1-X11:6`（编号 `CONN-0002 · 导线连接`，bbox 存在，4 个折线点）
    - `[3] +CN1-2Q1:T3 ↔ +CN1-X11:7`（编号 `CONN-0003 · 导线连接`，bbox 存在，4 个折线点）
    - `[4] +CN1-X11:5 ↔ 机舱信号柜供电接口端子组（未印器件位号）`（编号 `CONN-0004 · 导线连接`，bbox 存在，7 个折线点）
    - `[8] +CN1-X11:PE ↔ +CN1-PE1`（编号 `CONN-0008 · 导线连接`，bbox 存在，6 个折线点）
    - `[10] +CN1-105A3:3 ↔ +CN1-2Q1:53`（编号 `CONN-0010 · 导线连接`，bbox 存在，2 个折线点）
    - 彻底消除了“全是一样的导线连接”以及“未提供可定位区域”；
  - **端口展示**：
    - 22 个端口全部显示为 OntoBase 标志性墨绿实心圆点（直径 14px，白边 `1.5px solid #fff`，阴影，居中对准端口引线）；
    - 选中态呈现带有脉冲外环光晕的高亮墨绿圆点（直径 18px），层次分明，与 OntoBase 视觉完全一致。
- 健康检查：`https://vis.ontobase.ai/health` 返回 `200 OK`，状态正常。
