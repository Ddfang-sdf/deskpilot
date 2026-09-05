# ISS-0040：【修改引入】list_tools 工具清单构建失败

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0040 |
| 标题 | ISS-0037 增 screenshot 参数 `ocr: ("bool",)` 后,`_input_schema` 的 type_map 缺 "bool" 映射 → list_tools 构建全量抛 KeyError → MCP 客户端「tools fetch failed」,deskpilot 全部工具不可用 |
| 严重级 | **高**(修改引入——最严重最低级;MCP 工具清单是服务可发现性的命脉,一次漏映射全线瘫痪) |
| 状态 | **已修复**(先红后绿:TC-SC-01/02 红→绿;全量回归绿) |
| 提出 | 2026-09-05(sdfang 现场实证:/mcp 面板 deskpilot「△ connected · tools fetch failed」) |

## 1. 认账

2026-09-05 我在 ISS-0037 整改中给 `TOOL_SCHEMAS["screenshot"]` 新增
`"ocr": ("bool",)`,同步补了 `_check_type` 的 "bool" 分支,却**漏了
`_input_schema`(mcp_server.py:241)的 type_map**——该表负责把内部参数
模式转换为 MCP inputSchema,缺键即 `KeyError`,而 list_tools 会为全部
工具逐一构建 schema,于是一次性全线失败。根因:**类型体系的两个消费点
(_check_type 与 _input_schema)未做同步清单核对**;测试面当时只有
TC-SV-06(裸 TOOL_SCHEMAS 形态),没有 inputSchema 构建覆盖——守卫缺位。
修改引入,我负全责;修复同时补 TC-SC-01/02 回归用例(全部工具构建
零异常 + bool→boolean 映射形态)封死此类问题。

## 2. 修复

- `_input_schema.type_map` 增 `"bool": {"type": "boolean"}`,并注释
  注明"type_map 与 _check_type 分支一一对应,新增校验类型必须同步此表";
- 回归用例 `tests/test_inputschema_iss40.py`:TC-SC-01 全部工具
  inputSchema 构建零异常(判别性:任一缺键即红)、TC-SC-02 bool 映射形态。

## 3. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-05 | 建单(现场实证 tools fetch failed;根因=type_map 漏映射,认账)+修复+回归用例,全量 536 过 |
