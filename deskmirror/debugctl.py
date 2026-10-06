"""调试控制通道（只在设置了环境变量 DESKMIRROR_DEBUG_PORT 时启用，只监听 127.0.0.1）。

供自动化测试驱动正在运行的魔镜：读状态、移动魔镜、按住看原文、刷新、退出，以及生成
“用户实际看到的画面”合成图——覆盖层对截屏隐身，所以合成图 = 截屏 + 用同一套绘制代码
把覆盖层和边框画上去。正常使用时不开启。
"""
from __future__ import annotations

import json
import logging
import socket
import threading

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


class _Bridge(QObject):
    call = Signal(object)


class DebugServer:
    def __init__(self, port: int, handler) -> None:
        self._handler = handler
        self._bridge = _Bridge()
        self._bridge.call.connect(self._run_in_gui)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", port))
        self._sock.listen(4)
        self._thread = threading.Thread(target=self._serve, name="debugctl", daemon=True)
        self._thread.start()
        log.info("调试控制通道已开启：127.0.0.1:%d", port)

    def _run_in_gui(self, job) -> None:
        req, done, box = job
        try:
            box["result"] = self._handler(req)
        except Exception as e:  # noqa: BLE001
            log.exception("调试命令失败")
            box["result"] = {"error": f"{type(e).__name__}: {e}"}
        done.set()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        with conn:
            f = conn.makefile("rwb")
            for line in f:
                try:
                    req = json.loads(line)
                except ValueError:
                    continue
                done, box = threading.Event(), {}
                self._bridge.call.emit((req, done, box))
                done.wait(30)
                f.write((json.dumps(box.get("result", {"error": "timeout"}), ensure_ascii=False) + "\n").encode())
                f.flush()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def client_call(port: int, req: dict, timeout: float = 30.0) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        f = s.makefile("rwb")
        f.write((json.dumps(req) + "\n").encode())
        f.flush()
        return json.loads(f.readline())
