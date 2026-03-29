import { Panel } from '../components/Panel'
import { PublicPreviewSurface } from '../components/PublicPreviewSurface'
import { StatusPill } from '../components/StatusPill'

export default function PublicOrderManagement() {
  return (
    <PublicPreviewSurface
      title="Order Management"
      description="A non-functional preview of the order management surface."
      body="The public site exposes a demo-only execution console. Live orders, broker IDs, slippage detail, stop levels, and failure diagnostics remain private behind operator sign-in."
    >
      <Panel>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Order Health</h2>
              <StatusPill label="Demo" variant="draft" />
            </div>
            <p className="text-sm text-terminal-text-dim">
              Public visitors can see that the product includes reconciliation, failure tracking, and execution monitoring, but no live broker state is exposed here.
            </p>
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Execution Quality</h2>
              <StatusPill label="Private" variant="warning" />
            </div>
            <p className="text-sm text-terminal-text-dim">
              Slippage, partial fills, and broker error detail are restricted to authenticated operators.
            </p>
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Stop Protection</h2>
              <StatusPill label="Read-only" variant="dim" />
            </div>
            <p className="text-sm text-terminal-text-dim">
              Public portfolio pages summarize protection posture only. Stop prices and adjustment history stay private.
            </p>
          </div>
        </div>
      </Panel>
    </PublicPreviewSurface>
  )
}
