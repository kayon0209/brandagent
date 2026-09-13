-- Disposable-container verification for 011 (ON_ERROR_STOP).
-- The checkpoint role must never gain access to a legacy table-owner RPC.

\set ON_ERROR_STOP on

DO $$
DECLARE
  token_rpc regprocedure := 'public.increment_token_used(text,integer)'::regprocedure;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_proc
    WHERE oid = token_rpc
      AND 'search_path=pg_catalog, public' = ANY(COALESCE(proconfig, ARRAY[]::text[]))
  ) THEN
    RAISE EXCEPTION '011 FAILED: increment_token_used must pin search_path to pg_catalog, public';
  END IF;

  IF has_function_privilege('brandflow_checkpoint', token_rpc, 'EXECUTE') THEN
    RAISE EXCEPTION '011 FAILED: brandflow_checkpoint must not execute increment_token_used';
  END IF;

  -- Prove the ACL at the call boundary, not merely from the catalog.
  EXECUTE 'SET ROLE brandflow_checkpoint';
  BEGIN
    PERFORM public.increment_token_used('__checkpoint_denied_probe__', 0);
    RAISE EXCEPTION '011 FAILED: checkpoint role invoked increment_token_used';
  EXCEPTION
    WHEN insufficient_privilege THEN
      NULL;
  END;
  EXECUTE 'RESET ROLE';
EXCEPTION
  WHEN OTHERS THEN
    EXECUTE 'RESET ROLE';
    RAISE;
END
$$;

\echo '011 verification: token SECURITY DEFINER RPC is pinned and denied to checkpoint role'
