"""기대 HTTP 상태 코드 표현식 파서. 예: "200", "200-299", "200-299,301,302"."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"^(\d{3})(?:-(\d{3}))?$")
MAX_TOKENS = 20


class StatusSpecError(ValueError):
    pass


def parse_status_spec(spec: str) -> list[tuple[int, int]]:
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if not tokens:
        raise StatusSpecError("기대 상태 코드를 입력하세요. 예: 200-299")
    if len(tokens) > MAX_TOKENS:
        raise StatusSpecError(f"기대 상태 코드는 최대 {MAX_TOKENS}개 항목까지 입력할 수 있습니다.")
    ranges: list[tuple[int, int]] = []
    for token in tokens:
        match = _TOKEN_RE.match(token)
        if not match:
            raise StatusSpecError(f"'{token}' 은(는) 올바른 상태 코드 형식이 아닙니다. 예: 200, 200-299")
        low = int(match.group(1))
        high = int(match.group(2) or low)
        if not (100 <= low <= 599 and 100 <= high <= 599) or low > high:
            raise StatusSpecError(f"'{token}' 은(는) 100~599 범위의 올바른 구간이어야 합니다.")
        ranges.append((low, high))
    return ranges


def normalize_status_spec(spec: str) -> str:
    ranges = parse_status_spec(spec)
    return ",".join(f"{lo}" if lo == hi else f"{lo}-{hi}" for lo, hi in ranges)


def status_matches(status_code: int, spec: str) -> bool:
    return any(lo <= status_code <= hi for lo, hi in parse_status_spec(spec))
