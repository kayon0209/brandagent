'use client'

/**
 * Right-side platform panel (plan task 12 + Phase 5 fixes + round-3b WYSIWYG
 * + round-3e concept split).
 *
 * round-3e (评审 #1/#2 — 概念清楚): the rail previously mixed two DIFFERENT
 * things in one render — the live "how my draft looks on this platform" view
 * and the AI-polished variant — so a user couldn't tell what they were
 * looking at, and the bottom action bar conflated 定稿/重新生成/准备发布.
 *
 * Now the rail is two explicit modes behind a segmented control:
 *   [当前内容]  — the DRAFT rendered in the platform's layout, live.
 *   [平台优化]  — the AI-rewritten variant for that platform.
 *
 * And the product model is spoken (not hidden machinery):
 *   稿纸 (draft) → 设为母稿 (freeze a master) → 平台优化 (variants)
 *   → 准备发布 (topbar only, single publish entry).
 */

import { useEffect, useRef, useState } from 'react'

import { WeChatPreview } from './WeChatPreview'
import { XiaohongshuPreview } from './XiaohongshuPreview'
import { VideoScriptPreview } from './VideoScriptPreview'
import { GenericChannelPreview } from './GenericChannelPreview'
import styles from './consumer-preview.module.css'

export interface ChannelVariantState {
  content: string
  content_version_id?: string
  master_content_version_id?: string
}

export interface PlatformVariantsDataState {
  status: 'no_master' | 'generating' | 'failed' | 'ready' | 'error'
  channels: Record<string, ChannelVariantState | undefined>
  failedChannels?: Record<string, { retryable: boolean } | undefined>
  error?: { code: string; message: string }
}

interface PlatformPreviewProps {
  state: PlatformVariantsDataState
  /** P2-3: workspace-usable channels from the preview API */
  supportedChannels?: string[]
  /** Live draft text from the editor (round-3b WYSIWYG) */
  liveText?: string
  onGenerate(): void
  onRegenerate(channel?: string): void
  /** Freeze the current draft as the master the variants are derived from */
  onAdopt(): void
  /** Re-fetch the preview payload after a non-generation request failure. */
  onRetry?(): void
}

const BUILTIN_TABS: Array<{ key: string; label: string }> = [
  { key: 'wechat_website', label: '公众号' },
  { key: 'xiaohongshu', label: '小红书' },
  { key: 'video_script_60s', label: '口播' },
]

type Mode = 'draft' | 'polished'

export function PlatformPreview({ state, supportedChannels, liveText, onGenerate, onRegenerate, onAdopt, onRetry }: PlatformPreviewProps) {
  const supported = supportedChannels ?? BUILTIN_TABS.map(tab => tab.key)
  const hasVariant = (key: string) => Boolean(state.channels[key]?.content?.trim())
  const tabKeys = Array.from(new Set([...supported, ...Object.keys(state.channels)])).filter(
    key => key !== '__proto__',
  )
  const availableTabs = tabKeys
    .sort((a, b) => Number(hasVariant(b)) - Number(hasVariant(a)))
    .map(key => ({ key, label: channelLabel(key) }))
  const [active, setActive] = useState(availableTabs[0]?.key ?? 'wechat_website')
  const activeKey = availableTabs.some(tab => tab.key === active) ? active : availableTabs[0]?.key
  const anyVariant = tabKeys.some(hasVariant)

  // round-3e: explicit two-mode split. Default shows the polished variant
  // once one exists (that's why the user generated it); otherwise the live
  // draft preview. round-3f (P0-3): a user who switches to 平台优化 with
  // NO variant STAYS there — the empty state guides them to 定稿/生成, so we
  // must NOT yank them back to draft mode (that made 定稿 unreachable).
  const [mode, setMode] = useState<Mode>(anyVariant ? 'polished' : 'draft')
  const [collapsed, setCollapsed] = useState(false)
  const modeTouchedRef = useRef(false)
  useEffect(() => {
    // round-3g: variants arrive AFTER mount (async load). The initial
    // useState computed mode from an EMPTY channels map, so the rail stayed
    // stuck in draft mode even with variants loaded (observed live). Grow
    // to polished ONCE when variants first arrive — never override an
    // explicit user choice after that.
    if (!modeTouchedRef.current && anyVariant && mode === 'draft') {
      setMode('polished')
      modeTouchedRef.current = true
    }
  }, [anyVariant, mode])

  useEffect(() => {
    if (activeKey !== active) setActive(activeKey ?? 'wechat_website')
  }, [active, activeKey])

  const activeData = activeKey ? state.channels[activeKey] : undefined

  const hasMaster = state.status !== 'no_master'
  const masterReady = hasMaster && anyVariant
  const channelName = channelLabel(activeKey ?? 'wechat_website')

  return (
    <section
      data-testid="platform-preview-panel"
      className={styles.panel}
      style={{ maxWidth: '612px' }}
    >
      <div className={styles.panelHead}>
        <div className={styles.panelTitleRow}>
          <h2 className={styles.panelTitle}>平台预览</h2>
          <button type="button" className={styles.collapseButton} aria-label={collapsed ? '展开预览' : '折叠预览'} onClick={() => setCollapsed(v => !v)}>
            {collapsed ? '⌃' : '⌄'}
          </button>
        </div>
        <div className={styles.modeSwitch} role="tablist" aria-label="预览模式">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'draft'}
            data-active={mode === 'draft'}
            className={mode === 'draft' ? styles.modeActive : styles.modeTab}
            onClick={() => setMode('draft')}
          >
            当前内容
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'polished'}
            data-active={mode === 'polished'}
            className={mode === 'polished' ? styles.modeActive : styles.modeTab}
            onClick={() => setMode('polished')}
          >
            平台优化
            {anyVariant && <span className={styles.modeDot} aria-hidden />}
          </button>
        </div>
      </div>

      {collapsed ? (
        <p className={styles.collapsedHint} data-testid="preview-collapsed">预览已折叠，点击展开查看。</p>
      ) : (
        <>
          {state.status === 'error' && (
            <div className={styles.errorState} data-testid="variant-error">
              <p className={styles.hint}>
                预览暂时打不开：{state.error?.message?.replace(/。+$/, '') ?? '网络出了点问题'}。你的稿纸不受影响。
              </p>
              {onRetry && (
                <button type="button" className={styles.retryPreview} onClick={onRetry}>
                  重试预览
                </button>
              )}
            </div>
          )}

          {availableTabs.length > 0 && (
            <div className={styles.channelTabs} role="tablist" aria-label="平台">
              {availableTabs.map(tab => (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={tab.key === activeKey}
                  className={tab.key === activeKey ? styles.channelTabActive : styles.channelTab}
                  onClick={() => setActive(tab.key)}
                >
                  {tab.label}
                  {hasVariant(tab.key) && <span className={styles.tabReadyDot} aria-hidden title="已生成" />}
                </button>
              ))}
            </div>
          )}

          {state.status === 'generating' && (
            <p className={styles.progress} role="status" data-testid="generating-note">
              正在生成新版本…（上一版仍可查看）
            </p>
          )}

          {mode === 'draft' && (
            <>
              <PlatformShape activeKey={activeKey} content={liveText ?? ''} />
              {liveText && liveText.trim() ? (
                <p className={styles.previewCaption} data-testid="draft-preview-caption">
                  这是「{channelName}」的排版——内容实时取自你稿纸里的文字。
                </p>
              ) : (
                <p className={styles.previewCaption} data-testid="draft-preview-empty">
                  在稿纸里写下内容后，这里会实时显示「{channelName}」的排版效果。
                </p>
              )}
            </>
          )}

          {mode === 'polished' && (
            <>
              {activeData?.content ? (
                <>
                  <PlatformShape activeKey={activeKey} content={activeData.content} />
                  <p className={styles.previewCaption} data-testid="polished-caption">
                    AI 已按「{channelName}」的规格改写：标题、段落节奏、标签都适配过，可直接采用发布。
                  </p>
                </>
              ) : state.status === 'generating' ? null : hasMaster ? (
                <div className={styles.polishedEmpty} data-testid="polished-empty">
                  <p>还没有「{channelName}」的精修版。生成后，这里展示按平台特点改写的结果。</p>
                  <button type="button" className={styles.primarySmall} onClick={onGenerate}>
                    生成平台版本
                  </button>
                </div>
              ) : (
                <div className={styles.polishedEmpty} data-testid="polished-no-master">
                  <p>先「定稿」，把当前稿纸存为平台优化的基础，再生成「{channelName}」版本。</p>
                  <button type="button" className={styles.primarySmall} onClick={onAdopt}>
                    定稿
                  </button>
                </div>
              )}
            </>
          )}

          {state.status === 'failed' &&
            Object.entries(state.failedChannels ?? {}).map(([channel, failure]) =>
              failure?.retryable ? (
                <button
                  key={channel}
                  type="button"
                  className={styles.retry}
                  onClick={() => onRegenerate(channel)}
                >
                  重试{channelLabel(channel)}
                </button>
              ) : null,
            )}

          {mode === 'draft' && hasMaster && (
            <p className={styles.hint} data-testid="stale-hint">
              稿纸改动不会自动更新已生成的平台优化版——需要时切到「平台优化」重新生成。
            </p>
          )}

          {!state.error && (
            <div className={styles.modeActions} data-testid="mode-actions">
              {mode === 'draft' && (
                <button type="button" className={styles.secondary} onClick={() => setMode('polished')}>
                  生成平台优化版 →
                </button>
              )}
              {mode === 'polished' && activeData?.content && (
                <button type="button" className={styles.secondary} onClick={() => onRegenerate(activeKey)}>
                  重新生成
                </button>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}

/** Render the correct platform shape for the active channel. Empty content
 * renders the platform's structural skeleton (版式示意), never a fake load. */
function PlatformShape({ activeKey, content }: { activeKey: string | undefined; content: string }) {
  if (activeKey === 'wechat_website') {
    return <WeChatPreview data={{ content }} />
  }
  if (activeKey === 'xiaohongshu') {
    return <XiaohongshuPreview data={{ content }} />
  }
  if (activeKey === 'video_script_60s') {
    return (
      <VideoScriptPreview
        data={{ duration_seconds: 60, lines: content ? content.split('\n').filter(Boolean) : [] }}
      />
    )
  }
  return (
    <GenericChannelPreview
      channelKey={activeKey ?? 'custom'}
      label={channelLabel(activeKey ?? 'custom')}
      content={content}
    />
  )
}

function channelLabel(key: string): string {
  return BUILTIN_TABS.find(tab => tab.key === key)?.label ?? friendlyChannelName(key)
}

const CHANNEL_DISPLAY_NAMES: Record<string, string> = {
  zhihu: '知乎',
  douyin: '抖音',
  weibo: '微博',
  bilibili: 'B站',
  linkedin: 'LinkedIn',
  newsletter: '邮件订阅',
}

function friendlyChannelName(key: string): string {
  const base = key.split(/[:_]/).pop() ?? key
  return CHANNEL_DISPLAY_NAMES[base] ?? key
}
