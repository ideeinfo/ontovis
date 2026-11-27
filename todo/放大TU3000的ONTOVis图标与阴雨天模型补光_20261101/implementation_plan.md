# 放大TU-3000上的ONTOVis图标与阴雨天风机模型补光 实施方案

## 1. 需求与现状分析

### 1.1 需求一：放大 TU-3000 上的 ONTOVis 图标
- **现状**：当前在 [`apps/workbench/src/sceneResourceCache.ts`](../../apps/workbench/src/sceneResourceCache.ts) 中，将官方原件 `assets/brand/ONTOVis.png`（`2170 × 725`，长宽比 `2.9931`）映射到 `TU-3000` 机舱两侧 `Static:nacelle:10`（Decal 节点）时，设定的贴花高度为 `1.0m`，宽度为 `2.9931m`。
- **机舱空间实测**：
  - `TU-3000` 机舱外壳 `Static:nacelle:0` 总高 `5.10m`（Y ∈ `[87.90, 93.00]`），侧面平整立面高度约 `3.0m`；
  - 机舱总长 `14.30m`（Z ∈ `[-8.98, 5.32]`），平整侧面贴花有效区间为 Z ∈ `[-1.75, 3.15]`，中心约在 `Z = 0.70m`；
  - 现有的 `1.0m` 高度偏保守，在远处观察或三维全览时显得尺寸偏小，用户明确提出“将TU-3000上的ontovis图标放大”。
- **目标方案**：
  - 将贴花高度由 `1.0m` 放大至 **`1.60m`**（高度放大 60%，显示面积扩大至原来的 **2.56 倍**，显著提升视觉辨识度与质感）；
  - 严格保持官方 Logo 原始像素比例 `2170 : 725`（宽 `1.60 × (2170 / 725) ≈ 4.789m`）；
  - 纵向中心对齐在 `yCenter = 90.95m`（Y ∈ `[90.15, 91.75]`），前后中心对准机舱平整侧面中轴 `zCenter = 0.70m`（Z ∈ `[-1.6945, 3.0945]`），完全处于原贴花平整立面范围内，杜绝边缘悬空、拉伸或穿模。

---

### 1.2 需求二：阴雨环境下风机模型太过灰暗，需要补光
- **暗淡根因排查**：
  1. [`apps/workbench/src/weatherEnvironment.ts`](../../apps/workbench/src/weatherEnvironment.ts)（实际预报天气）：
     - 当检测到阴雨/浓云（`overcast: rain, snow, sleet, fog`）时，`result.lighting.sun.enabled = !night && !overcast` 直接将主平行光切断为 `false`（`sun.intensity = 0`），风机模型彻底丧失主光源与法线明暗层次；
     - 同时 `result.lighting.hemisphereIntensity = overcast ? .7 : 1` 反向将半球光压制到极低的 `0.7`；
     - 环境贴图反射强度 `environment.intensity = overcast ? .55 : .8` 降至 `0.55`；
  2. [`apps/workbench/src/cockpitDisplayState.ts`](../../apps/workbench/src/cockpitDisplayState.ts)（驾驶舱天气演示模式）：
     - 在选择 `rain` / `snow` / `fog` 时，`value.lighting.sun.enabled = weather === 'clear' || weather === 'cloud'` 同样切断了太阳光，未提供漫射天光；
  3. [`apps/workbench/src/sceneEnvironmentRuntime.ts`](../../apps/workbench/src/sceneEnvironmentRuntime.ts)（运行时光照管道）：
     - 辅助补光灯 `this.fill` 仅在 `night` 为 true 时激活（强度 `1.4`），在白天阴雨环境下强度为 `0`。
- **补光方案设计**：
  1. **保留并优化阴雨天主漫射光（Soft Skylight Directional Light）**：
     - 阴雨天不切断主光源（`sun.enabled = !night`）；
     - 将强烈的晴天直射阳光调整为漫射天光：强度设为 `1.15`，颜色调整为柔和高漫射冷白 `#dce6f2`，既保留风机塔筒与叶片的几何轮廓与立体感，又避免晴天刺眼高光；
  2. **大幅增强半球天光散射（HemisphereLight）**：
     - 阴雨天以天空散射为主要照明，将 `hemisphereIntensity` 从原本过低的 `0.7` 显著提升至 **`1.65`**；
     - 天光色彩提升为明亮散射灰白（`0xe8eef5`），地面反射光设为中性灰（`0x6e7882`），确保风机下表面与背光面不出现死黑；
  3. **增强环境贴图反射（Environment Intensity）**：
     - 阴雨天将 `environment.intensity` 从 `0.55` 提升至 **`1.00`**，使风机表面的白色防腐漆和金属机舱反射出明朗的天空漫反射光；
  4. **激活阴雨天侧向辅助补光（Fill Light）**：
     - 在 `sceneEnvironmentRuntime.ts` 中，检测到阴雨环境（`overcast` 且非夜间）时，将辅助补光灯 `this.fill` 强度设为 **`0.85`**（色温冷白），从侧上方对机舱侧面与背风叶片进行柔和补光，彻底驱散灰暗发乌感。

---

## 2. 涉及文件与修改清单

| 序号 | 文件路径 | 变更目的与核心修改 |
| :--- | :--- | :--- |
| 1 | [`apps/workbench/src/sceneResourceCache.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneResourceCache.ts) | 将 `TU-3000` 的 ONTOVis 图标高度从 `1.0m` 放大至 `1.60m`，宽度按 `2170:725` 自适应为 `4.789m`，前后中心对准 `Z = 0.70m` |
| 2 | [`apps/workbench/src/weatherEnvironment.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/weatherEnvironment.ts) | 阴雨天（overcast）保留散射天光主光（`sun.intensity = 1.15`，`color = '#dce6f2'`），提升半球光（`1.65`）与环境光反射（`1.00`） |
| 3 | [`apps/workbench/src/cockpitDisplayState.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitDisplayState.ts) | 驾驶舱天气演示模式在 `rain` / `snow` / `fog` 下同步配置漫射主光与高亮度半球补光，避免切到雨雪天时风机发黑 |
| 4 | [`apps/workbench/src/sceneEnvironmentRuntime.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneEnvironmentRuntime.ts) | 在阴雨天（overcast）且非夜间时激活侧向补光灯 `this.fill.intensity = 0.85`，彻底消除机身背光面沉闷阴影 |
| 5 | [`apps/workbench/tests/scene-resource-cache.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/scene-resource-cache.test.mjs) | 更新并强化 `TU-3000` 放大后顶点坐标（Y ∈ `[90.15, 91.75]`，Z ∈ `[-1.6945, 3.0945]`）及比例测试断言 |
| 6 | [`apps/workbench/tests/weather-lighting.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/weather-lighting.test.mjs) | 新增/更新天气环境光照单元测试，验证阴雨天主光、半球光与补光灯参数 |

---

## 3. 验证与验收计划

1. **自动化测试**：
   - 运行前端单元测试：`cd apps/workbench && node --test tests/*.test.mjs`，确保 660+ 项测试全绿；
   - 运行类型检查：`npm --prefix apps/workbench run build` 确保 TypeScript 0 错误；
   - 运行整机打包：`python3 tools/build_workbench.py` 确保打包与媒体校验无误。
2. **生产环境部署**：
   - 同步构建产物至远端服务器 `192.168.2.153`；
   - 重启服务并校验 `https://vis.ontobase.ai/health`。
3. **CDP 实机渲染截图核验**：
   - **截图 1（放大版 ONTOVis 图标）**：TU-3000 机舱正侧面高清特写，确认图标显著放大为原面积的 2.56 倍，居中整齐、比例保真、视觉霸气；
   - **截图 2（阴雨天补光效果）**：在平顶山夏李风场或阴雨天气环境下截取风机模型，对比验证补光后风机机舱、塔筒与叶片通透立体、白净明亮，彻底消除死黑与灰暗；
   - **截图 3（晴天与真实厂商保持）**：确认晴天模式与真实商业机型（MingYang/Vestas）不受任何异常影响。
4. **交接文档与备份**：
   - 更新 `docs/plans/开发执行记录.md` 与 `docs/plans/工作区交接.md`；
   - 生成 `walkthrough.md` 并备份至 `todo/放大TU3000的ONTOVis图标与阴雨天模型补光_20261101/walkthrough.md`。

---

## 4. 遵守约束

- 严格使用 UTF-8 编码读取与写入；
- 严禁修改、暂存、提交或回退受保护文件 `README.md` 与 `docs/references/夏李风场空间导航验证.md`；
- 所有回复、思考过程、注释与文档统一使用简体中文；
- **本方案在获得用户显式审核批准前，绝不擅自执行任何代码变更**。
