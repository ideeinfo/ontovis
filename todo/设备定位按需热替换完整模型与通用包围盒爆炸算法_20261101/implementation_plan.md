# 场景绑定OntoBase项目型号、模型上传管理重构与按需热替换通用爆炸算法 实施方案

## 1. 需求与核心原则确认

### 1.1 核心原则与决策（采纳方案 A）
1. **ONTOVis 场景与 OntoBase 项目强绑定**：
   - 所有场景均隶属于 OntoBase 项目（当前为 `Demo-PDS`），新建场景与工作台驾驶舱均以项目为主上下文；
   - 坚决避免松耦合带来的全局破坏性影响，保持系统的工程一致性与权威边界；
2. **型号直接从 OntoBase 项目读取**：
   - 彻底废除“只按模型文件名字符串配对”的脆弱方式；
   - 型号（Turbine Model）作为一等公民实体，直接来源于 OntoBase 项目下的风机工程定义（`object_scope = 'definition'`, `entity_type = 'turbine'`）；
3. **为现有场景在 `Demo-PDS` 项目中补齐型号主数据**：
   - 目前 `Demo-PDS` 下仅存在 `TU-3000 风机工程定义`；
   - 本方案将在 `Demo-PDS` 项目下，为其余场景所使用的风电机型（如 Vestas V105-3450、GE 3.2-103、Siemens SWT 2.3-82、Nordex N80-2500、GE Haliade-X 14MW、Siemens SG 8.0-167、Siemens SWT 2.3-93、MySE 18.5-260 等）全量补齐定义对象与规格参数；
4. **场景编辑器布置操作根本升级**：
   - 场景编辑器布置风机时，由原来的“选择具体模型文件”彻底升级为**“选择项目型号”**；
   - 场景实例记录其型号身份，系统底层自动分级加载：大场景全览默认使用该型号的【外观版】几何；
5. **设备特写即时热替换完整模型与通用包围盒爆炸/透视**：
   - 选中某台风机进入设备页或从报警定位飞入时，系统根据型号即时热替换为对应的【完整版】模型；
   - 结合仿 Autodesk Forge 的通用包围盒径向发散算法，彻底摆脱单一机型硬编码，全机型通用支持透视与爆炸。

---

## 2. 总体架构与数据流转

```
┌────────────────────────────────────────────────────────────────────────┐
│               OntoBase 权威项目主数据 (Project: Demo-PDS)               │
│  · 风机工程定义 (entity_type='turbine', object_scope='definition')        │
│    ├── TU-3000 (夏李风场)                                              │
│    ├── Vestas V105-3.45MW (Beck Burn)                                  │
│    ├── GE Haliade-X 14MW (Dogger Bank)                                 │
│    ├── Siemens SG 8.0-167 (Hornsea 2)                                  │
│    ├── 明阳智能 MySE 18.5-260 (海上风电·MySE)                          │
│    └── 其他主流机型工程定义 (GE 3.2, Nordex N80, SWT 2.3-82/93 等)      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 1. 同步 / 读取型号主数据
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             ONTOVis 模型库管理 (Model Library & Upload)                │
│  · 上传新模型时强制规范：                                              │
│    1. 必须选择所属项目型号 (来自 OntoBase 项目定义)                      │
│    2. 必须明确应用类型：【外观版 (appearance)】 或 【完整版 (detailed)】 │
│  · 底层基于 (definition_entity_uid, representation_type) 严格外键关联   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 2. 布置时展示型号清单
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             场景编辑器风机布置 (Scene Workspace Placement)              │
│  · 用户在左侧面板直接【选择风机型号】 (如选择 “Vestas V105-3.45MW”)      │
│  · 实例 (Instance) 记录型号绑定；底层大场景默认装载【外观版】几何        │
│  · 80~90 台机位大场景保持极致性能与极低显存                             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 3. 单机特写 / 报警定位
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│          设备页即时热替换 + 通用包围盒爆炸/透视 (Forge 机制)            │
│  · 根据实例绑定的型号，即时异步拉取该型号的【完整版】模型进行热替换      │
│  · 通用透视 (X-Ray)：自动识别外层大体积罩壳/Nacelle 材质半透明化 (.14) │
│  · 通用爆炸 (Exploded)：塔筒锁定，机壳抬升，叶轮前移，内构件径向微错位   │
│  · 退出/切页：100% 还原位置与材质，复位切回外观版，零副作用              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 详细设计与关键实现

### 3.1 在 OntoBase 的 `Demo-PDS` 项目中补齐风机型号定义
1. **梳理补齐清单（涵盖所有 20 款风机型号）**：
   - 包括现有场景使用的 8 个核心机型：
     - `TU-3000`（夏李已存在）
     - `Vestas V105-3450`（Beck Burn）
     - `GE 3.2-103`（Corriemoillie）
     - `Nordex N80-2500` 与 `Siemens SWT 2.3-82`（Crystal Rig）
     - `GE Haliade-X 14MW`（Dogger Bank）
     - `Siemens SG 8.0-167`（Hornsea 2）
     - `Siemens SWT 2.3-93`（Teesside Offshore）
     - `MySE 18.5-260`（海上风电·MySE）
   - 以及模型库中现有的其他 11 个机型（如 SG 11.0-200, V182-7.2, V80-2.0, V90-3.0, E-82 E2, MM82, N163/6.X, TU-22K 等）。
2. **在 OntoBase 中规范化录入**：
   - 插入 `asset.entities`，设定 `project_code = 'Demo-PDS'`，`entity_type = 'turbine'`，`object_scope = 'definition'`；
   - 录入清晰的 `display_name` 与 `properties`（包含机型编码、制造厂商、额定容量等规范字段）。

### 3.2 模型上传与模型库成对管理重构
1. **后端接口增强**：
   - 提供 `GET /api/workbench/project-turbine-definitions`：获取当前 OntoBase 项目下所有风机定义（`entityUid, displayName, modelCode, manufacturer` 等）；
   - 更新模型资产表（`project_model_assets` / `project_model_versions`）：增加 `definition_entity_uid` 与 `representation_type`（`'appearance' | 'detailed'`）字段；
   - 初始化数据迁移：自动将库中现存的 20 对模型资产与新补齐的 OntoBase 风机定义进行确切绑定。
2. **上传弹窗交互重构（`UploadModel`）**：
   - 上传 `.glb` 时，表单提供两项核心选择：
     1. **所属风机型号（OntoBase Turbine Definition）**：下拉单选当前项目中的风机定义；
     2. **模型类型（Representation Type）**：单选 `【外观版】(大场景轻量渲染)` 或 `【完整版】(含机舱内部结构)`；
   - 保存时严格存入对应的型号外键，告别文件名猜测。

### 3.3 场景编辑器风机布置操作升级（“选择型号”）
1. **资源面板（`ResourcePanel.tsx`）风机库改版**：
   - 左侧面板按 **“风机型号”** 展示列表（例如卡片标题显示 `Vestas V105-3.45MW`，副标题显示 `制造厂商: Vestas`）；
   - 卡片上展示状态徽标：`外观版就绪`（带绿点）、`完整版就绪`（带蓝点）；
2. **布置与场景快照存储**：
   - 用户点击或拖拽布置时，系统将该机型放置到场景中；
   - 场景快照的 `instances` 中记录：
     - `definitionEntityUid`: 所属风机工程定义 ID；
     - `modelVersionId`: 默认绑定的外观版模型 ID；
   - 场景保存与渲染大风场时，默认加载轻量外观版，性能与显存零负担。

### 3.4 设备特写即时热替换（Hot-swap）与通用爆炸/透视算法
1. **即时热替换机制**：
   - 当用户在驾驶舱切换到 `view === 'device'` 或由报警卡片定位到某台风机时：
     - 系统根据该风机实例的 `definitionEntityUid`，查询该型号关联的【完整版】模型版本引用；
     - `SceneViewport` 异步预加载完整版模型，并在单机镜头过渡期间将该实例的几何平滑替换为完整版；
     - 离开设备页返回场景总览时，自动切回外观版；
2. **通用包围盒爆炸算法（Generic Exploded Algorithm）**：
   - 计算风机机舱与传动链的局部装配中心 $C_{\text{nacelle}}$；
   - **塔筒**：保持绝对锁定不动；
   - **机舱外壳**：沿局部 $+Y$ 轴向上抬升 $+8\text{m} \sim +10\text{m}$；
   - **叶轮总成**（轮毂 + 叶片）：沿机舱轴向前方拉出 $+8\text{m} \sim +12\text{m}$；
   - **内部构件群**（主轴、齿轮箱、发电机、变流器、机柜等）：根据各自包围盒中心相对于机舱中心的向量，向四周径向展开并配合轻微纵向错位；
3. **通用透视（X-Ray）算法**：
   - 自动识别最外层大包围盒外壳或名称含 `nacelle / shell / housing / cover` 的网格，半透明化（opacity 0.14），透视内部全套构件；
4. **模型查看控制器（`CockpitModelView.tsx`）**：
   - 当风机成功热替换为完整版后，点亮「实体」「透视」「爆炸示意」三个按钮，支持全机型操作。

---

## 4. 文件修改清单与开发步骤

| 步骤 | 涉及模块与文件 | 修改目的与核心内容 |
| :---: | :--- | :--- |
| **1** | OntoBase 数据库脚本 / 迁移工具 | 在 `Demo-PDS` 项目下为全量 20 款风机补齐 `turbine` 类型的 `definition` 工程定义与属性 |
| **2** | [`apps/api/workbench_server.py`](file:///Users/diwei/项目2026/OntoVis/apps/api/workbench_server.py)<br>[`apps/api/model_library.py`](file:///Users/diwei/项目2026/OntoVis/apps/api/model_library.py) | 增加项目风机型号定义查询接口；模型表增加 `definition_entity_uid` 与 `representation_type` 并初始化迁移现有 20 对模型 |
| **3** | [`apps/workbench/src/ModelLibraryPanel.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ModelLibraryPanel.tsx) | 改造模型上传弹窗：必须选择项目型号与模型类型（外观版/完整版） |
| **4** | [`apps/workbench/src/ResourcePanel.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ResourcePanel.tsx)<br>[`apps/workbench/src/SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx) | 场景编辑器风机布置面板重构为“按型号选择”，实例记录型号身份 |
| **5** | [`apps/workbench/src/sceneModelView.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelView.ts)<br>[`apps/workbench/src/CockpitModelView.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitModelView.tsx) | 实现仿 Autodesk Forge 的通用包围盒径向发散爆炸与外壳透视算法，支持所有完整版风机 |
| **6** | [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx)<br>[`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 设备特写时根据风机型号即时热替换为完整版模型，退出时自动切回 |
| **7** | [`apps/workbench/tests/model-turbine-binding.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/model-turbine-binding.test.mjs) *(新建)* | 单元测试：覆盖型号定义获取、上传成对存储、按型号布置、通用爆炸算法与热替换生命周期 |

---

## 5. 验证与验收方案

1. **数据与接口验证**：
   - 验证 OntoBase `Demo-PDS` 项目下 20 款风机定义成功录入且格式符合权威规范；
   - 验证模型库中的 20 对模型已准确绑定对应的风机定义与版本类型（外观版/完整版）。
2. **场景布置与大场景性能验证**：
   - 打开场景编辑器，验证风机库按型号清晰展示，能够按型号顺利拖拽布置新风机；
   - 打开 Beck Burn、Dogger Bank 等大场景，验证全场景 80~90 台机位默认依然加载外观版，帧率与显存保持流畅轻快。
3. **设备页特写热替换与通用爆炸/透视验证（CDP 无头浏览器实机截图）**：
   - 在任意大风场（如 Beck Burn 或 Dogger Bank）中点击某台风机进入设备页：
     - 验证模型无感热替换为完整版，底部「透视」与「爆炸示意」按钮点亮；
     - 点击「透视」，验证机舱外壳半透明，内部主轴、齿轮箱、发电机清晰显现；
     - 点击「爆炸示意」，验证机壳抬升、叶轮前移、内部机械电气构件自然向四周展开；
     - 退出设备页返回场景总览，验证模型完好复位为外观版。
4. **自动化测试、构建与生产部署**：
   - 运行全量单元测试与 TypeScript 检查 0 错误；整机打包并部署至 `root@192.168.2.153`，重启服务并校验 `/health`。

---

## 6. 约束与安全边界

- **受保护文件**：严禁修改、暂存、提交或回退 `README.md` 与 `docs/references/夏李风场空间导航验证.md`；
- **语言限制**：所有回复、思考过程、注释与文档统一使用**简体中文**；
- **计划审批执行规范**：严格遵循用户规范，方案未获用户明确批准前，绝不擅自执行代码修改。
