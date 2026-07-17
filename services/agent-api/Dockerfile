FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY services/agent-api/pyproject.toml ./pyproject.toml
COPY services/agent-api/src ./src
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "agent_api.api.server:create_server_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
