'use client'

import Link from 'next/link'
import { AlertTriangle, Check, RefreshCw, Send, X, UserPlus, ShieldCheck } from 'lucide-react'
import styles from './brandflow-live-workspace.module.css'

interface RecoveryWizardProps {
  error: {
    code: string
    message: string
    recoverable: boolean
    saved_work_safe: boolean
    requires_human: boolean
  }
  retryCount?: number
  onRetry: () => void
  onManualContinue?: () => void
  onEscalate?: () => void
  onAbandon?: () => void
}

export function RecoveryWizard({
  error,
  retryCount = 0,
  onRetry,
  onManualContinue,
  onEscalate,
  onAbandon,
}: RecoveryWizardProps) {
  return (
    <div className={styles.failure} role="alert">
      <div className={styles.failureIcon}>
        <AlertTriangle size={24} />
      </div>

      <div className={styles.failureSections}>
        {/* 1. What happened */}
        <section className={styles.failureSection}>
          <h4>
            <X size={14} />
            发生了什么
          </h4>
          <p>{error.message}</p>
          <small>{error.code}</small>
        </section>

        {/* 2. Work safety */}
        <section className={styles.failureSection}>
          <h4>
            <ShieldCheck size={14} />
            工作安全性
          </h4>
          <p className={error.saved_work_safe ? styles.safeLabel : styles.unsafeLabel}>
            {error.saved_work_safe
              ? '已保存的工作内容安全，不会丢失。'
              : '需要人工核对保存状态，部分内容可能未持久化。'}
          </p>
        </section>

        {/* 3. What can be done */}
        <section className={styles.failureSection}>
          <h4>
            <Check size={14} />
            当前可以做什么
          </h4>
          <p>
            {error.requires_human
              ? '此问题需要管理员或团队成员介入处理。你可以将任务转交给相关人员。'
              : error.recoverable
                ? '系统可以从安全检查点自动恢复，点击下方"重试"按钮继续。'
                : '此任务无法自动恢复，请检查 Brief 信息后新建任务重试。'}
          </p>
          {!error.recoverable && (
            <div style={{marginTop:12,display:'flex',gap:12,flexWrap:'wrap'}}>
              <Link href="/brandflow/tasks" style={{fontSize:12,color:'#3b5ccc'}}>新建任务</Link>
              <span style={{fontSize:12,color:'#667085'}}>或</span>
              <Link href="/brandflow/settings" style={{fontSize:12,color:'#3b5ccc'}}>联系管理员</Link>
            </div>
          )}
        </section>

        {retryCount >= 1 && (
          <section className={styles.failureSection} style={{background:'#fef3c7',borderRadius:6,padding:12}}>
            <h4 style={{color:'#854d0e'}}>⚠️ 已重试 {retryCount} 次</h4>
            <p style={{color:'#854d0e',fontSize:13}}>
              多次重试未能解决问题。建议新建任务重试，或联系工作区管理员检查和修复配置。
            </p>
          </section>
        )}

        {/* 4. Actions */}
        <div className={styles.failureActions}>
          {error.recoverable && (
            <button className={styles.failurePrimaryBtn} onClick={onRetry}>
              <RefreshCw size={14} /> 从检查点重试
            </button>
          )}
          {onManualContinue && (
            <button className={styles.failureBtn} onClick={onManualContinue}>
              手动继续
            </button>
          )}
          {error.requires_human && onEscalate && (
            <button className={styles.failureBtn} onClick={onEscalate}>
              <UserPlus size={14} /> 转交管理员
            </button>
          )}
          {onAbandon && (
            <button className={styles.failureBtn} onClick={onAbandon} style={{ color: '#d92d20' }}>
              <X size={14} /> 终止任务
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
