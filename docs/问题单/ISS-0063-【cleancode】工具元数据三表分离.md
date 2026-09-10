# ISS-0063:【cleancode】工具元数据三表分离——29 个工具的身份散在三个文件

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0063 |
| 标题 | 一个工具的完整身份(schema/安全级别/绑定要求/直放路由)分散登记:TOOL_SCHEMAS(mcp_server)/ TOOL_LEVELS+BINDING_REQUIRED_TOOLS(models)/ _L0_DIRECT+_L1_DIRECT(tools)——新增工具要在 3 个文件登记 5 处,漏一处就是事故 |
| 严重级 | 低(可维护性;已有事故前科) |
| 状态 | 建单待排期 |
| 提出 | 2026-09-10(cleancode 审查;实证:schemas 29=levels 29(当前巧合一致),登记点 5 处/工具) |

## 现象与证据

- 同一工具的元数据散 3 文件 5 处登记;
- **前科**:ISS-0040【修改引入】——schema 增 bool 类型而 _input_schema
  类型映射未同步,list_tools 全量 KeyError,MCP 客户端「tools fetch
  failed」——就是"元数据散多处,漏同步一处"的直接事故;
- 单测 TC-SC-01/02 是事后补丁,结构性解法未做。

## 方向

工具注册表单源化:每工具一个声明块(schema+level+binding+路由),
TOOL_SCHEMAS/TOOL_LEVELS/_DIRECT 由注册表派生;加"派生一致性"单测
(集合恒等钉)。约束:对外 schema 形态零变化(MCP 客户端无感)。
