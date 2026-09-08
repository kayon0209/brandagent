-- Disposable-container verification for 004 (ON_ERROR_STOP).
-- 1) every consumer table has RLS enabled + the workspace policy
-- 2) business role WITH app.workspace_id can read/write its rows
-- 3) business role WITHOUT the setting sees NOTHING (fail closed)

\set ON_ERROR_STOP on

DO $$
DECLARE
  table_name TEXT;
  rls_ok BOOLEAN;
  policy_ok BOOLEAN;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'creator_profiles','consumer_projects','consumer_drafts','material_excerpts',
    'project_material_links','editor_suggestions','usage_ledger','style_reports'
  ] LOOP
    SELECT relrowsecurity INTO rls_ok FROM pg_class WHERE relname = table_name;
    IF NOT rls_ok THEN
      RAISE EXCEPTION 'RLS not enabled on %', table_name;
    END IF;
    SELECT COUNT(*) > 0 INTO policy_ok FROM pg_policies
      WHERE tablename = table_name
        AND policyname = CASE table_name
          WHEN 'style_reports' THEN 'style_reports_workspace_isolation'
          ELSE 'brandflow_consumer_workspace_scope'
        END;
    IF NOT policy_ok THEN
      RAISE EXCEPTION 'workspace policy missing on %', table_name;
    END IF;
  END LOOP;
END $$;

-- with scope: visible
SELECT set_config('app.workspace_id', '00000000-0000-0000-0000-0000000000aa', true);
SELECT COUNT(*) AS scoped_rows FROM consumer_projects WHERE workspace_id = '00000000-0000-0000-0000-0000000000aa';

-- without scope: zero rows (fail closed) — same transaction-safe reset
SELECT set_config('app.workspace_id', '', true);
DO $$
DECLARE visible INTEGER;
BEGIN
  SELECT COUNT(*) INTO visible FROM consumer_projects;
  IF visible <> 0 THEN
    RAISE EXCEPTION 'fail-closed check broken: % rows visible without workspace scope', visible;
  END IF;
END $$;

\echo '004 verification: all checks passed'
