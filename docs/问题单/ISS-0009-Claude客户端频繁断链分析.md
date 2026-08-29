# ISS-0009：Claude MCP 客户端频繁断链

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0009 |
| 标题 | Claude Code 与 deskpilot MCP server 之间的连接频繁断开 |
| 严重级 | **高**（断链即工具不可用，且当前用户需手动重启会话恢复） |
| 状态 | **已关闭**（2026-08-29 验收通过：245 用例全绿 + stdout 卫生黑盒通过） |
| 提出 | 2026-08-29（实盘使用反馈） |

## 1. 客户端机制调研（先说清对方怎么工作）

1. **MCP 协议本身没有 keep-alive**：断链判定完全依赖传输层事件——stdin 关闭、
   子进程退出、SIGINT/SIGTERM。**我们的 stdio exe 一旦死亡或关管，客户端即判断链。**
2. **Claude Code 的超时三件套**（环境变量）：
   `MCP_TIMEOUT`（启动/握手超时）、`MCP_TOOL_TIMEOUT`（单次工具执行超时）、
   `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`（远端 idle 超时）。
   另有历史版本 bug：v2.1.148 曾把 stdio 工具调用默认超时压到 1 秒导致长调用全灭。
   含义：**任何超过客户端执行超时的工具调用，都可能被客户端中止并视服务不可用。**
3. stdio 模式会话生命周期=子进程生命周期；客户端进程级崩溃不重连，需重建。

## 2. 我方实现自查（嫌疑按可能性排序）

| # | 嫌疑点 | 实证 | 机理 |
|---|--------|------|------|
| S1 | **同步审批时长(最长 60s)> 客户端执行超时** | ISS-0003 后 L3 调用在 daemon 内同步等待人类裁决至 approval_ttl=60s；`remote_call` 我方超时 90s，但**客户端自身 MCP_TOOL_TIMEOUT 更短** | 用户在审批窗前思考超过客户端超时 → 客户端中止调用并可能降连接健康度；单线程 daemon 期间连 L0 也排队超时（与 ISS-0008-C1 同根） |
| S2 | **冷启动 > 启动/握手超时** | onefile 解压 2-4s + RapidOCR 急切初始化 1-3s + 策略/审计/热键装配，合计可达 6-10s（AV 扫描时更高） | 新会话拉起 stdio exe 或健康检查冷探时超过 MCP_TIMEOUT → 直接显示未连接 |
| S3 | **未捕获异常杀死进程 → 传输层关闭** | ISS-0006 §7 实证：`Executor.move` 未捕获 pyautogui FailSafeException，HTTP handler 断连；stdio 路径同类异常=进程死亡 | 进程死 = stdin 关 = 客户端判断链（MCP 无 keep-alive，无法区分"崩了"与"下线"） |
| S4 | **stdout 污染破坏 JSON-RPC 帧** | MCP stdio 要求 stdout 只载 JSON-RPC；我方日志走 stderr，但第三方库（uiautomation/comtypes/rapidocr）可能向 stdout 直写 | 一帧坏帧 → 客户端解析失败 → 关闭连接 |
| S5 | **onefile 临时目录竞态** | 曾实证 _MEIPASS2 共享解压目录被子进程/清理策略删除导致 _overlapped 缺失崩溃（已通过剥离 _MEIPASS2 缓解，未系统验证长驻稳定性） | daemon 长驻期间临时文件被清 → 进程崩 → 断链 |
| S6 | **健康检查冷探成本** | `claude mcp list` 每次全新拉起 exe（6-10s 冷启动） | 冷探超时 → 误显示未连接（非真断，但观感等同） |

## 3. 整改方案

### 3.1 总体

三原则：**慢调用走协议允许的长任务语义（进度通知），快路径永远快（冷启动达标），
任何异常不许杀死进程（崩=断链）。** 断链恢复零成本（状态全在 daemon，stdio 重启即续）。

### 3.2 整改项

| 项 | 内容 | 对应 |
|----|------|------|
| A | **长调用进度通知**：审批等长阻塞调用改用 MCP progress notifications（progressToken 周期上报"等待人类裁决中"），协议兼容客户端收到进度会重置执行超时；不支持进度的客户端回退当前同步等待 | S1 |
| B | **超时预算表与告警**：服务端为每类工具声明内部时限（L0 <5s、写操作 <15s、审批 <approval_ttl），临期先回结构化"处理中"错误而非硬撑到客户端超时；README 增补推荐配置 `MCP_TOOL_TIMEOUT=120000` | S1/S6 |
| C | **进程不死身**：① httpd handler catch-all（未处理异常回 500 结构化错误，不断连）；② 执行层像素系调用统一捕获三方异常 → ExecutorError；③ stdio 服务主循环 catch-all 保活 | S3 |
| D | **stdout 卫生**：stdio 模式下所有我方 print 强制 stderr；启动时重定向第三方库 stdout（uiautomation/comtypes 噪音进 stderr）；加卫生测试 | S4 |
| E | **冷启动达标**：依赖 ISS-0008 P2（OCR 懒加载）+ P5（打包裁剪），目标 stdio exe 冷启动握手 < 3s（裸机 < 2s） | S2/S6 |
| F | **长驻稳定性验证**：daemon 连续运行 72h 巡检脚本（/health + L0 调用每小时），确认临时目录与内存无劣化 | S5 |
| G | **断链零成本化（验证并文档化）**：stdio exe 被杀后重拉 → 探测 daemon → 绑定/急停/SoM 状态全续（ISS-0001 既有语义），写进 README"断链后无需任何手工恢复" | 恢复面 |
| H | **daemon 版本握手与自愈重启**（借鉴 agent-browser connection.rs 边车文件协议）：daemon 启动时在审计目录写 `daemon.version`；stdio 瘦代理探测 daemon 时比对自身版本，**不一致则自动经 /estop 安全通道请求旧 daemon 退出并就地重启新 daemon**（状态文件协议不变，绑定在旧 daemon 内存中的状态按 TTL 自然过期语义处理并记审计）——exe 升级后不再依赖人肉重启 daemon，消除"新版 exe 转发到旧版 daemon"的隐形断链/语义漂移 | 恢复面 |

### 3.3 约束

- A 的进度通知必须以 MCP SDK 官方 API 实现（server.request_context / progress），不私有造帧。
- C 的 catch-all 不得吞掉结构化错误语义（已知错误码原样透传，仅未知异常包装 500）。
- 所有修复以"不断链"为验收：协议级故障必须能在不重拉进程的情况下继续下一调用。

## 4. 测试方案

### 4.1 单元（先行）

| 用例 | 断言 |
|------|------|
| 进度通知 | 长阻塞调用期间客户端收到 ≥1 次 progress（间隔 ≤ 配置值）；裁决完成后结果正常返回 |
| 时限预算 | 注入超时工具 → 临期返回结构化"处理中"错误码而非悬挂 |
| 不死身 | 注入 executor 未知异常 → /call 回 500 结构化错误，下一调用正常；stdio 路径同类注入进程仍活 |
| stdout 卫生 | 一次完整 stdio 会话抓 stdout，逐行 JSON 解析无坏帧 |
| 版本握手自愈 | daemon 写 version 文件可读；版本不一致的探测触发"旧 daemon 退出 + 新 daemon 拉起"且过程记审计 |
| 冷启动预算 | stdio exe 从启动到 initialize 完成 < 3s（CI 计时门禁） |

### 4.2 集成验收

- 全量 pytest 绿（现有 222 + 新增）
- 实盘：Claude 会话中发起 L3 审批并静置 90s 后批准 → 调用正常返回，无断链
- 实盘：强杀 stdio 客户端进程后重开会话 → 绑定窗口继续可用，用户无感知
- 72h 长驻巡检零失败

## 5. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-08-29 | 建立问题单（客户端机制调研/嫌疑 S1~S6/方案 A~G/测试），待评审 |
| v0.2 | 2026-08-29 | 经 agent-browser 源码对照研究（Rust 单二进制 + tokio daemon + 边车文件发现协议），补方案 H（daemon 版本握手与自愈重启）；确认 C/D/E 方向与其 stderr 管道纪律、socket 全超时实践一致 |
| v0.3 | 2026-08-29 | 开工前补 §6 接口定义（SDD 公开入口）；E（冷启动达标）已由 ISS-0008 覆盖（懒加载+裁剪，就绪 3.2s），本单不再单列实现项，以 H 项验收复测 |
| v0.4 | 2026-08-29 | SDD 整改完成：TC 11 条先行 → A~H 落地 → 245 用例全绿。A 进度通知接入 stdio 服务（须客户端 progressToken 方发，防御空转）；B 级别预算 L0=5/L1=15/L2=30s、L3=approval_ttl+5，临期回 TOOL_TIMEOUT；C httpd 未知异常兜底 500 不断连 + execute 三方异常收敛（FailSafeException→EMERGENCY_STOP、未知→INTERNAL_ERROR）；D stdout 卫生黑盒通过（stdio 会话全帧合法 JSON-RPC）；G 状态跨会话回归通过；H /version 端点 + daemon.version 握手文件 + check_daemon_version；F 交付 scripts/daemon_soak.py 巡检脚本；README 增补 MCP_TOOL_TIMEOUT=120000 与断链零成本说明。 |

## 6. 接口定义（SDD 公开入口；测试只允许调用以下入口）

### mcp_server（A 进度通知 / B 超时预算）

| 入口 | 签名 | 语义 |
|------|------|------|
| `call_with_progress`（新增） | `async (work, report, interval_s: float, clock) -> Any` | 周期触发进度回调直到 work 完成；返回 work 结果；用于 stdio 服务在长调用（L3 同步审批等）期间向客户端发 MCP progress notifications |
| `TOOL_TIME_BUDGETS`（新增，models） | `Mapping[str, float]`，键为级别（"L0"/"L1"/"L2"/"L3"） | 各级别内部时限预算（秒）：L0=5、L1=15、L2=30、L3=approval_ttl；临期返回结构化 `TOOL_TIMEOUT`"处理中"错误而非悬挂 |
| `TOOL_TIMEOUT`（新增错误码，errors） | `str` | 超时预算触发时的错误码 |

### httpd（C 不死身 / H 版本握手）

| 入口 | 签名 | 语义 |
|------|------|------|
| handler `/call`（行为变更） | — | 未处理异常兜底回 500 + 结构化错误码（已知错误码原样透传，不断连） |
| `/version`（新增端点） | `GET -> {"version": str}` | 返回 daemon 版本（包版本） |
| `check_daemon_version`（新增） | `(host, port, expected: str, timeout=0.3) -> bool` | 探测 /version 并与期望版本比对；探测失败按不匹配处理 |
| `VERSION_FILE`（新增常量） | `str`，值 `"daemon.version"` | daemon 启动时在审计目录写入版本号文件 |

### executor（C 不死身）

| 入口 | 签名 | 语义 |
|------|------|------|
| `execute`（行为变更） | 同现签名 | 像素系调用统一捕获三方库异常（pyautogui.FailSafeException 等）→ ExecutorError(EMERGENCY_STOP)；其他未知异常 → ExecutorError(INTERNAL_ERROR)，不再裸抛 |

### 断链零成本（G，回归约束）

| 入口 | 签名 | 语义 |
|------|------|------|
| `/call` attach→写操作跨调用 | — | daemon 持有绑定等内存态跨客户端会话保持（回归断言：跨两次独立 HTTP 会话绑定仍有效） |

参考：Claude Code MCP 超时环境变量与已知问题（[MCP_TOOL_IDLE_TIMEOUT 文档缺失](https://github.com/anthropics/claude-code/issues/70441)、[stdio 1s 超时 bug](https://github.com/anthropics/claude-code/issues/62121)、[handshake 超时](https://github.com/anthropics/claude-code/issues/47400)、[MCP_TOOL_TIMEOUT 提案](https://github.com/anthropics/claude-code/issues/47076)）；MCP 协议无 keep-alive，断链依赖传输事件（stdin 关闭/进程退出）。
