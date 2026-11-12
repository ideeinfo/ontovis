# 场景列表卡片化与缩略图重设计完成报告

## 1. 任务概述

用户需求：
> “参考 https://demo.twinsight.cn/facilities 的布局重新设计场景列表，需要显示场景缩略图”
> “先在 MagicPath 出设计稿，确认后再实施。”
> 用户随后于设计稿审阅后批准：“确认实施”。

本次任务已彻底完成：
1. **MagicPath 同源设计稿出具与用户确认**：
   在 MagicPath 管理工作台组件（`463127544821075968`，承接修订 `468579511345225728`）同源源码中完成了深色、浅色、选景联动、卡片/列表视图切换全套设计稿，并在实机截屏获得用户明确批准确认；
2. **正式工作台代码实施**：
   在正式工作台 [`apps/workbench/src/SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx) 和 [`apps/workbench/src/scenes.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/scenes.css) 中实现双栏卡片化 + 16:9 场景缩略图 + 右侧当前场景详情面板 + 视图切换；
3. **自动化测试与全量回归**：
   新增单测 [`apps/workbench/tests/scene-workspace-list.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/scene-workspace-list.test.mjs)，全量 **780 项单元测试 100% 全部通过**，类型检查 0 error，Vite 打包通过；
4. **提交推送与测试服务器上线**：
   代码已提交至 Git 分支 `codex/design-foundation`（Commit `a689560`），推送到 GitHub，并部署到公网服务器 `/data/ontovis/workbench-releases/a689560b866c80a42b8052529bc6676413c0a6fe`，公网 `https://vis.ontobase.ai` 运行正常。

---

## 2. 界面布局与交互要点

### 2.1 顶部标题与操作栏（`.sw-hub-header`）
- **左侧标题块**：主标题「场景组合」（回收站模式下为「场景回收站」），搭配简明工程职责说明文案；
- **右侧动作组**：
  - 「回收站 / 返回场景列表」切换按钮；
  - 「`+ 创建场景`」主按钮（点击呼出已有新建场景弹窗）。

### 2.2 左侧主面板（`.sw-hub-list-panel`）
- **搜索与视图切换（`.sw-hub-list-bar`）**：
  - 搜索输入表单：支持输入关键字即时过滤并回车快速查询；
  - 视图切换按钮组（`.sw-view-switch`）：卡片视图（`LayoutGrid` 图标）与列表视图（`List` 图标）一键切换；
- **场景卡片（`.sw-facility-card`）**：
  - 选中高亮边框与光影立体感（`.is-selected`）；
  - **左侧内容区**：
    - 场景标题（点击或双击卡片直接进入场景三维工作台）；
    - `SCN-XXXX` 短码徽标（由 `sceneId` 提取规范前缀和十六进制/字母短码）；
    - 状态徽标（`启用中` / `回收站`）；
    - 右上角 `⋯` 更多操作菜单（`RowActions`：打开工作台、基本信息、移至回收站 / 恢复）；
    - 场景范围与用途说明；
    - 底部三列关键指标：模型实例数、版本标识（`v{headRevision}`）、最近保存/删除时间；
  - **右侧 16:9 场景缩略图（`.sw-facility-card-thumb`）**：
    - 调用 `<SceneThumbnail>` 组件，无缝渲染场景真实截图；
    - 当场景未上传截图时，由内嵌的 `<ScenePlaceholderThumb>` 提供自适应的高清工程三维矢量剪影（区分变电站设备与风电机组群）；
    - 右下角叠加毛玻璃版本标识角标（`.sw-facility-thumb-badge`）；
- **表格视图兼容（`.sw-table-wrap`）**：
  - 点击列表切换为精简表格视图，首列带有紧凑缩略图与短码，行点击同样支持联动右侧面板。

### 2.3 右侧当前场景详情面板（`.sw-hub-detail-panel`）
- **实时选景联动**：点击左侧任意卡片或表格行，右侧详情面板平滑切换当前选中项；
- **头部信息**：呈现场景大标题与状态标签；
- **核心操作区（`.sw-hub-primary-actions`）**：
  - 正常模式：`打开工作台`（主按钮）+ `基本信息`（次按钮，点击直接编辑名称与描述）；
  - 回收站模式：`恢复场景` 按钮；
- **统计指标网格（`.sw-hub-stat-grid`）**：三宫格卡片呈现场景包含模型数、当前版本号、最近保存时间；
- **大图缩略图预览卡片（`.sw-hub-preview-card`）**：大尺寸呈现场景截图或空间基准预览，附带更新日期；
- **场景元数据摘要卡片（`.sw-hub-section-card`）**：展示所属项目、场景完整唯一标识、更新时间等真实工程字段。

---

## 3. 代码变更清单

| 文件路径 | 变更说明 |
| :--- | :--- |
| [`apps/workbench/src/SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx) | 1. 引入 `SceneThumbnail`、`LayoutGrid`、`List`；<br>2. 增加 `listMode`（卡片/列表模式切换）与 `selectedSceneId` 联动状态；<br>3. 增加 `ScenePlaceholderThumb` 智能矢量缩略图与 `sceneShortCode` 短码格式化函数；<br>4. 重构 `!base` 分支为双栏卡片化布局（左栏卡片流 + 右栏当前场景详情面板），同时支持表格视图与分页加载。 |
| [`apps/workbench/src/scenes.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/scenes.css) | 增加 `.sw-hub-*` 和 `.sw-facility-*` 完整样式定义（涵盖标题栏、网格流、16:9 缩略图、选中态高亮边框、指标卡、大图预览卡以及移动端自适应响应式断点）。 |
| [`apps/workbench/tests/scene-workspace-list.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/scene-workspace-list.test.mjs) | 新增场景列表布局结构、16:9 缩略图、短码生成、视图切换与详情面板联动的单元测试。 |
| [`output/scene-list-redesign-20261108/README.md`](file:///Users/diwei/项目2026/OntoVis/output/scene-list-redesign-20261108/README.md) | 记录本次任务设计、验证过程与部署版本说明。 |

---

## 4. 自动化测试与上线验证

1. **类型检查与单元测试**：
   - 运行 `npm --prefix apps/workbench run check`；
   - 全量 **780 项单元测试 100% 全部通过**；
   - TypeScript 类型检查 0 报错，Vite 编译打包顺利完成。
2. **Git 提交与远端推送**：
   - Commit: `a689560` (`feat(scene): 参考TwinSight设施布局重构场景列表为双栏卡片化与16:9缩略图`)；
   - 已成功推送到 GitHub 远端分支 `origin codex/design-foundation`。
3. **测试服务器部署**：
   - 目标主机：`192.168.2.153` (`root@192.168.2.153`)；
   - 部署路径：`/data/ontovis/workbench-releases/a689560b866c80a42b8052529bc6676413c0a6fe/`；
   - 软链接原子切换并平滑重启 `workbench-instance.service`，进程状态 `active (running)`；
   - 外部访问验证：`curl -fsSI https://vis.ontobase.ai` 响应 `HTTP/2 200`，静态资源已全部生效上线。
