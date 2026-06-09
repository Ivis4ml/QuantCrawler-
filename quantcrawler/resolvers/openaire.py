"""OpenAIRE 解析器：按 DOI 查询开放获取 PDF。

OpenAIRE 聚合了大量欧洲及全球机构库 / 工作论文仓库的开放副本，能补回一部分
Unpaywall / Semantic Scholar / arXiv 都没命中的 OA（如机构库、央行工作论文）。仅当
bestaccessright 为 OPEN 时采用，并排除出版社付费墙域名、优先 .pdf 直链。下载器仍会
校验 %PDF，故即便偶有落地页混入也会被安全跳过。
"""

from __future__ import annotations

import logging

from ..http import HttpClient

log = logging.getLogger("quantcrawler.resolvers.openaire")

BASE = "https://api.openaire.eu/search/publications"

# 出版社付费墙域名：这些链接多被反爬拦截，不作为 OA 候选。
_PUBLISHER_HOSTS = (
    "doi.org", "dx.doi.org", "academic.oup.com", "onlinelibrary.wiley.com",
    "sciencedirect.com", "tandfonline.com", "link.springer.com", "jstor.org",
    "pubsonline.informs.org", "journals.sagepub.com", "www.nature.com",
)


def _normalize_doi(doi: str) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi or None


def _collect_urls(obj, out: list[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_urls(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_urls(v, out)
    elif isinstance(obj, str) and obj.startswith("http"):
        out.append(obj)


def resolve_openaire(http: HttpClient, doi: str | None) -> tuple[str, str] | None:
    norm = _normalize_doi(doi or "")
    if not norm:
        return None
    resp = http.get(BASE, params={"doi": norm, "format": "json", "size": 1})
    if resp is None or resp.status_code != 200:
        return None
    # 必须是开放获取
    if '"@classid" : "OPEN"' not in resp.text and '"@classid":"OPEN"' not in resp.text:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None

    urls: list[str] = []
    _collect_urls(data, urls)
    # 优先 .pdf 直链；排除出版社付费墙域名与 doi 链接；去重保序
    seen: set[str] = set()
    pdfs: list[str] = []
    for u in urls:
        lu = u.lower()
        if any(h in lu for h in _PUBLISHER_HOSTS):
            continue
        if ".pdf" not in lu:
            continue
        if u not in seen:
            seen.add(u)
            pdfs.append(u)
    return ("openaire", pdfs[0]) if pdfs else None
