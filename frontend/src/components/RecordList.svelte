<script lang="ts">
  import { mutate } from '../lib/http';
  import { editMode } from '../lib/session';
  import { errorMessage } from '../lib/errors';
  import type { Example, Pattern } from '../lib/types';

  export let wordId: number;
  export let senseId: number;
  export let kind: 'examples' | 'patterns';
  export let items: (Example | Pattern)[];
  export let refresh: () => Promise<boolean>;
  export let onSaved: () => void;
  export let onSaveStart: () => void;

  let editingId: number | null = null;
  let adding = false;
  let russian = '';
  let english = '';
  let pattern = '';
  let error = '';
  let saving = false;

  $: visibleItems = items.filter((item) => item.active || $editMode);

  function start(item?: Example | Pattern): void {
    editingId = item?.id ?? null;
    russian = item && 'russian' in item ? item.russian : '';
    english = item && 'english' in item ? item.english : '';
    pattern = item && 'pattern' in item ? item.pattern : '';
    error = '';
    adding = true;
  }

  async function save(): Promise<void> {
    onSaveStart();
    saving = true;
    error = '';
    try {
      const url = `/api/lexemes/${wordId}/senses/${senseId}/${kind}${editingId ? `/${editingId}` : ''}`;
      const body = kind === 'examples' ? { russian, english } : { pattern };
      await mutate(url, editingId ? 'PUT' : 'POST', body);
      if (await refresh()) {
        adding = false;
        onSaved();
      }
    } catch (err) {
      error = errorMessage(err);
    } finally {
      saving = false;
    }
  }

  async function toggle(item: Example | Pattern): Promise<void> {
    onSaveStart();
    error = '';
    try {
      await mutate(`/api/lexemes/${wordId}/records/${kind}/${item.id}/active`, 'PATCH', {
        active: !item.active,
      });
      if (await refresh()) onSaved();
    } catch (err) {
      error = errorMessage(err);
    }
  }
</script>

{#if visibleItems.length || $editMode}
  <section class="mt-3">
    <div class="flex justify-between items-center mb-2">
      <h5 class="font-semibold text-sm capitalize">{kind}</h5>
      {#if $editMode}
        <button class="btn btn-xs btn-outline" on:click={() => start()}>+ Add</button>
      {/if}
    </div>
    <div class="space-y-2">
      {#each visibleItems as item (item.id)}
        <div class:opacity-50={!item.active} class="pl-3 border-l-2 border-base-300 text-sm">
          {#if 'russian' in item}
            <p class="russian">{item.russian}</p>
            {#if item.english}<p class="opacity-70">{item.english}</p>{/if}
          {:else}
            <p class="russian">{item.pattern}</p>
          {/if}
          {#if $editMode}
            <div class="flex gap-1 mt-1">
              <button class="btn btn-ghost btn-xs" on:click={() => start(item)}>Edit</button>
              <button class="btn btn-ghost btn-xs" on:click={() => toggle(item)}>
                {item.active ? 'Archive' : 'Restore'}
              </button>
            </div>
          {/if}
        </div>
      {/each}
    </div>

    {#if adding && $editMode}
      <form class="mt-3 p-3 bg-base-200 rounded-lg space-y-2" on:submit|preventDefault={save}>
        {#if kind === 'examples'}
          <label class="field">
            <span>Russian example</span>
            <textarea bind:value={russian} required></textarea>
          </label>
          <label class="field">
            <span>English translation</span>
            <textarea bind:value={english}></textarea>
          </label>
        {:else}
          <label class="field">
            <span>Grammar pattern</span>
            <textarea bind:value={pattern} required></textarea>
          </label>
        {/if}
        {#if error}<p class="text-error text-sm" role="alert">{error}</p>{/if}
        <div class="flex gap-2">
          <button class="btn btn-primary btn-sm" disabled={saving}>Save</button>
          <button class="btn btn-sm" type="button" disabled={saving} on:click={() => { adding = false; }}>
            Cancel
          </button>
        </div>
      </form>
    {/if}
    {#if error && !adding}<p class="text-error text-sm" role="alert">{error}</p>{/if}
  </section>
{/if}
