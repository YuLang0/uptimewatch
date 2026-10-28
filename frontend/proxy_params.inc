proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
# 클라이언트가 보낸 X-Forwarded-For 는 버리고 검증된 주소만 전달(위조 방지)
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_read_timeout 30s;
