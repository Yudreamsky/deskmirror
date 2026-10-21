"""截图（ui/snip.py）、标注（ui/marks.py）、贴图（ui/pin.py）、自动框选（snap.py）、原位翻译（ui/intrans.py）
和引擎里截图用的识别、翻译入口。界面在离屏平台上跑，识别、翻译用假的服务。"""
from __future__ import annotations

import ctypes
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np  # noqa: E402

import deskmirror  # noqa: E402,F401
from deskmirror import snap, textutil, winapi  # noqa: E402
from deskmirror import engine as E  # noqa: E402
from deskmirror.config import AppConfig  # noqa: E402

from tests.test_engine import make_engine  # noqa: E402
from tests.test_pixels import text_page  # noqa: E402


def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class ChainTest(unittest.TestCase):
    def test_smallest_first_and_dedupe(self) -> None:
        screen = (0, 0, 1000, 800)
        window = (100, 100, 900, 700)
        chain = snap.build_chain(300, 300, screen, window, [
            ("element", [(250, 280, 400, 320), (200, 200, 600, 500), (101, 101, 899, 699)]),
            ("text", [(240, 270, 410, 330), (700, 600, 800, 650)]),
            ("child", [(150, 150, 850, 650)])])
        rects = [c.rect for c in chain]
        self.assertEqual(rects[0], (250, 280, 400, 320), "最小的在最前")
        self.assertNotIn((700, 600, 800, 650), rects, "不包住鼠标的不要")
        self.assertEqual([(c.kind, c.rect) for c in chain][-2:], [("window", window), ("screen", screen)],
                         "和窗口几乎一样大的元素就是这个窗口（滚轮那一层叫“窗口”）")
        self.assertEqual(rects, sorted(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])))

    def test_tiny_and_clipped(self) -> None:
        chain = snap.build_chain(50, 50, (0, 0, 100, 100), (-50, -50, 300, 300),
                                 [("element", [(45, 45, 52, 52), (40, 40, 500, 60)])])
        self.assertNotIn((45, 45, 52, 52), [c.rect for c in chain], "太小的不要")
        self.assertIn((40, 40, 100, 60), [c.rect for c in chain], "裁到屏幕里")
        self.assertEqual(chain[-1].rect, (0, 0, 100, 100))

    def test_same_size_kinds(self) -> None:
        screen = (0, 0, 1000, 800)
        chain = snap.build_chain(50, 50, screen, (0, 0, 1000, 800), [("element", [(0, 0, 1000, 800)]),
                                                                    ("child", [(1, 1, 999, 799)])])
        self.assertEqual([c.kind for c in chain], ["screen"], "全屏的窗口、元素都算整个屏幕")
        chain = snap.build_chain(50, 50, screen, None, [("element", [(10, 10, 300, 300)]), ("text", [(10, 10, 300, 300)])])
        self.assertEqual([c.kind for c in chain], ["element", "screen"], "一样大的元素和文字段落：先来的种类留下")
        chain = snap.build_chain(50, 50, screen, None, [("element", [(10, 10, 300, 300)]), ("text", [(11, 11, 299, 299)])])
        self.assertEqual([(c.kind, c.rect) for c in chain][0], ("text", (11, 11, 299, 299)), "差不多大的留小的那个")

    def test_same_level(self) -> None:
        from deskmirror.ui.snip import SnipSession
        C = snap.Candidate
        keep = C((0, 0, 300, 200), "element")
        new = [C((10, 10, 50, 30), "element"), C((0, 0, 300, 200), "element"), C((0, 0, 800, 600), "window")]
        self.assertEqual(SnipSession._same_level(new, keep), 1, "原来那个框还在：停在它上面")
        new = [C((310, 0, 400, 20), "element"), C((300, 0, 600, 210), "element"), C((0, 0, 800, 600), "window")]
        self.assertEqual(SnipSession._same_level(new, keep), 1, "同一种里大小最接近的（列表里的下一项）")
        self.assertEqual(SnipSession._same_level(new, C((0, 0, 790, 600), "window")), 2)
        self.assertEqual(SnipSession._same_level(new, C((0, 0, 50, 50), "text")), 0, "没有同一种的：回到最小的")

    def test_window_at(self) -> None:
        wins = [(1, (0, 0, 100, 100)), (2, (0, 0, 500, 500))]
        self.assertEqual(snap.window_at(50, 50, wins)[0], 1, "Z 序上面的先")
        self.assertEqual(snap.window_at(300, 300, wins)[0], 2)
        self.assertIsNone(snap.window_at(900, 900, wins))


class FakeUia:
    """假的 UI Automation（照 snap.UiaProbe 用到的那几个虚表方法）：元素是名字，tree 是子元素，rects 是矩形；
    refs 记着还有几个 COM 引用没放掉。"""
    P = ctypes.c_void_p

    def __init__(self, tree: dict, rects: dict) -> None:
        self.tree, self.rects, self.refs = tree, rects, 0

    def _out_ptr(self, obj, index, *pre, argtypes=()):
        self.refs += 1
        if index == 6:                       # ElementFromHandle
            return "root"
        if index == 8:                       # FindAllBuildCache(子元素)
            return ("arr", obj)
        if index == 4:                       # 数组的 GetElement
            return self.tree[obj[1]][pre[0]]
        raise AssertionError(index)

    def _int(self, obj, index):              # 数组的 Length
        return len(self.tree[obj[1]])

    def _call(self, obj, index, *args, argtypes=()):
        assert index == 75                   # CachedBoundingRectangle
        rc = args[0]._obj
        rc.left, rc.top, rc.right, rc.bottom = self.rects[obj]
        return 0

    def _release(self, obj) -> None:
        if obj:
            self.refs -= 1


class UiaChainTest(unittest.TestCase):
    def test_tries_every_child_under_the_mouse(self) -> None:
        # Chrome：顶层下面两个和窗口一样大的子元素，前一个是空的，网页在后一个下面
        tree = {"root": ["d3d", "view"], "d3d": [], "view": ["doc"], "doc": ["side", "h1"], "side": [], "h1": []}
        rects = {"d3d": (0, 0, 800, 600), "view": (0, 0, 800, 600), "doc": (0, 30, 800, 600),
                 "side": (600, 30, 800, 600), "h1": (100, 100, 500, 160)}
        u = FakeUia(tree, rects)
        probe = snap.UiaProbe.__new__(snap.UiaProbe)          # 不开后台线程，只用找的那部分
        out = probe._chain(u, "ua", "cond", "cache", 1, 300, 120)
        self.assertEqual(out[:2], [(100, 100, 500, 160), (0, 30, 800, 600)], "找到网页里的标题，从小到大")
        self.assertEqual(u.refs, 0, "COM 引用都放掉了")
        self.assertEqual(probe._chain(u, "ua", "cond", "cache", 1, 700, 590)[0], (600, 30, 800, 600))
        self.assertEqual(u.refs, 0)


class UiaAskTest(unittest.TestCase):
    def test_warm_up_then_once_per_point(self) -> None:
        qapp()
        s = make_session()
        asks = []
        s.probe = SimpleNamespace(ask=lambda tok, hwnd, x, y: asks.append((tok, hwnd, x, y)), close=lambda: None)
        s.mouse = (200, 200)
        s._ask_uia()
        self.assertEqual(len(asks), 1)
        s._on_uia(asks[-1][0], [(100, 130, 500, 400)])           # 头一回的答案偏粗（Chrome 还没建好网页的树）
        s._ask_uia()
        self.assertEqual(len(asks), 2, "刚答上来不久：同一个点再问")
        s._on_uia(asks[-1][0], [(150, 180, 250, 220), (100, 130, 500, 400)])
        self.assertEqual(s.chain[0].rect, (150, 180, 250, 220))
        s._on_uia(asks[0][0], [])
        self.assertEqual(s.chain[0].rect, (150, 180, 250, 220), "过时的答案不要")
        s._uia_first[7] -= 1.0                                    # 过了预热的时候
        s._ask_uia()
        self.assertEqual(len(asks), 2, "问过的点不再问")
        s.mouse = (210, 205)
        s._ask_uia()
        self.assertEqual(len(asks), 3, "换了地方就问")
        s.cancel()


class MaskTest(unittest.TestCase):
    def test_excluded_rects(self) -> None:
        cfg = AppConfig()
        cfg.scope.exclude_apps = ["secret.exe", "WeChat.exe"]
        cfg.scope.exclude_titles = ["网上银行"]
        wins = [SimpleNamespace(hwnd=1, pid=11, rect=(0, 0, 100, 100), title="Notes"),
                SimpleNamespace(hwnd=2, pid=22, rect=(50, 0, 300, 100), title="secret"),
                SimpleNamespace(hwnd=3, pid=33, rect=(0, 200, 100, 300), title="招商 网上银行"),
                SimpleNamespace(hwnd=4, pid=44, rect=(0, 400, 100, 500), title="chat")]
        names = {11: "notes.exe", 22: "secret.exe", 33: "chrome.exe", 44: "wechat.exe"}
        with mock.patch.object(winapi, "process_name", side_effect=lambda pid: names[pid]):
            out = snap.excluded_rects(wins, cfg)
            self.assertIn((100, 0, 300, 100), out, "被上面的窗口挡住的部分不算")
            self.assertIn((0, 200, 100, 300), out, "标题里有名单里的词")
            self.assertIn((0, 400, 100, 500), out, "聊天软件默认也不翻")
            cfg.scope.translate_chat = True
            self.assertNotIn((0, 400, 100, 500), snap.excluded_rects(wins, cfg), "打开“聊天软件也翻译”")

    def test_masked(self) -> None:
        img = np.zeros((10, 20, 3), np.uint8)
        out = snap.masked(img, (100, 50), [(105, 52, 110, 55), (0, 0, 10, 10)])
        self.assertTrue((out[2:5, 5:10] == 128).all())
        self.assertEqual(int(out.sum()), 128 * 3 * 15, "只涂选区里那一块")
        self.assertEqual(int(img.sum()), 0, "原图不动")


class MarksTest(unittest.TestCase):
    def setUp(self) -> None:
        qapp()

    def test_render(self) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QImage
        from deskmirror.ui import marks as mk
        base = QImage(200, 100, QImage.Format.Format_RGB32)
        base.fill(QColor("white"))
        for x in range(0, 200, 2):                         # 有花纹才看得出马赛克
            for y in range(50, 100):
                base.setPixelColor(x, y, QColor("black"))
        st = mk.MarkStack()
        st.add(mk.Mark("rect", QColor("#E5484D"), 4, [QPointF(10, 10), QPointF(60, 40)]))
        st.add(mk.Mark("number", QColor("#3D8BFD"), 4, [QPointF(150, 20)], number=st.next_number()))
        st.add(mk.Mark("mosaic", QColor("red"), 4, [QPointF(100, 50), QPointF(200, 100)]))
        out = st.render(base)
        self.assertEqual(out.pixelColor(10, 25).red(), 0xE5, "矩形的边")
        self.assertEqual(out.pixelColor(35, 25), QColor("white"), "矩形里面不填")
        self.assertEqual(out.pixelColor(150, 20).blue(), 0xFD, "序号是实心圆")
        self.assertEqual(st.next_number(), 2)
        flat = {out.pixelColor(x, 75).rgb() for x in range(110, 116)}
        self.assertEqual(len(flat), 1, "马赛克一格里颜色一样")
        self.assertTrue(st.undo())
        self.assertEqual(len(st.marks), 2)
        self.assertTrue(st.redo())
        st.add(mk.Mark("arrow", QColor("black"), 2, [QPointF(0, 0), QPointF(50, 50)]))
        self.assertFalse(st.redo(), "画了新的就不能重做了")


def make_session(cfg=None, services=None, size=(640, 480)):
    from PySide6.QtGui import QColor, QGuiApplication, QImage
    from deskmirror.ui.snip import Shot, SnipSession
    scr = QGuiApplication.primaryScreen()
    g = scr.geometry()
    w, h = g.width(), g.height()
    mon = winapi.Monitor(scr.name(), (0, 0, w, h), (0, 0, w, h), 96, True)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#F0F0F0"))
    bgr = np.full((h, w, 3), 240, np.uint8)
    cfg = cfg or AppConfig()
    s = SnipSession([Shot(mon, scr, img, bgr)], [(7, (100, 100, 500, 400))], cfg, services or FakeServices())
    if s.probe is not None:
        s.probe.close()
        s.probe = None
    s.prev_focus = 0                     # 测试里关掉截图界面时别去动真窗口的焦点
    return s


class FakeServices:
    def __init__(self, blocks=None, translations=None) -> None:
        self.blocks = blocks or []
        self.translations = translations or {}
        self.ocr_calls = []
        self.tr_calls = []

    def ocr(self, bgr, origin, cb, detect_only=False) -> None:
        self.ocr_calls.append((bgr.shape, origin, detect_only, int((bgr == 128).all(axis=2).sum())))
        if detect_only:
            cb("paras", [(120, 120, 300, 150)])
        else:
            cb("blocks", self.blocks)
        cb("done", {})

    def translate(self, texts, hwnd, cb) -> None:
        self.tr_calls.append((list(texts), hwnd))
        for i, t in enumerate(texts):
            cb("segment", (i, self.translations.get(t, t)))
        cb("done", None)


class SessionTest(unittest.TestCase):
    def setUp(self) -> None:
        qapp()

    def drag(self, s, a, b, mods=None):
        from PySide6.QtCore import QPointF, Qt
        v = s.views[0]
        mods = mods or Qt.KeyboardModifier.NoModifier
        s.press(v, QPointF(*a), Qt.MouseButton.LeftButton, mods)
        s.move(v, QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), mods)
        s.move(v, QPointF(*b), mods)
        s.release(v, QPointF(*b), Qt.MouseButton.LeftButton, mods)

    def test_click_selects_candidate(self) -> None:
        from PySide6.QtCore import QPointF, Qt
        s = make_session()
        s.start()
        self.assertEqual(s.texts, {s.views[0].mon.device: [(120, 120, 300, 150)]}, "开始时先找文字段落")
        s.hover(150, 130)
        self.assertEqual(s.current().rect, (120, 120, 300, 150), "最小的：那段字")
        s.wheel(120)
        self.assertEqual(s.current().rect, (100, 100, 500, 400), "滚轮换大一层：整个窗口")
        v = s.views[0]
        s.press(v, QPointF(150, 130), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        s.release(v, QPointF(150, 130), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.assertEqual((s.state, s.sel), ("selected", (100, 100, 500, 400)))
        self.assertIsNotNone(s.toolbar)
        s.cancel()

    def test_drag_annotate_copy(self) -> None:
        from PySide6.QtCore import Qt
        s = make_session()
        s.start()
        got = []
        done = []
        s.copy_requested.connect(got.append)
        s.finished.connect(lambda: done.append(1))
        self.drag(s, (20, 30), (220, 150))
        self.assertEqual(s.sel, (20, 30, 220, 150))
        s.set_tool("rect")
        self.drag(s, (40, 50), (120, 100))
        self.assertEqual(len(s.marks.marks), 1)
        self.drag(s, (60, 60), (61, 61))
        self.assertEqual(len(s.marks.marks), 1, "几乎没动：不算一个标注")
        s.set_tool("rect")
        self.assertIsNone(s.tool, "再点一次同样的工具：放下工具")
        self.drag(s, (100, 90), (110, 100))               # 没工具时拖里面：整个选区挪动
        self.assertEqual(s.sel, (30, 40, 230, 160))
        s.copy()
        self.assertEqual(len(got), 1)
        img = got[0]
        self.assertEqual((img.width(), img.height()), (200, 120))
        self.assertEqual(img.pixelColor(40 - 30, 75 - 40).red(), 0xE5, "标注留在屏幕上原来的地方")
        self.assertEqual(done, [1])
        self.assertTrue(s.closed)
        self.assertEqual(Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.NoModifier)

    def test_resize_handles_and_keys(self) -> None:
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        s = make_session()
        s.start()
        self.drag(s, (100, 100), (300, 200))
        self.drag(s, (300, 200), (350, 260))           # 右下角的把手
        self.assertEqual(s.sel, (100, 100, 350, 260))
        s.key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier))
        self.assertEqual(s.sel, (110, 100, 360, 260), "Shift+方向键：挪 10 像素")
        s.key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier))
        self.assertEqual(s.sel, (110, 100, 360, 261), "Ctrl+方向键：改大小")
        s.key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertTrue(s.closed)

    def test_right_click_and_mirror(self) -> None:
        from PySide6.QtCore import QPointF, Qt
        s = make_session()
        s.start()
        self.drag(s, (100, 100), (300, 200))
        v = s.views[0]
        s.press(v, QPointF(150, 150), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        self.assertEqual((s.state, s.sel), ("hover", None), "有选区时右键：重选")
        self.drag(s, (100, 100), (300, 200))
        got = []
        s.mirror_requested.connect(lambda r, new: got.append((r, new)))
        s.to_mirror()
        self.assertEqual(got, [((100, 100, 300, 200), False)])

    def test_after_copy_setting(self) -> None:
        cfg = AppConfig()
        cfg.capture.after = "copy"
        s = make_session(cfg)
        s.start()
        got = []
        s.copy_requested.connect(got.append)
        self.drag(s, (10, 10), (110, 60))
        self.assertEqual(len(got), 1, "框选完直接复制")
        self.assertTrue(s.closed)

    def test_translate_in_place(self) -> None:
        from deskmirror.ocr_worker import OcrBlockOut, OcrLineOut
        blocks = [OcrBlockOut((120, 120, 300, 150), [OcrLineOut((120, 120, 300, 150), "Hello world", 0.99)],
                              "Hello world"),
                  OcrBlockOut((120, 200, 200, 220), [OcrLineOut((120, 200, 200, 220), "OK", 0.99)], "OK")]
        svc = FakeServices(blocks, {"Hello world": "你好，世界"})
        s = make_session(services=svc)
        s.masks = [(400, 300, 420, 320)]
        s.start()
        self.drag(s, (100, 100), (450, 350))
        s.toggle_translate()
        self.assertEqual(svc.ocr_calls[-1][1], (100, 100))
        self.assertEqual(svc.ocr_calls[-1][3], 20 * 20, "排除名单里的窗口先涂掉")
        self.assertEqual(svc.tr_calls, [(["Hello world", "OK"], 7)], "窗口标题从选区下面的窗口取")
        self.assertIsNotNone(s.translated)
        self.assertFalse(s.tr_busy)
        orig = s.crop()
        changed = sum(1 for x in range(20, 200, 4) for y in range(20, 50, 2)
                      if s.translated.pixelColor(x, y) != orig.pixelColor(x, y))
        self.assertGreater(changed, 20, "第一段换成了译文")
        same = all(s.translated.pixelColor(x, y) == orig.pixelColor(x, y) for x in range(20, 100, 4)
                   for y in range(100, 120, 2))
        self.assertTrue(same, "译文和原文一样（OK）：原样留着")
        pins = []
        s.pin_requested.connect(pins.append)
        s.toggle_translate()
        self.assertFalse(s.show_tr, "再点：换回原文")
        s.toggle_translate()
        s.pin()
        self.assertEqual(len(pins), 1)
        self.assertTrue(pins[0].showing_translation)
        self.assertIsNotNone(pins[0].alt, "贴图带上原文的样子，能来回换")
        self.assertEqual(pins[0].hwnd, 7)


class PinTest(unittest.TestCase):
    def setUp(self) -> None:
        qapp()

    def test_pin_zoom_swap(self) -> None:
        from PySide6.QtGui import QColor, QImage
        from deskmirror.ui.pin import Pins, text_card
        from deskmirror.ui.snip import PinData
        a = QImage(100, 50, QImage.Format.Format_RGB32)
        a.fill(QColor("red"))
        b = QImage(100, 50, QImage.Format.Format_RGB32)
        b.fill(QColor("blue"))
        pins = Pins(None)
        w = pins.pin(PinData(a, (0, 0, 100, 50), b, False))
        self.assertEqual(len(pins.items), 1)
        size = w.size()
        w.zoom = 2.0
        w._fit()
        self.assertGreater(w.width(), size.width() * 1.8)
        w.swap()
        self.assertEqual(w.image.pixelColor(5, 5), QColor("blue"))
        self.assertTrue(w.showing_tr)
        pins.pin(PinData(a, (0, 0, 100, 50)))
        pins.close_all()
        self.assertEqual(pins.items, [])
        card = text_card("一行字\nsecond line")
        self.assertGreater(card.width(), 40)
        self.assertGreater(card.height(), 30)

    def test_pin_clipboard_falls_back_to_history(self) -> None:
        from PySide6.QtGui import QColor, QGuiApplication, QImage
        from deskmirror.ui.pin import Pins
        from deskmirror.ui.snip import PinData
        QGuiApplication.clipboard().clear()
        pins = Pins(None)
        self.assertIsNone(pins.pin_clipboard((10, 10)), "剪贴板和历史都空")
        img = QImage(30, 20, QImage.Format.Format_RGB32)
        img.fill(QColor("green"))
        pins.remember(PinData(img, (5, 5, 35, 25)))
        w = pins.pin_clipboard((10, 10))
        self.assertIsNotNone(w)
        QGuiApplication.clipboard().setText("剪贴板里的字")
        w2 = pins.pin_clipboard((10, 10))
        self.assertNotEqual(w2.image.pixelColor(2, 2), QColor("green"), "剪贴板里的字画成卡片")
        pins.close_all()


class EngineSnipTest(unittest.TestCase):
    def test_translate_batches_cache_usage(self) -> None:
        page = text_page(800, 600, 13)
        eng, m, win, sc = make_engine(page)
        sent = []

        class Pool:
            def submit(self, batch) -> None:
                sent.append(batch)

        eng.pool = Pool()
        eng.cfg.llm.max_batch_items = 2
        eng.cache[textutil.cache_key("Hello")] = "你好"
        got = []
        eng._snip_translate(["Hello", "Bye", "Moon", "Sun"], 0, lambda k, d: got.append((k, d)))
        self.assertEqual(got, [("segment", (0, "你好"))], "缓存里有的马上给")
        self.assertEqual([b.texts for b in sent], [["Bye", "Moon"], ["Sun"]], "按批大小分批")
        self.assertEqual(len(eng.inflight), 2)
        b1, b2 = sent
        eng._on_translation(("segment", b1.batch_id, 1, "月亮"))
        self.assertEqual(got[-1], ("segment", (2, "月亮")), "回到原来的序号")
        self.assertEqual(eng.cache.get(textutil.cache_key("Moon")), "月亮", "进缓存：以后同样的字不再请求")
        usage = SimpleNamespace(tokens_in=500, tokens_out=20, cached=0, exact=True)
        with mock.patch.object(E.usagelog, "write"):
            eng._on_translation(("batch_done", b1.batch_id, None, 0.5, usage))
            self.assertNotIn(("done", None), got, "还有一批没回来")
            eng._on_translation(("batch_done", b2.batch_id, None, 0.4, usage))
        self.assertEqual(got[-1], ("done", None))
        self.assertEqual(eng.service["tok_in"], 1000, "用量照记")
        eng.service["budget"] = True
        got.clear()
        eng._snip_translate(["Mars"], 0, lambda k, d: got.append((k, d)))
        self.assertEqual(got[0][0], "error", "每天的上限照管")

    def test_snip_ocr_routing(self) -> None:
        page = text_page(800, 600, 13)
        eng, m, win, sc = make_engine(page)
        jobs = []
        eng.ocr = SimpleNamespace(submit=jobs.append)
        eng.ocr_state = "ready"
        got = []
        eng._snip_ocr(np.zeros((20, 30, 4), np.uint8), (5, 6), lambda k, d: got.append((k, d)), True)
        job = jobs[0]
        self.assertEqual(job.origin, (5, 6))
        self.assertEqual(job.image.shape, (20, 30, 3))
        self.assertTrue(job.meta["detect_only"])
        eng._on_ocr(("paras", job.job_id, [(1, 2, 3, 4)]))
        eng._on_ocr(("done", job.job_id, {}))
        self.assertEqual(got, [("paras", [(1, 2, 3, 4)]), ("done", {})])
        self.assertNotIn(job.job_id, eng.snip_jobs)
        self.assertEqual(eng.jobs, {}, "不进引擎自己的识别任务")


if __name__ == "__main__":
    unittest.main()
