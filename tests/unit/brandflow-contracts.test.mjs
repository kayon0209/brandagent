import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const yaml = require('js-yaml')

const read = path => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

const readPythonTaskStatus = async () => {
  const source = await read('services/agent-api/src/agent_api/domain/models.py')
  const block = source.match(/class TaskStatus\(StrEnum\):\n((?:[ \t]+\w+ = "[^"]+"\n)+)/)
  assert.ok(block, 'Python TaskStatus enum not found in domain/models.py')
  return [...block[1].matchAll(/"([^"]+)"/g)].map(match => match[1])
}

const readGeneratedTaskStatus = async () => {
  const source = await readFile(
    new URL('../../src/types/generated/brandflow-api.ts', import.meta.url),
    'utf8',
  ).catch(() => null)
  assert.ok(source, 'src/types/generated/brandflow-api.ts is missing; run the openapi-typescript codegen')
  const segment = source.match(/TaskStatus:\s*([^;]+);/)
  assert.ok(segment, 'TaskStatus union not found in generated types')
  return [...segment[1].matchAll(/"([^"]+)"/g)].map(match => match[1])
}

test('V2 domain contract contains every required entity and serializable AgentState', async () => {
  const source = await read('src/types/brandflow.types.ts')
  for (const entity of [
    'ContentTask',
    'ContentBrief',
    'SourceDocument',
    'VerifiedFact',
    'ContentVersion',
    'ReviewResult',
    'HumanDecision',
    'ToolCallLog',
    'AgentState',
  ]) {
    assert.match(source, new RegExp(`export interface ${entity}\\b`), `${entity} is missing`)
  }
  assert.doesNotMatch(source, /\bDate\b/, 'Agent contracts must use JSON-serializable timestamps')
})

test('V2 migration is additive and defines tenant-scoped foundations', async () => {
  const sql = await read('docs/migrations/002_brandflow_v2_foundation.sql')
  for (const table of [
    'workspaces',
    'workspace_members',
    'content_tasks',
    'content_briefs',
    'source_documents',
    'verified_facts',
    'content_versions',
    'review_results',
    'human_decisions',
    'content_lineage',
    'task_events',
    'tool_call_logs',
    'model_call_logs',
    'idempotency_records',
    'evaluation_tasks',
    'evaluation_runs',
    'bad_cases',
    'legacy_article_mappings',
  ]) {
    assert.match(sql, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}\\b`, 'i'), `${table} is missing`)
  }
  assert.doesNotMatch(sql, /\b(DROP|TRUNCATE)\b/i, 'Milestone 1 migration must be additive')
  assert.doesNotMatch(sql, /ALTER\s+TABLE\s+(users|articles)\b/i, 'Legacy tables must remain untouched')
  assert.match(sql, /FOREIGN KEY \(workspace_id, task_id\)/i)
  assert.match(sql, /content_versions_master_number_uidx/i)
  assert.match(sql, /content_versions_kind_coherence_chk/i)
  assert.match(sql, /content_versions_append_only/i)
  assert.match(sql, /human_decisions_member_tenant_fk/i)
  assert.match(sql, /human_decisions_requirement_once_uk/i)
  assert.match(sql, /approval_requirement_id = NEW\.approval_requirement_id\s+FOR UPDATE/i)
})

test('Consumer upgrade master plan exists and separates consumer from enterprise surfaces', async () => {
  const plan = await read('docs/MASTER_PLAN.md')
  assert.match(plan, /\/app\b/, 'MASTER_PLAN must name the /app consumer route group')
  assert.match(plan, /\/brandflow/, 'MASTER_PLAN must name the /brandflow enterprise route group')
  assert.match(plan, /个人创作者/, 'MASTER_PLAN must describe the consumer creator product')
  assert.match(plan, /企业/, 'MASTER_PLAN must keep the enterprise BrandFlow surface explicit')
  assert.match(plan, /Phase 0/i, 'MASTER_PLAN must be organized by upgrade phases')
})

test('PRD defines consumer material as traceable excerpt, not verified fact', async () => {
  const prd = await read('docs/PRD-v2.md')
  assert.match(prd, /material_excerpt/, 'PRD must define the material_excerpt term')
  assert.match(
    prd,
    /素材[^。]*不等于[^。]*verified[ _]fact/i,
    'PRD must state that consumer material is not a verified fact',
  )
})

test('README presents the consumer creator product as the current direction', async () => {
  const readme = await read('README.md')
  assert.match(readme, /个人创作者/, 'README must present the consumer creator product')
  assert.match(readme, /前身|旧版/, 'README must keep the blog assistant marked as legacy')
})

test('OpenAPI contract exposes task lifecycle and approval endpoints', async () => {
  const contract = await read('docs/brandflow-openapi.yaml')
  const document = yaml.load(contract)
  assert.equal(document.openapi, '3.1.0')
  for (const path of [
    '/api/v1/tasks',
    '/api/v1/tasks/{task_id}',
    '/api/v1/tasks/{task_id}/events',
    '/api/v1/tasks/{task_id}/clarification',
    '/api/v1/tasks/{task_id}/outline/approve',
    '/api/v1/tasks/{task_id}/master/approve',
    '/api/v1/tasks/{task_id}/final/approve',
    '/api/v1/tasks/{task_id}/export',
    '/api/v1/health',
    '/api/v1/readiness',
  ]) {
    assert.ok(document.paths && document.paths[path], `${path} is missing`)
  }
  assert.match(contract, /Idempotency-Key/)

  const resolvePointer = pointer =>
    pointer
      .slice(2)
      .split('/')
      .reduce((value, key) => value?.[key.replaceAll('~1', '/').replaceAll('~0', '~')], document)
  const refs = [...contract.matchAll(/\$ref:\s*['"](#[^'"]+)['"]/g)].map(match => match[1])
  for (const ref of refs) assert.ok(resolvePointer(ref), `Unresolved OpenAPI ref: ${ref}`)
})

test('OpenAPI, Python domain, and generated TypeScript share one task status lifecycle', async () => {
  const document = yaml.load(await read('docs/brandflow-openapi.yaml'))
  const openApiStatus = document.components?.schemas?.TaskStatus?.enum
  assert.ok(Array.isArray(openApiStatus), 'OpenAPI must define a TaskStatus enum schema')
  for (const status of [
    'generating_channels',
    'reviewing_channels',
    'waiting_for_final_approval',
    'exporting',
  ]) {
    assert.ok(openApiStatus.includes(status), `TaskStatus lifecycle is missing ${status}`)
  }

  const pythonStatus = await readPythonTaskStatus()
  assert.deepEqual(
    pythonStatus,
    openApiStatus,
    'Python TaskStatus drifted from the OpenAPI contract',
  )

  const generatedStatus = await readGeneratedTaskStatus()
  assert.deepEqual(
    [...generatedStatus].sort(),
    [...openApiStatus].sort(),
    'Generated TypeScript TaskStatus drifted from the OpenAPI contract',
  )
})

test('OpenAPI defines a Task schema bound to the task lifecycle', async () => {
  const document = yaml.load(await read('docs/brandflow-openapi.yaml'))
  const task = document.components?.schemas?.Task
  assert.ok(task, 'OpenAPI must define a Task schema')
  for (const field of ['task_id', 'workspace_id', 'title', 'status', 'selected_channels']) {
    assert.ok(task.properties?.[field], `Task schema is missing ${field}`)
  }
  assert.equal(task.properties.status.$ref, '#/components/schemas/TaskStatus')
  assert.equal(task.properties.selected_channels.items.$ref, '#/components/schemas/Channel')
  for (const field of ['task_id', 'workspace_id', 'title', 'status']) {
    assert.ok(task.required?.includes(field), `Task schema must require ${field}`)
  }
})

test('BrandFlow client types use the shared contract instead of loose records', async () => {
  const source = await read('src/lib/api/brandflow.ts')
  assert.match(
    source,
    /from '@\/types\/generated\/brandflow-api'/,
    'brandflow.ts must import the generated contract types',
  )
  const taskAlias = source.match(/export type BrandFlowTask = ([^\n]+)/)
  assert.ok(taskAlias, 'BrandFlowTask type not found')
  assert.equal(
    taskAlias[1].trim(),
    "components['schemas']['Task']",
    'BrandFlowTask must alias the OpenAPI Task schema',
  )
  const workspaceAlias = source.match(/export type BrandFlowWorkspace = ([^\n]+)/)
  assert.ok(workspaceAlias, 'BrandFlowWorkspace type not found')
  assert.equal(
    workspaceAlias[1].trim(),
    "components['schemas']['TaskWorkspace']",
    'BrandFlowWorkspace must alias the OpenAPI TaskWorkspace schema',
  )
})

test('hand-written brandflow.types.ts re-exports server enums instead of duplicating them', async () => {
  const source = await read('src/types/brandflow.types.ts')
  assert.match(
    source,
    /from '\.\/generated\/brandflow-api'/,
    'brandflow.types.ts must import the generated contract types',
  )
  assert.match(source, /export type TaskStatus = components\['schemas'\]\['TaskStatus'\]/)
  assert.match(source, /export type Channel = components\['schemas'\]\['Channel'\]/)
  assert.doesNotMatch(
    source,
    /'waiting_for_outline_approval'/,
    'server enum literals must not be hand-duplicated in brandflow.types.ts',
  )
})

test('OpenAPI documents the consumer material endpoints with idempotency headers', async () => {
  const contract = yaml.load(await read('docs/brandflow-openapi.yaml'))
  const paths = contract.paths
  for (const path of [
    '/api/v1/consumer/materials',
    '/api/v1/consumer/materials/text',
    '/api/v1/consumer/materials/url',
    '/api/v1/consumer/materials/upload',
    '/api/v1/consumer/materials/{document_id}',
    '/api/v1/consumer/materials/{document_id}/excerpts',
  ]) {
    assert.ok(paths[path], `material path ${path} is missing from the OpenAPI contract`)
  }
  for (const path of [
    '/api/v1/consumer/materials/text',
    '/api/v1/consumer/materials/url',
    '/api/v1/consumer/materials/upload',
  ]) {
    const parameters = paths[path].post.parameters || []
    const idempotency = parameters.find(parameter => parameter.name === 'Idempotency-Key')
    assert.ok(idempotency, `${path} must declare an Idempotency-Key header`)
    assert.equal(idempotency.in, 'header')
  }
  const generated = await readFile(
    new URL('../../src/types/generated/brandflow-api.ts', import.meta.url),
    'utf8',
  )
  assert.match(
    generated,
    /"\/api\/v1\/consumer\/materials"/,
    'generated types must include the consumer materials route',
  )
})

test('OpenAPI documents the consumer project and draft endpoints', async () => {
  const contract = yaml.load(await read('docs/brandflow-openapi.yaml'))
  const paths = contract.paths
  for (const path of [
    '/api/v1/consumer/projects',
    '/api/v1/consumer/projects/{task_id}',
    '/api/v1/consumer/projects/{task_id}/draft',
    '/api/v1/consumer/projects/{task_id}/draft/adopt',
    '/api/v1/consumer/projects/{task_id}/draft/generate',
    '/api/v1/consumer/projects/{task_id}/draft/apply-candidate',
    '/api/v1/consumer/projects/{task_id}/materials/{excerpt_id}',
  ]) {
    assert.ok(paths[path], `consumer project path ${path} is missing from the OpenAPI contract`)
  }
  const draftPut = paths['/api/v1/consumer/projects/{task_id}/draft'].put
  assert.ok(draftPut, 'draft PUT operation must exist')
  assert.ok(
    JSON.stringify(draftPut.responses).includes('409'),
    'draft PUT must document the REVISION_CONFLICT 409 response',
  )
  const adopt = paths['/api/v1/consumer/projects/{task_id}/draft/adopt'].post
  assert.ok(
    JSON.stringify(adopt.responses).includes('409'),
    'adopt must document the revision conflict response',
  )
})

test('OpenAPI documents the anchored editorial suggestion endpoints', async () => {
  const contract = yaml.load(await read('docs/brandflow-openapi.yaml'))
  const paths = contract.paths
  const proposePath = '/api/v1/consumer/projects/{task_id}/suggestions'
  const acceptPath = '/api/v1/consumer/projects/{task_id}/suggestions/{suggestion_id}/accept'
  assert.ok(paths[proposePath], 'suggestion propose path is missing')
  assert.ok(paths[acceptPath], 'suggestion accept path is missing')
  const propose = paths[proposePath].post
  const actionSchema = propose.requestBody.content['application/json'].schema.properties.action
  assert.deepEqual(
    actionSchema.enum,
    ['expand', 'replace_example', 'shorten'],
    'propose must pin the three supported actions',
  )
  assert.ok(
    JSON.stringify(propose.responses).includes('409'),
    'propose must document the stale-selection 409',
  )
  const accept = paths[acceptPath].post
  assert.ok(
    JSON.stringify(accept.responses).includes('409'),
    'accept must document the stale-selection 409',
  )
})
