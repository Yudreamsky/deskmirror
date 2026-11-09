# 桌面魔镜 · 网页原位翻译（浏览器扩展）隐私政策

生效日期：2026 年 11 月 9 日（扩展 0.9.1 版）

**一句话：开发者没有自己的服务器，收不到你的任何数据。扩展在你的电脑上处理网页文字等数据；要翻译时，只把要翻的文字连同网页标题、域名，发给你自己选的翻译服务。**

Chrome 应用商店要求，扩展只在本机处理、不发出去的数据也要写清楚，所以下面都列出来了。商店页“隐私权”一栏列出的数据类别，也是照这个要求申报的；这些数据都不会发给开发者。

## 1. 扩展处理哪些数据

1. **网页上的文字。** 你打开魔镜以后，扩展读取当前网页上你正在看的这一屏、以及上下各半屏里的文字，发去翻译，再按原来的排版显示译文。离镜框近的先翻；整页翻译时，整个窗口都是镜框；往下滚，新出现的文字也会翻。
2. **网页标题和域名。** 下面三种情况发起翻译请求时，扩展会把当前网页的标题和域名（合起来最多 160 个字，例如“如何煮咖啡 — example.com”）随要翻的文字一起发出去，作为翻译时参考的上下文，让译文更贴切：
   - 打开魔镜翻译网页；
   - 魔镜盖住开着字幕的视频，提前翻译字幕；
   - 你在输入框里连按三次空格，翻译框里的文字。

   网页上只显示着气泡、你没有打开魔镜，也没有在输入框里连按三次空格时，扩展不会因此发出任何请求。
3. **视频字幕。** 镜框盖住开着字幕的视频时，扩展读取这个视频的字幕，把播放位置往前 10 秒、往后 5 分钟以内的字幕提前发去翻译，在原字幕的位置显示译文。网页上挂着的字幕轨，扩展直接读。在 YouTube 上，扩展往网页里放一小段扩展自带的脚本，只抄下播放器自己取到的字幕，不改任何请求；如果字幕本来就开着，它会请播放器重新载入一次字幕。
4. **输入框里的文字。** 只有在你在某个输入框里连按三次空格时，扩展才把这个框里的文字发去翻译，并把译文替换进框里。这些文字可能是邮件、聊天消息，或者你正在写的内容。为了让你再连按三次空格就能换回原文，最近 20 次的原文和译文留在这个网页的内存里，不写进硬盘，关掉网页就没了。
5. **鼠标、键盘和滚动（只在本机）。** 魔镜开着时，扩展用这些让译文那一层和原网页保持一样：
   - 鼠标位置、点击、拖动、滚动位置：用来对齐、在译文上画出选中的高亮、显示悬停弹出的菜单；
   - 网页输入框里的内容：同步显示在译文那一层里。除非你在框里连按三次空格，这些内容不会发出去；
   - 按键：只响应连按三次空格、Ctrl+A、Ctrl+Alt+O 这几个操作，再就是照原网页显示键盘焦点框。

   这些都只在你的电脑上用，扩展不记录你按了什么键，也不保存、不发送这些操作。
6. **复制（只在本机）。** 你在镜框里选字以后复制或拖走时，扩展把剪贴板里的内容换成你看到的译文。
7. **设置和 API Key（只在本机）。** 语言、翻译服务列表（包括备用服务）、你填的 API Key、气泡的位置，保存在这台电脑上 Chrome 的扩展存储里（chrome.storage.local）。API Key 只发给它对应的翻译服务。
8. **出错记录（只在本机）。** 哪个翻译服务刚出过错、是什么原因，只保存在浏览器的会话存储里（chrome.storage.session），关掉浏览器就清空。

## 2. 发给谁

- **只发给你选的翻译服务。** 你在设置里排了备用服务时，主力用不了就换下一个，这一批请求就发给实际处理它的那个服务。
- **本机模型：在本机处理。** 用这台电脑上运行的模型（例如 Ollama、LM Studio 里的本地模型）时，文字在你的电脑上处理，不离开你的电脑。注意：本机 Ollama 里名字带 :cloud 的模型，实际在 Ollama 的服务器上运行。选这种模型时，文字会经本机的 Ollama 发到 Ollama 的服务器。
- **云端服务：直接发过去。** 你选用云端服务时，请求从你的浏览器直接发给那个服务，开发者不经手；你配好了云端备用服务、扩展切换过去时也一样。云端服务例如 DeepSeek、OpenAI、Google Gemini，或者你自己填的地址。预设的云端服务都用 HTTPS 加密传输；你自己填的地址用什么方式传输，由那个地址决定。
- 翻译服务怎么处理收到的文字，以那个服务自己的隐私政策为准。

## 3. 开发者收不到任何数据

- 没有开发者自己的服务器，不用注册账号，不做使用统计，不记录你看过哪些网页。
- 扩展不把任何数据发给开发者。除了你选的翻译服务，也不发给其他任何人。
- 你主动写信反馈时，开发者只会看到你信里写的内容。

## 4. 保存多久、怎么删除

- 网页文字、标题、域名、字幕、输入框里的文字：只在翻译时用，扩展不把它们写进硬盘。译文和输入框最近 20 次的记录，只在这个网页的内存里，关掉网页就没了。
- 设置和 API Key：一直存在这台电脑上，直到你在设置里删掉，或者卸载扩展（卸载时一起删除）。
- 出错记录：关掉浏览器就清空。
- 不想让文字离开你的电脑，可以用本机模型，或者不打开魔镜、不在输入框里连按三次空格。关掉“所有网页默认显示魔镜气泡”以后，扩展就不再往网页里放东西。

## 5. 权限

- **activeTab 和 scripting：** 你点工具栏图标或按快捷键时，把魔镜放进当前网页。在 YouTube 上，还会放上面说的抄字幕的小脚本。
- **storage：** 保存上面说的设置。
- **访问 127.0.0.1、localhost 和 api.deepseek.com：** 请求本机模型和 DeepSeek。
- **访问其他网址（可选）：** 只在两种情况下请求。
  - 你添加某个网址的翻译服务时：只用于这个网址。
  - 你在设置里打开“所有网页默认显示魔镜气泡”时：请求访问所有网站，只用来在每个网页的边上放一个气泡，让输入框翻译在所有网页上都能用。气泡不读取网页上的文字，你点开魔镜才开始读取和翻译。

## 6. 有限使用

扩展对用户数据的使用，遵守 Chrome 应用商店用户数据政策（Chrome Web Store User Data Policy），包括其中的“有限使用”（Limited Use）要求：

- 只用于一个用途：在网页上原位翻译文字（包括视频字幕和输入框里的文字）；
- 只在翻译需要时，交给你选的翻译服务；
- 不出售，不用于广告（包括个性化广告），不用于判断信用或发放贷款；
- 不让任何人阅读你的数据，开发者也收不到这些数据。

## 7. 政策更新

这份政策有改动时，上面的生效日期会跟着更新。

## 8. 联系

有问题请写信：a885187@gmail.com

---

# DeskMirror – translate web pages in place (browser extension) Privacy Policy

Effective date: November 9, 2026 (extension version 0.9.1)

**In short: the developer has no server and receives none of your data. The extension handles page text and other data on your computer. To translate, it sends only the text to be translated, together with the page title and domain, to the translation service you choose.**

The Chrome Web Store asks extensions to disclose the data they handle, even data that is only processed on your computer and never sent anywhere, so all of it is listed below. The data types listed under Privacy on the store page are declared the same way; none of that data is sent to the developer.

## 1. What data the extension handles

1. **Text on the page.** After you open the mirror, the extension reads the text on the screen you are looking at, plus half a screen above and below it. It sends this text for translation and shows the translation in the original layout. Text closest to the frame goes first. In whole-page mode the frame is the whole window. As you scroll, newly visible text is translated too.
2. **Page title and domain.** In the three cases below, each translation request also carries the current page's title and domain (at most 160 characters together, for example "How to brew coffee — example.com"). They are context that helps the translation fit the page:
   - translating a web page in the mirror;
   - translating the subtitles of a video ahead of playback, when the mirror covers the video and captions are on;
   - translating the text in a text box after you press Space three times.

   While a page only shows the bubble, and you have neither opened the mirror nor pressed Space three times in a text box, the extension sends no request because of it.
3. **Video subtitles.** When the frame covers a video with captions turned on, the extension reads that video's subtitles. It sends the lines from 10 seconds before to 5 minutes after the playback position for translation ahead of time, and shows the translation where the original subtitles are. Subtitle tracks on the page are read directly. On YouTube, the extension adds one small bundled script to the page. That script only copies the captions the video player loads itself and changes no request. If captions were already on, it asks the player to reload them once.
4. **Text in text boxes.** Only when you press Space three times in a text box does the extension send that box's text for translation and put the translation back into the box. This text may be an email, a chat message or something you are writing. The last 20 originals and translations stay only in that page's memory, so that pressing Space three times again can bring back the original. They are never written to disk and are gone when you close the page.
5. **Mouse, keyboard and scrolling (on your computer only).** While the mirror is open, the extension uses these to keep the translated layer the same as the page:
   - the mouse position, clicks, drags and the scroll position: to keep the two aligned, draw your selection on the translation and show hover menus;
   - what is in the page's text boxes: shown the same way on the translated layer. It is not sent anywhere unless you press Space three times in that box;
   - key presses: the extension reacts only to three Spaces in a row, Ctrl+A and Ctrl+Alt+O, and otherwise only notices keyboard use to show the same focus outline as the page.

   All of this is used only on your computer. The extension does not record which keys you press, and does not store or send any of it.
6. **Copying (on your computer only).** When you copy or drag away text you selected inside the frame, the extension puts the translation you see on the clipboard.
7. **Settings and API keys (on your computer only).** The following are stored in Chrome's extension storage on this computer (chrome.storage.local): your languages, your list of translation services (including backups), the API keys you enter and the bubble's position. Each API key is sent only to its own translation service.
8. **Error records (on your computer only).** Which translation service failed recently, and why, is kept only in the browser's session storage (chrome.storage.session). It is cleared when the browser closes.

## 2. Where the data goes

- **Only to the translation service you choose.** If you set up backup services, the next one takes over when the main one can't be used. Each batch goes to whichever service actually handles it.
- **Local models: processed on your computer.** With a model running on this computer (for example a local model in Ollama or LM Studio), the text is processed on your computer and never leaves it. Note: models in your local Ollama whose names end in :cloud actually run on Ollama's servers. If you pick one, the text goes through your local Ollama to Ollama's servers.
- **Cloud services: sent directly.** When you choose a cloud service, the request goes straight from your browser to that service; it never passes through the developer. The same applies when the extension switches to a cloud backup you have set up. Cloud services include, for example, DeepSeek, OpenAI, Google Gemini or an address you enter yourself. The built-in cloud services all use HTTPS; for an address you enter yourself, the connection is whatever that address uses.
- How a translation service handles the text it receives is governed by that service's own privacy policy.

## 3. The developer receives no data

- There is no developer server and no account. The extension keeps no usage statistics and no record of the pages you visit.
- The extension sends no data to the developer. It sends none to anyone other than the translation service you choose.
- If you write to the developer, the developer sees only what you write.

## 4. How long data is kept and how to delete it

- Page text, titles, domains, subtitles and text-box text are used only for translating; the extension never writes them to disk. Translations and the last 20 text-box records stay only in that page's memory and are gone when you close the page.
- Settings and API keys stay on this computer until you delete them in Settings or uninstall the extension (uninstalling removes them).
- Error records are cleared when the browser closes.
- To keep text from leaving your computer, use a local model, or don't open the mirror and don't press Space three times in text boxes. When you turn off "Show the mirror bubble on every page", the extension no longer puts anything into pages.

## 5. Permissions

- **activeTab and scripting:** put the mirror into the current page when you click the toolbar icon or press the shortcut. On YouTube, this also adds the caption-copying script described above.
- **storage:** save the settings above.
- **Access to 127.0.0.1, localhost and api.deepseek.com:** reach local models and DeepSeek.
- **Access to other addresses (optional):** requested only in two cases.
  - When you add a translation service at that address: used only for it.
  - When you turn on "Show the mirror bubble on every page" in Settings: this asks for access to all websites. It is used only to place a bubble at the edge of each page and to make text-box translation work on every page. The bubble reads no text on the page; reading and translating start only when you open the mirror.

## 6. Limited Use

The extension's use of user data complies with the Chrome Web Store User Data Policy, including the Limited Use requirements:

- it is used for one purpose only: translating text in place on web pages (including video subtitles and text in text boxes);
- it is passed only to the translation service you choose, and only as needed to translate;
- it is not sold, not used for advertising (including personalized advertising), and not used to determine creditworthiness or for lending;
- no person reads your data; the developer never receives it.

## 7. Changes

When this policy changes, the effective date above is updated.

## 8. Contact

Questions: a885187@gmail.com
