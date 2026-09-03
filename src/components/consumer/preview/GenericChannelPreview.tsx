'use client'

/**
 * Generic previewer for custom channels (agentization P2-3).
 *
 * Custom channels have no bespoke renderer; this shows the generated
 * text honestly (paragraph per line) with the channel's own label —
 * never a fake platform skin pretending to be a specific app.
 */

interface GenericChannelPreviewProps {
  channelKey: string
  label: string
  content: string
}

export function GenericChannelPreview({ channelKey, label, content }: GenericChannelPreviewProps) {
  const lines = content.split('\n').filter(Boolean)
  return (
    <div data-testid={`generic-preview-${channelKey}`} className="genericChannelPreview">
      <p className="genericChannelPreviewNote">
        「{label}」为自定义渠道，以纯文本展示实际内容。
      </p>
      <div className="genericChannelPreviewBody">
        {lines.map((line, index) => (
          <p key={index}>{line}</p>
        ))}
      </div>
    </div>
  )
}
