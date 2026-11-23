<script lang="ts">
  import { onMount } from 'svelte';
  import { request, navigate, reviewMode, user, editMode } from '../lib/api';
  import type { Book, Metadata, Page, Summary, Tag } from '../lib/types';
  let q = new URLSearchParams(location.search).get('q') || '';
  let status = 'visible'; let page = 1;
  let pos = ''; let kind = ''; let bookId = ''; let pageFrom = ''; let pageTo = '';
  let pageKind = 'pdf'; let selectedTags:number[]=[];
  let tags:Tag[]=[]; let books:Book[]=[]; let meta:Metadata|null=null;
  let results:Page<Summary>|null=null; let busy=false; let error=''; let advanced=false;
  let timer:ReturnType<typeof setTimeout>|undefined; let seq=0;
  onMount(() => {
    Promise.all([request<Tag[]>('/api/tags'),request<Book[]>('/api/books'),request<Metadata>('/api/meta')])
      .then(([t,b,m]) => {tags=t;books=b;meta=m;}).catch(e=>error=e.message);
    load();
  });
  function schedule() {page=1;results=null;clearTimeout(timer);timer=setTimeout(load,250);}
  async function load(){
    const id=++seq; busy=true;error='';
    if(pageFrom && pageTo && Number(pageFrom)>Number(pageTo)){
      error='First page must not be greater than the last';busy=false;return;
    }
    const p=new URLSearchParams({q,status:$reviewMode ? status : 'visible',page:String(page),page_size:'40'});
    if(pos)p.set('pos',pos);if(kind)p.set('entry_type',kind);if(bookId)p.set('book_id',bookId);
    if(pageFrom)p.set(`${pageKind}_page_min`,pageFrom);
    if(pageTo)p.set(`${pageKind}_page_max`,pageTo);
    for(const n of selectedTags)p.append('tag_id',String(n));
    try{const value=await request<Page<Summary>>(`/api/lexemes?${p}`);if(id===seq){results=value;
      const url=new URL(window.location.href); q ? url.searchParams.set('q',q) : url.searchParams.delete('q');
      window.history.replaceState({},'',url.pathname+url.search);
    }}catch(e){if(id===seq)error=(e as Error).message;}finally{if(id===seq)busy=false;}
  }
  function changeMode(){status='visible';page=1;results=null;load();}
  $: if (!$reviewMode && status !== 'visible') changeMode();
  function tagSwitch(id:number){selectedTags=selectedTags.includes(id)?selectedTags.filter(n=>n!==id):[...selectedTags,id];schedule();}
</script>
<div class="mb-7"><p class="kicker">Dictionary</p><h2 class="text-3xl md:text-4xl font-bold mt-2">Russian vocabulary<span class="text-primary">.</span></h2>
  <p class="opacity-60 mt-2">Find words, expressions, meanings and textbook references.</p></div>
<section class="surface p-5 mb-6 space-y-4">
  <input type="search" class="input input-lg input-bordered w-full" placeholder="Search Russian or English…" bind:value={q} on:input={schedule} />
  {#if $reviewMode}
    <div class="flex flex-wrap items-center gap-2 text-sm"><span class="meta-label mr-2">Review status</span>
      {#each ['visible','all','unreviewed','kept','followup','hidden'] as option}
        <button class={`btn btn-sm ${status===option?'btn-primary':'btn-ghost'}`} on:click={() => {status=option;schedule();}}>{option}</button>
      {/each}
    </div>
  {/if}
  <button class="btn btn-sm btn-ghost" on:click={() => advanced=!advanced}> {advanced?'▾':'▸'} Filters: book, page, tags, grammar</button>
  {#if advanced}
    <div class="grid md:grid-cols-2 gap-4 pt-3 border-t border-base-300">
      <label class="field"><span>Book</span><select class="select select-bordered" bind:value={bookId} on:change={schedule}><option value="">Any book</option>{#each books as b}<option value={String(b.id)}>{b.title} {b.edition}</option>{/each}</select></label>
      <label class="field"><span>Part of speech</span><select bind:value={pos} on:change={schedule}><option value="">Any</option>{#each meta?.parts_of_speech || [] as p}<option value={p.code}>{p.label}</option>{/each}</select></label>
      <label class="field"><span>Entry type</span><select bind:value={kind} on:change={schedule}><option value="">All</option><option value="word">Words</option><option value="expression">Expressions</option></select></label>
      <label class="field"><span>Page numbering</span><select bind:value={pageKind} on:change={schedule}><option value="pdf">PDF page</option><option value="printed">Printed page</option></select></label>
      <label class="field"><span>From page</span><input type="text" inputmode="numeric" bind:value={pageFrom} on:input={schedule} /></label>
      <label class="field"><span>To page</span><input type="text" inputmode="numeric" bind:value={pageTo} on:input={schedule} /></label>
    </div>
    {#each ['grammatical','semantic','usage'] as category}
      <div class="pt-3 border-t border-base-300"><p class="meta-label mb-2">{category} tags</p><div class="flex flex-wrap gap-2">
        {#each tags.filter(t=>t.category===category) as t}
          <button class={`badge cursor-pointer ${selectedTags.includes(t.id)?'badge-primary':'badge-outline'}`}
            on:click={() => tagSwitch(t.id)}>{t.name} · {t.word_count}</button>
        {/each}
      </div></div>
    {/each}
    <p class="text-xs opacity-55">Selected tags must all belong to one active sense.</p>
  {/if}
</section>
<div class="flex justify-between items-center mb-3"><h3 class="text-lg font-semibold">Entries <span class="text-base-content/50">{results?.total ?? '—'}</span></h3>
  <span class="text-xs opacity-60">{busy?'Searching…':q?'Relevance order':'Original entry order'}</span></div>
{#if error}<div class="alert alert-error mb-4">{error}<button class="btn btn-sm" on:click={load}>Retry</button></div>{/if}
<section class="surface divide-y divide-base-300">
  {#if !results && busy}<div class="p-8 text-center"><span class="loading loading-spinner"></span></div>{/if}
  {#if results?.items.length===0}<div class="p-10 text-center opacity-70">No matching entries.</div>{/if}
  {#each results?.items || [] as w (w.id)}
    <a href={`/word/${w.id}`} class="block p-4 md:p-5 hover:bg-base-200/50 transition-colors" on:click={(e)=>{e.preventDefault();navigate(`/word/${w.id}`);}}>
      <div class="flex gap-3 items-center flex-wrap"><strong class="russian text-xl">{w.lemma}</strong>
        <span class="badge badge-ghost">{w.pos}</span>{#if w.aspect}<span class="badge badge-outline">{w.aspect}</span>{/if}
        {#if $reviewMode}<span class="badge badge-warning">{w.human_status}</span>{/if}</div>
      <p class="text-sm opacity-75 mt-1">{w.gloss_preview || 'No sense recorded'}</p>
      <div class="flex gap-2 flex-wrap mt-2">{#each w.tags.slice(0,5) as tag}<span class="badge badge-sm badge-outline">{tag.name}</span>{/each}
        <span class="text-xs opacity-50">{w.page_count} pages</span></div>
    </a>
  {/each}
</section>
{#if results && results.pages>1}
  <div class="join flex justify-center mt-5"><button class="btn join-item" disabled={page<=1} on:click={()=>{page--;load();}}>Previous</button>
    <button class="btn join-item btn-disabled">{page} / {results.pages}</button>
    <button class="btn join-item" disabled={page>=results.pages} on:click={()=>{page++;load();}}>Next</button></div>
{/if}
{#if $editMode}<button class="btn btn-primary mt-6" on:click={()=>navigate('/new')}>+ Add entry</button>{/if}
