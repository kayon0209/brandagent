-- Consumer experience schema (upgrade plan task 5)
-- Additive only: no DROP, no RENAME, no TRUNCATE, no ALTER on 001/002 tables.
-- Layer: consumer experience tables on top of the BrandFlow V2 foundation.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. creator_profiles — personal identity of the individual creator
-- ============================================================
CREATE TABLE IF NOT EXISTS creator_profiles (
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  user_id TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  brand_name TEXT,
  audience TEXT,
  voice_traits JSONB NOT NULL DEFAULT '{}'::jsonb,
  preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id)
);

-- ============================================================
-- 2. consumer_projects — personal project aggregate over content_tasks
-- ============================================================
CREATE TABLE IF NOT EXISTS consumer_projects (
  task_id UUID PRIMARY KEY REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  core_idea TEXT NOT NULL DEFAULT '',
  writing_intent TEXT NOT NULL DEFAULT '',
  active_master_version_id UUID REFERENCES content_versions(content_version_id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS consumer_projects_workspace_idx ON consumer_projects(workspace_id, updated_at DESC);

-- ============================================================
-- 3. consumer_drafts — autosaved editable draft per project
-- ============================================================
CREATE TABLE IF NOT EXISTS consumer_drafts (
  task_id UUID PRIMARY KEY REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
  document JSONB NOT NULL,
  plain_text TEXT NOT NULL DEFAULT '',
  last_snapshot_version_id UUID REFERENCES content_versions(content_version_id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by TEXT
);
CREATE INDEX IF NOT EXISTS consumer_drafts_workspace_idx ON consumer_drafts(workspace_id, updated_at DESC);

-- ============================================================
-- 4. material_excerpts — traceable distilled material (never verified_facts)
-- ============================================================
CREATE TABLE IF NOT EXISTS material_excerpts (
  excerpt_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  document_id UUID NOT NULL REFERENCES source_documents(document_id) ON DELETE CASCADE,
  chunk_id UUID NOT NULL REFERENCES source_chunks(chunk_id) ON DELETE CASCADE,
  excerpt_type TEXT NOT NULL CHECK (excerpt_type IN ('quote','claim','example','voice_sample')),
  summary TEXT NOT NULL,
  excerpt_text TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  provenance_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','needs_review','rejected')),
  created_by_type TEXT NOT NULL CHECK (created_by_type IN ('human','model')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS material_excerpts_workspace_status_idx ON material_excerpts(workspace_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS material_excerpts_document_idx ON material_excerpts(document_id, chunk_id);

-- ============================================================
-- 5. project_material_links — which excerpts a project references
-- ============================================================
CREATE TABLE IF NOT EXISTS project_material_links (
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  excerpt_id UUID NOT NULL REFERENCES material_excerpts(excerpt_id) ON DELETE CASCADE,
  pinned BOOLEAN NOT NULL DEFAULT FALSE,
  position INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (task_id, excerpt_id)
);
CREATE INDEX IF NOT EXISTS project_material_links_workspace_idx ON project_material_links(workspace_id, task_id, position);

-- ============================================================
-- 6. editor_suggestions — anchored selection proposals with stale protection
-- ============================================================
CREATE TABLE IF NOT EXISTS editor_suggestions (
  suggestion_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  task_id UUID NOT NULL REFERENCES content_tasks(task_id) ON DELETE CASCADE,
  base_revision BIGINT NOT NULL CHECK (base_revision >= 0),
  block_id TEXT NOT NULL,
  start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
  end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
  selected_text_hash TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('expand','replace_example','shorten')),
  proposal_text TEXT NOT NULL,
  supporting_excerpt_ids UUID[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','accepted','rejected','stale')),
  model_call_id UUID REFERENCES model_call_logs(model_call_id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS editor_suggestions_task_idx ON editor_suggestions(task_id, status, created_at DESC);

-- ============================================================
-- 7. usage_ledger — idempotent per-workspace request settlement
-- ============================================================
CREATE TABLE IF NOT EXISTS usage_ledger (
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  request_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  model TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  estimated_cost NUMERIC(18,8),
  state TEXT NOT NULL CHECK (state IN ('reserved','settled','refunded')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  settled_at TIMESTAMPTZ,
  PRIMARY KEY (workspace_id, request_id)
);
