"""抓 N 個詳情頁，統計 sales / final / original 出現分布。"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import DealDB
from src.parser import parse_detail_prices
from src.scraper import CoupangScraper, ScraperConfig


async def main(n: int = 10):
    rows = DealDB("data/deals.db").query(limit=n)
    urls = [r["url"] for r in rows]
    print(f"probing {len(urls)} URLs...")

    s = CoupangScraper(ScraperConfig(headless=True, timeout_ms=45000, use_tor_on_fail=False))
    html_map = await s.fetch_detail_html(urls)

    stats = {"both": 0, "sales_only": 0, "final_only": 0, "neither": 0, "fetch_fail": 0}
    samples = {"final_only": [], "neither": []}

    for u in urls:
        h = html_map.get(u)
        if not h:
            stats["fetch_fail"] += 1
            continue
        p = parse_detail_prices(h)
        has_s = "sales" in p
        has_f = "final" in p
        has_o = "original" in p
        key = ("both" if has_s and has_f else
               "sales_only" if has_s else
               "final_only" if has_f else
               "neither")
        stats[key] += 1
        if key in samples and len(samples[key]) < 2:
            samples[key].append((u, p, has_o))

    print("\n=== distribution ===")
    for k, v in stats.items():
        print(f"  {k:15s} = {v}")

    if samples["final_only"]:
        print("\n=== final_only samples (no sales-price-amount) ===")
        for u, p, has_o in samples["final_only"]:
            print(f"  url={u[:80]}")
            print(f"  prices={p} original_in={has_o}")
            # 找 final-price 附近的文本，看有沒有首購標記
            h = html_map[u]
            m = re.search(r'final-price-amount[^>]*>\s*\$?\s*[\d,]+\s*</div>', h)
            if m:
                ctx_start = max(0, m.start() - 200)
                ctx_end = min(len(h), m.end() + 300)
                # 抽純文字脈絡（去 tag）
                ctx = re.sub(r'<[^>]+>', ' ', h[ctx_start:ctx_end])
                ctx = re.sub(r'\s+', ' ', ctx)
                print(f"  context: {ctx[:400]}")
            print()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
