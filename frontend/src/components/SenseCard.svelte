<script lang="ts">
  import { mutate, editMode } from '../lib/api';
  import type { Entry, Sense } from '../lib/types';
  import RecordList from './RecordList.svelte';
  import RelationList from './RelationList.svelte';
  export let entry:Entry;
  export let sense:Sense;
  export let refresh:()=>void;
  let editing=false;let meaning='';let description='';let tagName='';let category='semantic';let error='';
  function start(){editing=true;meaning=sense.meaning;description=sense.description;error='';}
  async function save(){try{await mutate(`/api/lexemes/${entry.id}/senses/${sense.id}`,'PUT',{meaning,description});editing=false;refresh();}
    catch(e){error=(e as Error).message;}}
  async function active(){try{await mutate(`/api/lexemes/${entry.id}/records/senses/${sense.id}/active`,'PATCH',{active:!sense.active});refresh();}
    catch(e){error=(e as Error).message;}}
  async function addTag(){try{await mutate(`/api/lexemes/${entry.id}/senses/${sense.id}/tags`,'POST',{name:tagName,category});tagName='';refresh();}
    catch(e){error=(e as Error).message;}}
  async function removeTag(id:number){try{await mutate(`/api/lexemes/${entry.id}/senses/${sense.id}/tags/${id}`,'DELETE');refresh();}
    catch(e){error=(e as Error).message;}}
</script>
<article class:opacity-50={!sense.active} class="surface p-5 mb-4">
  <div class="flex justify-between gap-3 mb-2"><div class="flex gap-2 items-start"><span class="text-xs badge badge-ghost">#{sense.id}</span>
    <h3 class="text-xl font-semibold">{sense.meaning}</h3></div>
    {#if $editMode}<div class="flex gap-1"><button class="btn btn-xs btn-outline" on:click={start}>Edit</button>
      <button class="btn btn-xs btn-ghost" on:click={active}>{sense.active?'Archive':'Restore'}</button></div>{/if}
  </div>
  {#if sense.description}<p class="opacity-70 text-sm mb-3">{sense.description}</p>{/if}
  {#if sense.tags.length}<div class="flex gap-2 flex-wrap">{#each sense.tags as tag}<span class="badge badge-outline badge-sm">{tag.name}
    {#if $editMode}<button class="ml-1" aria-label="Remove tag" on:click={()=>removeTag(tag.id)}>×</button>{/if}</span>{/each}</div>{/if}
  {#if editing && $editMode}<form class="bg-base-200 p-3 rounded-lg mt-3 space-y-2" on:submit|preventDefault={save}>
    <label class="field"><span>Meaning (English)</span><textarea bind:value={meaning} required></textarea></label>
    <label class="field"><span>Description</span><textarea bind:value={description}></textarea></label>
    <button class="btn btn-primary btn-sm">Save</button><button type="button" class="btn btn-sm ml-2" on:click={()=>editing=false}>Cancel</button>
  </form>{/if}
  {#if $editMode}<form class="mt-3 flex gap-2 flex-wrap items-center" on:submit|preventDefault={addTag}>
    <input class="input input-bordered input-sm" placeholder="New tag" bind:value={tagName} required maxlength="48" />
    <select class="select select-bordered select-sm" bind:value={category}><option>semantic</option><option>grammatical</option><option>usage</option></select>
    <button class="btn btn-outline btn-sm">Add tag</button></form>{/if}
  <RecordList wordId={entry.id} senseId={sense.id} kind="patterns" items={sense.patterns} {refresh} />
  <RecordList wordId={entry.id} senseId={sense.id} kind="examples" items={sense.examples} {refresh} />
  <RelationList {entry} scope={sense.id} {refresh}/>
  {#if error}<p class="text-error text-sm mt-2">{error}</p>{/if}
</article>
