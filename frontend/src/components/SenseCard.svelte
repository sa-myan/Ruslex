<script lang="ts">
  import { mutate } from '../lib/http';
  import { errorMessage } from '../lib/errors';
  import { editMode } from '../lib/session';
  import type { Entry, Sense, Tag } from '../lib/types';
  import RecordList from './RecordList.svelte';
  import RelationList from './RelationList.svelte';
  import TagPicker from './TagPicker.svelte';

  interface Props {
    entry: Entry;
    sense: Sense;
    refresh: () => Promise<boolean>;
    availableTags?: Tag[];
    reloadTags: () => Promise<void>;
    onSaved: () => void;
    onSaveStart: () => void;
  }

  let { entry, sense, refresh, availableTags = [], reloadTags, onSaved, onSaveStart }: Props = $props();

  let editing = $state(false);
  let meaning = $state('');
  let description = $state('');
  let busyTag = $state(false);
  let error = $state('');

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
      error = errorMessage(err);
    }
  }

  async function active() {
    onSaveStart();
    error = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/records/senses/${sense.id}/active`, 'PATCH', { active: !sense.active });
      if (await refresh()) onSaved();
    } catch (err) {
      error = errorMessage(err);
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
        onSaved();
        return true;
      }
      return false;
    } catch (err) {
      error = errorMessage(err);
      return false;
    } finally {
      busyTag = false;
    }
  }

  async function createTag(name: string, category: string): Promise<boolean> {
    const saved = await attachTag(name, category);
    if (saved) await reloadTags();
    return saved;
  }

  async function removeTag(id: number) {
    onSaveStart();
    busyTag = true;
    error = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/senses/${sense.id}/tags/${id}`, 'DELETE');
      if (await refresh()) onSaved();
    } catch (err) {
      error = errorMessage(err);
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
        <button class="btn btn-xs btn-outline" onclick={start}>Edit</button>
        <button class="btn btn-xs btn-ghost" onclick={active}>{sense.active ? 'Archive' : 'Restore'}</button>
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
            <button class="ml-1" aria-label={`Remove ${tag.name} tag`} disabled={busyTag} onclick={() => removeTag(tag.id)}>×</button>
          {/if}
        </span>
      {/each}
    </div>
  {/if}

  {#if editing && $editMode}
    <form class="bg-base-200 p-3 rounded-lg mt-3 space-y-2" onsubmit={(event) => { event.preventDefault(); void save(); }}>
      <label class="field"><span>Meaning (English)</span><textarea bind:value={meaning} required></textarea></label>
      <label class="field"><span>Description</span><textarea bind:value={description}></textarea></label>
      <button class="btn btn-primary btn-sm">Save</button>
      <button type="button" class="btn btn-sm ml-2" onclick={() => editing = false}>Cancel</button>
    </form>
  {/if}

  {#if $editMode}
    <TagPicker
      {sense}
      {availableTags}
      busy={busyTag}
      onAttach={attachTag}
      onCreate={createTag}
    />
  {/if}

  <RecordList wordId={entry.id} senseId={sense.id} kind="patterns" items={sense.patterns} {refresh} {onSaved} {onSaveStart} />
  <RecordList wordId={entry.id} senseId={sense.id} kind="examples" items={sense.examples} {refresh} {onSaved} {onSaveStart} />
  <RelationList {entry} scope={sense.id} {refresh} {onSaved} {onSaveStart} />

  {#if error}<p class="text-error text-sm mt-2">{error}</p>{/if}
</article>
