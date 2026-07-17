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

INSERT INTO workspace_members (workspace_id, user_id, role, status)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'user-a', 'content_operator', 'active'),
  ('00000000-0000-0000-0000-000000000001', 'reviewer-a', 'brand_reviewer', 'active'),
  ('00000000-0000-0000-0000-000000000001', 'final-a', 'final_approver', 'active'),
  ('00000000-0000-0000-0000-000000000001', 'suspended-reviewer', 'brand_reviewer', 'suspended');

DO $$
BEGIN
  BEGIN
    INSERT INTO content_briefs (workspace_id, task_id)
    VALUES ('00000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002');
    RAISE EXCEPTION 'cross-tenant task reference was accepted';
  EXCEPTION WHEN foreign_key_violation THEN
    NULL;
  END;
END $$;

INSERT INTO content_versions (
  content_version_id, workspace_id, task_id, content_type, channel,
  version_number, content, immutable_hash, created_by_type, created_by_id
) VALUES (
  '20000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'master_outline', NULL, 1, 'Outline', 'hash-1', 'human', 'user-a'
);

INSERT INTO content_tasks (task_id, workspace_id, user_id, title)
VALUES ('10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'user-other', 'Task A2');
INSERT INTO content_versions (
  content_version_id, workspace_id, task_id, content_type, channel,
  version_number, content, immutable_hash, created_by_type, created_by_id
) VALUES (
  '20000000-0000-0000-0000-000000000003',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000003',
  'master_outline', NULL, 1, 'Other task outline', 'hash-other', 'model', 'model-call'
);

DO $$
BEGIN
  BEGIN
    INSERT INTO review_results (
      workspace_id, task_id, content_version_id, review_type, passed,
      reviewer_type, reviewer_version
    ) VALUES (
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000001',
      '20000000-0000-0000-0000-000000000003',
      'factual', TRUE, 'deterministic', 'test-v1'
    );
    RAISE EXCEPTION 'same-workspace cross-task review was accepted';
  EXCEPTION WHEN foreign_key_violation THEN
    NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    INSERT INTO content_versions (
      content_version_id, workspace_id, task_id, content_type, channel,
      version_number, content, immutable_hash, created_by_type, created_by_id
    ) VALUES (
      '20000000-0000-0000-0000-000000000002',
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000001',
      'master_outline', NULL, 1, 'Duplicate', 'hash-2', 'human', 'user-a'
    );
    RAISE EXCEPTION 'duplicate master version number was accepted';
  EXCEPTION WHEN unique_violation THEN
    NULL;
  END;
END $$;

INSERT INTO approval_requirements (
  approval_requirement_id, workspace_id, task_id, content_version_id,
  decision_type, required_role, target_snapshot_hash
) VALUES (
  '30000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  'outline', 'brand_reviewer', 'hash-1'
);

DO $$
BEGIN
  BEGIN
    INSERT INTO human_decisions (
      workspace_id, task_id, content_version_id, approval_requirement_id,
      decision_type, decision, user_id, user_role, target_snapshot_hash,
      idempotency_key, request_id
    ) VALUES (
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000001',
      '20000000-0000-0000-0000-000000000001',
      '30000000-0000-0000-0000-000000000001',
      'outline', 'approve', 'user-a', 'brand_reviewer', 'hash-1', 'spoof-role-key-0001', 'req-spoof'
    );
    RAISE EXCEPTION 'spoofed decision role was accepted';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    INSERT INTO human_decisions (
      workspace_id, task_id, content_version_id, approval_requirement_id,
      decision_type, decision, user_id, user_role, target_snapshot_hash,
      idempotency_key, request_id
    ) VALUES (
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000001',
      '20000000-0000-0000-0000-000000000001',
      '30000000-0000-0000-0000-000000000001',
      'outline', 'approve', 'suspended-reviewer', 'brand_reviewer', 'hash-1', 'suspended-key-0001', 'req-suspended'
    );
    RAISE EXCEPTION 'suspended reviewer decision was accepted';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END $$;

INSERT INTO human_decisions (
  decision_id, workspace_id, task_id, content_version_id, approval_requirement_id,
  decision_type, decision, user_id, user_role, target_snapshot_hash,
  idempotency_key, request_id
) VALUES (
  '40000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001',
  'outline', 'approve', 'reviewer-a', 'brand_reviewer', 'hash-1', 'valid-decision-key-0001', 'req-valid'
);

DO $$
BEGIN
  BEGIN
    INSERT INTO tool_call_logs (
      workspace_id, task_id, workflow_node, mcp_server, tool_name, capability,
      output_status, latency_ms, approval_result, request_id
    ) VALUES (
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000001',
      'export_content_package', 'brand-tools', 'export_content_package', 'high_risk',
      'succeeded', 10, 'verified', 'tool-missing-evidence'
    );
    RAISE EXCEPTION 'verified high-risk tool log without evidence was accepted';
  EXCEPTION WHEN check_violation THEN
    NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    INSERT INTO tool_call_logs (
      workspace_id, task_id, workflow_node, mcp_server, tool_name, capability,
      output_status, latency_ms, approval_requirement, approval_requirement_id,
      approval_decision_id, target_snapshot_hash, approval_result, idempotency_key, request_id
    ) VALUES (
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000001',
      'export_content_package', 'brand-tools', 'export_content_package', 'high_risk',
      'succeeded', 10, 'outline', '30000000-0000-0000-0000-000000000001',
      '40000000-0000-0000-0000-000000000001', 'hash-1', 'verified',
      'wrong-scope-tool-key-0001', 'tool-wrong-scope'
    );
    RAISE EXCEPTION 'outline approval authorized export';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END $$;

INSERT INTO approval_requirements (
  approval_requirement_id, workspace_id, task_id, content_version_id,
  decision_type, required_role, target_snapshot_hash
) VALUES (
  '30000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  'export', 'final_approver', 'hash-1'
);
INSERT INTO human_decisions (
  decision_id, workspace_id, task_id, content_version_id, approval_requirement_id,
  decision_type, decision, user_id, user_role, target_snapshot_hash,
  idempotency_key, request_id
) VALUES (
  '40000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000002',
  'export', 'authorize', 'final-a', 'final_approver', 'hash-1', 'export-decision-key-0001', 'req-export'
);

INSERT INTO tool_call_logs (
  workspace_id, task_id, workflow_node, mcp_server, tool_name, capability,
  output_status, latency_ms, approval_requirement, approval_requirement_id,
  approval_decision_id, target_snapshot_hash, approval_result, idempotency_key, request_id
) VALUES (
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'export_content_package', 'brand-tools', 'export_content_package', 'high_risk',
  'succeeded', 10, 'export', '30000000-0000-0000-0000-000000000002',
  '40000000-0000-0000-0000-000000000002', 'hash-1', 'verified',
  'valid-tool-key-0001', 'tool-valid'
);

UPDATE approval_requirements
SET status = 'invalidated', invalidated_at = NOW(), invalidation_reason = 'source version changed'
WHERE approval_requirement_id = '30000000-0000-0000-0000-000000000002';

DO $$
BEGIN
  BEGIN
    INSERT INTO tool_call_logs (
      workspace_id, task_id, workflow_node, mcp_server, tool_name, capability,
      output_status, latency_ms, approval_requirement, approval_requirement_id,
      approval_decision_id, target_snapshot_hash, approval_result, idempotency_key, request_id
    ) VALUES (
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000001',
      'export_content_package', 'brand-tools', 'export_content_package', 'high_risk',
      'succeeded', 10, 'export', '30000000-0000-0000-0000-000000000002',
      '40000000-0000-0000-0000-000000000002', 'hash-1', 'verified',
      'invalidated-tool-key-0001', 'tool-invalidated'
    );
    RAISE EXCEPTION 'invalidated approval authorized export';
  EXCEPTION WHEN check_violation THEN
    NULL;
  END;
END $$;

INSERT INTO content_tasks (task_id, workspace_id, user_id, title)
VALUES ('10000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'reviewer-a', 'Self approval task');
INSERT INTO content_versions (
  content_version_id, workspace_id, task_id, content_type, channel,
  version_number, content, immutable_hash, created_by_type, created_by_id
) VALUES (
  '20000000-0000-0000-0000-000000000004',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000004',
  'master_outline', NULL, 1, 'Self approval outline', 'hash-self', 'model', 'model-call'
);
INSERT INTO approval_requirements (
  approval_requirement_id, workspace_id, task_id, content_version_id,
  decision_type, required_role, target_snapshot_hash
) VALUES (
  '30000000-0000-0000-0000-000000000004',
  '00000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000004',
  '20000000-0000-0000-0000-000000000004',
  'outline', 'brand_reviewer', 'hash-self'
);
DO $$
BEGIN
  BEGIN
    INSERT INTO human_decisions (
      workspace_id, task_id, content_version_id, approval_requirement_id,
      decision_type, decision, user_id, user_role, target_snapshot_hash,
      idempotency_key, request_id
    ) VALUES (
      '00000000-0000-0000-0000-000000000001',
      '10000000-0000-0000-0000-000000000004',
      '20000000-0000-0000-0000-000000000004',
      '30000000-0000-0000-0000-000000000004',
      'outline', 'approve', 'reviewer-a', 'brand_reviewer', 'hash-self', 'self-key-0001', 'req-self'
    );
    RAISE EXCEPTION 'self-approval was accepted';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    UPDATE content_versions
    SET content = 'Mutated'
    WHERE content_version_id = '20000000-0000-0000-0000-000000000001';
    RAISE EXCEPTION 'append-only content version was mutated';
  EXCEPTION WHEN SQLSTATE '55000' THEN
    NULL;
  END;
END $$;

DO $$
DECLARE missing_rls INTEGER;
BEGIN
  SELECT COUNT(*) INTO missing_rls
  FROM pg_class
  WHERE relnamespace = 'public'::regnamespace
    AND relkind = 'r'
    AND relname IN (
      'workspaces','workspace_members','content_tasks','content_briefs','source_documents',
      'source_chunks','verified_facts','content_versions','human_decisions','task_events',
      'tool_call_logs','idempotency_records','evaluation_tasks','evaluation_runs','bad_cases'
    )
    AND NOT relrowsecurity;
  IF missing_rls <> 0 THEN
    RAISE EXCEPTION '% tenant tables do not have RLS enabled', missing_rls;
  END IF;
END $$;

CREATE ROLE brandflow_m1_client NOLOGIN;
GRANT USAGE ON SCHEMA public TO brandflow_m1_client;
GRANT SELECT ON workspaces TO brandflow_m1_client;
SET LOCAL ROLE brandflow_m1_client;
DO $$
DECLARE visible_rows INTEGER;
BEGIN
  SELECT COUNT(*) INTO visible_rows FROM workspaces;
  IF visible_rows <> 0 THEN
    RAISE EXCEPTION 'deny-by-default RLS exposed % workspace rows', visible_rows;
  END IF;
END $$;
RESET ROLE;

ROLLBACK;
