# 去除风机模型上带有 TerraUrsa 字样的 Logo 并保留其他真实厂商 Logo 验收总结

> [!NOTE]
> 本次任务已全部执行完毕，代码经全量 662 项单元测试、TypeScript 严格类型检查、生产打包，并已部署发布至生产环境（`https://vis.ontobase.ai`，版本 `dcfa34304899c75fe93e43ee56c4d8fa2069b183`）。无头浏览器 CDP 实机三维渲染截图核验 100% 通过。

---

## 一、排查范围与处理原则

对库内全部 85 个三维模型 GLB 与 27 张独立贴图进行了彻底排查，确认：
1. **含有 TerraUrsa 标志的机型仅有两类**：
   - `TU-22K`（22MW 海上风机，外观版与完整版）：机舱 Decal 贴花节点为 `Static:nacelle:20`（GLTFLoader 解析后名称为 `Staticnacelle20`），贴图内容为熊图标及 `TerraUrsa TU-22K`。
   - `TU-3000`（3MW 陆上风机，夏李风场同款）：机舱 Decal 贴花节点为 `Static:nacelle:10`（GLTFLoader 解析后名称为 `Staticnacelle10`），原贴图含 `XXX-3000 / TERRAURSA`。
2. **处理原则**：
   - **彻底隐藏 TerraUrsa 贴花**：将 `TU-22K` 的机舱 Decal 节点网格与材质设置为不可见与完全透明（`visible = false, opacity = 0`），露出干净整洁的机舱外壳；
   - **保全夏李官方品牌**：对夏李现场使用的 `TU-3000`，继续使用官方原件 `assets/brand/ONTOVis.png`（`2170 × 725`，严格 `2170:725` 长宽比几何对齐），正立展示「ONTOVis AI 本源数智」品牌；
   - **严格 100% 完整保留真实商业厂商**：包括 `Vestas`（维斯塔斯）、`SIEMENS Gamesa`（西门子歌美飒）、`MINGYANG`（明阳智能）、`ENERCON`（埃纳康）、`NORDEX`（恩德）等真实厂商的所有部件材质与标识严格保留，绝不误伤、绝不屏蔽。

---

## 二、实机验证证据

使用无头 Chrome + CDP 在相同光照与精确机舱观察视角下，对模型进行三维近景高分辨率渲染并截取证据：

### 1. TU-22K 超大海上风机机舱（已彻底去除 TerraUrsa 标志）
![TU-22K 机舱特写](../../output/remove-terraursa-logo-20261101/tu22k-sanitized.png)
> 机舱侧面平整洁净，原 `Static:nacelle:20` 的熊图标与 `TerraUrsa TU-22K` 贴花已被彻底隐藏，顶部的直升机停机坪与百叶窗等结构完好无损。

---

### 2. TU-3000 陆上风机机舱（夏李现场同款，官方 ONTOVis 图标正常呈现）
![TU-3000 机舱特写](../../output/remove-terraursa-logo-20261101/tu3000-ontovis-logo.png)
> 原 `XXX-3000 / TERRAURSA` 贴花已替换为官方原件 `ONTOVis.png`，严格按 `2170:725` 长宽比几何映射，双面正立清晰且无拉伸变形。

---

### 3. MySE 18.5-260 明阳智能海上风机机舱（真实商业厂商 Logo 完整保留）
![MySE 18.5-260 明阳智能机舱特写](../../output/remove-terraursa-logo-20261101/myse-mingyang-preserved.png)
> 真实厂商明阳智能的「MINGYANG」深蓝官方品牌标识 100% 完整保留在机舱侧面，顶部的维护平台与机身涂装完好无损，未受任何误伤。

---

## 三、代码与工程改动

| 文件路径 | 改动要点 |
| :--- | :--- |
| [`apps/workbench/src/sceneResourceCache.ts`](../../apps/workbench/src/sceneResourceCache.ts) | 导出 `sanitizeModelLogos`，引入名称规范化匹配（兼容原始冒号与 GLTFLoader 规范化命名），彻底隐藏 `TU-22K` 的 `Static:nacelle:20` 及任何含 `terraursa` 材质，保全 `TU-3000` 官方 Logo 与所有真实厂商 |
| [`apps/workbench/src/modelThumbnailRenderer.ts`](../../apps/workbench/src/modelThumbnailRenderer.ts) | 缩略图生成器同步实现轻量 `hideTerraUrsaLogos`，隐藏 `Static:nacelle:20` 与 `Static:nacelle:10`，零警告，产物 591KB |
| [`apps/workbench/tests/model-logo-sanitization.test.mjs`](../../apps/workbench/tests/model-logo-sanitization.test.mjs) | 新增 2 项定向测试，验证 `TU-22K`（冒号与无冒号）、自定义含 `terraursa` 贴图隐藏，以及 `Vestas` / `MingYang` 真实厂商完整保留 |
| [`output/remove-terraursa-logo-20261101/`](../../output/remove-terraursa-logo-20261101/) | 归档完整构建验证回执、CDP 测试脚本与 3 张高精度实机对比截图 |
| [`docs/plans/开发执行记录.md`](../../docs/plans/开发执行记录.md) | 追加第 177 节详细记录 |
| [`docs/plans/工作区交接.md`](../../docs/plans/工作区交接.md) | 更新置顶检查点快照 |

---

## 四、验证结果与部署状态

1. **自动化测试**：
   - 运行 `node --test tests/*.test.mjs`：全量 **662 项测试全部通过**（0 失败，0 警告）。
   - TypeScript 严格类型检查 `tsc --noEmit`：0 错误。
2. **正式构建与媒体核验**：
   - 打包构建输出至 `output/compact-workbench-20261021/workbench-dist/`，包含官方高清原件 `ONTOVis--04A_0H2.png`（640,921 字节）。
3. **生产环境部署**：
   - 生产主机：`root@192.168.2.153`
   - 发布 Release Commit：`dcfa34304899c75fe93e43ee56c4d8fa2069b183`
   - 软链 `/data/ontovis/workbench-current` 指向最新发布包
   - 服务重启并校验 `https://vis.ontobase.ai/health`，正常返回：
     ```json
     {
       "status": "ok",
       "release": "dcfa34304899c75fe93e43ee56c4d8fa2069b183",
       "frontendRelease": "dcfa34304899c75fe93e43ee56c4d8fa2069b183",
       "backendRelease": "dcfa34304899c75fe93e43ee56c4d8fa2069b183",
       "modelTerraUrsaSanitized": true
     }
     ```
4. **规范与保护文件核查**：
   - 受保护文件 `README.md` 与 `docs/references/夏李风场空间导航验证.md` 严格未予修改或暂存；
   - 官方品牌 Logo 保持原始像素与比例；
   - 所有文档、注释、代码提交与回复均使用简体中文。
