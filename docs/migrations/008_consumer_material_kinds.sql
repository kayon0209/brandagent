-- ============================================================
-- 008 — round-3g D6: consumer material kinds in source_documents
-- The B-end table (002) constrained document_type to B-end kinds;
-- round-3g stores C-end materials (text/file/link) in the same
-- table. Additive fix: drop + re-add the CHECK with the three new
-- kinds allowed. No columns removed, no data touched.
-- ============================================================

ALTER TABLE source_documents DROP CONSTRAINT IF EXISTS source_documents_document_type_check;

ALTER TABLE source_documents
  ADD CONSTRAINT source_documents_document_type_check
  CHECK (document_type IN (
    'product_fact', 'brand_guideline', 'channel_guideline',
    'approved_content', 'campaign_information', 'forbidden_claim_rule',
    'external_reference', 'text', 'file', 'link'
  ));
