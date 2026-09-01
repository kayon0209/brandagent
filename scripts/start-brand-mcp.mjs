/** Start the real brand-tools-mcp against the DISPOSABLE PostgreSQL. */
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
  ['-m', 'brand_tools_mcp.server'],
  {
    cwd: 'services/brand-tools-mcp',
    env: {
      ...process.env,
      PYTHONPATH: 'src',
      BRAND_MCP_DATABASE_URL: 'postgresql://postgres@127.0.0.1:54398/postgres',
      BRAND_MCP_SERVICE_TOKEN: local.BRAND_MCP_SERVICE_TOKEN || '',
      BRAND_MCP_HOST: '127.0.0.1',
      BRAND_MCP_PORT: '8100',
    },
    stdio: ['ignore', 'inherit', 'inherit'],
  },
)
child.on('exit', code => process.exit(code ?? 0))
