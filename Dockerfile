FROM python:3.12-alpine

LABEL org.opencontainers.image.title="Xtream What's New" \
      org.opencontainers.image.description="Lightweight Xtream catalogue monitor for new VOD, series and episodes" \
      org.opencontainers.image.source="https://github.com/slideboy/xtream-whats-new" \
      org.opencontainers.image.licenses="MIT"

RUN apk add --no-cache tzdata

WORKDIR /app
COPY watcher.py /app/watcher.py
COPY assets /app/assets
COPY data/config.json /app/config.default.json
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]
EXPOSE 36401

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "/app/watcher.py"]
