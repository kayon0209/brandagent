'use client'

/**
 * Right-side platform preview panel (upgrade plan task 12).
 *
 * Real data states only — never a dark technical renderer:
 * - no_master: ask the user to adopt the current draft first;
 * - generating: keep the previous version visible, non-blocking progress;
 * - failed: keep the previous version, offer retry;
 * - ready: channel tabs + the platform-specific preview.
 */

import { useState } from 'react'

import { WeChatPreview } from './WeChatPreview'
import { XiaohongshuPreview } from './XiaohongshuPreview'
import { VideoScriptPreview } from './VideoScriptPreview'
import styles from './consumer-preview.module.css'

export interface ChannelVariantState {
  content: string
  content_version_id?: string
  master_content_version_id?: string
}

export interface PlatformVariantsDataState {
  status: 'no_master' | 'generating' | 'failed' | 'ready'
  channels: Record<string, ChannelVariantState | undefined>
  failedChannels?: Record<string, { retryable: boolean } | undefined>
}

interface PlatformPreviewProps {
  state: PlatformVariantsDataState
  onGenerate(): void
  onRegenerate(channel?: string): void
  onAdopt(): void
}

const TAB_LABELS: Array<{ key: string; label: string }> = [
  { key: 'wechat_website', label: '公众号' },
  { key: 'xiaohongshu', label: '小红书' },
  { key: 'video_script_60s', label: '口播' },
]

export function PlatformPreview({ state, onGenerate, onRegenerate, onAdopt }: PlatformPreviewProps) {
  const availableTabs = TAB_LABELS.filter(tab => state.channels[tab.key])
  const [active, setActive] = useState(availableTabs[0]?.key ?? 'wechat_website')
  const activeKey = availableTabs.some(tab => tab.key === active) ? active : availableTabs[0]?.key
  const activeData = activeKey ? state.channels[activeKey] : undefined

  return (
    <section
      data-testid="platform-preview-panel"
      className={styles.panel}
      style={{ maxWidth: '612px' }}
    >
      <h2 className={styles.panelTitle}>平台预览</h2>

      {state.status === 'no_master' && (
        <p className={styles.hint}>先采用当前稿（在稿纸里点「采用这版」），再回来生成平台版本。</p>
      )}

      {state.status === 'no_master' && (
        <button type="button" className={styles.retry} onClick={onAdopt}>
          去采用当前稿
        </button>
      )}

      {state.status !== 'no_master' && availableTabs.length === 0 && (
        <>
          <p className={styles.hint}>还没有生成平台版本。点下面的按钮，为公众号、小红书和口播各生成一版。</p>
          <button type="button" className={styles.retry} onClick={onGenerate}>
            生成平台版本
          </button>
        </>
      )}

      {state.status === 'generating' && (
        <p className={styles.progress} role="status">
          正在生成新版本…（旧版本仍可查看）
        </p>
      )}

      {availableTabs.length > 0 && (
        <>
          <div className={styles.channelTabs} role="tablist">
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
              </button>
            ))}
          </div>

          {activeData && activeKey === 'wechat_website' && (
            <WeChatPreview data={{ title: '公众号文章', paragraphs: splitParagraphs(activeData.content) }} />
          )}
          {activeData && activeKey === 'xiaohongshu' && (
            <XiaohongshuPreview data={{ title: '小红书笔记', body: activeData.content, tags: extractTags(activeData.content) }} />
          )}
          {activeData && activeKey === 'video_script_60s' && (
            <VideoScriptPreview data={{ duration_seconds: 60, lines: activeData.content.split('\n').filter(Boolean) }} />
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
    </section>
  )
}

function splitParagraphs(content: string): string[] {
  return content.split('\n').filter(Boolean)
}

function extractTags(content: string): string[] {
  const matches = content.match(/#[^\s#]+/g)
  return (matches ?? []).map(tag => tag.slice(1))
}

function channelLabel(key: string): string {
  return TAB_LABELS.find(tab => tab.key === key)?.label ?? key
}
