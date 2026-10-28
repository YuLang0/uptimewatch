"""테스트용 모의 HTTP(S) 서버. 실제 외부 사이트 대신 실패·복구 시나리오를 재현합니다.

경로
- /ok                 200
- /status/<code>      지정 상태 코드
- /delay/<sec>        sec 초 지연 후 200
- /redirect?to=<url>  302 → to
- /redirect-loop      자기 자신으로 무한 리다이렉트
- /big                약 5MB 본문
- /flaky              state.mode 에 따라 응답(ok | fail | slow)
- /count              /flaky 호출 횟수 반환
- /control?mode=...   /flaky 동작 변경(E2E 용)
"""

from __future__ import annotations

import ssl
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


@dataclass
class MockState:
    mode: str = "ok"  # ok | fail | slow
    fail_status: int = 503
    slow_seconds: float = 5.0
    hits: int = 0


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockServer/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # 테스트 출력 정리
        pass

    @property
    def state(self) -> MockState:
        return self.server.state  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes = b"ok", headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)
        if path == "/ok" or path == "/":
            return self._send(200)
        if path.startswith("/status/"):
            return self._send(int(path.rsplit("/", 1)[1]), b"status")
        if path.startswith("/delay/"):
            time.sleep(float(path.rsplit("/", 1)[1]))
            return self._send(200)
        if path == "/redirect":
            return self._send(302, b"", {"Location": query.get("to", ["/ok"])[0]})
        if path == "/redirect-loop":
            return self._send(302, b"", {"Location": "/redirect-loop"})
        if path == "/big":
            body = b"x" * (5 * 1024 * 1024)
            return self._send(200, body)
        if path == "/flaky":
            self.state.hits += 1
            if self.state.mode == "fail":
                return self._send(self.state.fail_status, b"fail")
            if self.state.mode == "slow":
                time.sleep(self.state.slow_seconds)
            return self._send(200)
        if path == "/control":  # E2E 테스트용: /control?mode=fail|ok|slow&status=500
            self.state.mode = query.get("mode", [self.state.mode])[0]
            self.state.fail_status = int(query.get("status", [self.state.fail_status])[0])
            return self._send(200, self.state.mode.encode())
        if path == "/count":
            return self._send(200, str(self.state.hits).encode())
        return self._send(404, b"not found")


class MockServer:
    def __init__(self, ssl_context: ssl.SSLContext | None = None, port: int = 0) -> None:
        self.state = MockState()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.state = self.state  # type: ignore[attr-defined]
        if ssl_context is not None:
            self.httpd.socket = ssl_context.wrap_socket(self.httpd.socket, server_side=True)
        self.scheme = "https" if ssl_context else "http"
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> MockServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str = "/ok", host: str = "127.0.0.1") -> str:
        return f"{self.scheme}://{host}:{self.port}{path}"


if __name__ == "__main__":  # E2E 테스트에서 독립 실행: python -m tests.mock_server 18080
    import sys

    server = MockServer(port=int(sys.argv[1]) if len(sys.argv) > 1 else 18080)
    print(f"mock target listening on 127.0.0.1:{server.port}", flush=True)
    server.httpd.serve_forever()
