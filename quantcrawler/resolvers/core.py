"""CORE 解析器：按 DOI 查询开放获取 PDF。

CORE（core.ac.uk）聚合了全球一万多个机构库、预印本与期刊出版商的开放副本，是规模
最大的开放获取全文聚合器之一。对仍处付费墙、且 Unpaywall / Semantic Scholar /
OpenAIRE / arXiv 均未命中的论文，CORE 常能补回一份机构库或作者自存档副本（如大学
ZORA、SSRN 自存档），以及 CORE 自身托管的 `core.ac.uk/download/<id>.pdf` 直链（不经
出版社 Cloudflare 拦截）。

注意：CORE 返回的 `downloadUrl` 并不可靠，常指向出版社付费接口（dx.doi.org、
api.elsevier.com、informs、cambridge 等）。故与 OpenAIRE 同样过滤出版社付费墙域名，
优先取 core.ac.uk 托管直链与机构库 .pdf 链接。下载器仍会校验 %PDF 魔数，落地页混入
也会被安全跳过。

鉴权：CORE v3 接口匿名可用，但限速极严（易触发 429）。设置环境变量 CORE_API_KEY
（在 https://core.ac.uk/services/api 免费注册获取）后以 Bearer 提交，可提升配额与吞吐。
"""

from __future__ import annotations

import logging
import os

from ..http import HttpClient

log = logging.getLogger("quantcrawler.resolvers.core")

# 路径必须带尾斜杠，否则服务端 301 重定向（HttpClient 默认跟随，但直接命中更省一跳）。
BASE = "https://api.core.ac.uk/v3/search/works/"

# 出版社付费墙 / 非开放接口域名：CORE 的 downloadUrl 常落到这些链接，不作为 OA 候选。
_PUBLISHER_HOSTS = (
    "doi.org", "dx.doi.org", "api.elsevier.com", "linkinghub.elsevier.com",
    "sciencedirect.com", "academic.oup.com", "onlinelibrary.wiley.com",
    "tandfonline.com", "link.springer.com", "jstor.org",
    "pubsonline.informs.org", "journals.sagepub.com", "www.nature.com",
    "cambridge.org", "api.crossref.org",
)


def _normalize_doi(doi: str) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi or None


def _is_publisher(url: str) -> bool:
    lu = url.lower()
    return any(h in lu for h in _PUBLISHER_HOSTS)


def _rank(url: str) -> int:
    """候选可靠性排序：CORE 自托管直链 < 机构库 .pdf < 其他开放链接。"""
    lu = url.lower()
    if "core.ac.uk/download" in lu:
        return 0          # CORE 自托管直链，最可靠，不经出版社 Cloudflare
    if ".pdf" in lu:
        return 1          # 机构库 / 自存档 .pdf
    return 2


def core_candidates(work: dict) -> list[str]:
    """从一条 CORE work 记录中提取经过滤、去重、按可靠性排序的开放获取候选链接。"""
    raw: list[str] = []
    du = (work.get("downloadUrl") or "").strip()
    if du:
        raw.append(du)
    for u in (work.get("sourceFulltextUrls") or []):
        if isinstance(u, str) and u.strip():
            raw.append(u.strip())

    seen: set[str] = set()
    good: list[str] = []
    for u in raw:
        if not u.lower().startswith("http"):
            continue
        if _is_publisher(u):
            continue
        if u in seen:
            continue
        seen.add(u)
        good.append(u)
    good.sort(key=_rank)
    return good


def resolve_core(http: HttpClient, doi: str | None) -> tuple[str, str] | None:
    norm = _normalize_doi(doi or "")
    if not norm:
        return None
    headers = {"Accept": "application/json"}
    key = os.environ.get("CORE_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    resp = http.get(BASE, params={"q": f'doi:"{norm}"', "limit": 1}, headers=headers)
    if resp is None or resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    results = data.get("results") or []
    if not results:
        return None
    work = results[0]
    # 校验返回 DOI 与查询一致，避免聚合器偶发误匹配。
    wdoi = (work.get("doi") or "").strip().lower()
    if wdoi and wdoi != norm.lower():
        return None
    cands = core_candidates(work)
    return ("core", cands[0]) if cands else None
