"""开机自动启动（源码版）的入口：设置里打开“开机时自动启动”时，启动项指向它（用 .venv 里的 pythonw，不弹黑框）。

从哪个目录启动都找得到程序；参数原样交给程序（--autostart：魔镜收成球待命，点开才开始识别）。
"""
import os
import runpy

os.chdir(os.path.dirname(os.path.abspath(__file__)))
runpy.run_module("deskmirror", run_name="__main__", alter_sys=True)
