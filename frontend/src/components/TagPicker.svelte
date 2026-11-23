<script lang="ts">
  import type { Sense, Tag } from '../lib/types';

  export let sense: Sense;
  export let availableTags: Tag[];
  export let busy = false;
  export let onAttach: (name: string, category: string) => Promise<boolean>;
  export let onCreate: (name: string, category: string) => Promise<boolean>;

  let query = '';
  let newTagName = '';
  let category = 'semantic';

  $: suggestions = availableTags
    .filter((tag) => !sense.tags.some((current) => current.id === tag.id))
    .filter((tag) => `${tag.name} ${tag.category}`.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => (b.sense_count ?? 0) - (a.sense_count ?? 0) || a.name.localeCompare(b.name))
    .slice(0, 8);

  async function attach(tag: Tag): Promise<void> {
    if (await onAttach(tag.name, tag.category)) query = '';
  }

  async function create(): Promise<void> {
    if (!newTagName.trim()) return;
    if (await onCreate(newTagName.trim(), category)) newTagName = '';
  }
</script>

<div class="mt-3 space-y-2">
  <label class="field">
    <span>Add existing tag</span>
    <input
      type="search"
      class="input input-bordered input-sm"
      placeholder="Filter available tags…"
      aria-label="Find an existing tag"
      bind:value={query}
    />
  </label>
  <div class="flex flex-wrap gap-2">
    {#each suggestions as tag (tag.id)}
      <button
        type="button"
        class="badge badge-outline cursor-pointer hover:bg-base-200"
        title={`${tag.category} tag — ${tag.sense_count ?? 0} senses`}
        disabled={busy}
        on:click={() => attach(tag)}
      >
        + {tag.name} <span class="opacity-60">({tag.category})</span>
      </button>
    {/each}
    {#if query.trim() && suggestions.length === 0}
      <span class="text-xs opacity-60">No matching unassigned tags.</span>
    {/if}
  </div>
  <details class="text-sm">
    <summary class="cursor-pointer text-primary">Create a new tag</summary>
    <form class="mt-2 flex gap-2 flex-wrap items-center" on:submit|preventDefault={create}>
      <input
        class="input input-bordered input-sm"
        placeholder="New tag name"
        bind:value={newTagName}
        required
        maxlength="48"
      />
      <select class="select select-bordered select-sm" bind:value={category}>
        <option value="semantic">semantic</option>
        <option value="grammatical">grammatical</option>
        <option value="usage">usage</option>
      </select>
      <button class="btn btn-outline btn-sm" disabled={busy}>Add tag</button>
    </form>
  </details>
</div>
