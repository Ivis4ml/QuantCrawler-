"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import load_settings
from .db import Catalog
from . import pipeline


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quantcrawler",
        description="金融顶刊量化论文采集器（仅下载合法开放获取版本）",
    )
    p.add_argument("--config", default=None, help="配置目录（默认 ./config）")
    p.add_argument("--data", default=None, help="数据目录（默认 ./data）")
    p.add_argument("--journal", default=None, help="仅处理指定期刊 slug")
    p.add_argument("-v", "--verbose", action="store_true", help="调试日志")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve-sources", help="解析并缓存期刊 OpenAlex Source ID")
    sub.add_parser("harvest", help="采集元数据、引用数并做量化相关性筛选")
    sub.add_parser("select", help="每刊每年按引用数取前 top_per_year，置 selected")
    sub.add_parser("resolve-pdfs", help="为入选论文补充定位开放获取 PDF")

    d = sub.add_parser("download", help="下载开放获取 PDF")
    d.add_argument("--limit", type=int, default=None, help="本次最多下载篇数")
    d.add_argument("--retry-failed", action="store_true", help="重试 failed / paywalled")

    sub.add_parser("report", help="生成 CSV / Markdown 报告")
    sub.add_parser("stats", help="打印库内统计")

    r = sub.add_parser("run", help="顺序执行全流程")
    r.add_argument("--limit", type=int, default=None, help="下载阶段最多篇数")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    settings = load_settings(args.config, args.data)
    catalog = Catalog(settings.db_path)
    only = args.journal

    try:
        if args.command == "resolve-sources":
            pipeline.resolve_sources(settings, catalog, only)
        elif args.command == "harvest":
            pipeline.harvest(settings, catalog, only)
        elif args.command == "select":
            pipeline.select(settings, catalog, only)
        elif args.command == "resolve-pdfs":
            pipeline.resolve_pdfs(settings, catalog, only)
        elif args.command == "download":
            pipeline.download(settings, catalog, only,
                              limit=args.limit, retry_failed=args.retry_failed)
        elif args.command == "report":
            pipeline.report(settings, catalog)
        elif args.command == "stats":
            print(json.dumps(catalog.counts(), ensure_ascii=False, indent=2))
        elif args.command == "run":
            pipeline.run_all(settings, catalog, only, limit=args.limit)
        else:  # pragma: no cover
            return 2
    finally:
        catalog.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
