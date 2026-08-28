FROM node:20-alpine AS build

WORKDIR /app
# 带上 package-lock.json 并用 npm ci：只 COPY package.json 的话 npm install 会
# 重新解析版本，lockfile 要到下面 COPY . . 才进来，那时已经装完了 —— 等于每次
# 构建的依赖版本都可能不同。npm ci 严格按 lockfile 装，lock 与 package.json
# 不一致时直接报错而不是悄悄放行。
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 非 root 运行（trivy DS-0002）。默认镜像只有 worker 降权，master 仍是 root。
# 三件事必须一起做，少一件 nginx 起不来：
#   1. pid 挪出 /run（root 755，uid 101 写不进去）
#   2. 删掉 user 指令（非 root master 下它无效，只会刷 warning）
#   3. 监听端口改到 8080/8443（<1024 需要 root），compose 的映射同步改
# 另外：certs/server.key 必须对 uid 101 可读（install.sh 生成的是 644）。
# 想收紧到 600 的话得先解决宿主/容器 uid 不一致，否则 TLS 直接起不来。
RUN sed -i 's|^pid .*|pid /tmp/nginx.pid;|; /^user .*;$/d' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx /usr/share/nginx/html

USER nginx
EXPOSE 8080 8443
CMD ["nginx", "-g", "daemon off;"]
