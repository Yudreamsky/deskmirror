import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:                       # 带参数：命令行（看、改设置等），不打开界面
        from deskmirror.cli import main as cli_main
        raise SystemExit(cli_main(sys.argv[1:]))
    from deskmirror.app import main
    raise SystemExit(main())
