-- Consumer experience migration checks
-- Runs on a fresh database after 001, 002 and 003. Every failure aborts with ON_ERROR_STOP.

\set ON_ERROR_STOP on

BEGIN;

INSERT INTO workspaces (workspace_id, name, slug, created_by)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'Tenant A', 'tenant-a', 'test'),
  ('00000000-0000-0000-0000-000000000002', 'Tenant B', 'tenant-b', 'test');

INSERT INTO content_tasks (task_id, workspace_id, user_id, title)
VALUES
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'user-a', 'Task A'),
  ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002', 'user-b', 'Task B');

-- 1. All seven consumer tables exist.
DO $$
DECLARE
  missing TEXT;
BEGIN
  SELECT string_agg(t, ', ') INTO missing FROM unnest(ARRAY[
    'creator_profiles', 'consumer_projects', 'consumer_drafts',
    'material_excerpts', 'project_material_links', 'editor_suggestions', 'usage_ledger'
  ]) AS t
  WHERE to_regclass(format('public.%I', t)) IS NULL;
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'consumer migration is missing tables: %', missing;
  END IF;
END $$;

-- 2. Every consumer business table carries workspace_id.
DO $$
DECLARE
  missing TEXT;
BEGIN
  SELECT string_agg(t, ', ') INTO missing FROM unnest(ARRAY[
    'creator_profiles', 'consumer_projects', 'consumer_drafts',
    'material_excerpts', 'project_material_links', 'editor_suggestions', 'usage_ledger'
  ]) AS t
  WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = t AND column_name = 'workspace_id'
  );
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'consumer tables without workspace_id: %', missing;
  END IF;
END $$;

-- 3. creator_profiles is unique per workspace + user.
DO $$
BEGIN
  BEGIN
    INSERT INTO creator_profiles (workspace_id, user_id, display_name)
    VALUES ('00000000-0000-0000-0000-000000000001', 'user-a', 'A')
    ON CONFLICT DO NOTHING;
    INSERT INTO creator_profiles (workspace_id, user_id, display_name)
    VALUES ('00000000-0000-0000-0000-000000000001', 'user-a', 'A duplicate');
    RAISE EXCEPTION 'creator_profiles allowed duplicate workspace user';
  EXCEPTION WHEN unique_violation THEN
    NULL;
  END;
END $$;

-- 4. consumer_projects and consumer_drafts are bound to content_tasks via task_id.
DO $$
BEGIN
  BEGIN
    INSERT INTO consumer_projects (task_id, workspace_id, core_idea)
    VALUES ('99999999-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'x');
    RAISE EXCEPTION 'consumer_projects accepted unknown task_id';
  EXCEPTION WHEN foreign_key_violation THEN
    NULL;
  END;
  BEGIN
    INSERT INTO consumer_drafts (task_id, workspace_id, revision, document)
    VALUES ('99999999-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 0, '{}'::jsonb);
    RAISE EXCEPTION 'consumer_drafts accepted unknown task_id';
  EXCEPTION WHEN foreign_key_violation THEN
    NULL;
  END;
END $$;

-- 5. material_excerpts requires provenance and references documents/chunks.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'material_excerpts' AND column_name = 'provenance_hash' AND is_nullable = 'NO'
  ) THEN
    NULL;
  ELSE
    RAISE EXCEPTION 'material_excerpts.provenance_hash must be NOT NULL';
  END IF;
  BEGIN
    INSERT INTO material_excerpts (excerpt_id, workspace_id, document_id, chunk_id, excerpt_type, summary, excerpt_text, provenance_hash, status, created_by_type)
    VALUES ('50000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
            '99999999-0000-0000-0000-000000000001', '99999999-0000-0000-0000-000000000002',
            'quote', 's', 't', 'hash', 'ready', 'model');
    RAISE EXCEPTION 'material_excerpts accepted unknown document';
  EXCEPTION WHEN foreign_key_violation THEN
    NULL;
  END;
END $$;

-- 6. project_material_links is unique per task + excerpt.
INSERT INTO source_documents (
  document_id, workspace_id, document_name, document_type, version,
  authority_level, checksum, created_by
) VALUES (
  '30000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
  'Material A', 'external_reference', 'v1', 'reference', 'checksum-material-a', 'user-a'
);
INSERT INTO source_chunks (chunk_id, workspace_id, document_id, chunk_index, content)
VALUES ('40000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
        '30000000-0000-0000-0000-000000000001', 0, 'chunk text');
INSERT INTO material_excerpts (
  excerpt_id, workspace_id, document_id, chunk_id, excerpt_type,
  summary, excerpt_text, provenance_hash, status, created_by_type
) VALUES (
  '50000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001',
  'quote', 'summary', 'text', 'hash-material-a', 'ready', 'model'
);
INSERT INTO project_material_links (workspace_id, task_id, excerpt_id)
VALUES ('00000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001');
DO $$
BEGIN
  BEGIN
    INSERT INTO project_material_links (workspace_id, task_id, excerpt_id)
    VALUES ('00000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001');
    RAISE EXCEPTION 'project_material_links allowed duplicate task+excerpt';
  EXCEPTION WHEN unique_violation THEN
    NULL;
  END;
END $$;

-- 7. editor_suggestions carries selected_text_hash and lifecycle states.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'editor_suggestions' AND column_name = 'selected_text_hash' AND is_nullable = 'NO'
  ) THEN
    RAISE EXCEPTION 'editor_suggestions.selected_text_hash is required';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'editor_suggestions'::regclass
      AND pg_get_constraintdef(oid) LIKE '%status%'
      AND pg_get_constraintdef(oid) LIKE '%stale%'
  ) THEN
    RAISE EXCEPTION 'editor_suggestions.status must constrain the suggestion lifecycle';
  END IF;
END $$;

-- 8. usage_ledger is idempotent per workspace + request.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_index i
    JOIN pg_class c ON c.oid = i.indrelid
    WHERE c.relname = 'usage_ledger' AND i.indisunique
      AND (SELECT string_agg(a.attname, ',' ORDER BY a.attnum)
           FROM unnest(i.indkey::smallint[]) k
           JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k
           WHERE a.attname IN ('workspace_id','request_id'))
      = (SELECT string_agg(col, ',' ORDER BY ord) FROM (VALUES ('workspace_id',1),('request_id',2)) v(col, ord))
  ) THEN
    RAISE EXCEPTION 'usage_ledger requires a unique constraint on (workspace_id, request_id)';
  END IF;
END $$;

-- 9. Style reports are isolated consumer data and projects may bind one.
-- 006/007 must remain compatible with the existing consumer task shape.
INSERT INTO style_reports (
  report_id, workspace_id, form, language, layers, corpus_digest
) VALUES (
  '60000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  'article', 'zh', '{"tone":"clear"}'::jsonb, 'style-digest-a'
);

INSERT INTO consumer_projects (task_id, workspace_id, core_idea)
VALUES (
  '10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  'Style binding fixture'
);

UPDATE consumer_projects
SET preferred_style_report_id = '60000000-0000-0000-0000-000000000001'
WHERE task_id = '10000000-0000-0000-0000-000000000001';

DO $$
DECLARE bound_report UUID;
BEGIN
  SELECT preferred_style_report_id INTO bound_report
  FROM consumer_projects
  WHERE task_id = '10000000-0000-0000-0000-000000000001';
  IF bound_report <> '60000000-0000-0000-0000-000000000001'::uuid THEN
    RAISE EXCEPTION 'consumer_projects did not persist preferred_style_report_id';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'style_reports'
      AND column_name IN ('corpus_stats', 'corpus_articles')
  ) THEN
    RAISE EXCEPTION '007 style report provenance columns are missing';
  END IF;

  BEGIN
    UPDATE consumer_projects
    SET preferred_style_report_id = '60000000-0000-0000-0000-000000000099'
    WHERE task_id = '10000000-0000-0000-0000-000000000001';
    RAISE EXCEPTION 'consumer_projects accepted a missing style report';
  EXCEPTION WHEN foreign_key_violation THEN
    NULL;
  END;
END $$;

-- 10. 008 extends the existing document-type contract without accepting
-- arbitrary values or invalidating legacy B-end material kinds.
DO $$
DECLARE kind TEXT;
DECLARE index_value INTEGER := 2;
BEGIN
  FOREACH kind IN ARRAY ARRAY['text', 'file', 'link'] LOOP
    INSERT INTO source_documents (
      document_id, workspace_id, document_name, document_type, version,
      authority_level, checksum, created_by
    ) VALUES (
      ('30000000-0000-0000-0000-00000000000' || index_value)::uuid,
      '00000000-0000-0000-0000-000000000001',
      'Consumer ' || kind, kind, 'v1', 'reference',
      'checksum-consumer-' || kind, 'user-a'
    );
    index_value := index_value + 1;
  END LOOP;

  BEGIN
    INSERT INTO source_documents (
      document_id, workspace_id, document_name, document_type, version,
      authority_level, checksum, created_by
    ) VALUES (
      '30000000-0000-0000-0000-000000000009',
      '00000000-0000-0000-0000-000000000001',
      'Invalid kind', 'untrusted_kind', 'v1', 'reference',
      'checksum-invalid-kind', 'user-a'
    );
    RAISE EXCEPTION '008 accepted an unsupported document_type';
  EXCEPTION WHEN check_violation THEN
    NULL;
  END;
END $$;

ROLLBACK;
