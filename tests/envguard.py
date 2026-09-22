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
