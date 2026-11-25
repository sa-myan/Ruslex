<script lang="ts">
  import { onDestroy } from 'svelte';
  import { request } from '../lib/http';
  import { errorMessage, isAbortError } from '../lib/errors';
  import type { EntryReference, Page, Summary } from '../lib/types';

  interface Props {
    selected?: EntryReference | null;
    onSelect: (item: EntryReference | null) => void;
  }

  let { selected = null, onSelect }: Props = $props();

  let query = $state('');
  let options = $state<Summary[]>([]);
  let busy = $state(false);
  let error = $state('');

  let debounceTimer: ReturnType<typeof setTimeout> | undefined;
  let activeRequest: AbortController | undefined;
  let requestVersion = 0;

  function cancelPendingSearch(): void {
    clearTimeout(debounceTimer);
    activeRequest?.abort();
    activeRequest = undefined;
    requestVersion += 1;
  }

  function scheduleSearch(): void {
    cancelPendingSearch();
    error = '';
    options = [];

    if (!query.trim()) {
      busy = false;
      return;
    }

    debounceTimer = setTimeout(() => void search(), 220);
  }

  async function search(): Promise<void> {
    const version = ++requestVersion;
    const controller = new AbortController();
    activeRequest = controller;
    busy = true;

    try {
      const params = new URLSearchParams({ q: query.trim(), page_size: '12' });
      const page = await request<Page<Summary>>(`/api/lexemes?${params}`, {
        signal: controller.signal,
      });
      if (version === requestVersion) options = page.items;
    } catch (err) {
      if (version === requestVersion && !isAbortError(err)) {
        error = errorMessage(err);
      }
    } finally {
      if (version === requestVersion) busy = false;
    }
  }

  function choose(item: EntryReference | null): void {
    cancelPendingSearch();
    busy = false;
    options = [];
    query = '';
    onSelect(item);
  }

  onDestroy(cancelPendingSearch);
</script>

{#if selected}
  <div class="flex items-center gap-2">
    <strong class="russian">{selected.stressed_lemma ?? selected.lemma}</strong>
    <span class="badge badge-sm">{selected.pos}</span>
    <button type="button" class="btn btn-xs btn-ghost" onclick={() => choose(null)}>
      Change ×
    </button>
  </div>
{:else}
  <input
    class="input input-bordered w-full"
    placeholder="Find another Russian entry…"
    aria-label="Search for a related entry"
    bind:value={query}
    oninput={scheduleSearch}
  />
  {#if busy}<span class="loading loading-spinner loading-xs" aria-label="Searching"></span>{/if}
  {#if error}<p class="text-error text-sm" role="alert">{error}</p>{/if}
  <div class="max-h-44 overflow-y-auto">
    {#each options as result (result.id)}
      <button
        type="button"
        class="block p-2 w-full text-left hover:bg-base-200"
        onclick={() => choose(result)}
      >
        <span class="russian font-semibold">{result.stressed_lemma ?? result.lemma}</span>
        <small>{result.pos} · {result.gloss_preview}</small>
      </button>
    {/each}
  </div>
{/if}
