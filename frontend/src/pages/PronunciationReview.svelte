<script lang="ts">
  import { onMount } from 'svelte';
  import { request, mutate } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { errorMessage } from '../lib/errors';
  import PronunciationEditor from '../components/entry/PronunciationEditor.svelte';
  import type { Entry } from '../lib/types';

  type Queue = 'pending' | 'deferred' | 'all';
  type Response = { entry: Entry | null; total: number; note: string; deferred: boolean };
  let queue = $state<Queue>('pending');
  let after = $state(0);
  let result = $state<Response | null>(null);
  let note = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let seq = 0;

  onMount(() => { void load(); });

  async function load(): Promise<void> {
    const current = ++seq;
    busy = true;
    error = '';
    try {
      const response = await request<Response>(
        `/api/pronunciation-review/next?queue=${encodeURIComponent(queue)}&after=${after}`,
      );
      if (current === seq) {
        result = response;
        note = response.note;
      }
    } catch (err) {
      if (current === seq) error = errorMessage(err);
    } finally {
      if (current === seq) busy = false;
    }
  }
  function selectQueue(value: Queue): void {
    queue = value;
    after = 0;
    result = null;
    notice = '';
    void load();
  }
  function next(): void {
    if (!result?.entry) return;
    after = result.entry.id;
    notice = '';
    void load();
  }
  async function refresh(): Promise<boolean> {
    const id = result?.entry?.id;
    if (!id) return false;
    try {
      const entry = await request<Entry>(`/api/lexemes/${id}`);
      if (result?.entry?.id === id) result = { ...result, entry };
      return true;
    } catch (err) {
      error = errorMessage(err);
      return false;
    }
  }
  async function saveDeferral(deferred: boolean): Promise<void> {
    const id = result?.entry?.id;
    if (!id || busy) return;
    busy = true;
    error = '';
    try {
      await mutate(`/api/pronunciation-review/${id}/defer`, 'PUT', {
        deferred, note: deferred ? note : '',
      });
      after = id;
      notice = deferred ? 'Deferred for later' : 'Returned to pending queue';
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }
  function saved(): void {
    const id = result?.entry?.id;
    if (!id) return;
    after = id;
    notice = 'Pronunciation saved';
    void load();
  }
</script>

<div class="mb-5">
  <p class="kicker">Pronunciation workflow</p>
  <h2 class="text-3xl font-bold">Stress and ё review</h2>
  <p class="text-sm opacity-70 mt-2">
    Entries without stored readings. Saving a reading removes it from this queue.
    Deferrals are separate from the dictionary's general review status.
  </p>
</div>

<section class="surface p-4 sm:p-5 mb-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <label class="field">
      <span>Queue</span>
      <select
        value={queue}
        onchange={(event) => selectQueue(event.currentTarget.value as Queue)}
      >
        <option value="pending">Pending</option>
        <option value="deferred">Deferred</option>
        <option value="all">All unresolved</option>
      </select>
    </label>
    <span class="badge badge-outline">{result?.total ?? '—'} entries</span>
  </div>
  {#if notice}<p class="text-success text-sm mt-3" role="status">{notice}</p>{/if}
  {#if error}<p class="text-error text-sm mt-3" role="alert">{error}</p>{/if}
  {#if busy}<div class="loading loading-spinner mt-4" aria-label="Loading pronunciation queue"></div>{/if}
  {#if result?.entry}
    {@const entry = result.entry}
    <div class="border-t border-base-300 mt-4 pt-5">
      <div class="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h3 class="russian text-3xl font-bold">{entry.stressed_lemma ?? entry.lemma}</h3>
          <p class="text-sm opacity-60">{entry.pos} · {entry.entry_type} · #{entry.id}</p>
        </div>
        <button type="button" class="btn btn-sm btn-outline"
          onclick={() => navigate(`/word/${entry.id}`)}>Complete entry</button>
      </div>

      {#if entry.senses.length}
        <div class="mt-4">
          <h4 class="font-semibold mb-1">Meanings</h4>
          {#each entry.senses.filter(sense => sense.active) as sense (sense.id)}
            <p class="text-sm my-1"><span class="opacity-60">#{sense.id}</span> {sense.meaning}</p>
          {/each}
        </div>
      {/if}
      {#if entry.sources.length}
        <div class="mt-4">
          <h4 class="font-semibold mb-2">Textbook context</h4>
          {#each entry.sources.slice(0, 3) as source, index (index)}
            <div class="border-t border-base-300 py-2">
              <small class="opacity-60">{source.title} · PDF {source.pdf_page}</small>
              <p class="russian text-sm mt-1">{source.context}</p>
            </div>
          {/each}
        </div>
      {/if}
      <div class="mt-5">
        <PronunciationEditor {entry} {refresh} onSaved={saved} />
      </div>
      <div class="mt-4 border-t border-base-300 pt-4">
        <label class="field">
          <span>Reason to defer (optional; private to this queue)</span>
          <textarea
            class="textarea textarea-bordered w-full"
            rows="2"
            maxlength="1000"
            bind:value={note}
            placeholder="e.g. ambiguous homograph, compound stress, check source meaning"
          ></textarea>
        </label>
        <div class="flex flex-wrap gap-2 mt-3">
          {#if result.deferred}
            <button class="btn btn-outline btn-sm" disabled={busy}
              onclick={() => saveDeferral(false)}>Return to pending</button>
          {:else}
            <button class="btn btn-outline btn-sm" disabled={busy}
              onclick={() => saveDeferral(true)}>Defer</button>
          {/if}
          <button class="btn btn-primary btn-sm" disabled={busy}
            onclick={next}>Skip / next</button>
        </div>
      </div>
    </div>
  {:else if result && !busy}
    <p class="py-8 text-center opacity-70">No entries in this queue.</p>
  {/if}
</section>
