<script lang="ts">
  import { currentPath, navigate } from '../lib/api';
  export let href:string;
  export let title:string;
  export let symbol = '•';
  export let onNavigate: () => void = () => {};
</script>
<a {href} class={`flex items-center gap-3 rounded-lg px-4 py-3 hover:bg-base-200 transition-colors ${$currentPath === href ? "bg-primary/10 font-semibold" : ""}`} on:click={(event) => {event.preventDefault();onNavigate();navigate(href);}}>
  <span class="text-xl opacity-70">{symbol}</span><span>{title}</span>
</a>
