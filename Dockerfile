# syntax=docker/dockerfile:1
#
# Single image: FastAPI + htmx + SQLite + pypgx + WeasyPrint.
# Personal project; run locally. Pin the base digest for reproducibility.

FROM ubuntu:24.04

ARG GIT_SHA=unknown
ARG VERSION=0.1.0

LABEL org.opencontainers.image.title="pharmcow" \
      org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.version=$VERSION

ENV DEBIAN_FRONTEND=noninteractive

# Runtime deps: bcftools (QC), WeasyPrint libs, Vietnamese fonts.
# python3.12-dev/build-essential are only needed while uv builds two sdists
# (sorted_nearest, matplotlib-venn) and are removed in the same layer.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates tini bcftools \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      shared-mime-info fonts-noto-core \
      build-essential python3.12-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
RUN uv sync --frozen --no-dev --extra star && \
    apt-get purge -y --auto-remove build-essential python3.12-dev && \
    rm -rf /var/lib/apt/lists/*

ENV PATH=/app/.venv/bin:$PATH \
    VGT_VERSION=$VERSION \
    VGT_GIT_SHA=$GIT_SHA \
    PHARMCOW_DATA_DIR=/data \
    MPLCONFIGDIR=/tmp/matplotlib

RUN mkdir -p /data
VOLUME ["/data"]

ENTRYPOINT ["tini","--"]
CMD ["pharmcow","serve","--host","0.0.0.0","--port","8000"]
