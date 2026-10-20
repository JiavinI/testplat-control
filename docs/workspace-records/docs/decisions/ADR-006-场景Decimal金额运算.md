# ADR-006：场景 Decimal 金额运算

状态：已采用（本地候选）
日期：2026-10-20

schema 0.3 增加无网络调用的 `decimal` 步骤，以结构化 operation/operands 表达 add、multiply、sum，sum 可按结构化 path 读取数组各项金额。绑定值沿用 case/flow 局部作用域和成功后发布规则，不加入任意表达式求值。scale 与 rounding 必填；每个步骤在内部精确计算，结束时仅量化一次，结果作为固定小数位 JSON 字符串发布，避免后续传递重新引入二进制浮点误差。

只读核对旧 `testplat-new/src/testplat/engine/functions.py` 的 money_add/money_mul：原语使用 Decimal(str(value))，结束时按 0.01、ROUND_HALF_UP 量化。本地候选显式配置 scale=2、rounding=HALF_UP 可保持这些操作的舍入点；同时支持 HALF_EVEN 和 DOWN，其他业务的舍入规则不得隐式继承。单行舍入与整单舍入可能不同，资产作者必须通过步骤边界表达，不能自动将多个步骤折叠。

输入接受十进制字符串及有限 JSON 数字，拒绝 bool/null、空白、NaN/Infinity 和非十进制字符串。float 仅在边界通过 str 转换，不能恢复上游已经丢失的精度；高精度金额应由字符串提供。sum 空数组为零；负金额允许表示调整，数量必须为正数的业务检查留到断言切片。

计算使用独立 Decimal 上下文；运算范围有明确上限，超限失败而非静默舍入。已知金额在首个请求前预检，响应来源延迟到对应步骤；map 动态项在首个迭代请求前逐项预检。trace.calculations 与 bindings 保存操作、舍入、输入来源及成功/失败证据。Control 展示、正式依赖交付、场景断言和完整业务资产另行实施，不改变旧 Case 0.2。
