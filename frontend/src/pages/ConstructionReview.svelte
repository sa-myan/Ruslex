<script lang="ts">
  import { onMount } from 'svelte';
  import { request, mutate } from '../lib/http';
  import { errorMessage } from '../lib/errors';
  import { navigate } from '../lib/navigation';
  import type { ConstructionReviewNext, Status } from '../lib/types';

  type Queue = 'pending' | 'deferred' | 'all';
  let queue = $state<Queue>('pending');
  let after = $state(0);
  let result = $state<ConstructionReviewNext | null>(null);
  let note = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let sequence = 0;

  onMount(() => { void load(); });

  async function load(): Promise<void> {
    const current = ++sequence;
    busy = true;
    error = '';
    try {
      const value = await request<ConstructionReviewNext>(
        `/api/construction-review/next?queue=${queue}&after=${after}`,
      );
      if (current === sequence) {
        result = value;
        note = value.item?.notes ?? '';
      }
    } catch (err) { if (current === sequence) error = errorMessage(err); }
    finally { if (current === sequence) busy = false; }
  }

  function switchQueue(value: Queue): void {
    queue = value;
    after = 0;
    result = null;
    notice = '';
    void load();
  }

  async function decide(status: Status): Promise<void> {
    const id = result?.item?.id;
    if (!id || busy) return;
    busy = true;
    error = '';
    try {
      await mutate(`/api/constructions/${id}/status`, 'PATCH', {
        human_status: status, notes: note,
      });
      after = id;
      notice = status === 'kept' ? 'Construction approved' :
        status === 'hidden' ? 'Proposal rejected (recoverable)' :
        'Proposal deferred';
      await load();
    } catch (err) { error = errorMessage(err); }
    finally { busy = false; }
  }

  function skip(): void {
    const id = result?.item?.id;
    if (!id) return;
    after = id;
    void load();
  }
</script>

<div class="mb-5">
  <p class="kicker">Review workflow</p>
  <h2 class="text-3xl font-bold">Construction review</h2>
  <p class="text-sm opacity-70 mt-2">
    AI proposals stay private until you explicitly keep them. Rejecting a proposal
    hides it without deleting its evidence, and deferral preserves it for later.
  </p>
</div>

<section class="surface p-4 sm:p-5">
  <div class="flex flex-wrap items-end justify-between gap-3 mb-5">
    <label class="field">
      <span>Review queue</span>
      <select class="select select-bordered" value={queue}
        onchange={(event) => switchQueue(event.currentTarget.value as Queue)}>
        <option value="pending">Pending</option>
        <option value="deferred">Deferred</option>
        <option value="all">All unresolved</option>
      </select>
    </label>
    <span class="badge badge-outline">{result?.total ?? '—'} remaining</span>
  </div>
  {#if notice}<p class="text-success text-sm mb-3" role="status">{notice}</p>{/if}
  {#if error}<p class="text-error text-sm mb-3" role="alert">{error}</p>{/if}
  {#if busy}<div class="loading loading-spinner mb-4" aria-label="Loading construction review"></div>{/if}
  {#if result && !result.installed}
    <p class="opacity-70">Construction storage has not been initialized. Stage your completed scan first.</p>
  {:else if result?.item}
    {@const item = result.item}
    <div class="space-y-4">
      <h3 class="russian text-2xl font-bold">{item.pattern}</h3>
      <p>{item.meaning}</p>
      {#if item.grammar}
        <div>
          <h4 class="font-semibold mb-1">Grammar and restrictions</h4>
          <p class="text-sm">{item.grammar}</p>
        </div>
      {/if}
      {#if item.examples.length}
        <div>
          <h4 class="font-semibold mb-2">Example</h4>
          {#each item.examples as example}
            <blockquote class="border-l-2 border-primary pl-3 my-2">
              <p class="russian">{example.russian}</p>
              <p class="text-sm opacity-75">{example.english}</p>
            </blockquote>
          {/each}
        </div>
      {/if}
      {#if item.sources.length || item.expressions.length}
        <div>
          <h4 class="font-semibold mb-2">Original evidence</h4>
          {#each item.sources as source}
            <div class="border-t border-base-300 py-2">
              <small class="opacity-65">{source.title} · PDF {source.pdf_page} · printed {source.printed_page}</small>
              <p class="russian">{source.surface}</p>
            </div>
          {/each}
          {#each item.expressions as expression}
            <button class="link link-primary block text-sm my-2"
              onclick={() => navigate(`/word/${expression.id}`)}>
              Related expression: {expression.lemma}
            </button>
          {/each}
        </div>
      {/if}
      <label class="field">
        <span>Review note (optional)</span>
        <textarea class="textarea textarea-bordered w-full" rows="2"
          maxlength="1000" bind:value={note}
          placeholder="e.g. ordinary expression, check the full page, duplicate pattern"></textarea>
      </label>
      <div class="flex flex-wrap gap-2 pt-2">
        <button class="btn btn-success btn-sm" disabled={busy}
          onclick={() => decide('kept')}>Keep</button>
        <button class="btn btn-error btn-outline btn-sm" disabled={busy}
          onclick={() => decide('hidden')}>Reject</button>
        <button class="btn btn-outline btn-sm" disabled={busy}
          onclick={() => decide('followup')}>Defer</button>
        <button class="btn btn-ghost btn-sm" disabled={busy}
          onclick={skip}>Skip / next →</button>
      </div>
    </div>
  {:else if result && !busy}
    <p class="py-8 text-center opacity-70">No constructions remain in this queue.</p>
  {/if}
  <button class="link link-primary block text-sm mt-5"
    onclick={() => navigate('/constructions')}>Browse constructions and revisit decisions</button>
</section>
