# GSB 接口迁移与调用身份

已将旧仓库 assets/api/gsb 的 24 个接口迁入 Assets 的 projects/gsb/api/gsb/b1、b2；另 1 份 create.checks.yaml 保存为只读参考，不作为 API 执行。公共契约复用一份，项目专属 go2/e3e3 目录通过 projects 声明约束；接口树按业务项目显示，Engine 对直接请求和场景步骤同样执行项目检查。

单次 API HTTP 请求新增可选 identity（账号名或 none），场景 API 步骤新增 identity。调用者选择优先于旧 API auth；迁入契约及旧余额/搜索兼容入口均不再绑定账号。API 信息面板不显示固定鉴权，调试面板从当前工作区环境读取账号列表，环境或资产切换清空本次选择。原 smoke 场景在步骤上声明账号，旧路径与历史资产 ID 保留。

GSB 的两个工作区复用 API、使用不同登录配置：source 分别为 go2/e3e3，由登录结果注入 X-TOKEN、X-USER-ID。源 GSB API 均使用 token 路由；源 CSRF 路由用于 unified_login，不将其 X-SOURCE 强行加到 gsb 请求。登录 Header 的差异和调用账号分别处理，不根据接口文件名猜身份。

输入支持 object/array JSON 编辑；未完成 JSON 可继续编辑/预览，提交时校验形状。structured 模板保留 ! 必填、默认值、嵌套路径和 JSON 类型，缺失可选字段省略，嵌套必填叶字段由 Engine 校验；完整请求内容模式绕过模板 body，仍进行身份和项目检查。源目标对照已验证 24 个 API 的请求模板、说明和成功条件一致，89 处必填标记保留。

## 验证与运行

所有测试使用隔离数据库、虚构账号和内存/本机假服务。未运行真实资金、订单或售后操作；未重启原预览，也未改其数据库或账号。

- Control：`bash scripts/dev.sh pytest -q --tb=short`，418 通过。
- Engine：在外层执行 `uv run --isolated --project testplat-control --locked --extra dev --with-editable ./testplat-engine pytest testplat-engine/tests -q`，436 通过。
- Assets：同一隔离包环境执行 `pytest testplat-assets/tests -q`，6 通过；`python testplat-assets/scripts/validate.py` 全部通过。
- 实际 Assets 的 10 个上下文假服务验收：`bash scripts/dev.sh python scripts/verify_platform_assets.py`，10 通过，GO2/E3E3 source 隔离及后台 Cookie 探测通过。
- 前端：全量 194 通过，覆盖账号选择/环境切换清空、JSON 输入与错误预览；lint/build 通过（build 保留既有大 bundle 提示）。

执行了 comment pass，核对新渲染模式、兼容回退、项目边界、只读 checks 和测试注释，未遗留“API 固定 gsb.b2.primary”或“迁入资产不支持 !”的维护说明。

## 依赖与交付边界

用户确认隔离验收通过并授权合并三仓到 main。Engine 0.5.2 功能提交 `7ae2c013a976da62074d4f4d28b86e8220bbed6d` 已推送，Control 的 pyproject.toml 与 uv.lock 已精确锁定到该提交，最低兼容版本同步为 0.5.2；新 Control 在启动时拒绝旧版本或缺少 identity 契约的错误安装。正式安装无需本地 editable；scripts/dev.sh 保留为显式本地开发入口。干净检出使用正式远程包验证 Control 421、Assets 6 通过，完整静态校验通过。此次 Git 合并不打标签、发布包或部署，原预览未启用本切片。合并记录与安装命令见 [本轮交付](stage-delivery-2026-10-19.md)。

旧固定版本验收脚本改为从 Git 历史克隆再固定提交，避免源仓当前未提交资产污染旧版本兼容测试；不会覆盖源仓工作树。用户原 PHASE2_3_REVIEW_REPORT.md 保留。

## 独立隔离预览验收

用户确认后，新增独立预览脚本：

```sh
bash scripts/dev.sh python scripts/verify_gsb_workspace.py --serve
```

默认前端 http://127.0.0.1:5183/apis/isolated/gsb，后端仅监听 127.0.0.1:8013；端口已占用会拒绝启动，可用 --frontend-port/--backend-port 指定。默认只运行验收并退出，--serve 则验收后保留预览，Ctrl-C 清理临时 Git 副本和进程。使用当前 Assets 的临时 Git 副本、内存数据库、新建随机内存密钥、虚构账号及本机假 HTTP 目标。虚构操作人只在该脚本创建的应用上覆盖；浏览器通过独立 Vite 代理访问真实后端，没有拦截或伪造应用 API。原预览、账号及数据库不参与。

2026-10-19 验收通过：GO2/E3E3 公共契约各一份、专属接口及目录正确显示；切换账号/匿名、切换资产/环境清空账号和输入；缺失必填及非法 JSON 阻断，嵌套 product.id 缺失 422；对象/数组保留 JSON 类型，数字 0 和可选字段省略正确。实际收到 6 次假业务请求，另有 1 次被 Engine 阻断的 422；浏览器页面异常 0，390px 无页面横向溢出。已人工核对桌面与窄屏截图；这些结果不代表真实业务系统验收。

发现并修复项目过滤后仍显示空的其他项目 API 目录，补回归断言。相关定向测试 test_gsb_migration.py、test_assets_api.py 共 10 通过；test_asset_service.py、test_platform_workspaces.py 共 19 通过。新增/修改 Python ruff、浏览器脚本语法及 diff 检查通过；本切片没有修改前端产品代码，不重复运行上一阶段前端全量。已完成新增中文注释核对。

报告和截图默认保存在 /tmp/testplat-gsb-preview（report.json、tree-go2.png、tree-e3e3.png、object-json.png、array-json.png、nested-required.png、mobile-identity.png、mobile-json.png）；临时文件可被系统清理，脚本可复现。内存数据停止后不保留，不能用此地址替代原预览或真实业务目标。
