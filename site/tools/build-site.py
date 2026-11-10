"""產生 echoic.twtools.cc 的靜態頁。要改內容就改這支再重跑，不要手改 public/ 裡的 HTML。

    python3 site/tools/build-site.py

GA4 評估 ID 預設是 echoic.twtools.cc 的資料串流（Charlie 2026-11-01 建）；ECHOIC_GA_ID 可覆蓋，設成空字串就不放追蹤碼。
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"
INSTALL_SH = Path(__file__).resolve().parent / "install.sh"  # 一行安裝腳本：原稿在這裡，public/ 是複本
BASE = "https://echoic.twtools.cc"
NAME = "Echoic 本機版"
REPO = "https://github.com/dvdmaru/echoic-local"
DMG = "EchoicLocal-mac-arm64.dmg"
DOWNLOAD = f"{REPO}/releases/latest/download/{DMG}"
RELEASES = f"{REPO}/releases/latest"
VERSION = "0.5.0"
DATE = "2026-11-10"
GA_ID = os.environ.get("ECHOIC_GA_ID", "G-80DLMF08HF").strip()
KANDONG = "https://kandong.twtools.cc/"
CLAUDE_CODE = "https://docs.claude.com/en/docs/claude-code"
BLACKHOLE = "https://existential.audio/blackhole/"

TAGLINE = "會議錄音，在自己的 Mac 上變成逐字稿"
DESC = ("Echoic 本機版是免費開源的會議逐字稿工具：在自己的 Mac 上把會議錄音轉成台灣正體逐字稿，分好誰在說話、每段有時間戳，"
        "預設錄音不上傳。想要摘要，再用你自己登入的 Claude 產生。目前支援 Apple Silicon Mac。")

ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
        "%3Crect width='32' height='32' rx='8' fill='%230f5c57'/%3E"
        "%3Cg fill='%23ffd166'%3E%3Crect x='6' y='13' width='3' height='6' rx='1.5'/%3E"
        "%3Crect x='11' y='9' width='3' height='14' rx='1.5'/%3E%3Crect x='16' y='6' width='3' height='20' rx='1.5'/%3E"
        "%3Crect x='21' y='10' width='3' height='12' rx='1.5'/%3E%3C/g%3E%3C/svg%3E")

FAQ = [
    ("要錢嗎？",
     "不用。Echoic 本機版是 MIT 授權的開源軟體，語音辨識與說話人分離預設都在你的電腦上執行，沒有月費。"
     "摘要是選用功能，用的是你自己的 Claude 方案；自己選用線上語音辨識時，費用依你選的服務計。"),
    ("錄音會被上傳嗎？",
     "預設不會。錄音、逐字稿都只存在你的電腦（預設在「下載項目」的 meetings 資料夾）。只有你打開摘要功能時，"
     "逐字稿文字才會送進你自己登入的 Claude Code。0.4.0 起可以自己選線上語音辨識，選了就會把錄音上傳到你填的服務，"
     "App 會先提醒你；沒選就一律不送。下載軟體與模型仍需要網路；安裝版每天最多向 GitHub 查一次有沒有新版（不含任何會議內容），"
     "App 右下角取消「自動」就不會查。"),
    ("摘要會吃掉我的 Claude 額度嗎？",
     "會，所以預設關。一小時的會議大約送出 4～5 萬字、拿回約 1 萬字（專名候選表與摘要各一次）。"
     "用 Pro（每月 US$20）方案時，一天做好幾場長會議可能比較快碰到用量上限。你可以只出逐字稿，想要哪一場的摘要再單獨按一次。"),
    ("沒有 Claude 可以用嗎？",
     "可以。沒裝 Claude Code 時只會產出逐字稿、說話人與時間戳，其他功能都一樣。"),
    ("為什麼 macOS 說「無法打開」，只給「丟到垃圾桶」？",
     "因為這個 App 沒有付費的 Apple 公證，用瀏覽器下載的版本第一次打開會被 macOS 擋下來，不是 App 壞掉或有毒。"
     "請按「完成」，不要按「丟到垃圾桶」，再從安裝教學的三種做法挑一種：系統設定按「仍要打開」、終端機一行指令解除，或用一行指令直接安裝。"
     "App 是開源的，安裝檔都附 SHA-256 可以自己比對。"),
    ("我的電腦能用嗎？",
     "目前只有 Apple Silicon（M1 以後）的 Mac 版，macOS 13 以上。Windows 版開發中。語音辨識模型約 1.6 GB，"
     "執行時建議至少 16 GB 記憶體；同時開很多 Chrome 分頁會變慢。"),
    ("要多久？",
     "M4 MacBook Air 實測 17 場會議：語音辨識每小時錄音多半要 4～6 分鐘，說話人分離另外約 7 分鐘。實際時間依錄音長度、電腦與同時開的程式而定。"),
    ("轉逐字稿的時候電腦會卡嗎？",
     "0.4.0 起，轉的時候視窗和其他程式照常能用（說話人分離改在獨立程序跑，以前會讓視窗一次凍住半分鐘以上）。"
     "語音辨識主要用 GPU，剪片、遊戲這類重度用 GPU 的工作會一起變慢。想再讓出一點資源，可以勾「本機背景模式」，代價是多花約 4 成時間。"),
    ("可以用線上的語音辨識嗎？",
     "可以，0.4.0 起是選用功能、預設關。按「線上 API 設定…」填任何 OpenAI 相容的服務（OpenAI、Groq 或自己架的 whisper 伺服器）與 API key。"
     "選了就會把錄音上傳到那個服務，上傳後怎麼保存、會不會拿去訓練依該服務的條款而定；公司或客戶的會議請先確認可以交給第三方。"
     "API key 只存在你的電腦，說話人分離與轉台灣正體仍在本機做。"),
    ("可以錄 Google Meet、Teams、Zoom 嗎？",
     "可以錄你的麥克風和電腦播出的聲音。錄對方的聲音要先裝免費的 BlackHole 虛擬音源，並在「音訊 MIDI 設定」建立多重輸出裝置，步驟在安裝教學。"
     "不管錄什麼，都請先取得與會者同意。"),
    ("有即時字幕嗎？",
     "沒有。Echoic 本機版只做會後批次轉錄：錄完再轉，換來的是預設不用連網、不用月費。"),
    ("逐字稿準嗎？",
     "語音辨識難免出錯，尤其是同音的專有名詞（例如「輝達」寫成「揮達」）。常錯的詞收進「詞彙表」一次，之後每場會自動修正。"
     "說話人分離在多人同時講話時也會分錯；知道與會人數就填進去，會準很多。重要內容請回聽原音，每一段都有時間戳。"),
    ("和「看懂 KanDong」有什麼關係？",
     "兩個都是 twtools 的免費本機工具，共用同一顆語音辨識模型（存在 ~/.cache/twtools/models）。裝過其中一個，另一個通常不必再下載模型。"),
]

GUIDE_STEPS = [
    ("下載", f'到 <a href="{DOWNLOAD}" data-dl="mac">GitHub Releases 下載 {DMG}</a>，打開後把「{NAME}」拖到「應用程式」。'),
    ("第一次開啟：macOS 說「無法打開」時，按「完成」，不要按「丟到垃圾桶」",
     "這個 App 沒有付費的 Apple 公證，用瀏覽器下載的版本第一次雙擊時，macOS 會跳出「無法打開」的警告，只有「丟到垃圾桶」和「完成」兩個按鈕。"
     "請按<strong>「完成」</strong>，再從<a href=\"#blocked\">下面三種做法</a>挑一種打開它（最簡單的是到「系統設定 → 隱私權與安全性」按「仍要打開」）。"
     "每台電腦只需要做一次；之後在 App 裡更新也不會再被擋。"),
    ("允許麥克風", "第一次錄音時 macOS 會問能不能用麥克風，按「允許」。錄音只存在你的電腦。"),
    ("下載語音辨識模型",
     f"按「下載語音辨識模型」，約 1.6 GB，從 Hugging Face 官方下載並比對 SHA256。裝過<a href=\"{KANDONG}\">看懂 KanDong</a>的話，"
     "通常已經有了，按鈕會直接顯示就緒。"),
    ("錄音、轉逐字稿",
     "選錄音來源（實體會議選「只錄麥克風」，線上會議選「兩者都錄」），按「開始錄音」，結束按「停止」，再按「轉逐字稿」。"
     "與會者有填，說話人分離會準很多。"),
    ("（選用）產生摘要",
     f"先安裝並登入 <a href=\"{CLAUDE_CODE}\">Claude Code</a>。勾「轉完逐字稿後自動用 Claude 產生摘要」，或對單場按「產生這場摘要」。"
     "會用到你 Claude 方案的額度，所以預設不自動做。"),
]


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def ga_snippet() -> str:
    if not GA_ID:
        return ""
    return f"""<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
<script>
window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
gtag('js',new Date());gtag('config','{GA_ID}');
document.addEventListener('click',function(e){{var a=e.target.closest&&e.target.closest('a[data-dl]');
if(a)gtag('event','echoic_local_download',{{platform:a.getAttribute('data-dl')}});}});
</script>"""


def head(title: str, desc: str, path: str, extra_ld: list[dict] | None = None) -> str:
    url = BASE + path
    lds = [{
        "@context": "https://schema.org", "@type": "SoftwareApplication", "name": NAME, "alternateName": "Echoic Local",
        "description": DESC, "applicationCategory": "BusinessApplication", "operatingSystem": "macOS 13+ (Apple Silicon)",
        "softwareVersion": VERSION, "inLanguage": "zh-TW", "isAccessibleForFree": True,
        "license": "https://opensource.org/licenses/MIT", "offers": {"@type": "Offer", "price": "0", "priceCurrency": "TWD"},
        "url": BASE + "/", "downloadUrl": RELEASES, "codeRepository": REPO,
    }] + (extra_ld or [])
    ld = "\n".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in lds)
    return f"""<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{BASE}/img/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="zh_TW">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0f5c57">
<link rel="icon" href="{ICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap">
<link rel="stylesheet" href="/site.css">
{ga_snippet()}
{ld}
</head>
<body>
<header class="top"><div class="wrap bar">
<a class="logo" href="/" aria-label="{NAME} 首頁"><span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span><span>Echoic <b>本機版</b></span></a>
<nav><a href="/guide/">安裝教學</a><a href="/faq/">常見問題</a><a href="{REPO}">GitHub</a></nav>
</div></header>
"""


FOOT = f"""<footer class="foot"><div class="wrap">
<p><strong>{NAME}</strong>：免費開源（MIT）的會議逐字稿工具。語音辨識使用 whisper.cpp、說話人分離使用 sherpa-onnx，都在你的電腦上執行。</p>
<p>錄音前請先取得與會者同意。逐字稿與摘要可能有錯，重要內容請回聽原音。</p>
<p><a href="{REPO}">原始碼</a>｜<a href="{REPO}/blob/main/THIRD_PARTY.md">第三方授權</a>｜<a href="{KANDONG}">姊妹工具：看懂 KanDong</a>｜<a href="https://twtools.cc/">twtools.cc</a></p>
</div></footer>
</body>
</html>
"""


def dl_button(cls: str = "btn") -> str:
    return (f'<a class="{cls}" href="{DOWNLOAD}" data-dl="mac">下載 Mac 版<small>Apple Silicon・macOS 13 以上・免費</small></a>')


def page_index() -> str:
    feats = [
        ("🔒", "錄音預設不出你的電腦", "語音辨識和說話人分離預設都在本機跑，沒有帳號、沒有月費。想讓電腦少做一點，也可以自己選線上語音辨識（會上傳錄音）。"),
        ("🗣️", "分好誰在說話", "自動分出 SPEAKER_00、01…；填了與會者，還會照人數分，摘要直接用人名。"),
        ("🇹🇼", "台灣正體＋詞彙表", "輸出一律台灣正體。公司名、產品名常寫錯？收進詞彙表一次，之後每場自動修。"),
        ("⏱️", "每段都有時間戳", "逐字稿、決議、待辦都附時間，想確認就回去聽原音。"),
        ("✨", "摘要是選用的", "要摘要，再用你自己登入的 Claude 產生；預設關，不會偷偷用掉你的額度。"),
        ("🤝", "和看懂共用模型", "裝過看懂 KanDong 的人，通常不用再下載 1.6 GB 的語音辨識模型。"),
    ]
    cards = "".join(f'<li class="card"><span class="emo" aria-hidden="true">{e}</span><h3>{t}</h3><p>{d}</p></li>' for e, t, d in feats)
    faq_short = "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in FAQ[:4])
    return head(f"{NAME}｜{TAGLINE}", DESC, "/") + f"""<main>
<section class="hero"><div class="wrap hero-grid">
<div>
<p class="eyebrow">免費開源・Mac・會後逐字稿</p>
<h1>會議錄音，<br>在自己的 Mac 上<br><span class="hl">變成逐字稿</span>。</h1>
<p class="lead">分好誰在說話、每段都有時間戳、一律台灣正體。錄音預設不上傳。想要摘要，再用你自己的 Claude。</p>
<div class="cta">{dl_button()}<a class="btn ghost" href="/guide/">先看安裝教學</a></div>
<p class="note">錄音前，請先取得與會者同意。</p>
</div>
<div class="demo" aria-label="逐字稿畫面示意">
<div class="demo-bar"><span></span><span></span><span></span><b>transcript-by-minute.txt</b></div>
<div class="demo-body">
<p><time>[00:03]</time><em class="s0">SPEAKER_00</em>那我們先看上週的數字，轉換率有比較好。</p>
<p><time>[00:04]</time><em class="s1">SPEAKER_01</em>對，改版之後大概多了兩成，但客服量也變多。</p>
<p><time>[00:05]</time><em class="s0">SPEAKER_00</em>好，那客服這塊下週三前給我一個方案。</p>
<p><time>[00:06]</time><em class="s1">SPEAKER_01</em>沒問題，我週三中午前寄給你。</p>
</div>
<p class="demo-cap">示意畫面（虛構對話）</p>
</div>
</div></section>

<section class="wrap"><h2 class="sec">它會幫你做什麼</h2><ul class="cards">{cards}</ul></section>

<section class="wrap steps-wrap"><h2 class="sec">三步驟</h2>
<ol class="steps">
<li><b>錄</b><span>選「只錄麥克風」或「兩者都錄」，按開始。</span></li>
<li><b>轉</b><span>按「轉逐字稿」，等語音辨識和說話人分離跑完。</span></li>
<li><b>看</b><span>打開資料夾：逐字稿、說話人、（選用）摘要都在裡面，也能直接當 Obsidian 筆記庫。</span></li>
</ol>
<p class="small">M4 MacBook Air 實測：語音辨識每小時錄音多半 4～6 分鐘，說話人分離另外約 7 分鐘；轉的時候照常能用電腦。</p>
</section>

<section class="wrap bounds"><h2 class="sec">先說清楚做不到的</h2>
<ul>
<li>沒有即時字幕，只做會後轉錄。</li>
<li>目前只有 Apple Silicon Mac 版；Windows 版開發中。</li>
<li>同音的專有名詞會寫錯，多人同時講話時說話人會分錯。重要內容請回聽原音。</li>
<li>App 沒有付費的 Apple 公證：用瀏覽器下載的版本第一次打開會被 macOS 擋下來，要多做一步（<a href="/guide/#blocked">三種做法，你選</a>）。</li>
</ul></section>

<section class="wrap"><h2 class="sec">常見問題</h2><div class="faq">{faq_short}</div><p><a href="/faq/">看全部常見問題 →</a></p></section>

<section class="wrap final">{dl_button()}<p class="small">原始碼與授權：<a href="{REPO}">GitHub</a>。版本 {VERSION}。</p></section>
</main>
""" + FOOT


GATEKEEPER_SVG = f"""<svg class="illus" viewBox="0 0 640 260" role="img" aria-label="系統設定的隱私權與安全性頁面，在安全性區塊按「仍要打開」">
<rect x="0" y="0" width="640" height="260" rx="16" fill="#fff"/>
<rect x="24" y="24" width="392" height="212" rx="12" fill="#f3efe6"/>
<circle cx="44" cy="42" r="5" fill="#ff5f57"/><circle cx="60" cy="42" r="5" fill="#febc2e"/><circle cx="76" cy="42" r="5" fill="#28c840"/>
<text x="44" y="78" font-size="14" fill="#777">一般</text>
<text x="44" y="104" font-size="14" fill="#777">外觀</text>
<rect x="34" y="116" width="128" height="28" rx="6" fill="#0f5c57"/>
<text x="44" y="135" font-size="14" fill="#fff" font-weight="700">隱私權與安全性</text>
<text x="44" y="166" font-size="14" fill="#777">桌面與 Dock</text>
<text x="44" y="192" font-size="14" fill="#777">顯示器</text>
<rect x="176" y="60" width="226" height="164" rx="10" fill="#fff"/>
<text x="192" y="88" font-size="15" fill="#1d2321" font-weight="700">安全性</text>
<text x="192" y="116" font-size="13" fill="#555">已阻擋「{NAME}」，</text>
<text x="192" y="136" font-size="13" fill="#555">因為無法確認它沒有</text>
<text x="192" y="156" font-size="13" fill="#555">惡意軟體。</text>
<rect x="276" y="174" width="112" height="32" rx="8" fill="#ff7a59"/>
<text x="332" y="195" font-size="15" fill="#fff" font-weight="700" text-anchor="middle">仍要打開</text>
<text x="436" y="70" font-size="15" fill="#1d2321">① 先雙擊一次，</text>
<text x="436" y="92" font-size="15" fill="#1d2321">警告視窗按「完成」</text>
<text x="436" y="128" font-size="15" fill="#1d2321">② 系統設定 →</text>
<text x="436" y="150" font-size="15" fill="#1d2321">隱私權與安全性</text>
<text x="436" y="186" font-size="15" fill="#1d2321">③ 往下捲，按</text>
<text x="436" y="208" font-size="15" fill="#1d2321">「仍要打開」</text>
</svg>"""


def page_guide() -> str:
    steps = "".join(f'<li><h2>{esc(t)}</h2><p>{body}</p></li>'
                    for i, (t, body) in enumerate(GUIDE_STEPS))
    howto = {"@context": "https://schema.org", "@type": "HowTo", "name": f"安裝並使用 {NAME}",
             "step": [{"@type": "HowToStep", "name": t, "position": i + 1} for i, (t, _) in enumerate(GUIDE_STEPS)]}
    return head(f"安裝教學｜{NAME}", f"{NAME} Mac 版安裝步驟：下載 dmg、第一次開啟按「仍要打開」、允許麥克風、下載語音辨識模型、錄音轉逐字稿，以及選用的 Claude 摘要。",
                "/guide/", [howto]) + f"""<main class="wrap doc">
<h1>安裝教學</h1>
<p class="lead">需要 Apple Silicon（M1 以後）的 Mac、macOS 13 以上，以及約 2 GB 的空間（App＋語音辨識模型）。</p>
<ol class="guide">{steps}</ol>

<h2 id="blocked">第一次打開被擋：三種做法，你選</h2>
<p><strong>為什麼會被擋</strong>：Apple 要開發者每年付費加入開發者計畫、把 App 送去「公證」，macOS 才會直接放行。{NAME} 目前沒有做這件事，所以用瀏覽器下載的版本會被標成「從網路下載、未經驗證」，第一次打開就被擋下來。
App 是開源的，程式碼都在 <a href="{REPO}">GitHub</a>；每個安裝檔都附 SHA-256（<a href="{RELEASES}">Releases 頁</a>的 <code>SHA256SUMS.txt</code>），可以自己比對檔案沒被動過。相信這個 App 再用下面任一種做法打開它，不相信就不要裝。</p>

<h3 id="blocked-settings">做法一：系統設定按「仍要打開」（不用終端機）</h3>
<ol>
<li>雙擊「{NAME}」。macOS 說「無法打開」時，按<strong>「完成」</strong>（不要按「丟到垃圾桶」）。</li>
<li>打開「系統設定」→ 左邊選「隱私權與安全性」→ 往下捲到「安全性」。</li>
<li>會看到「已阻擋『{NAME}』」，按旁邊的<strong>「仍要打開」</strong>（英文介面是 Open Anyway），輸入電腦密碼。</li>
<li>再跳一次確認視窗時，按<strong>「打開」</strong>。之後雙擊就能直接開。</li>
</ol>
<p class="small">「安全性」那裡沒有按鈕：先回去雙擊一次 App 再回來看，按鈕只會在被擋之後的一小時內出現。macOS 14 以前也可以對 App 按右鍵 →「打開」；macOS 15 起 Apple 拿掉了這條捷徑。</p>
{GATEKEEPER_SVG}

<h3 id="blocked-xattr">做法二：已經裝進「應用程式」了，用一行指令解除</h3>
<p>打開「終端機」（在「應用程式 → 工具程式」），貼上這行、按 Return：</p>
<pre>xattr -dr com.apple.quarantine "/Applications/{NAME}.app"</pre>
<p>這行只做一件事：拿掉 macOS 幫這個 App 貼的「從網路下載」標記。之後雙擊就能開。</p>

<h3 id="blocked-install">做法三：不經過瀏覽器，用一行指令直接安裝</h3>
<p>還沒下載、或想之後都這樣裝：打開「終端機」，貼上這行、按 Return：</p>
<pre>curl -fsSL {BASE}/install.sh | bash</pre>
<p>這支<a href="/install.sh">安裝腳本</a>只做五件事：從 GitHub Releases 下載最新版 dmg 與 <code>SHA256SUMS.txt</code>、比對 SHA-256（不符就停止，什麼都不裝）、把 App 複製到「應用程式」（覆蓋舊版）、卸載並刪掉暫存檔、打開 App。用 curl 下載的檔案不會被標成「從網路下載」，所以不會跳出警告。</p>
<p>想先看過內容再執行（比較謹慎的做法）：</p>
<pre>curl -fsSL {BASE}/install.sh -o install.sh
less install.sh
bash install.sh</pre>
<p class="small">只對你信任的網址這樣做。這個做法需要你的帳號能寫入「應用程式」資料夾（一般是管理者帳號）；不是的話請用做法一。</p>

<h2 id="online">錄線上會議（對方的聲音）</h2>
<p>macOS 預設錄不到電腦播出來的聲音，要先裝免費的 <a href="{BLACKHOLE}">BlackHole 2ch</a> 虛擬音源：</p>
<ol>
<li>安裝 BlackHole 2ch。</li>
<li>打開「音訊 MIDI 設定」（在「應用程式 → 工具程式」），按左下角 <kbd>+</kbd> →「建立多重輸出裝置」，勾選 <strong>BlackHole 2ch</strong> 和你實際在聽的喇叭或耳機。</li>
<li>開會時，把系統的聲音輸出選成這個多重輸出裝置；你照樣聽得到，App 也錄得到。</li>
<li>App 的錄音來源選「兩者都錄」。</li>
</ol>

<h2 id="glossary">常錯的名字：詞彙表</h2>
<p>會議資料夾最上層有一份 <code>詞彙表.md</code>（第一次轉錄時自動建立）。一行一條：</p>
<pre>- 正確寫法｜逐字稿常見錯寫（用、分開）｜備註</pre>
<p>之後每場：正確寫法會提示給語音辨識、已知的錯寫直接換掉、摘要也照這裡寫。只有一個字的錯寫不會自動換，免得換錯。</p>

<h2 id="output">轉完會得到什麼</h2>
<ul>
<li><code>transcript-by-minute.txt</code>：逐分鐘、同一人連續發言合併，最好讀。</li>
<li><code>transcript.srt</code>：字幕格式的逐字稿，可以拿去對影片。</li>
<li><code>summary.md</code>：一句話、決議、待辦、數字表，每條附時間戳（有做摘要才有）。</li>
<li><code>audio.wav</code>：原始錄音，不會被改動。</li>
</ul>

<h2 id="trouble">卡住了？</h2>
<ul>
<li><strong>打不開、說「無法打開」或「無法確認開發者」</strong>：看上面的<a href="#blocked">三種做法</a>。不小心按了「丟到垃圾桶」：到垃圾桶把 App 拖回「應用程式」，或重新下載。</li>
<li><strong>錄不到聲音</strong>：「系統設定 → 隱私權與安全性 → 麥克風」確認有允許 {NAME}。</li>
<li><strong>沒錄到對方</strong>：輸出裝置要選多重輸出裝置，錄音來源要選「兩者都錄」。</li>
<li><strong>摘要按鈕是灰的</strong>：沒偵測到 Claude Code。安裝並登入後重新開啟 App。</li>
<li>其他問題請到 <a href="{REPO}/issues">GitHub</a> 回報，附上會議資料夾裡的 <code>whisper-server.log</code> 或 <code>ffmpeg.log</code>（不要附錄音）。</li>
</ul>
<p class="cta">{dl_button()}</p>
</main>
""" + FOOT


def page_faq() -> str:
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in FAQ]}
    items = "".join(f"<details open><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in FAQ)
    return head(f"常見問題｜{NAME}", f"{NAME} 常見問題：要不要錢、錄音會不會上傳、摘要會不會用到 Claude 額度、電腦規格、處理時間、能不能錄線上會議。",
                "/faq/", [ld]) + f"""<main class="wrap doc"><h1>常見問題</h1><div class="faq">{items}</div>
<p class="cta">{dl_button()}</p></main>
""" + FOOT


CSS = """
:root{--ink:#1d2321;--muted:#5b6461;--bg:#fbf7f0;--card:#fff;--teal:#0f5c57;--teal2:#127a72;--sun:#ffd166;--coral:#ff7a59;--line:#e6dfd2}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font-family:"Noto Sans TC",-apple-system,"PingFang TC",sans-serif;line-height:1.75;font-size:17px}
a{color:var(--teal2)}a:hover{color:var(--teal)}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
.top{position:sticky;top:0;z-index:5;background:rgba(251,247,240,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;justify-content:space-between;height:64px;gap:12px}
.logo{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink);font-weight:900;font-size:19px}
.logo b{color:var(--teal)}
.mark{display:inline-flex;align-items:center;gap:3px;background:var(--teal);border-radius:9px;padding:0 7px;height:32px}
.mark i{display:block;width:4px;background:var(--sun);border-radius:2px}
.mark i:nth-child(1){height:9px}.mark i:nth-child(2){height:17px}.mark i:nth-child(3){height:23px}.mark i:nth-child(4){height:13px}
nav{display:flex;gap:18px;flex-wrap:wrap}nav a{text-decoration:none;color:var(--ink);font-weight:500;font-size:15px}
.hero{padding:56px 0 36px;background:radial-gradient(1200px 400px at 85% 0%,#fde9c4 0,transparent 60%)}
.hero-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:40px;align-items:center}
.eyebrow{display:inline-block;background:#e3f1ef;color:var(--teal);font-weight:700;font-size:14px;padding:4px 12px;border-radius:999px;margin:0 0 12px}
h1{font-size:46px;line-height:1.25;margin:0 0 16px;font-weight:900;letter-spacing:.01em}
.hl{background:linear-gradient(transparent 62%,var(--sun) 62%);padding:0 4px}
.lead{font-size:19px;color:var(--muted);margin:0 0 22px}
.cta{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.btn{display:inline-flex;flex-direction:column;background:var(--coral);color:#fff;text-decoration:none;font-weight:900;font-size:18px;padding:12px 22px;border-radius:14px;box-shadow:0 6px 0 #d95c3d;transition:transform .08s}
.btn:hover{color:#fff;transform:translateY(-1px)}.btn:active{transform:translateY(3px);box-shadow:0 3px 0 #d95c3d}
.btn small{font-weight:500;font-size:12px;opacity:.92}
.btn.ghost{background:#fff;color:var(--teal);box-shadow:0 6px 0 var(--line);border:2px solid var(--teal);justify-content:center}
.btn.ghost:hover{color:var(--teal)}
.note{font-size:14px;color:var(--muted);margin-top:16px}
.demo{background:#14201e;border-radius:16px;box-shadow:0 18px 40px rgba(15,92,87,.25);overflow:hidden;transform:rotate(1deg)}
.demo-bar{display:flex;gap:6px;align-items:center;padding:10px 14px;background:#0d1615}
.demo-bar span{width:10px;height:10px;border-radius:50%;background:#ff6159}.demo-bar span:nth-child(2){background:#ffbd2e}.demo-bar span:nth-child(3){background:#28c941}
.demo-bar b{color:#9fb3ae;font-weight:500;font-size:13px;margin-left:8px;font-family:ui-monospace,Menlo,monospace}
.demo-body{padding:16px 18px;color:#e9f1ef;font-size:15px}
.demo-body p{margin:0 0 10px}
.demo-body time{color:#7fa39c;font-family:ui-monospace,Menlo,monospace;margin-right:8px}
.demo-body em{font-style:normal;font-size:12px;font-weight:700;padding:1px 6px;border-radius:5px;margin-right:8px}
.s0{background:var(--sun);color:#3d2c00}.s1{background:#8fd3c9;color:#073b36}
.ghost-line{color:#6f8580}
.demo-cap{margin:0;padding:0 18px 12px;color:#6f8580;font-size:12px}
.sec{font-size:30px;font-weight:900;margin:56px 0 18px}
.cards{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px}
.card h3{margin:6px 0 6px;font-size:19px}.card p{margin:0;color:var(--muted);font-size:15px}
.emo{font-size:28px}
.steps{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;counter-reset:s}
.steps li{background:var(--teal);color:#fff;border-radius:16px;padding:20px;display:flex;gap:14px;align-items:flex-start}
.steps b{flex:none;width:52px;height:52px;border-radius:14px;background:var(--sun);color:var(--teal);display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:900}
.small{font-size:14px;color:var(--muted)}
.bounds ul{background:#fff;border:2px dashed var(--line);border-radius:16px;padding:18px 18px 18px 38px;margin:0}
.faq details{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 10px}
.faq summary{cursor:pointer;font-weight:700}
.faq p{margin:8px 0 0;color:var(--muted)}
.final{text-align:center;padding:48px 20px}
.final .btn{align-items:center}
.doc{max-width:820px;padding-top:36px;padding-bottom:48px}
.doc h1{font-size:38px}
.guide{padding-left:0;list-style:none;counter-reset:g}
.guide>li{counter-increment:g;background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px 18px 74px;margin:0 0 14px;position:relative}
.guide>li::before{content:counter(g);position:absolute;left:18px;top:18px;width:40px;height:40px;border-radius:12px;background:var(--sun);color:var(--teal);font-weight:900;font-size:20px;display:flex;align-items:center;justify-content:center}
.guide h2{font-size:21px;margin:4px 0 6px}.guide p{margin:0}
.illus{display:block;width:100%;height:auto;margin-top:14px;border:1px solid var(--line);border-radius:16px}
pre,code,kbd{font-family:ui-monospace,Menlo,monospace;font-size:.92em}
pre{background:#14201e;color:#e9f1ef;padding:12px 16px;border-radius:10px;overflow-x:auto}
code{background:#efe9dd;padding:1px 5px;border-radius:5px}
kbd{border:1px solid #ccc;border-bottom-width:2px;border-radius:5px;padding:0 5px;background:#fff}
.foot{border-top:1px solid var(--line);margin-top:40px;padding:24px 0;color:var(--muted);font-size:14px}
@media (max-width:860px){.hero-grid{grid-template-columns:1fr}.cards,.steps{grid-template-columns:1fr}h1{font-size:34px}.demo{transform:none}.sec{font-size:25px}}
@media (max-width:480px){.wrap{padding:0 16px}nav{gap:12px}nav a{font-size:14px}.logo{font-size:16px}.btn{width:100%}.guide>li{padding-left:18px;padding-top:70px}}
"""


def llms() -> str:
    return f"""# {NAME}（Echoic Local）

> 免費開源（MIT）的 Mac 會議逐字稿工具。會後在使用者自己的電腦把錄音轉成台灣正體逐字稿（whisper.cpp 語音辨識＋sherpa-onnx 說話人分離），預設錄音不上傳；0.4.0 起可自選 OpenAI 相容的線上語音辨識（選了會上傳錄音，預設關）。摘要選用，透過使用者自己登入的 Claude Code 產生，會用到使用者自己 Claude 方案的額度，預設關閉。目前只支援 Apple Silicon Mac（macOS 13+）；沒有即時字幕。

## 頁面
- [首頁與下載]({BASE}/)：功能、限制、下載連結。
- [安裝教學]({BASE}/guide/)：第一次開啟（仍要打開）、麥克風權限、下載模型、錄線上會議（BlackHole）、詞彙表、輸出檔。
- [常見問題]({BASE}/faq/)：費用、隱私、Claude 額度、電腦規格、處理時間、準確度、和看懂 KanDong 共用模型。
- [原始碼]({REPO})、[最新版]({RELEASES})。

## 引用範圍
處理時間只引用 M4 MacBook Air 的實測（語音辨識每小時錄音多半 4～6 分鐘，17 場），不推算其他硬體。摘要額度用量（一小時會議約送出 4～5 萬字）是以 26 場會議的逐字稿字數估算，不是 Anthropic 的官方數字。錄音須先取得與會者同意。
"""


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    files = {
        "index.html": page_index(),
        "guide/index.html": page_guide(),
        "faq/index.html": page_faq(),
        "site.css": CSS.lstrip(),
        "llms.txt": llms(),
        "install.sh": INSTALL_SH.read_text(encoding="utf-8"),
        "robots.txt": f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n",
        "sitemap.xml": '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                       + "".join(f"  <url><loc>{BASE}{p}</loc><lastmod>{DATE}</lastmod></url>\n" for p in ("/", "/guide/", "/faq/"))
                       + "</urlset>\n",
    }
    for rel, content in files.items():
        p = PUBLIC / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    print(f"✅ {len(files)} 個檔 → {PUBLIC}（GA4：{GA_ID or '未設定，未放追蹤碼'}）")


if __name__ == "__main__":
    main()
