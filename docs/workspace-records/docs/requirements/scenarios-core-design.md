# 业务场景核心需求与设计草案

日期：2026-10-19。状态：用户已审核设计，切片 1 本地实现与自动化验证完成，待隔离预览体验；未迁移完整场景或执行真实业务。下文涉及 map/目标/UI 的字段仍为后续设计，当前可运行契约见 Engine docs/scenario-schema-0.3.md 与 Assets examples/scenario-parameters。

## 1. 业务目标与边界

业务场景 case 是独立运行入口，围绕业务目标组织步骤；公共场景沿用领域名公共流程 flow，只供 case 或其他 flow 调用。需要单独运行某个 flow 时，创建薄 case 包装，不能给 flow 增加独立运行入口。API、flow、Page 都是可复用契约，组织场景不以 API 管理的平台树为边界。

用户已澄清：“一个文件”指在业务场景中集中展示和维护参数值，各步骤及被引用公共流程只引用这些值；不要求底层必须是一个物理文件。业务场景提供统一参数区，覆盖其完整步骤树需要人工填写的业务输入。公共流程维护输入、输出、步骤和参数映射，不保存商品、收件人、账号选择等调用方测试数据。静态配置与接口返回的运行态数据分开；后者由提取和显式传递产生。后续同一套编排支持 API 与 Web UI 混用。

用户审核后，本轮推进切片 1：统一参数展示、显式公共流程调用、输出传递与嵌套记录；仅假目标验收。不自动迁移完整场景、提交、推送或发布，不操作原预览或数据库。

## 2. 旧目标场景的实际行为

源仓库只读：`/Users/jiavin/Developer/products/testplat-new`。分析基于当前工作树，不假设它与历史提交一致；不导入或运行旧执行器。

入口：`assets/scenarios/go2/order/full_pay/items_create_pending.case.yaml`。
数据：`assets/scenarios/go2/items.data.yaml` 的 `base.common.order` 和 `base.profiles.multi_sku.items`。multi_sku 含两条商品、不同供应商；本报告不复制原收件人、手机号或其他实际业务数据。

静态依赖树：

```text
items_create_pending.case
└─ 创建全款多 SKU 待支付订单 → create_items_pending.flow
   ├─ 准备全款多商品订单 → prepare_items.flow
   │  ├─ 解析全部商品项 → resolve_items.flow
   │  │  ├─ collection.map（按 items 顺序）
   │  │  │  └─ resolve_item.flow × N
   │  │  │     ├─ 搜索完整货号 → 精确选择商品、颜色与尺码
   │  │  │     ├─ 校验正整数数量
   │  │  │     └─ 组装订单行、运费商品项及金额操作
   │  │  └─ 汇总数量、商品金额，导出有序列表
   │  ├─ 地址识别
   │  ├─ 整单智能快递 → 按 express_code 选同一方案
   │  ├─ 查询服务费 → 按 service_fee_type 选择
   │  └─ 按整单数量计算运费
   ├─ 计算服务费总额、建单总金额
   ├─ 创建 WAIT_PAY 订单 → 提取 order_no
   ├─ 后端预结算 → 校验订单号、金额和商品总数量
   └─ 导出 order 与 web_order_amount
```

它涉及 4 个 flow、7 个不同 API。每个商品查询一次，其余 6 次调用只执行一次；当前两条商品对应 8 次业务 API 调用，登录和未来轮询不在此计数中。全部业务请求使用 GSB b2 身份，本目标本身不覆盖跨平台、b1/b2 混用或 UI；这些需求必须另外构造验收。

| API ID（省略 api.gsb.b2. 前缀） | 作用 | 新 Assets |
| --- | --- | --- |
| order.search_product | 完整货号查询，提取同一商品及 SKU 的价格、供应商等字段 | 已存在 |
| area.user_area_place | 地址识别并提取收件信息 | 已存在 |
| order.intellect_express_items | 用全部商品取得整单快递方案 | 已存在 |
| order.service_fee | 选择 PLATFORM_DELIVER_FEE | 已存在 |
| order.freight | 整单数量与省份对应运费 | 已存在 |
| order.go2.create_items | 创建有序、多供应商订单行的待支付订单 | 已存在 |
| order.go2.settle | 取得后端权威金额和总数量 | 已存在 |

金额链：每行价格 × 数量得到商品金额，求和后加整单运费和单件服务费 × 总数量，作为提交金额；预结算返回 totalAmount 必须与提交金额 decimal_eq，itemQuantity 必须等于汇总数量，订单号必须一致。对外导出的应付金额只来自预结算，不能用本地估算冒充后端结果。当前 case 顶层另断言订单号和金额非空。

旧流程内仍有 service_fee_type、send_type、goods_pay_later_flag、remark 模板、地址随机后缀等字面值或生成表达式。不能只照抄旧文件就声称达成“所有可配置取值集中维护”：迁移时要逐项区分业务不变量和可配置输入，将后者显式上提到该 case 的统一参数区。

## 3. 已有能力与明确缺口

| 能力 | 当前代码事实 | 缺口 |
| --- | --- | --- |
| API 顺序执行 | Engine Case schema 0.2 仅支持 type=api；CaseRunner 串行、fail-fast | 不支持 flow、map、transform、场景级断言 |
| A 返回传 B | output alias 保存安全响应；支持点分对象路径和整字段 JSON 类型传递 | 无任意命名投影、数组路径、条件筛选及提取基数规则 |
| 参数集中 | case.params 与按资产/环境保存的覆盖已存在 | 缺完整嵌套步骤的统一参数展示、引用关系和 flow 输入契约；独立数据文件是可选实现 |
| 身份选择 | API step.identity 已存在；同 case 可选择已有身份表中不同身份 | 整个 Case 请求只有一份 environment/auth 上下文，不能据此声称已有跨工作区配置执行 |
| 前置检查 | API 资产、Host、身份等在执行前预检 | 无递归 flow 依赖、循环引用、map 子流程和输入/输出预检 |
| 运行记录 | 平铺 StepOutcome，含请求/响应/错误/身份；登录记录已有 | 无父子节点、变量解析/提取/输出快照和来源关系 |
| 页面 | 有 Page 资产浏览入口 | Case 未注册 UI 执行能力，不能执行混合场景 |
| 场景详情 | Control Case 详情仅返回文件元信息 | 需 Engine 公共 describe/validate 能力，Control 不复制一套 DSL 语义解析器 |

新系统入口证据：

- Engine `domain/case.py`、`adapters/filesystem/case_loader.py`：schema、未知字段拒绝、引用约束。
- Engine `engine/case_context.py`、`engine/case_runner.py`：JSON 类型、alias、失败停止和部分结果。
- Engine `ports/step_executor.py`、`engine/api_step_executor.py`：可复用的执行器边界。
- Engine `interface.py` 的 CaseExecutionRequest、StepOutcome、CaseExecutionOutcome：单环境输入与平铺结果。
- Control `services/execution_service.py`、`services/run_config.py`：现有参数、环境、身份冻结链。
- Control `api/case_schemas.py`、`services/case_asset_service.py`：HTTP 契约和语义归属。
- Control 前端 `features/executions/CaseResultView.tsx`：平铺折叠列表与失败定位。

以上路径分别相对 `testplat-engine/src/testplat_engine`、`testplat-control/src/testplat_control` 和 `testplat-control/frontend/src`。本轮没有发现工作区根目录的 `graphify-out/graph.json`，没有建立新图；结论来自文件和符号的直接核对。

## 4. 建议的参数模型

### 4.1 “公共”和“专用”的含义

- 场景参数区的 common：同一个 case 内多个业务步骤复用的稳定业务输入，如收件信息、快递选择。
- 场景参数区的 private：此 case 的专用输入，如这次多 SKU 商品列表、数量和预期。
- flow.inputs：每次调用的局部输入，必须由调用点显式绑定；flow 不直接读取根 case 的 common/private，也不自行加载业务数据文件。
- flow 内部变量：提取值、计算值、前序步骤结果，只在本次调用可见。不同调用、循环项、执行之间隔离。
- flow.outputs：明确声明的输出契约；父层只能读取已导出的字段，不穿透访问子流程内部临时变量。
- 跨 case 共享业务样本：作为以后独立的数据复用能力，不能默认变成所有 case 共享的可变全局变量。每个 case 有自己的统一参数视图；不要让 flow 隐式引用其他 case 的数据。

这里的 common 不是公共流程，也不是 ADR-003 的公共运行配置。Host、超时策略、基础服务连接与账号凭据仍走已有配置边界。身份在文件里只能保存引用或角色绑定，不能保存密码、Cookie、token。

### 4.2 作用域、覆盖与输出规则

| 规则 | 建议行为 |
| --- | --- |
| 参数归属 | case 统一参数区集中维护人工业务取值；不得通过 flow 隐式引入另一处需要填写的业务默认值。底层文件或数据库组织属于实现选择 |
| 现有覆盖 | 保留 ADR-003：Git 默认 < 页面默认 < 兼容共享环境参数 < 当前 case 环境覆盖 < 本次输入；默认值来源由后续实现确定，统一参数区展示最终值与来源，避免重复维护 |
| 覆盖粒度 | 延续顶层键整份替换，不自动深合并；覆盖 common 或 private 必须提交完整对象，并在预览展示最终值和来源 |
| Web 维护 | 同一个 case 参数工作区展示数据文件默认与该 case 的覆盖；公共流程不提供调用方参数保存入口。页面保存不写回 Git，延续现有显式保存与 revision 冲突机制 |
| 集中维护含义 | 用户在业务场景中一次查看、编辑所需业务参数，步骤及嵌套 flow 只引用；底层可复用已有 Git 默认和数据库覆盖，与 ADR-003 不冲突。无需为物理文件数量新增约束 |
| 调用绑定 | 在父作用域先解析 with/inputs 映射，再按 flow.inputs 验证并复制冻结；没有变量名同名自动传入 |
| 重名 | common.x 与 private.x 是不同路径，不建立 private 自动覆盖 common 的规则；调用点明确选择其一 |
| 默认 | flow 可声明类型、必填、允许为空等契约；可配置业务默认由 case 提供。协议固定常量可留契约内，变化就改变流程语义的常量应有说明 |
| 提取 | 指定来源节点、受限选择器、输出名、类型、是否必填及命中基数；缺失与 null 区分，0/false/空数组不因真假值被丢失 |
| 发布 | API 业务成功后执行提取到暂存局部值，再做本步断言；全部成功后才向后续步骤发布输出。失败保留脱敏暂存证据，不能供后续步骤消费 |
| 导出 | flow 结束验证所有声明输出；成功才向调用者发布一份不可变输出。子流程失败不发布“半成功”的正常输出 |
| 未知引用 | 前向引用、越界访问、未声明输入/输出、缺失路径、循环依赖明确报错，禁止旧 _base 或 API 默认值替调用者静默补齐必需业务输入 |

可配置输入如果必须经多层 flow 传递，就逐层声明输入和映射。这会多一些显式映射，但让依赖可检查，避免每个 flow 都能读整个 case 的隐性耦合。可用结构化输入对象减少字段重复，例如 order_options；依然要有字段契约。

### 4.3 统一参数区示意

下例用 YAML 表达业务场景统一参数区的数据结构，仅为展示示意，不规定实际文件格式或存储位置；符号值为虚构样本。

```yaml
# items_create_pending 业务场景的统一参数区
common:
  order:
    receiver_text: "测试收件信息"
    express_code: "示例编码"
private:
  items:
    - product_number: "样本货号A"
      sku_color: "样本颜色"
      sku_size: "样本尺码"
      quantity: 1
    - product_number: "样本货号B"
      sku_color: "样本颜色"
      sku_size: "样本尺码"
      quantity: 2
  order_options:
    service_fee_type: PLATFORM_DELIVER_FEE
    send_type: WHOLE
    goods_pay_later_flag: 0
    remark_prefix: "多商品全款待支付测试"
```

case 编排只映射 `params.common.order`、`params.private.items` 和 `params.private.order_options` 给建单 flow。随机后缀和运行时间作为有来源记录的生成变量，生成规则若允许测试人员配置，也在场景统一参数区声明；运行时只求值一次并冻结。所有接口 wire 字段的固定封装仍由 API 契约负责，不要求把每个协议常量复制进场景参数区。

## 5. 场景组织与跨平台运行

业务场景菜单以资产仓库、业务项目/业务目录、标签组织；业务项目用于订单归属，可作为筛选，但不要求选择单一被测平台才能看到场景。公共流程有独立复用目录/类型标识，支持查看契约、被引用关系和运行实例，没有直接运行按钮；后端同样拒绝 flow 直接运行，不能只禁前端。

case 声明需要的运行目标别名，如 buyer、seller、dispatcher、picker。启动时为每个目标绑定资产来源工作区、被测平台、业务项目、环境和账号引用。API step 使用目标别名，目标配置在执行前全部解析和冻结；账号选择可按不同步骤切换。不要把 b1/b2 名称直接当账号唯一键或由名字推断业务项目。

示意绑定：

| 目标别名 | 被测平台/业务归属 | 身份与环境 |
| --- | --- | --- |
| buyer | GO2 的 GSB / GO2 | GO2 环境 + 买家账号 |
| seller | GO2 的 GSB / GO2 | 同环境 + 商家账号 |
| dispatcher | 代发管理 / GO2 | 后台环境 + 后台账号 |
| picker | 代发拿货 / GO2 | 拿货端环境 + 拿货账号 |

flow 声明需要哪些目标角色，调用者显式映射；flow 不固定真实账号或工作区。一个 API 的项目限制仍按实际步骤目标校验。GO2 与自身 GSB 共用身份的 ADR-002 规则继续有效，独立后台配置不能借用网站登录态。

现有 project_id 路由和历史记录保留一个主办工作区作为兼容归属，新结果增加完整 targets 与每个目标配置 revision，不把一个 project_id 冒充整条链路的全部配置。场景资产放在哪个根目录与业务执行哪些平台分开。建议先支持同一资产仓库内已声明的多个工作区，并将各工作区 assets_root 组装为只读、来源明确的运行清单；API/flow ID 若有冲突必须带来源限定或拒绝，不能靠目录遍历顺序覆盖。跨多个资产仓库暂缓，未来需冻结每仓 commit。

运行开始前冻结主办仓 commit、全部被引用资产、参数来源、生效参数、目标环境 revision、账号引用及 revision；复用已有数据库配置解析器，不在 Engine 中查询数据库。认证会话缓存键必须包含目标配置归属、环境和具体身份，不能只按 buyer 或 gsb 命名复用。

## 6. 编排、计算与断言

新增版本化 schema；原 0.2 加载和执行继续保留，不扩大旧 schema 的未知字段容忍范围。建议以现有 StepExecutor 边界扩展 api、flow、map、transform，未来再注册 ui；不把所有逻辑复制进 Control 或一个巨型执行器。

- flow：输入与输出契约、独立调用作用域、递归依赖检查、深度限制、只读调用上下文。
- map：有序数组、每项独立 item/index、子流程、命名输出列表；默认串行、首错停止、结果顺序与输入一致。本目标要求 items 非空，空列表应在业务请求前拒绝。
- transform：允许列表内建操作，满足对象投影、正整数、整数求和、Decimal 乘加与金额格式化；不提供任意 Python/JS eval。金额精度、舍入点和输出格式按旧实现逐项核对，以定向夹具锁定，禁止 float 累加。
- extract：支持数组下标与条件筛选，条件值以参数绑定传入，不将字符串拼到 JSONPath 源码。商品、SKU、选中快递等要求恰好一个匹配；列表输出要求 many。旧 selector.select_first 的“取第一条”不作为唯一性保证。
- assert：API 原有成功条件继续执行；另外支持步骤、flow 输出和 case 结束断言，至少覆盖非空、相等、数量大于零、Decimal 相等。断言记录 actual/expected/操作符/来源/结果。

递归预检在任何登录和业务请求前检查全部静态依赖、flow 循环、输入/输出、已知参数类型、目标和执行器可用性。依赖未来响应的字段在到达步骤时检查；不要承诺静态预检可以证明真实响应存在。运行期失败保留原 timeout/transport/internal 与业务失败分类，层层归属到实际子节点。

本目标有建单副作用，不自动重试 case、flow、map 或建单步骤。预结算失败时保留已创建订单号及失败证据，不重新建单或自动删除订单。以后只读轮询必须与修改步骤明确区分，并逐次记录实际尝试。

## 7. 运行结果与变量可追溯

执行计划与实际执行记录分开保存。计划描述业务层级；运行节点记录真实发生的调用，不把未运行节点伪装成成功。新增结果版本，旧平铺历史保留原解析；新结果采用显式父子关系，不能通过名称、数组下标或缩进猜父节点。

建议节点最小契约：node_id、parent_id、定义中的 step_id、invocation_id、kind、name、asset_id/来源、顺序、iteration_index、status、开始/结束/耗时、skip_reason、error、inputs、outputs、bindings、extracts、assertions、目标与安全身份、HTTP 调用或 UI 动作/附件引用。相同 flow 多次调用及每个 map 项都生成独立 invocation/node ID。

每个 bindings 条目记录“目标参数路径 ← 来源作用域/节点/路径、表达式、解析类型和脱敏值”；每个 extracts 条目记录来源响应、选择器、命中数、目标变量、类型、值与是否成功。用户应可从建单参数回看它来自哪一条商品响应，再跳到后续预结算断言。

运行详情左侧是可展开的业务树，默认展开最深失败节点及其所有祖先；右侧显示选中节点的输入/输出、变量引用与提取、断言、请求/响应或 UI 动作。搜索节点名、变量名和错误路径；流程层显示输入输出与内部步骤，避免把整个流程当一条 HTTP 请求。

map 内要保留每次迭代容器与子流程树，显示 item 索引及安全摘要。失败后的已知计划节点标 skipped；输入尚未解析、迭代尚未展开的容器只记录未展开原因，不虚构迭代数量。父节点失败摘要指向实际失败子节点。顶层业务步骤数、叶子执行数与 HTTP 请求数分别统计，不能相加后当同一种“步骤总数”。

当前流程中的 noop 导出不必作为主要业务步骤展示；可以归入输出映射详情，但原始执行证据必须保留。费用计算、选品、建单、预结算仍有业务可读名称。

所有历史和 API 返回使用统一脱敏规则；变量改名和层层导出不能绕过敏感性标记。秘密仅由认证/受保护输入通道进入执行器，不进入普通业务参数。手机号、地址、UI 输入、截图与附件需沿用或扩展安全展示规则；只记录来源与已脱敏值，不为了变量追溯保存原始凭据。运行时业务值与公开记录快照分离，但不放宽当前安全边界去允许普通变量取得 token。

## 8. 后续 Web UI 与 API 混合的边界

已读旧 `domain/page.py`、`ports/browser.py`、`engine/executor.py` 的 UI 分支，以及 `assets/scenarios/go2/order/full_pay/payment_success.flow.yaml`。旧系统通过 Page 契约统一 URL/元素/iframe 链，支持 open/read/fill/click、登录态注入、按身份保留 BrowserContext、失败截图和动作事件；支付流程体现 API 产出订单号及金额后进入 UI 的使用方式。本轮仅阅读，没有执行这些动作。

新模型为 UI 保留同样的 inputs/outputs、assertions、bindings 和父子节点契约。增加 UiStepExecutor 与 BrowserSessionProvider，Page 继续独立于 case；认证服务提供可用于网站的状态，API Header 不直接当浏览器 Cookie。

浏览器会话属于整个 run 的资源管理器，flow 调用只隔离变量，不能每进入一个 flow 就丢失同一身份的浏览器会话。b1/b2 不同 BrowserContext；网站和所属 GSB 是否可沿用由认证协议决定；运行结束或取消时关闭资源。异步执行、取消与部分结果在引入 Browser 适配器时一并验收。

报告中 UI 节点展示动作、元素契约、读取结果、截图和失败位置，不强行伪造 HTTP response。截图与附件应受执行历史相同的访问控制。未来轮询记录 attempts 子节点，修改动作默认一次；本阶段不开发支付或验证码适配。

旧报告 `report_builder.py:build_case_detail` 已按 step 编号构树并归入 HTTP、断言、提取、UI 事件；可以借鉴信息层次。其未结束节点根据整条 case 状态补 pass/fail 的行为不应照搬，新运行记录必须保留实际未结束/取消状态。

## 9. 建议切片与可验证验收

按以下顺序一次推进一个切片；第 0 项完成，第 1 项本地实现及自动化验证完成，后续切片未实施。

| 切片 | 可观察结果 | 隔离验收 |
| --- | --- | --- |
| 0 需求分析 | 本文给出旧链路、参数/目标/结果契约与差距 | 只读解析依赖；7 个 API 文件存在；无业务执行 |
| 1 公共流程最小闭环 | 业务场景统一参数区 → 同 flow 调两次 → 输出传后续 API；能看嵌套结果和来源 | 假服务两次不同输入互不污染；flow 直接运行拒绝；缺输入、循环引用在零请求阶段拒绝；旧 0.2 回归 |
| 2 目标旧场景等价 | map/精确选择/Decimal/断言齐备，目标 case 在新系统按原业务顺序执行 | 假目标验证两供应商、有序数组、整单运费、权威金额与数量；失败矩阵见下；运行树与变量证据齐全 |
| 3 跨平台和身份 | 业务目录独立，单 case 混用买家/商家/两个后台目标 | 各目标独立假 Host 和账号；一次切换不串会话；晚期目标配置错误零请求拒绝；配置与来源快照完整 |
| 4 UI 混合 | 一个无支付副作用的 API → UI read → API 场景 | 本机页面、两身份、嵌套 flow 共享同身份会话、读值传递、失败截图/取消回收及历史复现 |
| 5 真实业务验收 | 新系统完成目标待支付建单场景 | 用户明确授权后，专用账号与样本；验证真实订单号、预结算金额、数量及 WAIT_PAY，保留结果证据；不提交支付 |

切片 1 应同时产出 Engine describe/validate 和最小结果树，不等全部编排完成后再返工前端。后续新增契约必须先交付 Engine，再按正式远程提交锁更新 Control，不能仅凭本地 editable 通过就宣称可交付。

目标场景失败矩阵至少包含：空 items；非法/零/负数数量；目标商品或 SKU 零匹配/多匹配；供应商字段串行污染；快递未命中/多命中；费用缺失；金额精度边界；建单业务失败；建单成功但预结算超时/金额或数量不符。建单前失败不得创建订单，建单后失败不得重新创建。每个失败都能定位到 flow/map 具体子节点及变量来源，后续步骤的未执行状态准确。

## 10. 已审核的设计方向

用户已审核以下方向，首切片决定见 ADR-005。map、目标映射和 UI 按后续切片细化：

1. 沿用 case / flow 术语与入口限制；业务场景集中展示和维护参数值（用户已澄清），flow 显式输入输出。
2. common/private 作为 case 内的命名空间；公共流程没有隐藏的业务默认取值或全局读写权限。
3. 保留现有 case 级 Web 覆盖和顶层替换规则，集中展示来源、可导出生效参数；“一个文件”不限制底层存储，不排除 Web 持久覆盖。
4. 场景不受单平台树限制；使用显式目标映射冻结多平台配置，先同资产仓库、多工作区，跨仓库引用延后。
5. 第一切片提供公共流程与变量证据的版本化运行树；后续 map 迭代与 UI 沿用相同记录边界。

## 11. 初始需求分析证据与限制（历史快照）

三仓均 main：Control 35f4e26、Engine a4d9500、Assets c41e987。Engine/Assets 干净；Control 仅用户原有未跟踪 PHASE2_3_REVIEW_REPORT.md，未改动。

本轮用现有 Control .venv 中的 PyYAML 仅读取源 YAML 并递归检查 flow/use 与 collection.map：1 case、4 flow、7 API、2 商品项，所有 API 在新 Assets 路径存在。已阅读必要执行实现与 UI/报告边界。没有运行产品测试或业务场景；这是设计盘点证据，不是功能验收证据。没有读取预览凭据、数据库或 env.sh，没有重启预览。

## 12. 切片 1 本地实现证据

Engine 448、Control 本地候选 424、前端 197、Assets 7 项通过，ruff、lint/build 与 diff 检查通过。覆盖同 flow 两次调用隔离、类型化输出、零请求预检拒绝、两层嵌套失败/超时、登录复用及脱敏、历史保存与前端递归展示。当前 case.params 沿用集中默认值存储与顶层覆盖；steps.params 仅维护调用绑定。trace.children 保存子步骤，汇总统计当前声明层。

远程 Engine 锁保持原 SHA，依赖通过 scripts/dev.sh 显式使用本地源码；新增代码未提交，预览服务未更新。自动化和假目标验证不等同浏览器端到端或真实业务验收。完整命令、日志和边界见最新交接。
