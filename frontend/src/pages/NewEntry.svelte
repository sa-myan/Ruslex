<script lang="ts">
  import {onMount} from 'svelte';
  import {request,mutate,navigate} from '../lib/api';
  import type {Metadata} from '../lib/types';
  let meta:Metadata|null=null;let lemma='';let pos='NOUN';let entryType='word';let aspect='';let animacy='';let error='';
  onMount(()=>{request<Metadata>('/api/meta').then(m=>meta=m).catch(e=>error=e.message);});
  async function save(){error='';try{const word=await mutate<{id:number}>('/api/lexemes','POST',
    {lemma,pos,entry_type:entryType,aspect:aspect||null,animacy:animacy||null});navigate(`/word/${word.id}`);}
    catch(e){error=(e as Error).message;}}
</script>
<p class="kicker">Editor</p><h2 class="text-3xl font-bold mt-2 mb-6">Add a dictionary entry</h2>
<section class="surface p-6 max-w-2xl"><form class="space-y-4" on:submit|preventDefault={save}>
  <label class="field"><span>Russian lemma or expression</span><input class="russian" bind:value={lemma} required maxlength="120"/></label>
  <label class="field"><span>Part of speech</span><select bind:value={pos}>{#each meta?.parts_of_speech||[] as p}<option value={p.code}>{p.label} ({p.code})</option>{/each}</select></label>
  <label class="field"><span>Entry type</span><select bind:value={entryType}><option value="word">Word</option><option value="expression">Expression</option></select></label>
  <label class="field"><span>Verb aspect</span><select bind:value={aspect}><option value="">Not specified</option>{#each meta?.aspects||[] as v}<option>{v}</option>{/each}</select></label>
  <label class="field"><span>Noun animacy</span><select bind:value={animacy}><option value="">Not specified</option>{#each meta?.animacies||[] as v}<option>{v}</option>{/each}</select></label>
  {#if error}<div class="alert alert-error">{error}</div>{/if}<button class="btn btn-primary">Create entry</button>
</form></section>
