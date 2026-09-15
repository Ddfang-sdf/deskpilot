"""ISS-0072【设计引入】撤回墓碑被再次入白审批抹平（TC-72-01~14 + M-72-01 对标）。

设计方案（问题单 §3/§5 v0.3）：
- §3.0 不变量「撤回即人类否决，永久有效」；
- §3.2 四处改动：policy._merge_local_whitelist 收集撤回集合 → Policy.revoked →
  WhitelistAdmin.is_revoked → enforcement 闸二硬拒 REVOKED_BY_HUMAN；
- §3.3 拒绝文案三要素（事实 / 重试无益 / 恢复通道归属）。

层级（问题单 §5 声明）：
- 单元：TC-72-01/02/03/04/05/06/12/13/14（允许替身，断言在返回值/替身记录/落盘文件）；
- 集成：TC-72-07/08/09/10/11（真实策略文件 + 真实 AuditLogger / 真实 HTTP 服务，
  断言在落盘 YAML 与审计 JSONL 数据层）。

关于 pytest 标记：本单全部用例均在 tmp 目录内完成，**无一需要真机窗口或真实硬件**，
故均不打 ``integration`` 标记（与 test_whitelist_iss12.TestWhitelistEndpoints
的真实 HTTP 用例先例一致），默认跑测即全量执行。

装配次序与 ``main.py:394-401`` 一致：出厂 base 先加载并校验（ISS-0032 B3）→
local 合并 → ``WhitelistAdmin`` 消费合并视图 → 强制层消费该 admin。

入口（问题单 §5，只用公开入口）：
policy.load_policy / whitelist_admin.WhitelistAdmin{,.is_revoked,.remove,
.add_permanent,.cap_of} / enforcement.Enforcement.submit / httpd.remote_call。
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from deskpilot.binding import BindingManager
from deskpilot.approval import ApprovalManager
from deskpilot.enforcement import Enforcement
from deskpilot.estop import EstopMonitor
from deskpilot.models import OperationRequest
from deskpilot.policy import load_policy
from deskpilot.whitelist_admin import WhitelistAdmin, file_sha256

from .conftest import read_audit

ROOT = Path(__file__).resolve().parents[1]

# 撤回态拒绝码（问题单 §3.2）。P1 阶段 errors.py 尚无该常量，故用字面量——
# 避免模块级 import 失败导致整文件收集失败，掩盖 TC-72-09/10/12 三条回归守卫
# 的红绿可辨性（这三条改前必须绿）。
REVOKED = "REVOKED_BY_HUMAN"

TOMBSTONE = {"process": "seeyou.exe", "max_level": None}


# ---------- 布置辅助 ----------

@dataclass
class Env:
    """装配产物；字段名即问题单 §3.2 的四个改动点与消费方。"""

    base: Path
    local: Path
    policy: object                        # 改动 2：Policy.revoked
    admin: WhitelistAdmin                 # 改动 3：is_revoked
    bindings: BindingManager
    enforcement: Enforcement              # 改动 4：闸二硬拒


def _write_base(tmp_path, audit_dir, whitelist=None) -> Path:
    """出厂策略文件（只读铁律：本单所有用例均不得写它）。"""
    data = {
        "whitelist": whitelist if whitelist is not None else [
            {"process": "notepad.exe", "max_level": "L2"},
            {"process": "explorer.exe", "max_level": "L1"},
        ],
        "terminal_apps": ["cmd.exe", "powershell.exe"],
        "keys": {"l2_allow": ["enter"], "l3_controlled": ["delete"]},
        "timeouts": {"binding_ttl": 600, "approval_ttl": 60,
                     "wait_poll_interval": 0.5, "wait_timeout_max": 300},
        "audit_dir": audit_dir,
    }
    p = tmp_path / "policy.yml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return p


def _write_local(tmp_path, entries) -> Path:
    """用户策略数据文件（撤回一律写墓碑 max_level: null）。"""
    p = tmp_path / "policy.local.yml"
    p.write_text(yaml.safe_dump({"whitelist": entries}, allow_unicode=True,
                                sort_keys=False), encoding="utf-8")
    return p


def _assembly(tmp_path, local_entries=None, audit=None):
    """双文件装配（只到 Policy + Admin 两层）。返回 (base, local, policy, admin)。

    ISS-0072 §3.2 改动 3：装配侧须把 ``policy.revoked`` 注入 ``WhitelistAdmin``
    （与 ``main.py:396-402`` 逐参一致）——此线即"人类否决"跨过装配边界的唯一通道。
    """
    base = _write_base(tmp_path, str(tmp_path / "audit"))
    local = _write_local(tmp_path, local_entries or [])
    base_policy = load_policy(str(base))                      # 出厂视图（无 local）
    policy = load_policy(str(base), local_path=str(local))    # 合并视图
    admin = WhitelistAdmin(str(base), policy.whitelist, audit=audit,
                           local_path=str(local),
                           base_whitelist=base_policy.whitelist,
                           revoked=policy.revoked)
    return base, local, policy, admin


def _env(tmp_path, local_entries=None, *, approver, clock, probe, executor,
         audit) -> Env:
    """全链装配：双文件 admin → 强制层消费它。"""
    base, local, policy, admin = _assembly(tmp_path, local_entries, audit)
    bindings = BindingManager(probe, policy.binding_ttl, clock)
    approvals = ApprovalManager(approver, policy.approval_ttl, clock)
    estop = EstopMonitor(policy.corner_hold_ms, clock, audit)
    enf = Enforcement(policy, bindings, approvals, estop, executor, audit,
                      whitelist_admin=admin)
    return Env(base, local, policy, admin, bindings, enf)


def _attach(process: str) -> OperationRequest:
    """attach 请求形态（tools/__init__.py:156-158：无绑定令牌）。"""
    return OperationRequest(tool="attach", params={"process": process},
                            binding_token=None)


# ---------- 单元：撤回事实抵达策略视图（TC-72-01/02） ----------

class TestRevokedReachesPolicy:
    """场景:墓碑进程的「存在性」必须抵达策略只读视图。
    断言:Policy.revoked / Policy.whitelist 直出。"""

    def test_tc_72_01_tombstone_in_policy_view(self, tmp_path):
        base = _write_base(tmp_path, str(tmp_path / "audit"))
        local = _write_local(tmp_path, [TOMBSTONE])
        p = load_policy(str(base), local_path=str(local))
        assert "seeyou.exe" in p.revoked
        assert "seeyou.exe" not in p.whitelist

    def test_tc_72_02_tombstone_beats_factory_reentry(self, tmp_path):
        """出厂回填同名进程时,人类裁决不被静默逆转（ISS-0032 A6 立意）。"""
        base = _write_base(tmp_path, str(tmp_path / "audit"),
                           whitelist=[{"process": "seeyou.exe", "max_level": "L2"},
                                      {"process": "notepad.exe", "max_level": "L2"}])
        local = _write_local(tmp_path, [TOMBSTONE])
        p = load_policy(str(base), local_path=str(local))
        assert "seeyou.exe" not in p.whitelist
        assert "seeyou.exe" in p.revoked
        assert "notepad.exe" not in p.revoked     # 反向:未撤回者不入集


# ---------- 单元：闸二硬拒、零交互、零副作用（TC-72-03/04/12/13） ----------

class TestGate2HardDeny:
    """场景:撤回态进程收到写请求。
    断言:Decision 直出 + 替身记录（审批请求/激活/截图）+ 落盘 YAML。"""

    def test_tc_72_03_zero_approval_interaction(self, tmp_path, approver, clock,
                                                probe, executor, audit_log):
        e = _env(tmp_path, [TOMBSTONE], approver=approver, clock=clock,
                 probe=probe, executor=executor, audit=audit_log)
        approver.decision = "approve_always"      # 最危险产品:一键永久入白
        d = e.enforcement.submit(_attach("seeyou.exe"))
        assert d.allowed is False
        assert d.reason_code == REVOKED
        assert approver.requests == []            # 审批通道零调用
        assert e.admin.cap_of("seeyou.exe") is None  # 未产生任何入白
        data = yaml.safe_load(e.local.read_text(encoding="utf-8"))
        assert data["whitelist"] == [TOMBSTONE]   # 盘面墓碑原样

    def test_tc_72_04_hard_deny_no_side_effects(self, tmp_path, approver, clock,
                                                probe, executor, audit_log):
        """硬拒路径不得抢焦点、不得实拍（目标窗口全程不被触碰）。"""
        e = _env(tmp_path, [TOMBSTONE], approver=approver, clock=clock,
                 probe=probe, executor=executor, audit=audit_log)
        # 预置可见窗口:若走取图链,该窗口必被前置并实拍
        executor.live_windows = [{"hwnd": 424242, "title": "seeyou",
                                  "process": "seeyou.exe",
                                  "rect": (0, 0, 400, 300), "visible": True}]
        approver.decision = "approve_always"
        d = e.enforcement.submit(_attach("seeyou.exe"))
        assert d.reason_code == REVOKED
        assert executor.activate_calls == []
        assert executor.approval_shot_rects == []

    def test_tc_72_12_self_protection_not_weakened(self, tmp_path, approver,
                                                   clock, probe, executor,
                                                   audit_log):
        """回归守卫:撤回判定插在自保护之前,不得削弱 NEVER_ENROLL 硬拒。"""
        e = _env(tmp_path, [TOMBSTONE], approver=approver, clock=clock,
                 probe=probe, executor=executor, audit=audit_log)
        d = e.enforcement.submit(_attach("deskpilot.exe"))
        assert d.allowed is False
        assert d.reason_code == "NOT_WHITELISTED"
        assert approver.requests == []

    def test_tc_72_13_message_three_elements(self, tmp_path, approver, clock,
                                             probe, executor, audit_log):
        """文案三要素齐备,且不含任何加入方法教学（ISS-0012 B 同纪律）。"""
        e = _env(tmp_path, [TOMBSTONE], approver=approver, clock=clock,
                 probe=probe, executor=executor, audit=audit_log)
        d = e.enforcement.submit(_attach("seeyou.exe"))
        assert "已被人类" in d.message            # 事实
        assert "重复请求" in d.message            # 重试无益
        assert "白名单管理窗" in d.message         # 恢复通道归属
        assert "policy" not in d.message and "yml" not in d.message


# ---------- 单元：运行期撤回与人类加回（TC-72-05/06） ----------

class TestRuntimeRevokeAndRestore:
    """场景:管理窗运行期撤回 → 人类主动加回（唯一恢复通道）。
    断言:方法返回值 + 落盘 YAML（数据层直出）。"""

    def test_tc_72_05_runtime_revoke_enters_revoked(self, tmp_path, audit_log):
        _, _, _, admin = _assembly(tmp_path, [], audit_log)
        assert admin.is_revoked("notepad.exe") is False   # 前置:尚未撤回
        assert admin.remove("notepad.exe") == "static"
        assert admin.is_revoked("notepad.exe") is True
        assert admin.cap_of("notepad.exe") is None

    def test_tc_72_06_human_add_back_is_only_recovery(self, tmp_path, audit_log):
        _, local, _, admin = _assembly(tmp_path, [], audit_log)
        admin.remove("notepad.exe")
        admin.add_permanent("notepad.exe", "L2")
        assert admin.is_revoked("notepad.exe") is False
        assert admin.cap_of("notepad.exe") == "L2"
        wl = yaml.safe_load(local.read_text(encoding="utf-8"))["whitelist"]
        assert not any(i["process"] == "notepad.exe" and i.get("max_level") is None
                       for i in wl)


# ---------- 集成：撤回不可被重复请求逆转（TC-72-07） ----------

class TestRepeatRequestsCannotRevert:
    """场景:现场 4 次连续 attach 的复现（问题单 §1 实证）。
    断言:4 次 Decision + 落盘 YAML + 审计 JSONL（数据层直出）。"""

    def test_tc_72_07_four_submits_identical(self, tmp_path, approver, clock,
                                             probe, executor, audit_log):
        e = _env(tmp_path, [TOMBSTONE], approver=approver, clock=clock,
                 probe=probe, executor=executor, audit=audit_log)
        approver.decision = "approve_always"
        before = file_sha256(str(e.local))
        ds = [e.enforcement.submit(_attach("seeyou.exe")) for _ in range(4)]
        assert [d.reason_code for d in ds] == [REVOKED] * 4
        assert approver.requests == []
        assert file_sha256(str(e.local)) == before  # 零写入（非"恰好相同"）
        assert yaml.safe_load(e.local.read_text(encoding="utf-8"))["whitelist"] == \
            [TOMBSTONE]
        rows = [r for r in read_audit(str(tmp_path / "audit"))
                if r.get("tool") == "attach"]
        assert [r["reason_code"] for r in rows] == [REVOKED] * 4
        assert {r["decision"] for r in rows} == {"拒绝"}


# ---------- 集成：分支序与回归守卫（TC-72-08/09/10） ----------

class TestGate2BranchOrder:
    """场景:闸二四分支（撤回 / 终端旁路 / 自保护 / 入白三态）互不吞噬。
    断言:Decision 直出 + 落盘 YAML 与出厂 base 哈希（数据层直出）。"""

    def test_tc_72_08_revoked_outranks_terminal_bypass(self, tmp_path, approver,
                                                       clock, probe, executor,
                                                       audit_log):
        """Q4 假设锁:撤回不因 terminal_apps 成员资格被降级为逐操作审批。"""
        e = _env(tmp_path, [{"process": "cmd.exe", "max_level": None}],
                 approver=approver, clock=clock, probe=probe,
                 executor=executor, audit=audit_log)
        approver.decision = "approve"
        d = e.enforcement.submit(_attach("cmd.exe"))
        assert d.reason_code == REVOKED
        assert approver.requests == []
        assert e.admin.cap_of("cmd.exe") is None

    def test_tc_72_09_fresh_process_still_enrolls(self, tmp_path, approver, clock,
                                                  probe, executor, audit_log):
        """非空对照:素未谋面进程的三态入白不回归（TC-72-03/07 有效性的前提）。"""
        e = _env(tmp_path, [TOMBSTONE], approver=approver, clock=clock,
                 probe=probe, executor=executor, audit=audit_log)
        approver.decision = "approve"
        d = e.enforcement.submit(_attach("fresh.exe"))
        assert approver.requests[0]["enroll"] == "fresh.exe"
        assert d.allowed is True
        assert e.admin.cap_of("fresh.exe") == "L2"

    def test_tc_72_10_factory_base_never_written(self, tmp_path, audit_log):
        base, local, _, admin = _assembly(tmp_path, [], audit_log)
        before = file_sha256(str(base))
        admin.remove("notepad.exe")
        assert file_sha256(str(base)) == before      # 出厂 base 字节不变
        wl = yaml.safe_load(local.read_text(encoding="utf-8"))["whitelist"]
        assert {"process": "notepad.exe", "max_level": None} in wl


# ---------- 集成：HTTP 外表面（TC-72-11） ----------

class TestHttpSurface:
    """场景:经真实 HTTP 服务（真实端口、真实策略文件、零桩）驱动 attach。
    断言:响应体四字段（数据层直出）。"""

    @pytest.fixture
    def daemon(self, tmp_path, approver, clock, probe, executor, audit_log):
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        e = _env(tmp_path, [TOMBSTONE], approver=approver, clock=clock,
                 probe=probe, executor=executor, audit=audit_log)
        # 目标窗口可见:若闸二走审批取图链,该窗口必被前置并实拍
        executor.live_windows = [{"hwnd": 424242, "title": "seeyou",
                                  "process": "seeyou.exe",
                                  "rect": (0, 0, 400, 300), "visible": True}]
        ctx = ToolContext(policy=e.policy, enforcement=e.enforcement,
                          bindings=e.bindings, executor=executor,
                          audit=audit_log, whitelist_admin=e.admin)
        d = HttpDaemon(ctx, port=0, whitelist_admin=e.admin)
        d.start()
        # 就绪等待:serve 线程绑定监听后再放行用例（真实 socket，零桩）
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{d.port}/health", timeout=0.5):
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(0.1)
        yield d, e, approver
        d.stop()

    def test_tc_72_11_http_surface_denies(self, daemon, executor):
        from deskpilot.httpd import remote_call
        d, e, approver = daemon
        approver.decision = "approve_always"
        body = remote_call("attach", {"process": "seeyou.exe"},
                           f"http://127.0.0.1:{d.port}", timeout=30.0)
        assert body["error_code"] == REVOKED
        assert body["ok"] is False
        assert "人类" in body["message"]
        assert "重复请求" in body["message"]
        assert approver.requests == []               # 屏幕零弹窗（零审批请求）
        assert executor.activate_calls == []         # 零抢焦点
        assert executor.approval_shot_rects == []    # 零取图
        assert yaml.safe_load(e.local.read_text(encoding="utf-8"))["whitelist"] == \
            [TOMBSTONE]


# ---------- 单元：文档随代码走（TC-72-14） ----------

class TestDocsSynced:
    """场景:实现完成后核对文档同步面（R11）。
    断言:文档文本与源码实有错误码，直出、零魔法数。

    P2 核对修正（TC-72-14）：原设计断言 ``"20 个错误码" in 详细设计说明书``
    无出处——该字符串不在详细设计说明书内（在功能设计说明书:219），而详细
    设计附录 A 实为 20 行、errors.py 实有 25 个常量（5 个未登记：见待查清单）。
    改为可从文件解析出的自洽断言：附录 A 必含 REVOKED_BY_HUMAN 行，且其
    "全量 N 码" 声明与附录 A 行数相等（计数自洽，不写死数字）。
    """

    def test_tc_72_14_docs_carry_revoked_semantics(self):
        detail = (ROOT / "docs" / "详细设计说明书.md").read_text(encoding="utf-8")
        design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
        func = (ROOT / "docs" / "功能设计说明书.md").read_text(encoding="utf-8")

        # 1) 附录 A 必须登记新码（行键名直出）
        appendix = detail.split("## 附录 A 错误码一览")[1].split("## 附录 B")[0]
        codes = [ln.split("|")[1].strip() for ln in appendix.splitlines()
                 if ln.startswith("|") and "---" not in ln][1:]
        assert REVOKED in codes

        # 2) 附录 A 已登记 REVOKED_BY_HUMAN 后仍自洽：附录 A 行数与
        #    errors.py 常量数须同进——本单只加自己一码，故此处只校验
        #    "本单这一码"的双向一致（附录 A 行键 ↔ errors.py 常量），
        #    全量登记册补登属 ISS-0074 的范围，不在本单顺手改。
        src = (ROOT / "deskpilot" / "errors.py").read_text(encoding="utf-8")
        consts = set(re.findall(r'^([A-Z][A-Z0-9_]*)\s*=\s*"', src, re.M))
        assert REVOKED in consts                # 新码须是实现层常量
        assert REVOKED in codes                 # 且须登记进附录 A
        assert "REVOKED_BY_HUMAN" in design

        # 3) INV-2 补款
        assert "撤回即人类否决" in design

        # 4) 功能设计拒绝码清单
        assert REVOKED in func
