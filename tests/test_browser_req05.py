"""REQ-005 浏览器翻译层测试(TC-BR-01~21/23~25,测试设计 §1 表逐行落码)。

层级分布(§3 层级边界):
- 形态:TC-BR-01/02/23/24/25(注册表/源码/i18n.yml 直读,无执行)
- 单元:TC-BR-03~21(通道/管理器替身允许,断言=返回值逐字段/异常 code
  属性/替身调用记录直出)
assembly:TC-BR-22 → tests/test_browserws_req05.py;
集成:TC-BR-26~28 → tests/test_browserint_req05.py。

入口(设计):deskpilot/browser/router.route(M1)/snapshot.browser_snapshot
/rect.browser_get_rect/manager.ensure_instance·reclaim·probe(M4)/
cdp.connect(M5);TOOL_SCHEMAS/TOOL_LEVELS/audit_events/i18n.yml 直读。
断言出处:注册表直读/源码检索直读/返回值逐字段直出/异常 code 属性直出/
替身调用记录直出——均直出,无中间转换。

替身缝约定(P3 实现须按此缝;拟定缝,已列上报裁决点):
- 通道替身(channel double):以 duck-type 对象注入 route/browser_snapshot/
  browser_get_rect 的同名形参(cdp/uia/ocr),被调即记 calls;
  cdp 通道替身面:snapshot()→AX 样本(含 meta.url)、
  element_box(name, control_type, index)→CSS rect、render_origin()、dpr();
  uia 通道替身面:snapshot()→统一元素样本(可编程首空后有)、
  rect_of(name, control_type, index)→屏幕 rect;
- 管理器替身:lookup(hwnd)/ensure_instance()/probe(instance) 记录面;
  manager 模块函数以 registry(内存 dict)+可调用缝(launch/alive/
  kill_by_profile/port_alive/process_alive)注入;
- 懒启用等待缝:monkeypatch 标准 time 模块 sleep(T1-02 等 ≤3s 钉);
- 顶层判定缝:browser_get_rect 的 topmost 形参(遮挡自检,T2-03)。

P1 红态预期:TC-BR-03~23 红(包空壳 NotImplementedError/R-MAP 未落);
TC-BR-01/02/24/25 绿(P1 空壳声明已落,ISS-0101 先例)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deskpilot.errors import (ELEMENT_NOT_FOUND, INVALID_PARAMS,
                              OUT_OF_BOUNDS, WINDOW_GONE, ExecutorError)
from deskpilot.mcp_server import TOOL_SCHEMAS
from deskpilot.models import TOOL_LEVELS

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "deskpilot"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


# ---------- 替身套件(缝约定见模块 docstring) ----------

class _Rec:
    def __init__(self):
        self.calls: list[str] = []

    def _rec(self, name):
        self.calls.append(name)


class _CdpChannel(_Rec):
    """CDP 通道替身:固定 AX 样本/三因子定值(缝约定面)。"""

    def __init__(self, *, ax=None, meta=None, box=None, origin=(1000, 200),
                 dpr=2.0):
        super().__init__()
        self._ax = ax if ax is not None else []
        self._meta = meta or {"url": "https://example.com/", "title": "示例"}
        self._box = box                       # CSS rect 定值或异常
        self._origin = origin
        self._dpr = dpr
        self.factor_calls = {"element_box": 0, "render_origin": 0, "dpr": 0}

    def snapshot(self):
        self._rec("cdp.snapshot")
        return {"elements": self._ax, "meta": self._meta}

    def element_box(self, name=None, control_type=None, index=None):
        self.factor_calls["element_box"] += 1
        if isinstance(self._box, Exception):
            raise self._box
        return self._box

    def render_origin(self):
        self.factor_calls["render_origin"] += 1
        return self._origin

    def dpr(self):
        self.factor_calls["dpr"] += 1
        return self._dpr


class _UiaChannel(_Rec):
    """UIA 通道替身:可编程快照序列(懒启用首空后有)/rect 定值。"""

    def __init__(self, *, snapshots=None, rect=(10, 20, 110, 60),
                 elements=None):
        super().__init__()
        self._snapshots = list(snapshots) if snapshots is not None else None
        self._rect = rect
        self._elements = elements or []

    def snapshot(self):
        self._rec("uia.snapshot")
        if self._snapshots is not None:
            return self._snapshots.pop(0) if len(self._snapshots) > 1 \
                else self._snapshots[0]
        return {"elements": self._elements,
                "meta": {"url": "", "title": "用户自拉浏览器"}}

    def rect_of(self, name=None, control_type=None, index=None):
        self._rec("uia.rect_of")
        return self._rect


class _OcrChannel(_Rec):
    def snapshot(self):
        self._rec("ocr.snapshot")
        return {"elements": [{"name": "确定", "control_type": "Text",
                              "rect": [1, 2, 30, 14], "interactable": False,
                              "state": {}}],
                "meta": {"url": "", "title": ""}}


class _Manager(_Rec):
    """管理器替身:lookup/ensure_instance/probe 记录面。"""

    def __init__(self, *, registered=None, alive=True):
        super().__init__()
        self._registered = registered or {}      # hwnd → 注册表项
        self._alive = alive
        self.instance = {"hwnd": 777, "port": 53333,
                         "profile": r"C:\tmp\dp-browser-profile",
                         "launched_at": 0.0, "binary": "edge"}

    def lookup(self, hwnd):
        self._rec("manager.lookup")
        return self._registered.get(hwnd)

    def ensure_instance(self):
        self._rec("manager.ensure_instance")
        return self.instance

    def probe(self, instance):
        self._rec("manager.probe")
        return self._alive


# ---------- TC-BR-01/02/23/24/25 形态钉 ----------

class TestRegistrationFace:
    """TC-BR-01/02/23/24/25(形态):注册面合规/禁进程名路由/R-MAP/
    冻结零分支/拉起提示双语。源码与注册表直读,无执行。"""

    def test_br01_tool_registry_compliant(self):
        """TC-BR-01(形态):两工具在册、L0、计数 32、描述 ≤200 且含
        「共管浏览器」备选路径措辞(ISS-0115)。断言:注册表直读。
        绿态:P1 空壳声明已落。"""
        assert len(TOOL_SCHEMAS) == 32, \
            f"TOOL_SCHEMAS 计数(直读): {len(TOOL_SCHEMAS)}"
        for tool in ("browser_snapshot", "browser_get_rect"):
            assert tool in TOOL_SCHEMAS, f"{tool} 未注册(直读)"
            assert TOOL_LEVELS[tool] == "L0", \
                f"{tool} 级别(直读): {TOOL_LEVELS.get(tool)}"
            desc = TOOL_SCHEMAS[tool]["description"]
            assert len(desc) <= 200, \
                f"{tool} 描述超长(直读): {len(desc)}"
            assert "共管浏览器" in desc, \
                f"{tool} 描述缺「共管浏览器」备选路径措辞(ISS-0115,直读)"

    def test_br02_no_process_name_routing(self):
        """TC-BR-02(形态钉):路由器无按进程名(msedge/chrome/firefox)
        的通道选择分支(M4 二进制探测不受本钉约束)。断言:源码检索为空。
        绿态:P1 空壳天然合规。"""
        src = _read("browser/router.py").lower()
        for token in ("msedge", "chrome", "firefox"):
            assert token not in src, \
                f"路由器存在进程名通道选择痕迹(直读): {token}"

    def test_br23_rmap_complete(self):
        """TC-BR-23(形态):R-MAP 含 §3.5 全部角色映射;未映射走
        raw_role。断言:源码检索直读。红态:P1 空壳未落 R-MAP。"""
        src = _read("browser/cdp.py")
        for role in ("button", "link", "textbox", "searchbox", "checkbox",
                     "combobox", "StaticText", "image", "list", "listitem",
                     "heading", "dialog"):
            assert role in src, f"R-MAP 缺角色(直读): {role}"
        for ctl in ("ButtonControl", "HyperlinkControl", "EditControl",
                    "CheckBoxControl", "ComboBoxControl", "TextControl",
                    "ImageControl", "ListControl", "ListItemControl",
                    "WindowControl"):
            assert ctl in src, f"R-MAP 缺目标控件型(直读): {ctl}"
        assert "raw_role" in src, "未映射项须透传 raw_role(直读)"

    def test_br24_no_freeze_branch(self):
        """TC-BR-24(形态):browser 包无 estop/secure_desktop 条件分支
        (沿用既有 L0 闸门)。断言:源码检索命中为空。绿态:P1 天然合规。"""
        pkg = SRC / "browser"
        for f in pkg.glob("*.py"):
            src = f.read_text(encoding="utf-8")
            for token in ("estop", "secure_desktop"):
                assert token not in src, \
                    f"{f.name} 出现冻结/安全桌面分支痕迹(直读): {token}"

    def test_br25_launch_hint_dual_language(self):
        """TC-BR-25(形态):拉起提示键 en/zh 双键非空。断言:YAML 解析直读。
        绿态:P1 空壳声明已落。"""
        doc = yaml.safe_load(
            (SRC / "i18n.yml").read_text(encoding="utf-8"))
        for key in ("br.launch.title", "br.launch.hint"):
            for lang in ("en", "zh-CN"):
                text = doc.get(lang, {}).get(key, "")
                assert isinstance(text, str) and text.strip(), \
                    f"{lang} 缺键 {key}(直读)"


# ---------- TC-BR-03~06 单元:路由判定 ----------

class TestRouteDecision:
    """TC-BR-03~06(单元):空 window→共管;注册表命中→CDP;实例死亡→
    WINDOW_GONE;其余→UIA。替身通道/拉起调用记录直出。"""

    def test_br03_empty_window_routes_managed_cdp(self):
        """TC-BR-03:route(None) → 走 CDP 通道且触发一次幂等拉起。
        红态:route 空壳 NotImplementedError。"""
        from deskpilot.browser.router import route
        mgr, cdp, uia = _Manager(), _CdpChannel(), _UiaChannel()
        route(None, manager=mgr, cdp=cdp, uia=uia)
        assert mgr.calls.count("manager.ensure_instance") == 1, \
            f"幂等拉起应恰一次(替身记录直出): {mgr.calls}"
        assert "cdp.snapshot" in cdp.calls, \
            f"应走 CDP 通道(替身记录直出): {cdp.calls}"
        assert uia.calls == [], \
            f"UIA 通道不应被触(替身记录直出): {uia.calls}"

    def test_br04_registered_window_routes_cdp_no_launch(self):
        """TC-BR-04:route(hwnd=注册表实例窗) → CDP 通道,不触发拉起。
        红态:route 空壳。"""
        from deskpilot.browser.router import route
        mgr = _Manager(registered={777: {"hwnd": 777, "port": 53333}})
        cdp, uia = _CdpChannel(), _UiaChannel()
        route(777, manager=mgr, cdp=cdp, uia=uia)
        assert "cdp.snapshot" in cdp.calls, \
            f"注册表命中应走 CDP(替身记录直出): {cdp.calls}"
        assert "manager.ensure_instance" not in mgr.calls, \
            f"存活实例不得重复拉起(替身记录直出): {mgr.calls}"

    def test_br05_dead_instance_window_gone_no_fallback(self):
        """TC-BR-05:注册表含死实例(探活失败) → WINDOW_GONE+重新拉起
        指引;不降级 UIA。断言:异常 code/消息直出。红态:route 空壳。"""
        from deskpilot.browser.router import route
        mgr = _Manager(registered={777: {"hwnd": 777, "port": 53333}},
                       alive=False)
        cdp, uia = _CdpChannel(), _UiaChannel()
        with pytest.raises(ExecutorError) as ei:
            route(777, manager=mgr, cdp=cdp, uia=uia)
        assert ei.value.code == WINDOW_GONE, \
            f"实例死亡应 WINDOW_GONE(异常 code 直出): {ei.value.code}"
        assert "拉起" in str(ei.value), \
            f"消息须含重新拉起指引(直出): {ei.value}"
        assert cdp.calls == [] and uia.calls == [], \
            f"死实例不得降级任何通道(替身记录直出): {cdp.calls}{uia.calls}"

    def test_br06_other_window_routes_uia(self):
        """TC-BR-06:非注册表窗口 → UIA 通道。红态:route 空壳。"""
        from deskpilot.browser.router import route
        mgr, cdp, uia = _Manager(), _CdpChannel(), _UiaChannel()
        route(4242, manager=mgr, cdp=cdp, uia=uia)
        assert "uia.snapshot" in uia.calls, \
            f"其余窗口应走 UIA(替身记录直出): {uia.calls}"
        assert cdp.calls == [], \
            f"不得走 CDP(替身记录直出): {cdp.calls}"


# ---------- TC-BR-07~11 单元:快照 schema/截断/懒启用 ----------

_AX_SAMPLE = [
    {"role": "button", "name": "提交", "rect": [10, 20, 90, 32],
     "focusable": True, "state": {}},
    {"role": "link", "name": "详情", "rect": [10, 60, 60, 18],
     "focusable": True, "state": {}},
    {"role": "textbox", "name": "搜索", "rect": [10, 90, 200, 24],
     "focusable": True, "state": {}},
    {"role": "mycustomrole", "name": "自绘件", "rect": [10, 120, 40, 40],
     "focusable": False, "state": {}},
]


class TestSnapshotShape:
    """TC-BR-07~11(单元):schema 归一/800 截断/懒启用复走/像素兜底。"""

    def test_br07_schema_normalized_and_raw_role_passthrough(self):
        """TC-BR-07:CDP 替身固定 AX 样本 → 元素含
        name/control_type/rect/interactable;role 映射按 R-MAP;未映射项
        raw_role 透传;meta 含 source=cdp/url。逐字段直出。
        红态:browser_snapshot 空壳。"""
        from deskpilot.browser.snapshot import browser_snapshot
        cdp = _CdpChannel(ax=list(_AX_SAMPLE))
        out = browser_snapshot(777, cdp=cdp)
        assert out["source"] == "cdp", f"source(直出): {out.get('source')}"
        assert out["url"] == "https://example.com/", \
            f"url(直出): {out.get('url')!r}"
        by_name = {e["name"]: e for e in out["elements"]}
        for e in out["elements"]:
            for field in ("name", "control_type", "rect", "interactable"):
                assert field in e, f"元素缺字段(直出): {field} in {e}"
        assert by_name["提交"]["control_type"] == "ButtonControl", \
            f"R-MAP button(直出): {by_name['提交']}"
        assert by_name["详情"]["control_type"] == "HyperlinkControl", \
            f"R-MAP link(直出): {by_name['详情']}"
        assert by_name["搜索"]["control_type"] == "EditControl", \
            f"R-MAP textbox(直出): {by_name['搜索']}"
        custom = by_name["自绘件"]
        assert custom.get("raw_role") == "mycustomrole", \
            f"未映射 role 须 raw_role 透传(直出): {custom}"

    def test_br08_truncation_at_800(self):
        """TC-BR-08:通道替身返回 801 元素 → elements=800 且
        truncated=true。红态:空壳。"""
        from deskpilot.browser.snapshot import browser_snapshot
        ax = [{"role": "StaticText", "name": f"t{i}", "rect": [0, i, 1, 1],
               "focusable": False, "state": {}} for i in range(801)]
        out = browser_snapshot(777, cdp=_CdpChannel(ax=ax))
        assert len(out["elements"]) == 800, \
            f"截断上限(直出): {len(out['elements'])}"
        assert out["truncated"] is True, \
            f"truncated(直出): {out.get('truncated')}"

    def test_br09_lazy_enable_waits_and_retries_once(self, monkeypatch):
        """TC-BR-09:UIA 替身首查空、复走有内容 → 等待(≤3s)后复走得
        内容;source=uia;替身调用次数=2+等待时序直出。红态:空壳。"""
        import time as time_mod

        from deskpilot.browser.snapshot import browser_snapshot
        sleeps: list[float] = []
        monkeypatch.setattr(time_mod, "sleep",
                            lambda s: sleeps.append(s))
        uia = _UiaChannel(snapshots=[{"elements": [], "meta": {}},
                                     {"elements": [
                                         {"name": "登录", "control_type":
                                          "ButtonControl", "rect": [1, 2, 3, 4],
                                          "interactable": True, "state": {}}],
                                      "meta": {"url": "", "title": "t"}}])
        out = browser_snapshot(4242, uia=uia)
        assert uia.calls.count("uia.snapshot") == 2, \
            f"懒启用须复走(替身计数直出): {uia.calls}"
        assert sleeps and max(sleeps) <= 3.0, \
            f"单次等待 ≤3s(时序记录直出): {sleeps}"
        assert out["source"] == "uia", f"source(直出): {out.get('source')}"
        assert [e["name"] for e in out["elements"]] == ["登录"], \
            f"复走后元素(直出): {out['elements']}"

    def test_br10_lazy_enable_retry_only_once_then_fail(self, monkeypatch):
        """TC-BR-10:UIA 两查皆空;允许兜底=否 → ELEMENT_NOT_FOUND(消息
        含「共管浏览器」指引);查询次数=2 不多不少。红态:空壳。"""
        import time as time_mod

        from deskpilot.browser.snapshot import browser_snapshot
        monkeypatch.setattr(time_mod, "sleep", lambda s: None)
        uia = _UiaChannel(snapshots=[{"elements": [], "meta": {}},
                                     {"elements": [], "meta": {}}])
        with pytest.raises(ExecutorError) as ei:
            browser_snapshot(4242, uia=uia, allow_pixel_fallback=False)
        assert ei.value.code == ELEMENT_NOT_FOUND, \
            f"两查皆空应 ELEMENT_NOT_FOUND(code 直出): {ei.value.code}"
        assert "共管浏览器" in str(ei.value), \
            f"消息须含共管浏览器指引(直出): {ei.value}"
        assert uia.calls.count("uia.snapshot") == 2, \
            f"复走只此一次(替身计数直出): {uia.calls}"

    def test_br11_pixel_fallback_branch(self, monkeypatch):
        """TC-BR-11:UIA 两查皆空;允许兜底 → 走 OCR 通道,source=ocr。
        红态:空壳。"""
        import time as time_mod

        from deskpilot.browser.snapshot import browser_snapshot
        monkeypatch.setattr(time_mod, "sleep", lambda s: None)
        uia = _UiaChannel(snapshots=[{"elements": [], "meta": {}},
                                     {"elements": [], "meta": {}}])
        ocr = _OcrChannel()
        out = browser_snapshot(4242, uia=uia, ocr=ocr,
                               allow_pixel_fallback=True)
        assert "ocr.snapshot" in ocr.calls, \
            f"兜底须走 OCR 通道(替身记录直出): {ocr.calls}"
        assert out["source"] == "ocr", \
            f"source(直出): {out.get('source')}"


# ---------- TC-BR-12~17 单元:坐标换算/遮挡/零命中/歧义/超界 ----------

class TestGetRect:
    """TC-BR-12~17(单元):CDP 换算/UIA 零换算/遮挡自检/零命中候选/
    歧义未给 index/超界 fail-closed。"""

    def test_br12_cdp_rect_three_factor_live(self):
        """TC-BR-12:CDP 替身渲染窗原点(1000,200)/元素 CSS rect
        (40,25,60,35)/dpr=2.0 → rect=原点+CSS×dpr=
        [1080,250,1120,270];三因子各取一次。红态:空壳。"""
        from deskpilot.browser.rect import browser_get_rect
        cdp = _CdpChannel(box={"left": 40, "top": 25, "right": 60,
                               "bottom": 35})
        out = browser_get_rect(777, name="提交", cdp=cdp)
        assert out["rect"] == [1080, 250, 1120, 270], \
            f"三因子换算(直出): {out.get('rect')}"
        for factor in ("element_box", "render_origin", "dpr"):
            assert cdp.factor_calls[factor] == 1, \
                f"{factor} 须每次现取恰一次(替身计数直出): " \
                f"{cdp.factor_calls}"

    def test_br13_uia_rect_zero_conversion(self):
        """TC-BR-13:UIA 替身元素 rect 定值 → 原样直出。红态:空壳。"""
        from deskpilot.browser.rect import browser_get_rect
        out = browser_get_rect(4242, name="登录",
                               uia=_UiaChannel(rect=(10, 20, 110, 60)))
        assert out["rect"] == [10, 20, 110, 60], \
            f"UIA 零换算(直出): {out.get('rect')}"

    def test_br14_occlusion_self_check(self):
        """TC-BR-14:顶层判定替身顶层≠目标 → occluded=true 且
        top_element=顶层名;rect 照给。红态:空壳。"""
        from deskpilot.browser.rect import browser_get_rect
        out = browser_get_rect(
            4242, name="登录", uia=_UiaChannel(rect=(10, 20, 110, 60)),
            topmost=lambda point: "钉钉升级提示")
        assert out["occluded"] is True, \
            f"occluded(直出): {out.get('occluded')}"
        assert out["top_element"] == "钉钉升级提示", \
            f"top_element(直出): {out.get('top_element')!r}"
        assert out["rect"] == [10, 20, 110, 60], \
            f"遮挡时 rect 照给(直出): {out.get('rect')}"

    def test_br15_zero_hit_candidates(self):
        """TC-BR-15:替身快照无该名但有相似名 → ELEMENT_NOT_FOUND+
        候选清单(≤5)。红态:空壳。"""
        from deskpilot.browser.rect import browser_get_rect
        uia = _UiaChannel(elements=[
            {"name": "提交按钮", "control_type": "ButtonControl",
             "rect": [1, 2, 3, 4], "interactable": True, "state": {}},
            {"name": "提交表单", "control_type": "ButtonControl",
             "rect": [5, 6, 7, 8], "interactable": True, "state": {}}])
        with pytest.raises(ExecutorError) as ei:
            browser_get_rect(4242, name="提交订", uia=uia)
        assert ei.value.code == ELEMENT_NOT_FOUND, \
            f"code(直出): {ei.value.code}"
        msg = str(ei.value)
        assert "提交按钮" in msg and "提交表单" in msg, \
            f"相似候选须附(直出): {msg}"

    def test_br16_ambiguous_without_index(self):
        """TC-BR-16:替身快照两个同名 → INVALID_PARAMS+候选清单。
        红态:空壳。"""
        from deskpilot.browser.rect import browser_get_rect
        uia = _UiaChannel(elements=[
            {"name": "删除", "control_type": "ButtonControl",
             "rect": [1, 2, 3, 4], "interactable": True, "state": {}},
            {"name": "删除", "control_type": "ButtonControl",
             "rect": [5, 6, 7, 8], "interactable": True, "state": {}}])
        with pytest.raises(ExecutorError) as ei:
            browser_get_rect(4242, name="删除", uia=uia)
        assert ei.value.code == INVALID_PARAMS, \
            f"code(直出): {ei.value.code}"
        assert "index" in str(ei.value), \
            f"歧义须指引 index(直出): {ei.value}"

    def test_br17_out_of_bounds_fail_closed(self):
        """TC-BR-17:CDP 替身元素中心越出渲染窗 → 报错(非静默给点)。
        拟定码=OUT_OF_BOUNDS(零新增码面,已列上报裁决点)。红态:空壳。"""
        from deskpilot.browser.rect import browser_get_rect
        cdp = _CdpChannel(box={"left": 40, "top": 25, "right": 60000,
                               "bottom": 35})
        with pytest.raises(ExecutorError) as ei:
            browser_get_rect(777, name="提交", cdp=cdp)
        assert ei.value.code == OUT_OF_BOUNDS, \
            f"超界须 fail-closed(code 直出): {ei.value.code}"


# ---------- TC-BR-18~20 单元:管理器生命周期 ----------

class TestManagerLifecycle:
    """TC-BR-18~20(单元):幂等拉起/回收清理/探活双查。"""

    def test_br18_ensure_idempotent_reuse(self):
        """TC-BR-18:注册表已有存活实例 → ensure_instance 不再拉起,
        直接复用。红态:空壳。"""
        from deskpilot.browser.manager import ensure_instance
        inst = {"hwnd": 777, "port": 53333, "profile": r"C:\tmp\p",
                "launched_at": 1.0, "binary": "edge"}
        launches: list = []
        out = ensure_instance(
            registry={"managed": inst},
            launch=lambda: launches.append(1) or {"hwnd": 888},
            alive=lambda i: True)
        assert launches == [], \
            f"存活实例不得重复拉起(调用记录直出): {launches}"
        assert out is inst, f"须复用既有实例标识(直出): {out}"

    def test_br19_reclaim_deregisters_and_kills_by_profile(self):
        """TC-BR-19:reclaim → 注册表注销+按 profile 清理补刀。
        红态:空壳。"""
        from deskpilot.browser.manager import reclaim
        registry = {"managed": {"hwnd": 777, "profile": r"C:\tmp\p"}}
        kills: list[str] = []
        cleaned = reclaim(registry=registry,
                          kill_by_profile=lambda p: kills.append(p))
        assert registry == {}, \
            f"注册表须注销(状态直出): {registry}"
        assert kills == [r"C:\tmp\p"], \
            f"按 profile 补刀(调用记录直出): {kills}"
        assert cleaned, f"清理清单直出: {cleaned}"

    def test_br20_probe_dual_check(self):
        """TC-BR-20:端口死/进程活、端口活/进程死两格 → 有一失败即判死;
        双活判活(同规正向格)。红态:空壳。"""
        from deskpilot.browser.manager import probe
        inst = {"port": 53333, "pid": 4321}
        assert probe(inst, port_alive=lambda p: False,
                     process_alive=lambda pid: True) is False, \
            "端口死即判死(直出)"
        assert probe(inst, port_alive=lambda p: True,
                     process_alive=lambda pid: False) is False, \
            "进程死即判死(直出)"
        assert probe(inst, port_alive=lambda p: True,
                     process_alive=lambda pid: True) is True, \
            "双活判活(直出)"


# ---------- TC-BR-21 单元:CDP 连接参数 ----------

class TestCdpConnect:
    """TC-BR-21(单元):握手参数含 suppress_origin=True(T5-01)。"""

    def test_br21_connect_suppresses_origin(self):
        """TC-BR-21:connect() 经 ws 工厂接缝建连,握手参数
        suppress_origin=True(替身参数记录直出)。红态:connect 空壳。"""
        from deskpilot.browser.cdp import connect
        seen: list[dict] = []

        def _factory(url, **kw):
            seen.append(kw)
            return object()

        connect("ws://127.0.0.1:53333/devtools/browser/abc",
                ws_factory=_factory)
        assert seen and seen[0].get("suppress_origin") is True, \
            f"握手必须 suppress_origin=True(替身参数直出): {seen}"
