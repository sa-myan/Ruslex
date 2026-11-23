<script lang="ts">
  import { mutate, request, editMode, navigate } from '../lib/api';
  import type { Entry, Relation, Summary, Sense } from '../lib/types';
  import EntryPicker from './EntryPicker.svelte';
  export let entry:Entry;
  export let scope:number|null=null;
  export let refresh: () => Promise<boolean>;
  export let onSaved: () => void;
  export let onSaveStart: () => void;
  let show=false;let editId:number|null=null;let selected:Summary|null=null;
  let relationType='related';let ownSense:number|null=null;let otherSense:number|null=null;
  let otherSenses:Sense[]=[];let notes='';let error='';
  $: scoped=entry.relations.filter(r => (r.direction==='outgoing'?r.source_sense_id:r.target_sense_id)===scope);
  async function pick(item:Summary|null){selected=item;otherSense=null;otherSenses=[];
    if(item){try{const detail=await request<Entry>(`/api/lexemes/${item.id}`);otherSenses=detail.senses;}
    catch(e){error=(e as Error).message;}}}
  async function start(item?:Relation){
    editId=item?.id??null;relationType=item?.relation_type??'related';ownSense=scope;
    otherSense=item?(item.direction==='outgoing'?item.target_sense_id:item.source_sense_id):null;
    notes=item?.notes??'';show=true;error='';
    if(item){const candidate={id:item.other_id,lemma:item.other_lemma,pos:item.other_pos} as Summary;await pick(candidate);
      otherSense=item.direction==='outgoing'?item.target_sense_id:item.source_sense_id;
    }else{selected=null;otherSenses=[];}
  }
  async function save(){
    onSaveStart();
    if(!selected){error='Select a related entry';return;}
    error='';try{const url=`/api/lexemes/${entry.id}/relations${editId?`/${editId}`:''}`;
      await mutate(url,editId?'PUT':'POST',{target_lexeme_id:selected.id,relation_type:relationType,
        source_sense_id:ownSense,target_sense_id:otherSense,notes});
      if (await refresh()) { show=false; onSaved(); }
    }catch(e){error=(e as Error).message;}
  }
  async function remove(rel:Relation){if(!confirm(`Remove relationship to ${rel.other_lemma}?`))return;
    onSaveStart();
    error = '';
    try{await mutate(`/api/lexemes/${entry.id}/relations/${rel.id}`,'DELETE');
      if (await refresh()) onSaved();}
    catch(e){error=(e as Error).message;}}
</script>
{#if scoped.length || $editMode}
  <div class="mt-4 rounded-xl p-3 bg-base-200/50 border border-base-300">
    <div class="flex justify-between items-center mb-2"><h4 class="text-sm font-semibold">{scope===null?'Entry-wide relationships':'Related to this meaning'}</h4>
      {#if $editMode}<button class="btn btn-xs btn-outline" on:click={()=>show?show=false:start()}>{show?'Cancel':'+ Link'}</button>{/if}</div>
    {#each scoped as rel (rel.id)}
      <div class="border-t border-base-300 py-2 flex flex-wrap items-center gap-2 text-sm">
        <span class="badge badge-sm">{rel.relation_type.replace('_',' ')}{rel.relation_type==='derivation'?(rel.direction==='outgoing'?' →':' ←'):''}</span>
        <a class="link link-primary russian font-semibold" href={`/word/${rel.other_id}`} on:click={(e)=>{e.preventDefault();navigate(`/word/${rel.other_id}`);}}>{rel.other_lemma}</a>
        {#if rel.other_sense_meaning}<small class="opacity-65">— {rel.other_sense_meaning}</small>{/if}
        {#if rel.notes && $editMode}<small class="opacity-60">{rel.notes}</small>{/if}
        {#if $editMode}<button class="btn btn-ghost btn-xs" on:click={()=>start(rel)}>Edit</button><button class="btn btn-ghost btn-xs" on:click={()=>remove(rel)}>Remove</button>{/if}
      </div>
    {/each}
    {#if show && $editMode}
      <form class="space-y-3 border-t border-base-300 pt-3" on:submit|preventDefault={save}>
        <div class="field"><span>Related entry</span><EntryPicker {selected} onSelect={pick} /></div>
        <label class="field"><span>Relationship type</span><select bind:value={relationType}>{#each ['aspect_pair','synonym','antonym','derivation','related'] as kind}<option value={kind}>{kind.replace('_',' ')}</option>{/each}</select></label>
        {#if scope === null}
          <label class="field"><span>This entry's sense (optional)</span><select bind:value={ownSense}><option value={null}>Whole entry</option>{#each entry.senses as sense}<option value={sense.id}>{sense.meaning}</option>{/each}</select></label>
        {/if}
        <label class="field"><span>Related entry's sense</span><select bind:value={otherSense}><option value={null}>Whole entry</option>{#each otherSenses as sense}<option value={sense.id}>{sense.meaning}</option>{/each}</select></label>
        <label class="field"><span>Private notes</span><textarea bind:value={notes}></textarea></label>
        {#if error}<p class="text-error text-sm">{error}</p>{/if}<button class="btn btn-primary btn-sm">Save relationship</button>
      </form>
    {/if}
  </div>
{/if}
