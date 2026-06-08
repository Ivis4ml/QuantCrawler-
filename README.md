# QuantCrawler

金融顶刊量化论文采集器。采集框架为 **5 年（2020-2024）× 20 本顶刊 × 每刊每年量化
论文前 20 篇（按引用数）= 2000 篇上限**，记录完整元数据，并在合法范围内下载开放
获取（Open Access）原文 PDF。

设计、期刊清单与计划详见 [CLAUDE.md](./CLAUDE.md)。

## 合规说明

本项目**仅下载合法的开放获取版本**：出版社 OA PDF、arXiv（q-fin / stat / econ）、
SSRN / NBER / RePEc 等被 OpenAlex 或 Unpaywall 收录的开放副本。对于仍在付费墙后、
无合法开放副本的论文，只记录元数据与 DOI，不下载、不绕过付费墙。

## 安装

```bash
pip install -r requirements.txt
```

依赖：`httpx`、`pyyaml`（其余使用 Python 标准库）。Python 3.11+。

## 使用

```bash
# 1. 解析并缓存期刊 OpenAlex Source ID
python -m quantcrawler resolve-sources

# 2. 采集元数据、引用数并做量化相关性筛选
python -m quantcrawler harvest

# 3. 每刊每年按引用数取前 20，置 selected
python -m quantcrawler select

# 4. 为入选论文补充定位开放获取 PDF（OpenAlex 之外）
python -m quantcrawler resolve-pdfs

# 5. 下载入选论文的开放获取 PDF
python -m quantcrawler download

# 6. 生成报告（CSV + Markdown）
python -m quantcrawler report

# 或一次性顺序执行全流程（resolve-sources -> harvest -> select -> resolve-pdfs -> download -> report）
python -m quantcrawler run

# 查看统计
python -m quantcrawler stats
```

常用参数：

- `--journal SLUG`：仅处理单个期刊（slug 见 `config/journals.yaml`）。
- `--config DIR` / `--data DIR`：自定义配置与数据目录。
- `download --limit N`：本次最多下载 N 篇；`--retry-failed` 重试失败 / 付费墙项。
- `-v`：调试日志（放在子命令之前）。

## 产物

- `data/catalog.sqlite`：论文元数据与下载状态（断点续跑的状态来源）。
- `data/pdfs/<期刊>/<年份>/<doi>.pdf`：下载的开放获取 PDF。
- `data/reports/quant_papers.csv`、`data/reports/summary.md`：清单与汇总。

## 配置

- `config/journals.yaml`：目标期刊（ISSN、类别、是否本质量化期刊）。可增删。
- `config/settings.yaml`：联系邮箱、采集起始日期、限速、量化相关性关键词与主题白名单。

## 数据来源

- [OpenAlex](https://openalex.org)：期刊与论文元数据枚举、开放获取位置、主题标注。
- [Unpaywall](https://unpaywall.org)：按 DOI 补充开放获取 PDF 定位。
- [arXiv](https://arxiv.org)：按标题匹配预印本（限 q-fin / stat / econ 等分类）。
