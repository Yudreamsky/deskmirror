[简体中文](QUICKSTART.md) · **English**

# Quick start

Using DeskMirror for the first time? Just follow these 6 steps. The same guide opens the first time the program
starts; to see it again later, right-click the tray icon (the blue 镜 icon at the bottom right of the taskbar) →
**Getting started…**.

## 1. Choose your native language

A row of big buttons, each language written in its own script: 简体中文, 繁體中文, English, 日本語, 한국어,
Bahasa Indonesia. The one matching your Windows language is already selected, so most people just click "Next".

- Translations are shown in the language you choose.
- With Chinese (Simplified or Traditional) the interface is in Chinese; with any other language it's in English.
- Later you can change "Translate into" and "Interface language" separately in Settings → Recognition and display.

## 2. What the mirror is

The blue frame on your desktop is the mirror: outside it is your desktop as usual; inside it, the same spot appears
translated.

- Just drag the mirror to what you want to read: web pages, PDFs, apps, games and video subtitles all work.
- The whole screen is translated ahead of time in the background, so wherever you drag, the translation is already
  there.
- Moving or resizing the mirror doesn't translate anything again or cost anything extra.

![The mirror slides onto a game's dialogue box and the Japanese turns into English](images/hero-en.gif)

## 3. Pick a translation service

The mirror hands the text on screen to a translation service. Choose one:

**Ollama on this PC** (free, text stays on your PC; needs a graphics card with plenty of video memory)

1. Download and install Ollama from [ollama.com](https://ollama.com), then open it.
2. In a command prompt, run `ollama pull gemma4:12b` (about 7.6 GB).
3. Step 3 of the guide checks automatically; once it says Ollama and the model are ready, you're set.

**Cloud service** (DeepSeek, Qwen, etc.; pay per use, works on any PC)

1. Get an API key on the provider's website.
2. In step 3 of the guide, choose "Cloud service", pick the service, enter the API key and click "Test connection".
3. The key is stored only on this PC, encrypted with your Windows account.

You can change this any time in Settings → Translation service.

## 4. Using the mirror

- **Move and resize**: drag the dark tab above the mirror to move it, and the blue border to resize it. You can also
  hold Ctrl+Alt and drag anywhere inside the frame.
- Inside the frame you can still click, select text and scroll as usual; it all goes to the program underneath.

Buttons on the tab:

| Button | What it does |
|---|---|
| Pause | Keeps the frame but stops recognizing and translating (costs nothing); click again to resume |
| Auto→EN | Sets the source and target languages, e.g. ZH→EN, ID→EN, KO→EN |
| Orig. shot / Shot | Takes a screenshot of the frame (as is / with translations) and copies it to the clipboard |
| Image | Sends the frame to a vision model: comics, stylized lettering, text in pictures |
| ⟳ | Recognizes and translates the frame again |
| ⚙ / — | Settings / hide the mirror |

Hotkeys: hold **Ctrl+Alt+O** to see the original; **Ctrl+Alt+H** hides and shows the mirror; **Ctrl+Alt+Y** opens
the history (recent subtitles and dialogue); **Ctrl+Alt+V** starts image translation.

Right-click the mirror's tab to open another mirror, or to make the mirror follow the window underneath.

## 5. Privacy and cost

- With a cloud service, the recognized text is sent to it (billed by the amount of text); with Ollama on this PC,
  nothing leaves your computer.
- Chat apps, password managers and online banking windows are not recognized or translated by default; you can change
  the list in Settings. When chatting with colleagues or friends abroad, right-click the mirror's tab (or the tray
  icon) and check "Translate chat apps"; turn it off again when you're done.
- Logs don't record screen text, and "Remember translations" is off by default. Hover over the tray icon to see how
  much text was sent today.
- **How much to translate ahead**: "Whole screen" has translations ready wherever you drag, but text in other windows
  is sent too. If you use a cloud service and care about privacy or cost, choose "Only the window under the mirror"
  (tray menu → Pre-translation scope).

## 6. Start

Drag the mirror over what you want to translate, wait a second or two, and the translation appears where the original
was.

More in the [user guide](GUIDE.en.md). Questions or problems: a885187@gmail.com.
