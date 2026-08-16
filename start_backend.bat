@echo off
setlocal
:: 安全修复：凭据一律从环境变量读取，禁止在此硬编码（曾泄漏 GLM_API_KEY，已修复）
if "%GLM_API_KEY%"=="" (
  echo [ERROR] 请先设置环境变量 GLM_API_KEY
  exit /b 1
)
set GLM_MODEL=glm-4.7
set AGENT_DATABASE_URL=postgresql://brandflow_app:%AGENT_DB_PASSWORD%@127.0.0.1:5432/brandflow
set AGENT_CHECKPOINT_DATABASE_URL=postgresql://brandflow_checkpoint:%CHECKPOINT_DB_PASSWORD%@127.0.0.1:5432/brandflow
set BRAND_MCP_URL=http://127.0.0.1:8100/mcp
set BRAND_MCP_SERVICE_TOKEN=%BRAND_MCP_SERVICE_TOKEN%
cd /d %~dp0\services\agent-api
if not exist .venv (
  echo [ERROR] 未找到 .venv，请先创建虚拟环境
  exit /b 1
)
call .venv\Scripts\activate.bat
python run.py
