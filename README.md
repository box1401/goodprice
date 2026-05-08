# Goodprice — Coupang Taiwan Daily Deal Tracker

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Playwright](https://img.shields.io/badge/scraper-Playwright-2EAD33.svg)](https://playwright.dev/python/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)](https://streamlit.io/)

每日自動抓取 [Coupang 台灣站](https://www.tw.coupang.com)「火箭跨境韓國／美國」特價商品，存 SQLite，提供 Streamlit 查詢介面，並透過 Telegram Bot 推播 Top N 折扣排行。

> Daily scraper for cross-border deals on Coupang Taiwan. Scrapes Korea / US imports, filters by discount, stores in SQLite, queries via Streamlit, pushes Top N to Telegram with product images.

---

## ✨ Features

- **無頭瀏覽器爬蟲**：Playwright + stealth，繞過 Cloudflare／Akamai 對 SPA 的基礎 bot 防護
- **精準過濾**：以「火箭跨境」徽章 (`<img alt="火箭跨境">`) 識別跨境商品，排除國內快遞混淆
- **歷史價格**：SQLite 每日 snapshot，可查 30 天內的價格走勢
- **多語言處理**：自動翻譯韓 / 日 / 英文標題為繁體中文（內建偵測，已是中文則跳過）
- **Telegram 推播**：每筆商品 `sendPhoto` 含縮圖、原價→特價、折扣率與商品連結
- **Streamlit 查詢介面**：表格、圖卡、圖表三分頁，支援篩選 / 排序 / Excel・CSV 匯出
- **Windows 工作排程**：一鍵註冊每日 08:00 自動執行
- **重試機制**：失敗自動退避重試，可選 Tor SOCKS5 fallback

## 📐 Architecture

```
┌─────────────────────┐
│ Windows Task        │ daily 08:00
│ Scheduler           │
└──────────┬──────────┘
           │ run_daily.bat
           ▼
┌─────────────────────────────────────────────┐
│ src/main.py                                 │
│  ┌──────────────────────────────────────┐   │
│  │ src/scraper.py                       │   │
│  │   Playwright (chromium + stealth)    │   │
│  │   randomized UA / delays / retry     │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ src/parser.py                        │   │
│  │   BeautifulSoup → Deal dataclass     │   │
│  │   filter by 火箭跨境 badge            │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ src/translator.py                    │   │
│  │   ko/ja/en → zh-TW (deep-translator) │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ src/db.py        SQLite (WAL)        │   │
│  │   upsert, retention, query           │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ src/notifier.py                      │   │
│  │   Telegram sendPhoto (rate-limited)  │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
           │
           ▼
   data/deals.db ─────► web/app.py (Streamlit)
                           localhost:8501
```

## 🚀 Quick Start

### Requirements

- Windows 10 / 11
- Python 3.11
- ~500 MB disk (Playwright Chromium)
- Telegram account (optional, for push notifications)

### One-shot setup

```powershell
git clone https://github.com/box1401/goodprice.git
cd goodprice
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

`setup.ps1` 會：
1. 建立 `.venv` (Python 3.11)
2. `pip install -r requirements.txt`
3. 安裝 Playwright Chromium
4. 從 `config.yaml.template` 複製出 `config.yaml`

### Configure

編輯 `config.yaml`：

```yaml
filter:
  max_price_ratio_pct: 90      # 折數，90 = 至少 10% off (即 9 折以下)

telegram:
  enabled: true
  bot_token: "YOUR_BOT_TOKEN"  # 跟 @BotFather 取
  chat_id:   "YOUR_CHAT_ID"    # 透過 getUpdates 取
  top_n: 50
  no_emoji: true
```

#### Get Telegram credentials

1. 在 Telegram 找 [@BotFather](https://t.me/BotFather) → `/newbot` 拿 `bot_token`
2. 跟你的 bot 對話傳一句 `hi`
3. 開瀏覽器訪問 `https://api.telegram.org/bot<TOKEN>/getUpdates` → 找 `chat.id`

### Run

```powershell
.\.venv\Scripts\Activate.ps1

# 一次性執行（爬 → 寫 DB → 推 Telegram）
python -m src.main

# 不推 Telegram，僅寫 DB
python -m src.main --no-notify

# 不寫 DB，僅驗證流程
python -m src.main --dry-run

# Discover 模式：印 selector 命中數，用於除錯
python -m src.main --discover
```

### Streamlit UI

直接執行 `scripts\launch_streamlit.bat`（雙擊即可），會自動：
1. 啟動 Streamlit server
2. 3 秒後開啟瀏覽器到 `http://localhost:8501`
3. 視窗關閉或 `Ctrl+C` 即停止 server

或從命令列：
```powershell
streamlit run web/app.py
```

要做桌面捷徑，把 `scripts\launch_streamlit.bat` 複製到桌面並改名（例：`Goodprice 介面.bat`）。

預設四個分頁：

| 分頁 | 內容 |
|---|---|
| 表格 | 完整資料表，附縮圖欄、可點連結 |
| 圖卡 | 5 欄商品縮圖 grid，點圖開 Coupang |
| 圖表 | 折扣率分布、每日新增筆數 |
| 原始資料 | DB 原始欄位 |

### Schedule daily run

以系統管理員開 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
```

註冊 Windows 工作排程 `GoodpriceCoupangDaily`，每天 08:00 觸發。

立即測試：
```powershell
Start-ScheduledTask -TaskName GoodpriceCoupangDaily
Get-ScheduledTaskInfo -TaskName GoodpriceCoupangDaily
```

## 🗂 Project Structure

```
goodprice/
├── src/
│   ├── main.py            # 主流程編排
│   ├── scraper.py         # Playwright 爬蟲 + retry/stealth
│   ├── parser.py          # DOM → Deal 解析、selector 集中
│   ├── translator.py      # 韓/日/英 → 繁中
│   ├── db.py              # SQLite + migration
│   ├── notifier.py        # Telegram Bot API
│   └── config.py          # YAML loader
├── web/
│   └── app.py             # Streamlit 介面
├── scripts/
│   ├── setup.ps1              # 一鍵環境建置
│   ├── run_daily.bat          # 排程器呼叫此檔
│   ├── register_task.ps1      # 註冊每日工作排程
│   └── launch_streamlit.bat   # 雙擊啟動查詢介面（自動開瀏覽器）
├── data/                  # deals.db（gitignored）
├── logs/                  # YYYY-MM-DD.log（gitignored）
├── config.yaml.template   # 設定範本
├── config.yaml            # 實際設定（gitignored）
├── requirements.txt
├── LICENSE
└── README.md
```

## ⚙ Configuration Reference

```yaml
site:
  base_url: https://www.tw.coupang.com

regions:
  - id: KR
    name: 火箭跨境韓國
    urls:
      - "https://www.tw.coupang.com/np/search?q=韓國%20火箭跨境&channel=user&listSize=72"
      - "https://www.tw.coupang.com/np/search?q=韓國&channel=user&rocketAll=true&listSize=72"
  - id: US
    name: 火箭跨境美國
    urls:
      - "https://www.tw.coupang.com/np/search?q=美國%20跨境&channel=user&listSize=72"
      - "https://www.tw.coupang.com/np/search?q=美國%20火箭跨境&channel=user&listSize=72"

filter:
  max_price_ratio_pct: 90       # 至少 10% off

filter_rocket_global_only: true # 只收火箭跨境徽章商品

scraper:
  max_pages_per_region: 8
  delay_min_sec: 3.0
  delay_max_sec: 8.0
  retry_count: 3
  retry_backoff_sec: 30
  use_tor_on_fail: false        # 設 true 並安裝 Tor 才生效
  tor_socks_proxy: socks5://127.0.0.1:9050
  headless: true
  timeout_ms: 45000

storage:
  db_path: data/deals.db
  retention_days: 30

translation:
  enabled: true
  provider: google              # google | none
  target_lang: zh-TW
  skip_if_chinese: true

telegram:
  enabled: false
  bot_token: ""
  chat_id: ""
  top_n: 50
  no_emoji: true
```

## 🛠 Maintenance

| 操作 | 指令 |
|---|---|
| 查 selector 命中數 | `python -m src.main --discover` |
| 查資料庫狀態 | `python -c "from src.db import DealDB; print(DealDB('data/deals.db').stats())"` |
| 清理舊資料 | 自動，每次跑會 purge >`retention_days` 天 |
| 解 selector 失效 | 改 `src/parser.py:SELECTORS` 後重跑 |
| 換 Telegram 通道 | 改 `src/notifier.py`，新 class 即可 |

## 🔒 Anti-bot Notes

Coupang 用 Akamai + Cloudflare：
- `/categories/*` 路徑被全擋（403）
- `/np/search?q=...` 路徑可正常存取
- 首頁 (`/`) 200 OK，作為暖機拿 cookie

故本專案：
1. 先載首頁建立 session cookie
2. 才訪問 `/np/search` 搜尋頁
3. 用 `<img alt="火箭跨境">` 徽章在 client-side 過濾結果（搜尋本身無此 filter）

若 IP 被擋：
- 啟用 `use_tor_on_fail: true` 並裝 Tor (`choco install tor`)，`tor.exe` 預設監聽 `127.0.0.1:9050`
- 或拉長 `delay_min_sec`／降低執行頻率

## ⚠ Disclaimer

- 本工具僅供個人使用，請遵守 [Coupang 使用條款](https://www.tw.coupang.com/article/terms-of-service)
- 抓取頻率請保持每日 1 次以下
- 商品價格／折扣以 Coupang 站上為準，本工具不保證資料正確性
- 翻譯由 Google 免費端點提供，可能有額度限制

## 📜 License

[MIT](LICENSE) © 2026
