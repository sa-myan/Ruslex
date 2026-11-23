<script lang="ts">
  import { request } from '../lib/api';
  import type { Summary, Page } from '../lib/types';
  export let selected: Summary|null = null;
  export let onSelect: (item:Summary|null)=>void;
  let query='';let options:Summary[]=[];let busy=false;
  let timer:ReturnType<typeof setTimeout>;
  async function search(){
    if(!query.trim()){options=[];return;}
    busy=true;
    try{const results=await request<Page<Summary>>(`/api/lexemes?q=${encodeURIComponent(query)}&page_size=12`);options=results.items;}
    catch{options=[];}finally{busy=false;}
  }
</script>
{#if selected}
  <div class="flex items-center gap-2"><strong class="russian">{selected.lemma}</strong><span class="badge badge-sm">{selected.pos}</span>
    <button type="button" class="btn btn-xs btn-ghost" on:click={() => {selected=null;onSelect(null);}}>Change ×</button></div>
{:else}
  <input class="input input-bordered w-full" placeholder="Find another Russian entry…" bind:value={query}
    on:input={() => {clearTimeout(timer);timer=setTimeout(search,220);}} />
  {#if busy}<span class="loading loading-spinner loading-xs"></span>{/if}
  <div class="max-h-44 overflow-y-auto">
    {#each options as result}
      <button type="button" class="block p-2 w-full text-left hover:bg-base-200" on:click={() => {selected=result;onSelect(result);options=[];}}>
        <span class="russian font-semibold">{result.lemma}</span> <small>{result.pos} · {result.gloss_preview}</small>
      </button>
    {/each}
  </div>
{/if}
