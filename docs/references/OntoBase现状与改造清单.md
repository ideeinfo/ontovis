# OntoBase现状与改造清单

审计日期：2026-10-20。用途：为ONTOVis独立产品的工程对象、资料、物理层级与模型绑定设计提供源码事实。

本次只读检查当前本机OntoBase源码及迁移，未连接运行数据库、未验证部署、未修改产品代码、未运行测试或冻结校验。下列绝对文件链接**仅在当前工作区有效**，行号对应审计时文件内容；它们不是发布版本链接，也不能证明运行服务已经部署这些代码。

源码根目录：`/Users/diwei/项目2026/OntoBase`。ONTOVis设计与实现归独立仓库；本文件只记录现状、建议边界和待核验项。

## 1. 结论

OntoBase已有可复用的工程对象表、UID/标识/RDS、图纸证据定位、MinIO文件存储、审核事件和图谱溯源基础。但目前对象业务以图纸识别/审核为中心，尚不能直接支撑“柜体模型下维护大量无几何子设备”的完整产品流程。

推荐分工：**OntoBase维护工程对象和资料事实；ONTOVis维护场景、模型版本、几何绑定、空间代理与可视化状态。** 大量子设备首先是独立工程对象，不要求有三维网格。柜体网格只绑定柜体；子设备通过已核验物理层级获得“定位到所属柜体”的空间代理，不能伪装成已绑定精确几何。

最先完成的是项目级授权、独立对象/生命周期契约和物理层级API，再建设跨产品绑定。存在数据表或演示图谱不等于已经具备可安全对外提供的完整服务。

## 2. 已有能力与明确缺口

### 2.1 对象UID、项目范围与生命周期

| 核查项 | 当前源码事实 | 对ONTOVis的影响 |
|---|---|---|
| 独立对象存储 | `asset.entities`有主键entity_uid、project_code、entity_type、display_name、properties、review_status，没有必填几何或图纸字段。[实体表](/Users/diwei/项目2026/OntoBase/deploy/ontobase/postgres/init/001_init.sql:51) | 无几何子设备在数据层有基础，不应为了创建对象而生成假bbox或假网格。 |
| UID生成 | 默认UID由drawing_uid、object_type、display_name的哈希加项目编码生成。[生成函数](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:3190) | UID持久化后应视为不透明身份；不按名称/RDS重算。不能把当前生成方式描述为天然跨图纸/跨导入的全局UUID。 |
| 人工建档入口 | 当前人工新增走图纸object-locations接口，服务端要求有效bbox；允许传既有UID，并校验其项目/名称/类型不能被此操作改写。[创建入口](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:8016)、[一致性校验](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:8047) | 需要独立于图纸定位的对象建档/读取入口；复用主体表，保留既有识别/审核流程。 |
| 缺定位导入 | XLSX导入允许缺定位的候选，但仍核对当前图纸及源PDF版本，不直接提升为工程事实。[图纸/PDF依赖](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/result_imports.py:57)、[导入准备](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/result_imports.py:101)、[候选属性](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/result_imports.py:120) | 可参考其预览/确认/幂等模式，但不能称其已是通用无几何设备台账导入。 |
| 合并记录 | 定位合并保留merged_into_location_id；吸收实体在properties内写absorbed_into_entity_uid，并退役相应标识/RDS。[迁移](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0006_review_identity_identifiers.sql:12)、[实体合并处理](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:8513) | 已有canonical解析依据，不能说完全没有合并处理；仍需对外定义解析链、历史引用、权限和冲突语义。 |
| 删除行为 | 删除图纸时仅按其他图纸定位/证据引用判断部分实体可否删除，随后可能硬删entity及RDS。[引用判定](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:5950)、[删除实体](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:5984) | 新增层级/外部引用后必须调整生命周期，避免删除最后一张图纸导致ONTOVis绑定失效。不能依赖跨库外键自动保护。 |
| 项目一致性 | 实体、图纸、标识均含project_code；基础定位表外键分别引用图纸和实体，未在该DDL内用复合键统一约束项目相同。[定位表](/Users/diwei/项目2026/OntoBase/deploy/ontobase/postgres/init/001_init.sql:75) | 新增关系应由权威服务验证两端项目/实例上下文一致，并以数据库约束覆盖可表达的不变量。字段存在不等于权限隔离。 |

### 2.2 分类、标识、RDS与关系

| 核查项 | 当前源码事实 | 对ONTOVis的影响 |
|---|---|---|
| 对象类型 | entity_type为文本；识别目标配置入口限定device、terminal、cable、loop_label、unknown等目标类型。[实体结构](/Users/diwei/项目2026/OntoBase/deploy/ontobase/postgres/init/001_init.sql:51)、[目标配置校验](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6700) | 类型可复用，但不能直接称为完整设备分类树。柜体/传感器等业务分类应与“物理父级”分开。 |
| 项目分类 | recognition.project_drawing_classes及其targets用于图纸分类和识别目标选择。[迁移](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0020_drawing_taxonomy_and_project_classes.sql:27) | 不能把这套图纸分类误当作风机—柜体—子设备安装树。 |
| 多标识/RDS | entity_identifiers包含scheme、role、scope、来源、审核状态、有效期；RDS包含profile/aspect及来源/有效期。[标识表](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0006_review_identity_identifiers.sql:33)、[RDS扩展](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0006_review_identity_identifiers.sql:80) | 可提供现成身份数据；产品/功能/位置RDS不能通过简单字符串切分自动确认为物理层级。 |
| 已有PART_OF | Neo4j查询已有PART_OF，用于将连接端点归属到DemoObject后聚合设备连接。[查询](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/knowledge_graph.py:43) | **事实纠正：并非完全没有父子/组成关系。** 当前证据只支持局部图谱归属使用，不能证明已有可维护柜体安装树。 |
| 当前关系输出 | 对外关系组装以CONNECTED_TO、HAS_CHANNEL、REPORTS_STATUS_TO为主，ID来自kgId；查询按项目图纸title_block选择一个dataset，再读取该批图谱。[dataset选择](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/knowledge_graph.py:337)、[关系加载](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/knowledge_graph.py:367)、[输出组装](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/knowledge_graph.py:563) | 不是实体UID驱动的子设备分页/祖先API；需明确kgId与entity_uid的对应关系。当前输出直接设置confirmed也不能作为新安装事实自动确认的依据。 |
| Drawing IR关系 | IR边有geometry/connection/device/semantic图层、状态、证据/底层路径；两端指向同run内IR item。仅禁止自环，不含通用物理树防环规则；快照不可变。[边表及约束](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0016_drawing_ir.sql:56)、[不可变约束](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0016_drawing_ir.sql:110) | 可复用证据溯源与确认状态原则；不能把run快照当作长期可编辑资产层级表。 |

在本次检查的API、迁移与相关服务中，未发现通用物理包含表、层级增删改API、同上下文单父约束和并发防环机制。这是检索范围内的缺口结论，不代表运行图数据库绝不包含人工导入的其他关系。

### 2.3 文档、照片与文件存储

| 核查项 | 当前源码事实 | 最小改造方向 |
|---|---|---|
| 图纸关联 | drawing_object_locations将实体关联到图纸页、bbox/text_span，支持一个实体的多次定位；读取快照返回UID、多标识、RDS集合、来源和版本信息。[表结构](/Users/diwei/项目2026/OntoBase/deploy/ontobase/postgres/init/001_init.sql:75)、[快照](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:3441) | 复用图纸定位，新增按对象UID查询的分页资料入口；无bbox时只定位到页，不伪造区域。 |
| 通用证据基础 | asset.evidence含project_code、entity_uid、drawing_uid、evidence_type、source_uri、location和confidence。[证据表](/Users/diwei/项目2026/OntoBase/deploy/ontobase/postgres/init/001_init.sql:90) | 有底层关联基础，但不等于完整照片档案、业务版本或多对象资料管理服务。 |
| 文件存储 | source_files有URI/hash/MIME；PDF上传按同项目同hash复用文件；MinIO辅助函数可存PDF或任意类型字节。[源文件表](/Users/diwei/项目2026/OntoBase/deploy/ontobase/postgres/init/001_init.sql:8)、[hash去重](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6853)、[字节存储](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:1367) | 存储设施可复用；对象存储键/URI不构成文件访问授权，也不等于已支持模型/照片业务。 |
| 上传能力 | 当前source-files上传仅接受PDF并解析页数；另有受限XLSX候选结果导入。[PDF限制](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6833)、[XLSX限制](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/result_imports.py:40) | 通用JPEG/PNG照片归档、EXIF/拍摄时间来源、对象关联和安全读取需明确新增。模型文件上传也不应自动视为覆盖照片业务。 |
| 图片读取 | 图纸image接口返回渲染PNG，并使用public/immutable缓存。[图纸图片接口](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:7270) | 图纸预览不是现场照片；受保护文件策略需重新设计，避免缓存绕过项目撤权。 |
| 业务版本 | 文件hash与不可变IR快照存在，但未发现面向设备资料的统一DocumentVersion/适用对象/修订继承契约。 | 最小资料版本＋对象多对多关联；历史引用固定版本/hash/anchor，更新时提示，不静默替换。 |

### 2.4 权限、审计与API边界

- 账号和HS256 JWT已实现，令牌包含用户身份和有效期；没有显式issuer/audience边界。[令牌实现](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/auth.py:22)
- require_active_user检查用户存在/有效，未查询该用户对目标项目的成员资格。[权限依赖](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/access_control.py:11)
- 项目成员表有admin/reviewer/viewer及row_version，管理入口受用户管理权限保护；这不等于所有数据路由自动使用项目权限。[成员表](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0017_formal_ui_admin.sql:24)、[管理入口](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6284)
- 当前项目列表、图纸详情、PDF/image、RDS和knowledge relationships等可见路由未强制认证/项目成员检查；应用初始化也没有全局认证依赖。[应用初始化](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:87)、[项目列表](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6229)、[图纸详情/原文](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:7229)、[关系接口](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/knowledge_graph.py:621)
- Drawing IR路由有活跃用户依赖，但所见run/edge读取没有项目成员校验。[路由依赖](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/drawing_ir.py:20)、[edge读取](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/drawing_ir.py:494)
- 对象审核有操作者、前后快照、理由、撤销/重做和append-only约束；管理审计另有表。[审核事件](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0002_object_review_events.sql:21)、[append-only](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0002_object_review_events.sql:96)、[管理审计](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/sql_migrations/0017_formal_ui_admin.sql:56)
- 当前读取不是通用资产目录：图纸列表固定limit 200，源文件固定limit 50，RDS固定limit 500/100；没有统一cursor分页契约。[列表](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6899)、[RDS读取](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:11726)

因此，ONTOVis接入前应补齐服务端授权范围，覆盖列表/详情/子设备/图谱/资料原文及文件下载；不能仅在前端隐藏其他项目。独立产品可复用账号体系，但不能复制共享JWT密钥就宣称实现SSO。

## 3. 最小合理领域模型（拟新增，不是现有API）

### 3.1 工程对象与实例

继续使用entity_uid作为不透明主键；补充对象生命周期、实体修订、canonical解析和无需图纸/bbox的建档入口。区分项目级模板对象与单机实例，在实例上下文内管理物理父级；同名/RDS相似不构成自动合并理由。保留旧UID和已审核标识，不批量重算。

ONTOVis跨系统引用统一为`ontobaseConnectionId + projectCode + entityUid`，分别映射受控连接、现有`project_code`与`entity_uid`；不得使用名称、数组序号、显示路径或glTF节点名代替工程身份。

### 3.2 物理层级与电气连接分开

建议新增窄范围物理包含记录：项目/实例上下文、parent_uid、child_uid、relation_kind、状态、证据引用、revision和有效期。首期只覆盖已明确的组成/安装关系，不先建设通用本体编辑框架。

权威写入服务必须检查：

1. 两端同项目、同物理实例上下文；不存在自指。
2. 同一上下文/有效期内，一个设备最多一个有效物理父级。功能分组、位置标签或资料适用关系另行表达，不挤进物理树。
3. 重设父级前检查祖先路径，禁止物理环；检查和更新在同一事务完成，并用项目/上下文锁防止并发请求分别通过后形成环。
4. 删除/退役/合并时检查子节点及外部引用，返回明确影响；不跟随图纸删除静默销毁设备。层级变更有理由、操作者、前后值和revision冲突处理。

**防环只用于物理层级。** 电气CONNECTED_TO/信号关系可以形成回路或多对多网络，必须保留方向、端点和来源，不应用树的单父/防环规则。已有PART_OF只能经类型、上下文和证据核验后作为候选，不自动迁成确认安装事实。

### 3.3 几何绑定与空间代理

ONTOVis拥有场景/模型版本。显式几何绑定表达`sceneModelInstanceId + modelVersionId + componentKey → ObjectRef`；版本内节点定位另存，模型换版后复查映射，不能用node下标或显示名称承担跨版本身份。

对于没有网格的子设备：

- 默认沿已确认物理树寻找最近有直接几何绑定的祖先；不为每个子设备写假绑定。
- 仅在需要人工例外时保存SpatialProxyOverride，明确subject、host、依据和修订；没有可靠位置时保持“未定位”。
- 返回定位结果时区分`direct_geometry`、`ancestor_proxy`、`unlocated`，并给出实际宿主对象与依据；`container_proxy`仅保留为旧提案/样机别名。
- 选中子设备时可聚焦/高亮所属柜体，同时显示子设备清单、图纸/照片与证据；应写“定位到所属柜体”，不能声称精确定位零件。
- 后续补齐设备几何后建立直接绑定；空间代理不能反向修改工程物理父级。

### 3.4 资料、文件与对象关联

复用现有MinIO/hash设施，增加最小资料版本与对象关联，而非复制一套完整文档管理平台：

- 文件/版本保存MIME、大小、hash、存储引用、来源、业务修订和状态。
- 对象与资料版本多对多，关联注明用途、来源和审核；一个照片可关联多个对象，但不能默认把柜体照片当每个子设备的近照。
- EvidenceRef固定资料版本及page/bbox/章节等定位。不能定位时明确降级。
- 文件上传校验、授权读取、删除/换版行为与对象关联一起交付。照片归档与模型上传分别明确预算及验收，不以“都存在MinIO”省略业务工作。

## 4. 分域最小改造与所有权

| 领域 | OntoBase负责 | ONTOVis负责 | 不应重复建设 |
|---|---|---|---|
| 身份/权限 | 对象UID、项目读取授权、canonical/退役、用户身份信任及受控API | 自身场景权限；验证调用者和项目上下文，受控委托调用 | 两套彼此可独立改写的工程对象主表；共享裸密钥伪SSO |
| 对象与层级 | 无几何对象建档、分类/标识、物理包含、证据确认、电气事实 | 场景对象选择/浏览、只读投影缓存和待关联状态 | 从网格树或RDS字符串自动生成确认工程事实 |
| 图纸与资料 | 资料版本、对象关联、来源定位、受控文件读取 | 查看/定位入口和与选中对象联动 | 为每个场景复制源图纸或把预览截图当权威原文 |
| 三维资源 | 工程对象只存外部引用所需身份，不承担场景资产生命周期 | 模型上传/版本、节点清单、几何绑定、换版迁移、空间代理 | 将glTF节点路径混入RDS；原始模型替换后静默保留失效绑定 |
| 审计 | 保持原审核语义；对象/层级/资料变更独立审计 | 场景、绑定、模型发布与配置变更审计 | 把所有行为塞进现有bbox审核事件动作集 |
| 合同与发布 | 维护自己提供的服务契约、迁移、实现和测试 | 维护消费者合同、集成适配和自身发布 | 跨仓库直接导入内部模块、直连对方表或双写同一事实 |

若ONTOVis允许脱离OntoBase单独工作，应明确本地模式的数据所有权和关联状态；一旦关联到OntoBase主对象，工程事实仍只有一个写入主系统，不能静默双写。

首批必要服务契约（名称为设计职责，不表示这些API已存在）：

- 受权项目内对象详情/批量解析、按ID解析canonical及退役原因。
- 直接子设备cursor分页、按名称/标识/类型筛选、祖先路径和子节点计数；权限一致，不能靠前端加载全项目再假分页。
- 按对象读取资料/版本/定位与受控文件获取。
- 按稳定UID查询限定类型/深度/条数的关系邻域，明确kgId映射和证据状态。
- 对象及物理层级变更使用revision/幂等键；删除/换版/合并结果可解释。
- 资源不可用、待关联、身份合并、权限撤销等状态由真实服务返回，前端不模拟成功。

首期只实现上述具体接口与ONTOVis直接适配，不先建设跨产品连接器注册平台。

## 5. 待核验的部署与数据能力

下列事项不能从本次源码审计推出，实施前应以目标环境验收：

- 目标服务版本、迁移是否实际完成、数据库中对象/项目成员/关系数据量；是否存在额外网关授权。
- Demo-PDS等项目的交付包ID与运行库entity_uid映射，柜级实体是否存在、是模板还是单台风机实例。
- Neo4j实际dataset、PART_OF关系类型和质量、kgId↔entity_uid映射是否完整；已有关系不能因名字相同直接视为安装事实。
- 资料/照片真实存放位置、文件访问路径、授权归属、业务版本及适用设备；MinIO桶策略、备份和恢复。
- 目标项目现有用户/角色、跨产品token信任边界、撤权传播与缓存行为；不能以登录成功代替授权测试。
- 无几何子设备规模、层级深度、资料数量、关系密度；据此设分页、查询与文件处理预算。
- 删除最后一个图纸、合并对象、模型换版后是否能保留正确跨产品引用，以及相应审计记录。
- 上传体积、支持格式、病毒/损坏文件处理、模型解析资源预算与失败清理。代码中通用字节存储不证明这些限制已实现。

最小验收样本应含：两个不同项目/角色；一个柜体及有/无几何子设备；同名不同实例；物理成环和并发重设父级；电气回路；对象合并/资料换版/权限撤销；模型版本节点变化。它们属于后续实现验证，本次未执行。

## 6. 事实纠正与使用边界

- **“没有父子关系”过强。** 已有Neo4j PART_OF查询；准确说法是“有局部组成归属基础，缺通用受控物理层级服务”。
- **“没有合并重定向”过强。** 已有merged_into_location_id和absorbed_into_entity_uid；准确说法是“有历史合并依据，缺稳定对外canonical解析与跨产品生命周期合同”。
- **“对象必须有三维几何”不成立。** 实体表不要求几何；当前限制主要来自图纸审核入口，新增独立台账API即可合理支持无几何设备。
- **“已有照片归档/完整多租户/通用资产分页”尚无源码依据。** 文件存储、成员表和固定limit列表不能替代这些产品能力。
- 本文是设计输入；不应将本机源码路径或本次静态分析写成已发布、已部署、已通过验收的证据。

## 7. 接手复核（2026-10-20）

本轮为首切合同再次只读核对本机源码，HEAD为`ed90bf3a45e75317dc99f251a6f3acc2512e44aa`；工作区有他人未提交变更，未重置、提交或修改该仓库。未连接运行库、测试部署API或执行冻结验证，不能据此确认目标环境的权限与三柜身份。

| 核对范围 | 本轮证据 | 合同/任务落点 |
|---|---|---|
| 独立实体/创建 | [实体表](/Users/diwei/项目2026/OntoBase/deploy/ontobase/postgres/init/001_init.sql:51)不要求几何；[人工创建](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:8016)仍要求图纸与有效bbox | OB-C02/05；OB-02/03，不把现有创建路由宣称为无bbox建档 |
| 项目/文件访问 | [项目列表](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6229)、[图纸详情/原文/图片](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:7229)所见路由没有项目成员依赖，图片仍用public/immutable缓存；[活跃用户依赖](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/access_control.py:11)仅核对账号 | OB-C01/06；OB-01/05，真实跨产品读取前补授权与文件策略；不推断外部网关状态 |
| 模型入口 | [source-files上传](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:6833)仍为PDF限制 | OV-C01/02在ONTOVis新增，不改名复用成模型上传能力 |
| 合并与删除 | [合并追踪](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:8513)仍保存merged_into_location_id及absorbed_into_entity_uid；[图纸删除](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/main.py:5950)按其他图纸定位/证据判定后可能硬删实体 | OB-C02/07；OB-02，先保护UID/关系/外部引用再允许真实绑定 |
| 层级/图谱 | 在`apps/api/ontobase_api`的Python与SQL迁移中检索物理包含、children/ancestors等合同相关名称并核对[现有PART_OF](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/knowledge_graph.py:43)和[关系路由](/Users/diwei/项目2026/OntoBase/apps/api/ontobase_api/knowledge_graph.py:621)，未发现通用受控物理树读写/快照合同 | OB-C03–05；OB-03/04。缺口限于检索范围，不声称运行图数据库没有任何父子数据 |

三柜运行库UID、项目/单机实例范围、目标API版本及实际资料授权仍待核实；未读取或复制业务运行库。首切逻辑合同与可执行验收计划分别见[契约](../contracts/三柜绑定与子设备定位契约.md)和[首批任务](../plans/首批实施任务与评审清单.md)。
