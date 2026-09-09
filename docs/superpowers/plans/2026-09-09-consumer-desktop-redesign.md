# Consumer Desktop Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a desktop-reference-grade consumer project dashboard and writing workspace while fixing the platform-preview empty-content defect with real state handling.

**Architecture:** Keep project creation, draft persistence, variants, and Clerk authentication unchanged. Extract presentation-only dashboard pieces from the oversized `/app` page, then make the preview rail render a discriminated UI state derived from the existing variants hook and live draft text. CSS modules own local composition; `consumer-tokens.css` remains the shared visual-token source.

**Tech Stack:** Next.js App Router, React 19, TypeScript, CSS Modules, Jest + Testing Library, Playwright.

**Spec:** `docs/superpowers/plans/2026-09-09-consumer-desktop-redesign-design.md`

## Global Constraints

- Preserve the `/api/*` response envelope and all existing consumer API contracts.
- Use only real endpoint fields; do not display fabricated metrics, content, progress, timestamps, or previews.
- Do not modify `.env*`, CI, schema, migrations, third-party dependencies, or publishing behavior.
- Preserve the current dirty worktree and stage neither unrelated files nor a commit without a separate user request.
- Keep the desktop target at 1440px while retaining a readable mobile fallback.

---

### Task 1: Reproduce and isolate platform-preview state

**Files:**
- Modify: `tests/unit/consumer-preview.test.tsx`
- Modify: `src/components/consumer/preview/PlatformPreview.tsx`
- Modify: `src/hooks/usePlatformVariants.ts`

**Interfaces:**
- Consumes: `VariantsState`, `PlatformPreviewProps.liveText`, and `reload()` from `usePlatformVariants`.
- Produces: an explicit preview state whose live-draft branch renders non-empty `liveText`, whose empty branch speaks that the manuscript has no text, and whose request-error branch exposes `onRetry`.

- [ ] **Step 1: Write failing tests for the real preview states.**

```tsx
it('renders typed manuscript text in the selected live platform preview', () => {
  render(<PlatformPreview state={{ status: 'no_master', channels: {} }} liveText="稿纸里的真实正文" onGenerate={jest.fn()} onRegenerate={jest.fn()} onAdopt={jest.fn()} onRetry={jest.fn()} />)
  expect(screen.getByTestId('wechat-preview')).toHaveTextContent('稿纸里的真实正文')
})

it('offers a retry when preview loading failed', () => {
  const onRetry = jest.fn()
  render(<PlatformPreview state={{ status: 'error', channels: {}, error: { code: 'NETWORK_ERROR', message: '网络错误' } }} onGenerate={jest.fn()} onRegenerate={jest.fn()} onAdopt={jest.fn()} onRetry={onRetry} />)
  fireEvent.click(screen.getByRole('button', { name: '重试预览' }))
  expect(onRetry).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 2: Run the focused Jest file and verify the new assertions fail for the missing retry interface/state.**

Run: `pnpm exec jest tests/unit/consumer-preview.test.tsx --runInBand`

- [ ] **Step 3: Trace the request boundary before modifying production code.**

Inspect the BFF response for `/variants/preview`, the `usePlatformVariants.load()` state transition, and the rendered `PlatformPreview` props. Record whether the observed project has no draft, a failed preview fetch, or live text lost between `ConsumerEditorClient.onStatus` and the preview.

- [ ] **Step 4: Implement the smallest confirmed state fix.**

Add `onRetry?: () => void` to `PlatformPreviewProps`, pass `variants.reload` from the write page, and render `重试预览` only for `state.status === 'error'`. Do not change variant generation or error-envelope semantics. If the trace proves live text is present, ensure `PlatformShape` receives it; if no text exists, retain the explicit empty-copy state.

- [ ] **Step 5: Re-run focused preview tests.**

Run: `pnpm exec jest tests/unit/consumer-preview.test.tsx --runInBand`

Expected: PASS, including the new populated, empty, and failed-preview states.

### Task 2: Build the project dashboard composition

**Files:**
- Create: `src/components/consumer/ProjectDashboard.tsx`
- Create: `src/components/consumer/project-dashboard.module.css`
- Modify: `src/app/(consumer)/workspace/page.tsx`
- Modify: `src/components/consumer/ConsumerNav.tsx`
- Modify: `src/components/consumer/materials/consumer-materials.module.css`
- Test: `tests/unit/consumer-project-dashboard.test.tsx`

**Interfaces:**
- Consumes: the existing `ConsumerProject`, current project count, latest style summary, quota, `onCreateProject`, and existing `/app/*` routes.
- Produces: a semantic desktop dashboard with no data fetches or mutations of its own; the page keeps ownership of creation state and the existing composer.

- [ ] **Step 1: Write failing dashboard tests.**

```tsx
it('renders only supplied project data in the recent-project row', () => {
  render(<ProjectDashboard projects={[{ task_id: 'p1', title: '真实项目', core_idea: '真实观点', writing_intent: '公众号' }]} projectCount={1} styleCount={0} quotaRemaining={30000} onCreateProject={jest.fn()} />)
  expect(screen.getByRole('link', { name: /打开项目：真实项目/ })).toHaveAttribute('href', '/app/write/p1')
  expect(screen.getByText('真实观点')).toBeInTheDocument()
  expect(screen.queryByText(/已发布 1 篇/)).toBeNull()
})
```

- [ ] **Step 2: Run the focused test and verify it fails because the dashboard component does not exist.**

Run: `pnpm exec jest tests/unit/consumer-project-dashboard.test.tsx --runInBand`

- [ ] **Step 3: Implement presentation-only dashboard components and styles.**

Use a 1200px content frame, editorial header, concise honest metric strip, three real quick-start routes, filter/search toolbar, and a horizontal project row. Use CSS-drawn desk texture and paper details instead of external or copied imagery. Keep the page component responsible for `load`, `createProject`, filters, and the composer.

- [ ] **Step 4: Move shared-nav presentation styles out of the materials module only if the dashboard needs them.**

Keep `ConsumerNav`’s public `active` interface unchanged. Any visual changes must preserve its existing link labels and UserButton behavior.

- [ ] **Step 5: Re-run the focused dashboard test.**

Run: `pnpm exec jest tests/unit/consumer-project-dashboard.test.tsx --runInBand`

Expected: PASS with no fabricated metric copy.

### Task 3: Compose the desktop writing workspace

**Files:**
- Modify: `src/app/(consumer)/workspace/write/[projectId]/page.tsx`
- Modify: `src/components/consumer/editor/consumer-editor.module.css`
- Modify: `src/components/consumer/preview/consumer-preview.module.css`
- Modify: `tests/e2e/consumer-editor.spec.ts`

**Interfaces:**
- Consumes: `ConsumerEditorClient.onStatus`, `PlatformPreview`, `SaveStatus`, `MaterialDrawer`, and current generate/export callbacks.
- Produces: a 1440px desktop workspace with a single clear writing column and a fixed-width preview rail while retaining existing test IDs and action labels.

- [ ] **Step 1: Write failing desktop-layout assertions in the mocked Playwright suite.**

```ts
await page.setViewportSize({ width: 1440, height: 810 })
await expect(page.getByTestId('write-layout')).toBeVisible()
await expect(page.getByTestId('platform-preview-panel')).toContainText('公众号第一段。')
await expect(page.getByTestId('manuscript-canvas')).toHaveCSS('max-width', '720px')
```

- [ ] **Step 2: Run the preview-layout test and verify it exposes the empty or incorrectly composed rail before styling changes.**

Run: `pnpm exec playwright test tests/e2e/consumer-editor.spec.ts --grep "platform preview"`

- [ ] **Step 3: Implement the layout without changing business callbacks.**

Keep the top bar’s back link, materials drawer, document title, prepare-publish gate, and account menu. Visually reduce chrome, promote the manuscript to an off-white paper sheet on a warm canvas, and render the rail as a stable right-side preview desk. Preserve the current action labels and `data-testid` values.

- [ ] **Step 4: Implement responsive fallback.**

At the existing narrow breakpoint, stack the preview rail below the manuscript, keep text controls reachable, and avoid horizontal overflow.

- [ ] **Step 5: Re-run the mock Playwright file.**

Run: `pnpm exec playwright test tests/e2e/consumer-editor.spec.ts`

Expected: PASS for draft autosave and all three platform preview structures.

### Task 4: Integrate and verify without overstating real-stack evidence

**Files:**
- Modify: `tests/e2e/consumer-real-journey.spec.ts`
- Modify: `docs/acceptance/consumer-desktop-redesign.md`

**Interfaces:**
- Consumes: existing authenticated storage-state gate and the real consumer APIs.
- Produces: a reproducible acceptance guide and a real-journey assertion that the create route reaches a visible write layout and non-empty live preview after text is typed.

- [ ] **Step 1: Write the real-journey assertion behind the existing storage-state prerequisite.**

```ts
await expect(page.getByTestId('write-layout')).toBeVisible({ timeout: 60_000 })
await expect(page.getByTestId('platform-preview-panel')).toContainText('第一段正文：这是真实旅程写入的句子', { timeout: 30_000 })
```

- [ ] **Step 2: Run the real suite only when `BRANDFLOW_E2E_STORAGE_STATE` is set; otherwise record the exact skipped prerequisite.**

Run: `pnpm exec playwright test tests/e2e/consumer-real-journey.spec.ts`

- [ ] **Step 3: Run the consumer-focused unit suite, mock E2E suite, type check, and lint.**

Run: `pnpm exec jest tests/unit/consumer-preview.test.tsx tests/unit/consumer-project-dashboard.test.tsx --runInBand && pnpm exec playwright test tests/e2e/consumer-editor.spec.ts && pnpm run typecheck && pnpm run lint`

- [ ] **Step 4: Record completed evidence in the acceptance guide.**

Record commands, exit states, test counts, and the real-stack prerequisite status. Do not label a skipped authenticated journey as passing.

### Task 5: Make the writing workflow explicit

**Files:**
- Modify: `src/app/(consumer)/workspace/write/[projectId]/page.tsx`
- Modify: `src/components/consumer/editor/ConsumerEditorClient.tsx`
- Modify: `src/components/consumer/editor/ConsumerEditor.tsx`
- Modify: `src/components/consumer/editor/CoreIdeaBlock.tsx`
- Modify: `src/components/consumer/editor/ManuscriptCanvas.tsx`
- Modify: `src/components/consumer/editor/consumer-editor.module.css`
- Modify: `src/components/consumer/preview/PlatformPreview.tsx`
- Modify: `src/components/consumer/preview/consumer-preview.module.css`
- Test: `tests/unit/consumer-core-idea.test.tsx`, `tests/unit/consumer-editor.test.tsx`, `tests/unit/consumer-preview.test.tsx`

**Interfaces:**
- The write page remains the owner of generation, material drawer, and real lifecycle state.
- `CoreIdeaBlock` owns debounce-only UI state, but reports persistence failures honestly and never creates a draft or triggers generation.
- The manuscript receives only actual server/live draft text. Its empty rendering is an affordance, not sample content.

- [ ] Replace manual core-idea save with debounced autosave plus failure retry, and make `生成初稿` / `添加素材` explicit page-owned actions.
- [ ] Derive and render a workflow stage from real core idea, draft, master, and publishable-variant state.
- [ ] Give the manuscript an editorial draft heading, clear empty placeholder, AI command affordance, and compact nonempty-draft assistance row.
- [ ] Rename preview modes to `当前内容` and `平台优化`; reduce the rail to 312px without changing variant lifecycle callbacks.
- [ ] Prove autosave, editor affordances, mode names, error recovery, typecheck, lint, and live authenticated visual behavior.
