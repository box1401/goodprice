"""SQLite 資料層。

schema 設計：
- deals: 每件商品每日一筆，可看歷史價格演進
- 同 (product_id, scrape_date) 視為同一筆 → upsert
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .parser import Deal


SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      TEXT    NOT NULL,
    region          TEXT    NOT NULL,         -- 'KR' | 'US'
    title_orig      TEXT    NOT NULL,
    title_zh        TEXT,
    image_url       TEXT,
    original_price  INTEGER,
    sale_price      INTEGER NOT NULL,
    discount_pct    REAL    NOT NULL,         -- (1 - sale/original) * 100
    sale_start      TEXT,                     -- ISO date
    sale_end        TEXT,
    url             TEXT    NOT NULL,
    scrape_date     TEXT    NOT NULL,         -- ISO date, 抓取日
    scraped_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(product_id, scrape_date)
);

CREATE INDEX IF NOT EXISTS idx_deals_discount   ON deals(discount_pct DESC);
CREATE INDEX IF NOT EXISTS idx_deals_scrape     ON deals(scrape_date DESC);
CREATE INDEX IF NOT EXISTS idx_deals_region     ON deals(region);
CREATE INDEX IF NOT EXISTS idx_deals_sale_end   ON deals(sale_end);
"""

# 既存 DB 升級：缺欄則補
MIGRATIONS = [
    ("image_url", "ALTER TABLE deals ADD COLUMN image_url TEXT"),
]


class DealDB:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)
            # 補欄位 (idempotent)
            existing = {r[1] for r in c.execute("PRAGMA table_info(deals)").fetchall()}
            for col, sql in MIGRATIONS:
                if col not in existing:
                    try:
                        c.execute(sql)
                    except sqlite3.OperationalError:
                        pass  # already exists

    # ---------- write ----------

    def upsert_many(self, deals: Iterable[Deal], scrape_date: Optional[date] = None) -> int:
        """寫入或更新；同 (product_id, scrape_date) 會被覆寫。回傳新增/更新筆數。"""
        d = (scrape_date or date.today()).isoformat()
        rows = []
        for x in deals:
            rec = asdict(x)
            rec["scrape_date"] = d
            rec["sale_start"] = x.sale_start.isoformat() if x.sale_start else None
            rec["sale_end"] = x.sale_end.isoformat() if x.sale_end else None
            rows.append(rec)

        if not rows:
            return 0

        sql = """
        INSERT INTO deals
            (product_id, region, title_orig, title_zh, image_url, original_price,
             sale_price, discount_pct, sale_start, sale_end, url, scrape_date)
        VALUES
            (:product_id, :region, :title_orig, :title_zh, :image_url, :original_price,
             :sale_price, :discount_pct, :sale_start, :sale_end, :url, :scrape_date)
        ON CONFLICT(product_id, scrape_date) DO UPDATE SET
            title_orig     = excluded.title_orig,
            title_zh       = excluded.title_zh,
            image_url      = excluded.image_url,
            original_price = excluded.original_price,
            sale_price     = excluded.sale_price,
            discount_pct   = excluded.discount_pct,
            sale_start     = excluded.sale_start,
            sale_end       = excluded.sale_end,
            url            = excluded.url,
            scraped_at     = datetime('now', 'localtime')
        """
        with self._conn() as c:
            c.executemany(sql, rows)
        return len(rows)

    def purge_older_than(self, days: int) -> int:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        with self._conn() as c:
            cur = c.execute("DELETE FROM deals WHERE scrape_date < ?", (cutoff,))
            return cur.rowcount

    def dedupe_keep_latest(self) -> int:
        """同 product_id 只保留最新一筆 (以 id 為準，AUTOINCREMENT 單調遞增)。回傳刪除筆數。"""
        with self._conn() as c:
            cur = c.execute(
                """
                DELETE FROM deals
                WHERE id NOT IN (
                    SELECT MAX(id) FROM deals GROUP BY product_id
                )
                """
            )
            return cur.rowcount

    # ---------- read ----------

    def list_today(self, scrape_date: Optional[date] = None, top_n: Optional[int] = None) -> list[sqlite3.Row]:
        d = (scrape_date or date.today()).isoformat()
        sql = "SELECT * FROM deals WHERE scrape_date = ? ORDER BY discount_pct DESC"
        params: list = [d]
        if top_n:
            sql += " LIMIT ?"
            params.append(top_n)
        with self._conn() as c:
            return c.execute(sql, params).fetchall()

    def query(
        self,
        *,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        region: Optional[str] = None,
        min_discount: Optional[float] = None,
        order_by: str = "discount_pct",
        descending: bool = True,
        limit: Optional[int] = None,
    ) -> list[sqlite3.Row]:
        clauses, params = [], []
        if date_from:
            clauses.append("scrape_date >= ?"); params.append(date_from.isoformat())
        if date_to:
            clauses.append("scrape_date <= ?"); params.append(date_to.isoformat())
        if region and region != "ALL":
            clauses.append("region = ?"); params.append(region)
        if min_discount is not None:
            clauses.append("discount_pct >= ?"); params.append(min_discount)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        # whitelist 排序欄，避免 SQL injection
        order_col = order_by if order_by in {
            "discount_pct", "sale_price", "original_price", "scrape_date", "sale_end"
        } else "discount_pct"
        direction = "DESC" if descending else "ASC"

        sql = f"SELECT * FROM deals {where} ORDER BY {order_col} {direction}"
        if limit:
            sql += f" LIMIT {int(limit)}"

        with self._conn() as c:
            return c.execute(sql, params).fetchall()

    def stats(self) -> dict:
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
            today = c.execute(
                "SELECT COUNT(*) FROM deals WHERE scrape_date = ?",
                (date.today().isoformat(),),
            ).fetchone()[0]
            latest = c.execute("SELECT MAX(scrape_date) FROM deals").fetchone()[0]
        return {"total": total, "today": today, "latest_scrape_date": latest}
