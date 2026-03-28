/**
 * Chat page — primary operator console for conversational trading.
 *
 * This is a thin wrapper that re-exports the Commands page which already
 * implements the full chat-first layout (session list + thread + evidence
 * drawer). The route `/chat` is now the canonical entry point; `/commands`
 * continues to work for backward compatibility.
 *
 * New chat components live in `components/chat/`:
 *   - ChatInput: Mode-selector input with keyboard shortcuts
 *   - ActionCard: Inline confirm/reject cards for pending actions
 *   - WorkflowTimeline: Agent activity step visualization
 */

export { default } from './Commands'
