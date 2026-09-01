/** Start the Next dev server for E2E with the BFF pointed at the
 *  real agent-api (18000) started by start-real-agent-api.mjs. */
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
  'node',
  ['node_modules/next/dist/bin/next', 'dev', '-p', '3000'],
  {
    env: {
      ...process.env,
      ...local, // .env.local values (user just replaced the Clerk secret key)
      BRANDFLOW_AGENT_INTERNAL_URL: 'http://127.0.0.1:18000',
    },
    stdio: ['ignore', 'inherit', 'inherit'],
  },
)
child.on('exit', code => process.exit(code ?? 0))
