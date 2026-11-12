# 场景列表居中对齐与简化繁琐标识 验收说明

## 任务背景与目标
针对场景组合列表页在大屏展示及用户实际体验中反馈的两个痛点问题进行了针对性重构：
1. **居中对齐**：宽屏下列表头部与双栏内容居中对齐，消除左偏与右侧留白不协调感；
2. **去除繁琐标识**：彻底清理用户圈出的 `SCN-XXXX` 短码徽标、`vscene:xxxx` 完整长 UUID 版本号、缩略图版本角标及场景标识 UUID，使信息层次更加聚焦、清爽专业。

---

## 变更明细与效果对比

| 区域 / 元素 | 修改前状态 | 修改后优化效果 |
| :--- | :--- | :--- |
| **页面头部容器** (`.sw-hub-header`) | 宽度 100% 紧贴左侧，大屏下与列表内容视觉偏离 | 内部包裹 `.sw-hub-header-inner`，与内容区统一设置 `max-width: 1440px; margin: 0 auto;` 严格居中对齐 |
| **卡片标题栏** (`.sw-facility-card-head`) | 标题右侧带有 `SCN-XXXX` 短码徽标 | 彻底移除短码徽标，保留清晰的场景名称与状态标签（启用中/回收站） |
| **卡片指标区** (`.sw-facility-card-metrics`) | 3 列网格，中间显示折行的内部长 UUID（`vscene:f99d59ae...`） | 移除冗余版本列，精简为干净对称的 2 列网格：**模型数** 与 **保存/删除时间** |
| **卡片缩略图** (`.sw-facility-card-thumb`) | 右下角浮动显示半透明 `vscene:...` 角标 | 移除角标覆盖层，缩略图完整无遮挡展示 |
| **列表视图模式** (`ov-list-table`) | 场景名称右侧带有 `SCN-XXXX` 短码徽标 | 移除短码，保持表格行高度与对齐整洁 |
| **右侧详情胶囊** (`.sw-hub-pills`) | 包含 `vscene:...` 长版本胶囊与 `SCN-XXXX` 短码胶囊 | 优化为 **模型数** 与 **三维空间场景** 属性胶囊，消除长字符串溢出 |
| **右侧统计三宫格** (`.sw-hub-stat-grid`) | 3 列卡片，中间卡片显示长版本 UUID 造成文字拥挤 | 调整为对称双列卡片（**模型数**、**更新/删除时间**），视觉呼吸感显著提升 |
| **右侧缩略图标题头** | 缩略图标题右侧附带 `SCN-XXXX` 标签 | 移除短码，保持纯粹模块标题 |
| **右侧场景元数据** (`.sw-instance-facts`) | 显示工程内部长 UUID `Scene ID / 场景标识` | 移除无业务意义的 UUID 字段，仅展示 **所属项目** 与 **保存/更新时间** |

---

## 验证与测试结果

1. **前端类型与单测全量验证**：
   - 运行 `npm --prefix apps/workbench run check`：
     - TypeScript 校验 0 错误（`tsc --noEmit` 通过）；
     - 单测套件全部通过（包含 `scene-workspace-list.test.mjs` 中对居中容器、2 列指标网格、无 SCN 短码与无冗余徽标的断言测试）；
     - 生产环境打包正常生成。
2. **Git 提交与推送**：
   - Commit: `be30754` (`fix(workbench): 场景列表布局居中对齐并移除繁琐编码与版本标识`)；
   - 远程分支 `origin/codex/design-foundation` 已完成同步推送。
3. **测试服务器部署验证**：
   - 服务器：`192.168.2.153`
   - Release 目录：`/data/ontovis/workbench-releases/be307549b9c0e5ffadd6005000ba63dddcf5ae1d`
   - 服务链接：`/data/ontovis/workbench-current`
   - 运行状态：`workbench-instance` 服务重启成功，状态为 `active`；
   - 公网验证：`curl -fsSI https://vis.ontobase.ai` 响应 HTTP 200，Last-Modified 为最新构建时间。
