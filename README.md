# ONTOVis

本源数智 · 面向工业资产的可视化与 AI 分析工作空间。

ONTOVis 是独立产品，首个验证场景为风电，产品结构适用于油气、铁路等行业。OntoBase 提供工程对象、物理层级、图纸与知识证据；ONTOVis 提供模型、场景、绑定、实时状态、分析 Canvas 和受控 AI 交互。

## 当前状态

2026-10-20：设计基线 **V0.2**。整体设计已迁入本仓库，补充官方风场目录采集与同视口“全球—风场—风机”连续导航。已实现本机采集工具、首批4,089条来源观测的SQLite暂存库及MagicPath导航样例；尚无生产应用、生产数据库迁移、已接通的工程/监测/AI接口。需求、接口和正式页面状态仍按首批评审门推进。

2026-10-21：按用户要求执行开发计划，推进PREP-01/02。已交付模型只读核验工具，实际TU-3000源/派生的全量几何映射检查通过；后续一批交付三柜/无几何子设备定位的离线合同验证，32个合成请求响应和43项定向测试通过。按用户授权，Demo-PDS现有候选已通过OntoBase已有审核流程采用为正式对象；三柜身份、安装实例与物理链仍待补齐。以上不代表真实绑定、G1/G2/G3或生产接口通过。当前任务、证据和下一步见[开发执行记录](docs/plans/开发执行记录.md)。

后续开发（2026-10-21）：用户确认先完成演示闭环。OntoBase测试环境已部署提交`a08c6412`及迁移73/74，10条路径支持受控对象读取、独立安装建档和有效期物理层级；73项单元/PostgreSQL测试通过。指定账户的项目管理员授权已通过API执行。7号演示范围已建立5个独立安装对象、4条假定关系；同型号定义共用，安装UID独立，原1,131个定义保留。三柜与无几何子对象已通过真实API连接本机三维演示，分析对象与CN空间宿主分列。详见[首切页面与服务评审](docs/plans/首切页面与服务评审.md)、[实际服务剖面](docs/contracts/三柜绑定与子设备定位契约.md#8-已实现的受控对象读取剖面2026-10-21)及[执行记录§9](docs/plans/开发执行记录.md#9-已确认范围安装后端与7号演示闭环)。

本机只读会话工具14项测试、真实API/三维交互18项、注入失败/迟到响应13项、窄屏3项检查通过，分别记录，不相加为生产覆盖率。固定演示范围会话代码已验证，后续公网Demo已按用户要求撤下；工程发布保持阻断；受保护原文、受控退役、模型上传/正式绑定尚未完成，G1/G2/G3未整体通过。

2026-10-21用户最新定位：**空间连续导航Demo仅作为ONTOVis交互实现参考，不发布到vis.ontobase.ai。** 公网Demo页面、资源及配套演示会话服务已撤下，域名仅显示“尚未开放”；本机数据、模型、源码及历史验证证据保留。正式ONTOVis按既有MagicPath项目实施，不把夏李Demo当作产品发布包。50项定向、21项组件、22项合成会话及26项原公网检查均是对应技术样机的历史证据，不代表正式产品已上线。详见[撤下记录](docs/plans/公网演示部署记录.md)及[执行记录](docs/plans/开发执行记录.md)。

GitHub 主仓库：[ideeinfo/ontovis](https://github.com/ideeinfo/ontovis)，本机`origin`已关联；首批设计、工具与测试纳入版本管理，开发分支为`codex/design-foundation`。模型、生产数据、原始附件、凭据和本机输出不进入远端。

管理工作台的活动视觉与交互设计已迁入 MagicPath 独立项目 **ONTOVis 产品设计**。现有三个管理画面包含八个管理视图，新增一个全球—风场—风机连续导航画面；版本及交互范围见[MagicPath 设计索引](docs/design/MagicPath交互设计.md)。

## 阅读入口

- **[整体设计维护入口](docs/design/ONTOVis整体设计.md)**
- **[本机完整HTML总册](output/spatial-catalog-design-20261020/index.html)** / **[完整MD总册](output/spatial-catalog-design-20261020/ONTOVis整体设计总册.md)**
- [风场数据库与已完成采集](docs/design/风场数据库与数据采集设计.md)、[可重复运行工具](tools/README.md)
- [全球—风场—风机连续导航](docs/design/全球风场风机连续导航设计.md)
- [夏李风场真实三维导航验证与数据边界](docs/references/夏李风场空间导航验证.md) / [本机 Demo 使用说明](output/xiali-spatial-demo-20261020/README.md)：含GEM公开地图35,089个风电分期点、全球地图/星空与夏李流云/黄昏光照；真实DSM、草地与既有GLB继续保留。2026-10-21按用户正式平面图修正为1–18及B1，共19个图示机位；坐标仍为配准估计，B1与公开18台/48MW口径的关系待核。分期点数不等于独立风场数。
- [运营与Canvas](docs/design/运营工作空间与Canvas设计.md)、[Agent详设](docs/design/AI_Agent详细设计.md)、[技术栈与实时接入](docs/design/技术栈与实时接入设计.md)

- [工作区交接与接手顺序](docs/plans/工作区交接.md)
- [有效需求基线与新旧覆盖关系](docs/requirements/有效需求基线.md)
- [三柜绑定与无几何子设备定位契约（拟议）](docs/contracts/三柜绑定与子设备定位契约.md)
- [首批实施任务、待评审项与验收清单](docs/plans/首批实施任务与评审清单.md)
- [开发执行记录与当前任务](docs/plans/开发执行记录.md)
- [公网空间演示部署](docs/plans/公网演示部署记录.md)、[历史演示会话契约](docs/plans/公网会话与工程读取评审.md)
- [MagicPath 交互设计与版本索引](docs/design/MagicPath交互设计.md)
- [产品与架构设计](docs/design/ONTOVis产品与架构设计.md)
- [模型与设备关联工作流](docs/design/模型与设备关联工作流.md)
- [配置中心与AI交互设计](docs/design/配置中心与AI交互设计.md)
- [实施范围与排期增补](docs/plans/实施范围与排期增补.md)
- [OntoBase现状与改造清单](docs/references/OntoBase现状与改造清单.md)
- [模型格式与来源核验](docs/references/模型格式与来源核验.md)
- [品牌规范](docs/design/brand-spec.md)
- 本机 HTML 总册：`output/design-20261020/index.html`；原交互原型：`output/design-20261020/console-prototype.html`。两者保留为 V0.1 历史快照，后续 UI 评审使用 MagicPath。

## 仓库边界

两个仓库独立构建、发布和版本管理。ONTOVis 通过明确的授权 API 访问 OntoBase，不导入其业务 Feature、不直连其数据库、不拷贝生产数据。正式代码按切片放 `apps/web`、`apps/api`、`apps/worker`；当前ONTOVis维护代码包括目录/模型/契约/定位/打包工具及测试；[会话参考实现](apps/README.md)验证固定演示范围的本人会话与简单登录，当前不对公网提供Demo。原installation_preview仍仅供本机操作者预览；未创建空应用框架。工程权威API在OntoBase自身后端实现。

维护中的设计在 `docs/`，用户 Logo 原件副本在 `assets/brand/`。HTML、截图、归档、临时脚本在 `output/`，不进入 Git；用户原始附件`资料/`也排除。原始业务资料仍在 OntoBase 的原位置。跨产品逻辑契约与未实施能力继续标为提案，已落地的HTTP范围单独列在实际服务剖面中。
