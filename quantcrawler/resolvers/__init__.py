"""PDF 来源解析器。

每个解析器尝试为一篇论文找到一个合法的开放获取 PDF 直链，返回
(source_label, pdf_url) 或 None。解析器按优先级依次尝试：

1. OpenAlex 自带 OA 位置（采集阶段已写入，无需再次请求）；
2. Unpaywall（按 DOI）；
3. Semantic Scholar（按 DOI，常给出 arXiv / 机构库 / PMC 直链）；
4. OpenAIRE（按 DOI，机构库 / 工作论文 .pdf 直链）；
5. CORE（按 DOI，机构库 / CORE 自托管直链，限速严，仅兜底时查）；
6. arXiv（按标题 / DOI 匹配，限 q-fin / stat / econ，最慢，仅兜底时查）。
"""

from .unpaywall import resolve_unpaywall, best_oa
from .arxiv import resolve_arxiv
from .semantic_scholar import resolve_semantic_scholar
from .openaire import resolve_openaire
from .core import resolve_core

__all__ = ["resolve_unpaywall", "resolve_arxiv", "resolve_semantic_scholar",
           "resolve_openaire", "resolve_core", "resolve_candidates"]


def resolve_candidates(http, doi, title, mailto):
    """汇总各来源的开放获取候选，返回去重后的 [(source, url), ...]。

    顺序：Unpaywall -> Semantic Scholar -> OpenAIRE -> CORE -> arXiv（标题搜索）。
    CORE 与 arXiv 标题搜索仅在前面都没拿到真正的 PDF 直链时才跑，既省请求又降误匹配。
    CORE 匿名限速极严（易 429），故置于免密钥快源之后、仅对剩余未命中项发起查询，把
    请求量限制在真正难解析的论文上。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(cand):
        if cand and cand[1] not in seen:
            seen.add(cand[1])
            out.append(cand)

    up = best_oa(http, doi, mailto)          # (url, is_direct_pdf) | None
    if up:
        add(("unpaywall", up[0]))
    s2 = resolve_semantic_scholar(http, doi)
    add(s2)
    oair = resolve_openaire(http, doi)       # 仓库 / 工作论文 .pdf 直链
    add(oair)

    have_direct = (up and up[1]) or bool(s2) or bool(oair)
    if not have_direct:                       # 前面都没命中，再查限速较严的 CORE
        core = resolve_core(http, doi)        # 机构库 / CORE 自托管 .pdf 直链
        add(core)
        have_direct = bool(core)
    if not have_direct:                       # 仍未命中才做最慢的 arXiv 标题搜索
        add(resolve_arxiv(http, title))
    return out
