"""ISS-0060 审计事件词汇单源化守卫钉(TC-60-01~03,问题单 §3 测试设计)。

层级:TC-60-01 形态/结构守卫(ast 直出,无正则);TC-60-02/03 单元
(常量值直出)。
入口(出处):deskpilot/audit_events.py EV_* 词汇表;
deskpilot/**/*.py 的 record_event/_event/event_name 三形态调用点。
断言出处:ast 节点集合直出/常量值直出/钉板字面量逐字比对。

红绿属性(S0 先红后绿):TC-60-01 红(约 50 处裸串,S2 逐文件收缩);
TC-60-02 红(空壳);TC-60-03 红(词汇表未建)。
词汇表口径:§0 表 41 种 + 表落档后 ISS-0094/0095 新增 5 种
(心跳写失败/心跳写恢复/管理窗拉起/名称缓存暖机/白名单数据装配)
=46 种(差额已在单据登记,非转录遗漏)。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "deskpilot"

CALL_FORMS = ("record_event", "_event")   # whitelist_admin._event 包装透传
EXEMPT = {"audit_events.py"}              # 词汇表自身豁免


def _literal_issues(path: Path) -> list[str]:
    """三形态裸串审计(ast 直出):①调用第一位置参 str 字面量;
    ②第一位置参条件表达式/拼接造名;③event_name 默认参/关键字传参裸串。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fname = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else "")
            if fname in CALL_FORMS and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    issues.append(f"{path.name}:{node.lineno} 裸串字面量")
                elif isinstance(a0, ast.IfExp):
                    issues.append(f"{path.name}:{node.lineno} 条件表达式造名")
                elif isinstance(a0, ast.JoinedStr):
                    issues.append(f"{path.name}:{node.lineno} 拼接造名")
            for kw in node.keywords:
                if (kw.arg == "event_name"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):
                    issues.append(
                        f"{path.name}:{node.lineno} event_name 传参裸串")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = node.args.args
            for arg, default in zip(
                    positional[len(positional) - len(node.args.defaults):],
                    node.args.defaults):
                if (arg.arg == "event_name"
                        and isinstance(default, ast.Constant)
                        and isinstance(default.value, str)):
                    issues.append(
                        f"{path.name}:{node.lineno} event_name 默认参裸串")
            for arg, default in zip(node.args.kwonlyargs,
                                    node.args.kw_defaults):
                if (arg.arg == "event_name"
                        and isinstance(default, ast.Constant)
                        and isinstance(default.value, str)):
                    issues.append(
                        f"{path.name}:{node.lineno} event_name 默认参裸串")
    return issues


class TestNoLiteralEventNames:
    """TC-60-01(形态/结构守卫):新审计事件必须经词汇表注册。"""

    def test_tc60_01_no_literal_event_names_in_call_sites(self):
        """TC-60-01:ast 遍历 deskpilot/ 全部 .py,record_event/_event
        第一位置参与 event_name 默认参/传参不得为 str 字面量/条件表达式/
        拼接造名(audit_events.py 豁免)。
        断言:违规节点清单由 ast 直出(无正则、无中间转换)。
        红→绿路径:S0 红(约 50 处)→S2 十二文件常量化后收缩至零。"""
        hits: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            if path.name in EXEMPT:
                continue
            hits.extend(_literal_issues(path))
        assert hits == [], \
            "审计事件名裸串(应改引 deskpilot.audit_events EV_*):\n" + \
            "\n".join(hits)


# ---- TC-60-02/03 词汇表与落盘文本冻结 ----

# 钉板:常量名 → 落盘文本(逐字;改值即红,护历史 JSONL 可比性)。
# 刻意的字面量重复(值冻结职责所在,TC-60-03 单点字钉,§5 裁决③)。
FREEZE: dict[str, str] = {
    "EV_SERVICE_START": "服务启动",
    "EV_SERVICE_STOP": "服务停止",
    "EV_POLICY_LOADED": "策略加载",
    "EV_POLICY_FINGERPRINT": "策略指纹",
    "EV_POLICY_LOCAL_FINGERPRINT": "用户策略数据指纹",
    "EV_POLICY_EXTERNALLY_MODIFIED": "策略文件被外部修改",
    "EV_POLICY_LOCAL_EXTERNALLY_MODIFIED": "用户策略数据被外部修改",
    "EV_POLICY_MIGRATED": "入白迁移",
    "EV_HOTKEY_REGISTER_FAILED": "急停热键注册失败",
    "EV_HOTKEY_REGISTERED": "急停热键注册",
    "EV_CORNER_LOOP_ERROR": "甩角轮询异常",
    "EV_ESTOP_TRIGGERED": "急停触发",
    "EV_ESTOP_RESET": "急停复位",
    "EV_RESET_NOOP_NOT_FROZEN": "复位请求-未冻结",
    "EV_DAEMON_SINGLETON_EXIT": "daemon 单例退出",
    "EV_DAEMON_DEATH_ALARM": "daemon 死亡告警",
    "EV_OWNER_BIND_9420_FAILED": "属主 9420 绑定失败",
    "EV_STDIO_BECOME_OWNER": "stdio 升属主",
    "EV_STDIO_TAKEOVER_OWNER": "stdio 接管属主",
    "EV_STDIO_CEDE_OWNER": "stdio 属主让位",
    "EV_PROCESS_EXIT": "进程退出",
    "EV_AUTOSTART_REGISTERED": "开机自启注册",
    "EV_PROXY_SKIPS_HOTKEY": "瘦代理跳过热键注册",
    "EV_HEARTBEAT_WRITE_FAILED": "心跳写失败",
    "EV_HEARTBEAT_WRITE_RECOVERED": "心跳写恢复",
    "EV_ENROLL_EVIDENCE_WINDOWS": "入白取证窗口明细",
    "EV_APPROVAL_SHOT_FAILED": "审批取图失败",
    "EV_STARTUP_KEY_SWEEP": "启动抬键清扫",
    "EV_STARTUP_KEY_SWEEP_FAILSAFE": "启动抬键清扫-FAILSAFE拦截",
    "EV_MOUSE_KEY_SELF_HEAL": "悬空按键自愈",
    "EV_SCREENSHOT_OVERWRITE": "screenshot覆盖写",
    "EV_SHARED_STATE_RECONCILED": "共享状态对账修复",
    "EV_SHARED_STATE_WRITE_FAILED": "共享状态写失败",
    "EV_SECURE_DESKTOP_REJECTED": "安全桌面拒绝",
    "EV_SECURE_DESKTOP_CHECK_FAILED": "安全桌面检测失效",
    "EV_SECURE_DESKTOP_ACTIVATED": "安全桌面激活",
    "EV_SECURE_DESKTOP_EXITED": "安全桌面退出",
    "EV_SCREENSHOT_CLEANUP": "截图清理",
    "EV_SCREENSHOT_CLEANUP_ERROR": "截图清理异常",
    "EV_AUDIT_LOG_CLEANUP": "审计日志清理",
    "EV_WHITELIST_ENROLLED_PERMANENT": "白名单入白-永久",
    "EV_WHITELIST_REMOVED": "白名单移除",
    "EV_WHITELIST_REMOVED_VIA_AI": "白名单移除-经AI请求",
    "EV_WHITELIST_DATA_ASSEMBLED": "白名单数据装配",
    "EV_MANAGER_WINDOW_LAUNCH": "管理窗拉起",
    "EV_NAME_CACHE_WARMED": "名称缓存暖机",
    "EV_STARTUP_STAGE": "启动段",
}


def _vocab() -> dict[str, str]:
    import deskpilot.audit_events as ev
    return {name: getattr(ev, name) for name in dir(ev)
            if name.startswith("EV_")
            and isinstance(getattr(ev, name), str)}


class TestVocabularyHealth:
    """TC-60-02(单元):词汇表自身可依赖。"""

    def test_tc60_02_vocabulary_complete_nonempty_unique(self):
        """TC-60-02:常量数==钉板数(46)、全非空 str、值互异
        (防两名同值致身份混淆)。断言:常量值直出。"""
        vocab = _vocab()
        assert len(vocab) == len(FREEZE), \
            f"常量数 {len(vocab)} != 钉板数 {len(FREEZE)}(直出)"
        assert all(isinstance(v, str) and v for v in vocab.values()), \
            "存在空值/非 str 常量(直出)"
        values = list(vocab.values())
        assert len(values) == len(set(values)), \
            "存在同值异名常量(身份混淆,直出)"


class TestEventTextFrozen:
    """TC-60-03(单元):落盘事件文本冻结(护历史 JSONL 可比性)。"""

    def test_tc60_03_event_text_matches_freeze_board(self):
        """TC-60-03:每个 EV_* 常量值==钉板中文字面量,逐字相等;
        常量名集合==钉板键集(不多不少)。断言:常量值直出——
        「改值即红」的永久守卫。"""
        vocab = _vocab()
        assert set(vocab) == set(FREEZE), \
            f"常量名集与钉板不符: 多 {set(vocab) - set(FREEZE)} " \
            f"缺 {set(FREEZE) - set(vocab)}"
        mismatches = {k: (v, FREEZE[k]) for k, v in vocab.items()
                      if v != FREEZE[k]}
        assert mismatches == {}, \
            f"落盘文本与钉板逐字不符(直出): {mismatches}"
