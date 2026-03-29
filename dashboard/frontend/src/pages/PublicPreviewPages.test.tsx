import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it } from 'vitest'
import PublicChat from './PublicChat'
import PublicEvolution from './PublicEvolution'
import PublicOrderManagement from './PublicOrderManagement'

function renderPage(path: string, node: ReactElement) {
  return renderToStaticMarkup(
    <StaticRouter location={path}>
      {node}
    </StaticRouter>
  )
}

describe('public preview pages', () => {
  it('renders preview-only surfaces for private product tabs', () => {
    const ordersMarkup = renderPage('/orders', <PublicOrderManagement />)
    const chatMarkup = renderPage('/chat', <PublicChat />)
    const evolutionMarkup = renderPage('/evolution', <PublicEvolution />)

    expect(ordersMarkup).toContain('Preview Only')
    expect(ordersMarkup).toContain('Operator sign in')
    expect(chatMarkup).toContain('Disabled')
    expect(chatMarkup).toContain('Operator sign-in required')
    expect(evolutionMarkup).toContain('Build Locked')
    expect(evolutionMarkup).toContain('Deploy Locked')
  })
})
