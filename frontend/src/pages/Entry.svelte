<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { request, mutate } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { editMode, reviewMode, user } from '../lib/session';
  import { errorMessage } from '../lib/errors';
  import type { Entry as DictionaryEntry, Metadata, Status, Tag } from '../lib/types';

  import EntryIdentityForm from '../components/entry/EntryIdentityForm.svelte';
  import ExpressionComponents from '../components/entry/ExpressionComponents.svelte';
  import ExternalLinks from '../components/entry/ExternalLinks.svelte';
  import SenseCard from '../components/SenseCard.svelte';
  import RelationList from '../components/RelationList.svelte';

  interface Props {
    wordId: number;
  }

  let { wordId }: Props = $props();

  const reviewStatuses: Status[] = ['unreviewed', 'kept', 'followup', 'hidden'];

  let entry = $state<DictionaryEntry | null>(null);
  let metadata = $state<Metadata | null>(null);
  let availableTags = $state<Tag[]>([]);
  let isLoading = $state(true);
  let error = $state('');
  let notice = $state('');
  let noticeTimer: ReturnType<typeof setTimeout> | undefined;

  let showArchived = $state(false);
  let isEditingIdentity = $state(false);
  let isAddingSense = $state(false);
  let newMeaning = $state('');
  let newDescription = $state('');
  let notes = $state('');

  let visibleSenses = $derived(entry?.senses.filter(
    (sense) => sense.active || ($editMode && showArchived),
  ) ?? []);

  onMount(() => {
    void refresh();
    void loadMetadata();
    void reloadTags();
  });
  onDestroy(() => clearTimeout(noticeTimer));

  async function loadMetadata(): Promise<void> {
    try {
      metadata = await request<Metadata>('/api/meta');
    } catch (err) {
      error = `Unable to load entry metadata: ${errorMessage(err)}`;
    }
  }

  async function reloadTags(): Promise<void> {
    try {
      availableTags = await request<Tag[]>('/api/tags');
    } catch (err) {
      error = `Unable to load existing tags: ${errorMessage(err)}`;
    }
  }

  function clearNotice(): void {
    clearTimeout(noticeTimer);
    notice = '';
  }

  function showSaved(): void {
    clearNotice();
    notice = 'Saved';
    noticeTimer = setTimeout(() => { notice = ''; }, 3000);
  }

  async function refresh(): Promise<boolean> {
    isLoading = true;
    error = '';
    try {
      const updatedEntry = await request<DictionaryEntry>(`/api/lexemes/${wordId}`);
      entry = updatedEntry;
      notes = updatedEntry.notes;
      return true;
    } catch (err) {
      error = errorMessage(err);
      return false;
    } finally {
      isLoading = false;
    }
  }

  /** Only acknowledge a save once Django has accepted it and the entry reload succeeds. */
  async function saveChange(action: () => Promise<unknown>): Promise<boolean> {
    clearNotice();
    error = '';
    try {
      await action();
      if (!(await refresh())) return false;
      showSaved();
      return true;
    } catch (err) {
      error = errorMessage(err);
      return false;
    }
  }

  function updateEntry(fields: Record<string, unknown>): Promise<boolean> {
    return saveChange(() => mutate(`/api/lexemes/${wordId}`, 'PATCH', fields));
  }

  async function addSense(): Promise<void> {
    const saved = await saveChange(() => mutate(`/api/lexemes/${wordId}/senses`, 'POST', {
      meaning: newMeaning,
      description: newDescription,
    }));
    if (saved) {
      isAddingSense = false;
      newMeaning = '';
      newDescription = '';
    }
  }
</script>

<button class="btn btn-ghost btn-sm mb-4" onclick={() => navigate('/')}>
  ← Dictionary
</button>

{#if isLoading && !entry}
  <div class="loading loading-spinner"></div>
{/if}
{#if error}
  <div class="alert alert-error mb-4" role="alert">{error}</div>
{/if}
{#if notice}
  <div class="toast toast-top toast-end z-50" aria-live="polite">
    <div class="alert alert-success shadow-lg" role="status">
      <span>{notice}</span>
      <button class="btn btn-ghost btn-xs" aria-label="Dismiss notification" onclick={clearNotice}>×</button>
    </div>
  </div>
{/if}

{#if entry}
  <div class="flex flex-wrap items-start justify-between gap-3 mb-6">
    <div>
      <p class="kicker">{entry.entry_type === 'expression' ? 'Expression' : 'Dictionary entry'}</p>
      <h2 class="text-3xl md:text-4xl russian font-bold mt-2">{entry.stressed_lemma ?? entry.lemma}</h2>
      <div class="flex flex-wrap gap-2 mt-3">
        <span class="badge badge-neutral">{entry.pos}</span>
        {#if entry.aspect}<span class="badge badge-outline">{entry.aspect}</span>{/if}
        {#if entry.animacy}<span class="badge badge-outline">{entry.animacy}</span>{/if}
        {#if $reviewMode}<span class="badge badge-warning">{entry.human_status}</span>{/if}
      </div>
    </div>
    <div class="flex gap-2 flex-wrap">
      <button
        class="btn btn-outline btn-sm"
        onclick={() => navigate(`/word/${wordId}/references`)}
      >References ({entry.source_page_count})</button>
      {#if $editMode}
        <button class="btn btn-primary btn-sm" onclick={() => { isEditingIdentity = !isEditingIdentity; }}>
          Edit entry
        </button>
      {/if}
    </div>
  </div>

  {#if isEditingIdentity && $editMode}
    <EntryIdentityForm
      {entry}
      {metadata}
      onSave={updateEntry}
      onCancel={() => { isEditingIdentity = false; }}
    />
  {/if}

  {#if $reviewMode && $user?.can_review}
    <section class="surface p-4 mb-4 flex gap-2 items-center flex-wrap">
      <span class="meta-label mr-2">Review</span>
      {#each reviewStatuses as status}
        <button
          class={`btn btn-sm ${entry.human_status === status ? 'btn-primary' : 'btn-outline'}`}
          onclick={() => updateEntry({ human_status: status })}
        >{status}</button>
      {/each}
    </section>
  {/if}

  {#if visibleSenses.length || $editMode}
    <div class="flex justify-between items-center mb-3">
      <h3 class="text-xl font-semibold">Meanings</h3>
      {#if $editMode}
        <button class="btn btn-primary btn-sm" onclick={() => { isAddingSense = !isAddingSense; }}>
          + Add meaning
        </button>
      {/if}
    </div>

    {#if isAddingSense && $editMode}
      <form class="surface p-4 space-y-2 mb-4" onsubmit={(event) => { event.preventDefault(); void addSense(); }}>
        <label class="field">
          <span>English meaning</span>
          <textarea bind:value={newMeaning} required></textarea>
        </label>
        <label class="field">
          <span>Description</span>
          <textarea bind:value={newDescription}></textarea>
        </label>
        <button class="btn btn-primary btn-sm">Save meaning</button>
      </form>
    {/if}

    {#if $editMode}
      <label class="label text-sm mb-2 gap-2">
        <input class="checkbox checkbox-sm" type="checkbox" bind:checked={showArchived} />
        Show archived meanings
      </label>
    {/if}
    {#each visibleSenses as sense (sense.id)}
      <SenseCard
        {entry}
        {sense}
        {refresh}
        {availableTags}
        {reloadTags}
        onSaved={showSaved}
        onSaveStart={clearNotice}
      />
    {/each}
  {/if}

  <RelationList
    {entry}
    scope={null}
    {refresh}
    onSaved={showSaved}
    onSaveStart={clearNotice}
  />

  <ExpressionComponents {entry} {saveChange} />

  {#if entry.occurs_in.length}
    <section class="surface p-5 mt-5">
      <h3 class="font-semibold">Occurs in expressions</h3>
      <div class="flex gap-3 flex-wrap mt-3">
        {#each entry.occurs_in as component}
          <a
            class="link link-primary"
            href={`/word/${component.expression_id}`}
            onclick={(event) => {
              event.preventDefault();
              navigate(`/word/${component.expression_id}`);
            }}
          >{component.expression_lemma}</a>
        {/each}
      </div>
    </section>
  {/if}

  <ExternalLinks {entry} {saveChange} />

  {#if entry.sources.length || entry.source_page_count}
    <section class="surface p-5 mt-5">
      <div class="panel-header">
        <h3 class="text-xl font-semibold">Textbook evidence</h3>
        <button class="btn btn-outline btn-sm" onclick={() => navigate(`/word/${wordId}/references`)}>
          All references
        </button>
      </div>
      {#each entry.sources as source}
        <div class="py-2 border-b border-base-300">
          <div class="text-xs opacity-60">
            {source.title} · PDF {source.pdf_page} · printed {source.printed_page} · {source.surface}
          </div>
          <p class="russian text-sm mt-1">{source.context}</p>
        </div>
      {/each}
    </section>
  {/if}

  {#if entry.notes.trim() || $editMode}
    <section class="surface p-5 mt-5">
      <h3 class="font-semibold mb-3">Notes</h3>
      {#if $editMode}
        <form onsubmit={(event) => { event.preventDefault(); void updateEntry({ notes }); }}>
          <textarea
            class="textarea textarea-bordered w-full"
            aria-label="Entry notes"
            rows="4"
            bind:value={notes}
            maxlength="5000"
          ></textarea>
          <button class="btn btn-primary btn-sm mt-2">Save notes</button>
        </form>
      {:else}
        <p class="whitespace-pre-wrap">{entry.notes}</p>
      {/if}
    </section>
  {/if}
{/if}
