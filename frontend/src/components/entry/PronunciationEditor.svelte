<script lang="ts">
  import { mutate } from '../../lib/http';
  import { errorMessage } from '../../lib/errors';
  import type { Entry, Pronunciation } from '../../lib/types';

  interface Props {
    entry: Entry;
    refresh: () => Promise<boolean>;
    onSaved?: () => void;
    suggestedReading?: string;
    suggestionToken?: number;
  }
  let { entry, refresh, onSaved, suggestedReading = '', suggestionToken = 0 }: Props = $props();

  let editing = $state<number | null | 'new'>(null);
  let spelling = $state('');
  let primary = $state(true);
  let selectedSenses = $state<number[]>([]);
  let saving = $state(false);
  let error = $state('');
  let success = $state('');

  const vowels = 'аеёиоуыэюяАЕЁИОУЫЭЮЯ';
  let accentChoices = $derived(
    Array.from(spelling.replace(/\u0301/g, ''))
      .map((letter, position) => ({ letter, position }))
      .filter(({ letter }) => vowels.includes(letter))
  );

  function begin(reading?: Pronunciation, proposed?: string): void {
    editing = reading?.id ?? 'new';
    spelling = reading?.stressed ?? proposed ?? entry.lemma;
    primary = reading?.is_primary ?? !entry.pronunciations.length;
    selectedSenses = [...(reading?.sense_ids ?? [])];
    error = '';
    success = '';
  }

  // A source suggestion is a draft only. This opens the normal editor;
  // it never sends a mutation until the user explicitly saves.
  $effect(() => {
    const token = suggestionToken;
    const proposal = suggestedReading;
    if (token > 0 && proposal) {
      const existing = entry.pronunciations.find(item => item.stressed === proposal);
      begin(existing, proposal);
    }
  });

  function accent(position: number): void {
    const letters = Array.from(spelling.replace(/\u0301/g, ''));
    if (letters.includes('ё') || letters.includes('Ё')) {
      error = 'Ё already indicates stress. Correct its spelling first if needed.';
      return;
    }
    letters.splice(position + 1, 0, '\u0301');
    spelling = letters.join('');
    error = '';
  }

  function flipYo(position: number): void {
    const letters = Array.from(spelling.replace(/\u0301/g, ''));
    const before = letters[position];
    if (before === 'е') letters[position] = 'ё';
    else if (before === 'Е') letters[position] = 'Ё';
    else if (before === 'ё') letters[position] = 'е';
    else if (before === 'Ё') letters[position] = 'Е';
    else return;
    spelling = letters.join('');
    error = '';
  }

  function toggleSense(id: number): void {
    selectedSenses = selectedSenses.includes(id)
      ? selectedSenses.filter((value) => value !== id)
      : [...selectedSenses, id];
  }

  async function save(): Promise<void> {
    if (editing === null) return;
    saving = true;
    error = '';
    success = '';
    try {
      const isNew = editing === 'new';
      const url = isNew
        ? `/api/lexemes/${entry.id}/pronunciations`
        : `/api/lexemes/${entry.id}/pronunciations/${editing}`;
      await mutate(url, isNew ? 'POST' : 'PUT', {
        stressed: spelling, is_primary: primary, sense_ids: selectedSenses,
      });
      if (await refresh()) {
        editing = null;
        success = 'Pronunciation saved';
        onSaved?.();
      }
    } catch (err) {
      error = errorMessage(err);
    } finally {
      saving = false;
    }
  }

  async function remove(reading: Pronunciation): Promise<void> {
    if (!confirm(`Delete the pronunciation "${reading.stressed}"?`)) return;
    saving = true;
    error = '';
    success = '';
    try {
      await mutate(`/api/lexemes/${entry.id}/pronunciations/${reading.id}`, 'DELETE');
      if (await refresh()) success = 'Pronunciation removed';
    } catch (err) {
      error = errorMessage(err);
    } finally {
      saving = false;
    }
  }
</script>

<section class="surface p-4 mb-5">
  <div class="flex gap-3 items-center justify-between flex-wrap mb-3">
    <h3 class="font-semibold">Headword pronunciation</h3>
    <button type="button" class="btn btn-sm btn-outline" onclick={() => begin()}>
      + Add reading
    </button>
  </div>
  {#if entry.pronunciations.length}
    <div class="space-y-2">
      {#each entry.pronunciations as reading (reading.id)}
        <div class="flex gap-2 items-center flex-wrap">
          <span class="russian text-lg font-semibold">{reading.stressed}</span>
          <span class="badge badge-outline badge-sm">{reading.verification.replace('_', ' ')}</span>
          {#if reading.is_primary}<span class="badge badge-sm">Primary</span>{/if}
          {#if reading.sense_ids.length}
            <small>Meanings: {reading.sense_ids.join(', ')}</small>
          {/if}
          <button class="btn btn-xs btn-ghost" onclick={() => begin(reading)}>Edit</button>
          <button class="btn btn-xs btn-ghost" disabled={saving} onclick={() => remove(reading)}>Remove</button>
        </div>
      {/each}
    </div>
  {:else}
    <p class="text-sm opacity-65">No pronunciation saved yet.</p>
  {/if}

  {#if editing !== null}
    <form class="mt-4 space-y-3 border-t border-base-300 pt-3"
      onsubmit={(event) => { event.preventDefault(); void save(); }}>
      <label class="field">
        <span>Stressed headword</span>
        <input class="input input-bordered w-full russian text-lg" bind:value={spelling} maxlength="150" required />
      </label>
      <p class="text-xs opacity-65">Select a vowel to mark stress, or toggle е and ё. The original lemma is not changed.</p>
      <div class="flex flex-wrap gap-1">
        {#each accentChoices as choice (choice.position)}
          <button type="button" class="btn btn-xs btn-outline russian"
            title="Stress this vowel" onclick={() => accent(choice.position)}>
            {choice.letter}<span class="opacity-50">{choice.position + 1}</span>
          </button>
          {#if 'еёЕЁ'.includes(choice.letter)}
            <button type="button" class="btn btn-xs btn-ghost"
              title="Toggle е/ё" onclick={() => flipYo(choice.position)}>е/ё</button>
          {/if}
        {/each}
      </div>
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" class="checkbox checkbox-sm" bind:checked={primary} />
        Use this reading in entry headings and search results
      </label>
      {#if entry.senses.length}
        <fieldset class="space-y-1">
          <legend class="text-sm font-semibold">Associated meanings (optional)</legend>
          {#each entry.senses as sense (sense.id)}
            <label class="flex items-center gap-2 text-sm">
              <input type="checkbox" class="checkbox checkbox-sm"
                checked={selectedSenses.includes(sense.id)} onchange={() => toggleSense(sense.id)} />
              {sense.id}: {sense.meaning}
            </label>
          {/each}
        </fieldset>
      {/if}
      <div class="flex gap-2">
        <button class="btn btn-sm btn-primary" disabled={saving} type="submit">Save reading</button>
        <button class="btn btn-sm btn-ghost" type="button" onclick={() => { editing = null; }}>Cancel</button>
      </div>
    </form>
  {/if}
  {#if error}<p class="text-error text-sm mt-2" role="alert">{error}</p>{/if}
  {#if success}<p class="text-success text-sm mt-2" role="status">{success}</p>{/if}
</section>
