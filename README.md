# testplat-control

测试平台控制面（FastAPI）。

本地路径：`/Users/jiavin/Developer/products/testplat1/testplat-control`

## 项目接口错误

约束冲突返回 409，响应体为 `{"detail": "<可读说明>"}`，不会变成 500。

- 创建或重命名为已存在的项目名称：`detail` 为 `项目名称已存在`。
- 删除仍有执行记录的项目：`detail` 为 `项目存在执行记录，无法删除`。执行历史不会被级联删除。
