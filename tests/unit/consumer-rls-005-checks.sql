-- Disposable-container verification for 005 (ON_ERROR_STOP).
--
-- 004 verified RLS enabled + the fail-closed workspace policy. 005 adds
-- FORCE ROW LEVEL SECURITY, closing the OWNER-BYPASS surface: with
-- ENABLE alone the table owner ignores every policy; FORCE binds the
-- owner too. PostgreSQL superusers keep BYPASSRLS regardless (design),
-- so the gate proves owner-binding through the catalog flags plus a
-- NON-superuser probe role.

\set ON_ERROR_STOP on

-- 1) every consumer table: RLS enabled AND forced
DO $$
DECLARE table_name TEXT;
  rls_ok BOOLEAN;
  force_ok BOOLEAN;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'creator_profiles','consumer_projects','consumer_drafts','material_excerpts',
    'project_material_links','editor_suggestions','usage_ledger','style_reports'
  ] LOOP
    SELECT relrowsecurity, relforcerowsecurity INTO rls_ok, force_ok
      FROM pg_class WHERE relname = table_name;
    IF NOT rls_ok THEN
      RAISE EXCEPTION 'RLS not enabled on %', table_name;
    END IF;
    IF NOT force_ok THEN
      RAISE EXCEPTION 'FORCE ROW LEVEL SECURITY missing on % — the owner bypass is still open', table_name;
    END IF;
  END LOOP;
END $$;

-- 2) owner-binding probe: reassign one consumer table to a dedicated
--    NON-superuser owner and confirm the OWNER sees zero rows without
--    app.workspace_id. Without FORCE this probe would see 1 row and
--    fail; with FORCE the owner is policy-bound. The visibility result is
--    handed back through the temp table in step 3 (dynamic EXECUTE
--    cannot write plpgsql variables directly).
DO $$
DECLARE
  probe_role TEXT := 'rls005_owner_probe';
  ws UUID := '00000000-0000-0000-0000-000000000f05';
BEGIN
  -- seed a workspace + project row (as the migration/superuser role)
  INSERT INTO workspaces(workspace_id, name, slug, created_by)
    VALUES (ws, 'RLS 005 check', 'rls-005-check', 'migration')
    ON CONFLICT (workspace_id) DO NOTHING;
  INSERT INTO content_tasks(task_id, workspace_id, user_id, title)
    VALUES ('00000000-0000-0000-0000-000000000705', ws, 'migration', 'RLS 005 probe')
    ON CONFLICT (task_id) DO NOTHING;
  INSERT INTO consumer_projects(task_id, workspace_id, core_idea)
    VALUES ('00000000-0000-0000-0000-000000000705', ws, '005 probe')
    ON CONFLICT (task_id) DO NOTHING;

  -- a non-superuser owner role (fresh each run; disposable container).
  -- CREATE on the schema is required to ACCEPT table ownership.
  EXECUTE format('DROP ROLE IF EXISTS %I', probe_role);
  EXECUTE format('CREATE ROLE %I LOGIN', probe_role);
  EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', probe_role);
  EXECUTE format('GRANT CREATE ON SCHEMA public TO %I', probe_role);
  EXECUTE format('GRANT SELECT ON consumer_projects TO %I', probe_role);
  -- hand over OWNERSHIP: this role now owns the table
  EXECUTE format('ALTER TABLE consumer_projects OWNER TO %I', probe_role);

  RAISE NOTICE '005: owner probe role now owns consumer_projects';
END $$;

-- 3) owner-visibility handoff through a temp table the gate can read.
--    The probe role needs explicit rights on the temp table (created by
--    the migration role) to write its count back.
CREATE TEMP TABLE _rls005_owner_visible AS
  SELECT 0 AS n;

DO $$
DECLARE probe_role TEXT := 'rls005_owner_probe';
BEGIN
  EXECUTE format('GRANT ALL ON _rls005_owner_visible TO %I', probe_role);
  EXECUTE format('SET ROLE %I', probe_role);
  EXECUTE 'SELECT set_config(''app.workspace_id'', '''', true)';
  EXECUTE 'TRUNCATE _rls005_owner_visible';
  EXECUTE 'INSERT INTO _rls005_owner_visible SELECT COUNT(*) FROM consumer_projects';
  EXECUTE 'RESET ROLE';
END $$;

DO $$
DECLARE visible INTEGER;
BEGIN
  SELECT n INTO visible FROM _rls005_owner_visible;
  IF visible <> 0 THEN
    RAISE EXCEPTION '005 FAILED: the table owner still sees % row(s) without app.workspace_id — FORCE is not binding', visible;
  END IF;
  RAISE NOTICE '005: owner sees 0 rows without the workspace scope — owner bypass closed';
END $$;

-- 4) business role re-verification: fail-closed still holds after FORCE
DO $$
DECLARE probe_role TEXT := 'rls005_owner_probe';
BEGIN
  EXECUTE format('SET ROLE %I', probe_role);
  EXECUTE 'SELECT set_config(''app.workspace_id'', ''' || '00000000-0000-0000-0000-000000000f05' || ''', true)';
  EXECUTE 'TRUNCATE _rls005_owner_visible';
  EXECUTE 'INSERT INTO _rls005_owner_visible SELECT COUNT(*) FROM consumer_projects';
  EXECUTE 'RESET ROLE';
END $$;

DO $$
DECLARE visible INTEGER;
BEGIN
  SELECT n INTO visible FROM _rls005_owner_visible;
  IF visible < 1 THEN
    RAISE EXCEPTION '005 FAILED: a scoped owner must still see its own workspace row';
  END IF;
END $$;

-- 5) restore ownership to the migration role so later migrations run
--    normally; drop every grant the probe role still holds (temp-table
--    ACLs keep it referenced) before dropping the role itself.
DO $$
DECLARE probe_role TEXT := 'rls005_owner_probe';
BEGIN
  -- postgres (superuser) can always re-take ownership
  EXECUTE 'ALTER TABLE consumer_projects OWNER TO postgres';
  EXECUTE 'REVOKE ALL ON _rls005_owner_visible FROM ' || quote_ident(probe_role);
  EXECUTE 'REVOKE CREATE ON SCHEMA public FROM ' || quote_ident(probe_role);
  EXECUTE 'REVOKE USAGE ON SCHEMA public FROM ' || quote_ident(probe_role);
  EXECUTE 'REVOKE SELECT ON consumer_projects FROM ' || quote_ident(probe_role);
  EXECUTE format('DROP ROLE IF EXISTS %I', probe_role);
END $$;

\echo '005 verification: RLS enabled + FORCED on all consumer tables; owner bypass closed'
