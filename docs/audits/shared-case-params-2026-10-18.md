# 共享环境参数消费者与迁移影响清单

只读盘点；不含参数值、Host、账号或凭据。不初始化表、不物化快照、不执行请求。

- 工作区：10；数据库环境：5；非空共享环境：0；共享键：0；分析缺口：0。
- 按资产参数表：尚不存在（未创建）。
- 所有项目均需审查；本报告不授权复制或删除共享值。

## 工作区与版本

| 实际工作区 | 平台／业务项目 | 配置归属 | 归档 | API／Case 数 | Assets SHA |
| --- | --- | --- | --- | --- | --- |
| main/admin_go2 | admin_go2 / go2 | main/admin_go2 | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/admin_go2_e3e3 | admin_go2 / e3e3 | main/admin_go2 | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/daifa_admin | daifa_admin / go2 | main/daifa_admin | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/daifa_admin_e3e3 | daifa_admin / e3e3 | main/daifa_admin | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/daifa_picker | daifa_picker / go2 | main/daifa_picker | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/daifa_picker_e3e3 | daifa_picker / e3e3 | main/daifa_picker | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/e3e3 | e3e3 / e3e3 | main/gsb_e3e3 | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/go2 | go2 / go2 | main/gsb | False | 1 / 0 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/gsb | gsb / go2 | main/gsb | False | 2 / 1 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |
| main/gsb_e3e3 | gsb / e3e3 | main/gsb_e3e3 | False | 2 / 1 | 7a2cc0bb393663bb15ac8573bddb167a90a6eef0 |

## main/admin_go2 · test

环境启用：True；revision：2；共享工作区：main/admin_go2, main/admin_go2_e3e3。

共享 case_params 为空，无需迁移；保留原状。

## main/daifa_admin · test

环境启用：True；revision：2；共享工作区：main/daifa_admin, main/daifa_admin_e3e3。

共享 case_params 为空，无需迁移；保留原状。

## main/daifa_picker · test

环境启用：True；revision：2；共享工作区：main/daifa_picker, main/daifa_picker_e3e3。

共享 case_params 为空，无需迁移；保留原状。

## main/gsb · test

环境启用：True；revision：8；共享工作区：main/go2, main/gsb。

共享 case_params 为空，无需迁移；保留原状。

## main/gsb_e3e3 · test

环境启用：True；revision：3；共享工作区：main/e3e3, main/gsb_e3e3。

共享 case_params 为空，无需迁移；保留原状。

## 分析缺口

无。

## 判读与后续操作

- `api_declared`：Control 表单声明该输入；未声明的共享键不会注入单接口。
- `case_reference`：Engine 校验后的步骤参数明确引用该共享键，包括嵌套路径；`case_injected_without_reference`：共享对象仍传给 Case，但没有发现步骤引用，不等于无消费者。
- 删除影响按无临时输入计算，比较 Git 默认、页面默认、共享环境、资产环境覆盖；`changed`／`removed` 表示有效参数变化，`unchanged` 只代表当前值相同。
- `would_overwrite_existing_override` 必须选择保留或替换；不得自动复制。布尔与数字严格区分，null 作为值。嵌套对象整体替换，不做深合并。
- 类型不符、敏感嵌套键、停用环境、归档工作区或任何分析缺口需单独处理。未引用参数、未发现消费者均不自动授权清空。
- 静态盘点不能代替真实业务验收；确认目标后先在隔离库逐项模拟复制及移除，保留原共享值直至全部消费者验证完成。
