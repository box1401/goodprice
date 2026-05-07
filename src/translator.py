"""標題翻譯。

策略：
- 偵測為主要 CJK 漢字 → 視為已是中文，跳過
- 韓文 (Hangul) / 日文 / 英文 → 走 Google free 端點 (deep-translator)
- 失敗時靜默 fallback：title_zh = title_orig
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterable, Optional

log = logging.getLogger(__name__)


_HANGUL = re.compile(r"[가-힯]")
_HIRAGANA_KATAKANA = re.compile(r"[぀-ヿ]")
_CJK_HAN = re.compile(r"[一-鿿]")
_ASCII_LETTER = re.compile(r"[A-Za-z]")


def detect_lang_simple(text: str) -> str:
    """回傳 'ko' | 'ja' | 'zh' | 'en' | 'mixed'。粗略夠用。
    Coupang 台灣標題常為中英混排（例「CAFE REAL 水蜜桃冰茶」），
    只要含 ≥3 個漢字即視為已是中文，避免徒勞翻譯。
    """
    if not text:
        return "en"
    if _HANGUL.search(text):
        return "ko"
    if _HIRAGANA_KATAKANA.search(text):
        return "ja"
    han = len(_CJK_HAN.findall(text))
    ascii_n = len(_ASCII_LETTER.findall(text))
    if han >= 3:
        return "zh"
    if han >= 2 and han >= ascii_n:
        return "zh"
    if ascii_n > 0:
        return "en"
    return "mixed"


class Translator:
    def __init__(self, *, enabled: bool = True, target: str = "zh-TW", skip_if_chinese: bool = True):
        self.enabled = enabled
        self.target = target
        self.skip_if_chinese = skip_if_chinese
        self._engine = None
        if enabled:
            try:
                from deep_translator import GoogleTranslator
                self._GoogleTranslator = GoogleTranslator
            except ImportError:
                log.warning("deep-translator 未安裝，停用翻譯")
                self.enabled = False

    def _engine_for(self, src: str):
        # GoogleTranslator 每次建立成本低，但快取 source 配對較穩
        return self._GoogleTranslator(source=src, target=self.target)

    def translate_one(self, text: str) -> Optional[str]:
        if not self.enabled or not text:
            return None
        lang = detect_lang_simple(text)
        if self.skip_if_chinese and lang == "zh":
            return text  # 已是中文，原樣回傳當作 title_zh
        src = {"ko": "ko", "ja": "ja", "en": "en"}.get(lang, "auto")
        try:
            return self._engine_for(src).translate(text)
        except Exception as e:
            log.warning("translate failed (%s → %s): %s", src, self.target, e)
            return None

    def translate_batch(self, texts: Iterable[str], *, sleep_per: float = 0.2) -> list[Optional[str]]:
        """一個個翻；deep-translator 沒有真 batch API。
        加 sleep 避免 Google 限額。
        """
        out: list[Optional[str]] = []
        for t in texts:
            out.append(self.translate_one(t))
            if sleep_per > 0:
                time.sleep(sleep_per)
        return out


def attach_zh_titles(deals: list, translator: Translator) -> None:
    """直接 mutate deals[i].title_zh。"""
    if not translator.enabled:
        for d in deals:
            d.title_zh = d.title_zh or d.title_orig
        return
    titles = [d.title_orig for d in deals]
    translated = translator.translate_batch(titles)
    for d, zh in zip(deals, translated):
        d.title_zh = zh or d.title_orig
