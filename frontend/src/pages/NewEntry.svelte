<script lang="ts">
  import { onMount } from 'svelte';
  import { request, mutate } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { errorMessage } from '../lib/errors';
  import type { Metadata } from '../lib/types';

  let metadata = $state<Metadata | null>(null);
  let lemma = $state('');
  let pos = $state('NOUN');
  let entryType = $state('word');
  let aspect = $state('');
  let animacy = $state('');
  let busy = $state(false);
  let error = $state('');

  onMount(() => {
    void request<Metadata>('/api/meta')
      .then((data) => { metadata = data; })
      .catch((err) => { error = errorMessage(err); });
  });

  async function save(): Promise<void> {
    if (busy) return;
    busy = true;
    error = '';
    try {
      const word = await mutate<{ id: number }>('/api/lexemes', 'POST', {
        lemma,
        pos,
        entry_type: entryType,
        aspect: aspect || null,
        animacy: animacy || null,
      });
      navigate(`/word/${word.id}`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }
</script>

<p class="kicker">Editor</p>
<h2 class="text-3xl font-bold mt-2 mb-6">Add a dictionary entry</h2>
<section class="surface p-6 max-w-2xl">
  <form class="space-y-4" onsubmit={(event) => { event.preventDefault(); void save(); }}>
    <label class="field">
      <span>Russian lemma or expression</span>
      <input class="russian" bind:value={lemma} required maxlength="120" />
    </label>
    <label class="field">
      <span>Part of speech</span>
      <select bind:value={pos}>
        {#each metadata?.parts_of_speech ?? [] as part}
          <option value={part.code}>{part.label} ({part.code})</option>
        {/each}
      </select>
    </label>
    <label class="field">
      <span>Entry type</span>
      <select bind:value={entryType}>
        <option value="word">Word</option>
        <option value="expression">Expression</option>
      </select>
    </label>
    <label class="field">
      <span>Verb aspect</span>
      <select bind:value={aspect}>
        <option value="">Not specified</option>
        {#each metadata?.aspects ?? [] as value}<option value={value}>{value}</option>{/each}
      </select>
    </label>
    <label class="field">
      <span>Noun animacy</span>
      <select bind:value={animacy}>
        <option value="">Not specified</option>
        {#each metadata?.animacies ?? [] as value}<option value={value}>{value}</option>{/each}
      </select>
    </label>
    {#if error}<div class="alert alert-error" role="alert">{error}</div>{/if}
    <button class="btn btn-primary" disabled={busy}>Create entry</button>
  </form>
</section>
