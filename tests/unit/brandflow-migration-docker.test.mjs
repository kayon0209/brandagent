import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import test from 'node:test'

const enabled = process.env.RUN_BRANDFLOW_DB_TESTS === 'true'
const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

function docker(args, options = {}) {
  return execFileSync('docker', args, {
    cwd: repositoryRoot,
    encoding: 'utf8',
    stdio: options.capture ? 'pipe' : 'inherit',
  })
}

test('fresh PostgreSQL applies legacy and BrandFlow migrations with negative security checks', { skip: !enabled }, () => {
  const container = `brandflow-m1-${randomUUID().slice(0, 8)}`
  const migrationPath = path.join(repositoryRoot, 'docs', 'migrations')
  const checkPath = path.join(repositoryRoot, 'tests', 'unit', 'brandflow-migration-checks.sql')

  docker([
    'run', '--rm', '--name', container, '-d',
    '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
    '-v', `${migrationPath}:/migrations:ro`,
    'postgres:16-alpine',
  ])

  try {
    docker([
      'exec', container, 'sh', '-c',
      'attempt=0; until pg_isready -U postgres; do attempt=$((attempt+1)); [ "$attempt" -ge 30 ] && exit 1; sleep 0.5; done',
    ])

    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/migrations/001_init.sql'])
    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/migrations/002_brandflow_v2_foundation.sql'])
    docker(['cp', checkPath, `${container}:/tmp/brandflow-migration-checks.sql`])
    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/tmp/brandflow-migration-checks.sql'])
  } finally {
    try {
      docker(['stop', container], { capture: true })
    } catch {
      // The daemon may already have removed the disposable container.
    }
  }
})
