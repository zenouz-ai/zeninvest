import { Panel } from '../components/Panel'
import { PublicPreviewSurface } from '../components/PublicPreviewSurface'
import { StatusPill } from '../components/StatusPill'

export default function PublicChat() {
  return (
    <PublicPreviewSurface
      title="Chat"
      description="A public preview of the conversational operator console."
      body="The chat tab is visible publicly so visitors can understand the product surface, but the live assistant, approvals, research trace, and action execution remain disabled outside operator sign-in."
    >
      <Panel className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-[-0.02em]">Demo Conversation</h2>
            <p className="mt-1 text-sm text-terminal-text-dim">Illustrative transcript only. No live model or trading action is available publicly.</p>
          </div>
          <StatusPill label="Preview Only" variant="draft" />
        </div>
        <div className="space-y-3">
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
            <div className="text-[11px] uppercase tracking-wide text-terminal-text-dim">User</div>
            <p className="mt-2 text-sm text-terminal-text">Summarize how the system thinks about risk before any action is proposed.</p>
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
            <div className="text-[11px] uppercase tracking-wide text-terminal-text-dim">Assistant</div>
            <p className="mt-2 text-sm text-terminal-text">
              The operator console combines market context, portfolio state, and explicit approval gates before any trade reaches execution. Public mode stops at explanation.
            </p>
          </div>
        </div>
        <div className="rounded-panel border border-terminal-border bg-terminal-bg/40 p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-sm text-terminal-text-dim">Public composer</span>
            <StatusPill label="Disabled" variant="warning" />
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] px-3 py-3 text-sm text-terminal-text-dim">
            Operator sign-in required to start a live chat session.
          </div>
        </div>
      </Panel>
    </PublicPreviewSurface>
  )
}
