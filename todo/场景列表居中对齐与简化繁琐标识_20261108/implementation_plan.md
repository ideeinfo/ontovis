# 场景列表居中对齐与简化繁琐标识实施计划

根据用户反馈与红圈标注截图（`media_1794146737313_28dfad4c.jpg`）：
1. 列表布局整体居中对齐，解决大屏下靠左留白不均的问题；
2. 彻底清理界面中繁琐生硬的编码标识符（如 `SCN-XXXX`、底层场景 UUID）与底层 revision 串（如 `scene:<revision-id>`），恢复清爽整洁的工程业务展示。

---

## 1. 变更范围与设计方案

### 1.1 列表布局居中对齐
- **`.sw-hub-header` 头部居中对齐**：
  在头部增加内层最大宽度约束容器 `.sw-hub-header-inner`（`max-width: 1440px; margin: 0 auto; width: 100%;`），使主标题、描述与右侧操作按钮与下方列表网格的左右边界严格垂直对齐；
- **`.sw-hub-grid` 双栏网格居中**：
  为 `.sw-hub-grid` 增加 `margin: 0 auto;`，确保在大屏或宽屏下左右对称居中，视觉更加均衡；
- **`.sw-empty-box` 空状态居中**：
  空状态同样保持 `max-width: 1440px; margin: 0 auto;`。

### 1.2 彻底清理繁琐编码与版本号标识
- **移除 `SCN-XXXX` 编码胶囊**：
  - 场景卡片标题旁移除 `SCN-XXXX`；
  - 表格视图中移除 `SCN-XXXX`；
  - 右侧详情面板胶囊标签中移除 `SCN-XXXX`；
  - 右侧缩略图标题栏右侧移除 `SCN-XXXX`；
- **移除底层版本 UUID（`scene:<revision-id>`）**：
  - **场景卡片底部指标**：由原先挤占中间的三列指标精简为两列清晰指标（「模型数」与「保存/删除时间」），排版更舒展通透；
  - **缩略图右下角角标**：移除覆盖在缩略图右下角的长版本串角标，还原完整纯净的场景缩略图视野；
  - **右侧详情胶囊标签**：移除底层 revision UUID 胶囊，仅保留「X 模型数」与「启用中 / 回收站」；
  - **右侧统计指标网格**：移除展示长 UUID 的「当前版本」卡片，调整为清晰的两列核心指标卡（「模型数」与「保存/删除时间」）；
  - **右侧场景元数据卡片**：移除底层的「场景标识（UUID）」字段，仅保留「所属项目」与「保存/删除时间」。

---

## 2. 涉及文件与改动清单

| 文件 | 变更说明 |
| :--- | :--- |
| [`apps/workbench/src/SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx) | 1. 移除 `sceneShortCode` 函数及卡片、表格、详情面板、缩略图等所有位置的短码展示；<br>2. 移除卡片底部、缩略图角标、详情胶囊、指标卡中的 `headRevision` 渲染；<br>3. 移除详情元数据卡片中的底层 `sceneId` 行；<br>4. 在头部包裹 `.sw-hub-header-inner` 容器保证垂直对齐。 |
| [`apps/workbench/src/scenes.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/scenes.css) | 1. `.sw-hub-grid` 和 `.sw-hub-header-inner` 设置 `margin: 0 auto; max-width: 1440px;` 居中对齐；<br>2. 卡片指标行 `.sw-facility-card-metrics` 适配双列指标；<br>3. 右侧指标卡网格 `.sw-hub-stat-grid` 适配双列指标；<br>4. 清理冗余的 `.sw-facility-thumb-badge`、`.sw-facility-code` 样式。 |
| [`apps/workbench/tests/scene-workspace-list.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/scene-workspace-list.test.mjs) | 更新单测断言，确保居中样式、移除冗余编码与版本号的行为受测试严格约束。 |

---

## 3. 验证与上线计划

1. 运行 `npm --prefix apps/workbench run check`，验证全量单测、类型检查与生产打包；
2. 提交代码至 git 并推送远端分支 `codex/design-foundation`；
3. 部署到测试服务器 `/data/ontovis/workbench-releases/<commit>` 并重启服务；
4. 验证公网 `https://vis.ontobase.ai` 实际界面效果；
5. 生成任务报告并备份至 `todo/场景列表居中对齐与简化繁琐标识_20261108/walkthrough.md`。
