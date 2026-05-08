"""讀取 config.yaml 的薄層。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RegionCfg:
    id: str
    name: str
    urls: list[str]    # 一或多個 URL，全部抓回後去重


@dataclass
class AppConfig:
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "AppConfig":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"找不到 {p}。請從 config.yaml.template 複製並修改。"
            )
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(raw=data)

    # accessors
    @property
    def base_url(self) -> str:
        return self.raw.get("site", {}).get("base_url", "https://www.tw.coupang.com")

    @property
    def regions(self) -> list[RegionCfg]:
        out = []
        for r in self.raw.get("regions", []):
            urls = r.get("urls")
            if not urls:
                u = r.get("url", "")
                urls = [u] if u else []
            out.append(RegionCfg(id=r["id"], name=r["name"], urls=urls))
        return out

    @property
    def max_price_ratio_pct(self) -> float:
        return float(self.raw.get("filter", {}).get("max_price_ratio_pct", 90))

    @property
    def rocket_global_only(self) -> bool:
        return bool(self.raw.get("filter_rocket_global_only", True))

    @property
    def use_detail_price(self) -> bool:
        """訪問商品詳情頁取「無首購折扣」一般售價。預設 True。"""
        return bool(self.raw.get("use_detail_price", True))

    @property
    def scraper_cfg(self) -> dict:
        return self.raw.get("scraper", {})

    @property
    def db_path(self) -> str:
        return self.raw.get("storage", {}).get("db_path", "data/deals.db")

    @property
    def retention_days(self) -> int:
        return int(self.raw.get("storage", {}).get("retention_days", 30))

    @property
    def translation_cfg(self) -> dict:
        return self.raw.get("translation", {})

    @property
    def telegram_cfg(self) -> dict:
        return self.raw.get("telegram", {})

    @property
    def log_dir(self) -> str:
        return self.raw.get("logging", {}).get("log_dir", "logs")

    @property
    def log_level(self) -> str:
        return self.raw.get("logging", {}).get("level", "INFO")

    @property
    def streamlit_cfg(self) -> dict:
        return self.raw.get("streamlit", {})
