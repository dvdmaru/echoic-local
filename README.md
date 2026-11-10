# Echoic 本機版

開完會，在自己的電腦把錄音轉成**台灣正體逐字稿**：分好誰在說話、每一段都有時間戳。想要的話，再用你自己的 Claude 整理成摘要（決議、待辦、數字表）。

- **預設錄音與逐字稿不出你的電腦**：語音辨識（whisper.cpp）和說話人分離（sherpa-onnx）都在本機跑，沒有雲端轉錄、沒有月費。
- **線上語音辨識是選用的**：想讓電腦少做一點，可以自己填一個線上服務（OpenAI、Groq 或自架的 whisper 伺服器）。選了就會**把錄音上傳到那個服務**，要不要相信它由你決定（說明見下）。
- **摘要是選用的**：預設關。打開後才會把逐字稿送進**你自己登入的 Claude Code**，會用到你 Claude 方案的額度（說明見下）。
- 目前只有 **Mac（Apple Silicon，M 系列晶片）** 版。Windows 版開發中。

程式代號是 `meeting-local`（指令名稱、設定變數都用這個）。

> **錄音之前，請先取得與會者同意。** 這個工具只負責轉錄，錄不錄、怎麼保存，責任在使用者。

## 安裝（Mac）

1. 到 [Releases](../../releases/latest) 下載 `EchoicLocal-mac-arm64.dmg`，打開後把「Echoic 本機版」拖到「應用程式」。
2. **第一次開啟會被 macOS 擋**：App 沒有付費的 Apple 公證，用瀏覽器下載的版本第一次雙擊時，macOS 會說「無法打開」，只給「丟到垃圾桶」和「完成」。請按**「完成」**（不要丟到垃圾桶），再三選一：
   - **系統設定**：「系統設定 → 隱私權與安全性」往下捲到「安全性」，按**「仍要打開」**（Open Anyway），輸入密碼後再按「打開」。macOS 14 以前也可以對 App 按右鍵 →「打開」，macOS 15 起這條捷徑沒了。
   - **已經裝好了**：終端機跑 `xattr -dr com.apple.quarantine "/Applications/Echoic 本機版.app"` 再雙擊。
   - **不經過瀏覽器直接裝**：`curl -fsSL https://echoic.twtools.cc/install.sh | bash`（下載最新版、比對 SHA-256、裝進「應用程式」再打開；想先看內容就把腳本存下來 `less` 過再 `bash`）。用 curl 下載的檔案不會被標成「從網路下載」，所以不會被擋。
   之後從 App 裡更新（右下角「檢查更新」）也不會再被擋。
3. 允許麥克風權限。
4. 按「下載語音辨識模型」（約 1.6 GB，從 Hugging Face 官方下載並比對 SHA256）。裝過「[看懂 KanDong](https://kandong.twtools.cc)」的人通常不用再下載，兩個工具共用同一個模型資料夾 `~/.cache/twtools/models/`。

### 錄線上會議（對方的聲音）

macOS 要先裝虛擬音源把系統聲音繞回來：

1. 安裝 [BlackHole 2ch](https://existential.audio/blackhole/)。
2. 打開「音訊 MIDI 設定」→ 左下 `+` →「建立多重輸出裝置」，勾 **BlackHole 2ch** 和你實際聽的喇叭或耳機。
3. 開會時把系統輸出選成這個多重輸出裝置，App 的錄音來源選「兩者都錄」。

實體會議直接選「只錄麥克風」即可。

## 用法

1. 選錄音來源、（選填）會議名稱與與會者，按「開始錄音」，結束按「停止」。
2. 按「轉逐字稿」。M4 MacBook Air 實測：語音辨識每小時錄音約 4～8 分鐘，說話人分離另外再約 7 分鐘。轉的時候視窗和其他程式照常能用（0.4.0 起說話人分離改在獨立程序跑，以前會讓視窗一次凍住半分鐘以上）。
3. 按「開啟資料夾」看結果。

**與會者**有填就照人數分離說話人，最準；摘要也會依內容推定誰說了什麼。

### 更新

安裝版右下角有「檢查更新」：有新版時按一下，App 會從 GitHub 下載、比對 SHA-256，關閉後換成新版並自動重開，會議資料、設定、模型都不動。勾著「自動」時每天最多查一次（只連 GitHub，不送任何會議內容）。從原始碼跑的話 `git pull` 就是更新。

### 轉的時候不想讓電腦變慢：背景模式

勾「本機背景模式」：語音辨識和說話人分離都降低優先權、少用核心，其他程式更不受影響，代價是比全速多花約 4 成時間（30 分鐘的會議 366 秒 → 515 秒）。適合開完會丟著讓它跑。語音辨識主要靠 GPU，這段兩種模式一樣快；想讓電腦完全不做這件事，見下面的線上語音辨識。

指令列：`meeting-local config --speed background|fast`；`--speed` 也可以只蓋過這一次。

### 線上語音辨識（選用，會上傳錄音）

按「線上 API 設定…」，填網址、模型和 API key，任何 OpenAI 相容的 `/audio/transcriptions` 都可以：

| 服務 | 網址 | 模型 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `whisper-1` |
| Groq | `https://api.groq.com/openai/v1` | `whisper-large-v3` |
| 自架（faster-whisper、whisper.cpp 伺服器等） | 你的伺服器網址 | 伺服器支援的模型名 |

- **錄音會上傳到你填的服務**，上傳後怎麼保存、會不會拿去訓練，依那個服務的條款而定。公司或客戶的會議，請先確認可以交給第三方處理。選線上時 App 會再問你一次。
- 費用依服務按分鐘計，請看服務自己的價目表。
- 長會議會切成約 10 分鐘一段上傳（多數服務單檔上限 25 MB），切點挑最安靜的地方。
- API key 只存在這台電腦（`~/.config/echoic-local/stt-api-key`，只有你的帳號讀得到），不寫進設定檔、log 或 `run.json`。
- 說話人分離、詞彙表、轉台灣正體照樣在本機做。
- 每場用的是哪個引擎記在 `run.json` 的 `models_touched.stt`。

指令列：

```bash
meeting-local config --api-url https://api.groq.com/openai/v1 --api-model whisper-large-v3
meeting-local config --set-api-key          # 不會顯示，也不會留在 shell 歷史
meeting-local config --engine api            # 之後預設用線上；--engine local 改回本機
meeting-local all <音檔> --engine local      # 只蓋過這一次
```

### 摘要（選用）

勾選「轉完逐字稿後，自動用 Claude 產生摘要」，或對單場按「產生這場摘要」。需要先安裝 [Claude Code](https://docs.claude.com/en/docs/claude-code) 並登入一次。

- 摘要會用到**你自己 Claude 方案的用量**。一小時的會議大約送出 4～5 萬字、拿回約 1 萬字（專名候選表與摘要各一次）。
- 用 Pro（每月 US$20）方案時，一天做好幾場長會議可能比較快碰到用量上限，所以預設不自動做。
- 沒裝 Claude Code 也能用，只是只出逐字稿。

指令列：`meeting-local config --auto-summary on|off`；`meeting-local all <音檔> --summary` 或 `--no-summary` 可以只蓋過這一次。

### 常錯的專有名詞：詞彙表

輸出資料夾根目錄有一份 `詞彙表.md`（第一次轉錄時自動放範本）。一行一條：

```
- 正確寫法｜逐字稿常見錯寫（用、分開）｜備註
```

之後每場：正確寫法會進語音辨識的提示、已知錯寫在逐字稿直接換掉、摘要也照這裡寫。1 個字的錯寫不自動換（誤殺風險高）。

## 輸出（每場一個資料夾）

預設放在 `~/Downloads/meetings/<YYYY-MM-DD-HHMM>/`（`MEETING_LOCAL_OUT` 可改）。整個資料夾可以直接當 Obsidian vault 開，`會議索引.md` 會自動更新。

| 檔案 | 內容 |
|---|---|
| `audio.wav` | 錄下來的原檔（16 kHz mono），不會被改動 |
| `transcript.srt` | 逐字稿（去重、台灣正體、`[SPEAKER_xx]` 前綴） |
| `transcript-by-minute.txt` | 逐分鐘、同一人連續發言合併，人讀和摘要都用這份 |
| `speakers.json` | 說話人分離結果與每人發言秒數 |
| `entities.md` | 專名候選表（有做摘要才有） |
| `summary.md` | 一句話／決議／待辦／數字表／未確認專名／品質註記，每條附時間戳（有做摘要才有） |
| `run.json` | 錄音裝置、音量、耗時、碰過哪些模型 |
| `whisper-server.log`、`ffmpeg.log` | 出問題時先看這兩個 |
| `stt-api/` | 用線上語音辨識時，每段的原始回應（音檔切片傳完就刪） |

有做摘要時，資料夾會改名成 `<時間戳>-<模型取的標題>`；會議名稱有自己填就保留你的名字。

## 從原始碼執行

```bash
git clone <這個 repo> && cd <資料夾>
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
brew install ffmpeg whisper-cpp   # Apple Silicon 版 Homebrew
.venv/bin/meeting-local doctor
.venv/bin/meeting-local ui
```

自己打包 `.app`／`.dmg`：`scripts/build-macos-app.sh`（會從官方原始碼建 whisper.cpp `v1.9.5` 與 FFmpeg `n9.0.2`，版本與 commit 都鎖在 `scripts/build-macos-deps.sh`）。

測試：`.venv/bin/python -m pytest -q`

### 模型與共用資料夾

`meeting_local/models-catalog.json` 是和「看懂」共用的模型清單：檔名、官方網址、SHA256、大小。規則：

- 兩個工具都會掃 `~/.cache/twtools/models/`（`TWTOOLS_MODELS` 可改），下載也存在這裡。
- 檔名＋SHA256 相同就是同一顆。Whisper large-v3-turbo 的未量化版與 q5_0 版都能用；本工具偏好未量化版，只有 q5_0 時照樣用。
- 下載先寫 `<檔名>.part`，比對 SHA256 後才改名；`.part` 60 秒內有寫入就當作另一個程式正在下載，不重開一份。

## 已知限制

- **不做即時字幕**，只做會後批次。16 GB 記憶體的機器開著很多 Chrome 分頁時，語音辨識會變慢，轉錄前會提醒。
- 本機語音辨識主要用 GPU，轉的時候 GPU 會接近滿載；實測不太拖累別的程式畫畫面，但重度用 GPU 的工作（剪片、遊戲）會一起變慢。
- 線上語音辨識各家回傳的時間軸精細度不同；只回整段文字、不給分段時間的服務，那一段只會有一個時間戳。
- whisper 在靜音或雜音段會一直重複同一句。程式把連續 3 段以上相同的合併成 `[幻覺，已略]` 並留痕。VAD 預設關（小聲的錄音會被 VAD 當成靜音整段丟掉），關 VAD 時固定帶 `-mc 0` 壓低重複；轉錄前先做響度正規化，原檔不動。
- whisper.cpp 偶爾輸出不合法的 UTF-8（一個中文字只吐出一部分 byte）。程式會丟掉殘缺字元並在 log 報數量；剛好跨段界的會接回下一段開頭。解碼前的原樣留在 `transcript.raw.bytes.srt`。
- 同一場會議同時只讓一個程序處理：工作資料夾會放 `.meeting-local.lock`，另一個程序撞到會直接說是誰在處理。
- 說話人分離只給 `SPEAKER_00／01…`，同一人音色變化大或多人重疊講話時會分錯。知道人數就填與會者或用 `--speakers N`；分得不好可以只重跑分離：`meeting-local diarize <資料夾> --speakers N`。
- 說話人分離的 embedding 模型以中文語料訓練，英文為主的會議效果較差。
- 同音的專有名詞會寫錯（例：輝達→揮達）。摘要不會自己猜，請收進 `詞彙表.md`。

## 授權

程式碼採 [MIT](LICENSE)。內附與下載的第三方元件見 [THIRD_PARTY.md](THIRD_PARTY.md)。
