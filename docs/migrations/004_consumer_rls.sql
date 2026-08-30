-- ============================================================
-- 004_consumer_rls.sql — row-level security for the consumer tables
-- Security-review P1 fix: the seven 003 tables relied only on
-- application-level WHERE clauses; this extends the same fail-closed
-- workspace policy batch from 002 (line 670) to the consumer surfaces.
--
-- ADDITIVE ONLY: enables RLS + policies; no columns, no data changes.
-- Repository connections already set app.workspace_id at transaction
-- scope, so policies fail closed when the setting is absent.
-- ============================================================

DO $$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'creator_profiles',
    'consumer_projects',
    'consumer_drafts',
    'material_excerpts',
    'project_material_links',
    'editor_suggestions',
    'usage_ledger'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY brandflow_consumer_workspace_scope ON %I USING (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid)',
      table_name
    );
  END LOOP;
END $$;
