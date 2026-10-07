FROM ghcr.io/astral-sh/uv:0.12.6-python3.14-trixie-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev && useradd --uid 1001 --create-home app
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8120 8121
CMD ["uvicorn", "sample_a2a_agents.netutils_agent.server:app", "--host", "0.0.0.0", "--port", "8120"]
