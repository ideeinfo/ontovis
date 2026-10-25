# ONTOVis 工作台与会话

当前首切：[workbench](workbench/README.md)承接MagicPath紧凑工作台，包含本人登录、设备树/完整项目对象搜索分页、现模型和三柜关联、子设备祖先定位及图纸预览。后端`api/workbench_server.py`固定部署项目和设备上下文，动态读取对象，不使用固定五个角色UID清单限制目录。已授权现模型的三柜映射单独存放静态目录之外，固定文件和对象修订；新增自有私有模型库、受控上传和演示关联写入；不写OntoBase业务库、不提供任意文件代理。

共用`authority.py`、`user_sessions.py`和`session_http.py`处理受限回环读取、内存会话及同源HTTP边界。令牌只保留在服务端内存，30分钟无操作或最长8小时失效；每次读取核验当前项目成员，读取/渲染后重查权限和会话。客户端只收到不透明HttpOnly会话Cookie，登录仅用户名、密码。

维护检查：`python3 -m unittest tests.test_workbench_server tests.test_session_server tests.test_installation_preview tests.test_model_assets tests.test_model_upload -v`；Node 22执行`npm --prefix apps/workbench run check`包含严格类型、时序/定位/语言检查和构建。上传限额与演示写入见[模型上传首切](../docs/plans/模型上传与演示关联切片.md)。本批服务及素材边界见[紧凑工作台切片](../docs/plans/紧凑工作台与模型接入切片.md)。部署模板为[正式会话服务](../deploy/ontovis-workbench.service)和[正式入口](../deploy/nginx-workbench.conf)；私有设备配置不含凭据，模型与UID映射不进入Git或静态发布目录。

Q-13登记后端候选：`api/workbench_server.py --registry-backend postgres`使用私有`ONTOVIS_REGISTRY_DSN`及经过离线activate-new生成的整组目录，可选驱动为[requirements-registry.txt](api/requirements-registry.txt)。运行时PG仅管理项目/共享库登记，业务SQLite与私有文件保持，原权限和单进程保护继续生效。默认SQLite不依赖PG驱动，PG错误不自动回退；完整迁移、备份和恢复规则见[契约§6](../docs/contracts/项目登记PostgreSQL迁移准备契约.md#6-实际会话服务的-postgresql-登记候选)。当前在线服务尚未切换。

## 场景与地形开发切片

Q-01已在原MagicPath工作台完成设计/服务基线；首批局部保存/地形服务见[原切片](../docs/plans/场景保存与地形服务切片.md)，当前新增[模型资源与地理保存](../docs/plans/模型资源与地理场景保存切片.md)。项目资源支持固定GLB版本、校准及模型使用去向；场景六个POST包含只读预检，配置GIS运行时后支持首次锚定、地理放置及固定修订重开。当前仅支持未关联布局，根/内部工程关联与换版明确拒绝，不能静默丢字段后保存。新116项隔离Linux检查无跳过；完整场景UI和部署仍未完成。

GIS处理器使用独立的[可选固定依赖](api/requirements-terrain.txt)，不在普通工作台启动时强制导入；处理范围、命令和缺口见[地形验证记录](../docs/plans/地形导入与坐标验证.md)。原界面和旧模型入口继续保留，地形五条私有HTTP已接通；旧库已做副本schema兼容检查，完整关联迁移尚未完成。离线孤立文件恢复见[受限维护工具](../tools/model_store_recovery.py)，不能在服务运行时清理暂存或将其当资源删除接口。

## 历史空间演示参考

空间连续导航Demo仅作本机交互参考，相关公网演示已撤下；以下参考入口独立保留，不能作为正式产品构建包。

`api/session_server.py`是固定演示来源的逐用户只读会话参考；`web/session.js`、`web/session.css`及`web/authority-preview.js`覆盖现有空间演示的账号入口与工程页。管理工作台设计继续维护于MagicPath，不将历史HTML转为设计源。

- 上游只调用OntoBase已有登录、本人信息、项目授权及五个演示角色的受控读取。UID清单和模型在仓库外，不能提交。
- HTTPS同源、`__Host-`/Secure/HttpOnly/SameSite=Strict cookie、不透明随机ID；令牌仅在服务内存，密码用后丢弃。
- 30分钟无操作、8小时最长会话；普通30秒状态检查不续期，真实交互至多每分钟续期一次。登录、退出、定位绑定会话修订，退出取消未完成登录/读取，跨标签页清理。
- 权限每次重查；只读Demo-PDS的7号五个安装角色，不含绑定写入、发布、原文下载、监测或现场控制。

本机定向检查：

```sh
python3 -m unittest tests.test_session_server tests.test_installation_preview tests.test_package_spatial_demo -v
node --check apps/web/session.js
node --check apps/web/authority-preview.js
```

维护的定向测试合计50项（24会话、14定位、12导出）。测试使用合成用户、身份与来源，不连接真实数据库。历史会话配置及当前域名未开放模板见[会话与工程读取](../docs/plans/公网会话与工程读取评审.md)、[systemd单元](../deploy/ontovis.service)和[Nginx模板](../deploy/nginx-vis.conf)。来源固定回环，服务使用独立无登录账户；私有清单/模型检查文件放静态根外。未建立空Web框架、通用代理、连接器平台或Worker。
