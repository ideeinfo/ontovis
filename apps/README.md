# ONTOVis 只读工作台与会话

当前首切：[workbench](workbench/README.md)是依据已确认MagicPath设计实现的正式只读工作台，包含本人登录、当前安装树/对象及关联图纸预览。后端`api/workbench_server.py`固定部署项目和安装范围，动态读取当前对象，不使用固定五个角色UID清单，不提供写入或任意文件代理。

共用`authority.py`、`user_sessions.py`和`session_http.py`处理受限回环读取、内存会话及同源HTTP边界。令牌只保留在服务端内存，30分钟无操作或最长8小时失效；每次读取核验当前项目成员，读取/渲染后重查权限和会话。客户端只收到不透明HttpOnly会话Cookie，登录仅用户名、密码。

维护检查：`python3 -m unittest tests.test_workbench_server tests.test_session_server tests.test_installation_preview -v`共47项；Node 22执行`npm --prefix apps/workbench run check`包含严格类型、9项时序检查和构建。首批接口/限制见[当前图纸评审与实际范围](../docs/plans/关联图纸首切页面与服务评审.md)。部署模板为[正式会话服务](../deploy/ontovis-workbench.service)和[正式入口](../deploy/nginx-workbench.conf)，项目与安装范围为部署私有配置，不含凭据或模型清单。

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
