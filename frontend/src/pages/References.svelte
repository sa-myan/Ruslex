<script lang="ts">
  import { onMount } from 'svelte';
  import { request,navigate } from '../lib/api';
  import type { Entry, Page, RefPage, Source } from '../lib/types';
  export let wordId:number;
  let entry:Entry|null=null;let pages:Page<RefPage>|null=null;let sources:Page<Source>|null=null;
  let p=1;let s=1;let selected:RefPage|null=null;let error='';
  onMount(()=>{request<Entry>(`/api/lexemes/${wordId}`).then(w=>entry=w).catch(e=>error=e.message);loadPages();loadSources();});
  async function loadPages(){try{pages=await request(`/api/lexemes/${wordId}/reference-pages?page=${p}&page_size=40`);}catch(e){error=(e as Error).message;}}
  async function loadSources(){const opts=new URLSearchParams({page:String(s),page_size:'40'});
    if(selected){opts.set('book_id',String(selected.book_id));opts.set('pdf_page',String(selected.pdf_page));}
    try{sources=await request(`/api/lexemes/${wordId}/references?${opts}`);}catch(e){error=(e as Error).message;}}
  function choose(page:RefPage|null){selected=selected?.page_id===page?.page_id?null:page;s=1;loadSources();}
</script>
<button class="btn btn-ghost btn-sm mb-5" on:click={()=>navigate(`/word/${wordId}`)}>← Entry</button>
<p class="kicker">Source evidence</p><h2 class="text-3xl font-bold mt-2 mb-2">References</h2>
{#if entry}<p class="mb-6 opacity-65"><strong class="russian">{entry.lemma}</strong> · {entry.sources_total} references on {entry.source_page_count} pages</p>{/if}
{#if error}<div class="alert alert-error">{error}</div>{/if}
<div class="grid md:grid-cols-[minmax(200px,320px)_1fr] gap-5 items-start">
  <section class="surface p-5"><h3 class="font-bold mb-3">Pages</h3>
    {#if selected}<button class="btn btn-ghost btn-sm" on:click={()=>choose(null)}>Clear filter ×</button>{/if}
    {#each pages?.items||[] as page}<button class={`block w-full text-left border-b border-base-300 p-3 hover:bg-base-200 ${selected?.page_id===page.page_id?'bg-primary/10':''}`} on:click={()=>choose(page)}>
      <strong class="block">{page.title}</strong><small>PDF {page.pdf_page} · printed {page.printed_page}</small>
      <small class="block opacity-50">{page.occurrence_count} occurrences</small></button>{/each}
    {#if pages && pages.pages>1}<div class="flex gap-2 mt-4 items-center"><button class="btn btn-xs" disabled={p<=1} on:click={()=>{p--;loadPages();}}>←</button>{p}/{pages.pages}<button class="btn btn-xs" disabled={p>=pages.pages} on:click={()=>{p++;loadPages();}}>→</button></div>{/if}
  </section>
  <section class="surface p-5"><h3 class="font-bold mb-3">Occurrences ({sources?.total||0})</h3>
    {#each sources?.items||[] as item}<div class="py-4 border-b border-base-300"><small class="opacity-60">{item.title} · PDF {item.pdf_page} · printed {item.printed_page} · {item.surface} × {item.count}</small>
      <p class="russian mt-2">{item.context}</p></div>{/each}
    {#if sources && sources.pages>1}<div class="flex gap-2 mt-4 items-center"><button class="btn btn-sm" disabled={s<=1} on:click={()=>{s--;loadSources();}}>← Previous</button>{s}/{sources.pages}
      <button class="btn btn-sm" disabled={s>=sources.pages} on:click={()=>{s++;loadSources();}}>Next →</button></div>{/if}
  </section>
</div>
