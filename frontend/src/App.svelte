<script lang="ts">
  import { onMount } from 'svelte';
  import { user, currentPath, editMode, reviewMode, refreshUser, navigate, mutate } from './lib/api';
  import NavLink from './components/NavLink.svelte';
  import Search from './pages/Search.svelte';
  import Entry from './pages/Entry.svelte';
  import References from './pages/References.svelte';
  import Stats from './pages/Stats.svelte';
  import Review from './pages/Review.svelte';
  import NewEntry from './pages/NewEntry.svelte';
  import Login from './pages/Login.svelte';
  let ready = false;
  let menuOpen = false;
  let error = '';
  onMount(async () => {
    try { await refreshUser(); } catch (err) { error = String(err); }
    finally { ready=true; }
  });
  async function logout() {
    try { await mutate('/api/auth/logout', 'POST'); await refreshUser(); navigate('/'); }
    catch(e) { error = String(e); }
  }
  $: path = $currentPath;
  $: wordMatch = path.match(/^\/word\/(\d+)(\/references)?$/);
</script>
<svelte:head><title>Russian Lexicon</title><meta name="description" content="A learner-friendly Russian vocabulary library" /></svelte:head>
<div class="min-h-screen lg:flex bg-base-200/70">
  <aside class="lg:w-64 lg:min-h-screen bg-base-100 border-r border-base-300 lg:sticky lg:top-0 lg:h-screen">
    <div class="p-5 flex items-center justify-between">
      <a href="/" class="flex items-center gap-3" on:click={(e) => {e.preventDefault(); navigate('/');}}>
        <span class="flex items-center justify-center w-11 h-11 rounded-xl bg-primary text-primary-content font-bold text-2xl">Я</span>
        <div><h1 class="font-bold text-lg leading-tight">Russian Lexicon</h1><p class="text-xs opacity-60">Language workspace</p></div>
      </a>
      <button class="btn btn-ghost btn-sm lg:hidden" on:click={() => menuOpen=!menuOpen} aria-label="Menu">☰</button>
    </div>
    <nav class={`p-3 space-y-1 ${menuOpen ? '' : 'hidden'} lg:block`} on:click={() => menuOpen=false}>
      <NavLink href="/" title="Dictionary" symbol="⌕" />
      <NavLink href="/stats" title="Statistics" symbol="▤" />
      {#if $reviewMode}<NavLink href="/review" title="Fast review" symbol="◈" />{/if}
      {#if $editMode}<NavLink href="/new" title="Add entry" symbol="＋" />{/if}
    </nav>
    <div class="p-4 border-t border-base-300 lg:absolute lg:bottom-0 lg:w-64 space-y-3">
      {#if $user?.can_review}
        <label class="flex justify-between items-center text-sm"><span>Review mode</span>
          <input class="toggle toggle-primary toggle-sm" type="checkbox" bind:checked={$reviewMode} /></label>
      {/if}
      {#if $user?.can_edit}
        <label class="flex justify-between items-center text-sm"><span>Edit mode</span>
          <input class="toggle toggle-primary toggle-sm" type="checkbox" bind:checked={$editMode} /></label>
      {/if}
      <div class="text-xs opacity-60">SQLite · Django · Svelte</div>
    </div>
  </aside>
  <div class="flex-1 min-w-0">
    <header class="bg-base-100 border-b border-base-300 px-5 md:px-10 py-4 flex flex-wrap justify-between items-center gap-3">
      <span class="font-semibold opacity-80">Russian language desk</span>
      <div class="flex gap-2 items-center">
        {#if $user?.authenticated}
          <span class="text-sm opacity-70">{$user.username}</span>
          {#if $user.is_staff}<a href="/admin/" class="btn btn-outline btn-sm">Admin</a>{/if}
          <button class="btn btn-ghost btn-sm" on:click={logout}>Sign out</button>
        {:else}<button class="btn btn-outline btn-sm" on:click={() => navigate('/login')}>Sign in</button>{/if}
      </div>
    </header>
    <main class="content-wrap px-4 py-6 md:p-10">
      {#if error}<div class="alert alert-error mb-4">{error}</div>{/if}
      {#if !ready}<div class="loading loading-spinner"></div>
      {:else if path === '/'}<Search />
      {:else if wordMatch && wordMatch[2]}{#key wordMatch[1]}<References wordId={Number(wordMatch[1])} />{/key}
      {:else if wordMatch}{#key wordMatch[1]}<Entry wordId={Number(wordMatch[1])} />{/key}
      {:else if path === '/stats'}<Stats />
      {:else if path === '/review' && $reviewMode}<Review />
      {:else if path === '/new' && $editMode}<NewEntry />
      {:else if path === '/login'}<Login />
      {:else}<div class="surface p-8">Page not found. <button class="link" on:click={() => navigate('/')}>Return to dictionary</button></div>{/if}
    </main>
  </div>
</div>
