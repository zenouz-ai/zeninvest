import { useEffect, useState } from 'react'
import { evolutionApi } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { SectionHeader } from '../components/SectionHeader'
import { StatusPill, type PillVariant } from '../components/StatusPill'
import { TableSkeleton } from '../components/Skeleton'
import { useAsyncData } from '../hooks/useAsyncData'
import type { EvolutionRequestDetail, EvolutionRequestSummary } from '../types'

const STATUS_VARIANT: Record<string, PillVariant> = {
  DRAFT: 'draft',
  NEEDS_CLARIFICATION: 'warning',
  PLANNED: 'live',
  APPROVED_FOR_BUILD: 'active',
  IMPLEMENTING: 'active',
  VALIDATING: 'warning',
  READY_FOR_REVIEW: 'live',
  APPROVED_FOR_DEPLOY: 'warning',
  DEPLOYING: 'warning',
  DEPLOYED: 'active',
  REJECTED: 'alert',
  ROLLED_BACK: 'alert',
}

const RISK_VARIANT: Record<string, PillVariant> = {
  LOW: 'active',
  MEDIUM: 'warning',
  HIGH: 'alert',
}

const primaryButtonClass =
  'inline-flex items-center justify-center rounded-full border border-cyan/40 bg-cyan/10 px-4 py-2 text-sm font-medium text-cyan transition-colors hover:bg-cyan/15 focus:outline-none focus:ring-2 focus:ring-cyan/40 disabled:cursor-not-allowed disabled:opacity-50'
const secondaryButtonClass =
  'inline-flex items-center justify-center rounded-full border border-terminal-border px-4 py-2 text-sm font-medium text-terminal-text-muted transition-colors hover:border-cyan/30 hover:text-terminal-text focus:outline-none focus:ring-2 focus:ring-cyan/40 disabled:cursor-not-allowed disabled:opacity-50'
const inputClass =
  'w-full rounded-panel border border-terminal-border bg-terminal-surface px-3 py-2 text-sm text-terminal-text placeholder:text-terminal-text-dim focus:outline-none focus:ring-2 focus:ring-cyan/35'

function safeFormat(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function humanizeStatus(value: string): string {
  return value.replace(/_/g, ' ')
}

function RequestListItem({
  item,
  selected,
  onSelect,
}: {
  item: EvolutionRequestSummary
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-panel border p-4 text-left transition-all focus:outline-none focus:ring-2 focus:ring-cyan/40 ${
        selected
          ? 'border-cyan/35 bg-cyan/10'
          : 'border-terminal-border bg-white/[0.02] hover:border-terminal-border-strong hover:bg-white/[0.04]'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <p className="text-sm font-medium text-terminal-text">{item.title}</p>
          <p className="text-xs text-terminal-text-muted line-clamp-2">
            {item.objective ?? 'No objective extracted yet.'}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusPill label={humanizeStatus(item.status)} variant={STATUS_VARIANT[item.status] ?? 'dim'} />
          {item.risk_class && (
            <StatusPill label={`${item.risk_class} risk`} variant={RISK_VARIANT[item.risk_class] ?? 'dim'} />
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-wide text-terminal-text-dim">
        <span>{safeFormat(item.updated_at)}</span>
        {item.open_questions_count > 0 && <span>{item.open_questions_count} open question(s)</span>}
        {item.touched_areas.slice(0, 2).map((area) => (
          <span key={area} className="rounded-full border border-terminal-border px-2 py-0.5 normal-case tracking-normal">
            {area}
          </span>
        ))}
      </div>
    </button>
  )
}

function PlannerDetail({ detail }: { detail: EvolutionRequestDetail }) {
  const plan = detail.latest_plan

  return (
    <div className="space-y-4">
      <Panel hero className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill label={humanizeStatus(detail.status)} variant={STATUS_VARIANT[detail.status] ?? 'dim'} />
              {detail.risk_class && (
                <StatusPill label={`${detail.risk_class} risk`} variant={RISK_VARIANT[detail.risk_class] ?? 'dim'} />
              )}
              <StatusPill label={humanizeStatus(detail.phase_capabilities.mode)} variant="draft" />
            </div>
            <h2 className="text-2xl font-heading font-bold text-terminal-text">{detail.title}</h2>
            <p className="max-w-3xl text-sm leading-6 text-terminal-text-muted">{plan.summary}</p>
          </div>
          <div className="grid min-w-[220px] gap-2 text-xs text-terminal-text-dim">
            <div>Requested by: <span className="text-terminal-text">{detail.requested_by ?? 'operator'}</span></div>
            <div>Last updated: <span className="text-terminal-text">{safeFormat(detail.updated_at)}</span></div>
            <div>Plan version: <span className="text-terminal-text">v{detail.latest_plan_version}</span></div>
            <div>Confidence: <span className="text-terminal-text">{plan.confidence_score ?? '—'}</span></div>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-panel border border-terminal-border bg-white/[0.03] p-3">
            <p className="label-mono mb-2">Phase 1</p>
            <p className="text-sm text-terminal-text">Planner-only</p>
            <p className="mt-1 text-xs text-terminal-text-muted">{detail.phase_capabilities.reason}</p>
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.03] p-3">
            <p className="label-mono mb-2">Build Gate</p>
            <p className="text-sm text-terminal-text">Locked</p>
            <p className="mt-1 text-xs text-terminal-text-muted">{plan.risk_policy.future_build_mode}</p>
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.03] p-3">
            <p className="label-mono mb-2">Deploy Gate</p>
            <p className="text-sm text-terminal-text">
              {plan.risk_policy.backtest_required ? 'Manual + evidence' : 'Manual later'}
            </p>
            <p className="mt-1 text-xs text-terminal-text-muted">{plan.risk_policy.future_deploy_gate}</p>
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <Panel className="space-y-4">
          <SectionHeader title="Conversation & Scope" />
          <div className="space-y-3">
            {detail.messages.map((message) => (
              <div key={message.id} className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                <div className="flex items-center justify-between gap-3 text-[11px] uppercase tracking-wide text-terminal-text-dim">
                  <span>{message.role}</span>
                  <span>{safeFormat(message.created_at)}</span>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-terminal-text">{message.message_text}</p>
              </div>
            ))}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="label-mono mb-2">Touched Areas</p>
              <div className="flex flex-wrap gap-2">
                {plan.touched_areas.length > 0 ? (
                  plan.touched_areas.map((area) => (
                    <span key={area} className="rounded-full border border-terminal-border px-3 py-1 text-xs text-terminal-text-muted">
                      {area}
                    </span>
                  ))
                ) : (
                  <span className="text-sm text-terminal-text-dim">Waiting on subsystem clarification.</span>
                )}
              </div>
            </div>
            <div>
              <p className="label-mono mb-2">Excluded Areas</p>
              <div className="flex flex-wrap gap-2">
                {plan.excluded_areas.length > 0 ? (
                  plan.excluded_areas.map((area) => (
                    <span key={area} className="rounded-full border border-terminal-border px-3 py-1 text-xs text-terminal-text-muted">
                      {area}
                    </span>
                  ))
                ) : (
                  <span className="text-sm text-terminal-text-dim">No explicit exclusions provided.</span>
                )}
              </div>
            </div>
          </div>

          {plan.clarification_questions.length > 0 && (
            <div className="rounded-panel border border-warning/30 bg-warning/10 p-4">
              <p className="label-mono mb-2 text-warning">Clarification Needed</p>
              <ul className="space-y-2 text-sm text-terminal-text">
                {plan.clarification_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </div>
          )}
        </Panel>

        <Panel className="space-y-4">
          <SectionHeader title="Planner Output" />
          <div>
            <p className="label-mono mb-2">Objective</p>
            <p className="text-sm leading-6 text-terminal-text">{plan.objective ?? detail.request_text}</p>
          </div>
          <div>
            <p className="label-mono mb-2">Implementation Steps</p>
            <ol className="space-y-2 text-sm leading-6 text-terminal-text-muted">
              {plan.implementation_steps.map((step, index) => (
                <li key={step}>
                  <span className="mr-2 text-terminal-text">{index + 1}.</span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
          <div>
            <p className="label-mono mb-2">Assumptions</p>
            <ul className="space-y-2 text-sm leading-6 text-terminal-text-muted">
              {plan.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(300px,0.9fr)]">
        <Panel className="space-y-4">
          <SectionHeader title="Validation Matrix" />
          <div className="space-y-3">
            {plan.validation_matrix.map((check) => (
              <div key={check.id} className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-terminal-text">{check.label}</p>
                  {check.required && <StatusPill label="required" variant="warning" />}
                </div>
                <p className="mt-2 text-sm leading-6 text-terminal-text-muted">{check.scope}</p>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="space-y-4">
          <SectionHeader title="Repo Context & Audit" />
          <div>
            <p className="label-mono mb-2">Key Docs</p>
            <div className="space-y-2">
              {plan.repo_context.docs.map((doc) => (
                <div key={doc.path} className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                  <p className="text-sm font-medium text-terminal-text">{doc.title}</p>
                  <p className="mt-1 font-mono text-xs text-cyan">{doc.path}</p>
                  <p className="mt-2 text-sm leading-6 text-terminal-text-muted">{doc.reason}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <p className="label-mono mb-2">Likely Code Areas</p>
            <div className="space-y-2">
              {plan.repo_context.code_areas.map((area) => (
                <div key={area.label} className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                  <p className="text-sm font-medium text-terminal-text">{area.label}</p>
                  <p className="mt-2 text-sm leading-6 text-terminal-text-muted">{area.reason}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {area.paths.map((path) => (
                      <span key={path} className="rounded-full border border-terminal-border px-2 py-0.5 font-mono text-[11px] text-terminal-text-dim">
                        {path}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
              <p className="label-mono mb-2">Planning Runs</p>
              <p className="text-2xl font-heading font-bold text-terminal-text">{detail.runs.length}</p>
              <p className="mt-1 text-xs text-terminal-text-dim">Every create or clarification turn is audited as a planning run.</p>
            </div>
            <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
              <p className="label-mono mb-2">Artifacts</p>
              <p className="text-2xl font-heading font-bold text-terminal-text">{detail.artifacts.length}</p>
              <p className="mt-1 text-xs text-terminal-text-dim">Validation matrices, repo context snapshots, and plan summaries are persisted.</p>
            </div>
          </div>
          <div>
            <p className="label-mono mb-2">Related Roadmap Items</p>
            <div className="flex flex-wrap gap-2">
              {plan.repo_context.related_roadmap_items.map((item) => (
                <span key={item} className="rounded-full border border-terminal-border px-3 py-1 text-xs text-terminal-text-muted">
                  {item}
                </span>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  )
}

export default function Evolution() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [composerText, setComposerText] = useState('')
  const [clarificationText, setClarificationText] = useState('')
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [mutationBusy, setMutationBusy] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  const requestsState = useAsyncData<EvolutionRequestSummary[]>(
    () => evolutionApi.listRequests({ limit: 20 }),
    [reloadToken],
    { refreshInterval: 30_000 }
  )

  const detailState = useAsyncData<EvolutionRequestDetail | null>(
    () => (selectedId == null ? Promise.resolve(null) : evolutionApi.getRequest(selectedId)),
    [selectedId, reloadToken],
    { enabled: selectedId != null, refreshInterval: 30_000 }
  )

  useEffect(() => {
    if (selectedId != null) return
    const first = requestsState.data?.[0]
    if (first) {
      setSelectedId(first.id)
    }
  }, [requestsState.data, selectedId])

  const handleCreate = async () => {
    if (!composerText.trim()) return
    try {
      setMutationBusy(true)
      setMutationError(null)
      const created = await evolutionApi.createRequest(composerText.trim())
      setComposerText('')
      setClarificationText('')
      setSelectedId(created.id)
      setReloadToken((value) => value + 1)
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'Failed to create evolution request.')
    } finally {
      setMutationBusy(false)
    }
  }

  const handleClarification = async () => {
    if (selectedId == null || !clarificationText.trim()) return
    try {
      setMutationBusy(true)
      setMutationError(null)
      await evolutionApi.addMessage(selectedId, clarificationText.trim())
      setClarificationText('')
      setReloadToken((value) => value + 1)
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'Failed to add clarification.')
    } finally {
      setMutationBusy(false)
    }
  }

  const selectedDetail = detailState.data

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="Zen Evolution Engine"
        title="Evolution Planner"
        description="Policy-constrained software evolution for ZenInvest. Operators can describe a change in natural language, retrieve repo-grounded planning context, and receive a scoped implementation plan with risk classification and deterministic validation gates."
      />

      <Panel hero className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <StatusPill label="dashboard first" variant="live" />
              <StatusPill label="planner only" variant="draft" />
              <StatusPill label="branch + review later" variant="warning" />
            </div>
            <p className="max-w-3xl text-sm leading-6 text-terminal-text-muted">
              This first slice implements the authenticated planning workflow only. It accepts operator requests, normalizes intent, retrieves roadmap and architecture context, classifies risk, and stores a full audit trail. Build and deploy gates stay hard-locked.
            </p>
          </div>
          <div className="flex gap-2">
            <button type="button" className={secondaryButtonClass} disabled>
              Build Locked
            </button>
            <button type="button" className={secondaryButtonClass} disabled>
              Deploy Locked
            </button>
          </div>
        </div>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Panel className="space-y-4">
            <SectionHeader title="New Request" />
            <textarea
              value={composerText}
              onChange={(event) => setComposerText(event.target.value)}
              rows={7}
              className={inputClass}
              placeholder="Describe the change you want in natural language. Include scope, exclusions, and success criteria when you can."
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-terminal-text-dim">
                Examples: dashboard UX changes, backend workflow changes, notification tweaks, or high-risk trading changes that should remain review-only.
              </p>
              <button type="button" onClick={() => void handleCreate()} className={primaryButtonClass} disabled={mutationBusy || !composerText.trim()}>
                {mutationBusy ? 'Planning…' : 'Create Plan'}
              </button>
            </div>
            {mutationError && <p className="text-sm text-terminal-negative">{mutationError}</p>}
          </Panel>

          <Panel className="space-y-4">
            <SectionHeader title="Recent Requests" />
            {requestsState.loading && !requestsState.data ? (
              <TableSkeleton rows={5} cols={1} />
            ) : requestsState.error && !requestsState.data ? (
              <EmptyState message="Failed to load evolution requests." hint={requestsState.error} />
            ) : requestsState.data && requestsState.data.length > 0 ? (
              <div className="space-y-3">
                {requestsState.data.map((item) => (
                  <RequestListItem
                    key={item.id}
                    item={item}
                    selected={item.id === selectedId}
                    onSelect={() => setSelectedId(item.id)}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                message="No evolution requests yet."
                hint="Create the first planner request from the panel above."
              />
            )}
          </Panel>
        </div>

        <div className="space-y-4">
          {detailState.loading && selectedId != null && !selectedDetail ? (
            <Panel className="p-4">
              <TableSkeleton rows={10} cols={2} />
            </Panel>
          ) : selectedDetail ? (
            <>
              <PlannerDetail detail={selectedDetail} />
              {selectedDetail.latest_plan.clarification_questions.length > 0 && (
                <Panel className="space-y-4">
                  <SectionHeader title="Answer Clarification Questions" />
                  <textarea
                    value={clarificationText}
                    onChange={(event) => setClarificationText(event.target.value)}
                    rows={5}
                    className={inputClass}
                    placeholder="Add the clarification the planner asked for. The plan will be regenerated and versioned."
                  />
                  <div className="flex items-center justify-end gap-2">
                    <button type="button" onClick={() => void handleClarification()} className={primaryButtonClass} disabled={mutationBusy || !clarificationText.trim()}>
                      {mutationBusy ? 'Updating…' : 'Regenerate Plan'}
                    </button>
                  </div>
                </Panel>
              )}
            </>
          ) : (
            <Panel className="p-8">
              <EmptyState
                message="Select an evolution request to inspect the structured plan."
                hint="The planner will show touched areas, validation requirements, repo context, and the current hard control gates."
              />
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
