# 场景列表卡片化与缩略图重设计实施方案

## 1. 背景与目标

用户需求：
> “参考 https://demo.twinsight.cn/facilities 的布局重新设计场景列表，需要显示场景缩略图”

参考页面（用户截图 `media_1794124055593_3d330b1a.jpg`）为“标题区 + 左侧卡片列表 + 右侧当前对象详情”的双栏布局：
- 顶部：页面标题、一句说明、右上角主操作“新建”；
- 左栏：搜索框 + 卡片/列表视图切换；每张卡片左侧为名称、标识徽标、状态、一行说明与三项统计，右侧为缩略图，右上角“⋯”更多菜单；选中卡片高亮描边；
- 右栏：当前选中对象的标题、状态、统计块和主操作（打开工作台、编辑信息）。

**改造对象**：工作台“场景管理”的场景列表（[`SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx) 中 `!base` 分支，当前为 `ov-list-table` 纯表格，无缩略图）。

**范围边界**：
- 仅改前端列表展示，不改后端接口、不新增字段。只展示列表接口已有数据：`displayName`、`instanceCount`、`updatedAt`/`deletedAt`、`thumbnail`、`state`。
- 参考页中的“资产/空间/IoT、知识库、文档档案”等板块在场景摘要中无对应真实数据，**不照搬、不编造**；右栏只显示真实字段。
- 场景编辑器（打开场景后的三栏界面）不改。

---

## 2. 设计方案

### 2.1 页面结构
```
┌ 标题区：场景管理 / 说明一句 ─────────────── [回收站] [+ 新建场景] ┐
├ 左栏（列表） ─────────────────────────┬ 右栏（当前场景） ──────────┤
│ [搜索场景……] [搜索]      [卡片|列表]  │ 大缩略图                     │
│ ┌──────────────────────────┐          │ 场景名称                     │
│ │ 名称  [ID短码]       ⋯   │ [缩略图] │ 实例数 · 更新时间            │
│ │ 实例 12 · 更新 2026-11-08│          │ [打开场景] [基本信息]        │
│ └──────────────────────────┘          │ [移至回收站]（有权限时）     │
│ ……                                    │                              │
│ [加载更多]                            │                              │
└───────────────────────────────────────┴──────────────────────────────┘
```

### 2.2 卡片（默认视图）
- 左侧：场景名称（允许两行换行）、场景 ID 前 8 位徽标（`title` 显示完整 ID）、统计行（实例数、更新时间；回收站模式显示删除时间）。
- 右侧：16:9 缩略图，复用现有 [`SceneThumbnail`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneThumbnail.tsx)（已有鉴权读取、缓存键与 `objectURL` 回收）；无缩略图或读取失败时显示 `Layers` 图标占位，并标注“未设置缩略图”。
- 右上角“⋯”：复用现有 `RowActions`，菜单项与现在一致（打开 / 基本信息 / 移至回收站；回收站模式为恢复）；右键菜单继续用 `RowContext`。
- 交互：单击卡片 = 选中并在右栏显示详情；双击卡片或点“打开场景” = 打开；键盘 Enter 打开、方向键可在卡片间移动焦点（卡片为 `button`/`role=option` 语义，保留可访问性）。
- 选中态：主色描边 + 浅色底，与驾驶舱选中风格一致。

### 2.3 列表视图
- 保留当前表格（`ov-list-table`），首列增加 48×27 小缩略图；视图偏好存 `localStorage`（`ontovis.scenes.list_view`）。

### 2.4 右栏详情
- 选中场景的大缩略图、名称、实例数、更新时间、完整场景 ID（可复制选择）；
- 主操作“打开场景”，次操作“基本信息”（复用现有 `setInfoTarget` 弹窗）、“移至回收站”（复用现有删除确认，受 `canWrite` 与 `sceneLifecycleWriteVersion` 控制，前端禁用仅为体验，后端权限不变）；
- 默认选中列表第一项；列表为空时右栏显示空状态与“新建场景”。
- 窄屏（< 1000px）右栏隐藏，卡片单击直接打开；< 600px 卡片缩略图移到上方。

### 2.5 样式
- 新增样式写入 [`scenes.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/scenes.css)，使用现有设计 token（`--surface`、`--surfaceRaised`、`--borderSubtle`、`--primary`、`--selected`、`--textSecondary`），深浅主题自动适配；正文 13px、说明 11px。
- 组件全部复用现有 `Btn`、`IconBtn`、`RowActions`、`RowContext`、`SceneThumbnail`，不引入新依赖。

> [!NOTE]
> 规则中“前端尽量使用 Element Plus”不适用：本项目工作台为 React，沿用仓库已有的共享控件（`Primitives`、`ListMenus`）。
>
> AGENTS.md 规定管理工作台的活动设计源为 MagicPath。本次按参考站直接在代码中改版，**不同步修改 MagicPath 项目**；如需先在 MagicPath 出稿再实现，请告知。

---

## 3. 修改文件清单

| 文件 | 修改 |
| :--- | :--- |
| `apps/workbench/src/SceneWorkspace.tsx` | `!base` 分支重写为标题区 + 双栏；新增 `listView`、`selectedSceneId` 状态；卡片与右栏渲染；表格首列加缩略图 |
| `apps/workbench/src/scenes.css` | 新增 `.sw-scene-page`、`.sw-scene-cards`、`.sw-scene-card`、`.sw-scene-detail` 等样式与响应式规则 |
| `apps/workbench/src/sceneI18n`（或现有文案表） | 新增中英文文案：页面说明、卡片/列表、未设置缩略图、当前场景等 |
| `apps/workbench/tests/` | 新增/补充测试：卡片渲染缩略图与占位、回收站模式操作、视图切换持久化 |

---

## 4. 验证与部署
1. `npm --prefix apps/workbench run check`（类型、单测、构建）。
2. 本机浏览器检查：深/浅主题、中/英文、1600/1000/390px；有/无缩略图；回收站模式；加载更多；键盘操作。截图存 `output/scene-list-redesign-20261108/`。
3. 提交推送 `codex/design-foundation`，部署 `https://vis.ontobase.ai`，`walkthrough.md` 备份到本目录。
