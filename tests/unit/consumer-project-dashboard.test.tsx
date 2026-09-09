import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'

import { ProjectDashboard } from '@/components/consumer/ProjectDashboard'

describe('ProjectDashboard', () => {
  it('renders a recent project from supplied data without inventing publishing metrics', () => {
    render(
      <ProjectDashboard
        projects={[
          {
            task_id: 'project-1',
            title: '真实项目',
            core_idea: '这是一条真实核心观点。',
            writing_intent: '公众号',
          },
        ]}
        projectCount={1}
        learnedStyleCount={0}
        quotaRemaining={30000}
        activeFilter="all"
        onFilterChange={jest.fn()}
        onCreateProject={jest.fn()}
      />,
    )

    expect(screen.getByRole('link', { name: '打开项目：真实项目' })).toHaveAttribute('href', '/app/write/project-1')
    expect(screen.getByText('这是一条真实核心观点。')).toBeInTheDocument()
    expect(screen.queryByText(/已发布\s*1\s*篇/)).toBeNull()
    expect(screen.getByLabelText('项目流程')).toBeInTheDocument()
    expect(screen.getByText('本周创作进度')).toBeInTheDocument()
  })

  it('keeps the primary creation action operable from the dashboard', () => {
    const onCreateProject = jest.fn()
    render(
      <ProjectDashboard
        projects={[]}
        projectCount={0}
        learnedStyleCount={0}
        quotaRemaining={null}
        activeFilter="all"
        onFilterChange={jest.fn()}
        onCreateProject={onCreateProject}
      />,
    )

    fireEvent.click(screen.getAllByRole('button', { name: '新建项目' })[0])
    expect(onCreateProject).toHaveBeenCalledTimes(1)
  })
})
