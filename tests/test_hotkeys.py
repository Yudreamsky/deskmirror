"""快捷键被别的程序占着：记下来；那个程序放开以后 retry() 接回来，按下去能到魔镜这里。"""
import ctypes
import os
import unittest
from ctypes import wintypes as wt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from deskmirror.hotkeys import WM_HOTKEY, HotkeyManager  # noqa: E402  先导入魔镜（它会先加载系统运行库），再导入 Qt
from deskmirror.keys import MOD_NOREPEAT, parse_hotkey  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

COMBO = "Ctrl+Alt+Shift+F24"        # 没人用的组合键：测试里先自己占住，当作“别的程序占着”
OTHER = "Ctrl+Alt+Shift+F23"
BLOCKER_ID = 0x7ABC


class TakenKeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.hk = HotkeyManager(self.app)
        mods, vk = parse_hotkey(COMBO)
        self.assertTrue(user32.RegisterHotKey(None, BLOCKER_ID, mods | MOD_NOREPEAT, vk), "测试用的组合键被别的程序占着")
        self.blocked = True

    def tearDown(self) -> None:
        self.hk.unregister_all()
        self.release()

    def release(self) -> None:
        if self.blocked:
            user32.UnregisterHotKey(None, BLOCKER_ID)
            self.blocked = False

    def register(self, bindings: dict[str, str]) -> list[str]:
        with self.assertLogs("deskmirror.hotkeys", "WARNING"):
            return self.hk.register(bindings)

    def test_taken_key_is_taken_back_once_released(self) -> None:
        errors = self.register({"capture": COMBO, "pin": OTHER})
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.hk.taken, {"capture": COMBO})
        self.assertEqual(self.hk.registered, ["pin"])
        self.assertEqual(self.hk.retry(), [])           # 还占着
        self.release()
        self.assertEqual(self.hk.retry(), ["capture"])
        self.assertEqual(self.hk.taken, {})
        self.assertEqual(self.hk.registered, ["capture", "pin"])
        self.assertEqual(self.hk.retry(), [])

    def test_key_taken_back_reaches_us(self) -> None:
        self.register({"capture": COMBO})
        self.release()
        self.hk.retry()
        got = []
        self.hk.activated.connect(got.append)
        hid = next(h for h, a in self.hk._actions.items() if a == "capture")
        user32.PostThreadMessageW(kernel32.GetCurrentThreadId(), WM_HOTKEY, hid, 0)   # 和按下组合键时系统发的一样
        for _ in range(20):
            QCoreApplication.processEvents()
            if got:
                break
        self.assertEqual(got, ["capture"])

    def test_registering_again_starts_over(self) -> None:
        self.register({"capture": COMBO})
        self.assertEqual(self.hk.register({"capture": OTHER}), [])     # 在设置里换了个键
        self.assertEqual(self.hk.taken, {})
        self.assertEqual(self.hk.registered, ["capture"])

    def test_unregister_all_forgets_taken(self) -> None:
        self.register({"capture": COMBO})
        self.hk.unregister_all()                        # 设置窗口打开时会先全部放开
        self.release()
        self.assertEqual(self.hk.retry(), [])
        self.assertEqual(self.hk.registered, [])


if __name__ == "__main__":
    unittest.main()
