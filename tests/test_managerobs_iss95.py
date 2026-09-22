"""ISS-0095 白名单管理窗打开链观测面 O1~O5 测试(TC-95-01~05,问题单 §6.3)。

背景:异机管理窗打开 >1 分钟,打开链零计时日志(慢在哪段不可观测)。
批准范围=观测面补齐(O1 拉起事件/O2 子进程分段计时 stderr 滚动日志/
O3 装配计时+慢条目留名/O4 暖机计时/O5=O1+O2 时间戳差值零代码派生);
fail-closed:埋点失败不阻断开窗/服务;不新增 HTTP 端点。

层级分布:全部单元(桩/替身允许;埋点断言=审计桩记录/真 AuditLogger
JSONL/capsys stderr/Popen 调用记录——均直出)。
入口(设计):main._open_manager_for(O1+O2 重定向)/
whitelist_window.main(O2 分段计时)/HttpDaemon GET /whitelist(O3)/
main._warm_caches_with_audit(O4 包层)。
断言出处:审计桩 records 直读/审计 JSONL 直读/capsys stderr 直读/
Popen kwargs 直出——无中间转换。

P1 红态预期:TC-95-01 红(无「管理窗拉起」事件);TC-95-02 红(Popen
无 stderr 重定向);TC-95-03 红(无「管理窗分段计时」行);TC-95-04 红
(无「白名单数据装配」事件);TC-95-05 红(O4 包层空壳)。
O5 覆盖:t0= 字段在 TC-95-03 行内钉住(派生前提),派生公式入单据。
"""

from __future__ import annotations

import dataclasses
import json
import urllib.request

import pytest

from deskpilot.httpd import HttpDaemon

from .conftest import read_audit


class _FakeAudit:
    """审计记录桩(单元层允许打桩;断言直读 records)。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def record_event(self, event: str, detail: str = "") -> None:
        self.records.append((event, detail))

    def count(self, event: str) -> int:
        return sum(1 for e, _ in self.records if e == event)

    def details(self, event: str) -> list[str]:
        return [d for e, d in self.records if e == event]


class TestO1LaunchAudited:
    """TC-95-01(O1,§6.3):托盘 on_manage 拉起打点。"""

    def test_tc95_01_open_manager_audits_launch(self, tmp_path, monkeypatch):
        """TC-95-01(单元,O1):_open_manager_for 的 _open() 在 Popen 前记
        「管理窗拉起」事件,detail 含 base_url。
        前提:Popen 桩(不真拉子进程);审计桩注入装配入参。
        断言:审计桩记录直读;Popen 调用记录直出。
        红态:现状零打点(审计桩零记录)。"""
        import deskpilot.main as m

        audit = _FakeAudit()
        popens: list[tuple] = []
        monkeypatch.setattr("subprocess.Popen",
                            lambda *a, **k: popens.append((a, k)))
        open_fn = m._open_manager_for(
            9420, audit=audit,
            stderr_log=tmp_path / "logs" / "manager-window.log")
        open_fn()
        assert popens, "拉起命令须真调 Popen(调用记录直出)"
        assert audit.count("管理窗拉起") == 1, \
            f"Popen 前须记「管理窗拉起」(审计桩直读): {audit.records}"
        assert "http://127.0.0.1:9420" in audit.details("管理窗拉起")[0]


class TestO2StderrRedirect:
    """TC-95-02(O2 重定向,§6.3):子进程 stderr→受管目录滚动日志。"""

    def test_tc95_02_popen_redirects_stderr_to_managed_log(self, tmp_path,
                                                           monkeypatch):
        """TC-95-02(单元,O2):_open() 的 Popen 携带 stderr=<受管目录
        日志文件句柄>(audit/logs 下,单文件追加);父目录不存在时自动创建;
        重定向失败静默降级不阻断拉起(另行断言见 docstring 注)。
        断言:Popen kwargs 直出(stderr.name);盘上文件路径直读。
        红态:现状 Popen 无 stderr 重定向。"""
        import deskpilot.main as m

        popens: list[tuple] = []
        monkeypatch.setattr("subprocess.Popen",
                            lambda *a, **k: popens.append((a, k)))
        log = tmp_path / "audit" / "logs" / "manager-window.log"
        open_fn = m._open_manager_for(9420, audit=_FakeAudit(),
                                      stderr_log=log)
        open_fn()
        assert popens, "拉起命令须真调 Popen(调用记录直出)"
        kwargs = popens[0][1]
        assert "stderr" in kwargs, \
            f"Popen 须携带 stderr 重定向(kwargs 直出): {sorted(kwargs)}"
        assert getattr(kwargs["stderr"], "name", None) == str(log), \
            f"stderr 目标须为受管日志文件(句柄 name 直出): {kwargs['stderr']}"
        assert log.parent.is_dir(), "日志父目录须已创建(盘上直读)"


class TestO2SegmentTiming:
    """TC-95-03(O2 分段,§6.3):管理窗进程分段计时行。"""

    def test_tc95_03_manager_main_emits_segment_timing(self, monkeypatch,
                                                       capsys):
        """TC-95-03(单元,O2):whitelist_window.main() 完成后 stderr 输出
        「管理窗分段计时」行,含 t0/boot_ms/tk_init_ms/fetch_ms/entries_n/
        fallback/build_ms/total_ms 字段(t0=O5 派生前提)。
        前提:单例检查/Tk/fetch/建窗全替身(不真开窗不真 HTTP);
        _http_json 桩返回 1 条目(真实 _fetch_whitelist 路径)。
        断言:capsys stderr 直读。
        红态:现状 main() 零计时输出。"""
        import deskpilot.whitelist_window as ww

        monkeypatch.setattr(ww, "focus_existing_or_exit", lambda title: False)
        monkeypatch.setattr("sys.argv", ["wl", "http://127.0.0.1:9420/"])

        class _Tk:
            def withdraw(self):
                pass

            def mainloop(self):
                pass

            def quit(self):
                pass

        monkeypatch.setattr(ww.tk, "Tk", lambda: _Tk())
        monkeypatch.setattr(
            ww, "_http_json",
            lambda url, payload=None: {"data": {
                "static": [{"process": "notepad.exe", "level": "L2",
                            "display": "记事本", "desc": "x"}],
                "session": []}})

        class _Win:
            def protocol(self, *a):
                pass

        monkeypatch.setattr(ww, "build_window", lambda *a, **k: _Win())
        ww.main()
        err = capsys.readouterr().err
        assert "管理窗分段计时" in err, f"stderr 须有分段计时行(直读): {err!r}"
        for field in ("t0=", "boot_ms=", "tk_init_ms=", "fetch_ms=",
                      "entries_n=1", "fallback=", "build_ms=", "total_ms="):
            assert field in err, f"计时行缺字段 {field}(直读): {err!r}"


class TestO3AssemblyTimed:
    """TC-95-04(O3,§6.3):/whitelist 装配计时+慢条目留名。"""

    def test_tc95_04_whitelist_endpoint_assembly_timed(self, ctx, tmp_path,
                                                       monkeypatch):
        """TC-95-04(单元,O3):GET /whitelist 后 daemon 审计记
        「白名单数据装配」一次,detail 含 dur_ms 与 n=1;逐条目解析超
        200ms 时 slow 留进程名。
        前提:真 HttpDaemon(临时端口)+真 WhitelistAdmin+真 AuditLogger;
        慢条目由 app_display_name 桩(阻塞 0.3s)制造。
        断言:审计 JSONL 记录对象 event/detail 直读。
        红态:现状端点零计时审计。"""
        from deskpilot.audit import AuditLogger
        from deskpilot.whitelist_admin import WhitelistAdmin

        audit_dir = tmp_path / "audit"
        ctx2 = dataclasses.replace(ctx, audit=AuditLogger(str(audit_dir)))
        admin = WhitelistAdmin(None, {"notepad.exe": "L2"})
        d = HttpDaemon(ctx2, host="127.0.0.1", port=0, whitelist_admin=admin)
        d.start()
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{d.port}/whitelist", timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            assert body["ok"] is True                # 行为不回退(响应体直出)

            import deskpilot.appnames as appnames
            import time as _time
            real = appnames.app_display_name

            def _slow(p):
                _time.sleep(0.3)                     # >200ms 阈值
                return real(p)

            monkeypatch.setattr(appnames, "app_display_name", _slow)
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{d.port}/whitelist", timeout=10) as resp:
                json.loads(resp.read().decode("utf-8"))
        finally:
            d.stop()
        events = read_audit(str(audit_dir))
        assemblies = [e for e in events
                      if e.get("event") == "白名单数据装配"]
        assert len(assemblies) >= 1, \
            "端点装配须计时审计(JSONL 直读)"
        assert "dur_ms" in assemblies[0]["detail"]
        assert "n=1" in assemblies[0]["detail"]
        slow_detail = assemblies[-1]["detail"]
        assert "notepad.exe" in slow_detail, \
            f"超 200ms 条目须留进程名(detail 直读): {slow_detail}"


class TestO4WarmCachesTimed:
    """TC-95-05(O4,§6.3):暖机计时包层。"""

    def test_tc95_05_warm_caches_timed_audit(self, monkeypatch):
        """TC-95-05(单元,O4):_warm_caches_with_audit 计时包层——成功记
        「名称缓存暖机」含 dur_ms+ok;warm_caches 抛异常 → ok=False 仍记
        且不上抛(fail-closed 不阻断启动)。
        前提:appnames.warm_caches 桩(成功/爆炸两形态);审计桩。
        断言:审计桩记录直读;调用不抛(无 pytest.raises 包装)。
        红态:O4 包层空壳(NotImplementedError)。"""
        import deskpilot.appnames as appnames
        import deskpilot.main as m

        audit = _FakeAudit()
        monkeypatch.setattr(appnames, "warm_caches", lambda **k: None)
        m._warm_caches_with_audit(audit)
        assert audit.count("名称缓存暖机") == 1, \
            f"暖机须计时审计(桩记录直读): {audit.records}"
        detail = audit.details("名称缓存暖机")[0]
        assert "dur_ms" in detail and "ok=True" in detail

        def _boom(**k):
            raise RuntimeError("桩:暖机失败")

        monkeypatch.setattr(appnames, "warm_caches", _boom)
        m._warm_caches_with_audit(audit)             # 失败不上抛
        details = audit.details("名称缓存暖机")
        assert len(details) == 2 and "ok=False" in details[1], \
            f"暖机失败须记 ok=False 且不上抛(桩记录直读): {audit.records}"
