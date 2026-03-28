import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it } from 'vitest'
import Chat from './Chat'

function renderChat(initialEntry = '/chat'): string {
  return renderToStaticMarkup(
    <StaticRouter location={initialEntry}>
      <Chat />
    </StaticRouter>
  )
}

describe('Chat page', () => {
  it('renders the canonical dashboard chat surface', () => {
    const markup = renderChat('/chat')

    expect(markup).toContain('Chat')
    expect(markup).toContain('canonical dashboard surface')
    expect(markup).toContain('Conversation Console')
    expect(markup).toContain('Legacy Slack Audit')
  })
})
