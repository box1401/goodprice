"""抓單個詳情頁 dump 到 logs/detail_sample.html 以便 diagnose price parser。"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.scraper import CoupangScraper, ScraperConfig


async def main(url: str):
    s = CoupangScraper(ScraperConfig(headless=True, timeout_ms=45000, use_tor_on_fail=False))
    html_map = await s.fetch_detail_html([url])
    html = html_map.get(url)
    if not html:
        print("fetch failed")
        return
    out = Path("logs/detail_sample.html")
    out.write_text(html, encoding="utf-8")
    print(f"saved {len(html):,} bytes to {out}")

    # 抽價格相關片段：price-amount / 首購 / 一般售價
    print("\n=== price-amount blocks ===")
    for m in re.finditer(
        r'<[^>]*class="[^"]*price-amount[^"]*"[^>]*>.*?</[^>]+>',
        html, re.DOTALL,
    ):
        txt = m.group(0)
        if len(txt) < 500:
            print(txt[:300])
            print("---")

    print("\n=== keywords ===")
    for kw in ("首購", "first", "original-price", "sales-price", "final-price",
               "instant-discount", "coupon", "折扣券", "優惠券"):
        n = len(re.findall(kw, html))
        print(f"  {kw:20s} = {n}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else \
        "https://www.tw.coupang.com/vp/products/21007689883345?itemId=21020561465710&vendorItemId=21079093075724"
    asyncio.run(main(url))
