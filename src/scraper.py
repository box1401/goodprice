"""Playwright headless 爬蟲。

特性：
- chromium + playwright-stealth
- 每頁隨機 delay 3–8s
- UA 從清單隨機選
- 失敗 retry，重試耗盡後切 Tor (若啟用)
- 不寫檔，純回傳 HTML 列表給 parser
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PWTimeout,
)

try:
    from playwright_stealth import stealth_async
except ImportError:  # 套件可能 import path 不同
    stealth_async = None  # type: ignore


log = logging.getLogger(__name__)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
]


@dataclass
class ScraperConfig:
    max_pages: int = 30
    delay_min: float = 3.0
    delay_max: float = 8.0
    retry: int = 3
    backoff_sec: int = 30
    headless: bool = True
    timeout_ms: int = 45000
    use_tor_on_fail: bool = True
    tor_proxy: str = "socks5://127.0.0.1:9050"


class CoupangScraper:
    """每次呼叫 fetch_listing() 走訪一個分類的多頁。"""

    def __init__(self, cfg: ScraperConfig):
        self.cfg = cfg

    async def fetch_listing(self, start_url: str) -> list[str]:
        """回傳每一頁的完整 HTML 字串列表。"""
        # 先正常嘗試
        try:
            return await self._fetch(start_url, use_tor=False)
        except Exception as e:
            log.warning("normal fetch failed: %s", e)
            if not self.cfg.use_tor_on_fail:
                raise
            log.info("retrying via Tor proxy %s", self.cfg.tor_proxy)
            return await self._fetch(start_url, use_tor=True)

    async def _fetch(self, start_url: str, *, use_tor: bool) -> list[str]:
        async with async_playwright() as p:
            launch_args: dict = {"headless": self.cfg.headless}
            if use_tor:
                launch_args["proxy"] = {"server": self.cfg.tor_proxy}

            browser: Browser = await p.chromium.launch(**launch_args)
            try:
                ua = random.choice(USER_AGENTS)
                context: BrowserContext = await browser.new_context(
                    user_agent=ua,
                    locale="zh-TW",
                    timezone_id="Asia/Taipei",
                    viewport={"width": 1366, "height": 900},
                    extra_http_headers={
                        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                page = await context.new_page()
                if stealth_async is not None:
                    try:
                        await stealth_async(page)
                    except Exception as e:
                        log.debug("stealth_async skipped: %s", e)

                # 先暖首頁拿 cookie，避免直連搜尋頁被 Akamai 認為機器人
                try:
                    await page.goto("https://www.tw.coupang.com/", wait_until="domcontentloaded", timeout=self.cfg.timeout_ms)
                    await asyncio.sleep(2.0)
                except Exception as e:
                    log.warning("warmup homepage failed: %s", e)

                pages_html: list[str] = []
                current_url: Optional[str] = start_url
                seen_urls: set[str] = set()

                for page_no in range(1, self.cfg.max_pages + 1):
                    if not current_url or current_url in seen_urls:
                        break
                    seen_urls.add(current_url)

                    html = await self._goto_with_retry(page, current_url, page_no)
                    if not html:
                        break
                    pages_html.append(html)

                    next_url = await self._find_next_page(page)
                    if not next_url:
                        log.info("no next page after p.%d", page_no)
                        break
                    current_url = next_url

                    await self._random_delay()

                return pages_html
            finally:
                await browser.close()

    async def _goto_with_retry(self, page: Page, url: str, page_no: int) -> Optional[str]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.cfg.retry + 1):
            try:
                log.info("p.%d attempt %d → %s", page_no, attempt, url)
                resp = await page.goto(url, timeout=self.cfg.timeout_ms, wait_until="domcontentloaded")
                if resp and resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}")
                # 等待商品卡渲染（短超時，超時繼續，後續再決定）
                short_timeout = min(self.cfg.timeout_ms, 15000)
                try:
                    await page.wait_for_selector(
                        "li.search-product",
                        timeout=short_timeout,
                    )
                except PWTimeout:
                    log.debug("p.%d product selector timeout, capturing anyway", page_no)
                # 捲到底觸發 lazy-load + 額外等待
                await self._scroll_to_bottom(page, steps=10)
                await asyncio.sleep(1.5)
                return await page.content()
            except Exception as e:
                last_exc = e
                log.warning("attempt %d failed: %s", attempt, e)
                await asyncio.sleep(self.cfg.backoff_sec * attempt)
        if last_exc:
            raise last_exc
        return None

    async def _scroll_to_bottom(self, page: Page, steps: int = 10) -> None:
        for _ in range(steps):
            await page.evaluate("window.scrollBy(0, Math.max(800, document.body.scrollHeight / 8))")
            await asyncio.sleep(0.6)

    async def _find_next_page(self, page: Page) -> Optional[str]:
        """tw.coupang.com /np/search 用 page=N query 翻頁。
        Coupang 的 <a class="next"> href 寫死成中文標題不可用，直接 query 算下一頁。
        """
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        try:
            current = page.url
            u = urlparse(current)
            qs = parse_qs(u.query)
            cur_page = int(qs.get("page", ["1"])[0])
            next_page = cur_page + 1

            # 驗證頁面上有 page=next_page 連結 (沒到尾頁)；
            # 同時排除 href 不像 URL 的假連結 (如「前往下一頁」)
            has_link = await page.evaluate(
                """(p) => {
                    const as = Array.from(document.querySelectorAll('a[href]'));
                    return as.some(a => {
                        const h = a.getAttribute('href') || '';
                        if (!h.startsWith('/') && !h.startsWith('http') && !h.startsWith('?')) return false;
                        try {
                            const u = new URL(a.href, location.href);
                            return u.searchParams.get('page') === String(p);
                        } catch (e) { return false; }
                    });
                }""",
                next_page,
            )
            if not has_link:
                return None

            qs["page"] = [str(next_page)]
            # 保留所有原始參數，僅改 page
            new_q = urlencode({k: v[0] for k, v in qs.items() if v}, safe=",:")
            return urlunparse(u._replace(query=new_q))
        except Exception as e:
            log.debug("page increment failed: %s", e)
            return None

    async def _random_delay(self) -> None:
        d = random.uniform(self.cfg.delay_min, self.cfg.delay_max)
        log.debug("sleep %.1fs", d)
        await asyncio.sleep(d)

    async def fetch_detail_html(self, urls: list[str]) -> dict[str, str]:
        """逐一訪問商品詳情頁，回傳 {url: html}。失敗 url 不在 dict 中。

        重用單一 browser context；相對短的 delay (1.5–3 秒) 加快進度。
        """
        out: dict[str, str] = {}
        if not urls:
            return out

        async with async_playwright() as p:
            browser: Browser = await p.chromium.launch(headless=self.cfg.headless)
            try:
                ua = random.choice(USER_AGENTS)
                context: BrowserContext = await browser.new_context(
                    user_agent=ua,
                    locale="zh-TW",
                    timezone_id="Asia/Taipei",
                    viewport={"width": 1366, "height": 900},
                    extra_http_headers={
                        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                page = await context.new_page()
                if stealth_async is not None:
                    try:
                        await stealth_async(page)
                    except Exception:
                        pass

                # 暖機
                try:
                    await page.goto("https://www.tw.coupang.com/", wait_until="domcontentloaded", timeout=self.cfg.timeout_ms)
                    await asyncio.sleep(1.5)
                except Exception as e:
                    log.warning("warmup failed: %s", e)

                total = len(urls)
                for i, url in enumerate(urls, 1):
                    try:
                        resp = await page.goto(url, wait_until="domcontentloaded", timeout=self.cfg.timeout_ms)
                        if resp and resp.status >= 400:
                            log.warning("detail %d/%d HTTP %d %s", i, total, resp.status, url[:80])
                            continue
                        # 等價格區塊渲染
                        try:
                            await page.wait_for_selector(".price-amount", timeout=10000)
                        except Exception:
                            pass
                        await asyncio.sleep(0.3)
                        out[url] = await page.content()
                        if i % 10 == 0 or i == total:
                            log.info("detail %d/%d done", i, total)
                    except Exception as e:
                        log.warning("detail %d/%d fail %s: %s", i, total, url[:60], e)
                    await asyncio.sleep(random.uniform(1.5, 3.0))
            finally:
                await browser.close()

        return out
