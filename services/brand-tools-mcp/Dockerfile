FROM python:3.12-slim

WORKDIR /app
COPY services/brand-tools-mcp/pyproject.toml services/brand-tools-mcp/README.md ./
COPY services/brand-tools-mcp/src ./src
RUN pip install --no-cache-dir .

EXPOSE 8100
CMD ["uvicorn", "brand_tools_mcp.server:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8100"]
