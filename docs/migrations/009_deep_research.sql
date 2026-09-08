-- ============================================================
-- 009 — Phase 6: deep research runs (深度调研) candidate material
-- User-approved additive migration (2026-09-08, decision recorded
-- in MASTER_PLAN.md「Phase 6 立项决定」).
--
-- Additive only: new tables, no changes to 001-008 objects.
-- Deep research results default to CANDIDATE material: nothing enters
-- the material library until the user picks 加入素材 (join_material).
-- Cancel is cooperative: workers poll `cancel_requested` between
-- directions, partial results are preserved (state='canceled').
-- ============================================================

CREATE TABLE IF NOT EXISTS deep_research_runs (
  run_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  question TEXT NOT NULL CHECK (length(trim(question)) BETWEEN 4 AND 500),
  audience TEXT NOT NULL DEFAULT '',
  scope_hint TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned','running','succeeded','failed','canceled')),
  planned_directions JSONB NOT NULL DEFAULT '[]'::jsonb,   -- planner output (≤4 strings)
  candidate_cards JSONB NOT NULL DEFAULT '[]'::jsonb,     -- validated evidence cards
  synthesis TEXT NOT NULL DEFAULT '',
  directions_completed INTEGER NOT NULL DEFAULT 0 CHECK (directions_completed >= 0),
  citations_valid INTEGER NOT NULL DEFAULT 0,
  citations_invalid INTEGER NOT NULL DEFAULT 0,
  search_calls INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  tokens_estimated INTEGER,                                -- ledger reservation snapshot
  tokens_used INTEGER,
  request_id TEXT NOT NULL,                                -- ledger Idempotency-Key
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cancel_requested_at TIMESTAMPTZ,                         -- cooperative cancel flag (workers poll)
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS deep_research_runs_workspace_idx
  ON deep_research_runs(workspace_id, created_at DESC);

-- Events for the SSE stream. Same wire pattern as task_events
-- (002): IDENTITY cursor for Last-Event-ID resume; public_payload
-- stays public, private search internals never ride the stream.
CREATE TABLE IF NOT EXISTS deep_research_events (
  event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  run_id UUID NOT NULL REFERENCES deep_research_runs(run_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  event_version TEXT NOT NULL DEFAULT '1.0',
  public_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  request_id TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS deep_research_events_stream_idx
  ON deep_research_events(workspace_id, run_id, event_id);

-- Row Level Security, same fail-closed predicate and FORCE pattern as
-- 004+005: workspace-scoped, owner bypass closed.
DO $$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['deep_research_runs', 'deep_research_events'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('CREATE POLICY brandflow_consumer_workspace_scope ON %I USING (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid)', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END $$;
