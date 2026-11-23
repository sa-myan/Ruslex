<script lang="ts">
  import type { Entry, Metadata } from '../../lib/types';

  interface Props {
    entry: Entry;
    metadata: Metadata | null;
    onSave: (fields: Record<string, unknown>) => Promise<boolean>;
    onCancel: () => void;
  }

  let { entry, metadata, onSave, onCancel }: Props = $props();

  let lemma = $state(entry.lemma);
  let pos = $state(entry.pos);
  let entryType = $state(entry.entry_type);
  let aspect = $state(entry.aspect ?? '');
  let animacy = $state(entry.animacy ?? '');
  let saving = $state(false);

  async function save(): Promise<void> {
    saving = true;
    try {
      const saved = await onSave({
        lemma,
        pos,
        entry_type: entryType,
        aspect: aspect || null,
        animacy: animacy || null,
      });
      if (saved) onCancel();
    } finally {
      saving = false;
    }
  }
</script>

<form class="surface p-5 mb-4 space-y-3" onsubmit={(event) => { event.preventDefault(); void save(); }}>
  <div class="grid md:grid-cols-2 gap-3">
    <label class="field">
      <span>Russian headword</span>
      <input bind:value={lemma} required />
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
      <span>Aspect</span>
      <select bind:value={aspect}>
        <option value="">Not set</option>
        {#each metadata?.aspects ?? [] as value}<option value={value}>{value}</option>{/each}
      </select>
    </label>
    <label class="field">
      <span>Noun animacy</span>
      <select bind:value={animacy}>
        <option value="">Not set</option>
        {#each metadata?.animacies ?? [] as value}<option value={value}>{value}</option>{/each}
      </select>
    </label>
  </div>
  <button class="btn btn-primary" disabled={saving}>Save details</button>
  <button class="btn ml-2" type="button" disabled={saving} onclick={onCancel}>Cancel</button>
</form>
