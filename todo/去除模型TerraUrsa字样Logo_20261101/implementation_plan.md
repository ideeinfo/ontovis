# 去除模型上带有TerraUrsa字样的Logo并保留其他Logo 实施方案

## 1. 现状调研与精准定位

通过对本地及线上全部 85 个 GLB 模型文件、全部 27 张内嵌独立贴图的全面扫描与视觉核验：

### 1.1 带有 TerraUrsa 字样的 Logo 定位
整个模型库中，带有 `TerraUrsa` 字样的模型贴图**仅有且只有以下两张**：
1. **`TU-22K` 系列风机模型**（`e03ff30f-...`, `c84653df-...`, `bfbcb9fc-...`, `75b25074-...` 等 4 个版本）：
   - 机舱两侧 Decal 贴面节点为 `Static:nacelle:20`（`mergedForRenderingOnly: true`）。
   - 贴图内容为 `40d0eb2b2e50`（左侧为棕熊徽标 + 蓝色 `TerraUrsa` 艺术字，右侧为机型 `TU-22K`）。
   - 当前在机舱两侧呈现明显的 `TerraUrsa` 字样与熊徽标。
2. **`TU-3000` 系列风机模型**（`e714805f-...`, `1fdb9dc5-...`, `9bcb448b-...` 等 6 个版本）：
   - 原机舱两侧 Decal 贴面节点为 `Static:nacelle:10`。
   - 原版贴图内容为 `6667c1f09031`（`TERRAURSA` + 横线 + `XXX-3000`）。
   - 平顶山夏李场景已按前序指令更换为官方原件 `ONTOVis.png`（ONTOVis AI 本源数智）；若在未配置 ONTOVis Logo 的通用情况下加载 `TU-3000`，原带有 `TERRAURSA` 的机舱 Logo 贴面也必须彻底去除。

### 1.2 其他真实品牌与机型 Logo 范围（必须 100% 完整保留）
库内其余 25 张内嵌贴图全部属于真实厂商、业主或工程机型标识，按用户明确要求**完整保留，绝不误伤**：
- `Vestas`（维斯塔斯真实厂商 Logo）
- `SIEMENS Gamesa`（西门子歌美飒真实厂商 Logo）
- `SIEMENS`（西门子真实厂商 Logo）
- `MINGYANG`（明阳风电真实厂商 Logo）
- `ENERCON`（埃纳康真实厂商 Logo）
- `NORDEX`（安迅能/诺德克斯真实厂商 Logo）
- `VATTENFALL`（大瀑布电力真实业主 Logo）
- `MHI VESTAS OFFSHORE WIND`（三菱重工维斯塔斯真实厂商 Logo）
- `ONTOVis AI / 本源数智`（官方原件品牌图标）
- 机型编号（`SWT-3.6-107`, `V105-3.45 MW`, `DELTA4000`, `MM82`）、机位编号（`02A`, `C04`）、停机坪 `H` 标识、塔筒铭牌（`T27 ORENELL WIND FARM`）等。

---

## 2. 方案设计与技术路径

为避免直接篡改底层 GLB 二进制导致文件 SHA-256 改变并破坏系统既有指纹校验、场景快照及构件绑定，沿用工作区已验证的成熟技术规范：在三维模型加载解析核心管道中建立全局 **品牌 Logo 净化过滤器**。

### 2.1 模型加载管道清理（`sceneResourceCache.ts`）
1. 扩展现有 `applyNacelleBrandLogo` 为统一处理函数 `sanitizeModelLogos(root: THREE.Object3D)`：
   - **清除 TU-22K 的 TerraUrsa Logo**：遍历识别到 `Static:nacelle:20` 节点（或绑定有带 TerraUrsa 贴图的网格），将其 `visible = false` 并从渲染树中隔离，使机舱两侧不再显示带有 `TerraUrsa` 字样的标志，露出干净整洁的白色机舱外壳。
   - **保全 TU-3000 的 ONTOVis 图标**：对 `Static:nacelle:10` 节点，平顶山夏李等场景继续赋予无拉伸的官方 `ONTOVis.png` 图标；若未加载 ONTOVis 图标，则隐藏带有 `TERRAURSA` 字样的原贴面。
   - **保全所有其他真实品牌 Logo**：对包含 `Vestas`, `Siemens`, `MingYang`, `Nordex`, `Enercon` 等真实厂商的节点与材质不做任何隐藏或变动，100% 完整保留。
2. 确保各渲染入口统一接入：
   - 场景视口解析（`parseModel` in `sceneResourceCache.ts`）；
   - 模型中心与构件检查视口（`ModelViewport.tsx`）；
   - 模型缩略图渲染器（`modelThumbnailRenderer.ts`）。

---

## 3. 涉及文件与修改计划

| 文件 | 变更目的 |
|---|---|
| [`apps/workbench/src/sceneResourceCache.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneResourceCache.ts) | 升级 `applyNacelleBrandLogo` 为 `sanitizeModelLogos`，实现对 `Static:nacelle:20` 等 TerraUrsa Logo 的净化清除，同时保留 ONTOVis 及所有其他真实厂商 Logo |
| [`apps/workbench/src/ModelViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ModelViewport.tsx) | 在模型中心模型视口中调用 `sanitizeModelLogos`，确保模型中心预览时 TerraUrsa Logo 同样被清除 |
| [`apps/workbench/src/modelThumbnailRenderer.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/modelThumbnailRenderer.ts) | 在模型缩略图渲染中调用 `sanitizeModelLogos`，避免缩略图出现 TerraUrsa Logo |
| [`apps/workbench/tests/model-logo-sanitization.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/model-logo-sanitization.test.mjs) | 新增单元测试，验证 TU-22K 隐藏、TU-3000 处理、Vestas/Siemens/MingYang 等保留 |
| [`docs/plans/开发执行记录.md`](file:///Users/diwei/项目2026/OntoVis/docs/plans/开发执行记录.md) & [`docs/plans/工作区交接.md`](file:///Users/diwei/项目2026/OntoVis/docs/plans/工作区交接.md) | 记录第 176 节交付与最新工作区交接快照 |

---

## 4. 验证计划

1. **自动化测试**：
   - 运行新增的 `model-logo-sanitization.test.mjs`；
   - 运行前端全量单元测试与 `tsc --noEmit`；
   - 运行 `python3 tools/build_workbench.py` 确保打包与构建零错误。
2. **多机型视觉对照核验（无头浏览器截图）**：
   - 查看 `TU-22K`：验证机舱两侧的 `TerraUrsa` 熊 Logo 已彻底消失；
   - 查看 `TU-3000` / 夏李风机：验证机舱两侧展现官方 `ONTOVis` 图标，无 TerraUrsa；
   - 查看 `MySE18.5-260`：验证机舱两侧明阳（MINGYANG）蓝色 Logo 完好保留；
   - 查看 `Vestas` / `Siemens Gamesa`：验证维斯塔斯、西门子真实品牌 Logo 完好保留。
3. **远端部署与业务保全**：
   - 部署更新到远端测试服务器；
   - 核验全库既有数据、场景缩略图及模型资产完整无损。
