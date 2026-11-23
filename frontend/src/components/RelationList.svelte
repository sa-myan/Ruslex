<script lang="ts">
  import { onDestroy } from 'svelte';
  import { mutate, request } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { editMode } from '../lib/session';
  import { errorMessage, isAbortError } from '../lib/errors';
  import type { Entry, EntryReference, Relation, Sense } from '../lib/types';
  import EntryPicker from './EntryPicker.svelte';

  export let entry: Entry;
  export let scope: number | null = null;
  export let refresh: () => Promise<boolean>;
  export let onSaved: () => void;
  export let onSaveStart: () => void;

  const relationshipTypes = ['aspect_pair', 'synonym', 'antonym', 'derivation', 'related'];

  let editing = false;
  let editingId: number | null = null;
  let selected: EntryReference | null = null;
  let relationType = 'related';
  let ownSense: number | null = null;
  let otherSense: number | null = null;
  let otherSenses: Sense[] = [];
  let notes = '';
  let error = '';

  let lookupController: AbortController | undefined;
  let lookupVersion = 0;

  $: scoped = entry.relations.filter((relation) => {
    const senseId = relation.direction === 'outgoing'
      ? relation.source_sense_id
      : relation.target_sense_id;
    return senseId === scope;
  });

  onDestroy(() => lookupController?.abort());

  async function pick(item: EntryReference | null): Promise<void> {
    lookupController?.abort();
    const version = ++lookupVersion;
    selected = item;
    otherSense = null;
    otherSenses = [];
    if (!item) return;

    const controller = new AbortController();
    lookupController = controller;
    try {
      const detail = await request<Entry>(`/api/lexemes/${item.id}`, { signal: controller.signal });
      if (version === lookupVersion) otherSenses = detail.senses;
    } catch (err) {
      if (version === lookupVersion && !isAbortError(err)) error = errorMessage(err);
    }
  }

  async function start(relation?: Relation): Promise<void> {
    editing = true;
    editingId = relation?.id ?? null;
    relationType = relation?.relation_type ?? 'related';
    ownSense = scope;
    notes = relation?.notes ?? '';
    error = '';

    if (relation) {
      await pick({ id: relation.other_id, lemma: relation.other_lemma, pos: relation.other_pos });
      if (selected?.id === relation.other_id) {
        otherSense = relation.direction === 'outgoing'
          ? relation.target_sense_id
          : relation.source_sense_id;
      }
    } else {
      await pick(null);
    }
  }

  async function save(): Promise<void> {
    if (!selected) {
      error = 'Select a related entry';
      return;
    }
    onSaveStart();
    error = '';
    try {
      const url = `/api/lexemes/${entry.id}/relations${editingId ? `/${editingId}` : ''}`;
      await mutate(url, editingId ? 'PUT' : 'POST', {
        target_lexeme_id: selected.id,
        relation_type: relationType,
        source_sense_id: ownSense,
        target_sense_id: otherSense,
        notes,
      });
      if (await refresh()) {
        editing = false;
        onSaved();
      }
    } catch (err) {
      error = errorMessage(err);
    }
  }

  async function remove(relation: Relation): Promise<void> {
    if (!confirm(`Remove relationship to ${relation.other_lemma}?`)) return;
    onSaveStart();
    error = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/relations/${relation.id}`, 'DELETE');
      if (await refresh()) onSaved();
    } catch (err) {
      error = errorMessage(err);
    }
  }
</script>

{#if scoped.length || $editMode}
  <div class="mt-4 rounded-xl p-3 bg-base-200/50 border border-base-300">
    <div class="flex justify-between items-center mb-2">
      <h4 class="text-sm font-semibold">
        {scope === null ? 'Entry-wide relationships' : 'Related to this meaning'}
      </h4>
      {#if $editMode}
        <button class="btn btn-xs btn-outline" on:click={() => { editing ? editing = false : void start(); }}>
          {editing ? 'Cancel' : '+ Link'}
        </button>
      {/if}
    </div>

    {#each scoped as relation (relation.id)}
      <div class="border-t border-base-300 py-2 flex flex-wrap items-center gap-2 text-sm">
        <span class="badge badge-sm">
          {relation.relation_type.replace('_', ' ')}
          {#if relation.relation_type === 'derivation'}
            {relation.direction === 'outgoing' ? ' →' : ' ←'}
          {/if}
        </span>
        <a
          class="link link-primary russian font-semibold"
          href={`/word/${relation.other_id}`}
          on:click={(event) => {
            event.preventDefault();
            navigate(`/word/${relation.other_id}`);
          }}
        >{relation.other_lemma}</a>
        {#if relation.other_sense_meaning}
          <small class="opacity-65">— {relation.other_sense_meaning}</small>
        {/if}
        {#if relation.notes && $editMode}
          <small class="opacity-60">{relation.notes}</small>
        {/if}
        {#if $editMode}
          <button class="btn btn-ghost btn-xs" on:click={() => start(relation)}>Edit</button>
          <button class="btn btn-ghost btn-xs" on:click={() => remove(relation)}>Remove</button>
        {/if}
      </div>
    {/each}

    {#if editing && $editMode}
      <form class="space-y-3 border-t border-base-300 pt-3" on:submit|preventDefault={save}>
        <div class="field">
          <span>Related entry</span>
          <EntryPicker {selected} onSelect={pick} />
        </div>
        <label class="field">
          <span>Relationship type</span>
          <select bind:value={relationType}>
            {#each relationshipTypes as type}
              <option value={type}>{type.replace('_', ' ')}</option>
            {/each}
          </select>
        </label>
        {#if scope === null}
          <label class="field">
            <span>This entry's sense (optional)</span>
            <select bind:value={ownSense}>
              <option value={null}>Whole entry</option>
              {#each entry.senses as sense}<option value={sense.id}>{sense.meaning}</option>{/each}
            </select>
          </label>
        {/if}
        <label class="field">
          <span>Related entry's sense</span>
          <select bind:value={otherSense}>
            <option value={null}>Whole entry</option>
            {#each otherSenses as sense}<option value={sense.id}>{sense.meaning}</option>{/each}
          </select>
        </label>
        <label class="field">
          <span>Private notes</span>
          <textarea bind:value={notes}></textarea>
        </label>
        {#if error}<p class="text-error text-sm" role="alert">{error}</p>{/if}
        <button class="btn btn-primary btn-sm">Save relationship</button>
      </form>
    {/if}
    {#if error && !editing}<p class="text-error text-sm" role="alert">{error}</p>{/if}
  </div>
{/if}
