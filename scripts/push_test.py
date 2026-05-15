"""一次性 Telegram 推播測試：從 DB 取 top N 推送。"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.db import DealDB
from src.notifier import TelegramNotifier


def row_to_deal_like(r):
    def _d(s):
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    return SimpleNamespace(
        region=r["region"],
        title_zh=r["title_zh"],
        title_orig=r["title_orig"],
        image_url=r["image_url"],
        original_price=r["original_price"],
        sale_price=r["sale_price"],
        discount_pct=r["discount_pct"],
        sale_start=_d(r["sale_start"]),
        sale_end=_d(r["sale_end"]),
        url=r["url"],
    )


def main(top_n: int = 5):
    cfg = AppConfig.load("config.yaml")
    tg = cfg.telegram_cfg
    if not tg.get("enabled"):
        print("telegram disabled in config.yaml")
        return

    db = DealDB(cfg.db_path)
    rows = db.query(order_by="discount_pct", descending=True, limit=top_n)
    if not rows:
        print("DB 無資料")
        return

    deals = [row_to_deal_like(r) for r in rows]
    print(f"推送 {len(deals)} 件 (top {top_n}):")
    for i, d in enumerate(deals, 1):
        print(f"  {i}. [{d.region}] -{d.discount_pct:.0f}% NT${d.sale_price:,} {(d.title_zh or d.title_orig)[:40]}")

    notifier = TelegramNotifier(
        bot_token=tg.get("bot_token", ""),
        chat_id=str(tg.get("chat_id", "")),
        enabled=True,
        no_emoji=bool(tg.get("no_emoji", True)),
    )
    header = f"Coupang TW 測試推播 top {top_n}"
    ok, fail = notifier.push_deals(deals, top_n=top_n, header=header)
    print(f"\n結果：成功 {ok}, 失敗 {fail}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    main(n)
