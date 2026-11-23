<script lang="ts">
  import { editMode } from '../../lib/session';
  import { mutate } from '../../lib/http';
  import { dictionaryLinks } from '../../lib/externalLinks';
  import type { Entry, ExternalLink } from '../../lib/types';

  interface Props {
    entry: Entry;
    saveChange: (action: () => Promise<unknown>) => Promise<boolean>;
  }

  let { entry, saveChange }: Props = $props();

  let editing = $state(false);
  let editingId = $state<number | null>(null);
  let label = $state('');
  let url = $state('');

  let standardLinks = $derived(dictionaryLinks(entry.lemma));

  function start(link?: ExternalLink): void {
    editingId = link?.id ?? null;
    label = link?.label ?? '';
    url = link?.url ?? '';
    editing = true;
  }

  async function save(): Promise<void> {
    const endpoint = `/api/lexemes/${entry.id}/external-links${editingId ? `/${editingId}` : ''}`;
    const saved = await saveChange(() => mutate(endpoint, editingId ? 'PUT' : 'POST', { label, url }));
    if (saved) editing = false;
  }

  async function remove(id: number): Promise<void> {
    if (!confirm('Remove this link?')) return;
    await saveChange(() => mutate(`/api/lexemes/${entry.id}/external-links/${id}`, 'DELETE'));
  }
</script>

<section class="surface p-5 mt-5">
  <div class="panel-header">
    <h3 class="text-xl font-semibold">External dictionaries</h3>
    {#if $editMode}
      <button class="btn btn-sm btn-outline" onclick={() => start()}>+ Custom link</button>
    {/if}
  </div>
  <div class="flex flex-wrap gap-x-5 gap-y-3">
    {#each standardLinks as link (link.label)}
      <div>
        <a class="link link-primary" href={link.url} target="_blank" rel="noopener noreferrer">
          {link.label} ↗
        </a>
      </div>
    {/each}
    {#each entry.external_links as link (link.id)}
      <div>
        <a class="link link-primary" href={link.url} target="_blank" rel="noopener noreferrer">
          {link.label} ↗
        </a>
        {#if $editMode}
          <button class="btn btn-ghost btn-xs" onclick={() => start(link)}>Edit</button>
          <button class="btn btn-ghost btn-xs" onclick={() => remove(link.id)}>Remove</button>
        {/if}
      </div>
    {/each}
  </div>
  {#if editing && $editMode}
    <form class="mt-4 space-y-2" onsubmit={(event) => { event.preventDefault(); void save(); }}>
      <label class="field">
        <span>Label</span>
        <input bind:value={label} required maxlength="80" />
      </label>
      <label class="field">
        <span>URL</span>
        <input type="url" bind:value={url} required maxlength="2048" />
      </label>
      <button class="btn btn-primary btn-sm">Save link</button>
      <button class="btn btn-sm ml-2" type="button" onclick={() => editing = false}>Cancel</button>
    </form>
  {/if}
</section>
