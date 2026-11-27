let csrfToken: string | null = null

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

async function ensureCsrf() {
  if (!csrfToken) {
    const response = await fetch('/api/csrf', { credentials: 'include' })
    if (!response.ok) throw new Error('Could not initialize the API session')
    const data = await response.json() as { csrfToken: string }
    csrfToken = data.csrfToken
  }
  return csrfToken
}

async function readResponse(response: Response) {
  const data = await response.json().catch(() => ({ error: 'Unexpected server response' }))
  if (!response.ok) throw new ApiError(data.error || 'Request failed', response.status)
  return data
}

export const api = {
  async get<T>(path: string): Promise<T> {
    const response = await fetch(path, { credentials: 'include' })
    return readResponse(response) as Promise<T>
  },
  async post<T = unknown>(path: string, body: Record<string, unknown> = {}): Promise<T> {
    const token = await ensureCsrf()
    const response = await fetch(path, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: JSON.stringify(body),
    })
    return readResponse(response) as Promise<T>
  },
  async patch<T = unknown>(path: string, body: Record<string, unknown>): Promise<T> {
    const token = await ensureCsrf()
    const response = await fetch(path, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: JSON.stringify(body),
    })
    return readResponse(response) as Promise<T>
  },
  async resetCsrf() {
    csrfToken = null
    await ensureCsrf()
  },
  setCsrfToken(token: string) {
    csrfToken = token
  },
}
