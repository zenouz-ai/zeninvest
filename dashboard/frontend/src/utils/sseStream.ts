/**
 * Incremental SSE parsing: append bytes, drain complete `\\n\\n`-terminated blocks.
 */
export function drainSseBuffer(
  buffer: string,
  chunk: string
): { buffer: string; dataJsonStrings: string[] } {
  let buf = buffer + chunk
  const dataJsonStrings: string[] = []
  while (true) {
    const sep = buf.indexOf('\n\n')
    if (sep === -1) break
    const block = buf.slice(0, sep)
    buf = buf.slice(sep + 2)
    const jsonStr = extractDataPayload(block)
    if (jsonStr !== null) dataJsonStrings.push(jsonStr)
  }
  return { buffer: buf, dataJsonStrings }
}

/** Extract JSON string from one SSE event block (handles `data: ` lines, ignores comments). */
export function extractDataPayload(block: string): string | null {
  const lines = block.split('\n')
  const parts: string[] = []
  for (const line of lines) {
    if (line.startsWith(':')) continue
    if (line.startsWith('data:')) {
      parts.push(line.slice(5).replace(/^\s/, ''))
    }
  }
  if (parts.length === 0) return null
  return parts.join('\n')
}

/** Exponential backoff with jitter; capped at maxMs. */
export function reconnectDelayMs(attempt: number, baseMs = 1000, maxMs = 30_000): number {
  const raw = Math.min(maxMs, baseMs * 2 ** attempt)
  const jitter = raw * 0.25 * Math.random()
  return Math.min(maxMs, Math.floor(raw * 0.75 + jitter))
}
