<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { request } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { editMode, reviewMode } from '../lib/session';
  import { errorMessage, isAbortError } from '../lib/errors';
  import { effectiveReviewStatus } from '../lib/searchFilters';
  import type { Book, Metadata, Page, Summary, Tag } from '../lib/types';

  const statuses = ['visible', 'all', 'unreviewed', 'kept', 'followup', 'hidden'];
  const tagCategories = ['grammatical', 'semantic', 'usage'];

  let query = $state(new URLSearchParams(window.location.search).get('q') ?? '');
  let status = $state('visible');
  let page = $state(1);
  let pos = $state('');
  let kind = $state('');
  let bookId = $state('');
  let pageFrom = $state('');
  let pageTo = $state('');
  let pageKind = $state('pdf');
  let selectedTags = $state<number[]>([]);

  let tags = $state<Tag[]>([]);
  let books = $state<Book[]>([]);
  let metadata = $state<Metadata | null>(null);
  let results = $state<Page<Summary> | null>(null);
  let busy = $state(false);
  let error = $state('');
  let advanced = $state(false);

  let debounceTimer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let requestVersion = 0;

  onMount(() => {
    void loadMetadata();
    void load();
  });
  onDestroy(() => {
    clearTimeout(debounceTimer);
    controller?.abort();
  });

  async function loadMetadata(): Promise<void> {
    try {
      [tags, books, metadata] = await Promise.all([
        request<Tag[]>('/api/tags'),
        request<Book[]>('/api/books'),
        request<Metadata>('/api/meta'),
      ]);
    } catch (err) {
      error = errorMessage(err);
    }
  }

  function schedule(): void {
    page = 1;
    results = null;
    controller?.abort();
    requestVersion += 1;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => void load(), 250);
  }

  function searchParameters(): URLSearchParams {
    const params = new URLSearchParams({
      q: query,
      status: effectiveReviewStatus($reviewMode, status),
      page: String(page),
      page_size: '40',
    });

    if (pos) params.set('pos', pos);
    if (kind) params.set('entry_type', kind);
    if (bookId) params.set('book_id', bookId);
    if (pageFrom) params.set(`${pageKind}_page_min`, pageFrom);
    if (pageTo) params.set(`${pageKind}_page_max`, pageTo);
    for (const tagId of selectedTags) params.append('tag_id', String(tagId));

    return params;
  }

  async function load(): Promise<void> {
    controller?.abort();
    const version = ++requestVersion;
    const nextController = new AbortController();
    controller = nextController;
    busy = true;
    error = '';

    if (pageFrom && pageTo && Number(pageFrom) > Number(pageTo)) {
      error = 'First page must not be greater than the last';
      busy = false;
      return;
    }

    try {
      const value = await request<Page<Summary>>(`/api/lexemes?${searchParameters()}`, {
        signal: nextController.signal,
      });
      if (version !== requestVersion) return;

      results = value;
      const url = new URL(window.location.href);
      if (query) url.searchParams.set('q', query);
      else url.searchParams.delete('q');
      window.history.replaceState({}, '', url.pathname + url.search);
    } catch (err) {
      if (version === requestVersion && !isAbortError(err)) error = errorMessage(err);
    } finally {
      if (version === requestVersion) busy = false;
    }
  }

  function changeMode(): void {
    status = 'visible';
    page = 1;
    results = null;
    void load();
  }

  // Hidden entries are never requested when Review Mode is disabled.
  $effect(() => {
    if (!$reviewMode && status !== 'visible') {
      // Run the reset without subscribing to its incidental synchronous reads.
      untrack(changeMode);
    }
  });

  function toggleTag(id: number): void {
    selectedTags = selectedTags.includes(id)
      ? selectedTags.filter((selected) => selected !== id)
      : [...selectedTags, id];
    schedule();
  }
</script>

<div class="mb-7">
  <p class="kicker">Dictionary</p>
  <h2 class="text-3xl md:text-4xl font-bold mt-2">
    Russian vocabulary<span class="text-primary">.</span>
  </h2>
  <p class="opacity-60 mt-2">Find words, expressions, meanings and textbook references.</p>
</div>

<section class="surface p-5 mb-6 space-y-4">
  <input
    type="search"
    class="input input-lg input-bordered w-full"
    aria-label="Search Russian or English"
    placeholder="Search Russian or English…"
    bind:value={query}
    oninput={schedule}
  />
  {#if $reviewMode}
    <div class="flex flex-wrap items-center gap-2 text-sm">
      <span class="meta-label mr-2">Review status</span>
      {#each statuses as option}
        <button
          class={`btn btn-sm ${status === option ? 'btn-primary' : 'btn-ghost'}`}
          onclick={() => { status = option; schedule(); }}
        >{option}</button>
      {/each}
    </div>
  {/if}

  <button class="btn btn-sm btn-ghost" aria-expanded={advanced} onclick={() => { advanced = !advanced; }}>
    {advanced ? '▾' : '▸'} Filters: book, page, tags, grammar
  </button>
  {#if advanced}
    <div class="grid md:grid-cols-2 gap-4 pt-3 border-t border-base-300">
      <label class="field">
        <span>Book</span>
        <select class="select select-bordered" bind:value={bookId} onchange={schedule}>
          <option value="">Any book</option>
          {#each books as book}<option value={String(book.id)}>{book.title} {book.edition}</option>{/each}
        </select>
      </label>
      <label class="field">
        <span>Part of speech</span>
        <select bind:value={pos} onchange={schedule}>
          <option value="">Any</option>
          {#each metadata?.parts_of_speech ?? [] as part}
            <option value={part.code}>{part.label}</option>
          {/each}
        </select>
      </label>
      <label class="field">
        <span>Entry type</span>
        <select bind:value={kind} onchange={schedule}>
          <option value="">All</option>
          <option value="word">Words</option>
          <option value="expression">Expressions</option>
          <option value="abbreviation">Abbreviations</option>
        </select>
      </label>
      <label class="field">
        <span>Page numbering</span>
        <select bind:value={pageKind} onchange={schedule}>
          <option value="pdf">PDF page</option>
          <option value="printed">Printed page</option>
        </select>
      </label>
      <label class="field">
        <span>From page</span>
        <input type="text" inputmode="numeric" bind:value={pageFrom} oninput={schedule} />
      </label>
      <label class="field">
        <span>To page</span>
        <input type="text" inputmode="numeric" bind:value={pageTo} oninput={schedule} />
      </label>
    </div>

    {#each tagCategories as category}
      <div class="pt-3 border-t border-base-300">
        <p class="meta-label mb-2">{category} tags</p>
        <div class="flex flex-wrap gap-2">
          {#each tags.filter((tag) => tag.category === category) as tag}
            <button
              class={`badge cursor-pointer ${selectedTags.includes(tag.id) ? 'badge-primary' : 'badge-outline'}`}
              onclick={() => toggleTag(tag.id)}
            >{tag.name} · {tag.word_count}</button>
          {/each}
        </div>
      </div>
    {/each}
    <p class="text-xs opacity-55">Selected tags must all belong to one active sense.</p>
  {/if}
</section>

<div class="flex justify-between items-center mb-3">
  <h3 class="text-lg font-semibold">
    Entries <span class="text-base-content/50">{results?.total ?? '—'}</span>
  </h3>
  <span class="text-xs opacity-60">
    {busy ? 'Searching…' : query ? 'Relevance order' : 'Original entry order'}
  </span>
</div>

{#if error}
  <div class="alert alert-error mb-4" role="alert">
    {error}
    <button class="btn btn-sm" onclick={() => load()}>Retry</button>
  </div>
{/if}

<section class="surface divide-y divide-base-300">
  {#if !results && busy}
    <div class="p-8 text-center"><span class="loading loading-spinner"></span></div>
  {/if}
  {#if results?.items.length === 0}
    <div class="p-10 text-center opacity-70">No matching entries.</div>
  {/if}
  {#each results?.items ?? [] as word (word.id)}
    <a
      href={`/word/${word.id}`}
      class="block p-4 md:p-5 hover:bg-base-200/50 transition-colors"
      onclick={(event) => { event.preventDefault(); navigate(`/word/${word.id}`); }}
    >
      <div class="flex gap-3 items-center flex-wrap">
        <strong class="russian text-xl">{word.stressed_lemma ?? word.lemma}</strong>
        <span class="badge badge-ghost">{word.pos}</span>
        {#if word.entry_type === "abbreviation"}<span class="badge badge-outline">Abbreviation</span>{/if}
        {#if word.aspect}<span class="badge badge-outline">{word.aspect}</span>{/if}
        {#if $reviewMode}<span class="badge badge-warning">{word.human_status}</span>{/if}
      </div>
      <p class="text-sm opacity-75 mt-1">{word.gloss_preview || 'No sense recorded'}</p>
      <div class="flex gap-2 flex-wrap mt-2">
        {#each word.tags.slice(0, 5) as tag}
          <span class="badge badge-sm badge-outline">{tag.name}</span>
        {/each}
        <span class="text-xs opacity-50">{word.page_count} pages</span>
      </div>
    </a>
  {/each}
</section>

{#if results && results.pages > 1}
  <div class="join flex justify-center mt-5">
    <button class="btn join-item" disabled={page <= 1} onclick={() => { page--; void load(); }}>
      Previous
    </button>
    <button class="btn join-item btn-disabled">{page} / {results.pages}</button>
    <button class="btn join-item" disabled={page >= results.pages} onclick={() => { page++; void load(); }}>
      Next
    </button>
  </div>
{/if}
{#if $editMode}
  <button class="btn btn-primary mt-6" onclick={() => navigate('/new')}>+ Add entry</button>
{/if}
