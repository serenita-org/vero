FROM squidfunk/mkdocs-material:9.6 AS build

WORKDIR /tmp

COPY ./mkdocs.yml .
COPY ./docs/ docs/

RUN mkdocs build -d mkdocs_dist

# ---------- runtime serving ----------
FROM caddy:2-alpine
COPY --from=build /tmp/mkdocs_dist /usr/share/caddy

# Caddy listens on HTTP 80 by default
EXPOSE 80
