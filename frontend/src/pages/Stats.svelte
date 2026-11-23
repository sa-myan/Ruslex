<script lang="ts">
  import {onMount} from 'svelte';
  import {request} from '../lib/api';
  import type {Stats} from '../lib/types';
  let stats:Stats|null=null;let error='';
  onMount(()=>{request<Stats>('/api/stats').then(x=>stats=x).catch(e=>error=e.message);});
</script>
<p class="kicker">Overview</p><h2 class="text-3xl font-bold mt-2 mb-6">Statistics</h2>
{#if error}<div class="alert alert-error">{error}</div>{/if}
{#if stats}<div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
  {#each Object.entries(stats.counts) as [title,count]}<div class="surface p-5"><p class="meta-label">{title}</p><p class="text-3xl font-semibold mt-3">{count.toLocaleString()}</p></div>{/each}
</div><div class="grid md:grid-cols-2 gap-4 mt-5">
  <section class="surface p-5"><h3 class="font-bold mb-3">Entry review statuses</h3>{#each Object.entries(stats.word_status) as [status,count]}<p class="py-2 flex justify-between border-b border-base-300"><span>{status}</span><strong>{count}</strong></p>{/each}</section>
  <section class="surface p-5"><h3 class="font-bold mb-3">OCR review statuses</h3>{#each Object.entries(stats.review_status) as [status,count]}<p class="py-2 flex justify-between border-b border-base-300"><span>{status}</span><strong>{count}</strong></p>{/each}</section>
</div>{:else if !error}<span class="loading loading-spinner"></span>{/if}
