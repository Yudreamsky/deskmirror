"""界面文字的英文对照表：键是代码里 tr("…") / N_("…") 的中文原文（一字不差），值是英文。

占位符 {x} 要和中文一致；新增界面文字时在这里补一条（tests/test_i18n.py 会检查缺漏）。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # app.py
    '已暂停：不识别、不翻译（点“继续”恢复）':
        'Paused: not recognizing or translating (click “Resume” to continue)',
    '桌面魔镜':
        'DeskMirror',
    '魔镜已经在运行了（看看右下角托盘图标）。':
        'DeskMirror is already running (look for its icon at the bottom right of the taskbar).',
    '刷新镜框内区域':
        'Refresh inside the frame',
    '新建一个魔镜':
        'New mirror',
    '截原图（镜框内原样）':
        'Screenshot: original (the frame as is)',
    '截译图（镜框内带译文）':
        'Screenshot: translated (the frame with translations)',
    '看图翻译（把镜框里的画面交给能看图的模型）':
        'Image translation (send the frame to a vision model)',
    '预译范围':
        'Pre-translation scope',
    '不翻译魔镜下的这个程序':
        "Don't translate the program under the mirror",
    '历史记录…（最近的原文和译文）':
        'History… (recent originals and translations)',
    '新手指南…':
        'Getting started…',
    '设置…':
        'Settings…',
    '显示识别到的滚动区域（调试）':
        'Show detected scroll areas (debug)',
    '关于…':
        'About…',
    '退出':
        'Quit',
    '魔镜下面没有找到窗口。':
        'No window found under the mirror.',
    '原文':
        'Source',
    '译成':
        'Translate into',
    '发送':
        'Send',
    '不发':
        "Don't send",
    '本机':
        'this PC',
    ' · 镜内有不翻译的窗口（排除名单）':
        ' · excluded windows in the mirror',
    ' · 聊天窗口默认不翻译（右键标签可打开）':
        ' · chat windows are not translated by default (right-click the tab to turn on)',
    '翻译聊天软件（和外国同事、朋友聊天时打开）':
        'Translate chat apps (turn on when chatting with colleagues or friends abroad)',
    '用的是本机 Ollama，聊天内容不出本机。':
        'You are using local Ollama, so chats stay on this PC. ',
    '聊天内容会发给翻译服务（{host}）。':
        'Chat text will be sent to the translation service ({host}). ',
    '已打开：微信、QQ、钉钉、飞书、Telegram、WhatsApp 等聊天窗口也会翻译。{where}聊完可以在托盘菜单或右键魔镜标签里关掉。':
        'On: chat windows (WeChat, QQ, DingTalk, Feishu, Telegram, WhatsApp and more) are translated too. {where}Turn it off from the tray menu or by right-clicking the mirror tab when you are done.',
    '已关闭：聊天软件的窗口不再识别、不再翻译。':
        'Off: chat app windows are no longer recognized or translated.',
    '已截译图':
        'Translated screenshot taken',
    '已截原图':
        'Original screenshot taken',
    '显示魔镜':
        'Show mirror',
    '隐藏魔镜':
        'Hide mirror',
    '继续翻译':
        'Resume translating',
    '暂停（框留着，不识别、不翻译）':
        'Pause (keep the frame, stop recognizing and translating)',
    '最多同时开 4 个魔镜。':
        'You can have at most 4 mirrors open.',
    '跟随下面的窗口（窗口移动、缩放时魔镜跟着走）':
        'Follow the window below (the mirror moves and resizes with it)',
    '取消跟随窗口':
        'Stop following the window',
    '关闭这个魔镜':
        'Close this mirror',
    '部分快捷键不可用':
        'Some hotkeys are unavailable',
    '继续工作，正在核对画面…':
        'Resuming, checking the screen…',
    '桌面魔镜 · 今天发给翻译服务（{where}）{requests} 次、{chars} 字':
        'DeskMirror · sent to the translation service ({where}) today: {requests} requests, {chars} characters',
    '魔镜下面没有找到窗口（或拿不到它的程序名）。':
        "No window found under the mirror (or its program name isn't available).",
    '跟随的窗口已关闭，魔镜不再跟随。':
        'The window being followed was closed; the mirror no longer follows it.',
    '本机 {model}':
        '{model} on this PC',
    '{host} 的 {model}':
        '{model} at {host}',
    '正在启动文字识别…':
        'Starting text recognition…',
    ' · 服务较慢':
        ' · service is slow',
    '已把 {name} 加入不翻译名单：它的窗口不再识别和翻译。可在 设置 → 范围与隐私 里移除。':
        'Added {name} to the do-not-translate list: its windows will no longer be recognized or translated. You can remove it in Settings → Scope and privacy.',
    '截图失败':
        'Screenshot failed',
    '魔镜译图':
        'DeskMirror-translated',
    '魔镜原图':
        'DeskMirror-original',
    '已复制到剪贴板，并保存到 {path}（点这条提示打开文件夹）':
        'Copied to the clipboard and saved to {path} (click this message to open the folder)',
    '已复制到剪贴板；保存到 {folder} 失败。':
        "Copied to the clipboard; couldn't save to {folder}.",
    '识别设备、屏幕范围和滚动跟随的更改在下次启动时生效。':
        'Changes to the recognition device, screens and scroll following take effect the next time DeskMirror starts.',
    '魔镜正跟随窗口：{title}':
        'The mirror is following: {title}',
    '这张截图会发给 {host}（模型 {model}），截图里看得见的内容都会发出去。\n\n要发送吗？':
        'This screenshot will be sent to {host} (model {model}). Everything visible in it will be sent.\n\nSend it?',
    '截图失败：{error}':
        'Screenshot failed: {error}',
    '内部错误：{name}':
        'Internal error: {name}',
    '翻译已暂停：{msg}（点 ⟳ 重试或改设置）':
        'Translation paused: {msg} (click ⟳ to retry, or change the settings)',
    '翻译服务出错，稍后自动重试：{msg}':
        'Translation service error, retrying shortly: {msg}',
    '{n} 块翻译失败，点 ⟳ 重试':
        '{n} blocks failed to translate; click ⟳ to retry',
    '正在识别桌面文字…':
        'Recognizing text on the screen…',
    '翻译中：镜内还有 {n} 块':
        'Translating: {n} blocks left in the mirror',
    '就绪 · 已翻译 {n} 块':
        'Ready · {n} blocks translated',
    # capture.py
    '暂不支持旋转的显示器':
        "Rotated displays aren't supported yet",
    '{what} 失败 0x{hr:08X}':
        '{what} failed: 0x{hr:08X}',
    '找不到显示器 {name} 对应的 DXGI 输出':
        'No DXGI output found for display {name}',
    # config.py
    '自动识别':
        'Auto-detect',
    '英文':
        'English',
    '印尼文':
        'Indonesian',
    '日文':
        'Japanese',
    '韩文（换用韩文识别模型）':
        'Korean (switches to the Korean recognition model)',
    '中文':
        'Chinese',
    '自动':
        'Auto',
    '英':
        'EN',
    '印尼':
        'ID',
    '日':
        'JA',
    '韩':
        'KO',
    '中':
        'ZH',
    '繁':
        'ZH-T',
    '通义千问（阿里云百炼）':
        'Qwen (Alibaba Cloud Model Studio)',
    '硅基流动':
        'SiliconFlow',
    'Ollama（OpenAI 兼容）':
        'Ollama (OpenAI-compatible)',
    'LM Studio（本地）':
        'LM Studio (local)',
    '整块屏幕（拖到哪里译文都已备好）':
        'Whole screen (translations ready wherever you drag)',
    '只翻魔镜所在的窗口':
        'Only the window under the mirror',
    '只翻镜框附近':
        'Only near the frame',
    # engine.py
    '文字识别启动失败':
        'Text recognition failed to start',
    '韩文识别模型没能下载，暂时用默认模型（检查网络后重新选一次韩文）':
        "Couldn't download the Korean recognition model; using the default model for now (check your network, then choose Korean again)",
    '模型漏掉了这段':
        'The model skipped this text',
    '初始化失败：{error}':
        'Startup failed: {error}',
    '内部错误，跟踪已停止：{name}（请重启魔镜）':
        'Internal error, tracking stopped: {name} (please restart DeskMirror)',
    # hotkeys.py
    '拖动键不能为空':
        "The drag keys can't be empty",
    '不认识的按键：{name}':
        'Unknown key: {name}',
    '快捷键缺少主键：{text}':
        'The hotkey has no main key: {text}',
    '快捷键至少要带一个 Ctrl / Alt / Shift / Win：{text}':
        'A hotkey needs at least one of Ctrl / Alt / Shift / Win: {text}',
    '快捷键格式不对：{text}':
        'Invalid hotkey: {text}',
    '{combo} 注册失败，可能被其他程序占用了':
        "Couldn't register {combo}; another program may be using it",
    '拖动键只能由 Ctrl / Alt / Shift / Win 组成：{text}':
        'The drag keys can only be Ctrl / Alt / Shift / Win: {text}',
    '快捷键只能有一个主键：{text}':
        'A hotkey can have only one main key: {text}',
    # translator.py
    '请求太频繁或额度用完（HTTP 429）':
        'Too many requests, or the quota is used up (HTTP 429)',
    '还没有填写翻译服务地址':
        'The translation service address is empty',
    '还没有填写模型名':
        'The model name is empty',
    '先填服务地址':
        'Enter the service address first',
    '服务返回错误 HTTP {code} {detail}':
        'The service returned an error: HTTP {code} {detail}',
    '翻译服务响应超时':
        'The translation service timed out',
    '连不上翻译服务（服务没启动或地址不对）':
        "Can't reach the translation service (it isn't running, or the address is wrong)",
    '翻译服务连接中途断开（服务重启或网络不稳）':
        'The connection to the translation service dropped (the service restarted or the network is unstable)',
    '连接成功，用时 {secs:.1f} 秒：{a} / {b}':
        'Connected in {secs:.1f} s: {a} / {b}',
    '连不上服务，检查服务地址和网络':
        "Can't reach the service; check the address and your network",
    '服务响应超时':
        'The service timed out',
    '服务返回的内容不是模型列表':
        "The service didn't return a model list",
    '密钥无效或没有权限（HTTP {code}）':
        'Invalid key or no permission (HTTP {code})',
    '地址或模型不存在（HTTP 404）{detail}':
        "The address or model doesn't exist (HTTP 404) {detail}",
    '服务有回应，但没有按编号返回译文（用时 {secs:.1f} 秒）；可换一个模型试试':
        "The service responded but didn't return numbered translations ({secs:.1f} s); try another model",
    '这个地址没有模型列表接口（HTTP 404），检查服务地址和接入方式':
        'This address has no model list endpoint (HTTP 404); check the address and the API type',
    '服务返回的模型列表是空的':
        'The service returned an empty model list',
    '网络错误：{name}':
        'Network error: {name}',
    '还没填 API Key':
        'No API key entered',
    '服务返回错误（HTTP {code}）':
        'The service returned an error (HTTP {code})',
    '密钥不对或没有权限（HTTP {code}）':
        'Wrong key or no permission (HTTP {code})',
    '服务报错：{detail}':
        'Service error: {detail}',
    # ui/about.py
    '复制邮箱':
        'Copy email',
    '打开新手指南':
        'Open the getting-started guide',
    '开源许可：GPL-3.0。可以免费使用、修改；修改后再发布也要以同样的许可开源。':
        'License: GPL-3.0. Free to use and modify; if you distribute a modified version, it must be open source under the same license.',
    '用到的开源组件：Qt / PySide6（LGPL-3.0）、RapidOCR 与 PaddleOCR 识别模型（Apache-2.0）、ONNX Runtime（MIT）、OpenCV（Apache-2.0）、NumPy（BSD-3-Clause）、httpx（BSD-3-Clause）、mss（MIT）。感谢这些项目的作者。':
        'Open-source components: Qt / PySide6 (LGPL-3.0), RapidOCR and the PaddleOCR recognition models (Apache-2.0), ONNX Runtime (MIT), OpenCV (Apache-2.0), NumPy (BSD-3-Clause), httpx (BSD-3-Clause), mss (MIT). Thanks to the authors of these projects.',
    '已复制':
        'Copied',
    '打赏作者':
        'Support the author',
    '完全自愿，不解锁任何功能，不打赏也一样用。':
        'Entirely optional: it unlocks nothing, and everything works the same without it.',
    '关闭':
        'Close',
    '关于桌面魔镜':
        'About DeskMirror',
    '桌面魔镜免费开源，所有功能都能用。\n如果它帮到了你，可以请作者喝杯咖啡。':
        'DeskMirror is free and open source.\nIf it helps you, you can buy the author a coffee.',
    '打赏作者…':
        'Support the author…',
    '用微信扫一扫':
        'Scan with WeChat',
    '<h3>桌面魔镜 DeskMirror</h3><p>版本 {version}</p><p>屏幕翻译工具：在网页、PDF、软件界面、游戏和视频字幕上，把译文贴在原文的位置。</p>':
        '<h3>DeskMirror</h3><p>Version {version}</p><p>A screen translator: on web pages, PDFs, apps, games and video subtitles, it puts the translation right where the original text is.</p>',
    '作者邮箱：{link}':
        "Author's email: {link}",
    '项目主页：{link}':
        'Homepage: {link}',
    '海外用户：{link}（可用 PayPal 或银行卡）':
        'Buy me a coffee on {link} (PayPal or card)',
    # ui/guide.py
    '魔镜':
        'Mirror',
    '就绪':
        'Ready',
    '← 镜框外：照常是你的桌面':
        '← Outside the frame: your desktop as usual',
    '← 镜框里：同一位置换成译文':
        '← Inside the frame: the same spot, translated',
    '欢迎使用桌面魔镜':
        'Welcome to DeskMirror',
    '第一件事：选一个翻译服务':
        'First, choose a translation service',
    '本机 Ollama（免费，文字不出本机；需要显存较大的独立显卡）':
        'Ollama on this PC (free, text stays on your PC; needs a graphics card with plenty of video memory)',
    '云端服务（DeepSeek、通义千问等；按用量收费，一般电脑都能用）':
        'Cloud service (DeepSeek, Qwen, etc.; pay per use, works on any PC)',
    '重新检查':
        'Check again',
    '服务':
        'Service',
    '模型':
        'Model',
    '在服务商网站申请；只用 Windows 账户加密保存在本机':
        "Get one on the provider's website; stored on this PC, encrypted with your Windows account",
    '测试连接':
        'Test connection',
    '魔镜怎么用':
        'Using the mirror',
    '隐私和费用':
        'Privacy and cost',
    '准备好了':
        "You're all set",
    '桌面魔镜 · 新手指南':
        'DeskMirror · Getting started',
    '跳过':
        'Skip',
    '上一步':
        'Back',
    '译文会显示成这种语言；选中文时界面用中文，选其他语言时界面用英文。以后可以在 设置 → 识别与显示 里分别修改。':
        'Translations will appear in this language. The interface is in Chinese if you choose Chinese, and in English otherwise. You can change both separately later in Settings → Recognition and display.',
    '正在检查本机的 Ollama…':
        'Checking Ollama on this PC…',
    '正在测试…':
        'Testing…',
    '本机 Ollama 和模型 {model} 都准备好了，文字不出本机，不花钱。':
        'Ollama and the model {model} are ready on this PC. Text stays on your PC, and it costs nothing.',
    '<p>桌面上那个蓝色的框就是<b>魔镜</b>：框外是你平常的桌面，框里是同一位置换成译文的样子。</p><ul><li>把魔镜拖到想看的地方就行，网页、PDF、软件、游戏、视频字幕都一样。</li><li>后台会提前翻译整块屏幕，所以拖到哪里，译文马上就在。</li><li>拖动、缩放魔镜不会重新翻译，也不会多花钱。</li></ul><p>接下来 3 分钟，把翻译服务设好，就能用了。</p>':
        "<p>The blue frame on your desktop is the <b>mirror</b>: outside it is your desktop as usual; inside it, the same spot appears translated.</p><ul><li>Just drag the mirror to what you want to read: web pages, PDFs, apps, games and video subtitles all work.</li><li>The whole screen is translated ahead of time in the background, so wherever you drag, the translation is already there.</li><li>Moving or resizing the mirror doesn't translate anything again or cost anything extra.</li></ul><p>Take 3 minutes to set up a translation service, and you're ready to go.</p>",
    '魔镜把屏幕上的文字交给翻译服务来翻。二选一：':
        'DeskMirror sends the text on your screen to a translation service. Choose one:',
    '<ul><li>用云端服务时，识别出的文字会发给它（按字数收费）。本机 Ollama 则完全不出本机。</li><li>聊天软件、密码管理器、网银窗口默认不识别、不翻译，可在设置里增减。和外国同事、朋友聊天时，右键魔镜的标签勾选“翻译聊天软件”，聊完再关掉。</li><li>日志不记屏幕上的文字；“记住译文”默认关闭。今天发了多少字，托盘图标的提示里能看到。</li></ul><p><b>预先翻译多大范围：</b></p>':
        "<ul><li>With a cloud service, the recognized text is sent to it (billed by volume). With Ollama on this PC, nothing leaves your PC.</li><li>Chat apps, password managers and online banking windows aren't recognized or translated by default; you can edit the list in Settings. When chatting with colleagues or friends abroad, right-click the mirror's tab and check “Translate chat apps”; turn it off when you're done.</li><li>The log never records text from your screen, and “Remember translations” is off by default. The tray icon's tooltip shows how much text was sent today.</li></ul><p><b>How much to translate ahead of time:</b></p>",
    "<p style='color:#888'>“整块屏幕”拖到哪里都马上有译文，但别的窗口里的文字也会发出去；用云端服务又在意隐私或花费时，建议选“只翻魔镜所在的窗口”。以后可在托盘菜单里随时改。</p>":
        "<p style='color:#888'>“Whole screen” has translations ready wherever you drag, but text in other windows is sent too. If you use a cloud service and care about privacy or cost, choose “Only the window under the mirror”. You can change this anytime from the tray menu.</p>",
    '<p>把魔镜拖到想翻译的地方，等一两秒，译文就会出现在原文的位置。</p><p>以后想再看这份指南：右键托盘图标（右下角蓝色“镜”字）→ <b>新手指南</b>，或者 设置 → 关于。退出魔镜也在托盘菜单里。</p>':
        '<p>Drag the mirror over what you want to translate. After a second or two, the translation appears right where the original text is.</p><p>To see this guide again: right-click the tray icon (the blue “镜” icon at the bottom right) → <b>Getting started</b>, or go to Settings → About. Quit is in the tray menu too.</p>',
    '开始使用':
        'Start',
    '下一步':
        'Next',
    '{service}（{model}）':
        '{service} ({model})',
    '没连上本机的 Ollama：请先到 https://ollama.com 下载安装并打开它。装好后在命令行运行 ollama pull {model}，再点“重新检查”。':
        "Can't reach Ollama on this PC: download and install it from https://ollama.com and start it. Then run ollama pull {model} in a terminal and click “Check again”.",
    'Ollama 在运行，但还没有模型 {model}：请在命令行运行 ollama pull {model}（gemma4:12b 约 7.6 GB，需要显存较大的独立显卡），下载完再点“重新检查”。':
        "Ollama is running, but the model {model} isn't installed: run ollama pull {model} in a terminal (gemma4:12b is about 7.6 GB and needs a graphics card with plenty of video memory), then click “Check again”.",
    '新手指南 · 第 {n} 步，共 {total} 步':
        'Getting started · step {n} of {total}',
    '本机 Ollama（{model}）':
        'Ollama on this PC ({model})',
    "<p><b>移动、调整大小：</b>拖魔镜上方的深色标签移动，拖蓝色边框调整大小；按住 <b>{drag}</b> 在镜框里任意位置拖也能移动。镜框里照常能点、能选文字、能滚动，操作的是下面的软件。</p><p><b>标签上的按钮：</b></p><table cellspacing='4'><tr><td><b>暂停</b></td><td>框留着，不识别、不翻译（不花钱），再点一下继续</td></tr><tr><td><b>自动→中</b></td><td>指定原文和译成的语言，比如英→中、印尼→中、韩→中</td></tr><tr><td><b>截原图 / 截译图</b></td><td>截下镜框里的画面（原样 / 带译文），复制到剪贴板</td></tr><tr><td><b>看图</b></td><td>把镜框里的画面交给能看图的模型来翻：漫画、艺术字、图片里的字</td></tr><tr><td><b>⟳</b></td><td>镜框里重新识别、重新翻译</td></tr><tr><td><b>⚙</b> / <b>—</b></td><td>设置 / 隐藏魔镜</td></tr></table><p><b>快捷键：</b>按住 <b>{peek}</b> 看原文；<b>{toggle}</b> 隐藏 / 显示；<b>{history}</b> 历史（回看刚才的字幕、对话）；<b>{vision}</b> 看图翻译。</p><p>右键魔镜的标签还能：再开一个魔镜、让魔镜跟着下面的窗口走。</p>":
        "<p><b>Move and resize:</b> drag the dark tab above the mirror to move it, and drag the blue border to resize it; hold <b>{drag}</b> to drag it from anywhere inside the frame. Inside the frame you can click, select text and scroll as usual: you're using the program underneath.</p><p><b>Buttons on the tab:</b></p><table cellspacing='4'><tr><td><b>Pause</b></td><td>Keep the frame but stop recognizing and translating (no cost); click again to resume</td></tr><tr><td><b>Auto→EN</b></td><td>Choose the source and target languages, e.g. JA→EN, ZH→EN, KO→EN</td></tr><tr><td><b>Orig. shot / Shot</b></td><td>Capture the frame (as is / with translations) and copy it to the clipboard</td></tr><tr><td><b>Image</b></td><td>Send the frame to a vision model to translate comics, stylized lettering and text in pictures</td></tr><tr><td><b>⟳</b></td><td>Recognize and translate the frame again</td></tr><tr><td><b>⚙</b> / <b>—</b></td><td>Settings / hide the mirror</td></tr></table><p><b>Hotkeys:</b> hold <b>{peek}</b> to see the original; <b>{toggle}</b> hide / show; <b>{history}</b> history (look back at recent subtitles and dialogue); <b>{vision}</b> image translation.</p><p>Right-click the mirror's tab to open another mirror or to make the mirror follow the window underneath.</p>",
    '<p>译文语言：<b>{lang}</b>；翻译服务：<b>{service}</b>；预译范围：<b>{scope}</b>。</p>':
        '<p>Translate into: <b>{lang}</b>; translation service: <b>{service}</b>; pre-translation scope: <b>{scope}</b>.</p>',
    '检查出错：{name}':
        'Check failed: {name}',
    '测试出错：{name}':
        'Test failed: {name}',
    # ui/history.py
    '桌面魔镜 · 历史':
        'DeskMirror · History',
    '搜索原文或译文':
        'Search originals or translations',
    '最近在魔镜里出现过的文字（最新的在上面），只保存在内存里，退出即清空。双击一条可以改译文。':
        "Text that recently appeared in the mirror (newest first). It's kept in memory only and cleared when you quit. Double-click an entry to edit its translation.",
    '改译文':
        'Edit translation',
    '保存':
        'Save',
    '取消':
        'Cancel',
    '复制译文':
        'Copy translation',
    '复制原文和译文':
        'Copy original and translation',
    '改译文…':
        'Edit translation…',
    '清空':
        'Clear',
    '原文：':
        'Original:',
    '译文（改完后，这段文字以后再出现也用这个译文）：':
        "Translation (after you edit it, it's also used whenever this text appears again):",
    # ui/mirror.py
    '截原图':
        'Orig. shot',
    '截译图':
        'Shot',
    '看图':
        'Image',
    '暂停':
        'Pause',
    '继续':
        'Resume',
    # ui/settings.py
    '桌面魔镜 · 设置':
        'DeskMirror · Settings',
    '翻译服务':
        'Translation service',
    '范围与隐私':
        'Scope and privacy',
    '术语表':
        'Glossary',
    '识别与显示':
        'Recognition and display',
    '快捷键':
        'Hotkeys',
    '关于':
        'About',
    'Ollama 原生接口':
        'Ollama native API',
    'OpenAI 兼容接口（DeepSeek、通义、硅基流动、LM Studio…）':
        'OpenAI-compatible API (DeepSeek, Qwen, SiliconFlow, LM Studio…)',
    '接入方式':
        'API type',
    '（常用地址，选一个自动填入）':
        '(Common services: pick one to fill in)',
    '常用服务':
        'Common services',
    '服务地址':
        'Service address',
    '获取模型列表':
        'Fetch models',
    '点“获取模型列表”选一个，也可以直接手填':
        'Click "Fetch models" to pick one, or type a name',
    '本地 Ollama 不需要；云端服务填这里。只用 Windows 账户加密保存在本机':
        'Not needed for local Ollama; enter it for cloud services. Stored on this PC, encrypted with your Windows account',
    ' 秒':
        ' s',
    '并发与超时':
        'Concurrency and timeout',
    '看图翻译（要能看图的多模态模型）':
        'Image translation (needs a multimodal model that can read images)',
    'OpenAI 兼容接口':
        'OpenAI-compatible API',
    '本机 Ollama 不需要；只用 Windows 账户加密保存在本机':
        'Not needed for Ollama on this PC; stored on this PC, encrypted with your Windows account',
    ' 像素':
        ' px',
    '“镜框附近”指镜框外':
        '“Near the frame” means within',
    '不翻译的程序\n（每行一个程序名）':
        'Programs not to translate\n(one program name per line)',
    '窗口标题含这些词\n时不翻译（每行一个）':
        'Skip windows whose title\ncontains (one per line)',
    '恢复默认名单（聊天软件、密码管理器、网银和支付页面）':
        'Restore default lists (chat apps, password managers, banking, payment)',
    '记住译文：加密保存在本机，下次遇到相同的文字直接用（默认关闭）':
        'Remember translations (encrypted on this PC; off by default)',
    '清空记住的译文':
        'Clear remembered translations',
    '译文记忆':
        'Translation memory',
    '用量':
        'Usage',
    '人名、地名、游戏里的专有名词：在这里写好译法，翻译时必须照用（不分大小写）。译法和原文一样表示保持不译。“只用于程序”填程序名（如 game.exe），空着表示所有程序都用。改了术语表后，含这些词的已有译文会重新翻译。':
        "Names, places and game terms: set their translations here and they'll always be used (case-insensitive). A translation identical to the original means “keep as is”. “Only for program” takes a program name (e.g. game.exe); leave it empty to apply everywhere. After you change the glossary, existing translations containing these terms are translated again.",
    '保持术语前后一致（推荐）':
        'Keep terminology consistent (recommended)',
    '添加一行':
        'Add row',
    '删除所选行':
        'Delete selected rows',
    '翻译与识别':
        'Translation and recognition',
    '显卡（DirectML，快）':
        'Graphics card (DirectML, fast)',
    'CPU（玩游戏时不和游戏抢显卡）':
        "CPU (doesn't compete with games for the graphics card)",
    '文字识别':
        'Text recognition',
    '处理所有屏幕（默认只处理魔镜所在的屏幕，更快、更省资源）':
        "All screens (default: only the mirror's screen, which is faster)",
    '屏幕范围':
        'Screens',
    '用滚轮学习滚动曲线，让译文和原文同步起步（以画面核对为准）':
        'Learn from the mouse wheel so translations start scrolling with the text',
    '滚动跟随':
        'Scroll following',
    '显示':
        'Display',
    '界面语言':
        'Interface language',
    '最小字号':
        'Minimum font size',
    '底板不透明度':
        'Backing opacity',
    '按住后在镜内拖动':
        'Hold to drag inside the mirror',
    '按住显示原文':
        'Hold to show the original',
    '隐藏 / 显示魔镜':
        'Hide / show the mirror',
    '历史面板':
        'History panel',
    '看图翻译':
        'Image translation',
    '已清空（保存后生效）':
        'Cleared (takes effect when you save)',
    '正在测试…（本地模型第一次加载可能要十几秒）':
        'Testing… (a local model can take 10+ seconds to load the first time)',
    '正在获取模型列表…':
        'Fetching models…',
    '同时请求':
        'Parallel requests',
    '超时':
        'Timeout',
    '提示：用云端服务时，屏幕上识别出的文字和所在窗口的标题会发送给该服务。哪些内容会被翻译，见“范围与隐私”。':
        'Note: with a cloud service, the recognized text and the titles of the windows it comes from are sent to that service. See “Scope and privacy” for what gets translated.',
    '“整块屏幕”：魔镜所在屏幕上看得见的文字都在后台预先翻译，拖到哪里都能立刻看到译文，但别的窗口里的文字也会发给翻译服务。另外两种只翻魔镜所在的窗口或镜框附近，其余等魔镜移过去再翻，更省、也更不容易把无关内容发出去。':
        "“Whole screen”: all visible text on the mirror's screen is translated ahead of time in the background, so translations appear instantly wherever you drag, but text in other windows is also sent to the translation service. The other two options only translate the window under the mirror or the area near the frame, and the rest once the mirror moves there: cheaper, and less likely to send unrelated content.",
    '名单里的窗口在送去识别之前就被遮掉：不识别、不翻译，不会发给任何翻译服务。也可以右键托盘图标 →“不翻译魔镜下的这个程序”。名单里的聊天软件只在打开“聊天软件也翻译”时照常翻（托盘菜单、右键魔镜标签也能随时开关），密码管理器和网银、支付页面始终不翻。':
        "Windows on these lists are masked before recognition: they're never recognized, translated or sent to any translation service. You can also right-click the tray icon → “Don't translate the program under the mirror”. Chat apps on the list are translated only while “Translate chat apps too” is on (you can also switch it from the tray menu or by right-clicking the mirror tab); password managers and banking and payment pages are never translated.",
    '聊天软件也翻译（微信、QQ、钉钉、飞书、Telegram、WhatsApp 等；聊天内容会发给翻译服务）':
        'Translate chat apps too (WeChat, QQ, DingTalk, Feishu, Telegram, WhatsApp and more; chat text is sent to the translation service)',
    '会把屏幕上识别出的原文和译文存进本机文件（只有当前 Windows 账户能解开）。只有数字不同的文字（计时器、进度、血量）不管开不开，都会套用已有译文、不再请求翻译。':
        'Saves recognized originals and translations to a file on this PC (only your current Windows account can decrypt it). Text that differs only in numbers (timers, progress, HP) always reuses existing translations without new requests, whether or not this is on.',
    '原文里的词':
        'Term in the original',
    '译法':
        'Translation',
    '只用于程序（可空）':
        'Only for program (optional)',
    '翻译时附上这个窗口里含同样词语的已有译文作参考，没写进术语表的词也沿用同样的译法。发给翻译服务的文字会多一些（实测约多 15%）。':
        "Adds earlier translations from the same window that contain the same words as a reference, so terms that aren't in the glossary are also translated consistently. Slightly more text is sent to the translation service (about 15% more in tests).",
    '今天（{date}）发给翻译服务 {requests} 次请求、{chars} 字（只统计数量，不记录内容）':
        'Today ({date}): {requests} requests and {chars} characters sent to the translation service (counts only, no content)',
    '按 {key} 或点魔镜标签上的“看图”，把镜框里的画面交给这里的模型来读、来翻，适合漫画、艺术字、图片里的字。默认用本机 Ollama 的 gemma4:12b，画面不出本机；发给云端服务前，每次都会先问你。':
        "Press {key} or click “Image” on the mirror's tab to have this model read and translate the picture inside the frame. Good for comics, stylized lettering and text in pictures. By default it uses gemma4:12b on local Ollama, so the picture never leaves your PC; before anything is sent to a cloud service, you'll be asked every time.",
    '取到 {n} 个模型，已列在下拉框里，点一个即可':
        "Found {n} models. They're listed in the drop-down; just pick one",
    '出错了（{name}）':
        'Something went wrong ({name})',
    '；当前填的“{model}”不在列表里，可能填错了':
        "; the current “{model}” isn't in the list and may be misspelled",
    '没取到模型列表：{error}。也可以直接手填模型名':
        "Couldn't fetch models: {error}. You can also type the model name yourself",
    # ui/vision.py
    '桌面魔镜 · 看图翻译':
        'DeskMirror · Image translation',
    '重新看一次':
        'Try again',
    '把魔镜框里的画面交给能看图的模型来读、来翻：适合漫画、艺术字、图片里的字。比实时翻译慢，结果只在这个窗口里，不存盘。':
        "Sends the picture inside the mirror to a vision model to read and translate. Good for comics, stylized lettering and text in pictures. Slower than live translation; the result stays in this window and isn't saved.",
    '正在看图…（{who}，通常几秒到十几秒）':
        'Reading the picture… ({who}, usually a few to 15 seconds)',
    '没看成：{error}':
        'Failed: {error}',
    '完成，用时 {secs:.1f} 秒。':
        'Done in {secs:.1f} s.',
    # vision.py
    '图片编码失败':
        "Couldn't encode the image",
    '还没有填写看图翻译的服务地址':
        'The image translation service address is empty',
    '还没有填写看图翻译用的模型':
        'The image translation model is empty',
    '看图翻译响应超时（多模态模型比较慢，可以稍后再试，或换一个快些的模型）':
        'Image translation timed out (vision models are slow; try again later, or use a faster model)',
    '连不上看图翻译的服务（服务没启动或地址不对）':
        "Can't reach the image translation service (it isn't running, or the address is wrong)",
    '看图翻译的连接中途断开':
        'The connection to the image translation service dropped',
    '模型 {model} 不能看图，请在设置里换一个能看图的模型':
        "The model {model} can't read images; choose one that can in Settings",
    '让截图工具截到魔镜（期间译文不更新）':
        'Let screenshot tools capture the mirror (translations pause meanwhile)',
    '截图模式：译文暂停更新':
        'Screenshot mode: translations paused',
    '截图模式：现在截图、录屏软件能截到魔镜和译文了。这期间译文不会更新，截完在托盘菜单或右键魔镜标签里关掉。':
        'Screenshot mode: screenshot and screen recording tools can now capture the mirror and its translations. '
        "Translations don't update meanwhile; when you're done, turn it off in the tray menu or by right-clicking "
        "the mirror's tab.",
    '已关闭截图模式：魔镜重新对截屏隐身，接着识别、翻译。':
        'Screenshot mode is off: the mirror is hidden from screen capture again and carries on translating.',
    '这台电脑上魔镜没能对截屏隐身，可能会把自己画的译文又当成原文识别。麻烦把程序文件夹里 logs 下的日志发给作者。':
        "On this PC the mirror couldn't hide itself from screen capture, so it may read its own translations as "
        'original text. Please send the files in the logs folder next to the program to the author.',
    '这台电脑（Windows 10）上底板总是不透明':
        'On this PC (Windows 10) the plates are always opaque',
}
