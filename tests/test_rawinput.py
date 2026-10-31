"""Raw Input 监听（滚轮、输入框翻译听空格）：解析原始输入，起停隐藏窗口。
不模拟真的按键、滚轮（会落到别的程序上）：解析用构造的 RAWINPUT 数据，起停只看登记成没成功、线程停没停。"""
import ctypes
import unittest

from deskmirror import fieldkeys as fk
from deskmirror import wheel as wh
from deskmirror.rawinput import RAWINPUTHEADER


def mouse_input(flags: int, data: int) -> tuple[bytes, int]:
    ri = wh._RAWINPUT_ALIGNED()
    ri.header = RAWINPUTHEADER(wh.RIM_TYPEMOUSE, ctypes.sizeof(ri), None, 0)
    ri.mouse.usButtonFlags = flags
    ri.mouse.usButtonData = data & 0xFFFF
    raw = bytes(ri)
    return raw + bytes(128 - len(raw)), len(raw)


def key_input(vk: int, up: bool) -> tuple[bytes, int]:
    ri = fk.RAWINPUT_KB()
    ri.header = RAWINPUTHEADER(fk.RIM_TYPEKEYBOARD, ctypes.sizeof(ri), None, 0)
    ri.keyboard.VKey = vk
    ri.keyboard.Flags = fk.RI_KEY_BREAK if up else 0
    raw = bytes(ri)
    return raw + bytes(128 - len(raw)), len(raw)


class ParseTest(unittest.TestCase):
    def test_wheel_notches(self) -> None:
        got = []
        w = wh.WheelListener(lambda *a: got.append(a))
        w.on_input(*mouse_input(wh.RI_MOUSE_WHEEL, 120))          # 向上一格
        w.on_input(*mouse_input(wh.RI_MOUSE_WHEEL, -240))         # 向下两格
        w.on_input(*mouse_input(wh.RI_MOUSE_HWHEEL, 120))         # 水平
        w.on_input(*mouse_input(0x0001, 0))                       # 左键按下：不算滚轮
        self.assertEqual([(a[3], a[4]) for a in got], [(1.0, False), (-2.0, False), (1.0, True)])

    def test_space_and_other_keys(self) -> None:
        events = []
        s = fk.SpaceListener(lambda t, hwnd, mods: events.append("space"), lambda: events.append("up"),
                             lambda: events.append("other"))
        for vk, up in ((fk.VK_SPACE, False), (fk.VK_SPACE, True), (fk.VK_A, False), (fk.VK_A, True), (0xFF, False)):
            s.on_input(*key_input(vk, up))
        self.assertEqual(events, ["space", "up", "other"])         # 别的键只算按下；0xFF（假键）不算

    def test_short_input_is_ignored(self) -> None:
        events = []
        s = fk.SpaceListener(lambda *a: events.append("space"), lambda: None, lambda: None)
        data, _n = key_input(fk.VK_SPACE, False)
        s.on_input(data, ctypes.sizeof(RAWINPUTHEADER))
        self.assertEqual(events, [])


class StartStopTest(unittest.TestCase):
    def test_listeners_start_and_stop(self) -> None:
        for make in (lambda: wh.WheelListener(lambda *a: None),
                     lambda: fk.SpaceListener(lambda *a: None, lambda: None, lambda: None)):
            sink = make()
            with self.subTest(sink=sink.name):
                self.assertTrue(sink.start_and_wait(), "Raw Input 登记没成功")
                sink.stop()
                self.assertFalse(sink.is_alive())


if __name__ == "__main__":
    unittest.main()
