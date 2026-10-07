# 更新记录 / Changelog

## 未发布

- **Windows 10 上不再把自己的译文当原文**：Windows 10 不支持让半透明的窗口对截屏隐身，魔镜会截到自己画的译文、又翻一遍（日志里是“SetWindowDisplayAffinity 失败，错误码 8”）。现在启动时先试一下，不支持就改用色键窗口：看起来一样，鼠标操作也一样，只是底板总是不透明（这种电脑上设置里的“底板不透明度”不能调）。（#2）
- **截图模式**：别的截图、录屏软件截不到魔镜，因为魔镜自己也靠截屏看字，截得到自己就会把译文当原文。现在托盘菜单或右键魔镜标签里可以打开“让截图工具截到魔镜”：期间译文定住不更新，关掉后接着识别、翻译。标签上的“截原图 / 截译图”照样能用。（#2）
- **新手指南第 3 步能获取模型列表**：选云端服务时，填好 API Key 点“获取模型列表”，从服务商现有的模型里选，不用手填；换服务时不再留着上一家的模型名。（#3）
- **命令行改设置，AI 助手能替你设置好**：`DeskMirrorCLI.exe`（源码版 `python -m deskmirror`）能查看、修改全部设置（`config list / get / set / reset / keys`），换翻译服务（`service deepseek` 等）、列出模型、测试连接、管理术语表；加 `--json` 输出 JSON。超出范围、格式不对的值直接报错；API Key 从标准输入读、只显示前后几位。正在运行的魔镜一秒内自动载入改动（以前直接改配置文件要先退出魔镜），说明里加了“让 AI 帮你设置”一节。（#4）
- **中文 Windows 上从源码安装不再失败**：依赖清单的注释改成英文，setup.bat、start.bat 让 Python 按 UTF-8 读写（以前 pip 按 GBK 读依赖清单就报错退出）。（#1）

- **No more translating its own translations on Windows 10**: Windows 10 can't hide translucent windows from screen
  capture, so the mirror captured the translations it had drawn and translated them again (the log said
  "SetWindowDisplayAffinity 失败，错误码 8"). DeskMirror now checks at startup and, where needed, uses colour-key
  windows instead: they look and work the same, except that plates are always opaque (the plate opacity setting is
  disabled on such PCs). (#2)
- **Screenshot mode**: other screenshot and screen recording tools can't capture the mirror, because the mirror reads
  the screen through screen capture too and would otherwise see its own translations. Now "Let screenshot tools
  capture the mirror" in the tray menu or the tab's right-click menu makes them visible; translations stay frozen
  meanwhile and carry on when you turn it off. The tab's screenshot buttons work as before. (#2)
- **Fetch models in the quick start**: step 3 has a "Fetch models" button for cloud services that lists the models
  the service offers, so you can pick one instead of typing it; switching services no longer keeps the previous
  service's model name. (#3)
- **Settings from the command line, so an AI assistant can set it up for you**: `DeskMirrorCLI.exe` (from source:
  `python -m deskmirror`) reads and changes every setting (`config list / get / set / reset / keys`), switches the
  translation service (`service deepseek` and others), lists models, tests the connection and manages the glossary;
  add `--json` for JSON output. Out-of-range or malformed values are rejected; API keys are read from standard input
  and only shown in part. A running DeskMirror picks up the changes within a second (editing the settings file used to
  require quitting it first), and the README has a new "Let an AI assistant set it up" section. (#4)
- **Installing from source on Chinese Windows**: the requirements files are plain ASCII now, and setup.bat and
  start.bat run Python in UTF-8 mode (pip used to fail reading the requirements file as GBK). (#1)

## 1.1.1（2026-10-07）

漫画气泡更干净：竖排气泡的底板只盖原来的字，不再盖掉气泡的边框，译文和原文一样大；说明有了六种语言。

- **漫画气泡更干净**：竖排气泡的底板只盖原来的每一个字（以前按检测框铺一整块，检测框常把气泡的弧形边框框进去，一列下端又常是窄的“！”，方底板的角会盖掉边框），气泡边框和边框外的网点纸都完整保留；译文字号按原文字的实际宽度估，和原文一样大（以前长的一列会大一圈）；英文译文在气泡里每行居中。识别时也不再把框进来的边框当成字（句末的“！”不会被认成长音）。
- **说明有六种语言**：README 有英文（GitHub 首页默认）、简体中文、繁體中文、日本語、한국어、Bahasa Indonesia，每种都配了实录截图和开头的动图；使用说明、新手指南加了英文版。发行包里带上各语言的 README。

Cleaner comic bubbles: in vertical speech bubbles the plate covers just the original characters, so the bubble
outlines stay intact and translations match the original size; the docs now come in six languages.

- **Cleaner comic bubbles**: in vertical speech bubbles the plate now covers just the original characters (it used to
  fill the whole detection box, which often took in part of the curved outline, and its corners stuck out past a
  narrow "!" at the end of a column), so bubble outlines and the screentone around them stay intact. The translation's
  font size follows the actual width of the original characters (long columns used to come out a size larger), and
  English is centered line by line. The outline is no longer mistaken for text either (a final "!" is no longer read
  as a long vowel mark).
- **Docs in six languages**: the README in English (the default on GitHub), Simplified Chinese, Traditional Chinese,
  Japanese, Korean and Indonesian, each with real screenshots and an animation at the top; English versions of the
  user guide and the quick start. The release zip includes the README in every language.

## 1.1.0（2026-10-07）

游戏、视频字幕、漫画用起来更顺：倒计时不闪、字幕换句不空不露原文、漫画竖排气泡直接翻；加了“翻译聊天软件”开关。

- **翻译聊天软件开关**：聊天软件默认仍不翻（私人聊天不发出去）；和外国同事、朋友聊天时，右键魔镜的标签或托盘菜单勾选“翻译聊天软件”，微信、QQ、钉钉、飞书、Telegram、WhatsApp 等窗口就照常翻译，聊完再关掉。密码管理器和网银、支付页面始终不翻。魔镜停在没翻的聊天窗口上时，标签会提示怎么打开。
- **更快、更省**：DeepSeek 等 OpenAI 兼容服务默认会先“思考”再回答，翻译用不着；现在翻译时关掉思考（不认这个开关的服务自动跳过）。实测一句短文 1.5～2.4 秒 → 1.1 秒。
- **英文译文更好看**：中日文译成英文放不下时，借用右边的纯色空白（不越过别的字，不盖图片、不盖视频画面）；英文单词不再从中间拆开；g、p、y 这类字母的下半截不再被裁掉；句末的全角“。”不再露在底板外面。
- **倒计时不再一闪一闪**：游戏里的倒计时、计数这类只有数字在变的字，以前每跳一下译文都要消失一会儿、露出原文，有时还忽大忽小；现在旧译文先留着，数字一变马上单独重新识别，约 0.2 秒换成新数字，排版也保持不变。动态画面上的抓拍识别不再从一行字中间切开。
- **译文不再伸出面板**：一行放不下要向下多占几行时，只用下面同色的空白；下面是面板边框、图片或在动的画面，就先再缩小一点字号排进原来的高度。
- **英文译文先横向压扁一点，少缩字号**：中日文译成英文常常更长，放不下时先把字横向压扁（压到八成以内几乎看不出来）再缩字号；名牌、倒计时这类短标签快要伸出面板时最扁压到原宽的六成（设置项 `style.min_squash`；中日韩文字最多压到八成）。小名牌里排成两行的译文不再被裁掉半截。
- **日文识别更准**：片假名的长音“ー”被识别成“-”或“一”时自动改回（比如“セ-ブ”→“セーブ”），术语表对得上，游戏菜单不再漏翻。字号小的短词（三个字以内，比如“セーブ”）重新识别时置信度常常差一点：现在同一位置还是同样的字就算认出来了，译文不再时有时无；像素没变时就算没认出来，也要连着三次才撤下。
- **字幕换句不再两头露原文**：新句子比旧译文宽时，以前在新译文出来之前（常常一秒多）两头会露出原文；现在字幕一换就单独识别那一条，约 0.2～0.5 秒内先用空底板挡住，旧译文留在上面，新译文一到就顶掉。
- **视频字幕换句不再空一下**：以前有几种情况换句时译文会消失一秒左右：刚把魔镜挪到视频上时的第一句字幕、新句子的识别结果因为画面在变被丢掉、识别时少认了句末一个字。现在旧译文都会留到新译文出来；中文、日文、韩文字幕实测各换句 5 次以上都不再空。识别时标点后的空格时有时无，也不再当成新句子多翻译一次。
- **漫画的竖排气泡能直接翻了**：以前横排的识别模型把竖排的字认成乱码（“待って！”认成“待号”）；现在把一列字切成单字排成一行再认，竖线写的长音、破折号单独补上，几列从右往左连成一句。中日文译文也竖着排在气泡里（在“！”“。”后面换列），英文照旧横排；底板不再盖住气泡的弧形边框。英文换行时不再把单词后面的“!”挤到下一行。
- **调试用的录制**：通过调试通道按用户看到的样子录 60 帧视频（宣传片的实录素材用）。

Smoother games, video subtitles and comics: countdowns no longer flicker, subtitle changes neither blank out nor show
the original, vertical text in manga speech bubbles is translated directly; and a new “Translate chat apps” switch.

- **Translate chat apps switch**: chat apps are still skipped by default (private chats are not sent anywhere); when
  chatting with colleagues or friends abroad, right-click the mirror's tab or the tray icon and check “Translate chat
  apps” to translate WeChat, QQ, DingTalk, Feishu, Telegram, WhatsApp and others, then turn it off. Password managers
  and banking or payment pages are never translated. The tab tells you how to turn it on when the mirror is over a chat.
- **Faster and cheaper**: DeepSeek and other OpenAI-compatible services think before answering by default; thinking is
  now turned off for translation (skipped automatically for services that don't support the switch). A short test went
  from 1.5–2.4 s to 1.1 s.
- **Nicer English translations**: when the English translation of Chinese or Japanese text doesn't fit, it borrows
  plain space to its right (never over other text, pictures or video); English words are no longer split in the
  middle; descenders are no longer clipped; a trailing full-width "。" no longer peeks out.
- **Countdowns no longer flicker**: for timers and counters where only the digits change, the translation used to
  vanish on every tick (showing the original) and sometimes changed size; the old translation now stays, the counter
  is re-read right away and the new number appears in about 0.2 s with the same layout. Snapshot reads on moving
  pictures no longer cut a line of text in half.
- **Translations stay inside their panels**: when a translation needs extra lines, it only takes plain space below;
  above a panel border, picture or moving video it first shrinks a little to fit the original height.
- **English is squeezed a little before it shrinks**: translations from Chinese or Japanese are often longer; they are
  first narrowed horizontally (up to 80%, barely visible) before the font gets smaller, and short labels such as name
  tags and timers may go down to 60% before spilling out of their panel (`style.min_squash`; CJK text stops at 80%).
  Two-line translations in small name tags are no longer cut in half.
- **Better Japanese OCR**: a katakana long-vowel mark misread as "-" or "一" is fixed automatically (セ-ブ → セーブ), so
  glossary terms match and game menus are no longer left untranslated. Small short words (three characters or fewer)
  often come back from a re-read with slightly too little confidence; the same word in the same place now counts as
  seen, so their translations no longer come and go, and unchanged pixels need three missed reads in a row.
- **Subtitle changes no longer show the original at the edges**: when the new line was wider than the old translation,
  its ends used to show until the new translation arrived (often over a second); the changed line is now re-read right
  away and covered by a blank plate within about 0.2–0.5 s, with the old translation on top until the new one is ready.
- **Subtitles no longer blank out between lines**: the translation used to vanish for about a second when the line
  changed in a few cases: the first subtitle after moving the mirror onto a video, a new line whose OCR result was
  dropped because the picture kept moving, or a read that missed the final character. The old translation now stays
  until the new one is ready; Chinese, Japanese and Korean subtitles were tested over many line changes. A space after
  punctuation that OCR sometimes sees and sometimes doesn't no longer makes a line count as new and get translated again.
- **Vertical text in manga speech bubbles is translated directly**: the horizontal OCR model used to garble vertical
  columns; each column is now cut into characters and read as a row, long-vowel and dash strokes are filled in, and
  columns are read right to left. Chinese and Japanese translations are laid out vertically in the bubble too (new
  column after “！” or “。”), English stays horizontal, and the plate no longer covers the curved bubble outline.
  English line breaks no longer push a trailing “!” onto the next line.
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
