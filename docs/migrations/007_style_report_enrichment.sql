-- ============================================================
-- 007 — style report enrichment and project binding
-- Additive only: binds one optional report to a consumer project and
-- preserves corpus provenance needed to render a report archive.
-- ============================================================

ALTER TABLE consumer_projects
  ADD COLUMN IF NOT EXISTS preferred_style_report_id UUID
  REFERENCES style_reports(report_id) ON DELETE SET NULL;

ALTER TABLE style_reports
  ADD COLUMN IF NOT EXISTS corpus_stats JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE style_reports
  ADD COLUMN IF NOT EXISTS corpus_articles JSONB NOT NULL DEFAULT '[]'::jsonb;
