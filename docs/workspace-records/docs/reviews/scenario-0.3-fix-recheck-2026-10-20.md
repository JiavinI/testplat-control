# 场景0.3引用与预检修复复审

日期：2026-10-20。基线Engine a4d9500，范围包含全部未提交场景候选；修复范围scenario.py和test_scenario.py。

原始三项发现：已知map source搭配动态绑定内部错误；已知flow.outputs缺路径在请求后失败；嵌套assert.expected绕过加载期引用校验。先补回归复现，再保留未知叶占位、递归检查expected、预检所有已知输出路径。合法动态map、动态outputs和嵌套expected仍成功。

复审又复现嵌套flow整体透传混合对象时，整个对象错误折叠为未知：已知missing在2次假请求后失败。新增正反例先运行得到1 failed/1 passed；完整引用保留部分容器结构后，两例通过，missing为InvalidInputError且0请求，合法混合对象完整输出且2请求。

## Standards

独立standards_recheck复审通过。硬性问题0；非阻断判断性气味1：preflight_value路径遍历和既有lookup少量重复，前者用于识别未知叶，不建议本轮扩大重构。解析仍复用resolve_step_params；错误摘要不回显输入，未知占位不进入网络或trace；测试使用既有隔离fixture。

## Spec

独立spec_recheck最终复审通过。三项原始缺陷和混合对象嵌套透传遗漏均已消除，缺失已知路径零请求拒绝，合法动态引用正常执行。独立重跑专项12 passed，先前组合缺口P1撤销，无剩余阻断。

## 验证与放行

- Engine专项12 passed；全量582 passed；ruff check与全源format检查通过。
- Assets全量62 passed，显式加载相邻Engine源码（此时元数据仍0.5.2），不代表已远程交付。
- 所有请求为隔离本机假服务/MockTransport；没有真实GO2请求、真实订单、WAIT_PAY验收或支付。

Standards：硬性0、非阻断1；Spec：0。修复切片放行，继续用户已授权的版本、精确锁与资产启用交付；远程交付证据另行记录。
