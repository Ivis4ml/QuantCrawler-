"""各阶段编排：resolve-sources / harvest / resolve-pdfs / download / report。

所有阶段幂等、可断点续跑：进度记录在 SQLite，重跑只处理未完成项。
"""

from __future__ import annotations

import csv
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import Settings, Journal
from .crossref import Crossref
from .db import Catalog
from .downloader import Downloader, target_path, _sha256_file
from .http import HttpClient
from .models import Paper
from .openalex import (
    OpenAlex, reconstruct_abstract, authors_of, topic_names,
    pdf_urls_from_work, landing_of,
)
from .relevance import RelevanceFilter
from .resolvers import resolve_candidates

log = logging.getLogger("quantcrawler.pipeline")


# arXiv / Semantic Scholar 等单独限频，避免 429 / 封 IP（1 rps 属礼貌范围）。
_META_HOST_RPS = {"export.arxiv.org": 1.0, "api.semanticscholar.org": 0.8}
_DL_HOST_RPS = {"arxiv.org": 1.0, "export.arxiv.org": 1.0}


def _http(settings: Settings) -> HttpClient:
    h = settings.http
    return HttpClient(
        timeout=h.get("timeout", 60),
        max_retries=h.get("max_retries", 4),
        backoff=h.get("backoff", 1.5),
        rate_limit_rps=h.get("rate_limit_rps", 8),
        host_rps=_META_HOST_RPS,
        retry_after_cap=h.get("retry_after_cap", 120),
        user_agent=f"QuantCrawler/0.1 (mailto:{settings.mailto})",
    )


def _download_http(settings: Settings) -> HttpClient:
    d = settings.download
    return HttpClient(
        timeout=d.get("timeout", 120),
        max_retries=d.get("max_retries", 3),
        backoff=settings.http.get("backoff", 1.5),
        rate_limit_rps=d.get("rate_limit_rps", 2),
        host_rps=_DL_HOST_RPS,
        retry_after_cap=settings.http.get("retry_after_cap", 120),
        user_agent=d.get("user_agent", f"QuantCrawler/0.1 (mailto:{settings.mailto})"),
    )


def _scope_clause(settings: Settings) -> str:
    """下载 / 解析阶段的目标范围：全部相关论文，或仅每刊每年入选项。"""
    return "selected=1" if settings.download_scope == "selected" else "is_quant=1"


def _select_journals(settings: Settings, only: str | None) -> list[Journal]:
    if only:
        j = settings.journal_by_slug(only)
        if not j:
            raise SystemExit(f"未找到期刊 slug: {only}")
        return [j]
    return settings.journals


# ----------------------------------------------------------------------------
# 阶段 1：解析期刊 Source ID
# ----------------------------------------------------------------------------
def resolve_sources(settings: Settings, catalog: Catalog, only: str | None = None) -> None:
    with _http(settings) as http:
        oa = OpenAlex(http, settings.mailto)
        for j in _select_journals(settings, only):
            if j.metadata_source == "crossref":
                log.info("跳过 %s：使用 Crossref 通路，无需 OpenAlex source", j.slug)
                catalog.upsert_journal(j.slug, j.name, j.issn, j.category,
                                       j.include_all, None, None)
                continue
            source_id = j.source_id
            works_count = None
            if not source_id:
                info = oa.resolve_source(j.issn)
                if not info:
                    log.warning("无法解析 source：%s (ISSN %s)", j.slug, j.issn)
                    catalog.upsert_journal(j.slug, j.name, j.issn, j.category,
                                           j.include_all, None, None)
                    continue
                source_id = info["id"]
                works_count = info.get("works_count")
                log.info("解析 %s -> %s (works=%s)", j.slug, source_id, works_count)
            catalog.upsert_journal(j.slug, j.name, j.issn, j.category,
                                   j.include_all, source_id, works_count)


# ----------------------------------------------------------------------------
# 阶段 2：采集元数据 + 相关性筛选
# ----------------------------------------------------------------------------
def harvest(settings: Settings, catalog: Catalog, only: str | None = None) -> None:
    rfilter = RelevanceFilter(settings.relevance)
    with _http(settings) as http:
        oa = OpenAlex(http, settings.mailto)
        cr = Crossref(http, settings.mailto)
        for j in _select_journals(settings, only):
            if j.metadata_source == "crossref":
                works = _iter_crossref(cr, j, settings)
            else:
                works = _iter_openalex(oa, catalog, j, settings)

            batch: list[Paper] = []
            n_total = n_quant = 0
            for work in works:
                paper = _work_to_paper(work, j, rfilter)
                n_total += 1
                if paper.is_quant:
                    n_quant += 1
                batch.append(paper)
                if len(batch) >= 200:
                    catalog.upsert_papers(batch)
                    batch.clear()
            if batch:
                catalog.upsert_papers(batch)
            log.info("  %s（%s）：采集 %d 篇，量化相关 %d 篇",
                     j.slug, j.metadata_source, n_total, n_quant)


def _iter_openalex(oa: OpenAlex, catalog: Catalog, j: Journal, settings: Settings):
    source_id = catalog.get_journal_source(j.slug) or j.source_id
    if not source_id:
        info = oa.resolve_source(j.issn)
        if not info:
            log.warning("跳过 %s：无 source", j.slug)
            return
        source_id = info["id"]
        catalog.upsert_journal(j.slug, j.name, j.issn, j.category,
                               j.include_all, source_id, info.get("works_count"))
    source_key = source_id.rsplit("/", 1)[-1]
    total = oa.count_works(source_key, settings.since, settings.work_types, settings.until)
    log.info("采集 %s（%s..%s，约 %s 篇）", j.slug, settings.since, settings.until, total)
    yield from oa.iter_works(source_key, settings.since, settings.work_types, settings.until)


def _iter_crossref(cr: Crossref, j: Journal, settings: Settings):
    log.info("采集 %s（Crossref，%s..%s）", j.slug, settings.since, settings.until)
    yield from cr.iter_works(j.issn, settings.since, settings.until)


def _work_to_paper(work: dict, j: Journal, rfilter: RelevanceFilter) -> Paper:
    is_crossref = "authorships" not in work  # Crossref 映射后的 dict 无此键

    if is_crossref:
        title = work.get("title")
        abstract = work.get("abstract")
        topics: list[str] = []
        primary = None
        oa_status = None
        authors = work.get("authors", [])
        pdf_source = pdf_url = None
        landing = work.get("landing") or work.get("doi")
    else:
        title = work.get("title") or work.get("display_name")
        abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        topics = topic_names(work)
        primary = (work.get("primary_topic") or {}).get("display_name")
        oa_status = (work.get("open_access") or {}).get("oa_status")
        authors = authors_of(work)
        candidates = pdf_urls_from_work(work)
        pdf_source = "openalex" if candidates else None
        pdf_url = candidates[0] if candidates else None
        landing = landing_of(work)

    is_quant, reason = rfilter.evaluate(
        include_all=j.include_all, category=j.category, title=title, abstract=abstract,
        primary_topic=primary, topics=topics,
    )

    return Paper(
        openalex_id=work["id"],
        journal_slug=j.slug,
        journal_name=j.name,
        doi=work.get("doi"),
        title=title,
        authors=authors,
        publication_year=work.get("publication_year"),
        publication_date=work.get("publication_date"),
        abstract=abstract,
        primary_topic=primary,
        topics=topics,
        oa_status=oa_status,
        cited_by_count=work.get("cited_by_count"),
        is_quant=is_quant,
        relevance_reason=reason,
        pdf_source=pdf_source,
        pdf_url=pdf_url,
        pdf_landing=landing,
        download_status="pending",
    )


# ----------------------------------------------------------------------------
# 阶段 2.5：每刊每年按引用数取前 top_per_year，置 selected
# ----------------------------------------------------------------------------
def select(settings: Settings, catalog: Catalog, only: str | None = None) -> None:
    order_col = {"citations": "cited_by_count",
                 "recency": "publication_date"}.get(settings.select_by, "cited_by_count")
    stats = catalog.select_top_per_year(
        top_per_year=settings.top_per_year,
        since_year=settings.since_year,
        until_year=settings.until_year,
        order_col=order_col,
    )
    log.info(
        "挑选完成：%d/%d 篇入选（每刊每年前 %d，按 %s）",
        stats["selected"], stats["eligible"], settings.top_per_year, settings.select_by,
    )
    if only:
        log.info("注意：select 为全库范围操作，--journal 不改变其行为")


# ----------------------------------------------------------------------------
# 阶段 3：为入选量化论文定位开放获取 PDF（OpenAlex 之外的补充）
# ----------------------------------------------------------------------------
def resolve_pdfs(settings: Settings, catalog: Catalog, only: str | None = None,
                 retry: bool = False) -> None:
    # retry=True：把之前判为 paywalled / failed 的项重置回 pending 重新解析，
    # 以便在新增 OA 来源（如 Semantic Scholar）后再榨一遍免费副本。
    if retry:
        rwhere = f"{_scope_clause(settings)} AND download_status IN ('paywalled','failed')"
        rparams: tuple = ()
        if only:
            rwhere += " AND journal_slug=?"
            rparams = (only,)
        cur = catalog.conn.execute(
            f"UPDATE papers SET download_status='pending', pdf_url=NULL, "
            f"pdf_source=NULL, error=NULL WHERE {rwhere}", rparams)
        catalog.conn.commit()
        log.info("retry：重置 %d 篇 paywalled/failed 回 pending", cur.rowcount)

    where = f"{_scope_clause(settings)} AND download_status='pending' AND pdf_url IS NULL"
    params = ()
    if only:
        where += " AND journal_slug=?"
        params = (only,)
    rows = catalog.iter_papers(where, params)
    log.info("需补充解析 PDF 的论文：%d 篇", len(rows))
    if not rows:
        return
    workers = int(settings.download.get("resolve_workers", 12))

    # 工作线程仅做网络解析；写库在主线程，保证 sqlite 单线程访问与续跑安全。
    with _http(settings) as http:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(resolve_candidates, http, r["doi"], r["title"], settings.mailto): r
                for r in rows
            }
            done = 0
            for fut in as_completed(futs):
                r = futs[fut]
                try:
                    cands = fut.result()
                except Exception as exc:  # noqa: BLE001
                    cands = []
                    log.debug("解析异常 %s: %s", r["openalex_id"], exc)
                if cands:
                    source, url = cands[0]
                    catalog.update_pdf_result(
                        r["openalex_id"], pdf_source=source, pdf_url=url,
                        pdf_path=None, sha256=None, download_status="pending", error=None,
                    )
                else:
                    catalog.update_pdf_result(
                        r["openalex_id"], pdf_source="none", pdf_url=None,
                        pdf_path=None, sha256=None, download_status="paywalled",
                        error="未找到开放获取副本",
                    )
                done += 1
                if done % 100 == 0:
                    log.info("  已解析 %d/%d", done, len(rows))


# ----------------------------------------------------------------------------
# 阶段 4：下载 PDF
# ----------------------------------------------------------------------------
def download(settings: Settings, catalog: Catalog, only: str | None = None,
             limit: int | None = None, retry_failed: bool = False) -> None:
    statuses = "('pending')" if not retry_failed else "('pending','failed','paywalled')"
    where = (f"{_scope_clause(settings)} AND pdf_url IS NOT NULL AND download_status IN {statuses}")
    params: tuple = ()
    if only:
        where += " AND journal_slug=?"
        params = (only,)
    rows = catalog.iter_papers(where, params)
    if limit:
        rows = rows[:limit]
    log.info("待下载论文：%d 篇", len(rows))

    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    workers = int(settings.download.get("download_workers", 12))
    with _http(settings) as meta_http, _download_http(settings) as dl_http:
        dl = Downloader(
            dl_http, settings.pdf_dir,
            min_pdf_bytes=settings.download.get("min_pdf_bytes", 8192),
            max_pdf_bytes=settings.download.get("max_pdf_bytes", 50 * 1024 * 1024),
        )
        # 工作线程纯 IO，返回结果；写库在主线程。
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_download_one, dict(r), dl, meta_http, settings): r for r in rows}
            n_ok = done = 0
            for fut in as_completed(futs):
                res = fut.result()
                if res["ok"]:
                    n_ok += 1
                    catalog.update_pdf_result(
                        res["openalex_id"], pdf_source=res["source"], pdf_url=res["url"],
                        pdf_path=res["path"], sha256=res["sha"],
                        download_status="downloaded", error=None,
                    )
                else:
                    catalog.update_pdf_result(
                        res["openalex_id"], pdf_source=res["source"], pdf_url=res["url"],
                        pdf_path=None, sha256=None,
                        download_status=res["status"], error=res["error"],
                    )
                done += 1
                if done % 50 == 0:
                    log.info("  下载进度 %d/%d，成功 %d", done, len(rows), n_ok)
        log.info("下载完成：成功 %d / %d", n_ok, len(rows))


def _download_one(row: dict, dl: Downloader, meta_http: HttpClient, settings: Settings) -> dict:
    """下载一篇论文（线程内执行，不触库）。先试已存储候选，失败再用 Unpaywall/arXiv 兜底。

    P1-2：下载失败时不覆盖原始 pdf_url/pdf_source，保留库中已有值，避免污染后续重试。
    """
    oaid = row["openalex_id"]
    dest = target_path(settings.pdf_dir, row["journal_slug"],
                       row["publication_year"], row["doi"], oaid)
    tried: set[str] = set()
    last = None

    def attempt(source, url):
        nonlocal last
        if not url or url in tried:
            return None
        tried.add(url)
        last = dl.download(url, dest)
        if last.ok:
            return {"ok": True, "openalex_id": oaid, "source": source, "url": url,
                    "path": last.path, "sha": last.sha256}
        return None

    if row.get("pdf_url"):
        r = attempt(row.get("pdf_source") or "stored", row["pdf_url"])
        if r:
            return r

    if row.get("pdf_source") in (None, "openalex", "stored"):
        for source, url in resolve_candidates(meta_http, row.get("doi"), row.get("title"), settings.mailto):
            r = attempt(source, url)
            if r:
                return r

    return {"ok": False, "openalex_id": oaid,
            "source": row.get("pdf_source"), "url": row.get("pdf_url"),
            "status": last.status if last else "failed",
            "error": last.error if last else "无候选 URL"}


# ----------------------------------------------------------------------------
# 阶段 5：报告
# ----------------------------------------------------------------------------
def report(settings: Settings, catalog: Catalog) -> Path:
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    scope = _scope_clause(settings)

    # 1) 完整相关论文清单（paper list）
    list_path = settings.report_dir / "paper_list.csv"
    rows = catalog.iter_papers(
        f"{scope} ORDER BY journal_slug, publication_year DESC, cited_by_count DESC"
    )
    fields = ["journal_slug", "journal_name", "publication_year", "cited_by_count",
              "title", "doi", "oa_status", "download_status", "pdf_source",
              "relevance_reason", "selected", "pdf_path", "pdf_url"]
    with open(list_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for r in rows:
            w.writerow([r[f] for f in fields])

    # 2) 失败 / 付费墙清单（供校园网或人工下载）
    work_path = settings.report_dir / "download_worklist.csv"
    todo = [r for r in rows if r["download_status"] != "downloaded"]
    wl_fields = ["journal_slug", "publication_year", "title", "doi", "pdf_landing",
                 "download_status", "error"]
    with open(work_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(wl_fields)
        for r in todo:
            w.writerow([r[f] for f in wl_fields])

    # 3) 汇总
    md_path = settings.report_dir / "summary.md"
    n_total = len(rows)
    by_status: dict[str, int] = {}
    by_journal: dict[str, int] = {}
    dl_by_journal: dict[str, int] = {}
    for r in rows:
        by_status[r["download_status"]] = by_status.get(r["download_status"], 0) + 1
        by_journal[r["journal_slug"]] = by_journal.get(r["journal_slug"], 0) + 1
        if r["download_status"] == "downloaded":
            dl_by_journal[r["journal_slug"]] = dl_by_journal.get(r["journal_slug"], 0) + 1
    n_dl = by_status.get("downloaded", 0)
    years = settings.until_year - settings.since_year + 1
    lines = ["# QuantCrawler 采集汇总", ""]
    lines.append(f"- 期刊数：{len(settings.journals)}；时间窗口：{settings.since[:4]}-"
                 f"{settings.until_year}（{years} 年）；主题：二级市场 / 微观结构 / 高频 / 量化因子")
    lines.append(f"- 采集范围：download_scope={settings.download_scope}")
    lines.append(f"- 相关论文（paper list）：{n_total}")
    lines.append(f"- 已下载：{n_dl}（{100*n_dl//max(n_total,1)}%）；待处理：{n_total - n_dl}")
    lines.append("")
    lines.append("## 下载状态")
    for k, v in sorted(by_status.items()):
        lines.append(f"- {k}：{v}")
    lines.append("")
    lines.append("## 各期刊相关论文数 / 已下载")
    for k, v in sorted(by_journal.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {k}：{v} / 已下载 {dl_by_journal.get(k, 0)}")
    lines.append("")
    lines.append(f"清单：`{list_path.name}`（全部）、`{work_path.name}`（{len(todo)} 篇待人工 / 校园网下载）")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("报告已写入 %s / %s / %s", list_path, work_path, md_path)
    return list_path


def reconcile(settings: Settings, catalog: Catalog, only: str | None = None) -> None:
    """扫描 data/pdfs/，把磁盘上已存在的 PDF 标记为 downloaded。

    用于「私下共享 PDF + 无缝衔接」：拿到别人下载好的 data/pdfs/（即便没有同一份
    catalog.sqlite）后，运行本命令即可识别已下载文件，避免重复下载。文件路径由
    (journal_slug, year, doi) 确定性派生，故与原下载机器一致。
    """
    min_bytes = settings.download.get("min_pdf_bytes", 8192)
    where = "is_quant=1 AND download_status!='downloaded'"
    params: tuple = ()
    if only:
        where += " AND journal_slug=?"
        params = (only,)
    rows = catalog.iter_papers(where, params)
    n = 0
    for r in rows:
        dest = target_path(settings.pdf_dir, r["journal_slug"],
                           r["publication_year"], r["doi"], r["openalex_id"])
        if dest.exists() and dest.stat().st_size >= min_bytes:
            catalog.update_pdf_result(
                r["openalex_id"], pdf_source=r["pdf_source"] or "local",
                pdf_url=r["pdf_url"], pdf_path=str(dest), sha256=_sha256_file(dest),
                download_status="downloaded", error=None,
            )
            n += 1
    log.info("reconcile：磁盘已有并标记为 downloaded 的论文：%d 篇", n)


def _norm_doi(d: str) -> str:
    d = (d or "").strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(p):
            d = d[len(p):]
    return d


def import_pdf(settings: Settings, catalog: Catalog, *, doi: str | None = None,
               openalex_id: str | None = None, file: str | None = None) -> None:
    """把手动下载的一个 PDF 按 DOI（或 openalex id）归位到正确路径并标记 downloaded。

    供实习生用校园网下载后回填：
        python -m quantcrawler import-pdf --doi 10.1016/j.jfineco.2024.xxx --file C:\\Users\\me\\Downloads\\paper.pdf
    """
    import shutil
    from pathlib import Path
    from .downloader import _looks_like_pdf, _sha256_file

    if not file:
        raise SystemExit("需要 --file 指定已下载的 PDF 路径")
    src = Path(file)
    if not src.exists():
        raise SystemExit(f"文件不存在：{src}")

    if openalex_id:
        rows = catalog.iter_papers("openalex_id=?", (openalex_id,))
    elif doi:
        nd = _norm_doi(doi)
        rows = [r for r in catalog.iter_papers("doi IS NOT NULL")
                if _norm_doi(r["doi"]) == nd]
    else:
        raise SystemExit("需要 --doi 或 --id 指定论文")
    if not rows:
        raise SystemExit("库中未找到该论文（确认 DOI 是否在 paper_list.csv 里）")
    r = rows[0]

    if not _looks_like_pdf(src.read_bytes()[:1024]):
        raise SystemExit(f"{src} 不是有效 PDF（开头不是 %PDF）")

    dest = target_path(settings.pdf_dir, r["journal_slug"],
                       r["publication_year"], r["doi"], r["openalex_id"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    catalog.update_pdf_result(
        r["openalex_id"], pdf_source="manual", pdf_url=r["pdf_url"],
        pdf_path=str(dest), sha256=_sha256_file(dest),
        download_status="downloaded", error=None,
    )
    log.info("已归位：%s -> %s（标记 downloaded）", src.name, dest)


def run_all(settings: Settings, catalog: Catalog, only: str | None = None,
            limit: int | None = None) -> None:
    resolve_sources(settings, catalog, only)
    harvest(settings, catalog, only)
    select(settings, catalog, only)
    resolve_pdfs(settings, catalog, only)
    download(settings, catalog, only, limit=limit)
    report(settings, catalog)
