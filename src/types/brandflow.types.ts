export type ISODateTime = string
export type UUID = string
export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }

export type Channel = 'wechat_website' | 'xiaohongshu' | 'video_script_60s' | 'marketing_email'
export type TaskStatus =
  | 'draft'
  | 'validating_brief'
  | 'waiting_for_clarification'
  | 'researching'
  | 'waiting_for_outline_approval'
  | 'generating_master'
  | 'reviewing_master'
  | 'waiting_for_master_approval'
  | 'generating_channels'
  | 'reviewing_channels'
  | 'waiting_for_final_approval'
  | 'exporting'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type AuthorityLevel = 'primary' | 'approved' | 'reference' | 'unverified'
export type DocumentType =
  | 'product_fact'
  | 'brand_guideline'
  | 'channel_guideline'
  | 'approved_content'
  | 'campaign_information'
  | 'forbidden_claim_rule'
  | 'external_reference'

export type ContentType =
  | 'master_outline'
  | 'master_draft'
  | 'master_revised'
  | 'master_approved'
  | 'channel_draft'
  | 'channel_revised'
  | 'channel_approved'

export type ReviewType =
  | 'factual'
  | 'citation'
  | 'brief_coverage'
  | 'brand'
  | 'channel_format'
  | 'compliance'
  | 'cross_channel_consistency'

export type IssueSeverity = 'info' | 'warning' | 'critical'
export type ApprovalStatus = 'not_required' | 'pending' | 'approved' | 'rejected' | 'invalidated'
export type Decision = 'approve' | 'reject' | 'request_revision' | 'cancel' | 'authorize'
export type DecisionType =
  | 'outline'
  | 'master_brand'
  | 'master_final'
  | 'channel'
  | 'final_package'
  | 'export'
  | 'preview'
  | 'replace_approved_content'

export type TransformationType =
  | 'condense'
  | 'rewrite'
  | 'reorder'
  | 'style_adaptation'
  | 'cta_adaptation'
  | 'format_conversion'

export interface ContentTask {
  task_id: UUID
  workspace_id: UUID
  user_id: string
  title: string
  status: TaskStatus
  selected_channels: Channel[]
  current_node: string | null
  cancellation_requested: boolean
  state_version: string
  created_at: ISODateTime
  updated_at: ISODateTime
  completed_at: ISODateTime | null
  error: TaskError | null
}

export interface ContentBrief {
  brief_id: UUID
  workspace_id: UUID
  task_id: UUID
  topic: string
  brand_id: UUID | null
  product_id: UUID | null
  target_audience: string
  publishing_objective: string
  primary_channel: Channel | null
  selected_derivative_channels: Channel[]
  desired_audience_action: string
  deadline: ISODateTime | null
  target_length: number | null
  required_messages: string[]
  required_facts: string[]
  required_source_ids: UUID[]
  forbidden_claims: string[]
  tone: string[]
  brand_keywords: string[]
  reference_content_ids: UUID[]
  clarification_history: Array<{ question: string; answer: string; answered_at: ISODateTime }>
  schema_version: string
  created_at: ISODateTime
  updated_at: ISODateTime
}

export interface SourceDocument {
  document_id: UUID
  workspace_id: UUID
  document_name: string
  document_type: DocumentType
  version: string
  effective_at: ISODateTime | null
  expires_at: ISODateTime | null
  authority_level: AuthorityLevel
  public_usage_allowed: boolean
  status: 'draft' | 'active' | 'expired' | 'superseded' | 'archived'
  checksum: string
  created_at: ISODateTime
}

export interface VerifiedFact {
  fact_id: UUID
  workspace_id: UUID
  product_id: UUID
  fact_content: string
  source_document_id: UUID
  source_chunk_id: UUID | null
  structured_field: string | null
  version: string
  effective_at: ISODateTime | null
  expires_at: ISODateTime | null
  authority_level: AuthorityLevel
  public_usage_allowed: boolean
  approval_required: boolean
}

export interface ContentBlock {
  block_id: UUID
  workspace_id: UUID
  task_id: UUID
  block_type: string
  position: number
  content: string
  metadata: Record<string, JsonValue>
}

export interface ContentVersion {
  content_version_id: UUID
  workspace_id: UUID
  task_id: UUID
  content_type: ContentType
  channel: Channel | null
  version_number: number
  parent_version_id: UUID | null
  master_content_version_id: UUID | null
  content: string
  structured_blocks: ContentBlock[]
  review_status: 'not_started' | 'in_review' | 'passed' | 'failed'
  approval_status: ApprovalStatus
  immutable_hash: string
  created_by_type: 'human' | 'model' | 'workflow'
  created_by_id: string
  model_call_id: UUID | null
  prompt_version: string | null
  created_at: ISODateTime
  change_summary: string
}

export interface ReviewIssue {
  issue_id: UUID
  issue_type: string
  severity: IssueSeverity
  problematic_text: string | null
  reason: string
  supporting_fact_ids: UUID[]
  missing_evidence: string | null
  suggested_action: string
  target_block_id: UUID | null
  status: 'open' | 'resolved' | 'accepted_risk'
}

export interface ReviewResult {
  review_id: UUID
  workspace_id: UUID
  task_id: UUID
  content_version_id: UUID
  review_type: ReviewType
  passed: boolean
  issues: ReviewIssue[]
  max_severity: IssueSeverity | null
  revision_instructions: string[]
  reviewer_type: 'deterministic' | 'model' | 'human'
  reviewer_version: string
  created_at: ISODateTime
}

export interface HumanDecision {
  decision_id: UUID
  workspace_id: UUID
  task_id: UUID
  content_version_id: UUID | null
  decision_type: DecisionType
  decision: Decision
  comment: string
  user_id: string
  user_role: 'content_operator' | 'brand_reviewer' | 'final_approver' | 'admin'
  target_snapshot_hash: string
  idempotency_key: string
  created_at: ISODateTime
}

export interface ToolCallLog {
  tool_call_id: UUID
  workspace_id: UUID
  task_id: UUID
  workflow_node: string
  mcp_server: string
  tool_name: string
  capability: 'read' | 'write' | 'high_risk'
  sanitized_input: Record<string, JsonValue>
  output_status: 'succeeded' | 'failed' | 'timed_out' | 'degraded' | 'rejected'
  latency_ms: number
  error_code: string | null
  error_summary: string | null
  approval_requirement: DecisionType | null
  approval_requirement_id: UUID | null
  approval_decision_id: UUID | null
  target_snapshot_hash: string | null
  approval_result: 'not_required' | 'verified' | 'missing' | 'invalid'
  idempotency_key: string | null
  created_at: ISODateTime
}

export interface ModelCallLog {
  model_call_id: UUID
  workspace_id: UUID
  task_id: UUID
  provider: string
  model: string
  prompt_version: string
  latency_ms: number
  input_tokens: number | null
  output_tokens: number | null
  usage_source: 'provider' | 'estimated' | 'unavailable'
  estimated_cost: number | null
  currency: string | null
  retry_count: number
  status: 'succeeded' | 'failed' | 'timed_out'
  error_code: string | null
  created_at: ISODateTime
}

export interface LineageEdge {
  lineage_id: UUID
  source_document_id: UUID | null
  source_chunk_id: UUID | null
  fact_id: UUID | null
  master_content_version_id: UUID
  master_block_id: UUID
  channel_variant_id: UUID | null
  channel_block_id: UUID | null
  transformation_type: TransformationType | null
  status: 'supported' | 'unsupported_new_claim' | 'invalidated'
}

export interface TaskError {
  code: string
  message: string
  failed_node: string | null
  recoverable: boolean
  saved_work_safe: boolean
  requires_human: boolean
}

export interface AgentState {
  state_version: string
  task_id: UUID
  workspace_id: UUID
  user_id: string
  brief: ContentBrief | null
  missing_fields: string[]
  clarification_questions: string[]
  clarification_history: Array<{ question: string; answer: string; answered_at: ISODateTime }>
  retrieved_sources: SourceDocument[]
  verified_facts: VerifiedFact[]
  brand_guideline_version: string | null
  channel_spec_versions: Partial<Record<Channel, string>>
  content_strategy: Record<string, JsonValue> | null
  master_outline: ContentVersion | null
  outline_approved: boolean
  master_content: ContentVersion | null
  master_content_version_id: UUID | null
  master_review_results: ReviewResult[]
  master_revision_count: number
  master_approved: boolean
  selected_channels: Channel[]
  channel_variants: Partial<Record<Channel, ContentVersion>>
  channel_review_results: Partial<Record<Channel, ReviewResult[]>>
  channel_revision_counts: Partial<Record<Channel, number>>
  channel_approval_status: Partial<Record<Channel, ApprovalStatus>>
  content_lineage: LineageEdge[]
  tool_calls: ToolCallLog[]
  human_decisions: HumanDecision[]
  status: TaskStatus
  current_node: string | null
  cancellation_requested: boolean
  error: TaskError | null
  created_at: ISODateTime
  updated_at: ISODateTime
}
