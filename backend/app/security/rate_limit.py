"""간단한 인메모리 슬라이딩 윈도/토큰 버킷 제한기.

API 인스턴스·작업자 프로세스 단위로 동작합니다. 여러 인스턴스로 수평 확장할 때는
리버스 프록시(nginx limit_req 등)의 제한과 함께 사용하세요.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def hit(self, key: str, now: float | None = None) -> bool:
        """요청을 기록하고 허용 여부를 반환합니다."""
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= self.max_keys:
                    self._evict(now)
                bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] >= self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        bucket = self._hits.get(key)
        if not bucket:
            return 0
        return max(1, int(self.window - (now - bucket[0])) + 1)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict(self, now: float) -> None:
        for key in [k for k, b in self._hits.items() if not b or now - b[-1] >= self.window]:
            del self._hits[key]
        if len(self._hits) >= self.max_keys:
            self._hits.clear()
