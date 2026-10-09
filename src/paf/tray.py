"""An icon in the Windows notification area while the app works on its own (paf.raidqueue), with its notifications:
"Nek'zali is ready". Plain Win32 through ctypes (Shell_NotifyIcon on a hidden window), no library. A click on the
icon or on a notification opens the app; its menu also stops the work. Does nothing outside Windows.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable

WM_USER = 0x0400
CALLBACK = WM_USER + 20
NIN_BALLOONUSERCLICK = WM_USER + 5
WM_DESTROY, WM_CLOSE, WM_COMMAND = 0x0002, 0x0010, 0x0111
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_USER, NIIF_LARGE_ICON = 0x04, 0x20


class Tray:
    """The icon, its tooltip and its menu [(label, callback)]; `on_open` runs on a click. Every call is safe from
    any thread; on a system without a notification area, nothing shows and nothing fails."""

    def __init__(self, tip: str, icon: str, menu: list[tuple[str, Callable[[], None]]],
                 on_open: Callable[[], None]) -> None:
        self.tip, self.icon, self.menu, self.on_open = tip, icon, menu, on_open
        self.hwnd = None
        self._ready = threading.Event()
        self._data = None
        if sys.platform == "win32":
            threading.Thread(target=self._loop, daemon=True).start()
            self._ready.wait(5)

    # --- Win32 ---------------------------------------------------------------------------------------------------
    def _loop(self) -> None:
        try:
            self._create()
        except Exception as ex:  # noqa: BLE001 - no icon is better than a crash of the work it shows
            print(f"no notification icon: {ex}", flush=True)
            self.hwnd = None
            self._ready.set()
            return
        self._ready.set()
        import ctypes
        import ctypes.wintypes as w

        msg = w.MSG()
        user32 = ctypes.windll.user32
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _create(self) -> None:
        import ctypes
        import ctypes.wintypes as w

        user32, shell32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
        lresult = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(lresult, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user32.DefWindowProcW.restype = lresult
        user32.CreateWindowExW.restype = w.HWND
        user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        user32.LoadImageW.restype = w.HANDLE
        user32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
        user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPVOID]
        user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
        user32.CreatePopupMenu.restype = w.HMENU
        user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", proc_type), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                        ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                        ("lpszClassName", w.LPCWSTR)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                        ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                        ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                        ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON)]

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == CALLBACK:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, NIN_BALLOONUSERCLICK):
                    self._safe(self.on_open)
                elif event == WM_RBUTTONUP:
                    self._popup(hwnd)
                return 0
            if msg == WM_DESTROY:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data))
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = proc_type(wndproc)  # kept: the window calls it for as long as it lives
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="prep-a-fight-tray")
        user32.RegisterClassW(ctypes.byref(cls))
        self.hwnd = user32.CreateWindowExW(0, "prep-a-fight-tray", "prep-a-fight (tray)", 0, 0, 0, 0, 0, None, None,
                                           hinst, None)
        icon = user32.LoadImageW(None, self.icon, 1, 0, 0, 0x10 | 0x40) if self.icon else None  # file, default size
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd, data.uID, data.uCallbackMessage = self.hwnd, 1, CALLBACK
        data.uFlags = NIF_MESSAGE | NIF_TIP | (NIF_ICON if icon else 0)
        data.hIcon = icon
        data.szTip = self.tip[:127]
        self._data, self._shell, self._user32 = data, shell32, user32
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))

    def _popup(self, hwnd) -> None:
        import ctypes
        import ctypes.wintypes as w

        user32 = self._user32
        menu = user32.CreatePopupMenu()
        for i, (label, _fn) in enumerate(self.menu, 1):
            user32.AppendMenuW(menu, 0, i, label)
        pt = w.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)  # else the menu does not close on a click elsewhere
        chosen = user32.TrackPopupMenu(menu, 0x0100 | 0x0080, pt.x, pt.y, 0, hwnd, None)  # RETURNCMD, NONOTIFY
        user32.DestroyMenu(menu)
        if 0 < chosen <= len(self.menu):
            self._safe(self.menu[chosen - 1][1])

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            print(f"tray action failed: {ex}", flush=True)

    # --- what the work calls -------------------------------------------------------------------------------------
    def set_tip(self, tip: str) -> None:
        if self.hwnd and self._data is not None:
            import ctypes

            self._data.uFlags = NIF_TIP
            self._data.szTip = tip[:127]
            self._shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._data))

    def notify(self, title: str, text: str) -> None:
        """A Windows notification from the icon (a click on it opens the app)."""
        if self.hwnd and self._data is not None:
            import ctypes

            self._data.uFlags = NIF_INFO
            self._data.szInfoTitle = title[:63]
            self._data.szInfo = text[:255]
            self._data.dwInfoFlags = NIIF_USER | NIIF_LARGE_ICON
            self._shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._data))

    def close(self) -> None:
        if self.hwnd:
            self._user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.hwnd = None


def bring_to_front(title: str) -> bool:
    """Show the app's window if it is open (restored and in front). False when it is not."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    return True
