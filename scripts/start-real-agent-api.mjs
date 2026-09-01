/** Start the real agent-api on a dedicated port (18000) against the
 *  DISPOSABLE PostgreSQL. Port 8000 is owned by an unrelated project. */
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'

function loadEnvLocal() {
  const env = {}
  for (const line of readFileSync('.env.local', 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/)
    if (m && !line.trim().startsWith('#')) env[m[1]] = m[2].replace(/^["']|["']$/g, '')
  }
  return env
}

const local = loadEnvLocal()
const child = spawn(
  './.venv/Scripts/python.exe',
  ['-c', `
import sys, asyncio, selectors
sys.path.insert(0, 'src')
from agent_api.api.server import create_server_app
from agent_api.runtime import configure_event_loop
import uvicorn

configure_event_loop()
port = int(sys.argv[1])
config = uvicorn.Config(create_server_app(), host='127.0.0.1', port=port, log_level='info')
server = uvicorn.Server(config)

async def run():
    await server.serve()

with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) as runner:
    runner.run(run())
`, '18000'],
  {
    cwd: 'services/agent-api',
    env: {
      ...process.env,
      PYTHONPATH: 'src',
      ENVIRONMENT: 'development',
      AUTH_MODE: 'dev',
      AGENT_DATABASE_URL: 'postgresql://postgres@127.0.0.1:54398/postgres',
      AGENT_CHECKPOINT_DATABASE_URL: 'postgresql://brandflow_app@127.0.0.1:54398/postgres?options=-csearch_path%3Dbrandflow_checkpoint',
      BRAND_MCP_URL: local.BRAND_MCP_URL || '',
      BRAND_MCP_SERVICE_TOKEN: local.BRAND_MCP_SERVICE_TOKEN || '',
      GLM_API_KEY: local.GLM_API_KEY || '',
      GLM_BASE_URL: local.GLM_BASE_URL || 'https://open.bigmodel.cn/api/paas/v4',
      CLERK_JWKS_URL: local.CLERK_JWKS_URL || '',
      CLERK_ISSUER: local.CLERK_ISSUER || '',
      CLERK_AUTHORIZED_PARTIES: local.CLERK_AUTHORIZED_PARTIES || '',
    },
    stdio: ['ignore', 'inherit', 'inherit'],
  },
)
child.on('exit', code => process.exit(code ?? 0))
