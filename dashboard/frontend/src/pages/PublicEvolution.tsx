import { Panel } from '../components/Panel'
import { PublicPreviewSurface } from '../components/PublicPreviewSurface'
import { StatusPill } from '../components/StatusPill'

export default function PublicEvolution() {
  return (
    <PublicPreviewSurface
      title="Evolution"
      description="A public preview of the evolution planner workflow."
      body="The public site shows the planner concept only. Live requests, repo context, artifacts, approvals, and deploy controls remain private and policy-gated."
    >
      <Panel className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill label="Planner Concept" variant="live" />
          <StatusPill label="Build Locked" variant="warning" />
          <StatusPill label="Deploy Locked" variant="warning" />
        </div>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
          <div className="space-y-4">
            <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
              <p className="label-mono mb-2">Example Request</p>
              <p className="text-sm text-terminal-text">Design a safer public demo surface without exposing operator controls.</p>
            </div>
            <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
              <p className="label-mono mb-2">Validation Preview</p>
              <ul className="space-y-2 text-sm text-terminal-text-dim">
                <li>Public routes expose only sanitized schemas.</li>
                <li>Protected actions require a valid operator session.</li>
                <li>Build and deploy approvals remain disabled in public mode.</li>
              </ul>
            </div>
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
            <p className="label-mono mb-2">Planner Status</p>
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-terminal-text-dim">Intent capture</span>
                <StatusPill label="Preview" variant="draft" />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-terminal-text-dim">Repo context</span>
                <StatusPill label="Private" variant="warning" />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-terminal-text-dim">Approval gates</span>
                <StatusPill label="Locked" variant="alert" />
              </div>
            </div>
          </div>
        </div>
      </Panel>
    </PublicPreviewSurface>
  )
}
