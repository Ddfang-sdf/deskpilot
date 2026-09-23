"""审计事件词汇表(ISS-0060,EV_* 常量单源)。

立规:
- EV_* 常量值**即落盘 JSONL 事件文本**,改值=改历史数据格式,
  必须另立问题单评审(历史可比性硬约束,TC-60-03 钉板看守);
- 新增审计事件:先在本模块注册 EV_* 常量,再在调用点引用
  (TC-60-01 结构守卫:调用点禁裸串字面量/条件造名/拼接造名);
- 中英文混排名保持原样(裁决②);值英文化涉历史数据迁移策略,另立单。

清单口径:§0 表 41 种 + 表落档后 ISS-0094/0095 新增 5 种 = 46 种
(差额已在问题单登记;值逐字转录,TC-60-03 逐字看守)。
"""

# ---- 服务与策略(main/policy) ----
EV_SERVICE_START = "服务启动"
EV_SERVICE_STOP = "服务停止"
EV_POLICY_LOADED = "策略加载"
EV_POLICY_FINGERPRINT = "策略指纹"
EV_POLICY_LOCAL_FINGERPRINT = "用户策略数据指纹"
EV_POLICY_EXTERNALLY_MODIFIED = "策略文件被外部修改"
EV_POLICY_LOCAL_EXTERNALLY_MODIFIED = "用户策略数据被外部修改"
EV_POLICY_MIGRATED = "入白迁移"

# ---- 急停与轮询(main/estop) ----
EV_HOTKEY_REGISTER_FAILED = "急停热键注册失败"
EV_HOTKEY_REGISTERED = "急停热键注册"
EV_CORNER_LOOP_ERROR = "甩角轮询异常"
EV_ESTOP_TRIGGERED = "急停触发"
EV_ESTOP_RESET = "急停复位"
EV_RESET_NOOP_NOT_FROZEN = "复位请求-未冻结"

# ---- 属主与心跳(main/ownership) ----
EV_DAEMON_SINGLETON_EXIT = "daemon 单例退出"
EV_DAEMON_DEATH_ALARM = "daemon 死亡告警"
EV_OWNER_BIND_9420_FAILED = "属主 9420 绑定失败"
EV_STDIO_BECOME_OWNER = "stdio 升属主"
EV_STDIO_TAKEOVER_OWNER = "stdio 接管属主"
EV_STDIO_CEDE_OWNER = "stdio 属主让位"
EV_PROCESS_EXIT = "进程退出"
EV_AUTOSTART_REGISTERED = "开机自启注册"
EV_PROXY_SKIPS_HOTKEY = "瘦代理跳过热键注册"
EV_HEARTBEAT_WRITE_FAILED = "心跳写失败"
EV_HEARTBEAT_WRITE_RECOVERED = "心跳写恢复"

# ---- 审批与入白(enforcement/whitelist_admin/tools) ----
EV_ENROLL_EVIDENCE_WINDOWS = "入白取证窗口明细"
EV_APPROVAL_SHOT_FAILED = "审批取图失败"
EV_WHITELIST_ENROLLED_PERMANENT = "白名单入白-永久"
EV_WHITELIST_REMOVED = "白名单移除"
EV_WHITELIST_REMOVED_VIA_AI = "白名单移除-经AI请求"
EV_WHITELIST_DATA_ASSEMBLED = "白名单数据装配"

# ---- 执行与状态(executor/freeze_notify) ----
EV_STARTUP_KEY_SWEEP = "启动抬键清扫"
EV_STARTUP_KEY_SWEEP_FAILSAFE = "启动抬键清扫-FAILSAFE拦截"
EV_MOUSE_KEY_SELF_HEAL = "悬空按键自愈"
EV_SCREENSHOT_OVERWRITE = "screenshot覆盖写"
EV_SHARED_STATE_RECONCILED = "共享状态对账修复"
EV_SHARED_STATE_WRITE_FAILED = "共享状态写失败"

# ---- 安全桌面(secure_desktop/tools) ----
EV_SECURE_DESKTOP_REJECTED = "安全桌面拒绝"
EV_SECURE_DESKTOP_CHECK_FAILED = "安全桌面检测失效"
EV_SECURE_DESKTOP_ACTIVATED = "安全桌面激活"
EV_SECURE_DESKTOP_EXITED = "安全桌面退出"

# ---- 启动装配观测(ISS-0064) ----
EV_STARTUP_STAGE = "启动段"

# ---- 清理与观测(janitor/ISS-0095) ----
EV_SCREENSHOT_CLEANUP = "截图清理"
EV_SCREENSHOT_CLEANUP_ERROR = "截图清理异常"
EV_AUDIT_LOG_CLEANUP = "审计日志清理"
EV_MANAGER_WINDOW_LAUNCH = "管理窗拉起"
EV_NAME_CACHE_WARMED = "名称缓存暖机"
