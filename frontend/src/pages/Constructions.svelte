<script lang="ts">
  import { onMount } from 'svelte';
  import { request, mutate } from '../lib/http';
  import { reviewMode } from '../lib/session';
  import { navigate } from '../lib/navigation';
  import { errorMessage } from '../lib/errors';
  import type { ConstructionPage, Construction, Status } from '../lib/types';

  let data = $state<ConstructionPage | null>(null);
  let q = $state('');
  let status = $state('visible');
  let page = $state(1);
  let busy = $state(false);
  let error = $state('');
  let seq = 0;
  onMount(() => { void load(); });

  async function load(): Promise<void> {
    const version = ++seq;
    busy = true;
    error = '';
    try {
      const params = new URLSearchParams({ q, status, page: String(page), page_size: '20' });
      const result = await request<ConstructionPage>(`/api/constructions?${params}`);
      if (version === seq) data = result;
    } catch (err) { if (version === seq) error = errorMessage(err); }
    finally { if (version === seq) busy = false; }
  }
  function filter(): void { page = 1; void load(); }
  function go(delta: number): void { page += delta; void load(); }

  async function review(item: Construction, next: Status): Promise<void> {
    if (busy) return;
    busy = true; error = '';
    try {
      await mutate(`/api/constructions/${item.id}/status`, 'PATCH', { human_status: next });
      await load();
    } catch (err) { error = errorMessage(err); }
    finally { busy = false; }
  }
</script>

<div class="mb-6">
  <p class="kicker">Language reference</p>
  <h2 class="text-3xl font-bold">Constructions</h2>
  <p class="opacity-65 mt-2">Productive patterns, separate from fixed lexical expressions.</p>
</div>
<section class="surface p-5 mb-5">
  <form class="flex flex-wrap gap-3 items-end" onsubmit={(event) => { event.preventDefault(); filter(); }}>
    <label class="field flex-1 min-w-52">
      <span>Find pattern or meaning</span>
      <input type="search" class="input input-bordered w-full" bind:value={q} maxlength="150" />
    </label>
    {#if $reviewMode}
      <label class="field">
        <span>Review status</span>
        <select bind:value={status} onchange={filter}>
          <option value="visible">Visible</option>
          <option value="all">All</option>
          <option value="followup">Follow-up</option>
          <option value="kept">Kept</option>
          <option value="hidden">Hidden</option>
        </select>
      </label>
    {/if}
    <button class="btn btn-primary" type="submit" disabled={busy}>Search</button>
  </form>
</section>
{#if error}<div class="alert alert-error mb-4" role="alert">{error}</div>{/if}
{#if busy}<span class="loading loading-spinner" aria-label="Loading constructions"></span>{/if}
{#if data && !data.installed}
  <p class="surface p-5">Construction storage has not yet been initialized.</p>
{:else if data && !data.total}
  <p class="surface p-5">No matching constructions. The historical scan can propose entries for review.</p>
{:else if data}
  <p class="text-sm opacity-60 mb-3">{data.total} constructions</p>
  {#each data.items as item (item.id)}
    <article class="surface p-5 mb-4 space-y-3">
      <div class="flex justify-between items-start gap-3">
        <h3 class="russian text-xl font-bold">{item.pattern}</h3>
        {#if $reviewMode}<span class="badge badge-outline">{item.human_status}</span>{/if}
      </div>
      <p>{item.meaning}</p>
      {#if item.grammar}<p class="text-sm opacity-75">{item.grammar}</p>{/if}
      {#each item.examples as example}
        <blockquote class="border-l-2 border-primary pl-3">
          <p class="russian">{example.russian}</p>
          <p class="text-sm opacity-70">{example.english}</p>
        </blockquote>
      {/each}
      {#if item.sources.length || item.expressions.length}
        <details>
          <summary class="cursor-pointer text-sm">Source evidence and related expressions</summary>
          {#each item.sources as source}
            <p class="text-sm border-t border-base-300 py-2"><strong>{source.title}, PDF {source.pdf_page}</strong> — <span class="russian">{source.surface}</span></p>
          {/each}
          {#each item.expressions as expression}
            <button class="link link-primary block text-sm my-2" onclick={() => navigate(`/word/${expression.id}`)}>Related expression: {expression.lemma}</button>
          {/each}
        </details>
      {/if}
      {#if $reviewMode}
        <div class="flex flex-wrap gap-2 pt-2">
          <button class="btn btn-success btn-sm" disabled={busy} onclick={() => review(item, 'kept')}>Keep</button>
          <button class="btn btn-outline btn-sm" disabled={busy} onclick={() => review(item, 'followup')}>Review later</button>
          <button class="btn btn-error btn-outline btn-sm" disabled={busy} onclick={() => review(item, 'hidden')}>Hide</button>
        </div>
      {/if}
    </article>
  {/each}
  <div class="flex gap-3 items-center">
    <button class="btn btn-outline btn-sm" disabled={busy || page <= 1} onclick={() => go(-1)}>Previous</button>
    <span class="text-sm">Page {data.page} of {data.pages}</span>
    <button class="btn btn-outline btn-sm" disabled={busy || page >= data.pages} onclick={() => go(1)}>Next</button>
  </div>
{/if}
