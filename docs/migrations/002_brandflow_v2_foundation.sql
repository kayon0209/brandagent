-- BrandFlow V2 foundation
-- Additive only. Do not execute against a remote database until reviewed.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS workspaces (
  workspace_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  default_locale TEXT NOT NULL DEFAULT 'zh-CN',
  approval_policy JSONB NOT NULL DEFAULT '{"separation_of_duties":true}'::jsonb,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_members (
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('content_operator','brand_reviewer','final_approver','admin')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('invited','active','suspended','removed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS content_tasks (
  task_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','validating_brief','waiting_for_clarification','researching','waiting_for_outline_approval','generating_master','reviewing_master','waiting_for_master_approval','generating_channels','reviewing_channels','waiting_for_final_approval','exporting','completed','failed','cancelled')),
  selected_channels TEXT[] NOT NULL DEFAULT '{}',
  current_node TEXT,
  error JSONB,
  cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
  state_version TEXT NOT NULL DEFAULT '2.0',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS content_tasks_workspace_status_idx ON content_tasks(workspace_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS content_briefs (
  brief_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL UNIQUE REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  topic TEXT NOT NULL DEFAULT '',
  brand_id UUID,
  product_id UUID,
  target_audience TEXT NOT NULL DEFAULT '',
  publishing_objective TEXT NOT NULL DEFAULT '',
  primary_channel TEXT,
  selected_derivative_channels TEXT[] NOT NULL DEFAULT '{}',
  desired_audience_action TEXT NOT NULL DEFAULT '',
  deadline TIMESTAMPTZ,
  target_length INTEGER CHECK (target_length IS NULL OR target_length > 0),
  required_messages JSONB NOT NULL DEFAULT '[]'::jsonb,
  required_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
  required_source_ids UUID[] NOT NULL DEFAULT '{}',
  forbidden_claims JSONB NOT NULL DEFAULT '[]'::jsonb,
  tone JSONB NOT NULL DEFAULT '[]'::jsonb,
  brand_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
  reference_content_ids UUID[] NOT NULL DEFAULT '{}',
  clarification_history JSONB NOT NULL DEFAULT '[]'::jsonb,
  schema_version TEXT NOT NULL DEFAULT '2.0',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_documents (
  document_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  document_name TEXT NOT NULL,
  document_type TEXT NOT NULL CHECK (document_type IN ('product_fact','brand_guideline','channel_guideline','approved_content','campaign_information','forbidden_claim_rule','external_reference')),
  version TEXT NOT NULL,
  effective_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  authority_level TEXT NOT NULL CHECK (authority_level IN ('primary','approved','reference','unverified')),
  public_usage_allowed BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','expired','superseded','archived')),
  checksum TEXT NOT NULL,
  storage_reference TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, checksum)
);

CREATE TABLE IF NOT EXISTS source_chunks (
  chunk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES source_documents(document_id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  structured_path TEXT,
  embedding REAL[], -- upgraded to pgvector in a reviewed environment-specific migration
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS verified_facts (
  fact_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  product_id UUID NOT NULL,
  fact_content TEXT NOT NULL,
  source_document_id UUID NOT NULL REFERENCES source_documents(document_id) ON DELETE RESTRICT,
  source_chunk_id UUID REFERENCES source_chunks(chunk_id) ON DELETE RESTRICT,
  structured_field TEXT,
  version TEXT NOT NULL,
  effective_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  authority_level TEXT NOT NULL CHECK (authority_level IN ('primary','approved','reference','unverified')),
  public_usage_allowed BOOLEAN NOT NULL DEFAULT FALSE,
  approval_required BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','expired','superseded','archived')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS verified_facts_product_idx ON verified_facts(workspace_id, product_id, status);

CREATE TABLE IF NOT EXISTS brand_guideline_versions (
  guideline_version_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  brand_id UUID NOT NULL,
  version TEXT NOT NULL,
  positioning TEXT NOT NULL DEFAULT '',
  standard_terms JSONB NOT NULL DEFAULT '{}'::jsonb,
  tone JSONB NOT NULL DEFAULT '[]'::jsonb,
  required_language JSONB NOT NULL DEFAULT '[]'::jsonb,
  forbidden_expressions JSONB NOT NULL DEFAULT '[]'::jsonb,
  cta_guidance JSONB NOT NULL DEFAULT '{}'::jsonb,
  effective_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  active BOOLEAN NOT NULL DEFAULT FALSE,
  source_document_id UUID REFERENCES source_documents(document_id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, brand_id, version)
);

CREATE TABLE IF NOT EXISTS channel_spec_versions (
  channel_spec_version_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  channel TEXT NOT NULL CHECK (channel IN ('wechat_website','xiaohongshu','video_script_60s','marketing_email')),
  version TEXT NOT NULL,
  length_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  required_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
  tone JSONB NOT NULL DEFAULT '[]'::jsonb,
  cta_style JSONB NOT NULL DEFAULT '{}'::jsonb,
  hashtag_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  forbidden_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
  active BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, channel, version)
);

CREATE TABLE IF NOT EXISTS model_call_logs (
  model_call_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
  input_tokens INTEGER,
  output_tokens INTEGER,
  usage_source TEXT NOT NULL CHECK (usage_source IN ('provider','estimated','unavailable')),
  estimated_cost NUMERIC(18,8),
  currency TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('succeeded','failed','timed_out')),
  error_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_versions (
  content_version_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  content_type TEXT NOT NULL CHECK (content_type IN ('master_outline','master_draft','master_revised','master_approved','channel_draft','channel_revised','channel_approved')),
  channel TEXT CHECK (channel IS NULL OR channel IN ('wechat_website','xiaohongshu','video_script_60s','marketing_email')),
  version_number INTEGER NOT NULL CHECK (version_number > 0),
  parent_version_id UUID REFERENCES content_versions(content_version_id) ON DELETE RESTRICT,
  master_content_version_id UUID REFERENCES content_versions(content_version_id) ON DELETE RESTRICT,
  content TEXT NOT NULL,
  structured_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
  review_status TEXT NOT NULL DEFAULT 'not_started' CHECK (review_status IN ('not_started','in_review','passed','failed')),
  approval_status TEXT NOT NULL DEFAULT 'pending' CHECK (approval_status IN ('not_required','pending','approved','rejected','invalidated')),
  immutable_hash TEXT NOT NULL,
  created_by_type TEXT NOT NULL CHECK (created_by_type IN ('human','model','workflow')),
  created_by_id TEXT NOT NULL,
  model_call_id UUID REFERENCES model_call_logs(model_call_id) ON DELETE SET NULL,
  prompt_version TEXT,
  change_summary TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, content_type, channel, version_number),
  UNIQUE (content_version_id, immutable_hash)
);
CREATE INDEX IF NOT EXISTS content_versions_task_idx ON content_versions(workspace_id, task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS content_blocks (
  block_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  content_version_id UUID NOT NULL REFERENCES content_versions(content_version_id) ON DELETE CASCADE,
  block_type TEXT NOT NULL,
  position INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (content_version_id, position)
);

CREATE TABLE IF NOT EXISTS review_results (
  review_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  content_version_id UUID NOT NULL REFERENCES content_versions(content_version_id) ON DELETE CASCADE,
  review_type TEXT NOT NULL CHECK (review_type IN ('factual','citation','brief_coverage','brand','channel_format','compliance','cross_channel_consistency')),
  passed BOOLEAN NOT NULL,
  max_severity TEXT CHECK (max_severity IS NULL OR max_severity IN ('info','warning','critical')),
  revision_instructions JSONB NOT NULL DEFAULT '[]'::jsonb,
  reviewer_type TEXT NOT NULL CHECK (reviewer_type IN ('deterministic','model','human')),
  reviewer_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS review_issues (
  issue_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  review_id UUID NOT NULL REFERENCES review_results(review_id) ON DELETE CASCADE,
  issue_type TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  problematic_text TEXT,
  reason TEXT NOT NULL,
  supporting_fact_ids UUID[] NOT NULL DEFAULT '{}',
  missing_evidence TEXT,
  suggested_action TEXT NOT NULL,
  target_block_id UUID REFERENCES content_blocks(block_id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','accepted_risk')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS approval_requirements (
  approval_requirement_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  content_version_id UUID REFERENCES content_versions(content_version_id) ON DELETE CASCADE,
  decision_type TEXT NOT NULL CHECK (decision_type IN ('outline','master_brand','master_final','channel','final_package','export','preview','replace_approved_content')),
  required_role TEXT NOT NULL CHECK (required_role IN ('content_operator','brand_reviewer','final_approver','admin')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','satisfied','rejected','invalidated')),
  target_snapshot_hash TEXT NOT NULL,
  invalidated_at TIMESTAMPTZ,
  invalidation_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS human_decisions (
  decision_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  content_version_id UUID REFERENCES content_versions(content_version_id) ON DELETE RESTRICT,
  approval_requirement_id UUID REFERENCES approval_requirements(approval_requirement_id) ON DELETE RESTRICT,
  decision_type TEXT NOT NULL CHECK (decision_type IN ('outline','master_brand','master_final','channel','final_package','export','preview','replace_approved_content')),
  decision TEXT NOT NULL CHECK (decision IN ('approve','reject','request_revision','cancel','authorize')),
  comment TEXT NOT NULL DEFAULT '',
  user_id TEXT NOT NULL,
  user_role TEXT NOT NULL CHECK (user_role IN ('content_operator','brand_reviewer','final_approver','admin')),
  target_snapshot_hash TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS content_lineage (
  lineage_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  source_document_id UUID REFERENCES source_documents(document_id) ON DELETE RESTRICT,
  source_chunk_id UUID REFERENCES source_chunks(chunk_id) ON DELETE RESTRICT,
  fact_id UUID REFERENCES verified_facts(fact_id) ON DELETE RESTRICT,
  master_content_version_id UUID NOT NULL REFERENCES content_versions(content_version_id) ON DELETE CASCADE,
  master_block_id UUID NOT NULL REFERENCES content_blocks(block_id) ON DELETE CASCADE,
  channel_variant_id UUID REFERENCES content_versions(content_version_id) ON DELETE CASCADE,
  channel_block_id UUID REFERENCES content_blocks(block_id) ON DELETE CASCADE,
  transformation_type TEXT CHECK (transformation_type IS NULL OR transformation_type IN ('condense','rewrite','reorder','style_adaptation','cta_adaptation','format_conversion')),
  status TEXT NOT NULL DEFAULT 'supported' CHECK (status IN ('supported','unsupported_new_claim','invalidated')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS task_events (
  event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  event_version TEXT NOT NULL DEFAULT '1.0',
  public_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  workflow_node TEXT,
  request_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS task_events_stream_idx ON task_events(workspace_id, task_id, event_id);

CREATE TABLE IF NOT EXISTS tool_call_logs (
  tool_call_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  workflow_node TEXT NOT NULL,
  mcp_server TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  capability TEXT NOT NULL CHECK (capability IN ('read','write','high_risk')),
  sanitized_input JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_status TEXT NOT NULL CHECK (output_status IN ('succeeded','failed','timed_out','degraded','rejected')),
  latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
  error_code TEXT,
  error_summary TEXT,
  approval_requirement TEXT,
  approval_requirement_id UUID REFERENCES approval_requirements(approval_requirement_id) ON DELETE RESTRICT,
  approval_decision_id UUID REFERENCES human_decisions(decision_id) ON DELETE RESTRICT,
  target_snapshot_hash TEXT,
  approval_result TEXT NOT NULL CHECK (approval_result IN ('not_required','verified','missing','invalid')),
  idempotency_key TEXT,
  request_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS idempotency_records (
  idempotency_record_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  immutable_target TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started','succeeded','failed')),
  response_status INTEGER,
  response_body JSONB,
  lease_owner TEXT,
  lease_version BIGINT NOT NULL DEFAULT 0,
  lease_expires_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, actor_id, action, idempotency_key)
);

CREATE TABLE IF NOT EXISTS evaluation_tasks (
  evaluation_task_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
  evaluation_version TEXT NOT NULL,
  brief JSONB NOT NULL,
  product_facts JSONB NOT NULL,
  brand_guidelines JSONB NOT NULL,
  channel_specifications JSONB NOT NULL,
  required_messages JSONB NOT NULL DEFAULT '[]'::jsonb,
  forbidden_claims JSONB NOT NULL DEFAULT '[]'::jsonb,
  expected_constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
  human_reference JSONB,
  gold_fact_ids UUID[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
  evaluation_run_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
  evaluation_version TEXT NOT NULL,
  code_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled')),
  dataset_size INTEGER NOT NULL DEFAULT 0,
  limitations TEXT NOT NULL DEFAULT '',
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluation_metrics (
  evaluation_metric_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
  evaluation_run_id UUID NOT NULL REFERENCES evaluation_runs(evaluation_run_id) ON DELETE CASCADE,
  evaluation_task_id UUID REFERENCES evaluation_tasks(evaluation_task_id) ON DELETE SET NULL,
  metric_group TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value NUMERIC,
  metric_payload JSONB,
  measurement_source TEXT NOT NULL CHECK (measurement_source IN ('deterministic','human','model_judge')),
  judge_model TEXT,
  judge_prompt_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bad_cases (
  bad_case_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
  evaluation_run_id UUID REFERENCES evaluation_runs(evaluation_run_id) ON DELETE SET NULL,
  evaluation_task_id UUID REFERENCES evaluation_tasks(evaluation_task_id) ON DELETE SET NULL,
  task_id UUID REFERENCES content_tasks(task_id) ON DELETE SET NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('warning','critical')),
  summary TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','triaged','resolved','accepted')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_article_mappings (
  legacy_article_mapping_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  legacy_article_id UUID NOT NULL REFERENCES articles(id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE RESTRICT,
  legacy_content_hash TEXT NOT NULL,
  migrated_content_hash TEXT NOT NULL,
  migration_status TEXT NOT NULL CHECK (migration_status IN ('pending','verified','failed')),
  failure_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, legacy_article_id),
  UNIQUE (workspace_id, task_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS content_versions_master_number_uidx
  ON content_versions(task_id, content_type, version_number)
  WHERE channel IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS content_versions_channel_number_uidx
  ON content_versions(task_id, content_type, channel, version_number)
  WHERE channel IS NOT NULL;

ALTER TABLE content_versions ADD CONSTRAINT content_versions_kind_coherence_chk CHECK (
  (content_type LIKE 'master_%' AND channel IS NULL AND master_content_version_id IS NULL)
  OR
  (content_type LIKE 'channel_%' AND channel IS NOT NULL AND master_content_version_id IS NOT NULL)
);

-- Composite uniqueness allows every tenant-owned relationship to enforce that
-- the child and parent belong to the same workspace.
ALTER TABLE content_tasks ADD CONSTRAINT content_tasks_workspace_object_uk UNIQUE (workspace_id, task_id);
ALTER TABLE workspace_members ADD CONSTRAINT workspace_members_role_uk UNIQUE (workspace_id, user_id, role);
ALTER TABLE source_documents ADD CONSTRAINT source_documents_workspace_object_uk UNIQUE (workspace_id, document_id);
ALTER TABLE source_chunks ADD CONSTRAINT source_chunks_workspace_object_uk UNIQUE (workspace_id, chunk_id);
ALTER TABLE verified_facts ADD CONSTRAINT verified_facts_workspace_object_uk UNIQUE (workspace_id, fact_id);
ALTER TABLE model_call_logs ADD CONSTRAINT model_call_logs_workspace_object_uk UNIQUE (workspace_id, model_call_id);
ALTER TABLE model_call_logs ADD CONSTRAINT model_call_logs_task_object_uk UNIQUE (workspace_id, task_id, model_call_id);
ALTER TABLE content_versions ADD CONSTRAINT content_versions_workspace_object_uk UNIQUE (workspace_id, content_version_id);
ALTER TABLE content_versions ADD CONSTRAINT content_versions_task_object_uk UNIQUE (workspace_id, task_id, content_version_id);
ALTER TABLE content_blocks ADD CONSTRAINT content_blocks_workspace_object_uk UNIQUE (workspace_id, block_id);
ALTER TABLE content_blocks ADD CONSTRAINT content_blocks_task_object_uk UNIQUE (workspace_id, task_id, block_id);
ALTER TABLE review_results ADD CONSTRAINT review_results_workspace_object_uk UNIQUE (workspace_id, review_id);
ALTER TABLE review_results ADD CONSTRAINT review_results_task_object_uk UNIQUE (workspace_id, task_id, review_id);
ALTER TABLE approval_requirements ADD CONSTRAINT approval_requirements_workspace_object_uk UNIQUE (workspace_id, approval_requirement_id);
ALTER TABLE approval_requirements ADD CONSTRAINT approval_requirements_task_object_uk UNIQUE (workspace_id, task_id, approval_requirement_id);
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_workspace_object_uk UNIQUE (workspace_id, decision_id);
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_task_object_uk UNIQUE (workspace_id, task_id, decision_id);
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_requirement_once_uk UNIQUE (workspace_id, approval_requirement_id);
ALTER TABLE evaluation_tasks ADD CONSTRAINT evaluation_tasks_workspace_object_uk UNIQUE (workspace_id, evaluation_task_id);
ALTER TABLE evaluation_runs ADD CONSTRAINT evaluation_runs_workspace_object_uk UNIQUE (workspace_id, evaluation_run_id);

ALTER TABLE content_briefs ADD CONSTRAINT content_briefs_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE source_chunks ADD CONSTRAINT source_chunks_document_tenant_fk FOREIGN KEY (workspace_id, document_id) REFERENCES source_documents(workspace_id, document_id) ON DELETE CASCADE;
ALTER TABLE verified_facts ADD CONSTRAINT verified_facts_document_tenant_fk FOREIGN KEY (workspace_id, source_document_id) REFERENCES source_documents(workspace_id, document_id) ON DELETE RESTRICT;
ALTER TABLE verified_facts ADD CONSTRAINT verified_facts_chunk_tenant_fk FOREIGN KEY (workspace_id, source_chunk_id) REFERENCES source_chunks(workspace_id, chunk_id) ON DELETE RESTRICT;
ALTER TABLE brand_guideline_versions ADD CONSTRAINT brand_guidelines_document_tenant_fk FOREIGN KEY (workspace_id, source_document_id) REFERENCES source_documents(workspace_id, document_id) ON DELETE RESTRICT;
ALTER TABLE model_call_logs ADD CONSTRAINT model_calls_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE content_versions ADD CONSTRAINT content_versions_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE content_versions ADD CONSTRAINT content_versions_parent_task_fk FOREIGN KEY (workspace_id, task_id, parent_version_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE RESTRICT;
ALTER TABLE content_versions ADD CONSTRAINT content_versions_master_task_fk FOREIGN KEY (workspace_id, task_id, master_content_version_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE RESTRICT;
ALTER TABLE content_versions ADD CONSTRAINT content_versions_model_call_task_fk FOREIGN KEY (workspace_id, task_id, model_call_id) REFERENCES model_call_logs(workspace_id, task_id, model_call_id) ON DELETE RESTRICT;
ALTER TABLE content_versions ADD CONSTRAINT content_versions_parent_tenant_fk FOREIGN KEY (workspace_id, parent_version_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE RESTRICT;
ALTER TABLE content_versions ADD CONSTRAINT content_versions_master_tenant_fk FOREIGN KEY (workspace_id, master_content_version_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE RESTRICT;
ALTER TABLE content_versions ADD CONSTRAINT content_versions_model_call_tenant_fk FOREIGN KEY (workspace_id, model_call_id) REFERENCES model_call_logs(workspace_id, model_call_id) ON DELETE RESTRICT;
ALTER TABLE content_blocks ADD CONSTRAINT content_blocks_version_tenant_fk FOREIGN KEY (workspace_id, content_version_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE content_blocks ADD CONSTRAINT content_blocks_version_task_fk FOREIGN KEY (workspace_id, task_id, content_version_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE review_results ADD CONSTRAINT review_results_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE review_results ADD CONSTRAINT review_results_version_tenant_fk FOREIGN KEY (workspace_id, content_version_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE review_results ADD CONSTRAINT review_results_version_task_fk FOREIGN KEY (workspace_id, task_id, content_version_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE review_issues ADD CONSTRAINT review_issues_review_tenant_fk FOREIGN KEY (workspace_id, review_id) REFERENCES review_results(workspace_id, review_id) ON DELETE CASCADE;
ALTER TABLE review_issues ADD CONSTRAINT review_issues_block_tenant_fk FOREIGN KEY (workspace_id, target_block_id) REFERENCES content_blocks(workspace_id, block_id) ON DELETE RESTRICT;
ALTER TABLE review_issues ADD CONSTRAINT review_issues_review_task_fk FOREIGN KEY (workspace_id, task_id, review_id) REFERENCES review_results(workspace_id, task_id, review_id) ON DELETE CASCADE;
ALTER TABLE review_issues ADD CONSTRAINT review_issues_block_task_fk FOREIGN KEY (workspace_id, task_id, target_block_id) REFERENCES content_blocks(workspace_id, task_id, block_id) ON DELETE RESTRICT;
ALTER TABLE approval_requirements ADD CONSTRAINT approval_requirements_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE approval_requirements ADD CONSTRAINT approval_requirements_version_tenant_fk FOREIGN KEY (workspace_id, content_version_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE approval_requirements ADD CONSTRAINT approval_requirements_version_task_fk FOREIGN KEY (workspace_id, task_id, content_version_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_version_tenant_fk FOREIGN KEY (workspace_id, content_version_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE RESTRICT;
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_requirement_tenant_fk FOREIGN KEY (workspace_id, approval_requirement_id) REFERENCES approval_requirements(workspace_id, approval_requirement_id) ON DELETE RESTRICT;
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_member_tenant_fk FOREIGN KEY (workspace_id, user_id) REFERENCES workspace_members(workspace_id, user_id) ON DELETE RESTRICT;
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_version_task_fk FOREIGN KEY (workspace_id, task_id, content_version_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE RESTRICT;
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_requirement_task_fk FOREIGN KEY (workspace_id, task_id, approval_requirement_id) REFERENCES approval_requirements(workspace_id, task_id, approval_requirement_id) ON DELETE RESTRICT;
ALTER TABLE human_decisions ADD CONSTRAINT human_decisions_member_role_fk FOREIGN KEY (workspace_id, user_id, user_role) REFERENCES workspace_members(workspace_id, user_id, role) ON DELETE RESTRICT;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_document_tenant_fk FOREIGN KEY (workspace_id, source_document_id) REFERENCES source_documents(workspace_id, document_id) ON DELETE RESTRICT;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_chunk_tenant_fk FOREIGN KEY (workspace_id, source_chunk_id) REFERENCES source_chunks(workspace_id, chunk_id) ON DELETE RESTRICT;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_fact_tenant_fk FOREIGN KEY (workspace_id, fact_id) REFERENCES verified_facts(workspace_id, fact_id) ON DELETE RESTRICT;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_master_version_tenant_fk FOREIGN KEY (workspace_id, master_content_version_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_master_block_tenant_fk FOREIGN KEY (workspace_id, master_block_id) REFERENCES content_blocks(workspace_id, block_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_channel_version_tenant_fk FOREIGN KEY (workspace_id, channel_variant_id) REFERENCES content_versions(workspace_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_channel_block_tenant_fk FOREIGN KEY (workspace_id, channel_block_id) REFERENCES content_blocks(workspace_id, block_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_master_version_task_fk FOREIGN KEY (workspace_id, task_id, master_content_version_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_master_block_task_fk FOREIGN KEY (workspace_id, task_id, master_block_id) REFERENCES content_blocks(workspace_id, task_id, block_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_channel_version_task_fk FOREIGN KEY (workspace_id, task_id, channel_variant_id) REFERENCES content_versions(workspace_id, task_id, content_version_id) ON DELETE CASCADE;
ALTER TABLE content_lineage ADD CONSTRAINT lineage_channel_block_task_fk FOREIGN KEY (workspace_id, task_id, channel_block_id) REFERENCES content_blocks(workspace_id, task_id, block_id) ON DELETE CASCADE;
ALTER TABLE task_events ADD CONSTRAINT task_events_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE tool_call_logs ADD CONSTRAINT tool_calls_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE CASCADE;
ALTER TABLE tool_call_logs ADD CONSTRAINT tool_calls_requirement_tenant_fk FOREIGN KEY (workspace_id, approval_requirement_id) REFERENCES approval_requirements(workspace_id, approval_requirement_id) ON DELETE RESTRICT;
ALTER TABLE tool_call_logs ADD CONSTRAINT tool_calls_decision_tenant_fk FOREIGN KEY (workspace_id, approval_decision_id) REFERENCES human_decisions(workspace_id, decision_id) ON DELETE RESTRICT;
ALTER TABLE tool_call_logs ADD CONSTRAINT tool_calls_requirement_task_fk FOREIGN KEY (workspace_id, task_id, approval_requirement_id) REFERENCES approval_requirements(workspace_id, task_id, approval_requirement_id) ON DELETE RESTRICT;
ALTER TABLE tool_call_logs ADD CONSTRAINT tool_calls_decision_task_fk FOREIGN KEY (workspace_id, task_id, approval_decision_id) REFERENCES human_decisions(workspace_id, task_id, decision_id) ON DELETE RESTRICT;
ALTER TABLE evaluation_metrics ADD CONSTRAINT evaluation_metrics_run_tenant_fk FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs(workspace_id, evaluation_run_id) ON DELETE CASCADE;
ALTER TABLE evaluation_metrics ADD CONSTRAINT evaluation_metrics_task_tenant_fk FOREIGN KEY (workspace_id, evaluation_task_id) REFERENCES evaluation_tasks(workspace_id, evaluation_task_id) ON DELETE RESTRICT;
ALTER TABLE bad_cases ADD CONSTRAINT bad_cases_run_tenant_fk FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs(workspace_id, evaluation_run_id) ON DELETE RESTRICT;
ALTER TABLE bad_cases ADD CONSTRAINT bad_cases_evaluation_task_tenant_fk FOREIGN KEY (workspace_id, evaluation_task_id) REFERENCES evaluation_tasks(workspace_id, evaluation_task_id) ON DELETE RESTRICT;
ALTER TABLE bad_cases ADD CONSTRAINT bad_cases_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE RESTRICT;
ALTER TABLE legacy_article_mappings ADD CONSTRAINT legacy_mapping_task_tenant_fk FOREIGN KEY (workspace_id, task_id) REFERENCES content_tasks(workspace_id, task_id) ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION brandflow_reject_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION brandflow_validate_human_decision()
RETURNS TRIGGER AS $$
DECLARE
  member_role TEXT;
  member_status TEXT;
  required_role_value TEXT;
  requirement_decision_type TEXT;
  requirement_task UUID;
  requirement_version UUID;
  requirement_hash TEXT;
  requirement_status TEXT;
  task_submitter TEXT;
  version_creator_type TEXT;
  version_creator_id TEXT;
  version_hash TEXT;
BEGIN
  SELECT role, status INTO member_role, member_status
  FROM workspace_members
  WHERE workspace_id = NEW.workspace_id AND user_id = NEW.user_id;

  IF member_status IS DISTINCT FROM 'active' OR member_role IS DISTINCT FROM NEW.user_role THEN
    RAISE EXCEPTION 'decision actor role is not an active workspace membership' USING ERRCODE = '42501';
  END IF;

  IF NEW.approval_requirement_id IS NULL THEN
    RAISE EXCEPTION 'approval requirement is required' USING ERRCODE = '23514';
  END IF;

  SELECT required_role, decision_type, task_id, content_version_id, target_snapshot_hash, status
  INTO required_role_value, requirement_decision_type, requirement_task, requirement_version, requirement_hash, requirement_status
  FROM approval_requirements
  WHERE workspace_id = NEW.workspace_id
    AND approval_requirement_id = NEW.approval_requirement_id
  FOR UPDATE;

  IF requirement_status IS DISTINCT FROM 'pending'
    OR required_role_value IS DISTINCT FROM NEW.user_role
    OR requirement_decision_type IS DISTINCT FROM NEW.decision_type
    OR requirement_task IS DISTINCT FROM NEW.task_id
    OR requirement_version IS DISTINCT FROM NEW.content_version_id
    OR requirement_hash IS DISTINCT FROM NEW.target_snapshot_hash THEN
    RAISE EXCEPTION 'decision does not match pending approval requirement' USING ERRCODE = '23514';
  END IF;

  SELECT user_id INTO task_submitter FROM content_tasks
  WHERE workspace_id = NEW.workspace_id AND task_id = NEW.task_id;

  IF NEW.content_version_id IS NOT NULL THEN
    SELECT created_by_type, created_by_id, immutable_hash
    INTO version_creator_type, version_creator_id, version_hash
    FROM content_versions
    WHERE workspace_id = NEW.workspace_id
      AND task_id = NEW.task_id
      AND content_version_id = NEW.content_version_id;

    IF version_hash IS DISTINCT FROM NEW.target_snapshot_hash THEN
      RAISE EXCEPTION 'decision snapshot does not match immutable content version' USING ERRCODE = '23514';
    END IF;
  END IF;

  IF NEW.decision IN ('approve','authorize')
    AND (task_submitter = NEW.user_id OR (version_creator_type = 'human' AND version_creator_id = NEW.user_id)) THEN
    RAISE EXCEPTION 'separation of duties prevents self-approval' USING ERRCODE = '42501';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION brandflow_validate_tool_approval_log()
RETURNS TRIGGER AS $$
DECLARE
  decision_requirement UUID;
  decision_hash TEXT;
  decision_value TEXT;
  decision_type_value TEXT;
  requirement_type_value TEXT;
  requirement_status_value TEXT;
  requirement_hash TEXT;
BEGIN
  IF NEW.capability = 'high_risk' AND NEW.approval_result = 'verified' THEN
    IF NEW.approval_requirement_id IS NULL OR NEW.approval_decision_id IS NULL
      OR NEW.target_snapshot_hash IS NULL OR NEW.idempotency_key IS NULL THEN
      RAISE EXCEPTION 'verified high-risk tool log requires approval and idempotency evidence' USING ERRCODE = '23514';
    END IF;

    SELECT approval_requirement_id, target_snapshot_hash, decision, decision_type
    INTO decision_requirement, decision_hash, decision_value, decision_type_value
    FROM human_decisions
    WHERE workspace_id = NEW.workspace_id
      AND task_id = NEW.task_id
      AND decision_id = NEW.approval_decision_id;

    SELECT target_snapshot_hash, decision_type, status
    INTO requirement_hash, requirement_type_value, requirement_status_value
    FROM approval_requirements
    WHERE workspace_id = NEW.workspace_id
      AND task_id = NEW.task_id
      AND approval_requirement_id = NEW.approval_requirement_id;

    IF decision_requirement IS DISTINCT FROM NEW.approval_requirement_id
      OR decision_value NOT IN ('approve','authorize')
      OR decision_type_value IS DISTINCT FROM requirement_type_value
      OR requirement_status_value IS DISTINCT FROM 'satisfied'
      OR decision_hash IS DISTINCT FROM NEW.target_snapshot_hash
      OR requirement_hash IS DISTINCT FROM NEW.target_snapshot_hash THEN
      RAISE EXCEPTION 'verified high-risk tool log approval evidence is inconsistent' USING ERRCODE = '23514';
    END IF;

    IF (NEW.tool_name = 'export_content_package' AND requirement_type_value NOT IN ('export','final_package'))
      OR (NEW.tool_name = 'create_publish_preview' AND requirement_type_value NOT IN ('preview','final_package'))
      OR (NEW.tool_name = 'save_content_version' AND requirement_type_value <> 'replace_approved_content')
      OR (NEW.tool_name NOT IN ('export_content_package','create_publish_preview','save_content_version')) THEN
      RAISE EXCEPTION 'high-risk tool is not authorized by this decision type' USING ERRCODE = '42501';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION brandflow_apply_human_decision()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE approval_requirements
  SET status = CASE
    WHEN NEW.decision IN ('approve','authorize') THEN 'satisfied'
    WHEN NEW.decision = 'reject' THEN 'rejected'
    ELSE status
  END
  WHERE workspace_id = NEW.workspace_id
    AND task_id = NEW.task_id
    AND approval_requirement_id = NEW.approval_requirement_id
    AND status = 'pending';
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER human_decisions_validate BEFORE INSERT ON human_decisions FOR EACH ROW EXECUTE FUNCTION brandflow_validate_human_decision();
CREATE TRIGGER human_decisions_apply AFTER INSERT ON human_decisions FOR EACH ROW EXECUTE FUNCTION brandflow_apply_human_decision();
CREATE TRIGGER tool_call_logs_validate_approval BEFORE INSERT ON tool_call_logs FOR EACH ROW EXECUTE FUNCTION brandflow_validate_tool_approval_log();

CREATE TRIGGER content_versions_append_only BEFORE UPDATE OR DELETE ON content_versions FOR EACH ROW EXECUTE FUNCTION brandflow_reject_mutation();
CREATE TRIGGER content_blocks_append_only BEFORE UPDATE OR DELETE ON content_blocks FOR EACH ROW EXECUTE FUNCTION brandflow_reject_mutation();
CREATE TRIGGER human_decisions_append_only BEFORE UPDATE OR DELETE ON human_decisions FOR EACH ROW EXECUTE FUNCTION brandflow_reject_mutation();
CREATE TRIGGER task_events_append_only BEFORE UPDATE OR DELETE ON task_events FOR EACH ROW EXECUTE FUNCTION brandflow_reject_mutation();
CREATE TRIGGER tool_call_logs_append_only BEFORE UPDATE OR DELETE ON tool_call_logs FOR EACH ROW EXECUTE FUNCTION brandflow_reject_mutation();
CREATE TRIGGER model_call_logs_append_only BEFORE UPDATE OR DELETE ON model_call_logs FOR EACH ROW EXECUTE FUNCTION brandflow_reject_mutation();
CREATE TRIGGER content_lineage_append_only BEFORE UPDATE OR DELETE ON content_lineage FOR EACH ROW EXECUTE FUNCTION brandflow_reject_mutation();

-- Repository connections set app.workspace_id at transaction scope before
-- accessing tenant data. Policies fail closed when the setting is absent.
DO $$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'workspaces','workspace_members','content_tasks','content_briefs','source_documents',
    'source_chunks','verified_facts','brand_guideline_versions','channel_spec_versions',
    'model_call_logs','content_versions','content_blocks','review_results','review_issues',
    'approval_requirements','human_decisions','content_lineage','task_events','tool_call_logs',
    'idempotency_records','evaluation_tasks','evaluation_runs','evaluation_metrics','bad_cases',
    'legacy_article_mappings'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY brandflow_workspace_scope ON %I USING (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid)',
      table_name
    );
  END LOOP;
END $$;
