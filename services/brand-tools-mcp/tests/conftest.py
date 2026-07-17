import asyncio
import sys
from pathlib import Path


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

repository_root = Path(__file__).resolve().parents[3]
agent_api_src = repository_root / "services" / "agent-api" / "src"
brand_tools_src = repository_root / "services" / "brand-tools-mcp" / "src"
if str(agent_api_src) not in sys.path:
    sys.path.insert(0, str(agent_api_src))
if str(brand_tools_src) not in sys.path:
    sys.path.insert(0, str(brand_tools_src))
