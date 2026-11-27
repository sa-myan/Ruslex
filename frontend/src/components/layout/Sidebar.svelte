<script lang="ts">
  import { editMode, reviewMode, workMode, user } from '../../lib/session';
  import { theme, toggleTheme } from '../../lib/theme';
  import NavLink from '../NavLink.svelte';

  interface Props {
    onNavigate: (path: string) => void;
    onClose: () => void;
    onLogout: () => Promise<void>;
    isOpen?: boolean;
    isDesktop?: boolean;
  }

  let { onNavigate, onClose, onLogout, isOpen = false, isDesktop = false }: Props = $props();

</script>

<aside
  id="ruslex-navigation"
  class="app-sidebar bg-base-100 border-r border-base-300"
  class:drawer-open={isOpen}
  aria-label="Primary navigation"
  aria-hidden={!isDesktop && !isOpen}
  inert={!isDesktop && !isOpen}
>
  <div class="p-5 flex items-center justify-between gap-2">
    <a
      href="/"
      class="flex items-center gap-3 min-w-0"
      onclick={(event) => { event.preventDefault(); onNavigate('/'); }}
    >
      <span class="flex shrink-0 items-center justify-center w-11 h-11 rounded-xl bg-primary text-primary-content font-bold text-2xl">Я</span>
      <div class="min-w-0">
        <h1 class="font-bold text-lg leading-tight">Russian Lexicon</h1>
        <p class="text-xs opacity-60">Language workspace</p>
      </div>
    </a>
    <button class="btn btn-ghost btn-sm sidebar-close" aria-label="Close menu" onclick={onClose}>
      ✕
    </button>
  </div>

  <nav class="p-3 space-y-1" aria-label="Dictionary pages">
    <NavLink href="/" title="Dictionary" symbol="⌕" onNavigate={onClose} />
    <NavLink href="/stats" title="Statistics" symbol="▤" onNavigate={onClose} />
    <NavLink href="/constructions" title="Constructions" symbol="◇" onNavigate={onClose} />
    {#if $reviewMode}
      <NavLink href="/review" title="Fast review" symbol="◈" onNavigate={onClose} />
      <NavLink href="/construction-review" title="Construction review" symbol="◇" onNavigate={onClose} />
    {/if}
    {#if $editMode}
      <NavLink href="/pronunciation-review" title="Pronunciation review" symbol="◉" onNavigate={onClose} />
      <NavLink href="/new" title="Add entry" symbol="＋" onNavigate={onClose} />
    {/if}
  </nav>

  <div class="mt-auto p-4 border-t border-base-300 space-y-4">
    {#if $user?.can_review || $user?.can_edit}
      <label class="flex justify-between items-center gap-3 text-sm">
        <span>Edit &amp; review mode</span>
        <input class="toggle toggle-primary toggle-sm" type="checkbox" bind:checked={$workMode} />
      </label>
    {/if}
    <div class="flex items-center justify-between gap-2">
      <span class="text-sm">Appearance</span>
      <button
        class="btn btn-outline btn-sm"
        onclick={toggleTheme}
        aria-label={`Switch to ${$theme === 'dark' ? 'light' : 'dark'} theme`}
      >
        {$theme === 'dark' ? '☀ Light' : '☾ Dark'}
      </button>
    </div>
    <div class="pt-3 border-t border-base-300 space-y-2">
      {#if $user?.authenticated}
        <div class="text-sm font-medium break-words">{$user.username}</div>
        {#if $user.is_staff}
          <a href="/admin/" class="btn btn-outline btn-sm w-full">Django Admin</a>
        {/if}
        <button class="btn btn-ghost btn-sm w-full" onclick={onLogout}>Sign out</button>
      {:else}
        <button class="btn btn-outline btn-sm w-full" onclick={() => onNavigate('/login')}>Sign in</button>
      {/if}
    </div>
    <div class="text-xs opacity-60">SQLite · Django · Svelte</div>
  </div>
</aside>
