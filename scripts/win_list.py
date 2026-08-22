"""Enumerate visible top-level windows with title, hwnd, rect, minimized state."""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

EnumWindows = user32.EnumWindows
GetWindowTextW = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
IsIconic = user32.IsIconic
GetWindowRect = user32.GetWindowRect

results = []


def callback(hwnd, _):
    if not IsWindowVisible(hwnd):
        return True
    buf = ctypes.create_unicode_buffer(256)
    GetWindowTextW(hwnd, buf, 256)
    title = buf.value.strip()
    if not title:
        return True
    rect = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    results.append(
        f"hwnd={hwnd:>8} min={bool(IsIconic(hwnd))!s:<5} "
        f"rect=({rect.left},{rect.top},{rect.right},{rect.bottom})  {title}"
    )
    return True


EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(callback), 0)
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("\n".join(results))
