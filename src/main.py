"""每日主流程：scrape → parse → filter → translate → save → notify。

執行：
    python -m src.main             # 正常每日跑
    python -m src.main --dry-run   # 不寫 DB、不通知
    python -m src.main --discover  # 第一次跑，印出 selector 命中數量供調整
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from .config import AppConfig
from .db import DealDB
from .notifier import TelegramNotifier, format_deals_message
from .parser import filter_by_ratio, parse_listing
from .scraper import CoupangScraper, ScraperConfig
from .translator import Translator, attach_zh_titles


log = logging.getLogger("goodprice.main")


def setup_logging(log_dir: str, level: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"{date.today().isoformat()}.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


async def run(cfg: AppConfig, *, dry_run: bool = False, discover: bool = False, no_notify: bool = False) -> int:
    s = cfg.scraper_cfg
    scraper = CoupangScraper(ScraperConfig(
        max_pages=int(s.get("max_pages_per_region", 30)),
        delay_min=float(s.get("delay_min_sec", 3.0)),
        delay_max=float(s.get("delay_max_sec", 8.0)),
        retry=int(s.get("retry_count", 3)),
        backoff_sec=int(s.get("retry_backoff_sec", 30)),
        headless=bool(s.get("headless", True)),
        timeout_ms=int(s.get("timeout_ms", 45000)),
        use_tor_on_fail=bool(s.get("use_tor_on_fail", True)),
        tor_proxy=s.get("tor_socks_proxy", "socks5://127.0.0.1:9050"),
    ))

    all_deals = []
    for region in cfg.regions:
        if not region.urls:
            log.warning("region %s 無 url，跳過。請填 config.yaml", region.id)
            continue
        log.info("=== 抓取 %s (%s, %d 個來源) ===", region.name, region.id, len(region.urls))

        pages_html: list[str] = []
        for src_idx, url in enumerate(region.urls, 1):
            log.info("  來源 %d/%d → %s", src_idx, len(region.urls), url[:120])
            try:
                pages_html.extend(await scraper.fetch_listing(url))
            except Exception as e:
                log.error("  region %s 來源 %d 失敗：%s", region.id, src_idx, e)
                continue

        log.info("region %s 共抓到 %d 頁 HTML", region.id, len(pages_html))
        if not pages_html:
            continue

        region_deals = []
        for i, html in enumerate(pages_html, 1):
            page_deals = parse_listing(
                html,
                region=region.id,
                base_url=cfg.base_url,
                rocket_global_only=cfg.rocket_global_only,
            )
            log.info("  p.%d 解析出 %d 件", i, len(page_deals))
            # 0 件時 dump HTML 以便 diagnose
            if len(page_deals) == 0:
                from pathlib import Path
                dump = Path(cfg.log_dir) / f"empty_{region.id}_p{i}.html"
                dump.write_text(html, encoding="utf-8")
                log.info("    (dumped to %s)", dump)
            region_deals.extend(page_deals)

            if discover:
                _print_discover_summary(html, page_deals, page_no=i)
                if i >= 1:
                    break

        # 同 region 內去重（不同頁可能重複）
        seen, dedup = set(), []
        for d in region_deals:
            if d.product_id in seen:
                continue
            seen.add(d.product_id)
            dedup.append(d)
        log.info("region %s 去重後 %d 件", region.id, len(dedup))
        all_deals.extend(dedup)

    if discover:
        log.info("discover 模式結束")
        return 0

    log.info("總計 %d 件，套用折數 ≤ %.0f 過濾", len(all_deals), cfg.max_price_ratio_pct)
    filtered = filter_by_ratio(all_deals, cfg.max_price_ratio_pct)
    log.info("過濾後 %d 件", len(filtered))

    # 翻譯
    tcfg = cfg.translation_cfg
    translator = Translator(
        enabled=bool(tcfg.get("enabled", True)) and tcfg.get("provider", "google") != "none",
        target=tcfg.get("target_lang", "zh-TW"),
        skip_if_chinese=bool(tcfg.get("skip_if_chinese", True)),
    )
    if translator.enabled:
        log.info("翻譯 %d 件標題", len(filtered))
        attach_zh_titles(filtered, translator)
    else:
        attach_zh_titles(filtered, translator)  # 仍會 fallback 到 title_orig

    # 寫 DB
    db = DealDB(cfg.db_path)
    if not dry_run:
        n = db.upsert_many(filtered)
        log.info("寫入 DB %d 筆", n)
        purged = db.purge_older_than(cfg.retention_days)
        log.info("清除 %d 筆過期資料 (>%d 天)", purged, cfg.retention_days)
    else:
        log.info("[dry-run] 不寫 DB")

    # Telegram — 逐筆 sendPhoto
    tg_cfg = cfg.telegram_cfg
    if tg_cfg.get("enabled") and not dry_run and not no_notify:
        notifier = TelegramNotifier(
            bot_token=tg_cfg.get("bot_token", ""),
            chat_id=str(tg_cfg.get("chat_id", "")),
            enabled=True,
            no_emoji=bool(tg_cfg.get("no_emoji", True)),
        )
        top_n = int(tg_cfg.get("top_n", 50))
        ranked = sorted(filtered, key=lambda d: d.discount_pct, reverse=True)
        header = f"Coupang 台灣 {date.today().isoformat()} 特價 (折數 ≤ {cfg.max_price_ratio_pct:.0f})"
        if ranked:
            log.info("Telegram 推播 top %d 筆（每筆含商品圖）...", min(top_n, len(ranked)))
            ok_n, fail_n = notifier.push_deals(ranked, top_n=top_n, header=header)
            log.info("Telegram 推播完成：成功 %d 失敗 %d", ok_n, fail_n)
        else:
            log.info("無資料可推播")
    else:
        log.info("Telegram 未啟用或 dry-run，跳過")

    return 0


def _print_discover_summary(html: str, deals, page_no: int) -> None:
    from bs4 import BeautifulSoup
    from .parser import SELECTORS

    soup = BeautifulSoup(html, "lxml")
    print(f"\n=== Discover Page {page_no} ===")
    print(f"HTML 長度: {len(html):,}")
    for name, sel in SELECTORS.items():
        n = len(soup.select(sel))
        print(f"  {name:18s}  selector={sel!r:60s}  命中={n}")
    print(f"成功解析 deals: {len(deals)}")
    if deals:
        sample = deals[0]
        print(f"\n首筆樣本:")
        print(f"  product_id  = {sample.product_id}")
        print(f"  title       = {sample.title_orig}")
        print(f"  price       = {sample.sale_price} (orig={sample.original_price})")
        print(f"  discount    = {sample.discount_pct}%")
        print(f"  url         = {sample.url}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Coupang 台灣每日特價爬蟲")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="不寫 DB、不通知")
    ap.add_argument("--discover", action="store_true", help="只跑第一頁、印 selector 命中")
    ap.add_argument("--no-notify", action="store_true", help="寫 DB 但不推 Telegram")
    args = ap.parse_args()

    cfg = AppConfig.load(args.config)
    setup_logging(cfg.log_dir, cfg.log_level)
    log.info("=== 啟動 %s ===", datetime.now().isoformat(timespec="seconds"))
    return asyncio.run(run(cfg, dry_run=args.dry_run, discover=args.discover, no_notify=args.no_notify))


if __name__ == "__main__":
    sys.exit(main())
