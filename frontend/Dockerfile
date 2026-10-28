# syntax=docker/dockerfile:1
# 1) 빌드
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
# 선택: 사내 프록시 CA (--secret id=extra_ca,src=<CA.pem>)
RUN --mount=type=secret,id=extra_ca \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund
COPY . .
RUN npx tsc -b && npx vite build

# 2) 정적 파일 + /api 리버스 프록시
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY proxy_params.inc /etc/nginx/conf.d/proxy_params.inc
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
