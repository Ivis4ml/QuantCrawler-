"""Semantic Scholar 解析器：按 DOI 查询开放获取 PDF。

Semantic Scholar 的 openAccessPdf 覆盖了一部分 Unpaywall / arXiv 标题匹配漏掉的开放
副本（常见为 arXiv、机构库、PMC 直链），是有效的补充 OA 来源。无需密钥（未认证时
约 1 rps，由 host 限速控制）。
"""

from __future__ import annotations

import logging

from ..http import HttpClient

log = logging.getLogger("quantcrawler.resolvers.semantic_scholar")

BASE = "https://api.semanticscholar.org/graph/v1/paper"


def _normalize_doi(doi: str) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi or None


def resolve_semantic_scholar(http: HttpClient, doi: str | None) -> tuple[str, str] | None:
    norm = _normalize_doi(doi or "")
    if not norm:
        return None
    resp = http.get(f"{BASE}/DOI:{norm}", params={"fields": "openAccessPdf"})
    if resp is None or resp.status_code != 200:
        return None
    oa = (resp.json() or {}).get("openAccessPdf") or {}
    url = oa.get("url")
    return ("semanticscholar", url) if url else None
