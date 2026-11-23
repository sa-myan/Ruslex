<script lang="ts">
  import {onMount} from 'svelte';
  import {request,mutate,navigate,reviewMode} from '../lib/api';
  import type {ReviewNext,Status} from '../lib/types';
  let filter='unreviewed';let after=0;let batch:ReviewNext|null=null;let busy=false;let error='';
  onMount(() => { void load(); });
  async function load(){busy=true;error='';try{batch=await request(`/api/review/next?filter=${filter}&after=${after}`);}
    catch(e){error=(e as Error).message;}finally{busy=false;}}
  async function choose(status:Status){if(!batch?.word)return;
    try{await mutate(`/api/lexemes/${batch.word.id}`,'PATCH',{human_status:status});after=batch.word.id;load();}
    catch(e){error=(e as Error).message;}}
</script>
{#if $reviewMode}<div class="mb-6"><p class="kicker">Review workflow</p><h2 class="text-3xl font-bold">Fast review</h2></div>
  <section class="surface p-5"><div class="flex flex-wrap items-center justify-between gap-2 mb-5"><label class="field"><span>Review queue</span>
    <select bind:value={filter} on:change={()=>{after=0;load();}}>
      {#each ['unreviewed','followup','kept','hidden','all'] as v}<option>{v}</option>{/each}</select></label>
    <span class="badge badge-outline">{batch?.total??'—'} total</span></div>
    {#if busy}<div class="loading loading-spinner"></div>{/if}
    {#if error}<div class="alert alert-error">{error}</div>{/if}
    {#if batch?.word}<h3 class="russian text-3xl font-bold">{batch.word.lemma} <span class="text-base opacity-50">{batch.word.pos}</span></h3>
      <button class="link link-primary my-3" on:click={()=>navigate(`/word/${batch!.word!.id}`)}>Open complete entry ↗</button>
      <div class="flex flex-wrap gap-2 my-5">{#each ['kept','followup','hidden','unreviewed'] as status}
        <button class={`btn ${status==='kept'?'btn-success':status==='hidden'?'btn-error':'btn-outline'}`} on:click={()=>choose(status as Status)}>{status}</button>{/each}
        <button class="btn btn-ghost" on:click={()=>{after=batch!.word!.id;load();}}>Skip →</button></div>
      {#each batch.sources as source}<div class="border-t border-base-300 py-2"><small class="opacity-55">{source.title} · PDF {source.pdf_page}</small><p class="russian">{source.context}</p></div>{/each}
    {:else if batch}<div class="p-8 text-center">No words remain in this queue.</div>{/if}
  </section>
{/if}
