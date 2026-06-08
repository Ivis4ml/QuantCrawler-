"""SQLite catalog：papers 与 journals 表。所有写入幂等（按主键 upsert）。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import Paper

_JSON_FIELDS = ("authors", "topics")

# papers 表列定义为单一事实来源，同时驱动 CREATE TABLE 与对旧库的补列迁移。
# 新增列只需在此追加一行，_migrate 会对缺列的旧库自动 ADD COLUMN。
_PAPERS_COLUMNS: list[tuple[str, str]] = [
    ("openalex_id", "TEXT PRIMARY KEY"),
    ("journal_slug", "TEXT"),
    ("journal_name", "TEXT"),
    ("doi", "TEXT"),
    ("title", "TEXT"),
    ("authors", "TEXT"),
    ("publication_year", "INTEGER"),
    ("publication_date", "TEXT"),
    ("abstract", "TEXT"),
    ("primary_topic", "TEXT"),
    ("topics", "TEXT"),
    ("oa_status", "TEXT"),
    ("cited_by_count", "INTEGER"),
    ("is_quant", "INTEGER"),
    ("relevance_reason", "TEXT"),
    ("selected", "INTEGER DEFAULT 0"),
    ("pdf_source", "TEXT"),
    ("pdf_url", "TEXT"),
    ("pdf_landing", "TEXT"),
    ("pdf_path", "TEXT"),
    ("sha256", "TEXT"),
    ("download_status", "TEXT"),
    ("error", "TEXT"),
    ("harvested_at", "TEXT"),
    ("updated_at", "TEXT"),
]

_SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS journals (
    slug         TEXT PRIMARY KEY,
    name         TEXT,
    issn         TEXT,
    category     TEXT,
    include_all  INTEGER,
    source_id    TEXT,
    works_count  INTEGER,
    resolved_at  TEXT
);

CREATE TABLE IF NOT EXISTS papers (
"""
    + ",\n".join(f"    {name:18s}{decl}" for name, decl in _PAPERS_COLUMNS)
    + "\n);\n"
)

# 索引在补列迁移之后创建（其中部分引用后加的列）。
_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_papers_journal ON papers(journal_slug);
CREATE INDEX IF NOT EXISTS idx_papers_quant ON papers(is_quant);
CREATE INDEX IF NOT EXISTS idx_papers_dl ON papers(download_status);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_sel ON papers(selected);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(journal_slug, publication_year);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Catalog:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.executescript(_INDEXES)
        self.conn.commit()

    def _migrate(self) -> None:
        """对旧库补齐 _PAPERS_COLUMNS 中缺失的列（主键列必在基表，跳过）。"""
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(papers)").fetchall()}
        for name, decl in _PAPERS_COLUMNS:
            if name not in existing and "PRIMARY KEY" not in decl:
                self.conn.execute(f"ALTER TABLE papers ADD COLUMN {name} {decl}")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------- journals ----------
    def upsert_journal(
        self, slug: str, name: str, issn: str, category: str,
        include_all: bool, source_id: str | None, works_count: int | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO journals (slug, name, issn, category, include_all, source_id, works_count, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name, issn=excluded.issn, category=excluded.category,
                include_all=excluded.include_all, source_id=excluded.source_id,
                works_count=excluded.works_count, resolved_at=excluded.resolved_at
            """,
            (slug, name, issn, category, int(include_all), source_id, works_count, _now()),
        )
        self.conn.commit()

    def get_journal_source(self, slug: str) -> str | None:
        row = self.conn.execute(
            "SELECT source_id FROM journals WHERE slug=?", (slug,)
        ).fetchone()
        return row["source_id"] if row else None

    # ---------- papers ----------
    def _serialize(self, paper: Paper) -> dict[str, Any]:
        row = paper.to_row()
        for f in _JSON_FIELDS:
            row[f] = json.dumps(row[f], ensure_ascii=False)
        row["is_quant"] = int(bool(row["is_quant"]))
        row["selected"] = int(bool(row["selected"]))
        return row

    def upsert_paper(self, paper: Paper) -> None:
        self.upsert_papers([paper])

    def upsert_papers(self, papers: Iterable[Paper]) -> int:
        rows = [self._serialize(p) for p in papers]
        if not rows:
            return 0
        cols = list(rows[0].keys())
        # 采集阶段不覆盖下载结果与挑选结果字段（断点续跑安全）。
        # cited_by_count 不在此列：重采时应刷新引用数。
        preserve = {"pdf_source", "pdf_url", "pdf_path", "sha256",
                    "download_status", "error", "selected"}
        set_clause = ", ".join(
            f"{c}=excluded.{c}" for c in cols
            if c not in preserve and c != "openalex_id"
        )
        placeholders = ", ".join(["?"] * len(cols))
        sql = (
            f"INSERT INTO papers ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(openalex_id) DO UPDATE SET {set_clause}, updated_at=excluded.updated_at"
        )
        now = _now()
        for r in rows:
            r["updated_at"] = now
            if not r.get("harvested_at"):
                r["harvested_at"] = now
        self.conn.executemany(sql, [[r[c] for c in cols] for r in rows])
        self.conn.commit()
        return len(rows)

    def update_pdf_result(
        self, openalex_id: str, *, pdf_source: str | None, pdf_url: str | None,
        pdf_landing: str | None = None, pdf_path: str | None = None,
        sha256: str | None = None, download_status: str, error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE papers SET pdf_source=?, pdf_url=?, pdf_landing=COALESCE(?, pdf_landing),
                   pdf_path=?, sha256=?, download_status=?, error=?, updated_at=?
            WHERE openalex_id=?
            """,
            (pdf_source, pdf_url, pdf_landing, pdf_path, sha256,
             download_status, error, _now(), openalex_id),
        )
        self.conn.commit()

    def iter_papers(self, where: str = "", params: tuple = ()) -> list[sqlite3.Row]:
        sql = "SELECT * FROM papers"
        if where:
            sql += " WHERE " + where
        return self.conn.execute(sql, params).fetchall()

    def select_top_per_year(
        self, top_per_year: int, since_year: int, until_year: int,
        order_col: str = "cited_by_count",
    ) -> dict[str, int]:
        """每个（期刊, 年份）单元内，对量化论文按 order_col 降序取前 N，置 selected=1。

        先把范围内所有量化论文 selected 归零，再按窗口函数排名标记前 N。返回
        {selected, eligible} 统计。NULL 的 order_col 排在最后。
        """
        scope = (
            "is_quant=1 AND publication_year>=? AND publication_year<=?"
        )
        sp = (since_year, until_year)
        # 重置范围内的挑选标记，保证幂等可重跑（如调整 N）。
        self.conn.execute(f"UPDATE papers SET selected=0 WHERE {scope}", sp)
        self.conn.execute(
            f"""
            WITH ranked AS (
                SELECT openalex_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY journal_slug, publication_year
                           ORDER BY COALESCE({order_col}, -1) DESC, openalex_id ASC
                       ) AS rk
                FROM papers
                WHERE {scope}
            )
            UPDATE papers SET selected=1
            WHERE openalex_id IN (SELECT openalex_id FROM ranked WHERE rk<=?)
            """,
            (*sp, top_per_year),
        )
        self.conn.commit()
        eligible = self.conn.execute(
            f"SELECT COUNT(*) FROM papers WHERE {scope}", sp
        ).fetchone()[0]
        selected = self.conn.execute(
            f"SELECT COUNT(*) FROM papers WHERE {scope} AND selected=1", sp
        ).fetchone()[0]
        return {"eligible": eligible, "selected": selected}

    def counts(self) -> dict[str, Any]:
        c = self.conn
        out: dict[str, Any] = {}
        out["total"] = c.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        out["quant"] = c.execute("SELECT COUNT(*) FROM papers WHERE is_quant=1").fetchone()[0]
        out["selected"] = c.execute("SELECT COUNT(*) FROM papers WHERE selected=1").fetchone()[0]
        # 下载状态以入选论文为口径（若尚未 select，回退到全部量化论文）。
        scope = "selected=1" if out["selected"] else "is_quant=1"
        out["by_status"] = {
            row[0]: row[1]
            for row in c.execute(
                f"SELECT download_status, COUNT(*) FROM papers WHERE {scope} GROUP BY download_status"
            ).fetchall()
        }
        out["by_journal"] = {
            row[0]: row[1]
            for row in c.execute(
                f"SELECT journal_slug, COUNT(*) FROM papers WHERE {scope} GROUP BY journal_slug"
            ).fetchall()
        }
        return out
