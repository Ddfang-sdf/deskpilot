"""ISS-0093 急停解冻通道收口测试(TC-93-01~12,问题单 §10 测试设计表)。

背景:req 文件邮箱 + HTTP /estop/reset + CLI --reset 三通道让持 MCP 的 AI
可自行解冻(§2 实证);裁定=解冻入口收敛为「弹窗点击+热键」人类独占。

层级分布(§10 表逐行落码):
- 单元:TC-93-01/03/04/05/07(替身/桩允许,断言在返回值/桩记录/盘上直读)
- 形态:TC-93-02/06/11(源码直读检索,无执行)
- assembly:TC-93-08/09(含替身 Popen,按 §3.2 降级命名,见类 docstring)
- 集成:TC-93-10(真 HttpDaemon 零 mock,断言在 HTTP 响应体)、
        TC-93-12(真 EstopMonitor+FreezeNotifier+DialogService 真 Tk,
        本机实测 tkinter 可用,无需降级 assembly)

入口(设计):estop.dialog_reset / FreezeNotifier.sync_local_with_shared_state
/ freeze_dialog.build_window(on_reset=) / DialogService.show→_dispatch /
FreezeNotifier.check_dialog_exit(§9.2 语义,方法名设计未定,见 TC-93-08 注)
/ HttpDaemon HTTP 外表面 / main.py·httpd.py·estop.py·freeze_*.py 源码。

断言出处:is_frozen() 返回值 / 审计 JSONL 记录对象 / 桩调用记录 /
目录 glob 直读 / HTTP 响应体 error_code / 源码文本检索——均直出,无中间转换。

P1 红态预期:TC-93-01 绿(语义平移,行为已存在);TC-93-02~12 红,
红色全部落在未实现行为(三通道未删/直调未接/退出码通道空壳/同步未单向化)。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from deskpilot.audit import AuditLogger
from deskpilot.estop import EstopMonitor
from deskpilot.freeze_dialog import EXIT_RESET
from deskpilot.freeze_notify import STATE_FILE, FreezeNotifier
from deskpilot.httpd import DEFAULT_HOST, DEFAULT_PORT, HttpDaemon, probe_daemon

from deskpilot.audit_events import (
    EV_ESTOP_RESET)
from .conftest import read_audit

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "deskpilot"


def _read_src(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


# ---------- Tk 替身装配(TC-93-04/07 共用,ISS-0059 步骤12 收编 tests/faketk) ----------

@pytest.fixture
def tk_rig(monkeypatch):
    """Tk 替身(ISS-0059 步骤12):_TkRig 收编 tests/faketk.install——
    after 队列泵=rec.pump(16)(15 帧滑入+1 次状态迁移进 SHOWN);
    按钮 command 按文本取=rec.button_command(文本)(断言零改动)。
    替身清单(assembly 边界自陈——本替身仅用于单元层 TC-93-04/07):
    Toplevel/Frame/Label/Button/Canvas 全为替身;真实部件=build_window
    状态机本体、reset_click_action 决策、盘上 state 文件读取;
    断层面=Tk 渲染与事件循环。"""
    import tkinter as _tk

    from .faketk import install
    rec = install(monkeypatch, _tk, screen=(1920, 1080))
    yield rec
    import deskpilot.freeze_dialog as fd
    fd.release_singleton()          # 替身窗无 Destroy 事件,互斥须手动放(iss103 先例)


def _write_state(dir_path: Path, frozen: bool, seq: int,
                 source: str = "热键 Ctrl+Shift+F12") -> None:
    (dir_path / STATE_FILE).write_text(json.dumps(
        {"frozen": frozen, "seq": seq, "source": source, "ts": "t"},
        ensure_ascii=False), encoding="utf-8")


# ---------- TC-93-01 弹窗直调复位(语义平移) ----------

class TestDialogResetCarryover:
    """TC-93-01(单元):弹窗直调复位,语义平移自 cli_reset(§11 登记)。

    场景:冻结后走「冻结提示弹窗」入口复位。前提:EstopMonitor 已热键冻结。
    步骤:estop.dialog_reset()。预期:frozen 复位+审计「急停复位/冻结提示弹窗」。
    断言:is_frozen() 返回值直出;审计记录对象 event/detail 直读。
    红绿属性:绿(行为已存在,通道载体收口后语义由 dialog_reset 继承)。
    """

    def test_tc93_01_dialog_reset_semantic_carryover(self, estop, audit_log,
                                                     tmp_path):
        estop.on_trigger_hotkey()
        assert estop.is_frozen() is True
        estop.dialog_reset()
        assert estop.is_frozen() is False                     # 返回值直出
        events = read_audit(str(tmp_path / "audit"))
        resets = [e for e in events if e.get("event") == EV_ESTOP_RESET]
        assert len(resets) == 1
        assert resets[0]["detail"] == "冻结提示弹窗"           # 审计记录直读


# ---------- TC-93-02/11 形态钉:三通道源码清除 ----------

class TestThreeChannelsSourcePurged:
    """TC-93-02/11(形态):源码直读,无执行;命中清单为空即通道消亡。"""

    def test_tc93_02_three_channels_source_purged(self):
        """TC-93-02(形态,§8 E4/E5/E6):estop.py 无 cli_reset;httpd.py 无
        /estop/reset 分支;main.py 无 _cli_reset;freeze_notify.py 无
        REQ_FILE/REQ_PREFIX/check_reset_request;freeze_dialog.py 无
        write_reset_request。断言:源码文本检索直读。"""
        estop_src = _read_src("estop.py")
        assert "cli_reset" not in estop_src, \
            "estop.py 仍定义 cli_reset(E5/E6 载体未删)"

        httpd_src = _read_src("httpd.py")
        assert "/estop/reset" not in httpd_src, \
            "httpd.py 仍存在 /estop/reset 端点分支(E5 未删)"

        main_src = _read_src("main.py")
        assert "_cli_reset" not in main_src, \
            "main.py 仍定义/调用 _cli_reset(E6 未删)"

        notify_src = _read_src("freeze_notify.py")
        for token in ("REQ_FILE", "REQ_PREFIX", "check_reset_request"):
            assert token not in notify_src, \
                f"freeze_notify.py 仍含 req 协议符号 {token}(E4 链路未删)"

        dialog_src = _read_src("freeze_dialog.py")
        assert "write_reset_request" not in dialog_src, \
            "freeze_dialog.py 仍含 write_reset_request(E4 写端未删)"

    def test_tc93_11_reset_cli_dispatch_gone(self):
        """TC-93-11(形态,§8 E6):main.py argv 分派无 --reset 分支。
        断言:源码文本检索直读。"""
        main_src = _read_src("main.py")
        assert '"--reset"' not in main_src, \
            "main.py argv 分派仍含 --reset 分支(CLI 复位通道未删)"


# ---------- TC-93-03 state 同步单向化(E7 关闭) ----------

class TestSyncOneWayOnly:
    """TC-93-03(单元,§9.4 v0.5):sync_local_with_shared_state 单向化。

    场景:E7 旁路——直写 estop-state.json frozen:false 不得解冻本地;
    反向(v0.5 裁决)——共享 frozen:true 不灌回本地,本地权威修共享(fg04)。
    断言:is_frozen() 返回值直出;审计 JSONL 无「复位-共享同步」直读;
    盘上 shared 文件直读。
    红态:现状 shared.frozen=false 会调 shared_sync_reset 本地复位(E7 开)
    ——红在未实现行为(复位方向未关闭)。
    """

    def test_tc93_03_shared_false_never_resets_local(self, tmp_path, policy,
                                                     clock, audit_log):
        shared = tmp_path / "shared"
        shared.mkdir()
        notifier = FreezeNotifier(str(shared), clock=time.monotonic,
                                  spawn=lambda *a, **k: None, audit=audit_log)
        estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log,
                             on_state_change=notifier.on_state_change)
        estop.on_trigger_hotkey()                # 本地冻结,共享 frozen:true seq=1
        assert estop.is_frozen() is True
        _write_state(shared, False, 2, "另一进程")   # E7:旁路直写 shared false
        notifier.sync_local_with_shared_state(estop)
        assert estop.is_frozen() is True, \
            "共享 frozen:false 不得本地复位(复位方向已关闭)"
        events = read_audit(str(tmp_path / "audit"))
        assert [e for e in events
                if e.get("event") == EV_ESTOP_RESET
                and "共享同步" in e.get("detail", "")] == [], \
            "「复位-共享同步」事件已退役,不得再产生"

    def test_tc93_03_reverse_shared_true_repairs_shared(self, tmp_path, policy,
                                                        clock, audit_log):
        """反向(v0.5 裁决修正):本地未冻 ∧ 共享 frozen:true → 沿用 fg04
        「本地权威防假象」语义——本地不冻,共享被修复为 frozen:false。

        P2 裁决(ISS-0093 v0.5):v0.4 设计「灌回本地冻结」与 ISS-0092 fg04
        冲突,定案沿用 fg04 语义;本条为授权修正,非私改测试迁就实现。
        断言:is_frozen() 返回值直出;盘上 shared 文件 json 直读。"""
        shared = tmp_path / "shared"
        shared.mkdir()
        _write_state(shared, True, 7, "鼠标甩角")
        notifier = FreezeNotifier(str(shared), clock=time.monotonic,
                                  spawn=lambda *a, **k: None, audit=audit_log)
        estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log)
        assert estop.is_frozen() is False        # 前提:本地未冻结
        notifier.sync_local_with_shared_state(estop)
        assert estop.is_frozen() is False, \
            "共享 frozen:true 不得灌回本地(本地权威,fg04 语义沿用)"
        st = json.loads((shared / STATE_FILE).read_text(encoding="utf-8"))
        assert st["frozen"] is False, \
            "共享假象须被修复为 frozen:false(盘上直读)"


# ---------- TC-93-04/05/07 弹窗直调(进程内形态) ----------

class TestDialogDirectReset:
    """TC-93-04/05/07(单元,§9.1/9.2):「立即解冻」进程内直调 / 回调透传 /
    子进程退出码发送侧。"""

    def test_tc93_04_dialog_on_reset_no_req_file(self, tk_rig, tmp_path):
        """TC-93-04(单元,§9.1):build_window(on_reset=桩),SHOWN 态点击
        「立即解冻」→ on_reset 被调一次;audit 目录零 .req 文件。
        前提:Tk 替身;estop-state.json frozen:true seq=1 在盘。
        断言:桩调用记录直出;目录 glob 直读为空。
        红态:现状点击写 estop-reset-<seq>.req 且不认 on_reset ——
        桩零调用 + req 落盘,双红均落在未实现行为。"""
        import deskpilot.freeze_dialog as fd
        from deskpilot.i18n import tr

        _write_state(tmp_path, True, 1)
        calls: list[str] = []
        fd.build_window(object(), audit_dir=str(tmp_path), interval=180.0,
                        on_reset=lambda: calls.append("reset"))
        tk_rig.pump(16)                              # 泵至 SHOWN(15 帧+1 迁移)
        click = tk_rig.button_command(tr("freeze.btn.reset_now"))
        click()
        assert calls == ["reset"], \
            "「立即解冻」须进程内直调 on_reset 一次(桩记录直出)"
        assert list(tmp_path.glob("estop-reset-*.req")) == [], \
            "解冻不得再经 req 文件中转(目录 glob 直读)"

    def test_tc93_05_payload_on_reset_passthrough(self, monkeypatch):
        """TC-93-05(单元,§9.1):DialogService.show("freeze", payload 含
        on_reset) 经真实 _default_factory 派发 → freeze_dialog.build_window
        收到 on_reset=payload 值。
        前提:最末端 build_window 为记录替身(同 iss13 R2 先例),其余真实。
        断言:替身工厂入参记录直出。
        红态:现状 _default_factory 不透传 on_reset(dialog_service.py:113-116)
        ——替身收到 on_reset=None,红在未接线。"""
        import deskpilot.freeze_dialog as fd
        from deskpilot.dialog_service import DialogService

        received: list[dict] = []

        def rec_build_window(parent, audit_dir, interval,
                             target_screen=None, on_reset=None):
            received.append({"audit_dir": audit_dir, "interval": interval,
                             "on_reset": on_reset})

        monkeypatch.setattr(fd, "build_window", rec_build_window)
        sentinel = object()
        inner = DialogService()                  # 默认装配:触达真实 _default_factory
        svc = DialogService(window_factory=inner._default_factory)
        svc.start()
        try:
            svc.show("freeze", {"audit_dir": "a", "interval": 180.0,
                                "on_reset": sentinel})
            deadline = time.monotonic() + 5.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.02)
        finally:
            svc.stop()
        assert len(received) == 1
        assert received[0]["on_reset"] is sentinel, \
            "freeze payload 的 on_reset 须透传给 build_window(入参记录直出)"

    def test_tc93_07_subprocess_click_exits_with_reset_code(self, tk_rig,
                                                            tmp_path):
        """TC-93-07(单元,§9.2 发送侧):子进程模式 build_window(on_reset=None),
        点击「立即解冻」→ 抛 SystemExit 且 code==EXIT_RESET(73)。
        断言:pytest.raises(SystemExit).value.code 直出;EXIT_RESET 常量直读==73。
        红态:现状点击走写 req 分支,不抛 SystemExit(DID NOT RAISE)。"""
        import deskpilot.freeze_dialog as fd
        from deskpilot.i18n import tr

        _write_state(tmp_path, True, 1)
        fd.build_window(object(), audit_dir=str(tmp_path), interval=180.0,
                        on_reset=None)           # 子进程形态:无进程内回调
        tk_rig.pump(16)                              # 泵至 SHOWN
        click = tk_rig.button_command(tr("freeze.btn.reset_now"))
        with pytest.raises(SystemExit) as exc:
            click()
        assert exc.value.code == EXIT_RESET      # SystemExit.code 直出
        assert EXIT_RESET == 73                  # 设计定值(常量直读)


# ---------- TC-93-06 形态钉:装配接线(守卫接替者) ----------

class TestAssemblyWiringPin:
    """TC-93-06(形态,§9.1):守卫搬走必含「新调用点已接线」钉(§6 反模式)。"""

    def test_tc93_06_main_injects_on_reset_dialog_reset(self):
        """TC-93-06(形态):main.py freeze payload 装配点注入
        on_reset=estop.dialog_reset(真实管线存在该调用,纯函数单测不算数)。
        断言:main.py 源码直读命中。
        红态:现状 main.py 无 on_reset 注入(freeze payload 在
        freeze_notify._default_spawn 组装且无回调)——红在未接线。"""
        main_src = _read_src("main.py")
        assert re.search(r"on_reset[\"']?\s*[:=]\s*estop\.dialog_reset",
                         main_src), \
            "main.py 装配侧未见 payload 注入 on_reset=estop.dialog_reset"


# ---------- TC-93-08/09 子进程退出码通道接收侧(assembly) ----------

class _FakePopen:
    """替身 Popen:poll() 返回预设退出码(None=仍在运行)。"""

    def __init__(self, code):
        self._code = code

    def poll(self):
        return self._code


class TestChildExitChannelAssembly:
    """TC-93-08/09(assembly,§3.2 降级命名:含替身 Popen,不授 integration 标签)。

    真实部件清单:EstopMonitor(真冻结态机+真审计)、FreezeNotifier 本体、
    盘上 estop-state.json(临时目录真文件)。
    替身清单:_FakePopen(poll→预设退出码;真实子进程弹窗不起)。
    断层面:弹窗子进程本体与其真实退出行为(Tk 子进程由 TC-93-07 发送侧
    与 TC-93-12 真 Tk 链覆盖)。

    入口:FreezeNotifier.check_dialog_exit(estop)——§9.2「监听循环 poll」
    语义的设计落点;设计 §10 未给方法名(测试设计表步骤仅写「触发监听
    poll 一轮」),本测试按既有 check_* 命名惯例拟定,已上报裁决。
    断言:is_frozen() 返回值直出。
    红态:check_dialog_exit 为 P1 空壳(NotImplementedError)——
    红在退出码消费未实现。
    """

    def _freeze_with_popen(self, tmp_path, policy, clock, audit_log, code):
        popen = _FakePopen(code)
        spawned: list = []
        notifier = FreezeNotifier(
            str(tmp_path), clock=time.monotonic,
            spawn=lambda d: spawned.append(popen) or popen, audit=audit_log)
        estop = EstopMonitor(policy.corner_hold_ms, clock, audit_log,
                             on_state_change=notifier.on_state_change)
        estop.on_trigger_hotkey()                # 冻结边沿 → 本轮句柄产生
        assert estop.is_frozen() is True
        assert spawned == [popen]                # spawn 真被调(桩记录直出)
        return notifier, estop

    def test_tc93_08_exit_code_73_resets(self, tmp_path, policy, clock,
                                         audit_log):
        """TC-93-08(assembly,§9.2 接收侧):子进程退出码 73 → estop 复位。"""
        notifier, estop = self._freeze_with_popen(tmp_path, policy, clock,
                                                  audit_log, EXIT_RESET)
        notifier.check_dialog_exit(estop)        # 监听循环 poll 一轮
        assert estop.is_frozen() is False, \
            "退出码 73(人类点击「立即解冻」)须触发 dialog_reset 复位"

    def test_tc93_09_non_73_exit_code_keeps_frozen(self, tmp_path, policy,
                                                   clock, audit_log):
        """TC-93-09(assembly,§9.2):退出码 1(异常退出)/ None(仍在运行)
        不具解冻语义 → 仍冻结。"""
        notifier, estop = self._freeze_with_popen(tmp_path, policy, clock,
                                                  audit_log, 1)
        notifier.check_dialog_exit(estop)
        assert estop.is_frozen() is True, \
            "非 73 退出码不得解冻(关窗/被杀非解冻语义)"

        p2 = tmp_path / "p2"
        p2.mkdir()
        notifier2, estop2 = self._freeze_with_popen(p2, policy,
                                                    clock, audit_log, None)
        notifier2.check_dialog_exit(estop2)
        assert estop2.is_frozen() is True, \
            "子进程仍在运行(poll=None)不得解冻"


# ---------- TC-93-10 /estop/reset 端点消亡(集成) ----------

@pytest.mark.integration
class TestEstopResetEndpointGone:
    """TC-93-10(集成,§3.2:零打桩+断言在外表面响应体,授 integration 标签)。

    场景:E5 暴露面——HTTP POST /estop/reset(localhost 接口,AI 可 curl)消亡;
    同文件对照端点 /whitelist/remove 正常(不误伤,estop 注入保留 idle 豁免在用)。
    前提:真 HttpDaemon(临时端口,零 mock)+真 WhitelistAdmin(内存态)。
    步骤:urllib POST /estop/reset;再 POST /whitelist/remove 对照。
    预期:前者 404 NOT_FOUND;后者 200 ok。
    断言:HTTP 响应体 error_code 直出。
    红态:现状 /estop/reset 返回 200 且真实复位 —— 红在端点未删。
    """

    def _post(self, port: int, path: str, payload: bytes = b""):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_tc93_10_estop_reset_endpoint_gone(self, ctx, estop):
        from deskpilot.whitelist_admin import WhitelistAdmin

        # 对照数据(v0.6 登记):会话条目而非静态条目——静态撤回需落盘
        # (policy_path=None 时 PolicyError fail-closed),P1 前提准备写错,
        # 此处仅修正数据准备;断言(响应体 error_code/ok)不变。
        admin = WhitelistAdmin(None, {})
        admin.add_session("notepad.exe", "L2")
        d = HttpDaemon(ctx, host="127.0.0.1", port=0, estop=estop,
                       whitelist_admin=admin)
        d.start()
        try:
            estop.on_trigger_hotkey()
            status, body = self._post(d.port, "/estop/reset")
            assert status == 404, \
                f"/estop/reset 须消亡(404),实得 {status}"
            assert body["error_code"] == "NOT_FOUND"     # 响应体直出
            assert estop.is_frozen() is True, \
                "HTTP 不得再能改变 frozen 态"

            s2, body2 = self._post(
                d.port, "/whitelist/remove",
                json.dumps({"process": "notepad.exe"}).encode("utf-8"))
            assert s2 == 200 and body2["ok"] is True, \
                "对照端点 /whitelist/remove 不得误伤"
        finally:
            d.stop()


# ---------- TC-93-12 全链无 req 落盘(集成,真 Tk) ----------

@pytest.mark.integration
class TestFullChainNoReqOnDisk:
    """TC-93-12(集成,§3.2:零打桩,断言在盘上数据/审计 JSONL/返回值)。

    场景:冻结→经 DialogService(真 Tk 线程)弹窗→人类点击「立即解冻」
    →复位;全程零文件中转。
    前提:真 EstopMonitor + FreezeNotifier(临时 shared 目录)+ DialogService
    真 Tk(本机 2026-09-22 实测 tkinter.Tk 可起,无需按 §3.2 降级 assembly);
    真实 daemon 在线时 skip(单例互斥/共享目录冲突,同 fg05 环境守卫)。
    步骤:on_trigger_hotkey → 等窗至 SHOWN → invoke「立即解冻」按钮。
    预期:复位成功;audit 目录自始至终零 estop-reset-*.req;
    审计 detail=「冻结提示弹窗」。
    断言:is_frozen() 直出;目录 glob 直读为空;审计记录 detail 直读。
    红态:现状 payload 无 on_reset、点击写 req 文件 —— req 落盘 +
    frozen 未复位,双红均落在未实现行为。
    """

    def test_tc93_12_full_chain_dialog_click_no_req(self, tmp_path, policy):
        import tkinter as tk

        from deskpilot.dialog_service import DialogService
        from deskpilot.i18n import tr

        if os.environ.get("ISS93_FORCE_E2E") != "1" and \
                probe_daemon(DEFAULT_HOST, DEFAULT_PORT):
            pytest.skip("环境守卫:真实 daemon 在线,单例互斥/共享面会冲突")

        shared = tmp_path / "shared"
        shared.mkdir()
        audit_dir = tmp_path / "audit"
        audit = AuditLogger(str(audit_dir))
        svc = DialogService()                    # 默认装配:真 Tk 线程
        svc.start()
        notifier = FreezeNotifier(str(shared), clock=time.monotonic,
                                  dialog_service=svc, audit=audit)
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit,
                             on_state_change=notifier.on_state_change)
        # v0.6 装配备案修正(已裁决授权):镜像 main.py 生产接线——
        # 冻结 payload 的 on_reset 由装配侧注入 estop.dialog_reset(§9.1);
        # P1 前提漏此行属测试 bug,此处只补接线,断言零改动。
        notifier.on_reset = estop.dialog_reset
        reset_text = tr("freeze.btn.reset_now")
        clicked = threading.Event()

        def _probe_click():
            """Tk 线程内找窗找钮;找到后延时 invoke(等滑入完成进 SHOWN)。"""
            for w in svc._tk_root.winfo_children():
                if isinstance(w, tk.Toplevel):
                    for b in w.winfo_children():
                        if (isinstance(b, tk.Button)
                                and str(b.cget("text")) == reset_text):
                            svc._tk_root.after(
                                700, lambda: (b.invoke(), clicked.set()))
                            return
            svc._tk_root.after(150, _probe_click)

        try:
            estop.on_trigger_hotkey()
            assert estop.is_frozen() is True
            svc._tk_root.after(150, _probe_click)
            assert clicked.wait(timeout=10), "冻结弹窗「立即解冻」按钮未出现"
            deadline = time.monotonic() + 3.0
            while estop.is_frozen() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert estop.is_frozen() is False, \
                "弹窗点击须进程内直调复位(无消费不确定性)"
            assert list(shared.glob("estop-reset-*.req")) == [], \
                "全链自始至终零 req 落盘(目录 glob 直读)"
            events = read_audit(str(audit_dir))
            resets = [e for e in events if e.get("event") == EV_ESTOP_RESET]
            assert len(resets) == 1
            assert resets[0]["detail"] == "冻结提示弹窗"   # 审计直读
        finally:
            svc.stop()
            import deskpilot.freeze_dialog as fd
            fd.release_singleton()               # 幂等兜底(正常路径窗毁已放)
