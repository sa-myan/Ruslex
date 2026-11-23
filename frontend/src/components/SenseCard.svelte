<script lang="ts">
  import { mutate, editMode } from '../lib/api';
  import type { Entry, Sense, Tag } from '../lib/types';
  import RecordList from './RecordList.svelte';
  import RelationList from './RelationList.svelte';

  export let entry: Entry;
  export let sense: Sense;
  export let refresh: () => Promise<boolean>;
  export let availableTags: Tag[] = [];
  export let reloadTags: () => Promise<void>;
  export let onSaved: () => void;
  export let onSaveStart: () => void;

  let editing = false;
  let meaning = '';
  let description = '';
  let tagName = '';
  let category = 'semantic';
  let tagQuery = '';
  let busyTag = false;
  let error = '';

  $: suggestedTags = availableTags
    .filter(tag => !sense.tags.some(current => current.id === tag.id))
    .filter(tag => `${tag.name} ${tag.category}`.toLowerCase().includes(tagQuery.trim().toLowerCase()))
    .sort((a, b) => (b.sense_count ?? 0) - (a.sense_count ?? 0) || a.name.localeCompare(b.name))
    .slice(0, 8);

  function start() {
    editing = true;
    meaning = sense.meaning;
    description = sense.description;
    error = '';
  }

  async function save() {
    onSaveStart();
    error = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/senses/${sense.id}`, 'PUT', { meaning, description });
      if (await refresh()) {
        editing = false;
        onSaved();
      }
    } catch (err) {
      error = (err as Error).message;
    }
  }

  async function active() {
    onSaveStart();
    error = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/records/senses/${sense.id}/active`, 'PATCH', { active: !sense.active });
      if (await refresh()) onSaved();
    } catch (err) {
      error = (err as Error).message;
    }
  }

  async function attachTag(name: string, selectedCategory: string): Promise<boolean> {
    onSaveStart();
    busyTag = true;
    error = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/senses/${sense.id}/tags`, 'POST', {
        name,
        category: selectedCategory
      });
      if (await refresh()) {
        tagQuery = '';
        tagName = '';
        onSaved();
        return true;
      }
      return false;
    } catch (err) {
      error = (err as Error).message;
      return false;
    } finally {
      busyTag = false;
    }
  }

  async function addTag() {
    if (!tagName.trim()) return;
    if (await attachTag(tagName.trim(), category)) await reloadTags();
  }

  async function removeTag(id: number) {
    onSaveStart();
    busyTag = true;
    error = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/senses/${sense.id}/tags/${id}`, 'DELETE');
      if (await refresh()) onSaved();
    } catch (err) {
      error = (err as Error).message;
    } finally {
      busyTag = false;
    }
  }
</script>

<article class:opacity-50={!sense.active} class="surface p-5 mb-4">
  <div class="flex justify-between gap-3 mb-2">
    <div class="flex gap-2 items-start">
      <span class="text-xs badge badge-ghost">#{sense.id}</span>
      <h3 class="text-xl font-semibold">{sense.meaning}</h3>
    </div>
    {#if $editMode}
      <div class="flex gap-1">
        <button class="btn btn-xs btn-outline" on:click={start}>Edit</button>
        <button class="btn btn-xs btn-ghost" on:click={active}>{sense.active ? 'Archive' : 'Restore'}</button>
      </div>
    {/if}
  </div>

  {#if sense.description}
    <p class="opacity-70 text-sm mb-3">{sense.description}</p>
  {/if}
  {#if sense.tags.length}
    <div class="flex gap-2 flex-wrap">
      {#each sense.tags as tag (tag.id)}
        <span class="badge badge-outline badge-sm">
          {tag.name}
          {#if $editMode}
            <button class="ml-1" aria-label={`Remove ${tag.name} tag`} disabled={busyTag} on:click={() => removeTag(tag.id)}>×</button>
          {/if}
        </span>
      {/each}
    </div>
  {/if}

  {#if editing && $editMode}
    <form class="bg-base-200 p-3 rounded-lg mt-3 space-y-2" on:submit|preventDefault={save}>
      <label class="field"><span>Meaning (English)</span><textarea bind:value={meaning} required></textarea></label>
      <label class="field"><span>Description</span><textarea bind:value={description}></textarea></label>
      <button class="btn btn-primary btn-sm">Save</button>
      <button type="button" class="btn btn-sm ml-2" on:click={() => editing = false}>Cancel</button>
    </form>
  {/if}

  {#if $editMode}
    <div class="mt-3 space-y-2">
      <label class="field">
        <span>Add existing tag</span>
        <input
          type="search"
          class="input input-bordered input-sm"
          placeholder="Filter available tags…"
          aria-label="Find an existing tag"
          bind:value={tagQuery}
        />
      </label>
      <div class="flex flex-wrap gap-2">
        {#each suggestedTags as tag (tag.id)}
          <button
            type="button"
            class="badge badge-outline cursor-pointer hover:bg-base-200"
            title={`${tag.category} tag — ${tag.sense_count ?? 0} senses`}
            disabled={busyTag}
            on:click={() => attachTag(tag.name, tag.category)}
          >
            + {tag.name} <span class="opacity-60">({tag.category})</span>
          </button>
        {/each}
        {#if tagQuery.trim() && suggestedTags.length === 0}
          <span class="text-xs opacity-60">No matching unassigned tags.</span>
        {/if}
      </div>
      <details class="text-sm">
        <summary class="cursor-pointer text-primary">Create a new tag</summary>
        <form class="mt-2 flex gap-2 flex-wrap items-center" on:submit|preventDefault={addTag}>
          <input class="input input-bordered input-sm" placeholder="New tag name" bind:value={tagName} required maxlength="48" />
          <select class="select select-bordered select-sm" bind:value={category}>
            <option value="semantic">semantic</option>
            <option value="grammatical">grammatical</option>
            <option value="usage">usage</option>
          </select>
          <button class="btn btn-outline btn-sm" disabled={busyTag}>Add tag</button>
        </form>
      </details>
    </div>
  {/if}

  <RecordList wordId={entry.id} senseId={sense.id} kind="patterns" items={sense.patterns} {refresh} {onSaved} {onSaveStart} />
  <RecordList wordId={entry.id} senseId={sense.id} kind="examples" items={sense.examples} {refresh} {onSaved} {onSaveStart} />
  <RelationList {entry} scope={sense.id} {refresh} {onSaved} {onSaveStart} />

  {#if error}<p class="text-error text-sm mt-2">{error}</p>{/if}
</article>
