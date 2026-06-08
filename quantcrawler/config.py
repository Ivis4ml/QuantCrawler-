"""配置加载：journals.yaml 与 settings.yaml。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_DATA_DIR = REPO_ROOT / "data"


@dataclass
class Journal:
    slug: str
    name: str
    issn: str
    category: str
    include_all: bool = False
    source_id: str | None = None
    metadata_source: str = "openalex"  # openalex | crossref

    @property
    def source_key(self) -> str | None:
        """OpenAlex source 短 id（去掉 URL 前缀），用于过滤参数。"""
        if not self.source_id:
            return None
        return self.source_id.rsplit("/", 1)[-1]


@dataclass
class Settings:
    mailto: str
    since: str
    work_types: list[str]
    http: dict[str, Any]
    download: dict[str, Any]
    relevance: dict[str, Any]
    until: str | None = None
    top_per_year: int = 20
    select_by: str = "citations"
    download_scope: str = "all"  # all（全部相关）| selected（每刊每年前 N）
    journals: list[Journal] = field(default_factory=list)
    config_dir: Path = DEFAULT_CONFIG_DIR
    data_dir: Path = DEFAULT_DATA_DIR

    @property
    def since_year(self) -> int:
        return int(self.since[:4])

    @property
    def until_year(self) -> int:
        return int(self.until[:4]) if self.until else self.since_year + 100

    # ---- 派生路径 ----
    @property
    def db_path(self) -> Path:
        return self.data_dir / "catalog.sqlite"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdfs"

    @property
    def report_dir(self) -> Path:
        return self.data_dir / "reports"

    def journal_by_slug(self, slug: str) -> Journal | None:
        for j in self.journals:
            if j.slug == slug:
                return j
        return None


def load_settings(
    config_dir: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> Settings:
    cfg_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    dat_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR

    with open(cfg_dir / "settings.yaml", "r", encoding="utf-8") as fh:
        s = yaml.safe_load(fh)
    with open(cfg_dir / "journals.yaml", "r", encoding="utf-8") as fh:
        jdata = yaml.safe_load(fh)

    journals = [Journal(**entry) for entry in jdata["journals"]]

    return Settings(
        mailto=s["mailto"],
        since=str(s["since"]),
        until=str(s["until"]) if s.get("until") else None,
        top_per_year=int(s.get("top_per_year", 20)),
        select_by=str(s.get("select_by", "citations")),
        download_scope=str(s.get("download_scope", "all")),
        work_types=list(s.get("work_types", ["article"])),
        http=dict(s.get("http", {})),
        download=dict(s.get("download", {})),
        relevance=dict(s.get("relevance", {})),
        journals=journals,
        config_dir=cfg_dir,
        data_dir=dat_dir,
    )
