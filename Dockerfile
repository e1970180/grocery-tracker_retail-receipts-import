FROM ghcr.io/astral-sh/uv:0.13.4 AS uv

FROM python:3.14.8-slim-trixie

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so a source-only change reuses this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
COPY migrations ./migrations
COPY texts ./texts

# The named volume takes this directory's owner when it is first created.
RUN useradd --system --uid 10001 app && mkdir /data && chown app /data
USER app
VOLUME /data

ENTRYPOINT ["python", "-m", "retail_receipts_import"]
CMD ["run"]
