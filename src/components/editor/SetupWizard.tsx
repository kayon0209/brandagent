'use client'

import { useState } from 'react'
import { Check, ChevronRight, Tags, Upload, FileCheck2, LayoutGrid, FileText, ArrowRight } from 'lucide-react'
import Link from 'next/link'
import styles from './brandflow-live-workspace.module.css'

interface SetupWizardProps {
  onComplete: () => void
}

const steps = [
  {
    title: '配置品牌',
    desc: '设置品牌名称和基本信息，BrandFlow 将基于品牌规范生成内容。',
    icon: Tags,
    action: { label: '前往品牌管理', href: '/brandflow/brands' },
  },
  {
    title: '上传产品资料',
    desc: '上传产品文档、规格说明或链接，作为内容生成的事实依据。',
    icon: Upload,
    action: { label: '前往知识库', href: '/brandflow/knowledge' },
  },
  {
    title: '审核品牌规范',
    desc: '检查品牌语气、术语表和禁止声明，确保生成内容符合品牌标准。',
    icon: FileCheck2,
    action: { label: '查看品牌规范', href: '/brandflow/brands' },
  },
  {
    title: '验证渠道配置',
    desc: '确认微信/小红书/视频脚本/营销邮件等渠道的格式规范和合规要求。',
    icon: LayoutGrid,
    action: { label: '查看渠道配置', href: '/brandflow/channels' },
  },
  {
    title: '创建首个内容任务',
    desc: '填写 Brief，选择渠道，开始生成你的第一篇品牌内容。',
    icon: FileText,
    action: { label: '创建任务', href: '/brandflow/tasks' },
  },
]

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const [completed, setCompleted] = useState<Set<number>>(new Set())

  function markComplete(index: number) {
    setCompleted((prev) => {
      const next = new Set(prev)
      next.add(index)
      return next
    })
  }

  return (
    <section className={styles.setupWizard}>
      <header className={styles.setupWizardHeader}>
        <div>
          <h2>开始使用 BrandFlow</h2>
          <p>完成以下 5 个步骤，建立可安全创建首个内容任务的工作区。</p>
        </div>
        <span className={styles.setupProgress}>
          {completed.size} / {steps.length} 步完成
        </span>
      </header>

      <ol className={styles.setupSteps}>
        {steps.map((step, index) => {
          const isDone = completed.has(index)
          const Icon = step.icon
          return (
            <li key={index} data-done={isDone ? 'true' : 'false'}>
              <span className={styles.setupStepIcon}>
                {isDone ? <Check size={16} /> : <Icon size={16} />}
              </span>
              <div className={styles.setupStepBody}>
                <h3>{step.title}</h3>
                <p>{step.desc}</p>
              </div>
              <div className={styles.setupStepActions}>
                <Link href={step.action.href} className={styles.primary}>
                  {step.action.label} <ArrowRight size={14} />
                </Link>
                {!isDone && (
                  <button className={styles.secondary} onClick={() => markComplete(index)}>
                    标记为已完成
                  </button>
                )}
              </div>
            </li>
          )
        })}
      </ol>

      {completed.size === steps.length && (
        <footer className={styles.setupWizardFooter}>
          <div>
            <Check size={18} />
            <span>
              <b>设置完成！</b>
              <small>你现在可以创建首个内容任务了。</small>
            </span>
          </div>
          <button className={styles.primary} onClick={onComplete}>
            开始使用 <ChevronRight size={16} />
          </button>
        </footer>
      )}
    </section>
  )
}
