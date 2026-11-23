<script lang="ts">
  import { onMount } from 'svelte';
  import { request } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { errorMessage } from '../lib/errors';
  import type { Entry, Page, RefPage, Source } from '../lib/types';

  interface Props {
    wordId: number;
  }

  let { wordId }: Props = $props();

  let entry = $state<Entry | null>(null);
  let pages = $state<Page<RefPage> | null>(null);
  let sources = $state<Page<Source> | null>(null);
  let pageNumber = $state(1);
  let sourcePageNumber = $state(1);
  let selected = $state<RefPage | null>(null);
  let error = $state('');
  let sourceSequence = 0;
  let pageSequence = 0;

  onMount(() => {
    void loadEntry();
    void loadPages();
    void loadSources();
  });

  async function loadEntry(): Promise<void> {
    try {
      entry = await request<Entry>(`/api/lexemes/${wordId}`);
    } catch (err) {
      error = errorMessage(err);
    }
  }

  async function loadPages(): Promise<void> {
    const version = ++pageSequence;
    try {
      const result = await request<Page<RefPage>>(
        `/api/lexemes/${wordId}/reference-pages?page=${pageNumber}&page_size=40`,
      );
      if (version === pageSequence) pages = result;
    } catch (err) {
      if (version === pageSequence) error = errorMessage(err);
    }
  }

  async function loadSources(): Promise<void> {
    const version = ++sourceSequence;
    const params = new URLSearchParams({ page: String(sourcePageNumber), page_size: '40' });
    if (selected) {
      params.set('book_id', String(selected.book_id));
      params.set('pdf_page', String(selected.pdf_page));
    }
    try {
      const result = await request<Page<Source>>(`/api/lexemes/${wordId}/references?${params}`);
      if (version === sourceSequence) sources = result;
    } catch (err) {
      if (version === sourceSequence) error = errorMessage(err);
    }
  }

  function choose(page: RefPage | null): void {
    selected = selected?.page_id === page?.page_id ? null : page;
    sourcePageNumber = 1;
    void loadSources();
  }
</script>

<button class="btn btn-ghost btn-sm mb-5" onclick={() => navigate(`/word/${wordId}`)}>← Entry</button>
<p class="kicker">Source evidence</p>
<h2 class="text-3xl font-bold mt-2 mb-2">References</h2>
{#if entry}
  <p class="mb-6 opacity-65">
    <strong class="russian">{entry.lemma}</strong> · {entry.sources_total} references on
    {entry.source_page_count} pages
  </p>
{/if}
{#if error}<div class="alert alert-error" role="alert">{error}</div>{/if}

<div class="grid md:grid-cols-[minmax(200px,320px)_1fr] gap-5 items-start">
  <section class="surface p-5">
    <h3 class="font-bold mb-3">Pages</h3>
    {#if selected}
      <button class="btn btn-ghost btn-sm" onclick={() => choose(null)}>Clear filter ×</button>
    {/if}
    {#each pages?.items ?? [] as page (page.page_id)}
      <button
        class={`block w-full text-left border-b border-base-300 p-3 hover:bg-base-200 ${selected?.page_id === page.page_id ? 'bg-primary/10' : ''}`}
        onclick={() => choose(page)}
      >
        <strong class="block">{page.title}</strong>
        <small>PDF {page.pdf_page} · printed {page.printed_page}</small>
        <small class="block opacity-50">{page.occurrence_count} occurrences</small>
      </button>
    {/each}
    {#if pages && pages.pages > 1}
      <div class="flex gap-2 mt-4 items-center">
        <button class="btn btn-xs" disabled={pageNumber <= 1} onclick={() => { pageNumber--; void loadPages(); }}>←</button>
        {pageNumber}/{pages.pages}
        <button class="btn btn-xs" disabled={pageNumber >= pages.pages} onclick={() => { pageNumber++; void loadPages(); }}>→</button>
      </div>
    {/if}
  </section>
  <section class="surface p-5">
    <h3 class="font-bold mb-3">Occurrences ({sources?.total ?? 0})</h3>
    {#each sources?.items ?? [] as item}
      <div class="py-4 border-b border-base-300">
        <small class="opacity-60">
          {item.title} · PDF {item.pdf_page} · printed {item.printed_page} · {item.surface} × {item.count}
        </small>
        <p class="russian mt-2">{item.context}</p>
      </div>
    {/each}
    {#if sources && sources.pages > 1}
      <div class="flex gap-2 mt-4 items-center">
        <button class="btn btn-sm" disabled={sourcePageNumber <= 1} onclick={() => { sourcePageNumber--; void loadSources(); }}>
          ← Previous
        </button>
        {sourcePageNumber}/{sources.pages}
        <button class="btn btn-sm" disabled={sourcePageNumber >= sources.pages} onclick={() => { sourcePageNumber++; void loadSources(); }}>
          Next →
        </button>
      </div>
    {/if}
  </section>
</div>
