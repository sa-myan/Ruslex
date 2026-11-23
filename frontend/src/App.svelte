<script lang="ts">
  import { onMount } from 'svelte';
  import { user, currentPath, editMode, reviewMode, refreshUser, navigate, mutate } from './lib/api';
  import { theme, toggleTheme } from './lib/theme';
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
  let desktopSidebar = false;
  let headerVisible = true;
  let error = '';
  let menuButton: HTMLButtonElement;

  function closeMenu() {
    menuOpen = false;
  }

  function goTo(path: string) {
    closeMenu();
    headerVisible = true;
    navigate(path);
  }

  async function logout() {
    try {
      await mutate('/api/auth/logout', 'POST');
      await refreshUser();
      goTo('/');
    } catch (err) {
      error = String(err);
    }
  }

  onMount(() => {
    let previousY = window.scrollY;
    const desktop = window.matchMedia('(min-width: 1024px) and (orientation: landscape)');
    function onLayoutChange() {
      desktopSidebar = desktop.matches;
      if (desktopSidebar) closeMenu();
    }
    function onScroll() {
      const currentY = window.scrollY;
      const movement = currentY - previousY;
      if (currentY < 90 || menuOpen) headerVisible = true;
      else if (movement > 8) headerVisible = false;
      else if (movement < -8) headerVisible = true;
      if (Math.abs(movement) > 8) previousY = currentY;
    }
    function onKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape' && menuOpen) {
        closeMenu();
        menuButton?.focus();
      }
    }
    onLayoutChange();
    desktop.addEventListener('change', onLayoutChange);
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('keydown', onKeydown);
    void refreshUser()
      .catch((err) => { error = String(err); })
      .finally(() => { ready = true; });
    return () => {
      desktop.removeEventListener('change', onLayoutChange);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('keydown', onKeydown);
      document.body.classList.remove('ruslex-drawer-open');
    };
  });

  $: document.body.classList.toggle('ruslex-drawer-open', menuOpen && !desktopSidebar);
  $: path = $currentPath;
  $: wordMatch = path.match(/^\/word\/(\d+)(\/references)?$/);
</script>

<svelte:head>
  <title>Russian Lexicon</title>
  <meta name="description" content="A learner-friendly Russian vocabulary library" />
</svelte:head>

<div class="app-shell bg-base-200/70">
  {#if menuOpen && !desktopSidebar}
    <button class="app-backdrop" aria-label="Close navigation" on:click={closeMenu}></button>
  {/if}

  <aside
    id="ruslex-navigation"
    class:drawer-open={menuOpen}
    class="app-sidebar bg-base-100 border-r border-base-300"
    aria-label="Primary navigation"
    aria-hidden={!desktopSidebar && !menuOpen}
    inert={!desktopSidebar && !menuOpen}
  >
    <div class="p-5 flex items-center justify-between gap-2">
      <a href="/" class="flex items-center gap-3 min-w-0" on:click={(event) => { event.preventDefault(); goTo('/'); }}>
        <span class="flex shrink-0 items-center justify-center w-11 h-11 rounded-xl bg-primary text-primary-content font-bold text-2xl">Я</span>
        <div class="min-w-0">
          <h1 class="font-bold text-lg leading-tight">Russian Lexicon</h1>
          <p class="text-xs opacity-60">Language workspace</p>
        </div>
      </a>
      <button class="btn btn-ghost btn-sm sidebar-close" aria-label="Close menu" on:click={closeMenu}>✕</button>
    </div>

    <nav class="p-3 space-y-1" aria-label="Dictionary pages">
      <NavLink href="/" title="Dictionary" symbol="⌕" onNavigate={closeMenu} />
      <NavLink href="/stats" title="Statistics" symbol="▤" onNavigate={closeMenu} />
      {#if $reviewMode}<NavLink href="/review" title="Fast review" symbol="◈" onNavigate={closeMenu} />{/if}
      {#if $editMode}<NavLink href="/new" title="Add entry" symbol="＋" onNavigate={closeMenu} />{/if}
    </nav>

    <div class="mt-auto p-4 border-t border-base-300 space-y-4">
      {#if $user?.can_review}
        <label class="flex justify-between items-center gap-3 text-sm">
          <span>Review mode</span>
          <input class="toggle toggle-primary toggle-sm" type="checkbox" bind:checked={$reviewMode} />
        </label>
      {/if}
      {#if $user?.can_edit}
        <label class="flex justify-between items-center gap-3 text-sm">
          <span>Edit mode</span>
          <input class="toggle toggle-primary toggle-sm" type="checkbox" bind:checked={$editMode} />
        </label>
      {/if}
      <div class="flex items-center justify-between gap-2">
        <span class="text-sm">Appearance</span>
        <button class="btn btn-outline btn-sm" on:click={toggleTheme} aria-label={`Switch to ${$theme === 'dark' ? 'light' : 'dark'} theme`}>
          {$theme === 'dark' ? '☀ Light' : '☾ Dark'}
        </button>
      </div>
      <div class="pt-3 border-t border-base-300 space-y-2">
        {#if $user?.authenticated}
          <div class="text-sm font-medium break-words">{$user.username}</div>
          {#if $user.is_staff}<a href="/admin/" class="btn btn-outline btn-sm w-full">Django Admin</a>{/if}
          <button class="btn btn-ghost btn-sm w-full" on:click={logout}>Sign out</button>
        {:else}
          <button class="btn btn-outline btn-sm w-full" on:click={() => goTo('/login')}>Sign in</button>
        {/if}
      </div>
      <div class="text-xs opacity-60">SQLite · Django · Svelte</div>
    </div>
  </aside>

  <div class="app-content" inert={menuOpen && !desktopSidebar}>
    <header class:header-hidden={!headerVisible && !menuOpen} class="app-header bg-base-100 border-b border-base-300">
      <div class="px-4 md:px-8 py-3 flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 min-w-0">
          <button
            bind:this={menuButton}
            class="btn btn-ghost btn-square menu-trigger"
            aria-label="Open navigation menu"
            aria-controls="ruslex-navigation"
            aria-expanded={menuOpen}
            on:click={() => { menuOpen = true; headerVisible = true; }}
          >☰</button>
          <span class="font-semibold opacity-80 truncate">Russian language desk</span>
        </div>
        <button
          class="btn btn-ghost btn-sm shrink-0"
          on:click={toggleTheme}
          aria-label={`Switch to ${$theme === 'dark' ? 'light' : 'dark'} theme`}
          title={`Switch to ${$theme === 'dark' ? 'light' : 'dark'} theme`}
        >{$theme === 'dark' ? '☀ Light' : '☾ Dark'}</button>
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
      {:else}<div class="surface p-8">Page not found. <button class="link" on:click={() => goTo('/')}>Return to dictionary</button></div>{/if}
    </main>
  </div>
</div>
