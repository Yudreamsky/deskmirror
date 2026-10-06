# 桌面魔镜 DeskMirror

Windows 上的屏幕翻译工具：在桌面上放一块可以拖动的“镜子”，镜框里同一位置的文字换成译文，镜框外照常是你的桌面。
网页、PDF、软件界面、游戏和视频字幕都用同一种方式工作，不需要浏览器插件。

![桌面魔镜：镜框里的英文换成了中文，镜框外照常](docs/screenshot.jpg)

[English](#english)

## 特点

- **原位显示**：译文贴在原文的位置，字号、颜色尽量和原文一致；按住 Ctrl+Alt+O 随时看原文。
- **跟得住画面**：滚动、窗口移动、遮挡、视频里的字幕都能跟上。按画面变化判断，不依赖具体软件。
- **后台预译**：魔镜所在屏幕上的文字提前翻译，拖到哪里马上显示；看过的内容不重复翻译。
- **翻译服务任选**：本机 [Ollama](https://ollama.com)（免费，文字不出本机），或 DeepSeek、通义千问、OpenAI 等 OpenAI 兼容接口。
- **隐私可控**：不翻译名单（默认排除聊天软件、密码管理器、网银）、三档预译范围、当天用量统计；屏幕上的文字默认不存盘。
- **语言随时切换**：魔镜标签上的语言按钮（如“英→中”）手动指定原文和译成的语言；支持中文、英文、日文、韩文、印尼文。
- **术语**：术语表里的词必须照用；没写进术语表的词也尽量前后一致。字幕和游戏对话带上前几句作上下文，人称、语气更连贯。
- **看图翻译**：按 Ctrl+Alt+V 或点标签上的“看图”，把镜框里的画面交给能看图的模型来读、来翻（默认本机 Ollama 的 gemma4:12b），适合漫画、艺术字、图片里的字。
- 还有：历史面板、改译文、多个魔镜、魔镜跟随窗口、暂停、截图。

## 安装

需要：

- Windows 11（Windows 10 应该也行，但还没测过）
- [Python 3.12](https://www.python.org/downloads/)（安装时勾选 “Add python.exe to PATH”）
- 翻译服务，二选一：
  - 本机：安装 [Ollama](https://ollama.com)，再运行 `ollama pull gemma4:12b`（模型约 7.6 GB，需要显存较大的独立显卡）
  - 云端：DeepSeek 等服务的 API Key（按用量收费）

步骤：

1. 下载本项目：`git clone https://github.com/Yudreamsky/deskmirror.git`，或在 GitHub 页面下载 ZIP 解压。
2. 双击 `setup.bat`：创建 `.venv` 并安装依赖（PySide6、RapidOCR、ONNX Runtime 等，需要联网）。
3. 双击 `start.bat`。文字识别模型随安装包一起装好；第一次选“原文：韩文”时，会自动下载韩文识别模型（约 14 MB）。
4. 用云端服务的话：点魔镜标签上的 ⚙ → 翻译服务，选 “OpenAI 兼容接口”，填地址、模型和 API Key，点 “测试连接”。

文字识别默认用显卡（DirectML，支持 DirectX 12 的显卡都可以），没有合适的显卡时自动改用 CPU。

## 使用

详见[使用说明](docs/GUIDE.md)。常用操作：

| 想做的事 | 怎么做 |
|---|---|
| 移动、调整魔镜 | 拖魔镜上方的标签；拖蓝色边框 |
| 临时看原文 | 按住 Ctrl+Alt+O |
| 隐藏 / 显示魔镜 | Ctrl+Alt+H |
| 回看刚才的字幕、对话 | Ctrl+Alt+Y 打开历史面板 |
| 暂停（框留着，不识别、不翻译） | 点标签上的 “暂停” |
| 指定语言（比如英→中、印尼→中、中→印尼） | 点标签上的语言按钮 |
| 看图翻译（漫画、艺术字、图片里的字） | Ctrl+Alt+V，或点标签上的 “看图” |
| 设置 | 点标签上的 ⚙，或右键托盘图标 |

## 隐私

- 用云端翻译服务时，屏幕上识别出的文字和窗口标题会发给该服务。在意的话用本机 Ollama，或在设置里缩小预译范围、添加不翻译的程序。
- API Key 用当前 Windows 账户加密（DPAPI）保存在本机的 `deskmirror.json`。
- 日志只记录耗时和数量，不记录屏幕上的文字。“记住译文”默认关闭，打开后才会把译文加密存到本机。
- 看图翻译会把镜框里的截图发给设置里的看图模型。默认是本机 Ollama，画面不出本机；改成云端服务时，每次发图前都会先问你。

## 已知限制

- 目前只在一台电脑上测试过（Windows 11、3840×2160 / 100% 缩放、RTX 4090）。
- 独占全屏的游戏、有版权保护的视频画面无法覆盖或截取；游戏请用无边框或窗口模式。
- 竖排文字、艺术字、很小的字可能识别错。韩文要在语言按钮里选“原文：韩文”（换用韩文识别模型）。
- 更多见[使用说明](docs/GUIDE.md#已知限制)。

## 开发

```bat
:: 单元测试（不需要屏幕和模型）
.venv\Scripts\python.exe -m unittest discover -s tests -t .

:: 带控制台窗口运行，看日志
start.bat debug
```

## 许可证

[GPL-3.0](LICENSE)。Copyright © 2026 Yudreamsky。

用到的第三方组件和它们的许可证见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 联系

a885187@gmail.com

---

## English

DeskMirror is a screen translator for Windows. A draggable "mirror" frame shows the same part of your desktop with
the text translated in place — web pages, PDFs, apps, games and video subtitles alike, no browser extension needed.
It follows scrolling, window moves and subtitles, pre-translates the screen in the background, and works with a local
[Ollama](https://ollama.com) model or any OpenAI-compatible API (DeepSeek, OpenAI, …).

The user interface is currently in Chinese. The default target language is Simplified Chinese; the language button on
the mirror switches source and target languages on the fly (Chinese, English, Japanese, Korean, Indonesian).

Requirements: Windows 11, Python 3.12. Run `setup.bat` once, then `start.bat`.

License: GPL-3.0. Contact: a885187@gmail.com
