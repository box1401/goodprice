"""Telegram 通知。

純 requests，不引入 python-telegram-bot 整套。
- 有 image_url 的商品走 sendPhoto + caption
- 無圖商品走 sendMessage
- 失敗一筆不阻斷其他筆
- 每筆間 1 秒延遲，避免 rate limit (Bot API 1 msg/sec/chat)
- 無 emoji（依使用者全域偏好）
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterable, Optional

import requests

log = logging.getLogger(__name__)

TG_API_PHOTO   = "https://api.telegram.org/bot{token}/sendPhoto"
TG_API_MESSAGE = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MSG_LEN     = 4000
MAX_CAPTION_LEN = 1024


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U00002600-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "⌀-⏿"
    "]+",
    flags=re.UNICODE,
)


def strip_emoji(s: str) -> str:
    return _EMOJI_RE.sub("", s)


def _escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramNotifier:
    def __init__(self, *, bot_token: str, chat_id: str, enabled: bool = True, no_emoji: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(enabled and bot_token and chat_id)
        self.no_emoji = no_emoji
        self._session = requests.Session()

    # ---------- low level ----------

    def _post(self, url: str, payload: dict) -> bool:
        try:
            r = self._session.post(url, json=payload, timeout=30)
            if r.ok:
                return True
            log.warning("telegram %d: %s", r.status_code, r.text[:200])
            # 429 too many requests: 多等一下
            if r.status_code == 429:
                try:
                    retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                except Exception:
                    retry_after = 5
                time.sleep(min(retry_after, 30))
            return False
        except requests.RequestException as e:
            log.warning("telegram error: %s", e)
            return False

    def send(self, text: str) -> bool:
        """送純文字訊息。長文自動分批。"""
        if not self.enabled:
            log.info("telegram disabled, skip")
            return False
        if self.no_emoji:
            text = strip_emoji(text)
        url = TG_API_MESSAGE.format(token=self.bot_token)
        ok = True
        for chunk in _split_message(text, MAX_MSG_LEN):
            if not self._post(url, {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }):
                ok = False
            time.sleep(1.0)
        return ok

    def send_photo(self, photo_url: str, caption: str) -> bool:
        """送單張圖片 + caption。"""
        if not self.enabled:
            return False
        if self.no_emoji:
            caption = strip_emoji(caption)
        if len(caption) > MAX_CAPTION_LEN:
            caption = caption[: MAX_CAPTION_LEN - 1] + "…"
        return self._post(TG_API_PHOTO.format(token=self.bot_token), {
            "chat_id": self.chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML",
        })

    # ---------- high level ----------

    def push_deals(self, deals: Iterable, *, top_n: int = 50, header: str = "") -> tuple[int, int]:
        """逐筆推送。回傳 (成功數, 失敗數)。"""
        items = list(deals)[:top_n]

        # 先送 header (若有)
        if header:
            self.send(f"<b>{_escape(header)}</b>\n共 {len(items)} 筆")

        ok = fail = 0
        for i, d in enumerate(items, 1):
            caption = _format_caption(d, idx=i, total=len(items))
            if d.image_url:
                if self.send_photo(d.image_url, caption):
                    ok += 1
                else:
                    # 圖失敗 fallback 純文字
                    if self.send(caption):
                        ok += 1
                    else:
                        fail += 1
            else:
                if self.send(caption):
                    ok += 1
                else:
                    fail += 1
            time.sleep(1.1)  # rate limit 1/sec/chat
        return ok, fail


def _split_message(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, buf, cur = [], [], 0
    for line in text.splitlines(keepends=True):
        if cur + len(line) > limit:
            out.append("".join(buf))
            buf, cur = [line], len(line)
        else:
            buf.append(line); cur += len(line)
    if buf:
        out.append("".join(buf))
    return out


def _format_caption(d, *, idx: int, total: int) -> str:
    """單筆 caption（HTML）。"""
    title = d.title_zh or d.title_orig
    op = f"NT${d.original_price:,}" if d.original_price else "—"
    sp = f"NT${d.sale_price:,}"
    pct = f"-{d.discount_pct:.0f}%"
    period = ""
    if d.sale_start and d.sale_end:
        period = f"\n期間 {d.sale_start.isoformat()} ~ {d.sale_end.isoformat()}"
    elif d.sale_end:
        period = f"\n到期 {d.sale_end.isoformat()}"

    return (
        f"<b>{idx}/{total}  [{d.region}]  {pct}</b>\n"
        f"{_escape(title)}\n"
        f"{op} → <b>{sp}</b>{period}\n"
        f"<a href=\"{_escape(d.url)}\">商品連結</a>"
    )


# 保留舊 API 以免其他地方 import 壞掉
def format_deals_message(deals: Iterable, *, top_n: int = 50, header: str = "") -> str:
    """組純文字訊息（舊版 fallback 用）。"""
    items = list(deals)[:top_n]
    lines: list[str] = []
    if header:
        lines.append(f"<b>{_escape(header)}</b>")
        lines.append("")
    for i, d in enumerate(items, 1):
        lines.append(_format_caption(d, idx=i, total=len(items)))
        lines.append("")
    return "\n".join(lines).rstrip()
