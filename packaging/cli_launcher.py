"""打包后的命令行入口 DeskMirrorCLI.exe（带控制台，和 DeskMirror.exe 共用 _internal）：看、改设置等，见 deskmirror/cli.py。"""
import sys

if __name__ == "__main__":
    from deskmirror.cli import main
    sys.exit(main(sys.argv[1:]))
