# ONTOVis 会话与工程读取参考实现

当前定位：空间连续导航Demo仅作本机交互参考，相关公网演示已撤下；以下代码和测试保留作正式ONTOVis实现的技术参考，不代表正式产品已部署。

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
