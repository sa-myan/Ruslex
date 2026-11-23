import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request, mutate } from '../src/lib/http';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Django API transport', () => {
  it('returns JSON on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 3 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })));
    await expect(request<{ id: number }>('/api/lexemes/3')).resolves.toEqual({ id: 3 });
  });

  it('preserves HTTP status and server validation errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Invalid sense' }), {
      status: 400,
      headers: { 'content-type': 'application/json' },
    })));
    await expect(request('/api/senses')).rejects.toEqual(new ApiError('Invalid sense', 400));
  });

  it('sends JSON and a CSRF header for writes', async () => {
    vi.stubGlobal('document', { cookie: 'csrftoken=test-token' });
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', {
      headers: { 'content-type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await mutate('/api/lexemes/4', 'PATCH', { notes: 'hello' });
    const options = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(options.headers);
    expect(headers.get('X-CSRFToken')).toBe('test-token');
    expect(options.body).toBe(JSON.stringify({ notes: 'hello' }));
  });
});
