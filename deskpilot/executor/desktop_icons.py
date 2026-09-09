"""桌面图标感知(REQ-002,详设)。

三路数据(侦察选型 D-10):
- UIA 枚举:display + cell_rect(复用既有元素通道);
- ListView LVIR_ICON:graphic_rect(跨进程内存,单块复用,获取-释放配对);
- ShellView IFolderView/IEnumIDList:source 路径(虚拟项如实 null)。
按索引合并(序对齐校验);region 相交过滤;fail-closed——任一路失败即
显式报错(含路标),禁止空列表假装成功。hwnd 易变:每次调用动态定位
容器,禁止缓存(Progman hwnd 实证可变)。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..errors import INTERNAL_ERROR, ExecutorError

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_shell32 = ctypes.windll.shell32
_ole32 = ctypes.windll.ole32

LVM_GETITEMCOUNT = 0x1004
LVM_GETITEMRECT = 0x100E
LVIR_ICON = 1


def rects_intersect(a, b) -> bool:
    """矩形相交判定:正面积重叠;边界相触不算(纯函数)。"""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


# ---------- 容器定位 ----------

class ContainerLocator:
    """每次调用动态定位桌面图标容器(SysListView32)。

    Progman→SHELLDLL_DefView→SysListView32 主链;壁纸类应用托管场景走
    WorkerW 兜底枚举;均不可达 → 「容器不可达(locate)」(fail-closed)。
    """

    def __init__(self, u32_seam=None):
        self._u = u32_seam or _u32

    def locate(self) -> int:
        u = self._u
        hwnd = self._find_listview(u.FindWindowW("Progman", None))
        if hwnd:
            return hwnd
        found: list[int] = []
        wndproc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)

        def cb(h, lp):
            lv = self._find_listview(h)
            if lv:
                found.append(lv)
                return False
            return True

        u.EnumWindows(wndproc(cb), 0)
        if found:
            return found[0]
        raise ExecutorError(
            INTERNAL_ERROR,
            "桌面图标容器不可达(locate): Progman 与 WorkerW 均无 SysListView32")

    def _find_listview(self, parent: int) -> int:
        if not parent:
            return 0
        dv = self._u.FindWindowExW(parent, None, "SHELLDLL_DefView", None)
        if not dv:
            return 0
        return self._u.FindWindowExW(dv, None, "SysListView32", None)


# ---------- UIA 路:display + cell_rect ----------

class UiaIconProvider:
    """经既有 UIA 元素通道收集桌面 ListItemControl(可注入 walker 接缝)。"""

    def __init__(self, walker):
        self._walk = walker     # callable(hwnd) -> [element dict]

    def list(self, hwnd) -> list[tuple[str, list[int]]]:
        out = []
        for e in self._walk(hwnd):
            if e.get("control_type") == "ListItemControl":
                out.append((e["name"], list(e["rect"])))
        return out


# ---------- ListView 路:graphic_rect(跨进程) ----------

class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _Win32Seam:
    """真实 OS 接缝(ctypes);测试以同形态替身注入。"""

    def open_process(self, pid):
        return _k32.OpenProcess(0x0438, False, pid)   # VM操作+读写+查询

    def virtual_alloc(self, hproc, size):
        return _k32.VirtualAllocEx(hproc, None, size, 0x1000, 0x04)

    def write_mem(self, hproc, addr, buf, size):
        n = ctypes.c_size_t(0)
        return _k32.WriteProcessMemory(hproc, addr, buf, size, ctypes.byref(n))

    def send_itemrect(self, hwnd, index, addr):
        return _u32.SendMessageW(hwnd, LVM_GETITEMRECT, index, addr)

    def read_mem(self, hproc, addr, buf, size):
        n = ctypes.c_size_t(0)
        return _k32.ReadProcessMemory(hproc, addr, buf, size, ctypes.byref(n))

    def virtual_free(self, hproc, addr):
        _k32.VirtualFreeEx(hproc, addr, 0, 0x8000)

    def close_handle(self, h):
        _k32.CloseHandle(h)


class ListViewIconProvider:
    """跨进程读图形矩形(LVIR_ICON);远程内存单块复用;获取-释放配对。"""

    def __init__(self, os_seam=None, u32_seam=None):
        self._os = os_seam or _Win32Seam()
        self._u = u32_seam or _u32

    def count(self, hwnd) -> int:
        return self._u.SendMessageW(hwnd, LVM_GETITEMCOUNT, 0, 0)

    def graphic_rect(self, hwnd, index) -> list[int]:
        return self.graphic_rects(hwnd, [index])[0]

    def graphic_rects(self, hwnd, indices) -> list[list[int]]:
        pid = wintypes.DWORD()
        self._u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        hproc = self._os.open_process(pid.value)
        if not hproc:
            raise ExecutorError(
                INTERNAL_ERROR, "桌面图形矩形读取失败(listview): 打开进程失败")
        remote = None
        try:
            remote = self._os.virtual_alloc(hproc, ctypes.sizeof(_RECT) + 16)
            if not remote:
                raise ExecutorError(
                    INTERNAL_ERROR,
                    "桌面图形矩形读取失败(listview): 远程内存分配失败")
            rects = []
            for i in indices:
                rc = _RECT(); rc.left = LVIR_ICON
                self._os.write_mem(hproc, remote, ctypes.byref(rc),
                                   ctypes.sizeof(rc))
                self._os.send_itemrect(hwnd, i, remote)
                back = _RECT()
                self._os.read_mem(hproc, remote, ctypes.byref(back),
                                  ctypes.sizeof(back))
                rects.append([back.left, back.top, back.right, back.bottom])
            return rects
        finally:
            if remote:
                self._os.virtual_free(hproc, remote)
            self._os.close_handle(hproc)


# ---------- ShellView 路:source(虚拟项 null) ----------

def _shell_sources() -> list[str | None]:
    """COM 链取桌面视图项路径(侦察实证通道;虚拟项如实 null)。"""
    import comtypes
    import comtypes.client
    from comtypes import GUID, HRESULT, IUnknown
    from comtypes.automation import VARIANT, IDispatch

    class IShellWindows(IDispatch):
        _iid_ = GUID("{85CB6900-4D95-11CF-960C-0080C7F4EE85}")
        _methods_ = [
            comtypes.STDMETHOD(HRESULT, "get_Count",
                               [ctypes.POINTER(ctypes.c_long)]),
            comtypes.STDMETHOD(HRESULT, "Item",
                               [VARIANT, ctypes.POINTER(ctypes.POINTER(IDispatch))]),
            comtypes.STDMETHOD(HRESULT, "_NewEnum",
                               [ctypes.POINTER(ctypes.POINTER(IUnknown))]),
            comtypes.STDMETHOD(HRESULT, "Register",
                               [ctypes.POINTER(IDispatch), ctypes.c_long,
                                ctypes.c_int, ctypes.POINTER(ctypes.c_long)]),
            comtypes.STDMETHOD(HRESULT, "RegisterPending",
                               [ctypes.c_long, VARIANT, VARIANT, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_long)]),
            comtypes.STDMETHOD(HRESULT, "Revoke", [ctypes.c_long]),
            comtypes.STDMETHOD(HRESULT, "OnNavigate", [ctypes.c_long, VARIANT]),
            comtypes.STDMETHOD(HRESULT, "OnActivated", [ctypes.c_long, VARIANT]),
            comtypes.STDMETHOD(HRESULT, "FindWindowSW",
                               [VARIANT, VARIANT, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_long), ctypes.c_int,
                                ctypes.POINTER(ctypes.POINTER(IDispatch))]),
            comtypes.STDMETHOD(HRESULT, "OnCreated", [ctypes.c_long, VARIANT]),
            comtypes.STDMETHOD(HRESULT, "ProcessAttachDetach", [VARIANT]),
        ]

    class IServiceProvider(IUnknown):
        _iid_ = GUID("{6d5140c1-7436-11ce-8034-00aa006009fa}")
        _methods_ = [comtypes.STDMETHOD(HRESULT, "QueryService",
                     [comtypes.GUID, comtypes.GUID,
                      ctypes.POINTER(ctypes.c_void_p)])]

    class IShellView(IUnknown):
        _iid_ = GUID("{000214E3-0000-0000-C000-000000000046}")
        _methods_ = []

    class IShellBrowser(IUnknown):
        _iid_ = GUID("{000214E2-0000-0000-C000-000000000046}")
        _methods_ = [
            comtypes.STDMETHOD(HRESULT, "GetWindow",
                               [ctypes.POINTER(ctypes.c_void_p)]),
            comtypes.STDMETHOD(HRESULT, "ContextSensitiveHelp", [ctypes.c_int]),
            comtypes.STDMETHOD(HRESULT, "InsertMenusSB",
                               [ctypes.c_void_p, ctypes.c_void_p]),
            comtypes.STDMETHOD(HRESULT, "SetMenuSB",
                               [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]),
            comtypes.STDMETHOD(HRESULT, "RemoveMenusSB", [ctypes.c_void_p]),
            comtypes.STDMETHOD(HRESULT, "SetStatusTextSB", [ctypes.c_wchar_p]),
            comtypes.STDMETHOD(HRESULT, "EnableModelessSB", [ctypes.c_int]),
            comtypes.STDMETHOD(HRESULT, "TranslateAcceleratorSB",
                               [ctypes.c_void_p, ctypes.c_ushort]),
            comtypes.STDMETHOD(HRESULT, "BrowseObject",
                               [ctypes.c_void_p, ctypes.c_uint]),
            comtypes.STDMETHOD(HRESULT, "GetViewStateStream",
                               [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]),
            comtypes.STDMETHOD(HRESULT, "GetControlWindow",
                               [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]),
            comtypes.STDMETHOD(HRESULT, "SendControlMsg",
                               [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.POINTER(ctypes.c_long)]),
            comtypes.STDMETHOD(HRESULT, "QueryActiveShellView",
                               [ctypes.POINTER(ctypes.POINTER(IShellView))]),
            comtypes.STDMETHOD(HRESULT, "OnViewWindowActive",
                               [ctypes.POINTER(IShellView)]),
            comtypes.STDMETHOD(HRESULT, "SetToolbarItems",
                               [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]),
        ]

    class IEnumIDList(IUnknown):
        _iid_ = GUID("{000214F2-0000-0000-C000-000000000046}")
        _methods_ = [
            comtypes.STDMETHOD(HRESULT, "Next",
                               [ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p),
                                ctypes.POINTER(ctypes.c_ulong)]),
            comtypes.STDMETHOD(HRESULT, "Skip", [ctypes.c_ulong]),
            comtypes.STDMETHOD(HRESULT, "Reset", []),
            comtypes.STDMETHOD(HRESULT, "Clone",
                               [ctypes.POINTER(ctypes.c_void_p)]),
        ]

    class IFolderView(IUnknown):
        _iid_ = GUID("{cde725b0-ccc9-4519-917e-325d72fab4ce}")
        _methods_ = [
            comtypes.STDMETHOD(HRESULT, "GetCurrentViewMode",
                               [ctypes.POINTER(ctypes.c_uint)]),
            comtypes.STDMETHOD(HRESULT, "SetCurrentViewMode", [ctypes.c_uint]),
            comtypes.STDMETHOD(HRESULT, "GetFolder",
                               [comtypes.GUID, ctypes.POINTER(ctypes.c_void_p)]),
            comtypes.STDMETHOD(HRESULT, "Item",
                               [ctypes.c_int, comtypes.GUID,
                                ctypes.POINTER(ctypes.c_void_p)]),
            comtypes.STDMETHOD(HRESULT, "ItemCount",
                               [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]),
            comtypes.STDMETHOD(HRESULT, "Items",
                               [ctypes.c_uint, comtypes.GUID,
                                ctypes.POINTER(ctypes.c_void_p)]),
            comtypes.STDMETHOD(HRESULT, "GetSelectionMarkedItem",
                               [ctypes.POINTER(ctypes.c_int)]),
            comtypes.STDMETHOD(HRESULT, "GetFocusedItem",
                               [ctypes.POINTER(ctypes.c_int)]),
            comtypes.STDMETHOD(HRESULT, "GetItemPosition",
                               [ctypes.c_void_p, ctypes.c_void_p]),
            comtypes.STDMETHOD(HRESULT, "GetSpacing", [ctypes.c_void_p]),
            comtypes.STDMETHOD(HRESULT, "GetDefaultSpacing", [ctypes.c_void_p]),
            comtypes.STDMETHOD(HRESULT, "GetAutoArrange", []),
            comtypes.STDMETHOD(HRESULT, "SelectItem",
                               [ctypes.c_int, ctypes.c_uint]),
            comtypes.STDMETHOD(HRESULT, "SelectAndPositionItems",
                               [ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint]),
        ]

    comtypes.CoInitialize()
    try:
        sw = comtypes.client.CreateObject(
            GUID("{9BA05972-F6A8-11CF-A442-00A0C90A8F39}"),
            interface=IShellWindows)
        hwnd = ctypes.c_long(0)
        disp = ctypes.POINTER(IDispatch)()
        hr = sw.FindWindowSW(VARIANT(), VARIANT(), 0x8, ctypes.byref(hwnd),
                             0x1, ctypes.byref(disp))   # DESKTOP|INCLUDEPENDING
        if hr != 0 or not disp:
            raise ExecutorError(
                INTERNAL_ERROR,
                f"桌面图标来源获取失败(shellview): FindWindowSW hr={hr:#010x}")
        sp = disp.QueryInterface(IServiceProvider)
        sb = ctypes.c_void_p()
        hr = sp.QueryService(GUID("{4C96BE40-915C-11CF-99D3-00AA004AE837}"),
                             IShellBrowser._iid_, ctypes.byref(sb))
        if hr != 0 or not sb:
            raise ExecutorError(
                INTERNAL_ERROR,
                f"桌面图标来源获取失败(shellview): QueryService hr={hr:#010x}")
        sbp = ctypes.cast(sb, ctypes.POINTER(IShellBrowser))
        sv = ctypes.POINTER(IShellView)()
        hr = sbp.QueryActiveShellView(ctypes.byref(sv))
        if hr != 0:
            raise ExecutorError(
                INTERNAL_ERROR,
                f"桌面图标来源获取失败(shellview): QueryActiveShellView hr={hr:#010x}")
        fv = sv.QueryInterface(IFolderView)
        en = ctypes.c_void_p()
        hr = fv.Items(0, IEnumIDList._iid_, ctypes.byref(en))
        if hr != 0 or not en:
            raise ExecutorError(
                INTERNAL_ERROR,
                f"桌面图标来源获取失败(shellview): Items hr={hr:#010x}")
        enp = ctypes.cast(en, ctypes.POINTER(IEnumIDList))
        out: list[str | None] = []
        while True:
            pidl = ctypes.c_void_p()
            got = ctypes.c_ulong(0)
            hr = enp.Next(1, ctypes.byref(pidl), ctypes.byref(got))
            if hr != 0 or got.value == 0:
                break
            pb = ctypes.create_unicode_buffer(260)
            ok = _shell32.SHGetPathFromIDListW(pidl, pb)
            out.append(pb.value if ok else None)     # 虚拟项如实 null
            _ole32.CoTaskMemFree(pidl)
        return out
    except ExecutorError:
        raise
    except Exception as e:
        raise ExecutorError(
            INTERNAL_ERROR, f"桌面图标来源获取失败(shellview): {e}") from e
    finally:
        comtypes.CoUninitialize()


class ShellViewIconProvider:
    """桌面图标来源路径 provider(链可注入;测试替身直接给清单)。"""

    def __init__(self, chain=None):
        self._chain = chain

    def sources(self) -> list[str | None]:
        if self._chain is not None:
            return self._chain()
        return _shell_sources()


# ---------- 装配 ----------

_VIRTUAL_FIRST_NAMES = {"回收站", "recycle bin"}


class DesktopIconAssembler:
    """三路装配:序对齐校验→按索引合并→region 过滤(fail-closed)。"""

    def __init__(self, locator, uia, listview, shellview):
        self._locator = locator
        self._uia = uia
        self._lv = listview
        self._sv = shellview

    def assemble(self, region=None) -> list[dict]:
        hwnd = self._locate()
        uia_items = self._uia_list(hwnd)
        n_lv = self._lv_count(hwnd)
        sources = self._sources()
        counts = (len(uia_items), n_lv, len(sources))
        if len(set(counts)) != 1:
            raise ExecutorError(
                INTERNAL_ERROR,
                f"序对齐失败:三路计数不一致 uia/listview/shellview={counts}")
        graphics = self._graphics(hwnd, len(uia_items))
        if uia_items:
            first_name = (uia_items[0][0] or "").strip().lower()
            if first_name in _VIRTUAL_FIRST_NAMES and sources[0] is not None:
                raise ExecutorError(
                    INTERNAL_ERROR,
                    f"序对齐失败:首项虚拟一致性——uia={uia_items[0][0]!r} 而 "
                    f"shellview 有路径 {sources[0]!r}")
        items = [{"display": display, "source": src,
                  "graphic_rect": g, "cell_rect": cell}
                 for (display, cell), g, src
                 in zip(uia_items, graphics, sources)]
        if region is not None:
            items = [i for i in items
                     if rects_intersect(i["cell_rect"], region)]
        return items

    def _locate(self):
        try:
            return self._locator.locate()
        except ExecutorError:
            raise
        except Exception as e:
            raise ExecutorError(
                INTERNAL_ERROR, f"桌面图标容器不可达(locate): {e}") from e

    def _uia_list(self, hwnd):
        try:
            return self._uia.list(hwnd)
        except Exception as e:
            raise ExecutorError(
                INTERNAL_ERROR, f"桌面图标枚举失败(uia): {e}") from e

    def _lv_count(self, hwnd):
        try:
            return self._lv.count(hwnd)
        except Exception as e:
            raise ExecutorError(
                INTERNAL_ERROR, f"桌面图形矩形读取失败(listview): {e}") from e

    def _graphics(self, hwnd, n):
        try:
            return self._lv.graphic_rects(hwnd, list(range(n)))
        except ExecutorError:
            raise
        except Exception as e:
            raise ExecutorError(
                INTERNAL_ERROR, f"桌面图形矩形读取失败(listview): {e}") from e

    def _sources(self):
        try:
            return self._sv.sources()
        except ExecutorError:
            raise
        except Exception as e:
            raise ExecutorError(
                INTERNAL_ERROR, f"桌面图标来源获取失败(shellview): {e}") from e
