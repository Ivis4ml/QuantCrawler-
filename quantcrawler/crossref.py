"""Crossref 采集通路：用于 OpenAlex 收录不完整的期刊（如 Review of Finance）。

按 ISSN 游标分页拉取 journal-article，映射为标准字段。引用数用
`is-referenced-by-count`，摘要在可得时从 JATS 标签清洗为纯文本。Crossref 不提供
OpenAlex 式主题，故这类期刊的量化筛选主要依赖标题 / 摘要关键词。
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Iterator

from .http import HttpClient

log = logging.getLogger("quantcrawler.crossref")

BASE = "https://api.crossref.org"
_TAG_RE = re.compile(r"<[^>]+>")
_JATS_PREFIX_RE = re.compile(r"^\s*(abstract|summary)\s*", re.IGNORECASE)


def _clean_abstract(raw: str | None) -> str | None:
    if not raw:
        return None
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = _JATS_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _year_date(item: dict[str, Any]) -> tuple[int | None, str | None]:
    for key in ("published", "published-online", "published-print", "issued"):
        block = item.get(key) or {}
        parts = block.get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            dp = parts[0]
            y = dp[0]
            m = dp[1] if len(dp) > 1 else 1
            d = dp[2] if len(dp) > 2 else 1
            return int(y), f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return None, None


def _authors(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for a in item.get("author", []) or []:
        name = " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        if not name:
            name = a.get("name") or ""
        if name:
            out.append(name)
    return out


class Crossref:
    def __init__(self, http: HttpClient, mailto: str):
        self.http = http
        self.mailto = mailto

    def iter_works(
        self, issn: str, since: str, until: str | None, rows: int = 200,
    ) -> Iterator[dict[str, Any]]:
        """游标分页迭代某 ISSN 在 [since, until] 内的 journal-article。

        产出已映射为统一字段的 dict（与 OpenAlex 通路保持相同键名子集）。
        """
        filt = f"from-pub-date:{since},type:journal-article"
        if until:
            filt += f",until-pub-date:{until}"
        cursor = "*"
        while cursor:
            resp = self.http.get(
                f"{BASE}/journals/{issn}/works",
                params={"filter": filt, "rows": rows, "cursor": cursor, "mailto": self.mailto},
            )
            if resp is None or resp.status_code != 200:
                log.warning("Crossref 迭代中断，issn=%s", issn)
                return
            msg = resp.json().get("message", {})
            items = msg.get("items", [])
            if not items:
                return
            for it in items:
                yield self._map(it)
            cursor = msg.get("next-cursor")

    @staticmethod
    def _map(item: dict[str, Any]) -> dict[str, Any]:
        year, date = _year_date(item)
        title_list = item.get("title") or []
        title = title_list[0] if title_list else None
        doi = item.get("DOI")
        return {
            "id": f"crossref:{doi}" if doi else f"crossref:{item.get('URL', '')}",
            "doi": f"https://doi.org/{doi}" if doi else None,
            "title": title,
            "authors": _authors(item),
            "publication_year": year,
            "publication_date": date,
            "abstract": _clean_abstract(item.get("abstract")),
            "cited_by_count": item.get("is-referenced-by-count"),
            "landing": item.get("URL"),
        }
