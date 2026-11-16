FROM squidfunk/mkdocs-material:9.8.1@sha256:f797da217ff01b20b298d2185eb9d88fb81f5a322c439eba854f2e4de8a48e65 AS build

WORKDIR /tmp

COPY ./mkdocs.yml .
COPY ./docs/ docs/
COPY ./overrides/ overrides/

RUN mkdocs build -d mkdocs_dist

# ---------- runtime serving ----------
FROM caddy:2-alpine
COPY --from=build /tmp/mkdocs_dist /usr/share/caddy

COPY Caddyfile /etc/caddy/Caddyfile

# Caddy listens on HTTP 80 by default
EXPOSE 80
