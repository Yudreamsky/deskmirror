"""打包成 exe 时的入口（PyInstaller 用）。源码运行仍然是 python -m deskmirror。"""
import multiprocessing
import os
import sys

if __name__ == "__main__":
    # 不带控制台的 exe 没有 stdout / stderr：给一个空的，免得第三方库往里写东西时出错（比如下载模型时的进度条）
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if getattr(sys, "frozen", False):           # Qt 插件在 _internal\PySide6\plugins（打包时带上的）
        os.environ.setdefault("QT_PLUGIN_PATH", os.path.join(sys._MEIPASS, "PySide6", "plugins"))
    multiprocessing.freeze_support()       # 文字识别子进程也是从这个 exe 启动的，在这里分流
    from deskmirror.app import main
    sys.exit(main())
