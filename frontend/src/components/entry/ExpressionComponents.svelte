<script lang="ts">
  import { editMode } from '../../lib/session';
  import { navigate } from '../../lib/navigation';
  import { mutate } from '../../lib/http';
  import type { Component, Entry, EntryReference } from '../../lib/types';
  import EntryPicker from '../EntryPicker.svelte';

  interface Props {
    entry: Entry;
    saveChange: (action: () => Promise<unknown>) => Promise<boolean>;
  }

  let { entry, saveChange }: Props = $props();

  let editing = $state(false);
  let editingId = $state<number | null>(null);
  let selected = $state<EntryReference | null>(null);
  let position = $state(1);
  let surface = $state('');
  let notes = $state('');
  let error = $state('');

  function start(component?: Component): void {
    editingId = component?.id ?? null;
    selected = component
      ? { id: component.word_id, lemma: component.word_lemma, pos: component.word_pos }
      : null;
    position = component?.position ?? Math.max(0, ...entry.components.map((part) => part.position)) + 1;
    surface = component?.surface ?? '';
    notes = component?.notes ?? '';
    error = '';
    editing = true;
  }

  async function save(): Promise<void> {
    if (!selected) {
      error = 'Choose a dictionary word';
      return;
    }
    error = '';
    const selectedWordId = selected.id;
    const endpoint = `/api/lexemes/${entry.id}/components${editingId ? `/${editingId}` : ''}`;
    const saved = await saveChange(() => mutate(endpoint, editingId ? 'PUT' : 'POST', {
      word_id: selectedWordId,
      position: Number(position),
      surface,
      notes,
    }));
    if (saved) editing = false;
  }

  async function remove(id: number): Promise<void> {
    if (!confirm('Remove constituent?')) return;
    await saveChange(() => mutate(`/api/lexemes/${entry.id}/components/${id}`, 'DELETE'));
  }
</script>

{#if entry.entry_type === 'expression' && (entry.components.length || $editMode)}
  <section class="surface p-5 mt-5">
    <div class="panel-header">
      <h3 class="text-xl font-semibold">Constituent words</h3>
      {#if $editMode}
        <button class="btn btn-outline btn-sm" onclick={() => start()}>+ Add</button>
      {/if}
    </div>
    {#each entry.components as component (component.id)}
      <div class="flex flex-wrap gap-3 py-2 border-b border-base-300">
        <span class="opacity-50">{component.position}.</span>
        <a
          class="link link-primary"
          href={`/word/${component.word_id}`}
          onclick={(event) => { event.preventDefault(); navigate(`/word/${component.word_id}`); }}
        >{component.word_lemma}</a>
        <span>{component.surface}</span>
        {#if $editMode}
          <button class="btn btn-xs" onclick={() => start(component)}>Edit</button>
          <button class="btn btn-xs" onclick={() => remove(component.id)}>Remove</button>
        {/if}
      </div>
    {/each}

    {#if editing && $editMode}
      <form class="mt-4 space-y-2" onsubmit={(event) => { event.preventDefault(); void save(); }}>
        <div class="field">
          <span>Constituent word</span>
          <EntryPicker {selected} onSelect={(item) => { selected = item; }} />
        </div>
        <label class="field">
          <span>Position</span>
          <input type="number" min="1" bind:value={position} />
        </label>
        <label class="field">
          <span>Surface in expression</span>
          <input bind:value={surface} />
        </label>
        <label class="field">
          <span>Notes</span>
          <textarea bind:value={notes}></textarea>
        </label>
        {#if error}<p class="text-error text-sm" role="alert">{error}</p>{/if}
        <button class="btn btn-primary">Save constituent</button>
        <button class="btn ml-2" type="button" onclick={() => editing = false}>Cancel</button>
      </form>
    {/if}
  </section>
{/if}
