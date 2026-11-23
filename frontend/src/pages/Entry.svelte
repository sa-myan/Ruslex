<script lang="ts">
  import { onMount } from 'svelte';
  import { request,mutate,navigate,editMode,reviewMode,user } from '../lib/api';
  import type {Entry as EntryType,Metadata,Summary,Status} from '../lib/types';
  import SenseCard from '../components/SenseCard.svelte';
  import RelationList from '../components/RelationList.svelte';
  import EntryPicker from '../components/EntryPicker.svelte';
  export let wordId:number;
  let entry:EntryType|null=null;let meta:Metadata|null=null;let busy=true;let error='';let notice='';
  let showArchived=false;let editIdentity=false;let lemma='';let pos='NOUN';let entryType='word';let aspect='';let animacy='';
  let notes='';let newSense=false;let newMeaning='';let newDescription='';
  let newLink=false;let linkId:number|null=null;let label='';let url='';
  let newComponent=false;let selected:Summary|null=null;let compPosition=1;let compSurface='';let compNotes='';let compId:number|null=null;
  onMount(()=>{refresh();request<Metadata>('/api/meta').then(x=>meta=x).catch(()=>{});});
  async function refresh(){busy=true;error='';try{entry=await request<EntryType>(`/api/lexemes/${wordId}`);
    notes=entry.notes;lemma=entry.lemma;pos=entry.pos;entryType=entry.entry_type;aspect=entry.aspect||'';animacy=entry.animacy||'';
  }catch(e){error=(e as Error).message;}finally{busy=false;}}
  async function doUpdate(body:object){error='';try{await mutate(`/api/lexemes/${wordId}`,'PATCH',body);notice='Saved';await refresh();}
    catch(e){error=(e as Error).message;}}
  async function saveIdentity(){await doUpdate({lemma,pos,entry_type:entryType,aspect:aspect||null,animacy:animacy||null});editIdentity=false;}
  async function saveSense(){try{await mutate(`/api/lexemes/${wordId}/senses`,'POST',{meaning:newMeaning,description:newDescription});newSense=false;newMeaning='';newDescription='';await refresh();}
    catch(e){error=(e as Error).message;}}
  async function saveLink(){try{await mutate(`/api/lexemes/${wordId}/external-links${linkId?`/${linkId}`:''}`,linkId?'PUT':'POST',{label,url});newLink=false;linkId=null;await refresh();}
    catch(e){error=(e as Error).message;}}
  function linkEdit(link:EntryType['external_links'][number]){linkId=link.id;label=link.label;url=link.url;newLink=true;}
  async function deleteLink(id:number){if(!confirm('Remove this link?'))return;
    try{await mutate(`/api/lexemes/${wordId}/external-links/${id}`,'DELETE');await refresh();}catch(e){error=(e as Error).message;}}
  function addComponent(){newComponent=true;compId=null;selected=null;compSurface='';compNotes='';
    compPosition=Math.max(0,...(entry?.components.map(c=>c.position)||[]))+1;}
  function editComponent(c:EntryType['components'][number]){newComponent=true;compId=c.id;
    selected={id:c.word_id,lemma:c.word_lemma,pos:c.word_pos} as Summary;
    compPosition=c.position;compSurface=c.surface;compNotes=c.notes;}
  async function saveComponent(){if(!selected){error='Choose a dictionary word';return;}
    try{await mutate(`/api/lexemes/${wordId}/components${compId?`/${compId}`:''}`,compId?'PUT':'POST',
      {word_id:selected.id,position:Number(compPosition),surface:compSurface,notes:compNotes});newComponent=false;await refresh();}
    catch(e){error=(e as Error).message;}}
  async function deleteComponent(id:number){if(!confirm('Remove constituent?'))return;
    try{await mutate(`/api/lexemes/${wordId}/components/${id}`,'DELETE');await refresh();}catch(e){error=(e as Error).message;}}
  function links(lemma:string){const q=encodeURIComponent(lemma);return [
    {label:'Gramota',url:`https://gramota.ru/poisk?mode=slovari&query=${q}`},
    {label:'OpenRussian',url:`https://en.openrussian.org/?search=${q}`},
    {label:'Multitran',url:`https://www.multitran.com/m.exe?l1=2&l2=1&s=${q}`},
    {label:'Wiktionary',url:`https://ru.wiktionary.org/wiki/${q}`}];}
</script>
<button class="btn btn-ghost btn-sm mb-4" on:click={()=>navigate('/')}>← Dictionary</button>
{#if busy && !entry}<div class="loading loading-spinner"></div>{/if}
{#if error}<div class="alert alert-error mb-4">{error}</div>{/if}
{#if notice}<div class="alert alert-success mb-4">{notice}<button class="btn btn-xs" on:click={()=>notice=''}>×</button></div>{/if}
{#if entry}
  <div class="flex flex-wrap items-start justify-between gap-3 mb-6">
    <div><p class="kicker">{entry.entry_type==='expression'?'Expression':'Dictionary entry'}</p>
      <h2 class="text-3xl md:text-4xl russian font-bold mt-2">{entry.lemma}</h2>
      <div class="flex flex-wrap gap-2 mt-3"><span class="badge badge-neutral">{entry.pos}</span>
        {#if entry.aspect}<span class="badge badge-outline">{entry.aspect}</span>{/if}
        {#if entry.animacy}<span class="badge badge-outline">{entry.animacy}</span>{/if}
        {#if $reviewMode}<span class="badge badge-warning">{entry.human_status}</span>{/if}</div>
    </div>
    <div class="flex gap-2 flex-wrap">
      <button class="btn btn-outline btn-sm" on:click={()=>navigate(`/word/${wordId}/references`)}>References ({entry.source_page_count})</button>
      {#if $editMode}<button class="btn btn-primary btn-sm" on:click={()=>editIdentity=!editIdentity}>Edit entry</button>{/if}
    </div>
  </div>
  {#if editIdentity && $editMode}
    <form class="surface p-5 mb-4 space-y-3" on:submit|preventDefault={saveIdentity}>
      <div class="grid md:grid-cols-2 gap-3"><label class="field"><span>Russian headword</span><input bind:value={lemma} required /></label>
        <label class="field"><span>Part of speech</span><select bind:value={pos}>{#each meta?.parts_of_speech || [] as part}<option value={part.code}>{part.label} ({part.code})</option>{/each}</select></label>
        <label class="field"><span>Entry type</span><select bind:value={entryType}><option value="word">Word</option><option value="expression">Expression</option></select></label>
        <label class="field"><span>Aspect</span><select bind:value={aspect}><option value="">Not set</option>{#each meta?.aspects || [] as v}<option value={v}>{v}</option>{/each}</select></label>
        <label class="field"><span>Noun animacy</span><select bind:value={animacy}><option value="">Not set</option>{#each meta?.animacies || [] as v}<option value={v}>{v}</option>{/each}</select></label></div>
      <button class="btn btn-primary">Save details</button><button class="btn ml-2" type="button" on:click={()=>editIdentity=false}>Cancel</button>
    </form>
  {/if}
  {#if $reviewMode && $user?.can_review}
    <section class="surface p-4 mb-4 flex gap-2 items-center flex-wrap">
      <span class="meta-label mr-2">Review</span>
      {#each ['unreviewed','kept','followup','hidden'] as value}
        <button class={`btn btn-sm ${entry.human_status===value?'btn-primary':'btn-outline'}`}
          on:click={()=>doUpdate({human_status:value as Status})}>{value}</button>
      {/each}
    </section>
  {/if}
  <div class="flex justify-between items-center mb-3"><h3 class="text-xl font-semibold">Meanings</h3>
    {#if $editMode}<button class="btn btn-primary btn-sm" on:click={()=>newSense=!newSense}>+ Add meaning</button>{/if}</div>
  {#if newSense && $editMode}<form class="surface p-4 space-y-2 mb-4" on:submit|preventDefault={saveSense}>
    <label class="field"><span>English meaning</span><textarea bind:value={newMeaning} required></textarea></label>
    <label class="field"><span>Description</span><textarea bind:value={newDescription}></textarea></label>
    <button class="btn btn-primary btn-sm">Save meaning</button>
  </form>{/if}
  {#if $editMode}<label class="label text-sm mb-2 gap-2"><input class="checkbox checkbox-sm" type="checkbox" bind:checked={showArchived} />Show archived meanings</label>{/if}
  {#each entry.senses.filter(s=>s.active || ($editMode && showArchived)) as sense (sense.id)}
    <SenseCard {entry} {sense} {refresh} />
  {/each}
  <RelationList {entry} scope={null} {refresh} />
  {#if entry.entry_type==='expression'}<section class="surface p-5 mt-5">
    <div class="panel-header"><h3 class="text-xl font-semibold">Constituent words</h3>
      {#if $editMode}<button class="btn btn-outline btn-sm" on:click={addComponent}>+ Add</button>{/if}</div>
    {#each entry.components as c}<div class="flex flex-wrap gap-3 py-2 border-b border-base-300">
      <span class="opacity-50">{c.position}.</span><a class="link link-primary" href={`/word/${c.word_id}`} on:click={(e)=>{e.preventDefault();navigate(`/word/${c.word_id}`);}}>{c.word_lemma}</a>
      <span>{c.surface}</span>{#if $editMode}<button class="btn btn-xs" on:click={()=>editComponent(c)}>Edit</button><button class="btn btn-xs" on:click={()=>deleteComponent(c.id)}>Remove</button>{/if}
    </div>{/each}
    {#if newComponent && $editMode}<form class="mt-4 space-y-2" on:submit|preventDefault={saveComponent}>
      <div class="field"><span>Constituent word</span><EntryPicker {selected} onSelect={(x)=>selected=x}/></div>
      <label class="field"><span>Position</span><input type="number" min="1" bind:value={compPosition}/></label>
      <label class="field"><span>Surface in expression</span><input bind:value={compSurface}/></label>
      <label class="field"><span>Notes</span><textarea bind:value={compNotes}></textarea></label>
      <button class="btn btn-primary">Save constituent</button><button class="btn ml-2" type="button" on:click={()=>newComponent=false}>Cancel</button></form>{/if}
  </section>{/if}
  {#if entry.occurs_in.length}<section class="surface p-5 mt-5"><h3 class="font-semibold">Occurs in expressions</h3>
    <div class="flex gap-3 flex-wrap mt-3">{#each entry.occurs_in as c}<a class="link link-primary" href={`/word/${c.expression_id}`} on:click={(e)=>{e.preventDefault();navigate(`/word/${c.expression_id}`);}}>{c.expression_lemma}</a>{/each}</div>
  </section>{/if}
  <section class="surface p-5 mt-5"><div class="panel-header"><h3 class="text-xl font-semibold">External dictionaries</h3>
    {#if $editMode}<button class="btn btn-sm btn-outline" on:click={()=>{newLink=true;linkId=null;label='';url='';}}>+ Custom link</button>{/if}</div>
    <div class="flex flex-wrap gap-x-5 gap-y-3">
      {#each links(entry.lemma) as link}
        <div><a class="link link-primary" href={link.url} target="_blank" rel="noopener noreferrer">{link.label} ↗</a></div>
      {/each}
      {#each entry.external_links as link (link.id)}
        <div><a class="link link-primary" href={link.url} target="_blank" rel="noopener noreferrer">{link.label} ↗</a>
          {#if $editMode}<button class="btn btn-ghost btn-xs" on:click={()=>linkEdit(link)}>Edit</button><button class="btn btn-ghost btn-xs" on:click={()=>deleteLink(link.id)}>Remove</button>{/if}
        </div>
      {/each}
    </div>
    {#if newLink && $editMode}<form class="mt-4 space-y-2" on:submit|preventDefault={saveLink}>
      <label class="field"><span>Label</span><input bind:value={label} required maxlength="80" /></label>
      <label class="field"><span>URL</span><input type="url" bind:value={url} required maxlength="2048" /></label>
      <button class="btn btn-primary btn-sm">Save link</button><button class="btn btn-sm ml-2" type="button" on:click={()=>newLink=false}>Cancel</button>
    </form>{/if}
  </section>
  <section class="surface p-5 mt-5"><div class="panel-header"><h3 class="text-xl font-semibold">Textbook evidence</h3>
    <button class="btn btn-outline btn-sm" on:click={()=>navigate(`/word/${wordId}/references`)}>All references</button></div>
    {#each entry.sources as source}<div class="py-2 border-b border-base-300"><div class="text-xs opacity-60">{source.title} · PDF {source.pdf_page} · printed {source.printed_page} · {source.surface}</div>
      <p class="russian text-sm mt-1">{source.context}</p></div>{/each}
  </section>
  {#if $editMode}<section class="surface p-5 mt-5"><h3 class="font-semibold mb-3">Private working notes</h3>
    <form on:submit|preventDefault={()=>doUpdate({notes})}><textarea class="textarea textarea-bordered w-full" rows="4" bind:value={notes}></textarea>
    <button class="btn btn-primary btn-sm mt-2">Save notes</button></form></section>{/if}
{/if}
