<script lang="ts">
  import { onMount } from 'svelte';
  import { mutate, request } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { reviewMode } from '../lib/session';
  import { errorMessage } from '../lib/errors';
  import type { ReviewNext, Status } from '../lib/types';

  const actions: Status[] = ['kept', 'followup', 'hidden', 'unreviewed'];
  const filters = ['unreviewed', 'followup', 'kept', 'hidden', 'all'];

  let filter = $state('unreviewed');
  let after = $state(0);
  let batch = $state<ReviewNext | null>(null);
  let busy = $state(false);
  let error = $state('');
  let sequence = 0;

  onMount(() => { void load(); });

  async function load(): Promise<void> {
    const version = ++sequence;
    busy = true;
    error = '';
    try {
      const data = await request<ReviewNext>(`/api/review/next?filter=${filter}&after=${after}`);
      if (version === sequence) batch = data;
    } catch (err) {
      if (version === sequence) error = errorMessage(err);
    } finally {
      if (version === sequence) busy = false;
    }
  }

  function changeFilter(): void {
    after = 0;
    batch = null;
    void load();
  }

  async function choose(status: Status): Promise<void> {
    const wordId = batch?.word?.id;
    if (!wordId || busy) return;
    busy = true;
    error = '';
    try {
      await mutate(`/api/lexemes/${wordId}`, 'PATCH', { human_status: status });
      after = wordId;
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  function openEntry(): void {
    const wordId = batch?.word?.id;
    if (wordId) navigate(`/word/${wordId}`);
  }

  function skip(): void {
    const wordId = batch?.word?.id;
    if (!wordId) return;
    after = wordId;
    void load();
  }
</script>

{#if $reviewMode}
  <div class="mb-6">
    <p class="kicker">Review workflow</p>
    <h2 class="text-3xl font-bold">Fast review</h2>
  </div>
  <section class="surface p-5">
    <div class="flex flex-wrap items-center justify-between gap-2 mb-5">
      <label class="field">
        <span>Review queue</span>
        <select bind:value={filter} onchange={changeFilter}>
          {#each filters as option}<option value={option}>{option}</option>{/each}
        </select>
      </label>
      <span class="badge badge-outline">{batch?.total ?? '—'} total</span>
    </div>
    {#if busy}<div class="loading loading-spinner"></div>{/if}
    {#if error}<div class="alert alert-error" role="alert">{error}</div>{/if}
    {#if batch?.word}
      <h3 class="russian text-3xl font-bold">
        {batch.word.lemma} <span class="text-base opacity-50">{batch.word.pos}</span>
      </h3>
      <button class="link link-primary my-3" onclick={openEntry}>
        Open complete entry ↗
      </button>
      <div class="flex flex-wrap gap-2 my-5">
        {#each actions as action}
          <button
            class={`btn ${action === 'kept' ? 'btn-success' : action === 'hidden' ? 'btn-error' : 'btn-outline'}`}
            disabled={busy}
            onclick={() => choose(action)}
          >{action}</button>
        {/each}
        <button class="btn btn-ghost" disabled={busy} onclick={skip}>Skip →</button>
      </div>
      {#each batch.sources as source}
        <div class="border-t border-base-300 py-2">
          <small class="opacity-55">{source.title} · PDF {source.pdf_page}</small>
          <p class="russian">{source.context}</p>
        </div>
      {/each}
    {:else if batch}
      <div class="p-8 text-center">No words remain in this queue.</div>
    {/if}
  </section>
{/if}
