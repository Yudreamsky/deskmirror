[简体中文](GUIDE.md) · **English**

# DeskMirror user guide

DeskMirror is a rectangular "mirror" that you can drag and resize freely: outside the frame is your normal desktop,
and inside it the same spot of the desktop appears with its text translated (into the language you picked in the
getting-started guide on first launch).
In the background it recognizes and translates all the visible text **on the mirror's screen** (not just inside the
frame), so when you drag the mirror somewhere else, text that has already been translated shows up immediately.
Moving and resizing only change which part you are looking at; nothing is translated again and no translation moves.

Web pages, PDF readers, documents, app interfaces, games and video subtitles all work the same way, with no special
browser or extension.

## Starting and quitting

- **Start**: double-click `DeskMirror.exe` in the folder you unzipped, or `start.bat` in the project folder when
  running from source (run `setup.bat` once first; see the [README](../README.md)). A blue 镜 icon appears in the tray
  at the bottom right, and the mirror (a blue frame) appears in the middle of the screen.
  On first launch, text recognition takes a few seconds to get ready; meanwhile the frame shows the original, and
  translated paragraphs appear one by one.
- **Quit**: right-click the tray icon → Quit. The mirror, the overlays and the background recognition process all
  close together.
- To see the log: `start.bat debug` (runs with a console window). The log file is `logs\deskmirror.log`; it records
  only timings and counts, never screen text.

## Controls

| To do this | Do this |
|---|---|
| Move the mirror | Drag the dark tab above the mirror, or **hold Ctrl+Alt** and drag anywhere inside the frame |
| Resize it | Drag the blue border or one of the four corners |
| Use the program underneath | Just click, select text and scroll inside the frame; it all goes to the program underneath |
| Peek at the original | **Hold Ctrl+Alt+O**; release it to get the translation back |
| Refresh inside the frame | **Ctrl+Alt+T**, or click ⟳ on the tab (checks again, recognizes again and retries failed translations; the cache elsewhere is not affected) |
| Hide / show the mirror | **Ctrl+Alt+H**, click — on the tab, or click the tray icon |
| Choose languages | Click the language button on the tab (it shows the current languages, e.g. "Auto→EN" or "ZH→EN") and pick the source and target languages; the change takes effect at once. When you change the target language, all existing translations are translated again; when you choose Korean as the source, the Korean recognition model is used (about 14 MB, downloaded the first time) and the text on screen is recognized again. You can also change this in Settings → Recognition and display |
| Image translation | **Ctrl+Alt+V**, or click **Image** on the tab (also in the tray menu): sends what is inside the frame (as is, without translations) to a model that can read images. The result appears paragraph by paragraph in a pop-up window, where you can copy it or look at it again. Good for stylized lettering, sound effects, text in pictures and game fonts that normal recognition can't read (vertical text in comic speech bubbles is read by normal recognition too, and Chinese and Japanese translations are set vertically). Slower than live translation (usually a few seconds with a local model). The model is set in Settings → Translation service → Image translation; the default is gemma4:12b on Ollama. With a cloud service you are asked each time before a picture is sent |
| Pause / resume | Click **Pause** on the tab (also in the tray menu): the frame stays, but nothing is captured, recognized or translated (no translation cost), and the mirror shows no translations. The button turns into a yellow **Resume**; click it to continue: the screen is checked again first, and anything already seen comes from the cache without new requests |
| Settings | ⚙ on the tab, or right-click the tray icon → Settings… |
| Getting started, About | Right-click the tray icon → Getting started… / About… (version, author's email, project page); the getting-started guide opens automatically on first launch |
| Interface language | In step 1 of the getting-started guide you pick your native language: translations come out in it, and the interface is in Chinese (if you chose Simplified or Traditional Chinese) or in English (for any other language). Change it later in Settings → Recognition and display → Interface language; it takes effect at once |
| Open another mirror | Right-click the tray icon → New mirror, or right-click the mirror's tab → New mirror (up to 4); right-click an extra mirror's tab to close it |
| Make the mirror follow a window | Right-click the mirror's tab → Follow the window below: when the window moves or resizes, the mirror keeps its relative position; when the window is minimized the mirror hides, and when the window closes, following stops (the tab shows 📌) |
| Look back at recent subtitles and dialogue | **Ctrl+Alt+Y** opens the history panel (also in the tray menu): the originals and translations that recently appeared in the mirror (up to 500), searchable and copyable. Kept in memory only and cleared when you quit |
| Edit a translation | Double-click the entry in the history panel, edit it and save: this text now uses your translation, now and later (after a restart too if translation memory is on; otherwise until you quit) |
| Fix how names and terms are translated | Settings → Glossary: enter a term as it appears in the original and its translation; translations must use it. English and similar languages match whole words (art doesn't match start). "Only for program" takes a program name, with or without .exe. After you change the glossary, existing translations containing those terms are translated again |
| Keep terms consistent | On by default (can be turned off in Settings → Glossary): existing translations in the same window that contain the same words are sent along as reference, so terms that aren't in the glossary keep their earlier translation too (if Employer was translated one way earlier, it won't change later). The first time a term appears there is no reference yet; put terms you want fixed into the glossary |
| Screenshots | Click **Orig. shot** (the frame as is) or **Shot** (the frame with translations, exactly as you see it) on the tab, or use the tray menu. The picture is copied to the clipboard and saved to the "Pictures\DeskMirror" folder ("图片\桌面魔镜" with the Chinese interface); click the notification to open the folder |
| Read a cut-off translation in full | A block with a small triangle at its bottom right didn't fit; hover over it to see the full text |

The default hotkeys may conflict with other programs on your PC: if registering one fails, the tray tells you, and
you can change them in Settings → Hotkeys.
While Ctrl+Alt is held, the mouse inside the frame drags the mirror, so actions like "Ctrl+Alt+click" don't reach the
program underneath while the pointer is inside the frame.

The text on the tab tells you what is going on: "Ready", "Translating: N blocks left in the mirror", "Recognizing
text on the screen…"; when the translation service fails, it says why (for example "Can't reach the translation
service").
Blocks that have been recognized and are waiting for a translation show a blue dashed line inside the mirror; blocks
whose translation failed show a red one.

## How it keeps up with the original

- **Still screens**: the translation stays at the position of the original block and covers it.
- **Scrolling areas**: the program works out from the actual screen changes which area is moving as a whole (it
  doesn't just look at the mouse wheel) and treats it as a separate "scrolling canvas".
  One window can have several (for example the sidebar and the main text of an MDN page); fixed title bars,
  navigation and sidebars don't move along.
  Scrolling is still recognized when the page contains a playing video or animation (the video moves with the page,
  and what plays inside it doesn't confuse the detection); when another window or a pop-up on the page sits on top
  and cuts the changed area into pieces, it's still treated as one scroll, so translations don't move twice.
  Translations that scroll out of view are kept as a cache; when they scroll back and still match, they are reused
  without calling the translation service.
- **Look before giving up**: when a paragraph doesn't match at its predicted position, the program first looks for
  the whole paragraph nearby along the scroll direction; if the pixels match exactly, the translation moves there.
  Only if it isn't found is the translation hidden and the text recognized again. If recognizing again only groups
  existing paragraphs differently (several lines merged into one paragraph, or one paragraph split into lines) and
  the pixels haven't changed, the existing translation is kept and nothing is translated again.
- **Mouse wheel lead**: the program receives wheel events passively (no hooks), learns for each program how many
  pixels one notch scrolls and what its animation curve looks like, and moves translations ahead of time so they
  start moving together with the original. Checking the screen always has the final say; when it doesn't match, the
  prediction is switched off automatically.
  The learned curves are saved next to the settings in `deskmirror_wheel.json` (numbers only) and are used again on
  the next start.
- **Speed-based lead**: for keyboard paging, dragging the scrollbar, touchpads, or a mouse wheel whose curve hasn't
  been learned yet, the program measures the speed and deceleration over the last two frames while scrolling and
  places the translation where the original will be "at the moment it is shown"; while slowing down it goes at most
  to where scrolling is expected to stop, and pulls back the moment scrolling stops.
- **Partly covered paragraphs**: when a pop-up, overlay or tooltip on a web page covers part of a paragraph, only the
  visible part is checked; the paragraph keeps its full translation, cut to the visible area, instead of being
  replaced by a half sentence and translated again.
- **No recognition mid-scroll**: newly revealed content in a scrolling area is recognized only after it has been
  still for 0.15 seconds, so the result isn't out of date the moment it arrives.
- **Moving, covered and resized windows**: translations move with their window; parts covered by other windows aren't
  drawn; when resizing a window rewraps its text, translations that no longer match are hidden first and filled in
  again after the text is recognized again.
- **Text that changes in web pages and documents**: the old translation is removed at once and the text is
  recognized and translated again.
- **Context for subtitles and game dialogue**: a new line is translated together with the previous 3 lines (originals
  and translations) from the same window within the last 30 seconds, so names and tone stay consistent.
- **Areas that keep moving, such as video subtitles and game scenes**: whether the text is still there is judged by
  its strokes; when a subtitle changes, the old translation stays until the new line's translation arrives and
  replaces it (kept for at most 4 seconds; removed when the subtitle disappears). Only when the background behind the
  text really is busy (video, game scenes) does the translation use a dark plate with white text; text on web pages
  and documents always keeps its original background color.

Recognition and translation order: first everything inside the mirror, then a ring just outside the frame, then ring
after ring outwards until the whole screen is covered; content that hasn't changed isn't recognized or translated
again.

## Translation scope and privacy

Settings → "Scope and privacy" (the tray menu also has "Pre-translation scope" and "Don't translate the program
under the mirror"):

- **Pre-translation scope**:
  - **Whole screen** (default): all visible text on the mirror's screen is translated ahead of time in the
    background, so translations appear instantly wherever you drag; but text in other windows is also sent to the
    translation service.
  - **Only the window under the mirror**: only the windows visible inside the mirror are translated; the rest waits
    until the mirror moves there.
  - **Only near the frame**: only paragraphs within a certain distance of the frame (480 pixels by default).
  - If you use a cloud service and care about privacy or cost, the last two are recommended.
- **Programs and window titles not to translate**:
  - Chat apps (WeChat, QQ, WeCom, DingTalk, Feishu, Telegram, WhatsApp, Discord and others) and password managers are
    excluded by default; windows whose titles contain words such as online banking, Alipay or PayPal are excluded too.
  - Windows on the list are blanked out before recognition: they are neither recognized nor translated, and nothing
    from them is sent to any translation service.
  - **Translate chat apps** (off by default): when chatting with colleagues or friends abroad, check it by
    right-clicking the mirror's tab or the tray icon, and the chat apps on the list are translated as usual (chat text
    is sent to the translation service; with Ollama on this PC it stays local); turn it off again when you're done.
    Password managers and banking or payment pages are never translated. The same switch is in Settings → Scope and
    privacy.
  - When such a window is inside the mirror, the tab says so.
- **Usage**: the tray icon's tooltip and the settings page show how many requests and how much text were sent to the
  translation service today (only counts are kept, never the content).
- **Translation memory** (off by default): when on, translations are stored on this PC, encrypted with your Windows
  account, and reused the next time the same text appears, saving time and money. You can clear it any time in
  Settings (clicking Clear while memory is off also deletes files saved earlier). Text that differs only in numbers
  (timers, progress, health, "3 days ago") always reuses the existing translation with the new numbers, whether
  memory is on or not, without asking the translation service.

## Translation service settings

Settings → "Translation service":

- **API type**: `Ollama native API` (default, `http://127.0.0.1:11434` on this PC, model `gemma4:12b`; free, nothing
  leaves your PC), or `OpenAI-compatible API` (DeepSeek, Qwen, SiliconFlow, OpenAI, LM Studio and others; the
  "Common services" drop-down fills in the address with one click).
- **Model**: type it in, or click "Fetch models": when the list arrives, the drop-down opens by itself; when it
  doesn't, the reason is shown (for example a wrong key, or the address has no such endpoint).
- **API key**: only needed for cloud services; stored only on this PC in `deskmirror.json`, encrypted with your
  Windows account (DPAPI), and never written to the source code, the repository or the logs.
- **Test connection**: sends one short sentence and shows whether it worked, how long it took and the translation.
- **Parallel requests / Timeout**: 1 is recommended for a local model; cloud services can go up to 2–3.
- For a local Ollama, use "Ollama native API": through the OpenAI-compatible endpoint (/v1) the model's "thinking"
  can't be turned off, and gemma4 then takes over ten seconds per request.
- With a cloud service, the text recognized on screen, the titles of the windows it comes from, the glossary entries
  used in that text, and already translated text from the same window attached as reference are sent to that
  service.
- Image translation sends a screenshot of the frame (everything visible in it is sent), and only when you press the
  hotkey or click "Image"; before sending to a service outside this PC you are asked every time.

Other settings: the source and target languages (by default auto-detect → Simplified Chinese, or whatever you chose
in the getting-started guide; the language button on the tab changes them too), whether text recognition runs on the
graphics card or the CPU (switch to the CPU while gaming so it doesn't compete with the game for the graphics card),
whether all screens are processed (by default only the mirror's screen), mouse wheel prediction, the minimum font
size, the backing opacity and the hotkeys.
Changes to the recognition device, the screens and wheel prediction take effect the next time DeskMirror starts.

## Default parameters (adjustable in deskmirror.json)

Usually there's no need to change these; quit DeskMirror before editing (it writes its settings back to this file
when it quits).

| Parameter | Default | Meaning |
|---|---|---|
| `track.stable_ms` | 350 | How long an area must be still before new text is recognized (not during fast scrolling) |
| `track.dynamic_ms` | 1000 | How often areas near the mirror that keep moving (subtitles, games) are snapshotted and recognized |
| `track.subtitle_hold_ms` | 4000 | How long the old translation is kept at most when a subtitle changes |
| `track.ring_px` | 240 | Width of each ring in the spiral scheduling |
| `track.max_cache_blocks` / `max_cache_texts` | 6000 / 20000 | Limits of the text block cache and the translation cache (in memory only) |
| `track.display_lead_ms` | 12 | Lead time of the wheel prediction (drawing plus one composited frame) |
| `llm.max_batch_items` / `max_batch_chars` | 10 / 1000 | At most how many text blocks and characters go into one request (throughput tops out at 8–10 blocks) |
| `llm.timeout_s` / `concurrency` | 45 / 1 | Request timeout, parallel requests |
| `style.min_font_px` / `min_scale` | 11 / 0.75 | When a translation doesn't fit, it shrinks to at most 11 pixels or 75% of the original size. If there is plain space to the right it borrows it (often needed when Chinese or Japanese turns into English; never past text on the right or over pictures), then takes plain space below. Above a panel border, a picture or moving video it first shrinks a little more (down to 60% of the original size), and only then covers it; if it still doesn't fit, it is cut off and marked. English words are kept whole where possible |
| `style.min_squash` | 0.6 | When English and similar text doesn't fit, it may be narrowed to 60% of its width: first to 80% (barely visible), then the font shrinks; narrower than that only when the text would otherwise spill out of its panel or shrink further. Chinese, Japanese and Korean text stops at 80% |
| `style.plate_opacity` | 1.0 | Backing opacity (1 = the original is fully covered) |

## Resetting and uninstalling

- **Reset to default settings**: quit DeskMirror, delete `deskmirror.json` in the program folder (the unzipped folder,
  or the project folder when running from source) and start it again (the API key is removed too and has to be
  entered again).
- **Uninstall**: quit DeskMirror and delete the whole program folder. It doesn't change any system settings and
  doesn't start with Windows.

## Known limitations

- Tested on one PC so far: Windows 11, a 3840×2160 main screen at 100% scaling, RTX 4090. On the second screen
  (2560×1600 at 125%) only "dragging the mirror there switches screens and starts recognizing" has been checked.
  Other scaling factors, graphics cards and Windows 10 haven't been tested yet; feedback is welcome.
- Exclusive-fullscreen games and protected content (DRM video and so on) can't be overlaid or captured; switch games
  to borderless or windowed mode. Real games haven't been tested yet, only test pages that imitate game screens and
  subtitles.
- Pixel fonts, stylized lettering and very small text may be misread, and the translation goes wrong with it.
  Vertical text works when it is set in neat columns, as in comic speech bubbles; slanted sound effects need image
  translation. The local 12B model occasionally translates words such as CSS property names too.
- English, Chinese, Japanese, Indonesian and more can be recognized; for Korean, choose "Original: Korean" with the
  language button (it switches to the Korean recognition model, which can't read Chinese or Japanese).
- Page zoom (Ctrl+wheel), full page reloads, expanding and collapsing are treated as content changes: translations
  hide first and the text is recognized again, so the original flashes briefly.
- When a window is dragged quickly, translations may hide for a moment and come back once it stops.
- Newly appearing text needs time to be recognized and translated (about 1–3 seconds with a local model); while
  scrolling, translations can be a few to a few dozen pixels off the original (they line up exactly once scrolling
  stops).
- The mirror's own tab and the settings window don't scale up at 125%.
