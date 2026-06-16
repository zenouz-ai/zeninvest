import type { ReactNode } from 'react'
import type { LearningTabId } from './hooks/useLearningPageData'

const TABS: { id: LearningTabId; label: string; description: string }[] = [
  {
    id: 'shadow',
    label: 'Live shadow',
    description: 'What challengers would do this month without touching orders.',
  },
  {
    id: 'evaluation',
    label: 'Offline evaluation',
    description: 'Would challengers have improved historical outcomes?',
  },
  {
    id: 'attribution',
    label: 'Pipeline attribution',
    description: 'Which committee stage or context correlates with bad pace outcomes?',
  },
  {
    id: 'rejection',
    label: 'Rejection',
    description: 'Did the gate decline tickers that would have lost?',
  },
]

interface LearningTabsProps {
  activeTab: LearningTabId
  onTabChange: (tab: LearningTabId) => void
  children: (tab: LearningTabId) => ReactNode
}

export function LearningTabs({ activeTab, onTabChange, children }: LearningTabsProps) {
  return (
    <div data-testid="learning-tabs">
      <div className="flex flex-wrap gap-2 mb-4 border-b border-terminal-border pb-3">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            data-testid={`learning-tab-${tab.id}`}
            className={`px-3 py-2 text-sm rounded-panel border transition-colors ${
              activeTab === tab.id
                ? 'border-cyan/50 text-cyan bg-cyan/10'
                : 'border-terminal-border text-terminal-text-muted hover:bg-terminal-surface'
            }`}
            onClick={() => onTabChange(tab.id)}
            title={tab.description}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-terminal-text-dim mb-4">
        {TABS.find((t) => t.id === activeTab)?.description}
      </p>
      {children(activeTab)}
    </div>
  )
}

export { TABS as LEARNING_TABS }
