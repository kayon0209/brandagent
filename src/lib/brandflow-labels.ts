export const statusLabel: Record<string, string> = {
  draft: 'Brief 草稿',
  validating_brief: '正在校验 Brief',
  waiting_for_clarification: '等待补充信息',
  researching: '正在检索权威事实',
  waiting_for_outline_approval: '等待大纲审批',
  generating_master: '正在生成主内容',
  reviewing_master: '正在审查主内容',
  waiting_for_master_approval: '等待主内容审批',
  generating_channels: '正在生成渠道版本',
  reviewing_channels: '渠道审查中',
  waiting_for_final_approval: '等待最终审批',
  exporting: '正在准备导出',
  completed: '已完成',
  failed: '已停止',
  cancelled: '已取消',
}

export function channelLabel(channel: string) {
  return (
    (
      {
        wechat_website: '微信 / 官网',
        xiaohongshu: '小红书',
        video_script_60s: '60 秒视频脚本',
        marketing_email: '营销邮件',
      } as Record<string, string>
    )[channel] ?? channel
  )
}

export function approvalLabel(type: string) {
  return (
    (
      {
        outline: '批准大纲',
        master_brand: '批准品牌语言',
        master_final: '批准主内容事实与风险',
        channel: '批准渠道版本',
        final_package: '批准最终内容包',
      } as Record<string, string>
    )[type] ?? type
  )
}

export function versionTitle(item: Record<string, unknown>) {
  const ch = item.channel ? channelLabel(String(item.channel)) : ''
  return `${ch ? `${ch} · ` : ''}${String(item.content_type ?? '内容版本')} v${String(item.version_number ?? '')}`
}
