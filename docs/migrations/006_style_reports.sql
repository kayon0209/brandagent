-- ============================================================
-- 006 — style distillation reports (round-3 six-layer feature)
-- Additive only: one new table, one new index; no existing object is
-- renamed or dropped. RLS follows the consumer pattern from 004/005.
-- ============================================================

CREATE TABLE IF NOT EXISTS style_reports (
  report_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
  form TEXT NOT NULL,
  language TEXT NOT NULL CHECK (language IN ('zh','en')),
  layers JSONB NOT NULL,
  corpus_digest TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS style_reports_workspace_idx
  ON style_reports(workspace_id, created_at DESC);

ALTER TABLE style_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY style_reports_workspace_isolation ON style_reports
  USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
  WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid);

-- harden against owner bypass like 005 does for the consumer tables
ALTER TABLE style_reports FORCE ROW LEVEL SECURITY;
