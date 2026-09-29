import type { Answer, DocumentInfo, Health } from './types'

export class ApiError extends Error {
  requestId: string | undefined
  constructor(message: string, requestId?: string) {
    super(message)
    this.requestId = requestId
  }
}

async function json<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, options)
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new ApiError('Could not reach the backend. Make sure it is running, then retry.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok || !data) {
    throw new ApiError(data?.error?.message ?? 'The request could not be completed. Please retry.', data?.request_id)
  }
  return data as T
}

export const getHealth = () => json<Health>('/api/health')
export const getDocument = () => json<DocumentInfo>('/api/document')
export const ask = (query: string, signal: AbortSignal) => json<Answer>('/api/chat', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query }), signal,
})
