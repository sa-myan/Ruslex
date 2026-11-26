<script lang="ts">
  import type { WordForm } from '../../lib/types';
  import { organizeWordForms } from '../../lib/wordForms';

  interface Props {
    forms: WordForm[];
    pos: string;
  }
  let { forms, pos }: Props = $props();
  let expanded = $state(false);
  const organized = $derived(organizeWordForms(forms, pos));

  // One spelling may have several distinct grammatical analyses.
  const unique = $derived(
    Array.from(new Map(forms.map((row) => [row.form + '/' + row.grammemes, row])).values())
  );
  const visible = $derived(expanded ? unique : unique.slice(0, 18));
</script>

{#if unique.length}
  <section class="surface p-5 mt-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-xl font-semibold">Word forms</h3>
        <p class="text-xs opacity-65 mt-1">
          Morphologically generated; not necessarily attested in the textbook.
          Stress is shown only on verified headwords, not predicted inflections.
        </p>
      </div>
      <span class="badge badge-outline">{unique.length} analyses</span>
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mt-4">
      {#each visible as item (item.form + '/' + item.grammemes)}
        <div class="rounded-lg border border-base-300 p-2">
          <div class="russian font-medium">{item.form}</div>
          <div class="text-xs opacity-60 break-words mt-1" title={item.grammemes}>
            {item.grammemes.replaceAll(',', ' · ')}
          </div>
        </div>
      {/each}
    </div>
    {#if unique.length > 18}
      <button class="btn btn-sm btn-outline mt-3"
        onclick={() => { expanded = !expanded; }}>
        {expanded ? 'Show fewer forms' : `Show all ${unique.length} analyses`}
      </button>
    {/if}
  </section>
{/if}
