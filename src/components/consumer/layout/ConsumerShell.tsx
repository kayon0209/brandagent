'use client'

import type { ReactNode } from 'react'

import styles from '../editor/consumer-editor.module.css'

interface ConsumerShellProps {
  children: ReactNode
}

export function ConsumerShell({ children }: ConsumerShellProps) {
  return <div className={styles.shell}>{children}</div>
}
