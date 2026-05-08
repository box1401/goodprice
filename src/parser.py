"""DOM 解析。

針對 tw.coupang.com 的 /np/search 搜尋頁。
selector 已驗證於 logs/search_kr_rocketall.html (50 火箭跨境 / 10 火箭速配 卡片)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup, Tag


# ============================================================
# selectors
# ============================================================

SELECTORS = {
    # 商品卡 — search-product 後面有空格 (HTML 雙空格)
    "product_card":      "li.search-product",
    "title":             ".name",
    "price_sale":        "strong.price-value",
    "price_original":    "del.base-price",
    "discount_pct":      ".instant-discount-rate",
    "url":               "a.search-product-link",
    "image":             "img.search-product-wrap-img",
    "rocket_global":     'span.badge.global img[alt="火箭跨境"]',
    "rocket_express":    'span.badge.rocket img[alt="火箭速配"]',
}


@dataclass
class Deal:
    product_id: str
    region: str                              # 'KR' or 'US'
    title_orig: str
    sale_price: int
    discount_pct: float                      # 0–100, % off
    url: str
    original_price: Optional[int] = None
    title_zh: Optional[str] = None
    image_url: Optional[str] = None          # 商品縮圖 (絕對 URL)
    sale_start: Optional[date] = None        # 搜尋頁不提供，留 None
    sale_end: Optional[date] = None

    @property
    def price_ratio_pct(self) -> float:
        if not self.original_price or self.original_price <= 0:
            return 100.0
        return self.sale_price / self.original_price * 100.0


_PRICE_RE = re.compile(r"[\d,]+")
_PCT_RE = re.compile(r"(\d{1,3})\s*%")


def _to_int_price(text: str) -> Optional[int]:
    if not text:
        return None
    m = _PRICE_RE.search(text.replace(" ", ""))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _to_pct(text: str) -> Optional[float]:
    if not text:
        return None
    m = _PCT_RE.search(text)
    return float(m.group(1)) if m else None


def _extract_product_id(card: Tag, full_url: str) -> Optional[str]:
    """tw.coupang.com 商品卡有 data-product-id 屬性。fallback 解 URL。"""
    pid = card.get("data-product-id")
    if pid:
        return str(pid).strip()
    # URL fallback
    m = re.search(r"/products?/[^/?]*-(\d+)", full_url)
    if m:
        return m.group(1)
    qs = parse_qs(urlparse(full_url).query)
    for key in ("itemId", "productId", "vendorItemId"):
        if key in qs and qs[key]:
            return qs[key][0]
    return None


def _first_text(node: Tag, selector: str) -> Optional[str]:
    if not node:
        return None
    el = node.select_one(selector)
    if not el:
        return None
    txt = el.get_text(" ", strip=True)
    return txt or None


def parse_listing(
    html: str,
    region: str,
    base_url: str,
    *,
    rocket_global_only: bool = True,
) -> list[Deal]:
    """解析一頁列表。rocket_global_only=True 時排除非火箭跨境商品。"""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(SELECTORS["product_card"])
    deals: list[Deal] = []

    for card in cards:
        # 火箭跨境 badge 過濾
        if rocket_global_only:
            if not card.select_one(SELECTORS["rocket_global"]):
                continue

        # URL & product_id
        a = card.select_one("a[href]")
        if not a:
            continue
        href = a.get("href") or ""
        full_url = urljoin(base_url, href)
        pid = _extract_product_id(card, full_url)
        if not pid:
            continue

        # 標題
        title = _first_text(card, SELECTORS["title"])
        if not title:
            img = card.select_one("img[alt]")
            title = img.get("alt") if img else None
        if not title:
            continue

        # 價格
        sale_text = _first_text(card, SELECTORS["price_sale"])
        sale_price = _to_int_price(sale_text or "")
        if not sale_price:
            continue
        orig_text = _first_text(card, SELECTORS["price_original"])
        original_price = _to_int_price(orig_text or "")

        # 折扣
        pct_text = _first_text(card, SELECTORS["discount_pct"])
        discount_pct = _to_pct(pct_text or "")
        if discount_pct is None and original_price and sale_price:
            discount_pct = round((1 - sale_price / original_price) * 100, 1)
        if discount_pct is None:
            continue

        # 圖片 — Coupang 有兩種 lazy-load 模式：
        #   (a) src = real URL          (data-src = base64 placeholder)
        #   (b) src = blank1x1.gif      (data-img-src = real URL)
        # 優先取 data-img-src；其次 src（排除 placeholder）；最後 data-src（排除 data:）。
        image_url: Optional[str] = None
        img = card.select_one(SELECTORS["image"])
        if img:
            for attr in ("data-img-src", "src", "data-src"):
                val = (img.get(attr) or "").strip()
                if not val:
                    continue
                if val.startswith("data:"):
                    continue
                if "blank1x1" in val or val.endswith(("blank.gif", "transparent.gif")):
                    continue
                if val.startswith("//"):
                    val = "https:" + val
                image_url = val
                break

        deals.append(Deal(
            product_id=str(pid),
            region=region,
            title_orig=title,
            sale_price=sale_price,
            discount_pct=float(discount_pct),
            url=full_url,
            original_price=original_price,
            image_url=image_url,
        ))

    return deals


def filter_by_ratio(deals: list[Deal], max_ratio_pct: float) -> list[Deal]:
    """保留「折數 ≤ max_ratio_pct」的商品。max_ratio_pct=90 即至少 10% off。"""
    out = []
    for d in deals:
        if d.original_price:
            ratio = d.price_ratio_pct
        else:
            ratio = 100 - d.discount_pct
        if ratio <= max_ratio_pct:
            out.append(d)
    return out


# ============================================================
# 詳情頁價格解析
# 詳情頁有三組價：
#   .price-amount.original-price-amount  → 原價 (劃線)
#   .price-amount.sales-price-amount     → 一般售價 (無首購折扣) ← 我們要的
#   .price-amount.final-price-amount     → 首購折扣後最終價
# ============================================================

_DETAIL_PRICE_PAT = re.compile(
    r'<div[^>]*class="[^"]*\b(original|sales|final)-price-amount\b[^"]*"[^>]*>\s*\$?\s*([\d,]+)',
    re.IGNORECASE,
)


def parse_detail_prices(html: str) -> dict[str, int]:
    """從詳情頁 HTML 抽出 {original, sales, final} 三個價（缺哪個就沒哪個）。"""
    out: dict[str, int] = {}
    for m in _DETAIL_PRICE_PAT.finditer(html):
        kind = m.group(1).lower()
        try:
            val = int(m.group(2).replace(",", ""))
        except ValueError:
            continue
        # 同類型多筆只取第一個 (主要價格區塊)
        out.setdefault(kind, val)
    return out
