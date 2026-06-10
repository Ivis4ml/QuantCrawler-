#!/usr/bin/env bash
# CORE 兜底 OA 补充全量运行：resolve-pdfs --retry -> download -> report。
# 幂等可续跑；只重置 paywalled/failed，已下载的不动。日志见 data/reports/core_boost.log。
set -uo pipefail
cd /Users/xinyu/Code/QuantCrawler- || exit 1
export CORE_API_KEY="$(cat .core_env)"
LOG=data/reports/core_boost.log
exec >> "$LOG" 2>&1

echo "==== CORE boost start: $(date -u +%FT%TZ)  key=${CORE_API_KEY:0:6}… ===="
python - <<'PY'
import sqlite3
c = sqlite3.connect("data/catalog.sqlite")
n = c.execute("SELECT COUNT(*) FROM papers WHERE is_quant=1 AND download_status='downloaded'").fetchone()[0]
pw = c.execute("SELECT COUNT(*) FROM papers WHERE is_quant=1 AND download_status IN ('paywalled','failed')").fetchone()[0]
print(f"BEFORE: downloaded={n}  paywalled+failed(to retry)={pw}")
PY

echo "---- resolve-pdfs --retry : $(date -u +%FT%TZ) ----"
python -m quantcrawler resolve-pdfs --retry
echo "---- download : $(date -u +%FT%TZ) ----"
python -m quantcrawler download
echo "---- report : $(date -u +%FT%TZ) ----"
python -m quantcrawler report

python - <<'PY'
import sqlite3
c = sqlite3.connect("data/catalog.sqlite")
n  = c.execute("SELECT COUNT(*) FROM papers WHERE is_quant=1 AND download_status='downloaded'").fetchone()[0]
nc = c.execute("SELECT COUNT(*) FROM papers WHERE pdf_source='core' AND download_status='downloaded'").fetchone()[0]
bysrc = dict(c.execute("SELECT pdf_source, COUNT(*) FROM papers WHERE is_quant=1 AND download_status='downloaded' GROUP BY pdf_source").fetchall())
print(f"AFTER: downloaded={n}  (pdf_source=core: {nc})")
print("downloaded by source:", bysrc)
PY
echo "==== CORE boost done: $(date -u +%FT%TZ) ===="
