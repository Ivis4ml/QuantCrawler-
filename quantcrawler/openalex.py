"""OpenAlex 客户端：source 解析、works 游标分页迭代、摘要重建。"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from .http import HttpClient

log = logging.getLogger("quantcrawler.openalex")

BASE = "https://api.openalex.org"

# 仅拉取需要的字段，减少响应体积。
_WORK_SELECT = ",".join([
    "id", "doi", "title", "display_name", "publication_year", "publication_date",
    "type", "authorships", "open_access", "primary_location", "locations",
    "best_oa_location", "primary_topic", "topics", "abstract_inverted_index",
    "cited_by_count",
])


def reconstruct_abstract(inv: dict[str, list[int]] | None) -> str | None:
    """从 OpenAlex abstract_inverted_index 重建摘要文本。"""
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    if not pos:
        return None
    return " ".join(pos[i] for i in sorted(pos))


def authors_of(work: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for a in work.get("authorships", []) or []:
        author = a.get("author") or {}
        name = author.get("display_name")
        if name:
            out.append(name)
    return out


def topic_names(work: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for t in work.get("topics", []) or []:
        name = t.get("display_name")
        if name:
            out.append(name)
    return out


class OpenAlex:
    def __init__(self, http: HttpClient, mailto: str):
        self.http = http
        self.mailto = mailto

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        p = {"mailto": self.mailto}
        p.update(extra)
        return p

    def resolve_source(self, issn: str) -> dict[str, Any] | None:
        """按 ISSN 解析 OpenAlex source，返回 {id, works_count, issn_l, display_name}。"""
        resp = self.http.get(
            f"{BASE}/sources", params=self._params({"filter": f"issn:{issn}"})
        )
        if resp is None or resp.status_code != 200:
            return None
        results = resp.json().get("results", [])
        if not results:
            return None
        s = results[0]
        return {
            "id": s["id"],
            "works_count": s.get("works_count"),
            "issn_l": s.get("issn_l"),
            "display_name": s.get("display_name"),
        }

    def count_works(self, source_key: str, since: str, work_types: list[str],
                    until: str | None = None) -> int:
        flt = self._works_filter(source_key, since, work_types, until)
        resp = self.http.get(
            f"{BASE}/works", params=self._params({"filter": flt, "per-page": 1})
        )
        if resp is None or resp.status_code != 200:
            return -1
        return resp.json().get("meta", {}).get("count", -1)

    def iter_works(
        self, source_key: str, since: str, work_types: list[str],
        until: str | None = None, per_page: int = 200,
    ) -> Iterator[dict[str, Any]]:
        """游标分页迭代某 source 在 [since, until] 窗口内的全部 works。"""
        flt = self._works_filter(source_key, since, work_types, until)
        cursor = "*"
        while cursor:
            resp = self.http.get(
                f"{BASE}/works",
                params=self._params({
                    "filter": flt, "per-page": per_page,
                    "cursor": cursor, "select": _WORK_SELECT,
                }),
            )
            if resp is None or resp.status_code != 200:
                log.warning("works 迭代中断，source=%s cursor=%s", source_key, cursor)
                return
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return
            for w in results:
                yield w
            cursor = data.get("meta", {}).get("next_cursor")

    @staticmethod
    def _works_filter(source_key: str, since: str, work_types: list[str],
                      until: str | None = None) -> str:
        parts = [
            f"primary_location.source.id:{source_key}",
            f"from_publication_date:{since}",
        ]
        if until:
            parts.append(f"to_publication_date:{until}")
        if work_types:
            parts.append("type:" + "|".join(work_types))
        return ",".join(parts)


def pdf_urls_from_work(work: dict[str, Any]) -> list[str]:
    """从 work 的各 location 抽取候选 PDF 直链，去重保序。"""
    urls: list[str] = []

    def add(u: str | None) -> None:
        if u and u not in urls:
            urls.append(u)

    for key in ("best_oa_location", "primary_location"):
        loc = work.get(key) or {}
        add(loc.get("pdf_url"))
    for loc in work.get("locations", []) or []:
        add(loc.get("pdf_url"))
    oa = work.get("open_access") or {}
    add(oa.get("oa_url"))
    return urls


def landing_of(work: dict[str, Any]) -> str | None:
    pl = work.get("primary_location") or {}
    return pl.get("landing_page_url") or work.get("doi")
