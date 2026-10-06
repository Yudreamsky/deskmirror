# 更新记录 / Changelog

## 未发布 / Unreleased

- **更快、更省**：DeepSeek 等 OpenAI 兼容服务默认会先“思考”再回答，翻译用不着；现在翻译时关掉思考（不认这个开关的服务自动跳过）。实测一句短文 1.5～2.4 秒 → 1.1 秒。
- **英文译文更好看**：中日文译成英文放不下时，借用右边的纯色空白（不越过别的字，不盖图片、不盖视频画面）；英文单词不再从中间拆开；g、p、y 这类字母的下半截不再被裁掉；句末的全角“。”不再露在底板外面。
- **调试用的录制**：通过调试通道按用户看到的样子录 60 帧视频（宣传片的实录素材用）。

- **Faster and cheaper**: DeepSeek and other OpenAI-compatible services think before answering by default; thinking is
  now turned off for translation (skipped automatically for services that don't support the switch). A short test went
  from 1.5–2.4 s to 1.1 s.
- **Nicer English translations**: when the English translation of Chinese or Japanese text doesn't fit, it borrows
  plain space to its right (never over other text, pictures or video); English words are no longer split in the
  middle; descenders are no longer clipped; a trailing full-width "。" no longer peeks out.
- **Debug recording**: record 60 fps video of what the user sees through the debug channel (used for promo footage).

## 1.0.0（2026-10-06）

第一个正式版。

- **魔镜**：可拖动、可调整大小的镜框，框里同一位置换成译文，框外照常是桌面；跟得住滚动、窗口移动、遮挡和视频字幕；后台预译魔镜所在的屏幕，拖到哪里马上有译文。
- **翻译服务**：本机 Ollama（免费，文字不出本机），或 DeepSeek、通义千问、OpenAI 等 OpenAI 兼容接口；测试连接、获取模型列表。
- **语言**：第一次启动先选母语（也就是译文语言）；中文、英文两种界面；标签上的语言按钮随时切换原文和译文语言（中、英、日、韩、印尼），原文选韩文时自动换韩文识别模型。
- **术语**：术语表里的词必须照用；没写进术语表的词也尽量前后一致；字幕和对话带上前几句作上下文。
- **看图翻译**：把镜框里的画面交给能看图的模型来读、来翻（漫画、艺术字、图片里的字）；发给云端前每次都先问。
- **隐私**：不翻译名单（默认排除聊天软件、密码管理器、网银）、三档预译范围、当天用量统计；日志不记屏幕文字，“记住译文”默认关闭。
- **其他**：暂停、截图（原图 / 译图）、历史面板和改译文、最多 4 个魔镜、魔镜跟随窗口、新手指南。
- **Windows 发行包**：解压后双击 `DeskMirror.exe`，不用装 Python；文字识别模型（含韩文）都在包里。

First official release.

- **The mirror**: a draggable, resizable frame that shows the same spot of your desktop with the text translated in
  place. It follows scrolling, window moves, overlapping windows and video subtitles, and pre-translates the mirror's
  screen in the background, so translations are ready wherever you drag.
- **Translation services**: local Ollama (free, text stays on your PC) or any OpenAI-compatible API (DeepSeek, Qwen,
  OpenAI, …), with a connection test and a model list.
- **Languages**: pick your native language (the translation target) on first launch; English and Chinese interface;
  switch source and target languages from the mirror's tab (Chinese, English, Japanese, Korean, Indonesian).
- **Terminology**: a glossary that is always applied, consistent wording for terms not in the glossary, and the last
  few lines as context for subtitles and dialogue.
- **Image translation**: send the frame to a vision model (comics, stylized lettering, text in pictures); you are asked
  every time before anything goes to a cloud service.
- **Privacy**: do-not-translate lists (chat apps, password managers and online banking by default), three
  pre-translation scopes, daily usage counts; the log never records screen text.
- **Windows release**: unzip and run `DeskMirror.exe`; no Python needed, OCR models (including Korean) included.
