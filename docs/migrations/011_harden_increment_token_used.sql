-- ============================================================
-- 011 — restrict the legacy token-usage SECURITY DEFINER RPC.
--
-- 001 created increment_token_used(text, integer) for the trusted
-- Supabase service role, but left PostgreSQL's default PUBLIC EXECUTE
-- grant in place and did not pin search_path. A non-business role such
-- as brandflow_checkpoint could therefore invoke a table-owner function
-- and bypass RLS. This migration is forward-only: it changes no tables
-- and preserves the RPC's service-role contract.
-- ============================================================

-- SECURITY DEFINER functions must resolve unqualified names only through
-- trusted schemas; pg_catalog comes first to prevent shadowing.
ALTER FUNCTION public.increment_token_used(text, integer)
  SET search_path = pg_catalog, public;

-- Function EXECUTE is granted to PUBLIC by default. Remove that ambient
-- capability before granting the RPC to its only confirmed caller.
REVOKE ALL ON FUNCTION public.increment_token_used(text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_token_used(text, integer) FROM brandflow_app;
REVOKE EXECUTE ON FUNCTION public.increment_token_used(text, integer) FROM brandflow_checkpoint;

-- Next.js calls this RPC through the Supabase admin client, whose database
-- role is service_role. The disposable BrandFlow CI database deliberately
-- has no such role, so grant only when running in a Supabase deployment.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE 'GRANT EXECUTE ON FUNCTION public.increment_token_used(text, integer) TO service_role';
  END IF;
END
$$;
