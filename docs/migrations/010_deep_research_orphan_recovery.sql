-- ============================================================
-- 010 — deep research orphan recovery: restricted security-definer
-- entry points (Phase 6 follow-up, RLS gap fix).
--
-- GAP being closed (found in deep review):
--   009 enabled AND FORCED RLS on deep_research_runs /
--   deep_research_events; brandflow_app is neither superuser nor
--   BYPASSRLS. PostgresDeepResearchStore.find_orphans() therefore
--   reads ZERO rows under production semantics, so a service restart
--   never fails restart-abandoned runs and never refunds their
--   ledger reservations.
--
-- DESIGN RULES (from the review contract):
--   * forward-only, additive: no changes to 001-009 objects;
--   * NO RLS disabling, NO BYPASSRLS, NO superuser connections, NO
--     global workspace_id bypass, NO swallowed exceptions;
--   * minimal privilege: each function does exactly ONE recovery
--     step and returns the minimal column set recovery needs;
--   * fixed safe search_path (pg_catalog, public) on every definer;
--   * explicit owner, explicit GRANT to brandflow_app only, and
--     REVOKE from PUBLIC so no other role gains the entry;
--   * the listing is NOT a generic cross-workspace read interface:
--     it only ever returns planned/running rows, never question /
--     synthesis / candidate content, never terminal history.
--
-- Both functions are owned by the migration owner (postgres, the
-- table owner). SECURITY DEFINER is what lets the business role
-- touch rows its RLS predicate would otherwise (correctly) hide;
-- the function bodies are the ONLY code that may do so, and they
-- are constrained to the two recovery-shaped mutations.
-- ============================================================

-- ------------------------------------------------------------
-- 1) LIST orphaned runs: planned/running only, minimal columns.
--    Read-only. No app.workspace_id is consulted or required.
-- ------------------------------------------------------------
CREATE FUNCTION public.deep_research_list_orphaned_runs()
RETURNS TABLE (
  run_id        uuid,
  workspace_id  uuid,
  request_id    text,
  created_by    text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT r.run_id, r.workspace_id, r.request_id, r.created_by
    FROM public.deep_research_runs AS r
   WHERE r.status IN ('planned', 'running')
$$;

COMMENT ON FUNCTION public.deep_research_list_orphaned_runs() IS
  'Deep research startup recovery: list restart-orphaned (planned/running) runs across workspaces. Minimal identification columns only; not a general cross-workspace read path.';

-- ------------------------------------------------------------
-- 2) FAIL one orphan: planned/running -> failed, atomically and
--    idempotently. Terminal runs are refused (returns false), so a
--    raced completion is never overwritten by recovery.
--    The error message is FIXED by the migration — honest refund
--    wording belongs to the data contract, not to each caller.
-- ------------------------------------------------------------
CREATE FUNCTION public.deep_research_fail_orphaned_run(p_run_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_current_status text;
BEGIN
  SELECT r.status INTO v_current_status
    FROM public.deep_research_runs AS r
   WHERE r.run_id = p_run_id
     FOR UPDATE;
  IF NOT FOUND THEN
    RETURN false;  -- unknown run: caller reports, nothing was mutated
  END IF;
  IF v_current_status NOT IN ('planned', 'running') THEN
    RETURN false;  -- terminal: NEVER rewritten by recovery
  END IF;
  UPDATE public.deep_research_runs
     SET status = 'failed',
         error = '服务重启导致调研中断，额度已退回。',
         completed_at = now(),
         cancel_requested_at = NULL
   WHERE public.deep_research_runs.run_id = p_run_id;
  RETURN true;
END;
$$;

COMMENT ON FUNCTION public.deep_research_fail_orphaned_run(uuid) IS
  'Deep research startup recovery: fail exactly one restart-orphaned (planned/running) run. Terminal and unknown runs are refused (returns false). Not a general cross-workspace write path.';

-- ------------------------------------------------------------
-- Privilege boundary: ONLY the business role gets the two entry
-- points; every other role (PUBLIC, brandflow_checkpoint, any
-- future role) is explicitly denied. REVOKE ... FROM PUBLIC is the
-- default posture but is stated here for auditability.
-- ------------------------------------------------------------

REVOKE ALL ON FUNCTION public.deep_research_list_orphaned_runs() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.deep_research_fail_orphaned_run(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.deep_research_list_orphaned_runs() TO brandflow_app;
GRANT EXECUTE ON FUNCTION public.deep_research_fail_orphaned_run(uuid) TO brandflow_app;

REVOKE EXECUTE ON FUNCTION public.deep_research_list_orphaned_runs() FROM brandflow_checkpoint;
REVOKE EXECUTE ON FUNCTION public.deep_research_fail_orphaned_run(uuid) FROM brandflow_checkpoint;
