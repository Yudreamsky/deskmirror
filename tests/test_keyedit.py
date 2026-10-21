"""快捷键录入（ui/keyedit.py）和新设置窗口：按键序列 → 组合键、写法来回转换、重复和被占用的提示、截图设置存得上。"""
from __future__ import annotations

import unittest
from unittest import mock

from deskmirror.config import AppConfig
from deskmirror.keys import combo_text, key_name, normalize_hotkey, parse_hotkey


class KeyTextTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        for text in ("Ctrl+1", "Ctrl+Alt+O", "Ctrl+Shift+Num+3", "Alt+F4", "F9", "Shift+Win+S", "Ctrl+PrtSc",
                     "PrtSc", "Ctrl+Alt+Space", "Ctrl+`", "Ctrl+\\", "Ctrl+PgDown"):
            self.assertEqual(combo_text(*parse_hotkey(text)), text)

    def test_normalize(self) -> None:
        self.assertEqual(normalize_hotkey(" ctrl + alt + o "), "Ctrl+Alt+O")
        self.assertEqual(normalize_hotkey("alt+ctrl+O"), "Ctrl+Alt+O", "修饰键顺序固定")
        self.assertEqual(normalize_hotkey(""), "")
        with self.assertRaises(ValueError):
            normalize_hotkey("A")                   # 单个字母会吞掉打字
        self.assertEqual(key_name(0xAD), "", "媒体键不能当快捷键")


class RecorderTest(unittest.TestCase):
    def feed(self, rec, keys):
        out = []
        for vk, down in keys:
            out.append(rec.feed(vk, down))
        return out

    def test_combo(self) -> None:
        from deskmirror.ui.keyedit import Recorder
        rec = Recorder()
        res = self.feed(rec, [(0xA2, True), (0x31, True)])          # 左 Ctrl 按下，再按 1
        self.assertEqual(res[0], (False, None), "修饰键放过")
        self.assertEqual(res[1], (True, ("set", "Ctrl+1")), "主键吞掉，不触发别的程序的热键")
        rec = Recorder()
        res = self.feed(rec, [(0xA4, True), (0xA0, True), (0x70, True)])
        self.assertEqual(res[-1][1], ("set", "Alt+Shift+F1"))
        rec = Recorder()
        self.assertEqual(rec.feed(0x1B, True), (True, ("cancel", "")))
        self.assertEqual(rec.feed(0x08, True), (True, ("clear", "")))
        kind, msg = rec.feed(0x41, True)[1]
        self.assertEqual(kind, "hint", "单个字母不行：提示，接着录")
        self.assertTrue(msg)
        self.assertEqual(rec.feed(0x41, False), (False, None), "松开不吞（吞掉松开会让键卡住）")

    def test_modifier_up_never_swallowed(self) -> None:
        from deskmirror.ui.keyedit import Recorder
        rec = Recorder()
        for vk in (0xA2, 0xA3, 0xA4, 0xA5, 0xA0, 0x5B):
            self.assertFalse(rec.feed(vk, True)[0])
            self.assertFalse(rec.feed(vk, False)[0])

    def test_mods_only(self) -> None:
        from deskmirror.ui.keyedit import Recorder
        rec = Recorder(mods_only=True)
        res = self.feed(rec, [(0xA2, True), (0xA4, True), (0xA4, False), (0xA2, False)])
        self.assertEqual(res[-1], (False, ("set", "Ctrl+Alt")), "全部松开时定下按过的那组")
        rec = Recorder(mods_only=True)
        self.assertEqual(rec.feed(0x08, True)[1][0], "hint", "拖动键不能清空")
        self.assertEqual(rec.feed(0x41, True)[1][0], "hint")


class SettingsHotkeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make(self, cfg=None):
        from deskmirror.ui import settings
        with mock.patch.object(settings, "probe", side_effect=lambda text: text != "Ctrl+Alt+Q"):
            d = settings.SettingsDialog(cfg or AppConfig())
        return d, settings

    def test_conflicts(self) -> None:
        d, settings = self.make()
        with mock.patch.object(settings, "probe", side_effect=lambda text: text != "Ctrl+Alt+Q"):
            self.assertEqual(d.key_problem("capture"), "")
            d._key_changed("pin", "Ctrl+1")
            self.assertIn("“", d.key_problem("pin"), "和截图重复")
            self.assertEqual(d.key_problem("capture"), d.key_problem("capture"))
            d._key_changed("pin", "Ctrl+Alt+Q")
            self.assertTrue(d.key_problem("pin"), "被别的程序占着")
            d._key_changed("pin", "")
            self.assertEqual(d.key_problem("pin"), "", "清空 = 不用这个快捷键")
            d._key_changed("drag_modifiers", "Ctrl+X")
            self.assertTrue(d.key_problem("drag_modifiers"), "拖动键只能是修饰键")
        d.close()

    def test_two_editors_stay_in_sync(self) -> None:
        d, settings = self.make()
        with mock.patch.object(settings, "probe", return_value=True):
            first, second = d._keys["capture"]                 # 截图页一个，快捷键页一个
            first.set_value("Ctrl+Shift+A")
            self.assertEqual(second.value(), "Ctrl+Shift+A")
            self.assertEqual(d.collect().hotkeys.capture, "Ctrl+Shift+A")
            d._reset_keys()
            self.assertEqual(d.collect().hotkeys.capture, "Ctrl+1")
        d.close()

    def test_capture_settings_saved(self) -> None:
        cfg = AppConfig()
        cfg.capture.after = "pin"
        cfg.capture.format = "jpg"
        d, _settings = self.make(cfg)
        self.assertEqual(d.cap_after.currentData(), "pin")
        d.cap_snap.setChecked(False)
        d.cap_dir.setText(r"D:\shots")
        c = d.collect()
        self.assertEqual((c.capture.after, c.capture.format, c.capture.snap, c.capture.save_dir),
                         ("pin", "jpg", False, r"D:\shots"))
        d.show_page("capture")
        self.assertEqual(d.pages.currentIndex(), 3)
        d.close()

    def test_window_fits_small_screens(self) -> None:
        d, _settings = self.make()
        self.assertLess(d.minimumSizeHint().height(), 600, "每页自己滚动：窗口不会被最长的一页撑高")
        d.close()


if __name__ == "__main__":
    unittest.main()
