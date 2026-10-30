# syntax=docker/dockerfile:1.7
# Build do SPA e servidor Caddy (arquivos estáticos + proxy reverso para a API).

FROM node:24-alpine AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN npm install --global pnpm@10.34.7
WORKDIR /web
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile --store-dir /pnpm/store
COPY apps/web/ ./
RUN pnpm build

FROM caddy:2.11-alpine
COPY docker/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
EXPOSE 8080
