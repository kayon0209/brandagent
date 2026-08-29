import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import test from 'node:test'

const enabled = process.env.RUN_BRANDFLOW_DB_TESTS === 'true'
const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const migrationPath = path.join(repositoryRoot, 'docs', 'migrations', '003_consumer_experience.sql')
const checkPath = path.join(repositoryRoot, 'tests', 'unit', 'consumer-migration-checks.sql')

test('003_consumer_experience.sql exists and stays additive', () => {
  assert.ok(existsSync(migrationPath), 'docs/migrations/003_consumer_experience.sql is missing')
  const source = readFileSync(migrationPath, 'utf8')
  for (const banned of ['DROP', 'RENAME', 'TRUNCATE']) {
    assert.doesNotMatch(
      source.replace(/--[^\n]*/g, ''),
      new RegExp(`\\b${banned}\\b`, 'i'),
      `the consumer migration must never contain ${banned}`
    )
  }
})

function docker(args, options = {}) {
  return execFileSync('docker', args, {
    cwd: repositoryRoot,
    encoding: 'utf8',
    stdio: options.capture ? 'pipe' : 'inherit',
  })
}

test('fresh PostgreSQL applies legacy, BrandFlow and consumer migrations with checks', { skip: !enabled }, () => {
  const container = `brandconsumer-${randomUUID().slice(0, 8)}`
  const migrationsDir = path.join(repositoryRoot, 'docs', 'migrations')

  docker([
    'run', '--rm', '--name', container, '-d',
    '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
    '-v', `${migrationsDir}:/migrations:ro`,
    'postgres:16-alpine',
  ])

  try {
    docker([
      'exec', container, 'sh', '-c',
      'attempt=0; until pg_isready -U postgres; do attempt=$((attempt+1)); [ "$attempt" -ge 30 ] && exit 1; sleep 0.5; done',
    ])

    for (const file of ['001_init.sql', '002_brandflow_v2_foundation.sql', '003_consumer_experience.sql']) {
      docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', `/migrations/${file}`])
    }
    docker(['cp', checkPath, `${container}:/tmp/consumer-migration-checks.sql`])
    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/tmp/consumer-migration-checks.sql'])
  } finally {
    try {
      docker(['stop', container], { capture: true })
    } catch {
      // The daemon may already have removed the disposable container.
    }
  }
})
