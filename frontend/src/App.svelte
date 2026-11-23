<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { currentPath, navigate } from './lib/navigation';
  import { editMode, reviewMode, refreshUser } from './lib/session';
  import { mutate } from './lib/http';
  import { errorMessage } from './lib/errors';
  import { theme, toggleTheme } from './lib/theme';

  import Sidebar from './components/layout/Sidebar.svelte';
  import Search from './pages/Search.svelte';
  import Entry from './pages/Entry.svelte';
  import References from './pages/References.svelte';
  import Stats from './pages/Stats.svelte';
  import Review from './pages/Review.svelte';
  import NewEntry from './pages/NewEntry.svelte';
  import Login from './pages/Login.svelte';

  let ready = $state(false);
  let menuOpen = $state(false);
  let desktopSidebar = $state(false);
  let headerVisible = $state(true);
  let error = $state('');
  let menuButton = $state<HTMLButtonElement>();

  let path = $derived($currentPath);
  let wordMatch = $derived(path.match(/^\/word\/(\d+)(\/references)?$/));
  $effect(() => {
    document.body.classList.toggle('ruslex-drawer-open', menuOpen && !desktopSidebar);
  });

  function closeMenu(): void {
    const shouldRestoreFocus = menuOpen && !desktopSidebar;
    menuOpen = false;
    if (shouldRestoreFocus) {
      void tick().then(() => menuButton?.focus());
    }
  }

  function goTo(path: string): void {
    closeMenu();
    headerVisible = true;
    navigate(path);
  }

  async function openMenu(): Promise<void> {
    menuOpen = true;
    headerVisible = true;
    await tick();
    document.querySelector<HTMLElement>('#ruslex-navigation a')?.focus();
  }

  async function logout(): Promise<void> {
    try {
      await mutate('/api/auth/logout', 'POST');
      await refreshUser();
      goTo('/');
    } catch (err) {
      error = errorMessage(err);
    }
  }

  onMount(() => {
    let previousY = window.scrollY;
    const layout = window.matchMedia('(min-width: 1024px) and (orientation: landscape)');

    function updateLayout(): void {
      desktopSidebar = layout.matches;
      if (desktopSidebar) closeMenu();
    }

    function updateHeader(): void {
      const currentY = window.scrollY;
      const movement = currentY - previousY;

      if (currentY < 90 || menuOpen) headerVisible = true;
      else if (movement > 8) headerVisible = false;
      else if (movement < -8) headerVisible = true;

      if (Math.abs(movement) > 8) previousY = currentY;
    }

    function handleKeys(event: KeyboardEvent): void {
      if (!menuOpen || desktopSidebar) return;

      if (event.key === 'Escape') {
        closeMenu();
      }
      if (event.key !== 'Tab') return;

      const drawer = document.getElementById('ruslex-navigation');
      const elements = Array.from(
        drawer?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled])') ?? [],
      ).filter((item) => item.getClientRects().length > 0);
      if (!elements.length) return;

      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    updateLayout();
    layout.addEventListener('change', updateLayout);
    window.addEventListener('scroll', updateHeader, { passive: true });
    window.addEventListener('keydown', handleKeys);

    void refreshUser()
      .catch((err) => { error = errorMessage(err); })
      .finally(() => { ready = true; });

    return () => {
      layout.removeEventListener('change', updateLayout);
      window.removeEventListener('scroll', updateHeader);
      window.removeEventListener('keydown', handleKeys);
      document.body.classList.remove('ruslex-drawer-open');
    };
  });
</script>

<svelte:head>
  <title>Russian Lexicon</title>
  <meta name="description" content="A learner-friendly Russian vocabulary library" />
</svelte:head>

<div class="app-shell bg-base-200/70">
  {#if menuOpen && !desktopSidebar}
    <button class="app-backdrop" aria-label="Close navigation" onclick={closeMenu}></button>
  {/if}

  <Sidebar
    isOpen={menuOpen}
    isDesktop={desktopSidebar}
    onNavigate={goTo}
    onClose={closeMenu}
    onLogout={logout}
  />

  <div class="app-content" inert={menuOpen && !desktopSidebar}>
    <header class="app-header bg-base-100 border-b border-base-300" class:header-hidden={!headerVisible && !menuOpen}>
      <div class="px-4 md:px-8 py-3 flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 min-w-0">
          <button
            bind:this={menuButton}
            class="btn btn-ghost btn-square menu-trigger"
            aria-label="Open navigation menu"
            aria-controls="ruslex-navigation"
            aria-expanded={menuOpen}
            onclick={openMenu}
          >☰</button>
          <span class="font-semibold opacity-80 truncate">Russian language desk</span>
        </div>
        <button
          class="btn btn-ghost btn-sm shrink-0"
          onclick={toggleTheme}
          aria-label={`Switch to ${$theme === 'dark' ? 'light' : 'dark'} theme`}
          title={`Switch to ${$theme === 'dark' ? 'light' : 'dark'} theme`}
        >{$theme === 'dark' ? '☀ Light' : '☾ Dark'}</button>
      </div>
    </header>

    <main class="content-wrap px-4 py-6 md:p-10">
      {#if error}<div class="alert alert-error mb-4" role="alert">{error}</div>{/if}
      {#if !ready}
        <div class="loading loading-spinner"></div>
      {:else if path === '/'}
        <Search />
      {:else if wordMatch && wordMatch[2]}
        {#key wordMatch[1]}<References wordId={Number(wordMatch[1])} />{/key}
      {:else if wordMatch}
        {#key wordMatch[1]}<Entry wordId={Number(wordMatch[1])} />{/key}
      {:else if path === '/stats'}
        <Stats />
      {:else if path === '/review' && $reviewMode}
        <Review />
      {:else if path === '/new' && $editMode}
        <NewEntry />
      {:else if path === '/login'}
        <Login />
      {:else}
        <div class="surface p-8">Page not found. <button class="link" onclick={() => goTo('/')}>Return to dictionary</button></div>
      {/if}
    </main>
  </div>
</div>
