"""带限速、重试、退避的 HTTP 客户端封装。

限速器按主机（host）分桶且线程安全，因此可在多线程下并发请求不同主机，而对单一主机
（尤其 arXiv）仍受配额约束。下载支持流式落盘与体积上限。
"""

from __future__ import annotations

import logging
import threading
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("quantcrawler.http")


class HostRateLimiter:
    """按主机分桶的令牌间隔限速，线程安全。

    在锁内预约下一次请求的时间槽（推进该主机的 _last），在锁外睡眠，使并发线程能对
    同一主机排队而不长时间持锁。不同主机各自独立，可真正并发。
    """

    def __init__(self, default_rps: float, host_rps: dict[str, float] | None = None):
        self.default_interval = 1.0 / default_rps if default_rps and default_rps > 0 else 0.0
        self.host_intervals = {
            h: (1.0 / rps if rps and rps > 0 else 0.0)
            for h, rps in (host_rps or {}).items()
        }
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        interval = self.host_intervals.get(host, self.default_interval)
        if interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            scheduled = max(now, last + interval)
            self._last[host] = scheduled
            sleep_for = scheduled - now
        if sleep_for > 0:
            time.sleep(sleep_for)


class HttpClient:
    """对 GET 做限速、重试与退避。区分可重试错误（429/5xx/网络）与永久错误。"""

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        max_retries: int = 4,
        backoff: float = 1.5,
        rate_limit_rps: float = 8.0,
        host_rps: dict[str, float] | None = None,
        retry_after_cap: float = 120.0,
        user_agent: str = "QuantCrawler/0.1",
        follow_redirects: bool = True,
    ):
        self.max_retries = max_retries
        self.backoff = backoff
        self.retry_after_cap = retry_after_cap
        self.limiter = HostRateLimiter(rate_limit_rps, host_rps)
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers={"User-Agent": user_agent},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, url: str, *, params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None) -> httpx.Response | None:
        """返回成功响应；重试耗尽后返回 None。永久性 4xx（非 429）直接返回该响应。"""
        attempt = 0
        while True:
            self.limiter.wait(url)
            try:
                resp = self.client.get(url, params=params, headers=headers)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                attempt += 1
                if attempt > self.max_retries:
                    log.warning("GET %s 网络错误，重试耗尽：%s", url, exc)
                    return None
                self._sleep(attempt)
                continue

            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504):
                attempt += 1
                if attempt > self.max_retries:
                    log.warning("GET %s 状态 %s，重试耗尽", url, resp.status_code)
                    return resp
                self._sleep(attempt, resp.headers.get("Retry-After"))
                continue
            return resp

    def stream_to_file(
        self, url: str, dest_part, *, max_bytes: int,
        headers: dict[str, str] | None = None, chunk_size: int = 1 << 16,
        first_chunk_validator=None,
    ) -> tuple[bool, int, str | None]:
        """流式下载到文件对象 dest_part，逐块写入。返回 (ok, n_bytes, error)。

        - 超过 max_bytes 立即中止；
        - first_chunk_validator(bytes)->bool：对首个数据块校验（如 %PDF 魔数），不通过即中止；
        - 不做自身重试（交由调用方按结果决定），但遵守限速。
        """
        self.limiter.wait(url)
        try:
            with self.client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    return False, 0, f"HTTP {resp.status_code}"
                clen = resp.headers.get("Content-Length")
                if clen and clen.isdigit() and int(clen) > max_bytes:
                    return False, 0, f"content-length {clen} 超上限"
                total = 0
                first = True
                for chunk in resp.iter_bytes(chunk_size):
                    if first:
                        first = False
                        if first_chunk_validator and not first_chunk_validator(chunk):
                            return False, len(chunk), "non-pdf-content"
                    total += len(chunk)
                    if total > max_bytes:
                        return False, total, f"超过 max_bytes {max_bytes}"
                    dest_part.write(chunk)
                return True, total, None
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            return False, 0, f"网络错误 {exc}"

    def _sleep(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self.backoff * (2 ** (attempt - 1))
        if retry_after:
            parsed = self._parse_retry_after(retry_after)
            if parsed is not None:
                delay = max(delay, parsed)
        delay = min(delay, self.retry_after_cap)
        log.debug("退避 %.1fs（第 %d 次重试）", delay, attempt)
        time.sleep(delay)

    @staticmethod
    def _parse_retry_after(value: str) -> float | None:
        value = value.strip()
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
        try:
            dt = parsedate_to_datetime(value)
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError):
            return None
