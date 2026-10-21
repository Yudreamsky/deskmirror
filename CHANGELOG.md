# 更新记录 / Changelog

## 未发布

- 魔镜标签上的 token 用量（↑ ↓）挪到标签最右头，鼠标停上去不再弹明细（去点按钮时一划过就弹，容易误触）：
  点一下才弹，再点一下或者鼠标移开就收起；像按钮一样，鼠标移上去有底色。

- The token usage on the mirror's tab (↑ ↓) moved to the right end of the tab, and hovering over it no longer pops
  up the details (it used to pop up whenever the pointer passed over it on the way to a button): click it to show
  them, click again or move away to close them. Like the buttons, it lights up under the pointer.

## 1.5.0（2026-10-21）

新增截图（Ctrl+1）和贴图（Ctrl+2）：鼠标停在哪就框住那里的窗口、按钮、段落，能标注、复制、保存、贴到屏幕、原位翻译，
还能一键把选区变成魔镜。设置窗口改版：左边分页、每页自己滚动，快捷键点一下、按新的组合键就录好。
托盘菜单重新排过，右键收起来的球弹出的也是它。

- **截图（Ctrl+1）**：每块屏幕先定格，鼠标停在哪就自动框住那里的一行字、一段文字、按钮、网页里的一块或者整个窗口，
  滚轮换大一层、小一层，点一下就选它；也能自己拖框，拖动、拖边角、方向键微调（Shift 一次 10 像素）。光标旁边有放大镜、
  坐标和颜色（C 复制颜色）。按钮、网页里的元素靠 Windows 的 UI Automation 找；文字段落由本机的识别进程只找位置、不认字。
- **标注**：矩形、椭圆、箭头、画笔、荧光笔、文字、序号、马赛克，可选颜色和粗细，能撤销、重做。
- **用掉它**：Enter（或 Ctrl+C、双击选区）复制，Ctrl+S 保存（文件夹和 PNG / JPG 在 设置 → 截图 里选），Ctrl+T 贴到屏幕。
  **识别文字**弹出一个能改、能复制的小窗口；**原位翻译**把选区里的字就地换成译文（和魔镜一样的底板和字体），能在原文、
  译文之间换，复制、保存、贴图的就是看到的样子；**变成魔镜**（M）把主魔镜挪到选区上、和选区一样大（收成球的就在那里展开），
  Shift+M 另开一个。截图界面关掉后，焦点回到截图前在用的窗口，复制完直接 Ctrl+V。
- **贴图（Ctrl+2）**：把剪贴板里的图（或文字，画成一张卡片）贴在鼠标那里，剪贴板里没有就把最近一次截图贴回原处。
  拖动挪位置，滚轮缩放，Ctrl+滚轮调透明度，双击或 Esc 关掉；右键还有原位翻译、原文译文来回换、识别文字、原始大小、
  关闭所有贴图。
- 截下的图只在点“保存”时才写进硬盘，贴图和最近 20 次截图只放在内存里。只有点“原位翻译”时，才把选区里识别出的字
  发给翻译服务（排除名单里的窗口先涂掉），图本身不发送。
- 默认的 Ctrl+1、Ctrl+2 会占掉 Excel 的“设置单元格格式”和浏览器切到第 1、2 个标签页；用不惯就在 设置 → 截图 里换一个
  或者清空。被别的软件占着时，托盘会提示没注册上。
- **设置窗口改版**：左边 11 页（常用、翻译服务、翻译范围、截图、输入框翻译、快捷键、用量与省钱、隐私与记忆、术语表、
  识别与显示、关于），原来 11 项挤在一页的“范围与隐私”拆成三页。窗口不再被最长的一页撑高（以前至少 759 像素，
  1080p 笔记本开 150% 缩放时保存按钮在屏幕外）。
- **快捷键点一下就能录**：点录入框再按新的组合键，被别的程序占着的也录得到、录的时候不会触发它；重复的、被占用的当场提示。
  设置窗口开着时，魔镜的快捷键先放开。
- **托盘菜单重新排**：天天用的（隐藏、暂停、刷新、截图、贴图、看图翻译、历史记录）在上面，快捷键写在右边；
  翻译范围、截镜框里的画面、帮助（新手指南、检查更新、关于）收进子菜单，顶层从 19 项减到 13 项；有贴图时才出现
  “关闭所有贴图”。**右键收起来的球**弹出的也是这个菜单，设置、退出都在里面。
- 魔镜标签上的截图按钮也按 设置 → 截图 里的文件夹和格式保存。

New screenshot (Ctrl+1) and pin (Ctrl+2) tools: the box snaps to the window, button or paragraph under the pointer,
and you can mark it up, copy, save, pin it on the screen, translate it in place, or turn the selection into a mirror
with one key. The settings window is redesigned with pages on the left that scroll on their own, and you set a hotkey
by clicking it and pressing the new combination. The tray menu is reorganized, and right-clicking the tucked-away
ball opens it too.

- **Screenshot (Ctrl+1)**: every screen freezes; wherever the pointer rests, a box snaps to the line or paragraph of
  text, the button, the block of a web page or the whole window under it. Scroll for the next larger or smaller one
  and click to take it, or drag your own box; move it, drag its edges or nudge it with the arrow keys (10 px with
  Shift). A magnifier next to the pointer shows the coordinates and the color (C copies the color). Buttons and web
  page elements are found through Windows UI Automation; paragraphs are located by the local recognition process,
  which doesn't read the text for this.
- **Marking up**: rectangle, ellipse, arrow, pen, highlighter, text, numbered marker and mosaic, with colors and
  widths, undo and redo.
- **Using it**: Enter (or Ctrl+C, or double-click the box) copies, Ctrl+S saves (folder and PNG / JPG under
  Settings → Screenshot), Ctrl+T pins it on the screen. **Recognize text** opens a small window where you can edit and
  copy the text; **Translate in place** replaces the text in the box with translations right where it is (the same
  plates and fonts as in the mirror) and switches between original and translation, and copying, saving and pinning
  take what you see; **Make it a mirror** (M) moves the main mirror onto the box at the same size (unfolding it there
  if it was a ball), and Shift+M opens another mirror. When the screenshot closes, the focus goes back to the window
  you were using, so Ctrl+V pastes right away.
- **Pin (Ctrl+2)**: the picture on the clipboard (or text, drawn as a card) is pinned at the pointer; with nothing on
  the clipboard, the latest screenshot is pinned back where it was taken. Drag to move it, scroll to zoom, Ctrl+scroll
  for opacity, double-click or Esc to close; right-click to translate it in place, switch between original and
  translation, recognize text, show it at actual size or close all pins.
- A screenshot is written to disk only when you save it; pins and the last 20 screenshots stay in memory. Only
  Translate in place sends anything out: the text recognized in the selection goes to the translation service
  (excluded windows are blanked first); the picture itself is never sent.
- The default Ctrl+1 and Ctrl+2 take over Excel's Format Cells and the browser's switch to tab 1 and 2; if that gets
  in your way, pick other keys or clear them in Settings → Screenshot. If another program already holds them, the tray
  tells you they couldn't be registered.
- **Redesigned settings window**: 11 pages on the left (General, Translation service, What to translate, Screenshot,
  Text boxes, Hotkeys, Usage and cost, Privacy and memory, Glossary, Recognition and display, About); the old
  "Scope and privacy" page with 11 items is split into three. The window is no longer as tall as the longest page (it
  used to be at least 759 px, which put the Save button off screen on a 1080p laptop at 150 % scaling).
- **Hotkeys are recorded with a click**: click the box and press the new combination; combinations held by other
  programs can be recorded too, without triggering them, and duplicates or taken combinations are flagged right away.
  DeskMirror's own hotkeys are released while the settings window is open.
- **Tray menu reorganized**: everyday items (hide, pause, refresh, screenshot, pin, image translation, history)
  come first, with their hotkeys on the right; What to translate, Screenshot of the frame and Help (Getting started,
  Check for updates, About) are submenus, so the top level is down from 19 items to 13; Close all pins shows up
  only while there are pins. **Right-clicking the tucked-away ball** opens the same menu, with Settings and Quit in
  it.
- The screenshot buttons on the mirror's tab also save to the folder and in the format set in Settings → Screenshot.

## 1.4.0（2026-10-12）

滚动时译文由 Windows 的系统合成器每一帧移动，和原文贴得住，不再一格一格地跳；跟踪本身也更快、更准。
新增安装程序：装在当前用户目录，不用管理员权限，开始菜单、卸载都有。

- **滚动时译文跟得更紧、更顺**：镜里的译文改交给 Windows 的系统合成器显示。同一块滚动区域里的译文挂在同一层上，
  滚动时魔镜算出接下来内容会怎么动（学到的滚轮曲线，或者按实测速度），交给系统，系统每显示一帧就把这一层挪到那一刻的位置：
  屏幕刷新多快，译文就跟多快，不再一格一格地跳。跟踪本身也更快、更准：每一帧按“这一帧显示出来的时刻”记时间（以前用截完屏的
  时刻，晚 3–7 毫秒还忽早忽晚）；正在滚的区域只取三条窄竖条、在预计的位移附近找，每帧省约 3 毫秒；量到新位移马上交给系统，
  不等这一帧其余部分处理完；滚轮每格多少像素取最近几次的中位数，一次算偏的不再把它带偏；连着快速滚时同时参考实测速度；
  内容一停译文就停，不再冲过头再弹回来。实测（Chrome，真滚轮）：普通滚动时译文和原文错开的中位数从 4–6 像素降到约 1.5 像素，
  九成时间在 6 像素以内（以前 13–20 像素）；快速连滚时最大的错开从约 90 像素降到约 45 像素。
- 有时整块屏幕每一帧都被报成“变了”（比如系统合成器里有东西在动）：这种帧先只细看魔镜附近和正在滚动的区域，
  其余部分最多隔 0.1 秒补看一次，跟踪不会被拖慢。
- Windows 10 的色键窗口照旧用原来的译文层。环境变量 `DESKMIRROR_GLIDE=0` 可以换回原来的译文层（`=1` 强制用新的，排查用）。
- **安装程序**：`DeskMirror-版本号-win64-setup.exe`，装在当前用户的 `%LOCALAPPDATA%\Programs\DeskMirror`（不用管理员权限，
  魔镜自己的“检查更新”照样能用），开始菜单、可选桌面快捷方式和开机自启；装新版本、卸载前先请正在运行的魔镜退出；
  卸载时问要不要删设置和日志，开机自启一起去掉。安装界面有简体、繁体中文、英文、日文、韩文。
  `python packaging\build.py --installer` 打出来（要 Inno Setup 6）。程序里更新完，“应用”里显示的版本号也跟着改。（#11）
- 打包脚本在 python.org 装的 Python 上也能用（以前只认 Anaconda 的 Python 许可证文件名）。

While you scroll, translations are now moved by the Windows compositor frame by frame, so they stay with the
original text instead of jumping in steps, and tracking itself is faster and more precise. There is also an
installer that sets DeskMirror up for the current user, without admin rights, with a Start menu entry and an
uninstaller.

- **Translations follow scrolling more closely and smoothly**: inside the mirror, translations are now shown by the
  Windows compositor. All translations of one scrolling area sit on one layer; while you scroll, DeskMirror works out
  how the content will move next (the learned wheel curve, or the measured speed) and hands that to Windows, which
  moves the layer for every frame it shows. Translations now keep pace with the screen's refresh rate instead of
  jumping in steps. Tracking itself is faster and more precise: frames are timed by when they are actually shown
  (instead of when the capture finished, which was 3–7 ms late and uneven); an area that is already scrolling is
  matched on three narrow strips around the expected offset (about 3 ms less per frame); a new offset goes to Windows
  right away; pixels per wheel notch is the median of recent scrolls, so one bad reading no longer skews it; fast
  continuous wheel scrolling also takes the measured speed into account; and when the content stops, translations stop
  too instead of overshooting and snapping back. Measured with a real mouse wheel in Chrome: during normal scrolling
  the median offset between translation and original dropped from 4–6 px to about 1.5 px and stays within 6 px 90 % of
  the time (was 13–20 px); during fast continuous scrolling the largest offset dropped from about 90 px to about 45 px.
- When the whole screen is reported as changed on every frame (for example while something in the compositor is
  moving), only the area around the mirror and the scrolling area are checked right away and the rest at most every
  0.1 s, so tracking does not slow down.
- Windows 10's colour-key windows keep the previous translation layer. Set the environment variable
  `DESKMIRROR_GLIDE=0` to go back to it (`=1` forces the new one, for troubleshooting).
- **Installer**: `DeskMirror-<version>-win64-setup.exe` installs for the current user in
  `%LOCALAPPDATA%\Programs\DeskMirror` (no admin rights; DeskMirror's own update check keeps working), with a Start
  menu entry, an optional desktop shortcut and optional autostart. Installing over it or uninstalling first asks a
  running DeskMirror to quit; uninstalling asks whether to delete settings and logs and removes the autostart. The
  setup wizard comes in Simplified and Traditional Chinese, English, Japanese and Korean. Built with
  `python packaging\build.py --installer` (needs Inno Setup 6). After an in-app update, the version shown under Apps
  is updated too. (#11)
- The build script also works with a python.org Python (it used to expect Anaconda's license file name).

## 1.3.0（2026-10-10）

魔镜拖到屏幕边缘就收成球、停止翻译，拖出来接着翻；新的液态玻璃皮肤，边框一圈像弧形玻璃一样折射后面的画面；可以开机自动启动，
启动后收成球待命；在别的软件的输入框里连按三次空格，把你打的母语换成外语。都照浏览器版 0.6.0–0.7.1 的做法（PR #10）。
英文软件的界面（工具栏、菜单、参数面板）也翻得更像原样了。

- **拖到边缘收成球**：标签左头加了六个点的抓手（整个标签照样能拖）。拖着魔镜让鼠标到了屏幕边缘，魔镜平滑地缩成一个球
  吸在边上，翻译停下（魔镜都收起来时不截屏、不识别、不花 token）；松手后球藏进边缘一半，鼠标移上去滑出来。按住球往外拖，
  离开边缘后变成虚线框跟着鼠标走，同时开始翻译、框里已经能看到译文，松手就落在那里；点一下球回到原来的地方。
  上下左右四条边都行，两块屏幕相接的边不收；顶边要把鼠标顶到最上沿才收。收没收起、球在哪会记住。（#8）
- **液态玻璃皮肤**：设置 → 识别与显示 → 显示 → 皮肤（命令行 `config set style.skin glass`），照浏览器版的样子。边框变成镜框外
  一圈圆角的弧形玻璃：后面的画面在这一圈里被拉宽、沿圆角弯过去（折射），边上一丝色散，外沿一道高光；标签是浮在边框上方的
  玻璃长条，球是玻璃球，后面是深色画面时自动换成烟灰玻璃。折射用的是识别时本来就要截的屏幕画面，只在边框后面的画面真的变了时
  重画那一块（大魔镜整圈重画约 3 毫秒，每秒最多 30 次）；Windows 10 的色键窗口里玻璃先和后面的画面混好再画，边缘一样平滑。
  默认还是经典样子，选回经典和原来完全一样。（#8）
- **开机自动启动**：设置 → 识别与显示 → 启动（默认关），命令行 `config set autostart true`。登录后魔镜收成球待命，
  点开或拖出来才开始截屏、识别（文字识别那时才准备，开机不拖慢）。写在 Windows 的启动项里，程序挪了地方会自己改路径。（#9）
- **输入框翻译**：在别的软件的输入框里用母语打完字，连按三次空格（或按 Ctrl+Alt+J），整个框换成外语（默认母语是英文时
  译成简体中文，否则译成英文）；再按换回原文，再按又换成译文，来回换不再请求。写回去用粘贴，聊天软件里自己另存内容的
  编辑器也会真的换掉；剪贴板用完放回原样，不进剪贴板历史。只听空格和修饰键，密码框不碰，原文和译文只放在内存里。
  默认关（设置 → 输入框翻译），默认不管浏览器（浏览器版自己会翻）、写代码的编辑器和命令行。
- **英文软件的界面**（拿英文版 Houdini 实测）：并排的按钮名不再框成一行一起翻，按字之间的大空隙拆开分别翻；图标下分两行写的
  名字合成一块再翻；字号按原文笔画估，同一列、同一排统一；照原文对齐（参数名右对齐、菜单左对齐、工具栏和标签页居中）；
  界面上的短标签不折行；底板取字周围最多的颜色，按钮和下拉框照着渐变画；菜单里的快捷键不翻。

Drag the mirror to the edge of the screen and it tucks away as a ball and stops translating; drag it out and it
carries on. A new liquid glass skin turns the border into a ring of curved glass that refracts what's behind it.
DeskMirror can start with Windows, waiting as a ball. And in any program's text box, press Space three times to turn
what you typed in your own language into another one. All of these follow the browser version 0.6.0–0.7.1 (PR #10).
The interfaces of English software (toolbars, menus, parameter panels) are translated more faithfully too.

- **Tuck it away at the edge**: the tab has a six-dot grip at its left end (the whole tab still drags). Drag the mirror
  until the mouse reaches the edge of the screen and it shrinks smoothly into a ball stuck to that edge, and translation
  stops (when every mirror is tucked away nothing is captured or recognized and no tokens are spent). Let go and the
  ball slides halfway into the edge; move the mouse onto it and it slides out. Drag the ball out and it opens into a
  dashed frame that follows the mouse, translation starts and translations already show inside; let go and it lands
  there. Click the ball to put the mirror back where it was. Any of the four edges works, except where two screens
  meet; the top edge only counts when you push the mouse all the way up. Whether it's tucked away, and where, is
  remembered. (#8)
- **Liquid glass skin**: Settings → Recognition and display → Display → Skin (or `config set style.skin glass`), in the
  style of the browser version. The border becomes a ring of curved glass around the frame with rounded corners: what's
  behind it is stretched across the ring and bent around the corners (refraction), with a faint colour fringe and a
  highlight along the outer edge. The tab is a strip of glass floating above the border and the ball is a glass ball;
  over dark backgrounds they turn smoky. The refraction uses the screen pictures DeskMirror captures for recognition
  anyway, and only the part of the border whose background really changed is redrawn (about 3 ms for the whole ring of a
  large mirror, at most 30 times a second). On Windows 10's colour-key windows the glass is blended with the background
  before it's drawn, so its edges stay smooth. The classic look is still the default and choosing it again gives exactly
  the old look. (#8)
- **Start with Windows**: Settings → Recognition and display → Startup (off by default), or `config set autostart
  true`. After you sign in the mirror waits as a ball and starts capturing and recognizing when you click it or drag it
  out (text recognition only gets ready then, so startup isn't slowed down). It's stored in Windows' startup list and
  follows the program if you move its folder. (#9)
- **Text box translation**: after typing in your own language in another program's text box, press Space three times
  (or Ctrl+Alt+J) to turn the whole box into another language (by default Simplified Chinese if your own language is
  English, otherwise English); press again for the original, and again for the translation, without new requests. The
  text goes back in by pasting, so editors in chat apps that keep their own copy really change too; the clipboard is
  put back afterwards and the borrowed paste stays out of clipboard history. It only listens to Space and modifier
  keys, never touches password boxes, and keeps the text in memory only. Off by default (Settings → Text boxes);
  browsers (the browser version handles those), code editors and terminals are left alone by default.
- **English software interfaces** (tested on English Houdini): buttons sitting side by side are no longer boxed into
  one line and translated together; they're split at the wide gaps and translated one by one. Names written on two
  lines under an icon are joined first. The font size follows the original strokes and stays the same along a column
  or row, and translations follow the original's alignment (parameter names right-aligned, menus left-aligned,
  toolbars and tabs centred). Short interface labels don't wrap; the plate takes the most common colour around the
  text, and buttons and drop-downs keep their gradient. Menu shortcuts aren't translated.

## 1.2.0（2026-10-08）

程序里就能检查并更新到新版本；所有设置都能用命令行改，AI 助手可以替你设置好；魔镜标签上显示 token 用量，还加了省钱保护；Windows 10 上不再把自己的译文当原文，还加了截图模式。

- **程序内更新**：托盘菜单、设置 → 关于里“检查更新”；启动后每天最多自动查一次（可以关掉，只向 GitHub 查版本号），有新版本在托盘提示。点“下载并更新”：下载、核对 SHA256，魔镜退出后换上新版本、自动重新打开，设置都留着，出错就换回旧版本。源码版用 git pull 更新。命令行 `update --check`、`update --yes`。（#5）
- **命令行改设置，AI 助手能替你设置好**：`DeskMirrorCLI.exe`（源码版 `python -m deskmirror`）能查看、修改全部设置（`config list / get / set / reset / keys`），换翻译服务（`service deepseek` 等）、列出模型、测试连接、管理术语表、看用量（`usage`）和状态（`status`）；加 `--json` 输出 JSON。超出范围、格式不对的值直接报错；API Key 从标准输入或环境变量（`--env`）读、只显示前后几位。正在运行的魔镜一秒内自动载入改动（以前直接改配置文件要先退出魔镜），说明里加了“让 AI 帮你设置”一节。（#4）
- **标签上显示 token 用量**：像网速监控那样显示今天的 ↑ 输入 ↓ 输出 token，鼠标停上去看明细（服务、模型、请求数、命中缓存的部分）。
  用量读服务商报回来的数（OpenAI 兼容接口请它在最后报，Ollama 自带），报不了的按字数估算并标“≈”。托盘提示、设置里的用量也有 token。（#6）
- **省钱保护**：好一会儿（默认 5 分钟）没碰键盘鼠标就只翻镜框里的，不在后台预译屏幕上别处的；锁屏、屏保时完全停下；云端服务一天的
  token 用到上限（默认 100 万，0 = 不限）就停止翻译新文字。有请求在途时，零星的新文字等一下（最多 0.6 秒）凑成一批再发：
  每次请求都带约 430 token 的固定说明，一两行字单独发，九成花在说明上。余额不足（HTTP 402）时说清楚、停下等充值。（#7）
- **用量日志**：每次翻译请求记一行到 `logs/usage-年-月.jsonl`（只有数量和程序名，不记屏幕上的字），命令行 `usage --log` 按程序、批大小、小时汇总，并给出缓存命中率。（#7）
- **Windows 10 上不再把自己的译文当原文**：Windows 10 不支持让半透明的窗口对截屏隐身，魔镜会截到自己画的译文、又翻一遍（日志里是“SetWindowDisplayAffinity 失败，错误码 8”）。现在启动时先试一下，不支持就改用色键窗口：看起来一样，鼠标操作也一样，只是底板总是不透明（这种电脑上设置里的“底板不透明度”不能调）。（#2）
- **截图模式**：别的截图、录屏软件截不到魔镜，因为魔镜自己也靠截屏看字，截得到自己就会把译文当原文。现在托盘菜单或右键魔镜标签里可以打开“让截图工具截到魔镜”：期间译文定住不更新，关掉后接着识别、翻译。标签上的“截原图 / 截译图”照样能用。（#2）
- **新手指南第 3 步能获取模型列表**：选云端服务时，填好 API Key 点“获取模型列表”，从服务商现有的模型里选，不用手填；换服务时不再留着上一家的模型名。（#3）
- **中文 Windows 上从源码安装不再失败**：依赖清单的注释改成英文，setup.bat、start.bat 让 Python 按 UTF-8 读写（以前 pip 按 GBK 读依赖清单就报错退出）。（#1）

DeskMirror can now update itself; every setting can be changed from the command line, so an AI assistant can
set it up for you; the mirror's tab shows token usage, with new cost guards; on Windows 10 it no longer reads its
own translations as original text; and there's a new screenshot mode.

- **Updating from inside the app**: "Check for updates" in the tray menu and in Settings → About; after starting,
  DeskMirror checks at most once a day (can be turned off; it only asks GitHub for the version number) and announces a
  new version in the tray. "Download and update" downloads and verifies it (SHA256), then DeskMirror quits, switches
  to the new version and reopens with your settings intact; if anything goes wrong the previous version is put back.
  From source it updates with git pull. Command line: `update --check`, `update --yes`. (#5)
- **Settings from the command line, so an AI assistant can set it up for you**: `DeskMirrorCLI.exe` (from source:
  `python -m deskmirror`) reads and changes every setting (`config list / get / set / reset / keys`), switches the
  translation service (`service deepseek` and others), lists models, tests the connection, manages the glossary and
  shows usage (`usage`) and status (`status`); add `--json` for JSON output. Out-of-range or malformed values are
  rejected; API keys are read from standard input or an environment variable (`--env`) and only shown in part. A
  running DeskMirror picks up the changes within a second (editing the settings file used to require quitting it
  first), and the README has a new "Let an AI assistant set it up" section. (#4)
- **Token meter on the tab**: today's ↑ input ↓ output tokens, like a network monitor; hover for details (service,
  model, requests, cached input). Uses the counts the service reports (OpenAI-compatible services are asked to report
  them; Ollama always does) and estimates from text length otherwise, marked "≈". The tray tooltip and Settings show
  tokens too. (#6)
- **Cost guards**: after a while without keyboard or mouse input (5 minutes by default) only text inside the mirror is
  translated; everything stops while the screen is locked or the screensaver runs; cloud services stop translating
  new text at a daily token cap (1,000,000 by default, 0 = unlimited). While a request is in flight, stray new lines
  wait up to 0.6 s and go out as one batch: every request carries about 430 tokens of fixed instructions. HTTP 402
  (insufficient balance) is reported clearly and stops until you top up. (#7)
- **Usage log**: one line per translation request in `logs/usage-YYYY-MM.jsonl` (counts and program names only, no
  screen text); `usage --log` on the command line sums it up by program, batch size and hour, with the cache hit
  rate. (#7)
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
