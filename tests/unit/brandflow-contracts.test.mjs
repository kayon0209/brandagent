import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const yaml = require('js-yaml')

const read = path => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

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

test('OpenAPI contract exposes task lifecycle and approval endpoints', async () => {
  const contract = await read('docs/brandflow-openapi.yaml')
  const document = yaml.load(contract)
  assert.equal(document.openapi, '3.1.0')
  assert.ok(document.components.pathItems.ApprovalPost.post)
  for (const path of [
    '/api/v1/tasks:',
    '/api/v1/tasks/{task_id}:',
    '/api/v1/tasks/{task_id}/events:',
    '/api/v1/tasks/{task_id}/clarification:',
    '/api/v1/tasks/{task_id}/outline/approve:',
    '/api/v1/tasks/{task_id}/master/approve:',
    '/api/v1/tasks/{task_id}/final/approve:',
    '/api/v1/tasks/{task_id}/export:',
    '/api/v1/tools:',
    '/api/v1/health:',
    '/api/v1/readiness:',
  ]) {
    assert.ok(contract.includes(path), `${path} is missing`)
  }
  assert.match(contract, /Idempotency-Key/)
  assert.match(contract, /text\/event-stream/)

  const resolvePointer = pointer =>
    pointer
      .slice(2)
      .split('/')
      .reduce((value, key) => value?.[key.replaceAll('~1', '/').replaceAll('~0', '~')], document)
  const refs = [...contract.matchAll(/\$ref:\s*['"](#[^'"]+)['"]/g)].map(match => match[1])
  for (const ref of refs) assert.ok(resolvePointer(ref), `Unresolved OpenAPI ref: ${ref}`)
})
