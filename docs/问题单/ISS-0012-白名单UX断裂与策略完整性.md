# ISS-0012：白名单 UX 断裂与策略完整性——运行时审批入白

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0012 |
| 标题 | 非白名单软件"改 YAML 再重启"的 UX 断裂（启动批了却不让操作）；拒绝文案直授提权路径；policy.yml 可被 AI 经白名单应用静默编辑 |
| 严重级 | **中**（功能可用但体验断裂自相矛盾；策略完整性属纵深防御缺口，非威胁模型内失效） |
| 状态 | 开发完成待实盘验收（2026-08-31：方案 A~E 实现完毕，新增 34 用例 + 全量 323 用例全绿；托盘图标可见性/三态弹窗实盘/管理窗口实盘待 §4.2 验收） |
| 提出 | 2026-08-31（sdfang 设计质疑：白名单形同虚设/用户不该感知白名单/黑名单化之议） |

## 1. 问题现状

1. **UX 断裂自相矛盾**：`launch_app` 启动非白名单进程已走 L3 审批
   （`enforcement.py:81-83`，人类批准即可启动）；但启动后 attach/点击仍被闸二
   NOT_WHITELISTED 拍死（`enforcement.py:88-92`），AI 只能回复用户"去改
   policy.yml 并重启服务"。**批准了启动却不让操作**；且用户（集成方）根本
   不知道、也不该知道 policy.yml 的存在与写法。
2. **拒绝文案直授提权路径**：闸二拒绝消息原文"请人类管理员在 policy.yml 的
   whitelist 节添加该进程并重启服务"（`enforcement.py:91-92`）。该文本被 AI
   完整读取，等于把"如何把自己加进白名单"的攻击说明递给 AI（含被注入的
   AI）——提示注入放大器。
3. **policy.yml 可被 AI 静默编辑**：notepad.exe 为 L2 白名单条目，AI 经其
   打开/编辑 policy.yml **全程无需审批**；当前唯一实质防线是 INV-9
   （`policy.py:3` 运行期只读不重载，改了须重启才生效）。但终端类 attach 即
   L3（`enforcement.py:71-72`），逐条审批后 AI 可在终端 taskkill 并重启
   daemon——**完整提权链在威胁模型"防犯错不防作恶"之外、但路径已被现状
   文案明示**；且编辑动作本身无任何审计/告警。
4. **黑名单化之议（提出方备选）**：默认放行、只禁个别软件。经分析**不推荐**：
   危险软件不可枚举（regedit/浏览器存密/远控/银行/安全软件/钱包……），
   默认放行把系统从 fail-closed 反转为 fail-open，推翻 INV-2 与产品
   "安全不靠 AI 自觉"的立身之本；且对 UX 问题的解决力不优于审批入白。
   此议留作评审备选，由人类裁决。

## 2. 根因分析

| # | 根因 | 说明 |
|---|------|------|
| R1 | **白名单变更只有静态通道** | INV-9 只读不重载 + 唯一变更方式是手编 YAML，没有"运行时经人类裁决扩容"的动态通道；launch_app 的 L3 升级是只做了半拉的动态通道（批了启动不给操作）。 |
| R2 | **错误消息越权教学** | 拒绝文案把管理员操作手册写进了给 AI 的响应，违背"AI 只需知道被拒、无需知道如何解拒"的最小知情原则。 |
| R3 | **策略文件完整性无观测** | 启动加载不记录文件指纹，运行期变更无审计无告警，静默编辑不可见。 |

## 3. 整改方案

### 3.1 总体

**把"改 YAML"变成"审批入白"**：非白名单进程统一走既有 L3 本地审批通道，
人类三选（本次允许 / 永久加入白名单 / 拒绝）；永久加入由**系统**写
policy.yml（非 AI），全程审计；拒绝文案去教学化；策略文件指纹入审计。
fail-closed 语义不变：无人类点头，非白名单依旧一律拒绝。

### 3.2 整改项

| 项 | 内容 |
|----|------|
| A | **运行时审批入白**：闸二 NOT_WHITELISTED 由"硬拒"改为"升 L3 走审批"；审批弹窗文案含进程名、路径、请求操作级别，选项三态：① 本次允许（会话级放行，内存态，重启失效）② 永久加入白名单（系统写 policy.yml 的 whitelist 节并热生效，原子写+备份）③ 拒绝。launch_app 的既有 L3 升级并入同一通道（批启动=批该进程，消除半成品矛盾）。 |
| B | **拒绝文案去教学化**：NOT_WHITELISTED / 相关拒绝消息只陈述"目标进程未经本地授权"，删除一切关于 policy.yml 写法/重启的指引； INSTALL.md 的管理员指引保留（面向人类文档不变）。 |
| C | **策略完整性审计**：启动加载时计算 policy.yml SHA-256 写入审计（含路径与条目数）；运行期每 60s 轮询文件指纹，变更即写审计事件"策略文件被外部修改"（不自动重载、不冻结，仅留痕告警）。 |
| D | **系统写策略而非 AI**：永久入白的 policy.yml 修改由 daemon 进程内函数完成（读-改-写原子化，先写 .bak）；AI 全程无策略写路径。 |
| E | **全可视化管理（零命令，2026-08-31 修订，否决原 CLI 路线）**：E1 daemon 系统托盘图标（右键菜单：白名单管理 / 运行状态；ctypes Shell_NotifyIconW，不引第三方依赖）——同时解决 daemon 运行不可见的潜伏问题；E2 白名单管理窗口（tkinter，复用弹窗进程模式）：列出静态+会话条目，逐行 [移出]，会话区 [全部清空]，一切变更由 daemon 原子写 policy.yml + 审计，数据经本机 127.0.0.1 HTTP 端点；E3 AI 请求撤回弹窗（用户说"别动 X"时，弹窗"是否将 X 移出白名单？[移出/保留]"，特权收缩 fail-safe）；E4 入白确认自带 [撤销]（"已加入白名单 [撤销]"，误点立撤）。 |

### 3.3 约束

- fail-closed 不变：审批通道不可用（DenyAll/超时/冻结）时非白名单依旧一律拒绝。
- 会话级放行仅内存态，不落盘；永久入白落盘必须经弹窗人类显式选择。
- 不引入黑名单机制（本单否决该备选，除非评审人类推翻）。
- 终端类进程（terminal_apps）**不适用**审批入白：维持 attach 即 L3 且逐操作审批的现有语义，禁止"永久入白终端"。
- **自保护铁律（2026-08-31 新增）**：`deskpilot.exe` 自身及弹窗/管理窗口进程**永远不可入白、attach 即硬拒**——防止 AI 用 deskpilot 自己的工具点击管理窗口自我加白。
- **管理零命令（2026-08-31 新增）**：白名单全部管理动作（加入/撤回/清空会话）只经 GUI（弹窗/托盘/管理窗口），不向用户提供任何需要记忆与手敲的命令；HTTP 端点为管理窗口内部通道，仅绑 127.0.0.1。
- 单白名单/黑盒行为变化须同步 README/INSTALL/DESIGN 文档（INV-2 语义调整）。

### 3.4 备选方案（供评审裁决，不推荐）

黑名单化（默认放行+枚举禁止）：见 §1.4 不推荐理由。若评审选择此路，需另立
危险软件枚举清单与级别映射设计，本单方案 A~D 作废。

## 4. 测试方案

### 4.1 单元/集成（先行）

| 用例 | 断言 |
|------|------|
| 非白名单升 L3 | 注入非白名单进程 attach → 不返回 NOT_WHITELISTED 硬拒，而是触发审批通道调用（替身记录进程名/级别直出） |
| 本次允许 | 审批器回 approve-once → 同进程后续操作放行；新 Executor 实例（模拟重启）→ 恢复拒绝 |
| 永久入白 | 审批器回 approve-always → policy.yml 落盘含新条目（数据层断言：文件内容含进程名+级别）、.bak 备份存在、审计含入白事件；同进程操作放行 |
| 拒绝与超时 | 审批器回 deny/timeout → 操作拒绝；审计含拒绝事件 |
| 终端豁免 | 对 terminal_apps 成员触发入白审批 → 不出现"永久加入"选项语义（直接维持逐操作 L3） |
| 文案去教学 | 全部面向 AI 的错误消息不含 "policy.yml" 字样（grep 级断言响应体） |
| 指纹审计 | 启动审计含 sha256 字段且与文件重算一致；运行期改文件 → 60s 内出现"策略文件被外部修改"审计事件 |
| 管理数据端点 | GET 白名单端点返回静态+会话两组条目（集成：真实 HTTP 响应体直出） |
| 端点撤回 | POST 移除静态条目 → policy.yml 无该条目（数据层直出）、.bak 备份在、内存态即时生效（同进程 attach 被拒）、审计含移除事件；清空会话端点 → 会话条目清零 |
| 入白撤销键 | 审批器回 approve-always 后触发撤销 → policy.yml 回到原样（数据层直出）、操作恢复拒绝 |
| 自保护 | attach deskpilot.exe → 硬拒且不触发入白审批（断言拒绝码直出）；弹窗进程同理 |
| 托盘菜单 | 菜单项→动作映射（单元：纯函数直出）；图标可见性留实盘验收 |

### 4.2 集成验收

- 全量 pytest 绿（现有 289 + 新增）
- 实盘：让 AI 操作白名单外软件（如 Excel）→ 弹窗三态可选；选"永久加入"后重开对话直接可操作，policy.yml 已含条目，全程用户未碰 YAML
- 实盘：托盘右键 → 白名单管理 → 移出 Excel → AI 再操作即回到审批/拒绝；会话条目 [全部清空] 即时生效
- 实盘：DenyAll 通道（无弹窗形态）下非白名单依旧硬拒；AI attach deskpilot 自身窗口硬拒

## 5. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-08-31 | 建立问题单（现状 1~4 实证：enforcement.py:81-92/policy.py:3；根因 R1~R3；方案 A~D/备选/测试），待评审 |
| v0.2 | 2026-08-31 | sdfang 批准 A~D+E3；否决 CLI 管理路线（"用户当成白痴，任何难用的点都应该消除"），E 修订为全可视化：托盘图标+管理窗口+入白撤销键+E3 撤回弹窗；新增自保护铁律（deskpilot.exe 不可入白）与管理零命令约束 |
| v0.3 | 2026-08-31 | 开工前补 §6 接口定义（SDD 公开入口） |
| v0.4 | 2026-08-31 | A~E 实现完成：whitelist_admin（三态+原子写盘+自保护）、闸二入白审批流、弹窗三态、/whitelist 三端点、管理窗口、入白撤销 toast、撤回确认通道、托盘图标、指纹审计与守望、request_remove_from_whitelist 工具；DESIGN/功能/详细/测试设计/README/INSTALL/RELEASE_NOTES 同步；新增 34 用例，全量 323 全绿 |

## 6. 接口定义（SDD 公开入口；测试只允许调用以下入口）

### whitelist_admin（新增模块 `deskpilot/whitelist_admin.py`）

| 入口 | 签名 | 语义 |
|------|------|------|
| `NEVER_ENROLL` | `frozenset[str]` | 永不可入白进程集（含 `"deskpilot.exe"`，自保护铁律） |
| `file_sha256` | `(path: str) -> str` | 文件 SHA-256 小写 hex（C 指纹用，纯函数） |
| `WhitelistAdmin` | `(policy_path: str, static: Mapping[str,str], never_enroll=NEVER_ENROLL, audit=None)` | 运行期白名单状态：静态（含永久热生效）+ 会话两视图 |
| `cap_of` | `(process: str) -> str \| None` | 进程级别上限（静态∪会话合并视图；进程名小写归一） |
| `add_session` | `(process: str, level: str = "L2") -> None` | 会话放行（仅内存）；never_enroll 命中 → PolicyError |
| `add_permanent` | `(process: str, level: str = "L2") -> None` | 原子写 policy.yml（先写 .bak）+ 内存热生效 + 审计"白名单入白-永久"；never_enroll 命中 → PolicyError |
| `remove` | `(process: str) -> str \| None` | 撤回：命中静态 → 原子改盘 + 审计"白名单移除"，返回 "static"；命中会话返回 "session"；未命中 None |
| `clear_session` | `() -> int` | 清空会话放行，返回清除条数 |
| `entries` | `() -> dict` | `{"static": {proc: level}, "session": {proc: level}}` |

### approval / enforcement（A 审批入白）

| 入口 | 签名 | 语义 |
|------|------|------|
| `ApprovalChannel.request`（行为变更） | 新增可选参 `enroll: str \| None = None`；返回值域扩 `"approve_always"` | enroll 非 None 时为入白审批（三态语义）；DenyAll 恒 deny 不变 |
| `ApprovalManager.request_enroll`（新增） | `(process, description, fingerprint, image_path=None, target_rect=None) -> str` | 入白审批；"approve"/"approve_always" 均签发令牌（当前操作即放行） |
| `Enforcement`（行为变更） | 构造新增可选参 `whitelist_admin=None` | 闸二未命中且非终端/非自保护 → 走 request_enroll；approve→add_session、approve_always→add_permanent；自保护进程硬拒；拒绝文案不含 "policy.yml" |

### approval_dialog / approval_ui（A 弹窗三态）

| 入口 | 签名 | 语义 |
|------|------|------|
| `build_window`（行为变更） | 新增可选参 `enroll: str \| None = None` | enroll 非 None：三按钮「本次允许 / 永久加入 / 拒绝」+ 入白文案（含进程名）；结果文件合法值扩 `"approve_always"` |
| `TkApprovalChannel.request`（行为变更） | 透传 enroll 与 "approve_always" | 结果文件非法内容仍按 deny（fail-closed） |

### httpd（E2 管理端点，仅 127.0.0.1）

| 入口 | 语义 |
|------|------|
| `GET /whitelist` | `{"ok":true,"data":{"static":{...},"session":{...}}}` |
| `POST /whitelist/remove` `{"process": str}` | daemon 撤回；`data.removed` ∈ "static"/"session"/null |
| `POST /whitelist/clear_session` | 清空会话；`data.cleared` 条数 |

### whitelist_window（E2 新增模块 `deskpilot/whitelist_window.py`）

| 入口 | 签名 | 语义 |
|------|------|------|
| `build_window` | `(parent, entries: dict, on_remove, on_clear_session)` | 管理窗口：静态/会话分组列出，逐行 [移出]、会话区 [全部清空] |
| `build_enroll_notice` | `(parent, process: str, on_undo)` | E4 入白确认 toast：「已加入白名单 [撤销]」 |
| `main` | `() -> None` | `--whitelist-manager <base_url>` 进程入口：经 HTTP 拉取/操作 |

### tray（E1 新增模块 `deskpilot/tray.py`）

| 入口 | 签名 | 语义 |
|------|------|------|
| `menu_items` | `() -> tuple[tuple[str, str], ...]` | 菜单模型纯函数：(动作ID, 显示名)，含 ("manage", ...) |
| `TrayIcon` | `(on_manage, tooltip="DeskPilot")` | start()/stop()；ctypes Shell_NotifyIconW，不引第三方依赖 |

### tools（E3 AI 请求撤回）

| 入口 | 签名 | 语义 |
|------|------|------|
| `request_remove_from_whitelist`（新工具，L1） | `(process: str) -> {"removed": bool}` | 弹本地确认窗「是否移出 X？[移出/保留]」（15s 默认保留）；移出 → admin.remove + 审计；保留/超时 → removed=False |

### main（C 指纹审计与装配）

| 入口 | 签名 | 语义 |
|------|------|------|
| `policy_sha256_audit`（新增，模块级公开函数） | `(policy_path: str, audit) -> str` | 启动指纹审计：算 sha256 写审计"策略指纹"，返回指纹 |
| `_start_policy_watch`（新增） | `(policy_path, audit, interval=60.0, fingerprint="") -> threading.Thread` | 周期比对指纹，变更写审计"策略文件被外部修改"（不重载不冻结） |
