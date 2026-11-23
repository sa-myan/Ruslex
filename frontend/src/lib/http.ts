/** HTTP transport for the same-origin Django API. No UI state belongs here. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function csrfToken(): string {
  const cookie = document.cookie
    .split('; ')
    .find((part) => part.startsWith('csrftoken='));

  return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : '';
}

function responseMessage(body: unknown, status: number): string {
  if (typeof body === 'object' && body !== null) {
    const details = body as { detail?: unknown; error?: unknown; message?: unknown };
    for (const value of [details.detail, details.error, details.message]) {
      if (typeof value === 'string' && value.trim()) return value;
    }
  }
  return `HTTP ${status}`;
}

export async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const headers = new Headers(options.headers);

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('X-CSRFToken', csrfToken());
    if (options.body !== undefined && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'same-origin',
  });

  const contentType = response.headers.get('content-type') ?? '';
  const body: unknown = contentType.includes('json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new ApiError(responseMessage(body, response.status), response.status);
  }
  return body as T;
}

export function mutate<T>(
  url: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  return request<T>(url, {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
