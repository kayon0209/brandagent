# Consumer Desktop Redesign Design

## Goal

Make the authenticated consumer project list and manuscript workspace read as one calm, editorial product at desktop width, using the supplied references as visual direction while preserving every existing real-data and safety boundary.

## Workflow-first revision (2026-09-09)

The writing surface is not a collection of independent controls. Its primary
path is `核心观点 → 素材上下文 → 正文草稿 → 平台优化 → 发布`. The UI must
make that path legible without explanatory paragraphs. A manual “保存观点”
button is system-centric and is replaced by debounced, failure-honest
autosave; while the manuscript is empty, `生成初稿` is the one primary action
next to the core idea and material linking is secondary. The manuscript must
remain a visibly editable draft surface even when it holds no real text;
never seed reference copy, made-up article text, imagery, completion state,
or metrics.

## Visual direction

The direction is warm editorial craft: off-white paper, charcoal ink, restrained terracotta for the primary path, compact serif headings, and a quiet desk-like canvas around the manuscript. It is an original implementation, not a copy of the reference images, their iPhone copy, or their photography.

## Scope

- `/app`: shared navigation, editorial page heading, honest summary metrics, action cards, filters, and a denser horizontal project row.
- `/app/write/[projectId]`: compact writing chrome, paper canvas, visible save state, writing aids, and a composed right-hand platform preview rail.
- Platform preview: diagnose and fix the case where a project has visible draft text but the selected live preview remains empty; make loading, empty, and request-error states distinct and actionable.

## Data integrity

The project-list endpoint currently supplies only `task_id`, `title`, `core_idea`, and `writing_intent`. The redesign must not invent published counts, weekly progress, modification time, word counts, or workflow stages. It may display project count, learned-style availability, remaining quota, and fields actually returned by the endpoint. Any richer metric needs a separately approved API contract change.

## Interaction and accessibility

- Keep existing create-project controls and their labels; `新建项目`, `项目名称`, `核心观点`, and `创建并开始写作` remain discoverable to keyboard and existing E2E journeys.
- Keep the preview mode/channel controls as ARIA tabs. The selected platform must show exactly one of: live draft content, an explicit no-text state, request error with retry, or a generated variant.
- At widths below the desktop breakpoint, retain the existing readable single-column fallback. The desktop reference layout is the visual target at 1440px.
- The right preview rail is subordinate to the manuscript: 300–320px at desktop, named `当前内容｜平台优化` rather than implementation-oriented terminology.

## Verification

- Unit tests cover project-dashboard real-data rendering, the creation entry, selected preview tabs, live-text rendering, empty state, and failed preview retry.
- Mock Playwright covers 1440px project and write layouts plus a populated preview.
- The authenticated real-stack journey remains the only proof of Clerk/BFF/Agent interoperability. It must not be reported as passed unless its storage-state prerequisite is available and the run finishes.

## Non-goals

- No database migration, API-contract expansion, environment change, third-party asset download, or automatic publishing.
- No copying the reference images as production assets.
