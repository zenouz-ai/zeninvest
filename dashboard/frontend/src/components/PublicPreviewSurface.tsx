import type { ReactNode } from 'react'
import { PageBrandHeader } from './PageBrandHeader'
import { PublicPageBanner } from './PublicPageBanner'

export function PublicPreviewSurface({
  title,
  description,
  body,
  children,
}: {
  title: string
  description: string
  body: string
  children?: ReactNode
}) {
  return (
    <div className="space-y-6">
      <PageBrandHeader eyebrow="PUBLIC DEMO" title={title} description={description} />
      <PublicPageBanner
        mode="preview"
        message={body}
      />
      {children}
    </div>
  )
}
