'use client'

/**
 * DeepResearchPanel — Phase 6 深度调研面板 (user-approved 2026-09-08).
 *
 * Product rules from MASTER_PLAN §10 用户价值与界面边界:
 * - user-initiated from a project (素材抽屉) or the materials page;
 * - pre-start estimate + cancel-anytime, NO agent chain-of-thought —
 *   progress is 「已完成方向数」 only;
 * - results are CANDIDATE material cards (summary/excerpt/source/time/
 *   risk hint); nothing enters the library until 加入素材;
 * - a joined card becomes a traceable material linked to this project.
 */

import { useState } from 'react'

import { useDeepResearch } from '@/hooks/useDeepResearch'
import type { ResearchCandidateCard } from '@/lib/api/research'
import { newIdempotencyKey } from '@/lib/idempotency'

const RISK_HINTS = ['来源为网络公开内容，请核实后引用', '时效性有限，注意数据年份', '观点来自单一来源，建议交叉验证']

function riskHint(card: ResearchCandidateCard): string {
  if (!card.reachable) return '来源当前不可访问，摘录为调研时记录'
  if (!card.excerpt_valid) return '摘录与来源原文的匹配度存疑，请人工核对'
  return RISK_HINTS[0]
}

export function DeepResearchPanel({ taskId }: { taskId?: string | null }) {
  const { phase, run, progress, busy, message, start, cancel, reset, joinCard, joinedCards } = useDeepResearch()
  const [question, setQuestion] = useState('')
  const [audience, setAudience] = useState('')
  const [scope, setScope] = useState('')
  const [formOpen, setFormOpen] = useState(false)

  const cards = run?.candidate_cards ?? []

  return (
    <section data-testid="deep-research-panel" style={{ margin: '24px 0' }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 8px' }}>深度调研</h2>

      {phase === 'idle' && !formOpen && (
        <>
          <p style={{ margin: '0 0 12px', fontSize: 14 }}>
            围绕一个具体问题搜集公开资料，整理成可引用的候选素材卡片。你确认后才会进入素材库。
          </p>
          <button type="button" data-testid="research-open-form" onClick={() => setFormOpen(true)}>
            发起深度调研
          </button>
        </>
      )}

      {(formOpen || phase === 'starting') && (
        <form
          data-testid="research-form"
          onSubmit={event => {
            event.preventDefault()
            void start(question, audience, scope)
          }}
        >
          <label htmlFor="research-question" style={{ display: 'block', fontSize: 14 }}>
            调研问题
          </label>
          <textarea
            id="research-question"
            data-testid="research-question-input"
            value={question}
            onChange={event => setQuestion(event.target.value)}
            placeholder="例如：2026 年中文创作者最常用的内容分发渠道有哪些？"
            rows={2}
            maxLength={500}
            style={{ width: '100%', marginBottom: 8 }}
            required
          />
          <label htmlFor="research-audience" style={{ display: 'block', fontSize: 14 }}>
            目标读者（可选）
          </label>
          <input
            id="research-audience"
            data-testid="research-audience-input"
            value={audience}
            onChange={event => setAudience(event.target.value)}
            placeholder="例如：小红书上的新手工坊主"
            maxLength={200}
            style={{ width: '100%', marginBottom: 8 }}
          />
          <label htmlFor="research-scope" style={{ display: 'block', fontSize: 14 }}>
            范围（可选）
          </label>
          <input
            id="research-scope"
            data-testid="research-scope-input"
            value={scope}
            onChange={event => setScope(event.target.value)}
            placeholder="例如：只要近两年的中文公开讨论"
            maxLength={500}
            style={{ width: '100%', marginBottom: 12 }}
          />
          <p data-testid="research-estimate" style={{ fontSize: 13, margin: '0 0 12px' }}>
            发起前说明：一次调研通常消耗约 30K token 额度、几分钟内完成；期间可随时取消，已完成方向的结果会保留。
          </p>
          <div>
            <button type="submit" disabled={busy || question.trim().length < 4} data-testid="research-submit">
              {phase === 'starting' ? '正在发起…' : '开始调研'}
            </button>
            <button type="button" onClick={() => setFormOpen(false)} style={{ marginLeft: 8 }} disabled={busy}>
              收起
            </button>
          </div>
        </form>
      )}

      {phase === 'running' && (
        <div data-testid="research-progress" style={{ fontSize: 14 }}>
          <p style={{ margin: '0 0 8px' }} role="status">
            正在调研：已完成 {progress.completedDirections}/{progress.directions.length || 4} 个方向
            {progress.searchCalls > 0 ? `，检索 ${progress.searchCalls} 次` : ''}
          </p>
          {progress.directions.length > 0 && (
            <ul style={{ margin: '0 0 12px', paddingLeft: 20, fontSize: 13 }}>
              {progress.directions.map(direction => (
                <li key={direction}>{direction}</li>
              ))}
            </ul>
          )}
          <button type="button" data-testid="research-cancel" onClick={() => void cancel()} disabled={busy}>
            取消调研
          </button>
        </div>
      )}

      {message && (
        <p role="status" data-testid="research-message" style={{ fontSize: 13, margin: '12px 0' }}>
          {message}
        </p>
      )}

      {(phase === 'succeeded' || phase === 'canceled') && cards.length > 0 && (
        <div data-testid="research-cards">
          <p style={{ fontSize: 14, margin: '0 0 8px' }}>
            {phase === 'canceled' ? '调研已取消，以下是取消前拿到的候选素材：' : '候选素材卡片（未加入素材库前不参与生成）：'}
          </p>
          {run?.synthesis && (
            <blockquote
              data-testid="research-synthesis"
              style={{ fontSize: 14, whiteSpace: 'pre-wrap', borderLeft: '3px solid #ccc', margin: '0 0 12px', padding: '4px 12px' }}
            >
              {run.synthesis}
            </blockquote>
          )}
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {cards.map((card, index) => (
              <li
                key={`${card.url}-${index}`}
                data-testid="research-card"
                style={{ border: '1px solid #e5e5e5', borderRadius: 8, padding: 12, marginBottom: 8 }}
              >
                <p style={{ margin: '0 0 4px', fontWeight: 600, fontSize: 14 }}>{card.title || card.url}</p>
                <p style={{ margin: '0 0 4px', fontSize: 13 }}>
                  摘录：{card.excerpt.slice(0, 200)}
                  {card.excerpt.length > 200 ? '…' : ''}
                </p>
                <p style={{ margin: '0 0 4px', fontSize: 12 }}>
                  来源：
                  <a href={card.url} target="_blank" rel="noreferrer noopener">
                    {card.url}
                  </a>
                  （访问于 {card.retrieved_at?.slice(0, 10) || '—'}）
                </p>
                <p style={{ margin: '0 0 8px', fontSize: 12 }}>风险提示：{riskHint(card)}</p>
                <button
                  type="button"
                  data-testid="research-join-card"
                  disabled={busy || joinedCards.has(index)}
                  onClick={() => void joinCard(index, taskId)}
                >
                  {joinedCards.has(index) ? '已加入素材库' : '加入素材'}
                </button>
              </li>
            ))}
          </ul>
          <button type="button" data-testid="research-reset" onClick={reset} style={{ marginTop: 8 }}>
            再发起一次调研
          </button>
        </div>
      )}

      {phase === 'succeeded' && cards.length === 0 && (
        <div data-testid="research-no-cards" style={{ fontSize: 14 }}>
          <p>{run?.synthesis || '本轮调研没有拿到可核实的来源，建议换个问法或稍后再试。'}</p>
          <button type="button" onClick={reset}>
            重新发起
          </button>
        </div>
      )}

      {phase === 'failed' && (
        <div data-testid="research-failed" role="alert" style={{ fontSize: 14 }}>
          <p>调研没能完成：{run?.error || '服务暂时不可用'}</p>
          <button type="button" onClick={reset}>
            重试
          </button>
        </div>
      )}
    </section>
  )
}
