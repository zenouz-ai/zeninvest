/** Dashboard API key — same resolution as axios client (US-7.1). */

const buildTimeKey: string = import.meta.env.VITE_API_KEY ?? ''

export function getDashboardApiKey(): string {
  if (buildTimeKey) return buildTimeKey
  try {
    return localStorage.getItem('dashboard_api_key') ?? ''
  } catch {
    return ''
  }
}
