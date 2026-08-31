"""ISS-0012 白名单 UX 断裂与策略完整性测试（问题单 §4.1/§6）。

层级：
- WhitelistAdmin / 审批入白 / 文案去教学 / 指纹审计 / 托盘菜单 / 弹窗三态 = 单元
  （允许替身；断言在返回值/落盘 YAML/审计记录/替身调用记录，均直出）；
- /whitelist 端点 = 集成（真实 HTTP 服务与策略文件，断言在响应体与落盘文件）。

入口（§6）：whitelist_admin 全表 / request_enroll / Enforcement(whitelist_admin) /
build_window(enroll) / build_enroll_notice / GET+POST /whitelist* /
tray.menu_items / request_remove_from_whitelist / policy_sha256_audit / _start_policy_watch。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

from deskpilot.errors import PolicyError
from deskpilot.models import OperationRequest

from .conftest import make_policy


# ---------- 布置辅助 ----------

def _write_policy(path: Path, whitelist: list[dict]) -> Path:
    path.write_text(yaml.safe_dump({"whitelist": whitelist}, allow_unicode=True),
                    encoding="utf-8")
    return path


def _admin(tmp_path, whitelist=None, never=None):
    from deskpilot.whitelist_admin import WhitelistAdmin
    p = _write_policy(tmp_path / "policy.yml",
                      whitelist if whitelist is not None
                      else [{"process": "notepad.exe"}])
    kw = {"never_enroll": never} if never is not None else {}
    return WhitelistAdmin(str(p), {"notepad.exe": "L2"}, **kw)


def _enforcement_with_admin(policy, bindings, approvals, estop, executor,
                            audit_log, admin):
    from deskpilot.enforcement import Enforcement
    return Enforcement(policy, bindings, approvals, estop, executor, audit_log,
                       whitelist_admin=admin)


# ---------- WhitelistAdmin（单元） ----------

class TestWhitelistAdmin:
    """场景:静态/会话/永久三态管理与原子落盘。
    断言:cap_of/entries/remove 返回值与落盘 YAML(直出)。"""

    def test_cap_of_static_hit_and_miss(self, tmp_path):
        a = _admin(tmp_path)
        assert a.cap_of("notepad.exe") == "L2"
        assert a.cap_of("excel.exe") is None

    def test_add_session_memory_only(self, tmp_path):
        a = _admin(tmp_path)
        a.add_session("excel.exe")
        assert a.cap_of("excel.exe") == "L2"
        # 重启语义:新实例不见会话放行
        a2 = _admin(tmp_path)
        assert a2.cap_of("excel.exe") is None

    def test_add_permanent_persists(self, tmp_path):
        a = _admin(tmp_path)
        a.add_permanent("excel.exe")
        data = yaml.safe_load((tmp_path / "policy.yml").read_text(encoding="utf-8"))
        procs = [i["process"] for i in data["whitelist"]]
        assert "excel.exe" in procs                      # 数据层:落盘直出
        assert (tmp_path / "policy.yml.bak").exists()    # 原子写先备份
        assert a.cap_of("excel.exe") == "L2"             # 内存热生效

    def test_never_enroll_rejected(self, tmp_path):
        a = _admin(tmp_path)
        with pytest.raises(PolicyError):
            a.add_session("deskpilot.exe")
        with pytest.raises(PolicyError):
            a.add_permanent("deskpilot.exe")

    def test_remove_static(self, tmp_path):
        a = _admin(tmp_path)
        assert a.remove("notepad.exe") == "static"
        data = yaml.safe_load((tmp_path / "policy.yml").read_text(encoding="utf-8"))
        assert data["whitelist"] == []                   # 数据层:条目消失
        assert a.cap_of("notepad.exe") is None           # 内存即时生效

    def test_remove_session_and_miss(self, tmp_path):
        a = _admin(tmp_path)
        a.add_session("excel.exe")
        assert a.remove("excel.exe") == "session"
        assert a.remove("nothing.exe") is None

    def test_clear_session(self, tmp_path):
        a = _admin(tmp_path)
        a.add_session("a.exe")
        a.add_session("b.exe")
        assert a.clear_session() == 2
        assert a.entries()["session"] == {}

    def test_entries_grouping(self, tmp_path):
        a = _admin(tmp_path)
        a.add_session("excel.exe")
        e = a.entries()
        assert e["static"] == {"notepad.exe": "L2"}
        assert e["session"] == {"excel.exe": "L2"}

    def test_file_sha256(self, tmp_path):
        from deskpilot.whitelist_admin import file_sha256
        p = tmp_path / "f.bin"
        p.write_bytes(b"abc")
        assert file_sha256(str(p)) == hashlib.sha256(b"abc").hexdigest()


# ---------- A 审批入白（单元,强制层） ----------

class TestEnrollAtGate2:
    """场景:非白名单进程过闸二触发入白审批,三态裁决。
    断言:Decision 直出 + 替身审批请求记录 + 落盘 YAML(直出)。"""

    def test_attach_unknown_approve_session(self, policy, bindings, approvals,
                                            estop, executor, audit_log, approver,
                                            tmp_path):
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        approver.decision = "approve"
        d = enf.submit(OperationRequest("attach", {"process": "excel.exe"}, None))
        assert d.allowed is True
        assert approver.requests[0].get("enroll") == "excel.exe"  # 入白语义送达
        assert a.cap_of("excel.exe") == "L2"                      # 会话放行

    def test_attach_unknown_approve_always_persists(self, policy, bindings,
                                                    approvals, estop, executor,
                                                    audit_log, approver, tmp_path):
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        approver.decision = "approve_always"
        d = enf.submit(OperationRequest("attach", {"process": "excel.exe"}, None))
        assert d.allowed is True
        data = yaml.safe_load((tmp_path / "policy.yml").read_text(encoding="utf-8"))
        assert "excel.exe" in [i["process"] for i in data["whitelist"]]

    def test_attach_unknown_deny(self, policy, bindings, approvals, estop,
                                 executor, audit_log, approver, tmp_path):
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        approver.decision = "deny"
        d = enf.submit(OperationRequest("attach", {"process": "excel.exe"}, None))
        assert d.allowed is False
        assert "policy.yml" not in d.message            # B:文案去教学

    def test_attach_unknown_timeout(self, policy, bindings, approvals, estop,
                                    executor, audit_log, approver, tmp_path):
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        approver.decision = "timeout"
        d = enf.submit(OperationRequest("attach", {"process": "excel.exe"}, None))
        assert d.allowed is False
        assert d.reason_code == "APPROVAL_TIMEOUT"

    def test_self_protection_hard_deny_no_dialog(self, policy, bindings,
                                                 approvals, estop, executor,
                                                 audit_log, approver, tmp_path):
        """自保护铁律:attach deskpilot.exe 硬拒,且不触发任何审批弹窗。"""
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        d = enf.submit(OperationRequest("attach", {"process": "deskpilot.exe"}, None))
        assert d.allowed is False
        assert d.reason_code == "NOT_WHITELISTED"
        assert approver.requests == []                  # 审批通道零调用

    def test_terminal_no_enroll(self, policy, bindings, approvals, estop,
                                executor, audit_log, approver, tmp_path):
        """终端豁免:cmd.exe 维持逐操作 L3 审批,不走入白(enroll=None)。"""
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        approver.decision = "approve"
        d = enf.submit(OperationRequest("attach", {"process": "cmd.exe"}, None))
        assert d.allowed is True
        assert approver.requests[0].get("enroll") is None
        assert a.cap_of("cmd.exe") is None              # 未产生任何入白

    def test_launch_unknown_approve_always(self, policy, bindings, approvals,
                                           estop, executor, audit_log, approver,
                                           tmp_path):
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        approver.decision = "approve_always"
        d = enf.submit(OperationRequest("launch_app", {"app": "excel.exe"}, None))
        assert d.allowed is True
        assert executor.instructions                     # 启动指令落执行层
        data = yaml.safe_load((tmp_path / "policy.yml").read_text(encoding="utf-8"))
        assert "excel.exe" in [i["process"] for i in data["whitelist"]]

    def test_session_entry_silences_later_ops(self, policy, bindings, approvals,
                                              estop, executor, audit_log,
                                              approver, tmp_path):
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        approver.decision = "approve"
        enf.submit(OperationRequest("attach", {"process": "excel.exe"}, None))
        n = len(approver.requests)
        d2 = enf.submit(OperationRequest("attach", {"process": "excel.exe"}, None))
        assert d2.allowed is True
        assert len(approver.requests) == n              # 会话内不再审批


# ---------- ApprovalManager.request_enroll（单元） ----------

class TestRequestEnroll:
    """场景:入白审批令牌签发语义。
    断言:返回值与 count() 观测口(直出)。"""

    def test_approve_always_issues_token(self, approvals, approver):
        approver.decision = "approve_always"
        r = approvals.request_enroll("excel.exe", "desc", "fp-1")
        assert r == "approve_always"
        assert approvals.count() == 1                   # 令牌已签发

    def test_deny_issues_nothing(self, approvals, approver):
        approver.decision = "deny"
        r = approvals.request_enroll("excel.exe", "desc", "fp-2")
        assert r == "deny"
        assert approvals.count() == 0


# ---------- 弹窗三态与通道透传（单元） ----------

class TestEnrollDialog:
    """场景:enroll 模式三按钮,裁决写结果文件。
    断言:按钮文案(替身记录)与结果文件内容(直出)。"""

    def _fake_tk(self, monkeypatch, mod, clicks):
        class W:
            def __init__(self, *a, **k):
                self.geo = None

            def pack(self, *a, **k): pass
            def place(self, *a, **k): pass
            def bind(self, *a, **k): pass
            def config(self, *a, **k): pass
            def focus_set(self): pass
            def title(self, *a): pass
            def overrideredirect(self, *a): pass
            def attributes(self, *a, **k): pass
            def configure(self, *a, **k): pass
            def geometry(self, g): self.geo = g
            def after(self, *a, **k): pass
            def winfo_screenwidth(self): return 2560
            def winfo_screenheight(self): return 1440

        class Btn(W):
            def __init__(self, *a, **k):
                super().__init__()
                clicks.append(k.get("text", ""))
                self.command = k.get("command")

        monkeypatch.setattr(mod.tk, "Toplevel", lambda parent: W())
        monkeypatch.setattr(mod.tk, "Frame", lambda *a, **k: W())
        monkeypatch.setattr(mod.tk, "Label", lambda *a, **k: W())
        monkeypatch.setattr(mod.tk, "Button", lambda *a, **k: Btn(*a, **k))
        return W

    def test_enroll_dialog_three_buttons(self, monkeypatch, tmp_path):
        import deskpilot.approval_dialog as ad
        clicks = []
        self._fake_tk(monkeypatch, ad, clicks)
        rp = tmp_path / "r.txt"
        ad.build_window(object(), "入白审批 excel.exe", str(rp), 5,
                        enroll="excel.exe")
        assert "本次允许" in clicks
        assert "永久加入" in clicks
        assert "拒绝" in clicks


class TestChannelPassthrough:
    """场景:结果文件 approve_always 合法透传;enroll 载荷送弹窗服务。
    断言:request 返回值 / dialog_service 收到的 payload(替身记录直出)。"""

    def test_approve_always_passthrough(self, tmp_path):
        from deskpilot.approval_ui import TkApprovalChannel

        class FakeService:
            def __init__(self): self.shown = []
            def show(self, kind, payload): self.shown.append((kind, payload))

        svc = FakeService()
        ch = TkApprovalChannel(timeout=2.0, dialog_service=svc,
                               result_root=str(tmp_path))

        def write_result():
            time.sleep(0.2)
            rp = Path(ch.last_request["result_path"])
            rp.write_text("approve_always", encoding="utf-8")

        t = threading.Thread(target=write_result, daemon=True)
        t.start()
        r = ch.request("desc", "fp", enroll="excel.exe")
        assert r == "approve_always"
        assert svc.shown[0][1].get("enroll") == "excel.exe"

    def test_garbage_result_is_deny(self, tmp_path):
        from deskpilot.approval_ui import TkApprovalChannel

        class FakeService:
            def show(self, kind, payload): pass

        ch = TkApprovalChannel(timeout=2.0, dialog_service=FakeService(),
                               result_root=str(tmp_path))

        def write_result():
            time.sleep(0.2)
            rp = Path(ch.last_request["result_path"])
            rp.write_text("approve_always1", encoding="utf-8")

        threading.Thread(target=write_result, daemon=True).start()
        assert ch.request("desc", "fp") == "deny"       # 非法内容 fail-closed


# ---------- E2 管理端点（集成） ----------

def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


class TestWhitelistEndpoints:
    """场景:/whitelist 三端点真实 HTTP 往返。
    断言:响应体 + 落盘 YAML(数据层直出)。无桩:真实 daemon/策略文件。"""

    @pytest.fixture
    def daemon(self, policy, bindings, approvals, estop, executor, audit_log,
               tmp_path):
        from deskpilot.enforcement import Enforcement
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        a = _admin(tmp_path)
        enf = Enforcement(policy, bindings, approvals, estop, executor,
                          audit_log, whitelist_admin=a)
        ctx = ToolContext(policy=policy, enforcement=enf, bindings=bindings,
                          executor=executor, audit=audit_log)
        d = HttpDaemon(ctx, port=0, whitelist_admin=a)
        d.start()
        yield d, a
        d.stop()

    def test_get_whitelist(self, daemon):
        d, a = daemon
        a.add_session("excel.exe")
        with urllib.request.urlopen(f"http://127.0.0.1:{d.port}/whitelist",
                                    timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["ok"] is True
        assert body["data"]["static"] == {"notepad.exe": "L2"}
        assert body["data"]["session"] == {"excel.exe": "L2"}

    def test_post_remove(self, daemon, tmp_path):
        d, a = daemon
        r = _post(f"http://127.0.0.1:{d.port}/whitelist/remove",
                  {"process": "notepad.exe"})
        assert r["ok"] is True
        assert r["data"]["removed"] == "static"
        data = yaml.safe_load((tmp_path / "policy.yml").read_text(encoding="utf-8"))
        assert data["whitelist"] == []                   # 数据层直出

    def test_post_clear_session(self, daemon):
        d, a = daemon
        a.add_session("a.exe")
        a.add_session("b.exe")
        r = _post(f"http://127.0.0.1:{d.port}/whitelist/clear_session", {})
        assert r["ok"] is True
        assert r["data"]["cleared"] == 2
        assert a.entries()["session"] == {}


# ---------- E2 管理窗口与 E4 撤销 toast（单元,fake tk） ----------

class TestManagerWindow:
    """场景:管理窗口逐行[移出]与会话区[全部清空]回调。
    断言:回调收到的进程名/调用计数(替身记录直出)。"""

    def _build(self, monkeypatch, entries, removed, cleared, labels=None):
        import deskpilot.whitelist_window as ww
        buttons = []
        if labels is None:
            labels = []
        tops = []

        class W:
            def __init__(self, *a, **k):
                self.text = k.get("text", "")
                self.command = k.get("command")
                self._text_value = ""

            def pack(self, *a, **k): pass
            def grid(self, *a, **k): pass
            def config(self, *a, **k): pass
            def configure(self, *a, **k):
                if "text" in k: self.text = k["text"]
                if "command" in k: self.command = k["command"]
            def bind(self, *a, **k): pass
            def bind_all(self, *a, **k): pass
            def title(self, *a): pass
            def geometry(self, *a): pass
            def minsize(self, *a): pass
            def protocol(self, *a, **k): pass
            def yview(self, *a, **k): pass
            def create_window(self, *a, **k): return 1
            def itemconfig(self, *a, **k): pass
            def bbox(self, *a, **k): return (0, 0, 0, 0)
            def set(self, *a, **k): pass
            def yview_scroll(self, *a, **k): pass
            def winfo_children(self): return []
            def destroy(self): pass
            def pack_forget(self): pass
            def get(self): return self._text_value
            def create_line(self, *a, **k): pass
            def delete(self, *a, **k): pass

        class Btn(W):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                buttons.append(self)

        class Lbl(W):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                labels.append(self.text)

        class Top(W):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                tops.append(self)

        monkeypatch.setattr(ww.tk, "Toplevel", lambda parent: Top())
        monkeypatch.setattr(ww.tk, "Frame", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Canvas", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Scrollbar", lambda *a, **k: W(*a, **k))
        monkeypatch.setattr(ww.tk, "Label", lambda *a, **k: Lbl(*a, **k))
        monkeypatch.setattr(ww.tk, "Button", lambda *a, **k: Btn(*a, **k))
        monkeypatch.setattr(ww.tk, "Entry", lambda *a, **k: W(*a, **k))
        win = ww.build_window(object(), entries,
                              on_remove=lambda p: removed.append(p),
                              on_clear_session=lambda: cleared.append(1))
        return buttons, win

    def test_row_remove_callback(self, monkeypatch):
        removed, cleared = [], []
        entries = {"static": {"notepad.exe": "L2", "excel.exe": "L2"},
                   "session": {"a.exe": "L2"}}
        buttons, _ = self._build(monkeypatch, entries, removed, cleared)
        excel_btn = [b for b in buttons
                     if b.text == "移出" and b.command is not None][1]
        excel_btn.command()
        assert removed == ["excel.exe"]

    def test_clear_session_callback(self, monkeypatch):
        removed, cleared = [], []
        entries = {"static": {"notepad.exe": "L2"}, "session": {"a.exe": "L2"}}
        buttons, _ = self._build(monkeypatch, entries, removed, cleared)
        clear_btn = [b for b in buttons if b.text == "全部清空"][0]
        clear_btn.command()
        assert cleared == [1]

    def test_rows_show_display_names(self, monkeypatch):
        """管理窗口行主名显示应用显示名(与审批弹窗同源),次行含进程名。"""
        removed, cleared, labels = [], [], []
        entries = {"static": {"notepad.exe": "L2"}, "session": {}}
        self._build(monkeypatch, entries, removed, cleared, labels)
        assert "记事本" in labels                       # 显示名(直出)
        assert any("notepad.exe" in s for s in labels)  # 次行进程名(直出)

    def test_more_button_expands_beyond_five(self, monkeypatch):
        """默认每区 5 条;尖角按钮▼更多 N 项→点击展开→▲收起。"""
        removed, cleared = [], []
        entries = {"static": {f"app{i}.exe": "L2" for i in range(7)},
                   "session": {}}
        buttons, win = self._build(monkeypatch, entries, removed, cleared)
        initial = [b for b in buttons if b.text == "移出"]
        assert len(initial) == 5                        # 默认 5 条(直出)
        ui = win._manager
        more = ui._blocks["static"]["more"]
        assert more.direction == "down"                 # ▼ 收拢态(直出)
        assert more.label.text == "更多 2 项"
        more._command()                                 # 展开
        assert more.direction == "up"                   # ▲ 展开态(直出)
        assert more.label.text == "收起"
        assert len(ui._filtered(entries["static"])) == 7

    def test_scrollbar_auto_hide(self, monkeypatch):
        """滚动条按内容量显隐:行数≤容量隐藏,展开超出出现。"""
        removed, cleared = [], []
        entries = {"static": {f"app{i}.exe": "L2" for i in range(7)},
                   "session": {}}
        buttons, win = self._build(monkeypatch, entries, removed, cleared)
        ui = win._manager
        blk = ui._blocks["static"]
        assert blk["scroll_visible"] is False           # 5 行=容量,隐藏(直出)
        blk["more"]._command()                          # 展开 7 行
        assert blk["scroll_visible"] is True            # 超出容量,出现(直出)

    def test_search_filters_rows(self, monkeypatch):
        """搜索串同时匹配显示名与进程名,过滤非匹配行。"""
        removed, cleared = [], []
        entries = {"static": {"notepad.exe": "L2", "excel.exe": "L2"},
                   "session": {}}
        buttons, win = self._build(monkeypatch, entries, removed, cleared)
        ui = win._manager
        ui._query = "notepad"
        rows = ui._filtered(entries["static"])
        assert [r[0] for r in rows] == ["notepad.exe"]  # 过滤直出


class TestEnrollNotice:
    """场景:E4 入白确认 toast[撤销]回调。
    断言:on_undo 调用记录(直出)。"""

    def test_undo_callback(self, monkeypatch):
        import deskpilot.whitelist_window as ww
        undone = []
        buttons = []

        class W:
            def pack(self, *a, **k): pass
            def place(self, *a, **k): pass
            def bind(self, *a, **k): pass
            def config(self, *a, **k): pass
            def configure(self, *a, **k): pass
            def title(self, *a): pass
            def overrideredirect(self, *a): pass
            def attributes(self, *a, **k): pass
            def geometry(self, *a): pass
            def after(self, *a, **k): pass
            def winfo_screenwidth(self): return 2560
            def winfo_screenheight(self): return 1440

        class Btn(W):
            def __init__(self, *a, **k):
                self.text = k.get("text", "")
                self.command = k.get("command")
                buttons.append(self)

        monkeypatch.setattr(ww.tk, "Toplevel", lambda parent: W())
        monkeypatch.setattr(ww.tk, "Frame", lambda *a, **k: W())
        monkeypatch.setattr(ww.tk, "Label", lambda *a, **k: W())
        monkeypatch.setattr(ww.tk, "Button", lambda *a, **k: Btn(*a, **k))
        ww.build_enroll_notice(object(), "excel.exe",
                               on_undo=lambda: undone.append(1))
        undo_btn = [b for b in buttons if b.text == "撤销"][0]
        undo_btn.command()
        assert undone == [1]


# ---------- E1 托盘菜单（单元,纯函数） ----------

class TestTrayMenu:
    """场景:托盘菜单模型含管理入口。
    断言:menu_items() 返回值(直出)。"""

    def test_menu_contains_manage(self):
        from deskpilot.tray import menu_items
        ids = [item[0] for item in menu_items()]
        assert "manage" in ids


# ---------- E3 AI 请求撤回工具（单元） ----------

class TestRequestRemoveTool:
    """场景:AI 请求撤回,人类裁决后才执行。
    断言:ToolResult 直出 + admin 状态 + 撤回通道收到的进程名(替身记录)。"""

    class _FakeRevoke:
        def __init__(self, decision):
            self.decision = decision
            self.asked = []

        def request(self, process):
            self.asked.append(process)
            return self.decision

    def _ctx(self, policy, enforcement, bindings, executor, audit_log,
             tmp_path, decision):
        from deskpilot.tools import ToolContext
        a = _admin(tmp_path)
        a.add_session("excel.exe")
        ctx = ToolContext(policy=policy, enforcement=enforcement,
                          bindings=bindings, executor=executor,
                          audit=audit_log)
        object.__setattr__(ctx, "whitelist_admin", a)
        object.__setattr__(ctx, "revoke_channel", self._FakeRevoke(decision))
        return ctx, a

    def test_human_confirms_remove(self, policy, enforcement, bindings,
                                   executor, audit_log, tmp_path):
        from deskpilot import tools
        ctx, a = self._ctx(policy, enforcement, bindings, executor, audit_log,
                           tmp_path, "remove")
        r = tools.call_tool(ctx, "request_remove_from_whitelist",
                            {"process": "excel.exe"})
        assert r.ok is True
        assert r.data["removed"] is True
        assert a.cap_of("excel.exe") is None
        assert ctx.revoke_channel.asked == ["excel.exe"]

    def test_human_keeps(self, policy, enforcement, bindings, executor,
                         audit_log, tmp_path):
        from deskpilot import tools
        ctx, a = self._ctx(policy, enforcement, bindings, executor, audit_log,
                           tmp_path, "keep")
        r = tools.call_tool(ctx, "request_remove_from_whitelist",
                            {"process": "excel.exe"})
        assert r.ok is True
        assert r.data["removed"] is False
        assert a.cap_of("excel.exe") == "L2"            # 保留不动


# ---------- C 指纹审计（单元,fake audit） ----------

class _FakeAudit:
    def __init__(self):
        self.events = []

    def record_event(self, event, detail=""):
        self.events.append((event, detail))


class TestPolicyFingerprint:
    """场景:启动指纹入审计;运行期外部修改被留痕。
    断言:audit 事件记录(直出)。"""

    def test_startup_fingerprint_audited(self, tmp_path):
        from deskpilot.main import policy_sha256_audit
        p = _write_policy(tmp_path / "policy.yml", [{"process": "notepad.exe"}])
        audit = _FakeAudit()
        fp = policy_sha256_audit(str(p), audit)
        assert fp == hashlib.sha256(p.read_bytes()).hexdigest()
        assert audit.events[0][0] == "策略指纹"
        assert fp in audit.events[0][1]

    def test_external_modify_flagged(self, tmp_path):
        from deskpilot.main import _start_policy_watch
        p = _write_policy(tmp_path / "policy.yml", [{"process": "notepad.exe"}])
        audit = _FakeAudit()
        t = _start_policy_watch(str(p), audit, interval=0.05)
        try:
            time.sleep(0.15)
            p.write_text(yaml.safe_dump({"whitelist": [{"process": "evil.exe"}]}),
                         encoding="utf-8")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not audit.events:
                time.sleep(0.05)
            assert any(e[0] == "策略文件被外部修改" for e in audit.events)
        finally:
            t.stop()


# ---------- B 文案去教学（单元,grep 级） ----------

class TestMessageDeTeach:
    """场景:面向 AI 的拒绝消息不得含 policy.yml 教学。
    断言:Decision.message 字符串(直出)。"""

    def test_not_whitelisted_message_clean(self, policy, bindings, approvals,
                                           estop, executor, audit_log, tmp_path):
        a = _admin(tmp_path)
        enf = _enforcement_with_admin(policy, bindings, approvals, estop,
                                      executor, audit_log, a)
        d = enf.submit(OperationRequest("attach", {"process": "deskpilot.exe"}, None))
        assert "policy.yml" not in d.message
