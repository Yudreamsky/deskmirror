[English](README.md) · [简体中文](README.zh-CN.md) · **繁體中文** · [日本語](README.ja.md) · [한국어](README.ko.md) · [Bahasa Indonesia](README.id.md)

# 桌面魔鏡 DeskMirror

Windows 上的螢幕翻譯工具：在桌面上放一塊可以拖曳的「鏡子」，鏡框裡同一位置的文字換成譯文，鏡框外照常是你的桌面。
網頁、PDF、軟體介面、遊戲和影片字幕都用同一種方式運作，不需要瀏覽器擴充功能。

![魔鏡滑到遊戲的對話框上，框裡的日文換成了中文](docs/images/hero-zh.gif)

第一次用？看[新手指南](docs/QUICKSTART.md)（程式第一次啟動時也會彈出同樣的指南），更多用法見[使用說明](docs/GUIDE.md)。兩份文件目前是簡體中文。

## 效果

兩分半鐘的介紹影片（簡體中文版）：

https://github.com/user-attachments/assets/3a04cbfd-9331-4180-9e04-9c29c09e237e

桌面魔鏡在本專案測試頁上的實錄截圖（翻譯服務：DeepSeek；圖中的譯文是簡體中文，母語選繁體中文時譯文就是繁體）：

| 網頁 | 影片字幕 |
|---|---|
| ![英文網頁，魔鏡裡換成了中文](docs/images/web-zh.jpg) | ![英文字幕的影片，魔鏡裡的字幕換成了中文](docs/images/video-zh.jpg) |
| **視窗化的遊戲** | **PDF** |
| ![日文遊戲：任務、選單、倒數計時、名牌和對話都換成了中文](docs/images/game-zh.jpg) | ![英文 PDF，魔鏡裡的摘要換成了中文](docs/images/pdf-zh.jpg) |

**漫畫**：對話框裡的直排文字直接辨識，中文譯文也直排在原位，對話框的邊框完整保留。

<img src="docs/images/manga-zh.jpg" width="560" alt="日文漫畫：對話框和旁白都換成了中文">

## 特色

- **原位顯示**：譯文貼在原文的位置，字級、顏色盡量和原文一致；按住 Ctrl+Alt+O 隨時看原文。
- **跟得上畫面**：捲動、視窗移動、遮擋、影片裡的字幕都跟得上。依畫面變化判斷，不依賴特定軟體。
- **背景預先翻譯**：魔鏡所在螢幕上的文字提前翻譯，拖到哪裡馬上顯示；看過的內容不會重複翻譯。
- **翻譯服務任選**：本機 [Ollama](https://ollama.com)（免費，文字不離開本機），或 DeepSeek、通義千問、OpenAI 等 OpenAI 相容介面。
- **隱私可控**：不翻譯名單（預設排除聊天軟體、密碼管理工具、網路銀行；和外國同事聊天時一鍵開啟「翻譯聊天軟體」）、三種預先翻譯範圍、當天用量統計；螢幕上的文字預設不存檔。
- **語言隨時切換**：魔鏡標籤上的語言按鈕（如「英→中」）手動指定原文和譯成的語言；支援中文、英文、日文、韓文、印尼文。
- **中英文介面**：第一次啟動先選母語，譯文就用這種語言。選繁體中文時介面是簡體中文（還沒有繁體介面），選其他語言時介面是英文；之後可在設定裡隨時更改。
- **術語**：術語表裡的詞一定照用；沒寫進術語表的詞也盡量前後一致。字幕和遊戲對話會帶上前幾句當上下文，人稱、語氣更連貫。
- **放得下**：譯文比原文長時，先橫向壓扁一點，再借用旁邊的空白，最後才縮小字級；不會超出面板邊框，不蓋住圖片和影片畫面。
- **漫畫**：對話框裡的直排文字直接辨識，中日文譯文也直排在原位，英文在對話框裡置中。
- **看圖翻譯**：按 Ctrl+Alt+V 或點標籤上的「看圖」，把鏡框裡的畫面交給能看圖的模型來讀、來翻（預設是本機 Ollama 的 gemma4:12b），適合藝術字、狀聲詞、圖片裡的字。
- 還有：歷史面板、修改譯文、多個魔鏡、魔鏡跟隨視窗、暫停、截圖、程式內更新。

## 安裝

需要：

- Windows 11（Windows 10 應該也可以，但還沒測試過）
- 翻譯服務，二選一：
  - 本機：安裝 [Ollama](https://ollama.com)，再執行 `ollama pull gemma4:12b`（模型約 7.6 GB，需要顯示記憶體較大的獨立顯示卡）
  - 雲端：DeepSeek 等服務的 API Key（依用量計費）

### 下載即用（推薦）

1. 在 [Releases](https://github.com/Yudreamsky/deskmirror/releases/latest) 下載 `DeskMirror-版本號-win64.zip`（約 140 MB）。
2. 解壓縮到任意資料夾（例如「文件」或 D 槽），按兩下裡面的 `DeskMirror.exe`，照新手指南設定好就能用。
   - Windows 可能顯示「Windows 已保護您的電腦」（程式沒有付費的程式碼簽章）：點「其他資訊」→「仍要執行」。
   - 設定和記錄檔都存在這個資料夾裡；換新版本時，把新版解壓縮到同一位置覆蓋即可，設定會保留。
   - 不要解壓縮到 C:\Program Files（那裡無法寫入設定，會改存到 `%LOCALAPPDATA%\DeskMirror`）。
3. 不需要安裝 Python；文字辨識模型（含韓文）都在壓縮檔裡。

### 從原始碼執行

1. 安裝 [Python 3.12](https://www.python.org/downloads/)（安裝時勾選「Add python.exe to PATH」）。
2. 下載本專案：`git clone https://github.com/Yudreamsky/deskmirror.git`，或在 GitHub 頁面下載 ZIP 解壓縮。
3. 按兩下 `setup.bat`：建立 `.venv` 並安裝相依套件（PySide6、RapidOCR、ONNX Runtime 等，需要連網）。
4. 按兩下 `start.bat`。文字辨識模型會隨套件一起裝好；第一次選「原文：韓文」時，會自動下載韓文辨識模型（約 14 MB）。
5. 自行封裝 exe：`.venv\Scripts\python -m pip install -r requirements-build.txt`，再執行 `.venv\Scripts\python packaging\build.py`。

使用雲端服務：在新手指南第 3 步選「雲端服務」，或點魔鏡標籤上的 ⚙ → 翻譯服務，選「OpenAI 相容介面」，填入位址、模型和 API Key，點「測試連線」。

文字辨識預設使用顯示卡（DirectML，支援 DirectX 12 的顯示卡都可以），沒有合適的顯示卡時自動改用 CPU。

## 使用

第一次啟動會彈出新手指南（第 1 步選母語；之後隨時可從系統匣選單再開啟），詳見[新手指南](docs/QUICKSTART.md)和[使用說明](docs/GUIDE.md)。常用操作：

| 想做的事 | 怎麼做 |
|---|---|
| 移動、調整魔鏡 | 拖曳魔鏡上方的標籤；拖曳藍色邊框 |
| 暫時看原文 | 按住 Ctrl+Alt+O |
| 隱藏 / 顯示魔鏡 | Ctrl+Alt+H |
| 回看剛才的字幕、對話 | Ctrl+Alt+Y 開啟歷史面板 |
| 暫停（框留著，不辨識、不翻譯） | 點標籤上的「暫停」 |
| 指定語言（例如英→中、印尼→中、中→印尼） | 點標籤上的語言按鈕 |
| 翻譯聊天軟體（和外國同事、朋友聊天時） | 在標籤或系統匣圖示上按右鍵 → 勾選「翻譯聊天軟體」 |
| 看圖翻譯（漫畫、藝術字、圖片裡的字） | Ctrl+Alt+V，或點標籤上的「看圖」 |
| 設定 | 點標籤上的 ⚙，或在系統匣圖示上按右鍵 |
| 更新到新版本 | 在系統匣圖示上按右鍵 →「檢查更新…」 |

### 用量和省錢

- 魔鏡標籤上的 `↑12.3k ↓4.1k` 是今天傳給翻譯服務的 token（↑ 輸入、↓ 輸出），滑鼠停在上面可看明細，包括命中服務商快取的部分。
- 每次請求都會附帶約 430 token 的固定說明，所以最省的做法是少發零碎的小請求：已有請求在途時，零星的新文字會稍等一下、湊成一批再送出；
  預先翻譯範圍選「只翻魔鏡所在的視窗」或「只翻鏡框附近」，比「整個螢幕」省得多。
- 一段時間沒碰鍵盤滑鼠就只翻鏡框裡的文字，鎖定畫面、螢幕保護程式執行時完全停下；雲端服務預設一天最多用 100 萬 token，到了就停。這些都在 設定 →「範圍與隱私」裡調整。
- 每次請求都記在 `logs/usage-年-月.jsonl`（只有數量和程式名稱，沒有螢幕上的文字）；命令列的 `usage --log`（見下一節）
  會按程式、批次大小、小時彙總，看看錢花在哪裡。

## 讓 AI 幫你設定

所有設定也都能用命令列修改，Claude Code、Codex 這類 AI 助理可以替你從頭設定好。改完後，正在執行的魔鏡一秒內自動生效。

- 下載版：DeskMirror 資料夾裡的 `DeskMirrorCLI.exe`；原始碼版：`.venv\Scripts\python -m deskmirror`。
- `config keys` 列出每項設定的說明和可用的值；`config list`、`config get`、`config set`、`config reset` 查看和修改；`service`、`models`、`test` 切換翻譯服務、列出模型、測試能不能用；`usage` 查看今天用了多少 token，`status` 查看魔鏡是否正在執行。加上 `--json` 輸出 JSON。
- API Key 從標準輸入（`config set llm.api_key -`）或環境變數（`config set llm.api_key --env DEEPSEEK_API_KEY`）讀取，不會留在命令列裡；以 Windows 帳戶加密儲存，任何時候都只顯示成 `sk-…1234`。

例如換成 DeepSeek、譯成繁體中文：

```bat
DeskMirrorCLI.exe service deepseek
DeskMirrorCLI.exe config set llm.api_key -
DeskMirrorCLI.exe config set target_lang zh-Hant first_run_tip false
DeskMirrorCLI.exe test
```

（第二行會請你貼上 API Key，輸入時不顯示。）也可以直接對 AI 助理說：

> 幫我設定桌面魔鏡：程式在 D:\DeskMirror，先執行 `DeskMirrorCLI.exe --help` 和 `DeskMirrorCLI.exe config keys --json` 看看能設定什麼。翻譯服務用 DeepSeek（API Key 我給你，用 `config set llm.api_key -` 傳入），譯成繁體中文，最後用 `DeskMirrorCLI.exe test` 測試一下。

## 隱私

- 使用雲端翻譯服務時，螢幕上辨識出的文字和視窗標題會傳送給該服務。若在意，請使用本機 Ollama，或在設定裡縮小預先翻譯範圍、加入不翻譯的程式。
- API Key 以目前的 Windows 帳戶加密（DPAPI），儲存在本機的 `deskmirror.json`。
- 記錄檔只記錄耗時和數量，不記錄螢幕上的文字（每次請求的用量記錄還會記下文字在哪個程式裡）。「記住譯文」預設關閉，開啟後才會把譯文加密存在本機。
- 看圖翻譯會把鏡框裡的截圖傳給設定裡的看圖模型。預設是本機 Ollama，畫面不離開本機；改用雲端服務時，每次傳送圖片前都會先詢問你。
- 檢查更新：啟動後每天最多一次向 GitHub 查詢最新版本號和更新說明，不傳送任何螢幕內容；按了才會下載。可以在設定 →「範圍與隱私」裡關閉。

## 已知限制

- 目前只在一台電腦上測試過（Windows 11、3840×2160 / 100% 縮放、RTX 4090）。
- 獨占全螢幕的遊戲、有版權保護的影片畫面無法覆蓋或擷取；遊戲請改用無邊框或視窗模式。
- 藝術字、像素字型、很小的字可能辨識錯誤。直排文字要像漫畫對話框那樣一行行排整齊才辨識得好，斜著排的狀聲詞請用看圖翻譯。韓文要在語言按鈕裡選「原文：韓文」（改用韓文辨識模型）。
- 更多內容見[使用說明](docs/GUIDE.md#已知限制)。

## 開發

```bat
:: 單元測試（不需要螢幕和模型）
.venv\Scripts\python.exe -m unittest discover -s tests -t .

:: 帶主控台視窗執行，查看記錄
start.bat debug
```

## 授權條款

[GPL-3.0](LICENSE)。Copyright © 2026 Yudreamsky。

使用的第三方元件和它們的授權條款見 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 聯絡

a885187@gmail.com

桌面魔鏡免費開源，所有功能都能用。如果它幫上了你的忙，可以在程式的「關於 → 打賞作者」裡掃碼請作者喝杯咖啡，或使用 [Ko-fi](https://ko-fi.com/dreamskyu)。
