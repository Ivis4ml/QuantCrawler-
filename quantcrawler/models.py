"""数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Paper:
    """一篇论文的规范化记录，对应 SQLite papers 表一行。"""

    openalex_id: str
    journal_slug: str
    journal_name: str
    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    publication_year: int | None = None
    publication_date: str | None = None
    abstract: str | None = None
    primary_topic: str | None = None
    topics: list[str] = field(default_factory=list)
    oa_status: str | None = None  # OpenAlex open_access.oa_status: gold/green/hybrid/bronze/closed
    cited_by_count: int | None = None

    # 相关性与挑选
    is_quant: bool = False
    relevance_reason: str | None = None
    selected: bool = False  # 是否在每刊每年前 top_per_year 之内

    # PDF 解析与下载
    pdf_source: str | None = None       # openalex / unpaywall / arxiv / none
    pdf_url: str | None = None
    pdf_landing: str | None = None      # 落地页（即使没有 PDF 也记录）
    pdf_path: str | None = None
    sha256: str | None = None
    download_status: str = "pending"    # pending / downloaded / paywalled / failed
    error: str | None = None

    harvested_at: str | None = None
    updated_at: str | None = None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
