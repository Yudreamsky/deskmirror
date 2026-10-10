import sys

if __name__ == "__main__":
    if [a for a in sys.argv[1:] if a != "--autostart"]:     # 带参数：命令行（看、改设置等），不打开界面
        from deskmirror.cli import main as cli_main
        raise SystemExit(cli_main(sys.argv[1:]))
    from deskmirror.app import main                          # --autostart：开机自启，魔镜收成球待命
    raise SystemExit(main())
