"""REQ-002 桌面图标感知测试(TC-ICONS-01~10,测试设计 v0.1)。

层级:单元(三 provider/locator 替身,真 Assembler 本体)+ 形态
+ 集成(真 daemon+真桌面,--run-integration,断言在响应体与像素)。
入口(设计):desktop_icons.ContainerLocator/DesktopIconAssembler/
ListViewIconProvider / Executor.list_desktop_icons / TOOL_SCHEMAS。
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from deskpilot.errors import INTERNAL_ERROR, ExecutorError


class _FakeLocator:
    def __init__(self, hwnd=778899, error=None):
        self.hwnd = hwnd
        self.error = error

    def locate(self):
        if self.error:
            raise self.error
        return self.hwnd


class _FakeUia:
    def __init__(self, items, error=None):
        self.items = items       # [(display, cell_rect)]
        self.error = error

    def list(self, hwnd):
        if self.error:
            raise self.error
        return list(self.items)


class _FakeListView:
    def __init__(self, rects, error=None):
        self.rects = rects       # [graphic_rect]
        self.error = error

    def count(self, hwnd):
        return len(self.rects)

    def graphic_rect(self, hwnd, index):
        if self.error:
            raise self.error
        return self.rects[index]

    def graphic_rects(self, hwnd, indices):
        return [self.graphic_rect(hwnd, i) for i in indices]


class _FakeShellView:
    def __init__(self, sources, error=None):
        self._src_list = sources   # [str|None]
        self.error = error

    def sources(self):
        if self.error:
            raise self.error
        return list(self._src_list)


def _assembler(uia, lv, sv, locator=None):
    from deskpilot.executor.desktop_icons import DesktopIconAssembler
    return DesktopIconAssembler(locator or _FakeLocator(), uia, lv, sv)


CELL_A = [0, 5, 76, 77]
CELL_B = [76, 5, 152, 77]
G_A = [0, 5, 76, 57]
G_B = [76, 5, 152, 57]


class TestAssemble:
    """TC-ICONS-01/03/04/05/06/08:合并/序对齐/fail-closed。断言:直出。"""

    def test_icons01_merge_by_index(self):
        """TC-ICONS-01:归并主路径(ISS-0054 起=按名;序一致时与按索引同果)。"""
        a = _assembler(_FakeUia([("微信", CELL_A), ("回收站", CELL_B)]),
                       _FakeListView([G_A, G_B]),
                       _FakeShellView([r"C:\D\微信.lnk", None]))
        items = a.assemble()
        assert items[0] == {"display": "微信", "source": r"C:\D\微信.lnk",
                            "graphic_rect": G_A, "cell_rect": CELL_A}
        assert items[1] == {"display": "回收站", "source": None,
                            "graphic_rect": G_B, "cell_rect": CELL_B}

    def test_icons03_count_mismatch_fails(self):
        a = _assembler(_FakeUia([("微信", CELL_A), ("回收站", CELL_B),
                                 ("画图", [0, 80, 76, 152])]),
                       _FakeListView([G_A, G_B]),
                       _FakeShellView([None, None]))
        with pytest.raises(ExecutorError) as ei:
            a.assemble()
        assert ei.value.code == INTERNAL_ERROR
        assert "3" in str(ei.value) and "2" in str(ei.value)   # 三路 count 直出

    def test_icons04_obsolete_first_item_check(self):
        """TC-ICONS-04 已废除(ISS-0054):首项序对齐检查机制被按名归并取代;
        该场景(回收站位有路径源)新语义下正常归并,fail-closed 由
        TC-54-02(重名歧义)/TC-54-03(实体无源)承接。保留此注释作废除记录。"""
        a = _assembler(_FakeUia([("回收站", CELL_A), ("微信", CELL_B)]),
                       _FakeListView([G_A, G_B]),
                       _FakeShellView([r"C:\X\回收站.lnk", r"C:\D\微信.lnk"]))
        items = a.assemble()                      # 新语义:不再误判序对齐失败
        assert items[0]["display"] == "回收站" and items[0]["source"] is None
        assert items[1]["source"] == r"C:\D\微信.lnk"

    def test_icons05_locate_unreachable_no_empty_list(self):
        a = _assembler(_FakeUia([]), _FakeListView([]), _FakeShellView([]),
                       locator=_FakeLocator(error=OSError("桌面被替换")))
        with pytest.raises(ExecutorError) as ei:
            a.assemble()
        assert ei.value.code == INTERNAL_ERROR
        assert "locate" in str(ei.value)              # 路标(直出)
        # 禁止空列表假装成功:异常即无返回

    def test_icons06a_provider_stage_tags(self):
        for tag, uia, lv, sv in (
            ("uia", _FakeUia([], error=OSError("x")), _FakeListView([]),
             _FakeShellView([])),
            ("listview", _FakeUia([("a", CELL_A)]),
             _FakeListView([G_A], error=OSError("x")), _FakeShellView([None])),
            ("shellview", _FakeUia([("a", CELL_A)]), _FakeListView([G_A]),
             _FakeShellView([None], error=OSError("x"))),
        ):
            a = _assembler(uia, lv, sv)
            with pytest.raises(ExecutorError) as ei:
                a.assemble()
            assert tag in str(ei.value), f"缺路标 {tag}: {ei.value}"

    def test_icons06b_listview_releases_resources_on_failure(self, monkeypatch):
        """真 ListViewIconProvider 本体+替身 OS 接缝:中途失败也必须释放。"""
        from deskpilot.executor.desktop_icons import ListViewIconProvider
        calls = {"free": 0, "close": 0}

        class FakeOs:
            def open_process(self, pid):
                return 0x99

            def virtual_alloc(self, hproc, size):
                return 0xFC0000

            def write_mem(self, hproc, addr, buf, size):
                return True

            def send_itemrect(self, hwnd, index, addr):
                if index == 1:
                    raise OSError("第二项读取失败")
                return True

            def read_mem(self, hproc, addr, buf, size):
                return True

            def virtual_free(self, hproc, addr):
                calls["free"] += 1

            def close_handle(self, h):
                calls["close"] += 1

        p = ListViewIconProvider(os_seam=FakeOs())
        with pytest.raises(OSError):
            p.graphic_rects(778899, [0, 1])
        assert calls["free"] == 1                     # finally 释放(直出)
        assert calls["close"] == 1

    def test_icons08_stacked_icons_stay_separate(self):
        a = _assembler(_FakeUia([("Google", CELL_A), ("Chrome", CELL_A)]),
                       _FakeListView([G_A, G_A]),
                       _FakeShellView([r"C:\D\Google.lnk", r"C:\D\Chrome.lnk"]))
        items = a.assemble()
        assert len(items) == 2                        # 不合并不加 count
        assert items[0]["cell_rect"] == items[1]["cell_rect"]


class TestRegionFilter:
    """TC-ICONS-02:region 相交过滤(纯函数,直出)。"""

    def test_icons02_intersect_filter(self):
        from deskpilot.executor.desktop_icons import rects_intersect
        region = [0, 0, 100, 100]
        assert rects_intersect([50, 50, 150, 150], region) is True   # 相交
        assert rects_intersect([100, 100, 200, 200], region) is False  # 相触不算
        assert rects_intersect([200, 200, 300, 300], region) is False  # 不相交

    def test_icons02b_region_invalid_shape(self, policy):
        from deskpilot.errors import InvalidParamsError
        from deskpilot.mcp_server import validate_call
        with pytest.raises(InvalidParamsError):
            validate_call("list_desktop_icons", {"region": [1, 2, 3]}, policy)


class TestContainerLocator:
    """TC-ICONS-11:容器定位分支(Progman 主链/WorkerW 兜底/双失败)。"""

    class _FakeU32:
        """可编程 user32 接缝:主链与 WorkerW 链各有无可配。"""

        def __init__(self, progman_lv=0, workerw_lv=0):
            self.progman_lv = progman_lv
            self.workerw_lv = workerw_lv

        def FindWindowW(self, cls, title):
            return 500 if cls == "Progman" else 0

        def FindWindowExW(self, parent, after, cls, title):
            if parent == 500 and cls == "SHELLDLL_DefView":
                return 501 if self.progman_lv else 0
            if parent == 501 and cls == "SysListView32":
                return self.progman_lv
            if parent == 900 and cls == "SHELLDLL_DefView":
                return 901 if self.workerw_lv else 0
            if parent == 901 and cls == "SysListView32":
                return self.workerw_lv
            return 0

        def EnumWindows(self, cb, lp):
            if self.workerw_lv:
                cb(900, 0)
            return True

    def test_icons11a_progman_main_chain(self):
        from deskpilot.executor.desktop_icons import ContainerLocator
        loc = ContainerLocator(u32_seam=self._FakeU32(progman_lv=777))
        assert loc.locate() == 777

    def test_icons11b_workerw_fallback(self):
        from deskpilot.executor.desktop_icons import ContainerLocator
        loc = ContainerLocator(u32_seam=self._FakeU32(progman_lv=0,
                                                      workerw_lv=888))
        assert loc.locate() == 888

    def test_icons11c_both_fail_fails_closed(self):
        from deskpilot.errors import INTERNAL_ERROR, ExecutorError
        from deskpilot.executor.desktop_icons import ContainerLocator
        loc = ContainerLocator(u32_seam=self._FakeU32())
        with pytest.raises(ExecutorError) as ei:
            loc.locate()
        assert ei.value.code == INTERNAL_ERROR
        assert "locate" in str(ei.value)

    def test_icons11d_empty_desktop_returns_empty(self):
        """真空桌面:三路皆空,如实返回空(非错误)。"""
        a = _assembler(_FakeUia([]), _FakeListView([]), _FakeShellView([]))
        assert a.assemble() == []


class TestSchema:
    """TC-ICONS-07:schema 形态(直出)。"""

    def test_icons07_schema_shape(self):
        from deskpilot.mcp_server import TOOL_SCHEMAS
        from deskpilot.models import TOOL_LEVELS
        s = TOOL_SCHEMAS["list_desktop_icons"]
        assert TOOL_LEVELS["list_desktop_icons"] == "L0"
        assert s["optional"]["region"] == ("rect",)
        d = s["description"]
        assert len(d) <= 200
        assert any(h in d for h in ("Windows", "桌面", "窗口", "浏览器"))
        assert "null" in d                            # 虚拟项 source 说明
        assert "ocr" in d                             # 与 ocr:true 分工


@pytest.mark.integration
class TestRealDesktop:
    """TC-ICONS-09/10(集成):真 daemon+真桌面,零替身。"""

    def _call(self, port, tool, params, timeout=30):
        body = json.dumps({"tool": tool, "params": params}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/call", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _daemon(self, policy, audit_log, tmp_path):
        from deskpilot.estop import EstopMonitor
        from deskpilot.executor import DesktopProbe, Executor
        from deskpilot.httpd import HttpDaemon
        from deskpilot.tools import ToolContext
        estop = EstopMonitor(policy.corner_hold_ms, time.monotonic, audit_log)
        executor = Executor(estop, str(tmp_path / "audit"),
                            probe=DesktopProbe(), audit=audit_log)
        ctx = ToolContext(policy=policy, enforcement=None, bindings=None,
                          executor=executor, audit=audit_log)
        d = HttpDaemon(ctx, port=0)
        d.start()
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{d.port}/health", timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        return d

    def test_icons09_real_desktop_inventory(self, policy, audit_log, tmp_path):
        d = self._daemon(policy, audit_log, tmp_path)
        try:
            r = self._call(d.port, "list_desktop_icons", {})
            assert r["ok"] is True, r.get("message")
            items = r["data"]["items"]
            # 环境不变量断言(修复:原 ">=25" 与具名图标抽验打在本机富桌面上,
            # 干净 CI runner 仅 6 图标必败——断言只许打在环境无关不变量上):
            # 数量自洽 + 回收站虚拟项 + 实体项 source/graphic 链路存在
            assert r["data"]["count"] == len(items) >= 1
            names = [i["display"] for i in items]
            # 虚拟项在场且如实 null——名录单源引用,本地化无关
            # (CI runner 英文系统实证:显示名为 "Recycle Bin" 非「回收站」)
            from deskpilot.executor.desktop_icons import _VIRTUAL_FIRST_NAMES
            virtual = [i for i in items if (i["display"] or "").strip().lower()
                       in _VIRTUAL_FIRST_NAMES]
            assert virtual, f"虚拟项(回收站)不在清单: {names}"
            assert all(i["source"] is None for i in virtual)
            real = [i for i in items if (i["display"] or "").strip().lower()
                    not in _VIRTUAL_FIRST_NAMES]
            if real:                                   # 桌面有实体项时:
                assert any(i["source"] for i in real)  # PIDL→path 链路实证
            # 图形真实性抽验(泛化不具名):可见(未被遮挡)图形的中心像素非空;
            # 可见性判定同 ct12(WindowFromPoint 属 Progman 链)
            import ctypes
            from ctypes import wintypes
            from PIL import Image
            u32 = ctypes.windll.user32
            pm_hwnd = u32.FindWindowW("Progman", None)
            shot = self._call(d.port, "screenshot", {"scope": "fullscreen"})
            im = Image.open(shot["data"]["path"]).convert("RGB")
            checked = 0
            for it in items:
                g = it.get("graphic_rect")
                if not g:
                    continue
                cx, cy = (g[0] + g[2]) // 2, (g[1] + g[3]) // 2
                if not (0 <= cx < im.width and 0 <= cy < im.height):
                    continue                          # 屏外项跳过
                h = u32.WindowFromPoint(wintypes.POINT(cx, cy))
                if not (h == pm_hwnd or u32.IsChild(pm_hwnd, h)):
                    continue                          # 被遮挡项跳过(环境守卫)
                n = sum(1 for x in range(cx - 8, cx + 8)
                        for y in range(cy - 8, cy + 8)
                        if im.getpixel((x, y)) != (0, 0, 0))
                assert n > 40, f"{it['display']} graphic 中心附近无图形"
                checked += 1
                if checked >= 3:
                    break
            if not checked:
                pytest.skip("当前桌面图标全被遮挡(环境守卫——清桌面后跑)")
            # 栈叠同 rect 各成一条(若存在)
            rects = [tuple(i["cell_rect"]) for i in items]
            assert len(rects) == len(items)           # 数量守恒(未合并)
        finally:
            d.stop()

    def test_icons10_real_region_filter(self, policy, audit_log, tmp_path):
        d = self._daemon(policy, audit_log, tmp_path)
        try:
            full = self._call(d.port, "list_desktop_icons", {})
            region = [0, 0, 230, 300]          # 左上小角(必为全量子集)
            part = self._call(d.port, "list_desktop_icons",
                              {"region": region})
            assert part["ok"] is True
            for it in part["data"]["items"]:
                c = it["cell_rect"]
                assert c[0] < region[2] and c[2] > region[0] \
                    and c[1] < region[3] and c[3] > region[1]
            assert 0 < part["data"]["count"] < full["data"]["count"]
        finally:
            d.stop()
