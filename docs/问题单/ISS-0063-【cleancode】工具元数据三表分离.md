# ISS-0063:【cleancode】工具元数据三表分离——29 个工具的身份散在三个文件

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0063 |
| 标题 | 一个工具的完整身份(schema/安全级别/绑定要求/直放路由)分散登记:TOOL_SCHEMAS(mcp_server)/ TOOL_LEVELS+BINDING_REQUIRED_TOOLS(models)/ _L0_DIRECT+_L1_DIRECT(tools)——新增工具要在 3 个文件登记 5 处,漏一处就是事故 |
| 严重级 | 低(可维护性;已有事故前科) |
| 状态 | **裁定落地(sdfang 离场授权自决 2026-09-22):C(集合恒等钉)立即实施;A(单源注册表派生投影)挂起至下一个新工具单顺手做;B(装饰器)否** |
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

## 评估记录(2026-09-17)

| 项 | 内容 |
|----|------|
| 现状核对 | 仍成立:TOOL_SCHEMAS(mcp_server)/TOOL_LEVELS(models)/_L0_DIRECT+BINDING_REQUIRED(tools)三表各自维护,漂移有事故前科(ISS-0040) |
| 处置 | **待架构师裁定**(系统层面结构变更,超出自主推进边界):方案=工具注册表单源(每工具一条记录携带 schema/level/路由/预算键,三表现态为投影);影响面=mcp_server/tools/models/httpd 四处消费+全部形态钉。请先裁定方向再排期 |

## 裁定(2026-09-22,sdfang 离场留言授权自决,记录在案)

1. **C 立即实施**:集合恒等钉(keys(TOOL_SCHEMAS)==keys(TOOL_LEVELS)、BINDING_REQUIRED_TOOLS⊆schemas、_L0/_L1_DIRECT⊆schemas)——封死 ISS-0040 类漂移事故,成本半天,随本批次落地;
2. **A(单源注册表派生三视图)挂起**:至「下一个必动三表的新工具单」顺手做——声明块落 models.py 或新 registry.py,三表改派生投影同名同形态导出(测试面近零改动,工具新增约 1 个/月,摊销成本,不为此单开大重构);
3. **B(注册装饰器)否**:收益同 A,import 序敏感+装配隐式化风险显著更高。

依据素材:新增工具登记点 5(ISS-0101 实证 6 装配点);钉面=19 测试文件约 100 处,全部按名字 import 三表,同名投影可零适配。
