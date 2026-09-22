"""ISS-0046 daemon 单例与冻结弹窗去重单元测试(TC-46-01~04,问题单 §2)。

层级:单元(main() 全替身装配;build_window 的 Tk 全桩;互斥体语义既有单锁定)。
入口(设计):main.main / freeze_dialog.build_window(公开入口)。
断言值来源:main 返回值 / 审计 JSONL / 桩调用记录 / build_window 返回值——直出。

语义钉:
- A:--daemon 实例启动预检,9420 已有属主 → 审计+显式返回 4,不起甩角监听、
  不绑端口(不僵尸);probe→bind 竞态败者同样干净退出(不抛栈);
- B:build_window 建窗前原子抢跨进程命名互斥(共享线程路径与子进程路径
  同锁收口),抢不到 → None 不建窗;窗毁(Destroy)释放;
- C:甩角监听归属由 A 覆盖(非属主 daemon 退出即无监听),stdio 全功能实例
  (daemon 离线时)保留自身甩角(安全通道不留空洞),弹窗去重由 B 兜底。

测试设计(五要素):
- TC-46-01 场景=--daemon 预检已有属主;前提=probe→True;
  步骤=main();预期=rc 4+审计「daemon 单例退出」+甩角监听桩 0 调;
  断言=返回值/审计/桩计数直出。
- TC-46-02 场景=绑定竞争败者;前提=probe→False+start 抛 RuntimeError;
  预期=rc 4+审计「daemon 单例退出」(不抛栈);断言=返回值/审计直出。
- TC-46-03 场景=共享线程路径互斥未抢到;前提=acquire_singleton→False;
  步骤=build_window;预期=None 且 Toplevel 0 调;断言=返回值+桩计数直出。
- TC-46-04 场景=抢到互斥建窗,窗毁释放;前提=acquire→True+Tk 全桩;
  步骤=build_window→手动触发 Destroy 回调;预期=release_singleton 恰 1 次;
  断言=桩计数直出。
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import yaml

from deskpilot.audit_events import (
    EV_DAEMON_SINGLETON_EXIT)
from .conftest import policy_yaml_dict, read_audit


def _main_stubs(monkeypatch, tmp_path, probe_online, daemon_start_raises=None):
    """main() 装配替身:策略落临时目录、探活/监听/弹窗/执行器/HTTP/托盘全桩。

    返回 (main 模块, 桩记录 dict)。time.sleep 首调即 KeyboardInterrupt,
    防旧代码路径走进常驻 while 循环挂死测试。
    """
    import deskpilot.main as m

    policy_file = tmp_path / "policy.yml"
    policy_file.write_text(yaml.dump(policy_yaml_dict(str(tmp_path / "audit"))),
                           encoding="utf-8")
    monkeypatch.setattr(m, "_find_policy_path", lambda: policy_file)
    monkeypatch.setattr(m, "probe_daemon", lambda *a, **k: probe_online)
    rec = {"estop_start": Mock(), "tray": Mock()}
    monkeypatch.setattr(m, "_start_estop_listeners", rec["estop_start"])
    monkeypatch.setattr("deskpilot.dialog_service.get_dialog_service",
                        lambda: Mock())
    monkeypatch.setattr(m, "Executor", Mock())
    monkeypatch.setattr(m, "TrayIcon", rec["tray"], raising=False)
    monkeypatch.setattr("deskpilot.tray.TrayIcon", rec["tray"])

    class FakeDaemon:
        def __init__(self, *a, **k):
            self.port = 9420

        def start(self):
            if daemon_start_raises is not None:
                raise daemon_start_raises

        def stop(self):
            pass

    monkeypatch.setattr("deskpilot.httpd.HttpDaemon", FakeDaemon)
    monkeypatch.setattr(m.time, "sleep",
                        lambda _s: (_ for _ in ()).throw(KeyboardInterrupt()))
    return m, rec


class TestDaemonSingleton:
    def test_tc46_01_daemon_precheck_exits_when_owner_online(
            self, tmp_path, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["deskpilot", "--daemon"])
        m, rec = _main_stubs(monkeypatch, tmp_path, probe_online=True)
        rc = m.main()
        assert rc == 4                            # 显式退出码(直出)
        assert rec["estop_start"].call_count == 0  # 甩角/热键监听未起
        events = [e["event"] for e in read_audit(str(tmp_path / "audit"))]
        assert EV_DAEMON_SINGLETON_EXIT in events

    def test_tc46_02_bind_race_loser_exits_cleanly(self, tmp_path, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["deskpilot", "--daemon"])
        m, _rec = _main_stubs(monkeypatch, tmp_path, probe_online=False,
                              daemon_start_raises=RuntimeError("端口被占"))
        rc = m.main()                             # 不得抛栈(直出)
        assert rc == 4
        events = [e["event"] for e in read_audit(str(tmp_path / "audit"))]
        assert EV_DAEMON_SINGLETON_EXIT in events


class TestFreezeDialogSingletonGuard:
    def test_tc46_03_build_skipped_when_mutex_held(self, monkeypatch):
        import deskpilot.freeze_dialog as fd
        monkeypatch.setattr(fd, "acquire_singleton", lambda: False)
        toplevel = Mock()
        monkeypatch.setattr("tkinter.Toplevel", toplevel)
        win = fd.build_window(Mock(), "dummy", 180.0,
                              target_screen={"rect": (0, 0, 1920, 1080),
                                             "work_area": (0, 0, 1920, 1032)})
        assert win is None                        # 未抢到不建窗(直出)
        assert toplevel.call_count == 0

    def test_tc46_04_destroy_releases_mutex(self, monkeypatch):
        import deskpilot.freeze_dialog as fd
        monkeypatch.setattr(fd, "acquire_singleton", lambda: True)
        release = Mock()
        monkeypatch.setattr(fd, "release_singleton", release)
        win = Mock()                                  # Toplevel 替身
        monkeypatch.setattr("tkinter.Toplevel", Mock(return_value=win))
        monkeypatch.setattr("tkinter.Canvas", Mock())
        monkeypatch.setattr("tkinter.Label", Mock())
        monkeypatch.setattr("tkinter.Button", Mock())
        out = fd.build_window(Mock(), "dummy", 180.0,
                              target_screen={"rect": (0, 0, 1920, 1080),
                                             "work_area": (0, 0, 1920, 1032)})
        assert out is win                             # 抢到即建窗(直出)
        destroys = [c for c in win.bind.call_args_list
                    if c.args and c.args[0] == "<Destroy>"]
        assert destroys, "建窗必须绑定 Destroy 释放互斥(接线断言)"
        for c in destroys:
            c.args[1](Mock(widget=win))               # 手动触发窗毁回调
        assert release.call_count == 1                # 互斥恰释放一次(直出)
