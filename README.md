**English** · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Bahasa Indonesia](README.id.md)

# DeskMirror

A screen translator for Windows. Put a draggable "mirror" anywhere on your desktop: inside the frame, the same spot
of the screen shows up with its text translated in place; outside the frame, your desktop stays as it is.
Web pages, PDFs, apps, games and video subtitles all work the same way, with no browser extension.

![The mirror slides onto a game's dialogue box and the Japanese turns into English](docs/images/hero-en.gif)

New here? Start with the [quick start](docs/QUICKSTART.en.md) (the same guide opens on first launch), then the
[user guide](docs/GUIDE.en.md).

## What it looks like

A 2½-minute tour:

https://github.com/user-attachments/assets/949fc01b-9277-44ab-8253-7a7a5162d22c

Screenshots of DeskMirror running on the project's test pages (translation service: DeepSeek):

| Web pages | Video subtitles |
|---|---|
| ![A Chinese web page; inside the mirror the text is in English](docs/images/web-en.jpg) | ![A video with Chinese subtitles; inside the mirror the subtitle is in English](docs/images/video-en.jpg) |
| **Windowed games** | **PDFs** |
| ![A Japanese game: quest, menu, timer, name tag and dialogue all in English](docs/images/game-en.jpg) | ![A Chinese PDF; inside the mirror the abstract is in English](docs/images/pdf-en.jpg) |

**Comics**: vertical text in speech bubbles is read directly and replaced in place; the bubble outlines stay intact.

<img src="docs/images/manga-en.jpg" width="560" alt="A Japanese comic page: the speech bubbles and the caption are in English">

## Features

- **In place**: the translation sits where the original was, matching its size and color as closely as possible;
  hold Ctrl+Alt+O to peek at the original.
- **Keeps up with the screen**: scrolling, moving and overlapping windows, video subtitles. It watches what changes on
  screen, so it doesn't depend on any particular program.
- **Pre-translates in the background**: text on the mirror's screen is translated ahead of time, so wherever you drag
  the mirror the translation is already there; nothing is translated twice.
- **Your choice of translation service**: a local [Ollama](https://ollama.com) model (free, text never leaves your
  PC), or any OpenAI-compatible API such as DeepSeek, Qwen or OpenAI.
- **Privacy under your control**: a do-not-translate list (chat apps, password managers and online banking are
  skipped by default; when chatting with colleagues or friends abroad, turn on "Translate chat apps" with one click),
  three pre-translation scopes, and today's usage at a glance. Screen text is not saved to disk by default.
- **Switch languages any time**: the language button on the mirror's tab (e.g. "Auto→EN") sets the source and target
  languages. Chinese, English, Japanese, Korean and Indonesian are supported.
- **English or Chinese interface**: on first launch you pick your native language; translations come out in it and
  the interface follows (Chinese for Chinese, English for everything else). Both can be changed later in Settings.
- **Glossary**: glossary terms are always used, and other terms stay consistent too. Subtitles and game dialogue are
  translated with the previous few lines as context, so names and tone stay coherent.
- **Fits the space**: a translation longer than the original is first narrowed slightly, then borrows plain space
  nearby, and only then shrinks. It doesn't spill over panel borders, pictures or video.
- **Comics**: vertical text in speech bubbles is recognized directly. Chinese and Japanese translations are set
  vertically in place, and English is centered in the bubble.
- **Image translation**: press Ctrl+Alt+V or click "Image" on the tab to send the frame to a vision model (gemma4:12b
  on Ollama by default). Good for stylized lettering, sound effects and text in pictures.
- **Tuck it away**: drag the mirror to the edge of the screen and it shrinks into a ball that stops translating; drag
  it out and it carries on wherever you drop it.
- **Translate what you type**: in another program's text box, press Space three times (or Ctrl+Alt+J) to turn what you
  typed in your own language into another one; press again to switch back. Off by default.
- **Liquid glass skin** (optional): the border becomes a ring of curved glass that refracts what's behind it, and the
  tab and the ball turn into glass too.
- Also: a history panel, editing translations, several mirrors, mirrors that follow a window, pause, screenshots,
  starting with Windows, updating from inside the app.

## Installation

You need:

- Windows 11 (Windows 10 should work but hasn't been tested)
- A translation service, either:
  - Local: install [Ollama](https://ollama.com), then run `ollama pull gemma4:12b` (about 7.6 GB; needs a graphics
    card with plenty of video memory)
  - Cloud: an API key for DeepSeek or a similar service (pay per use)

### Download (recommended)

1. Download `DeskMirror-<version>-win64.zip` (about 140 MB) from
   [Releases](https://github.com/Yudreamsky/deskmirror/releases/latest).
2. Unzip it to any folder you can write to (for example Documents or drive D:) and double-click `DeskMirror.exe`.
   The getting-started guide takes it from there.
   - If Windows says "Windows protected your PC" (the program isn't code-signed), click "More info" → "Run anyway".
   - Settings and logs are kept in that folder. To upgrade, unzip the new version over it; your settings are kept.
   - Don't unzip into C:\Program Files (settings can't be written there and go to `%LOCALAPPDATA%\DeskMirror`
     instead).
3. No Python needed; the text recognition models (Korean included) are in the package.

### Run from source

1. Install [Python 3.12](https://www.python.org/downloads/) (check "Add python.exe to PATH" during setup).
2. Get the code: `git clone https://github.com/Yudreamsky/deskmirror.git`, or download the ZIP from GitHub.
3. Double-click `setup.bat`. It creates `.venv` and installs the dependencies (PySide6, RapidOCR, ONNX Runtime and
   others; needs an internet connection).
4. Double-click `start.bat`. The recognition models come with the packages; the Korean model (about 14 MB) is
   downloaded the first time you choose "Original: Korean".
5. To build the exe yourself: `.venv\Scripts\python -m pip install -r requirements-build.txt`, then
   `.venv\Scripts\python packaging\build.py`.

To use a cloud service: choose "Cloud service" in step 3 of the getting-started guide, or click ⚙ on the mirror's
tab → Translation service, choose "OpenAI-compatible API", fill in the address, the model and the API key, and click
"Test connection".

Text recognition runs on the graphics card by default (DirectML, any DirectX 12 card) and falls back to the CPU
automatically.

## Usage

The getting-started guide opens on first launch (step 1 asks for your native language; you can reopen it from the
tray menu any time). See the [quick start](docs/QUICKSTART.en.md) and the [user guide](docs/GUIDE.en.md).
Common actions:

| To do this | Do this |
|---|---|
| Move or resize the mirror | Drag the tab above the mirror; drag the blue border |
| Peek at the original | Hold Ctrl+Alt+O |
| Hide / show the mirror | Ctrl+Alt+H |
| Tuck the mirror away as a ball | Drag the tab to the edge of the screen; click the ball to bring it back |
| Turn what you type into another language | Press Space three times in a text box, or Ctrl+Alt+J (turn it on in Settings → Text boxes) |
| Liquid glass look | Settings → Recognition and display → Skin |
| Look back at recent subtitles and dialogue | Ctrl+Alt+Y opens the history panel |
| Pause (the frame stays; no recognition, no translation) | Click "Pause" on the tab |
| Choose languages (e.g. ZH→EN, ID→EN, JA→EN) | Click the language button on the tab |
| Translate chat apps (when chatting with friends abroad) | Right-click the tab or the tray icon → "Translate chat apps" |
| Image translation (comics, stylized text, text in pictures) | Ctrl+Alt+V, or click "Image" on the tab |
| Settings | Click ⚙ on the tab, or right-click the tray icon |
| Update to a new version | Right-click the tray icon → "Check for updates…" |

### Usage and cost

- `↑12.3k ↓4.1k` on the mirror tab is today's tokens sent to the translation service (↑ input, ↓ output); hover
  over it for details, including how much hit the provider's cache.
- Every request carries about 430 tokens of fixed instructions, so the cheapest thing is fewer tiny requests: while a
  request is in flight, stray new lines wait a moment and go out together. The "Only the window under the mirror" and
  "Only near the frame" pre-translation scopes cost much less than "Whole screen".
- After a while without keyboard or mouse input only the text inside the mirror is translated, and everything stops
  while the screen is locked; cloud services stop at 1,000,000 tokens a day by default. All of this is in
  Settings → Scope and privacy.
- Every request is logged to `logs/usage-YYYY-MM.jsonl` (counts and program names only, no screen text);
  `usage --log` on the command line (see the next section) sums it up by program, batch size and hour.

## Let an AI assistant set it up

Every setting can also be changed from the command line, so an AI assistant such as Claude Code or Codex can do the
whole setup for you. A running DeskMirror picks up the changes within a second.

- Download version: `DeskMirrorCLI.exe` in the DeskMirror folder. From source: `.venv\Scripts\python -m deskmirror`.
- `config keys` lists every setting with what it means and which values it takes; `config list`, `config get`,
  `config set` and `config reset` read and change them; `service`, `models` and `test` switch the translation
  service, list its models and check that it works; `usage` shows today's tokens and `status` whether DeskMirror is
  running. Add `--json` for JSON output.
- API keys are read from standard input (`config set llm.api_key -`) or from an environment variable
  (`config set llm.api_key --env DEEPSEEK_API_KEY`), so they stay off the command line. They are stored encrypted with
  your Windows account and only ever shown as `sk-…1234`.

For example, to switch to DeepSeek with English translations:

```bat
DeskMirrorCLI.exe service deepseek
DeskMirrorCLI.exe config set llm.api_key -
DeskMirrorCLI.exe config set target_lang en first_run_tip false
DeskMirrorCLI.exe test
```

(The second line asks for the key and doesn't show it as you type.) Or just tell your assistant something like:

> Set up DeskMirror for me. It's in D:\DeskMirror: run `DeskMirrorCLI.exe --help` and
> `DeskMirrorCLI.exe config keys --json` to see what can be set. Use DeepSeek (I'll give you the API key; pass it
> with `config set llm.api_key -`), translate into English, and check it with `DeskMirrorCLI.exe test`.

## Privacy

- With a cloud translation service, the text recognized on screen and the window titles are sent to that service.
  If that matters to you, use Ollama on your PC, or narrow the pre-translation scope and add programs to the
  do-not-translate list in Settings.
- The API key is encrypted with your Windows account (DPAPI) and stored on this PC in `deskmirror.json`.
- Logs record only timings and counts, never screen text; the per-request usage log also notes which program the
  text was in. "Remember translations" is off by default; when it's on, translations are stored encrypted on this PC.
- Image translation sends a screenshot of the frame to the vision model set in Settings. By default that's Ollama on
  your PC, so the picture stays local; with a cloud service you are asked each time before a picture is sent.
- Checking for updates asks GitHub for the latest version number and release notes, at most once a day after
  starting; no screen content is sent, and nothing is downloaded until you click. Turn it off in Settings → Scope and
  privacy.

## Known limitations

- Tested on one PC so far (Windows 11, 3840×2160 at 100% scaling, RTX 4090).
- Exclusive-fullscreen games and protected video can't be overlaid or captured; play games in borderless or windowed
  mode.
- Stylized lettering, pixel fonts and very small text may be misread. Vertical text works when it is set in neat
  columns, as in comic speech bubbles; slanted sound effects need image translation. For Korean, choose
  "Original: Korean" with the language button (it switches to the Korean recognition model).
- More in the [user guide](docs/GUIDE.en.md#known-limitations).

## Development

```bat
:: Unit tests (no screen or models needed)
.venv\Scripts\python.exe -m unittest discover -s tests -t .

:: Run with a console window to see the log
start.bat debug
```

## License

[GPL-3.0](LICENSE). Copyright © 2026 Yudreamsky.

Third-party components and their licenses: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Contact

a885187@gmail.com

DeskMirror is free and open source, and every feature is available. If it helps you, you can
[buy me a coffee on Ko-fi](https://ko-fi.com/dreamskyu) (also under About → Support the author in the app).
