"""ISS-0062 步骤 A:集成测试环境守卫统一 helper(散落写法收敛,纯重构)。

口径(单据 §方向):守卫 skip 必须写明缺什么环境,禁止静默 skip;
消息统一「环境守卫:<原因>」前缀(经 env_skip 产出,调用方传裸原因)。

helper 清单与出处:
- env_skip:统一 skip 口径;
- notepad_mains:记事本主窗口清单(自 test_clicktext_iss21._spawn_notepad
  内联逻辑抽出);
- real_daemon_online:真 daemon 在线判定(test_typeguard_iss100:339/
  test_estopreset_iss93:494 先例收敛);
- is_unoccluded_point / pick_unoccluded_desktop_icon:桌面图标未遮挡
  判定与首个可用图标选取(ct12 test_clicktarget_iss44:316-331 与
  test_desktop_icons_req02:341-357 同构逻辑抽出)。
"""

from __future__ import annotations

import pytest

DEFAULT_DAEMON_PORT = 9420


def env_skip(reason: str) -> None:
    """显式环境守卫:写明缺什么环境/什么冲突(禁止静默 skip)。"""
    pytest.skip(f"环境守卫:{reason}")


def notepad_mains(probe=None) -> list[dict]:
    """记事本主窗口清单(有标题且尺寸 >100px)。"""
    if probe is None:
        from deskpilot.executor import DesktopProbe
        probe = DesktopProbe()
    return [w for w in probe.find_windows(process="notepad.exe",
                                          include_hidden=True)
            if w.get("title")
            and (w["rect"][2] - w["rect"][0]) > 100
            and (w["rect"][3] - w["rect"][1]) > 100]


def real_daemon_online(port: int = DEFAULT_DAEMON_PORT) -> bool:
    """真 daemon(127.0.0.1:port)是否在线。"""
    from deskpilot.httpd import probe_daemon
    return probe_daemon("127.0.0.1", port)


def is_unoccluded_point(cx: int, cy: int) -> bool:
    """点位于桌面(Progman 链)可见=未被外来窗口遮挡(ct12 同源判定)。"""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    pm = u32.FindWindowW("Progman", None)
    h = u32.WindowFromPoint(wintypes.POINT(cx, cy))
    return h == pm or u32.IsChild(pm, h)


def pick_unoccluded_desktop_icon(items) -> dict | None:
    """首个图形中心未被遮挡的桌面图标;无 → None(调用方 env_skip)。"""
    for it in items:
        g = it.get("graphic_rect")
        if not g:
            continue
        cx, cy = (g[0] + g[2]) // 2, (g[1] + g[3]) // 2
        if is_unoccluded_point(cx, cy):
            return it
    return None


def dismiss_xaml_save_prompt(hwnds, timeout: float = 6.0) -> None:
    """Store 记事本未保存关窗的 XAML 内嵌保存提示消除(ISS-0104 二次裁决
    形态,自 test_typefocus_iss104 收敛共享,ISS-0062 步骤 C)。

    本机实证 '*' 永不消退(30s 观察),WM_CLOSE 必弹 XAML 提示(非经典
    #32770);UIA 找提示三键(保存/不保存/取消,序位实证)并 Invoke 序位
    第二「不保存」。找不到提示即静默跳过(无提示=无阻塞)。"""
    import ctypes
    import ctypes.wintypes  # noqa: F401
    import time

    import uiautomation as uia

    u32 = ctypes.windll.user32
    for h in hwnds:
        u32.PostMessageW(h, 0x0010, 0, 0)              # WM_CLOSE
    deadline = time.monotonic() + timeout
    pending = set(hwnds)
    while pending and time.monotonic() < deadline:
        for h in list(pending):
            if not u32.IsWindow(h):
                pending.discard(h)
                continue
            try:
                btns = []

                def walk(c, d=0):
                    if c is None or d > 14:
                        return
                    try:
                        if c.ControlTypeName == "ButtonControl" and c.Name:
                            btns.append(c)
                    except Exception:
                        pass
                    try:
                        ch = c.GetChildren()
                    except Exception:
                        return
                    for x in ch:
                        walk(x, d + 1)

                walk(uia.ControlFromHandle(h))
                if (len(btns) >= 3
                        and btns[0].Name in ("保存", "Save")
                        and btns[1].Name in ("不保存", "Don't save")):
                    btns[1].GetInvokePattern().Invoke()   # 不保存
            except Exception:
                pass
        time.sleep(0.6)
