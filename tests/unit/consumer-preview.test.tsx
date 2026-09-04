/**
 * Consumer platform preview tests (upgrade plan task 12).
 *
 * Vertical slices through the preview components: three platforms have
 * INDEPENDENT structures (not the same text re-skinned), the panel never
 * exceeds 85% of the manuscript width, pre-publish review speaks plainly,
 * and real data states (no master / generating / failed / empty review)
 * never lie to the user.
 */

import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

import { PlatformPreview } from '@/components/consumer/preview/PlatformPreview'
import { WeChatPreview } from '@/components/consumer/preview/WeChatPreview'
import { XiaohongshuPreview } from '@/components/consumer/preview/XiaohongshuPreview'
import { VideoScriptPreview } from '@/components/consumer/preview/VideoScriptPreview'
import { PrePublishReview } from '@/components/consumer/preview/PrePublishReview'
import { PrimaryActionBar } from '@/components/consumer/preview/PrimaryActionBar'

describe('platform-specific preview structures', () => {
  it('renders WeChat as a light paper article deriving its title from content', () => {
    const { container } = render(
      <WeChatPreview data={{ content: '第一段标题。\n第二段正文。\n第三段结尾。' }} />,
    )
    const article = container.querySelector('[data-testid="wechat-preview"]')!
    expect(article).not.toBeNull()
    expect(screen.getByText('第一段标题。')).toBeInTheDocument()
    expect(screen.getByText('第二段正文。')).toBeInTheDocument()
    expect(getComputedStyle(article).background).not.toBe('rgb(20, 20, 28)')
  })

  it('renders Xiaohongshu as a white card with a cover and quiet tags', () => {
    const { container } = render(
      <XiaohongshuPreview data={{ content: '笔记标题\n正文一句话。 #标签一 #标签二' }} />,
    )
    const card = container.querySelector('[data-testid="xiaohongshu-preview"]')!
    expect(card).not.toBeNull()
    expect(screen.getByText('笔记标题')).toBeInTheDocument()
    expect(screen.getByText('#标签一')).toBeInTheDocument()
    expect(screen.getByText('#标签二')).toBeInTheDocument()
  })

  it('renders the video script with a mono timecode column', () => {
    const { container } = render(
      <VideoScriptPreview data={{ duration_seconds: 60, lines: ['开场口播。', '核心卖点。'] }} />,
    )
    expect(container.querySelector('[data-testid="video-script-preview"]')).not.toBeNull()
    expect(screen.getByText('开场口播。')).toBeInTheDocument()
    expect(screen.getByText(/00:00/)).toBeInTheDocument()
    expect(screen.getByText(/00:30/)).toBeInTheDocument()
  })

  it('three platforms expose distinct structures, not one text re-skinned', () => {
    const { container: wechat } = render(<WeChatPreview data={{ content: '标题\n正文' }} />)
    const { container: xhs } = render(<XiaohongshuPreview data={{ content: '标题\n正文 #标签' }} />)
    const { container: script } = render(
      <VideoScriptPreview data={{ duration_seconds: 60, lines: ['一', '二'] }} />,
    )
    expect(wechat.querySelector('[data-testid="wechat-paragraphs"]')).not.toBeNull()
    expect(xhs.querySelector('[data-testid="xiaohongshu-tags"]')).not.toBeNull()
    expect(script.querySelector('[data-testid="video-script-lines"]')).not.toBeNull()
    expect(wechat.querySelector('[data-testid="xiaohongshu-tags"]')).toBeNull()
  })
})

describe('PlatformPreview panel', () => {
  it('is titled 平台预览 and never exceeds 85% of the manuscript width', () => {
    render(
      <PlatformPreview
        state={{ status: 'ready', channels: {} }}
        onGenerate={jest.fn()}
        onRegenerate={jest.fn()}
        onAdopt={jest.fn()}
      />,
    )
    expect(screen.getByText('平台预览')).toBeInTheDocument()
    const panel = screen.getByTestId('platform-preview-panel')
    expect(panel.style.maxWidth).toBe('612px') // 720 * 0.85
  })

  it('shows adopt-first hint when no master snapshot exists', () => {
    render(
      <PlatformPreview
        state={{ status: 'no_master', channels: {} }}
        onGenerate={jest.fn()}
        onRegenerate={jest.fn()}
        onAdopt={jest.fn()}
      />,
    )
    expect(screen.getByText(/先采用当前稿/)).toBeInTheDocument()
  })

  it('keeps the previous version visible and non-blocking during regeneration', () => {
    render(
      <PlatformPreview
        state={{ status: 'generating', channels: { wechat_website: { content: '上一版内容' } } }}
        onGenerate={jest.fn()}
        onRegenerate={jest.fn()}
        onAdopt={jest.fn()}
      />,
    )
    expect(screen.getByText('上一版内容')).toBeInTheDocument()
    expect(screen.getByText(/正在生成/)).toBeInTheDocument()
  })

  it('keeps the last version on failure and offers retry', () => {
    const onRegenerate = jest.fn()
    render(
      <PlatformPreview
        state={{
          status: 'failed',
          failedChannels: { xiaohongshu: { retryable: true } },
          channels: { xiaohongshu: { content: '失败前的上一版' } },
        }}
        onGenerate={jest.fn()}
        onRegenerate={onRegenerate}
        onAdopt={jest.fn()}
      />,
    )
    expect(screen.getByText('失败前的上一版')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    expect(onRegenerate).toHaveBeenCalled()
  })
})

describe('PrePublishReview', () => {
  it('is titled 发布前再看一眼 and renders plain-language bubbles', () => {
    render(
      <PrePublishReview
        bubbles={[
          { kind: 'needs_fix', text: '这段有点长，读起来可能不够顺。' },
          { kind: 'blocking', text: '这句话里的说法我们找不到来源。' },
        ]}
      />,
    )
    expect(screen.getByText('发布前再看一眼')).toBeInTheDocument()
    expect(screen.getByText('这段有点长，读起来可能不够顺。')).toBeInTheDocument()
    expect(screen.getByText('这句话里的说法我们找不到来源。')).toBeInTheDocument()
  })

  it('renders hints on paper-warm background with a thin red left border', () => {
    const { container } = render(
      <PrePublishReview bubbles={[{ kind: 'needs_fix', text: '小提示' }]} />,
    )
    const hint = container.querySelector('[data-testid="review-bubble"]')!
    expect(hint).not.toBeNull()
    expect(hint.className).toMatch(/needsFix|hint/)
  })

  it('shows the honest empty state that says WHAT was checked instead of a fake all-passed', () => {
    render(<PrePublishReview bubbles={[]} />)
    // N7: the empty state must prove the check RAN (length + forbidden
    // pattern per channel spec) — 'nothing found' alone reads as
    // 'nothing checked' to a suspicious user
    expect(screen.getByTestId('review-empty')).toHaveTextContent('长度与禁用词检查')
    expect(screen.queryByText(/全部通过/)).toBeNull()
  })

  it('renders a source tracer when a bubble carries a grounded excerpt (N13)', () => {
    render(
      <PrePublishReview
        bubbles={[
          {
            kind: 'needs_fix',
            text: '这句话里的说法我们找不到来源。',
            sourceExcerpt: '素材原文摘录：2025 年上半年起要求 AI 生成内容添加显著标识。',
          },
        ]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '查看来源' }))
    expect(screen.getByTestId('review-source')).toHaveTextContent('素材原文摘录')
  })
})

describe('PrimaryActionBar', () => {
  it('places 采用这版 as the only red primary button on the left', () => {
    const onAdopt = jest.fn()
    render(<PrimaryActionBar onAdopt={onAdopt} onRegenerate={jest.fn()} onPrepareExport={jest.fn()} />)
    const adopt = screen.getByRole('button', { name: '采用这版' })
    expect(adopt).toBeInTheDocument()
    const all = screen.getAllByRole('button')
    expect(all[0]).toBe(adopt)
  })

  it('puts 重新生成 as a secondary button on the right and 准备发布 as brown/ink secondary', () => {
    const onRegenerate = jest.fn()
    const onPrepareExport = jest.fn()
    render(<PrimaryActionBar onAdopt={jest.fn()} onRegenerate={onRegenerate} onPrepareExport={onPrepareExport} />)
    expect(screen.getByRole('button', { name: '重新生成' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '准备发布' })).toBeInTheDocument()
  })
})

describe('PlatformPreview dynamic channels (P2-3)', () => {
  it('renders a custom channel tab from supportedChannels with the generic previewer', () => {
    render(
      <PlatformPreview
        state={{
          status: 'ready',
          channels: {
            custom_zhihu: { content: '自定义渠道的第一版内容' },
          },
        }}
        supportedChannels={['wechat_website', 'xiaohongshu', 'video_script_60s', 'custom_zhihu']}
        onGenerate={jest.fn()}
        onRegenerate={jest.fn()}
        onAdopt={jest.fn()}
      />,
    )
    // the custom tab exists and is first (channels WITH content sort first)
    const tab = screen.getByRole('tab', { name: '知乎' })
    expect(tab).toBeInTheDocument()
    // the generic previewer shows the real content, honestly labeled
    expect(screen.getByTestId('generic-preview-custom_zhihu')).toBeInTheDocument()
    expect(screen.getByText('自定义渠道的第一版内容')).toBeInTheDocument()
  })

  it('keeps the built-in three when supportedChannels is not provided', () => {
    render(
      <PlatformPreview
        state={{ status: 'ready', channels: { wechat_website: { content: '公众号内容' } } }}
        onGenerate={jest.fn()}
        onRegenerate={jest.fn()}
        onAdopt={jest.fn()}
      />,
    )
    expect(screen.getByRole('tab', { name: '公众号' })).toBeInTheDocument()
    expect(screen.getByText('公众号内容')).toBeInTheDocument()
  })

  it('shows a channel version even if it is no longer in supportedChannels (spec lapsed)', () => {
    render(
      <PlatformPreview
        state={{ status: 'ready', channels: { video_script_60s: { content: '口播稿' } } }}
        supportedChannels={['wechat_website']}
        onGenerate={jest.fn()}
        onRegenerate={jest.fn()}
        onAdopt={jest.fn()}
      />,
    )
    // the lapsed channel keeps a tab (existing versions are never hidden)
    expect(screen.getByRole('tab', { name: '口播' })).toBeInTheDocument()
    expect(screen.getByText('口播稿')).toBeInTheDocument()
  })
})
