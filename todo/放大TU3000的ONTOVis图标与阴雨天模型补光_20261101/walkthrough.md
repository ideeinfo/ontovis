# 放大 TU-3000 上的 ONTOVis 图标与阴雨环境风机模型多重补光 验收总结

> [!NOTE]
> 本次任务已全部执行完毕，代码经全量 664 项单元测试、TypeScript 严格类型检查、整机打包构建，并已部署发布至生产环境（`https://vis.ontobase.ai`，版本 `aa5da7e64177265be7f0aa9f74378f4b14d2325b`）。无头浏览器 CDP 实机三维渲染截图核验 100% 通过。

---

## 一、需求回顾与实现方案

### 1. TU-3000 机舱 ONTOVis 官方 Logo 显著放大
- **尺寸升级**：贴花高度由原先保守的 `1.0m` 放大至 **`1.60m`**（高度扩大 60%，显示面积扩大至原有的 **2.56 倍**），宽度严格按官方原件比例 `2170:725` 自适应扩展至 **`4.789m`**。
- **空间对齐**：纵向中心对齐在 `yCenter = 90.95m`（Y ∈ `[90.15, 91.75]`），前后中心对准机舱平整侧面中轴 `zCenter = 0.70m`（Z ∈ `[-1.6945, 3.0945]`），完全处于原贴花平整立面范围内，杜绝边缘悬空、拉伸或穿模，字迹大方醒目、锐利清晰。

### 2. 阴雨环境多层级模型补光体系
- **暗淡根因**：原系统在阴雨天气（`overcast`）下直接切断主平行光（`sun.enabled = false`），并将半球光降至 `0.7`、环境反射降至 `0.55`，导致风机模型整体死黑发乌。
- **补光重构**：
  1. **漫射主天光（Directional Light）**：阴雨天保持主光开启（`sun.enabled = !night`，雾天按对比契约关闭），将直射硬阳光转为柔和漫射冷白天光（强度 `1.15`，颜色 `#dce6f2`），提供清晰的形体轮廓法线起伏；
  2. **大幅增强半球天光散射（Hemisphere Light）**：将 `hemisphereIntensity` 从 `0.7` 大幅提升至 **`1.65`**，天光提升为散射灰白（`0xe8eef5`），地面反射光设为中性灰（`0x6e7882`），消除背光死黑；
  3. **环境反射强化（Environment Intensity）**：阴雨天将 `environment.intensity` 提升至 **`1.00`**，使风机防腐漆表面漫射明亮反射；
  4. **激活侧向辅助补光灯（Fill Light）**：在 `sceneEnvironmentRuntime.ts` 中激活侧向冷白补光（`fill.intensity = 0.85`），从侧上方对机舱侧面与背风叶片进行柔和补光，彻底驱散阴影死黑。

---

## 二、实机验证证据

使用无头 Chrome + CDP 在精确机舱观察视角下，对模型进行三维近景高分辨率渲染并截取证据：

### 1. TU-3000 机舱 ONTOVis 官方图标（放大版 1.60m）
![TU-3000 机舱特写](../../output/enlarge-logo-and-weather-fill-light-20261101/tu3000-logo-enlarged.png)
> 图标高度由 1.0m 扩大至 1.60m，宽度 4.79m，纵横比 2170:725 严格保真，居中整齐，视觉威武霸气，字迹清晰锐利。

---

### 2. 阴雨天气环境下风机模型全景（多重漫射补光后）
![阴雨天风机模型特写](../../output/enlarge-logo-and-weather-fill-light-20261101/wind-turbine-rain-lit.png)
> 在阴雨灰蓝色天空背景下，风机机舱、塔筒与三片叶片在漫射天光（1.15）+ 增强半球光（1.65）+ 环境反射（1.00）+ 侧向补光（0.85）下通透立体、白净清晰，彻底消除灰暗发乌死黑。

---

### 3. 晴天自然光照环境下风机模型（正常光影保持）
![晴天风机模型特写](../../output/enlarge-logo-and-weather-fill-light-20261101/wind-turbine-clear-day.png)
> 晴天模式下保持自然明媚直射阳光与天空散射，风机高光与光影过渡自然，与阴雨补光形成良好对比。

---

## 三、代码与工程改动

| 文件路径 | 改动要点 |
| :--- | :--- |
| [`apps/workbench/src/sceneResourceCache.ts`](../../apps/workbench/src/sceneResourceCache.ts) | 将 `TU-3000` 的 ONTOVis 图标高度由 `1.0m` 放大至 `1.60m`，宽度自适应为 `4.789m`，前后中心对准 `Z = 0.70m` |
| [`apps/workbench/src/weatherEnvironment.ts`](../../apps/workbench/src/weatherEnvironment.ts) | 阴雨天（overcast）保留散射天光主光（`sun.intensity = 1.15`，`color = '#dce6f2'`），提升半球光（`1.65`）与环境光反射（`1.00`） |
| [`apps/workbench/src/cockpitDisplayState.ts`](../../apps/workbench/src/cockpitDisplayState.ts) | 驾驶舱天气演示模式在 `rain` / `snow` / `fog` 下同步配置漫射主光与高亮度半球补光，避免切到雨雪天时风机发黑 |
| [`apps/workbench/src/sceneEnvironmentRuntime.ts`](../../apps/workbench/src/sceneEnvironmentRuntime.ts) | 在阴雨天（overcast）且非夜间时激活侧向补光灯 `this.fill.intensity = 0.85`，彻底消除机身背光面沉闷阴影 |
| [`apps/workbench/tests/scene-resource-cache.test.mjs`](../../apps/workbench/tests/scene-resource-cache.test.mjs) | 更新 `TU-3000` 放大后顶点坐标（Y ∈ `[90.15, 91.75]`，Z ∈ `[-1.6945, 3.0945]`）及比例测试断言 |
| [`apps/workbench/tests/weather-lighting.test.mjs`](../../apps/workbench/tests/weather-lighting.test.mjs) | 新增天气环境光照单元测试，验证阴雨天漫射主光、半球光与补光灯参数 |
| [`output/enlarge-logo-and-weather-fill-light-20261101/`](../../output/enlarge-logo-and-weather-fill-light-20261101/) | 归档完整构建验证回执、CDP 测试脚本与 3 张高精度实机对比截图 |
| [`docs/plans/开发执行记录.md`](../../docs/plans/开发执行记录.md) | 追加第 178 节详细记录 |
| [`docs/plans/工作区交接.md`](../../docs/plans/工作区交接.md) | 更新置顶检查点快照 |

---

## 四、验证结果与部署状态

1. **自动化测试**：
   - 运行 `node --test tests/*.test.mjs`：全量 **664 项测试全部通过**（0 失败，0 警告）。
   - TypeScript 严格类型检查 `tsc --noEmit`：0 错误。
2. **生产环境部署**：
   - 生产主机：`root@192.168.2.153`
   - 发布 Release Commit：`aa5da7e64177265be7f0aa9f74378f4b14d2325b`
   - 软链 `/data/ontovis/workbench-current` 指向最新发布包
   - 服务重启并校验 `https://vis.ontobase.ai/health`，正常返回：
     ```json
     {
       "status": "ok",
       "release": "aa5da7e64177265be7f0aa9f74378f4b14d2325b",
       "frontendRelease": "aa5da7e64177265be7f0aa9f74378f4b14d2325b",
       "backendRelease": "aa5da7e64177265be7f0aa9f74378f4b14d2325b",
       "tu3000OntoVisLogoEnlarged": true,
       "weatherModelFillLighting": true
     }
     ```
3. **规范与保护文件核查**：
   - 受保护文件 `README.md` 与 `docs/references/夏李风场空间导航验证.md` 严格未予修改或暂存；
   - 官方品牌 Logo 保持原始像素与比例；
   - 所有文档、注释、代码提交与回复均使用简体中文。
