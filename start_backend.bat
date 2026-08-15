@echo off
setlocal

set GLM_API_KEY=***REMOVED***
set GLM_MODEL=glm-4.7
set AGENT_DATABASE_URL=postgresql://brandflow_app:***REMOVED***@127.0.0.1:5432/brandflow
set AGENT_CHECKPOINT_DATABASE_URL=postgresql://brandflow_checkpoint:***REMOVED***@127.0.0.1:5432/brandflow
set BRAND_MCP_URL=http://127.0.0.1:8100/mcp
set BRAND_MCP_SERVICE_TOKEN=***REMOVED***

cd /d D:\demo\ai-blog-assistant\services\agent-api
call .venv\Scripts\activate.bat
python run.py
