-- ============================================================
-- 005_consumer_rls_hardening.sql — FORCE ROW LEVEL SECURITY
--
-- Acceptance P1-5 (user-authorized schema change, 2026-09-01):
-- 004 enabled RLS on the seven consumer tables, but ENABLE alone does
-- not bind the table OWNER: a superuser or the owning role bypasses
-- every policy unconditionally (relforcerowsecurity was 'f' on the
-- disposable verification database). FORCE closes that bypass surface —
-- even the table owner is now subject to the workspace policies.
--
-- ADDITIVE ONLY: no columns, no data, no policy rewrites, no changes
-- to 004. The existing brandflow_consumer_workspace_scope policies
-- from 004 keep providing the fail-closed predicate:
--   workspace_id = NULLIF(current_setting('app.workspace_id', true), '')
-- so without app.workspace_id every row is invisible AND unwritable.
--
-- Migration-executor note: run as the migration role, then continue
-- applying via the same numbered pipeline. The business role
-- (brandflow_app) is NOT the owner and was already policy-bound.
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
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END $$;
