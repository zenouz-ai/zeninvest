/** Horizontal pipeline waterfall: Strategy → Moderation → Risk → Execution (3B bonus). */

import type { LastDecision } from './LLMOutputBlocks'

type StageStatus = 'passed' | 'blocked' | 'skipped' | 'pending'

type Stage = {
  label: string
  status: StageStatus
  detail: string
}

function deriveStages(decision: NonNullable<LastDecision>): Stage[] {
  const stages: Stage[] = []

  // Strategy
  const action = decision.strategy?.action?.toUpperCase() ?? ''
  const stratDetail = action
    ? `${action}${decision.strategy?.conviction != null ? ` @ ${decision.strategy.conviction}` : ''}`
    : 'No data'
  const stratStatus: StageStatus = action === 'HOLD' || action === 'QUEUED' ? 'blocked' : action ? 'passed' : 'skipped'
  stages.push({ label: 'Strategy', status: stratStatus, detail: stratDetail })

  // Moderation
  if (decision.moderation && decision.moderation.length > 0) {
    const consensus = decision.moderation.find((e) => e.consensus)?.consensus ?? decision.moderation[decision.moderation.length - 1]?.verdict ?? ''
    const modStatus: StageStatus = consensus.toLowerCase().includes('reject') ? 'blocked'
      : consensus.toLowerCase().includes('approve') ? 'passed' : 'passed'
    stages.push({ label: 'Moderation', status: modStatus, detail: consensus || 'Reviewed' })
  } else {
    stages.push({ label: 'Moderation', status: 'skipped', detail: 'Not invoked' })
  }

  // Risk
  if (decision.risk) {
    const verdict = decision.risk.verdict?.toUpperCase() ?? ''
    const riskStatus: StageStatus = verdict === 'VETO' || verdict === 'REJECT' ? 'blocked'
      : verdict === 'APPROVE' || verdict === 'APPROVED' || verdict === 'PASS' ? 'passed' : 'passed'
    const triggered = Array.isArray(decision.risk.triggered_rules) && decision.risk.triggered_rules.length > 0
      ? ` (${decision.risk.triggered_rules.length} rules)` : ''
    stages.push({ label: 'Risk', status: riskStatus, detail: (verdict || 'Checked') + triggered })
  } else {
    stages.push({ label: 'Risk', status: 'skipped', detail: 'Not invoked' })
  }

  // Execution
  if (decision.execution_summary?.last_buy || decision.execution_summary?.last_sell) {
    const exec = decision.execution_summary.last_buy ?? decision.execution_summary.last_sell!
    stages.push({ label: 'Execution', status: exec.status === 'filled' ? 'passed' : 'pending', detail: exec.status })
  } else if (stratStatus === 'blocked' || stages.some((s) => s.status === 'blocked')) {
    stages.push({ label: 'Execution', status: 'skipped', detail: 'Not reached' })
  } else {
    stages.push({ label: 'Execution', status: 'skipped', detail: 'No order' })
  }

  return stages
}

const STATUS_STYLES: Record<StageStatus, { dot: string; line: string; text: string }> = {
  passed: { dot: 'bg-gain', line: 'bg-gain/40', text: 'text-gain' },
  blocked: { dot: 'bg-loss', line: 'bg-loss/40', text: 'text-loss' },
  skipped: { dot: 'bg-terminal-border', line: 'bg-terminal-border', text: 'text-terminal-text-dim' },
  pending: { dot: 'bg-warning', line: 'bg-warning/40', text: 'text-warning' },
}

export function PipelineWaterfall({ decision }: { decision: NonNullable<LastDecision> }) {
  const stages = deriveStages(decision)

  return (
    <div className="flex items-center gap-0 overflow-x-auto py-2" aria-label="Pipeline stages">
      {stages.map((stage, i) => {
        const style = STATUS_STYLES[stage.status]
        return (
          <div key={stage.label} className="flex items-center">
            {/* Stage node */}
            <div className="flex flex-col items-center min-w-[72px]">
              <div className={`w-3 h-3 rounded-full ${style.dot}`} />
              <span className="text-[10px] font-semibold mt-1">{stage.label}</span>
              <span className={`text-[9px] ${style.text} max-w-[80px] truncate`} title={stage.detail}>
                {stage.detail}
              </span>
            </div>
            {/* Connector line */}
            {i < stages.length - 1 && (
              <div className={`h-0.5 w-6 sm:w-10 ${style.line} flex-shrink-0`} />
            )}
          </div>
        )
      })}
    </div>
  )
}
