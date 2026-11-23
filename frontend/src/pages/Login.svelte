<script lang="ts">
  import { mutate } from '../lib/http';
  import { navigate } from '../lib/navigation';
  import { refreshUser, user } from '../lib/session';
  import { errorMessage } from '../lib/errors';

  let username = $state('');
  let password = $state('');
  let email = $state('');
  let register = $state(false);
  let busy = $state(false);
  let error = $state('');
  let successMessage = $state('');

  async function submit(): Promise<void> {
    if (busy) return;
    busy = true;
    error = '';
    successMessage = '';

    try {
      if (register) {
        await mutate('/api/auth/signup', 'POST', { username, email, password });
        successMessage = 'Account created. You can sign in now.';
        register = false;
        password = '';
      } else {
        await mutate('/api/auth/login', 'POST', { username, password });
        await refreshUser();
        navigate('/');
      }
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }
</script>

<section class="surface p-6 max-w-md mx-auto">
  <p class="kicker">Account</p>
  <h2 class="text-2xl font-bold my-3">{register ? 'Create an account' : 'Sign in'}</h2>
  <form class="space-y-4" onsubmit={(event) => { event.preventDefault(); void submit(); }}>
    <label class="field">
      <span>Username</span>
      <input bind:value={username} required maxlength="150" autocomplete="username" />
    </label>
    {#if register}
      <label class="field">
        <span>Email</span>
        <input type="email" bind:value={email} required autocomplete="email" />
      </label>
    {/if}
    <label class="field">
      <span>Password</span>
      <input
        type="password"
        bind:value={password}
        required
        autocomplete={register ? 'new-password' : 'current-password'}
      />
    </label>
    {#if error}<div class="alert alert-error" role="alert">{error}</div>{/if}
    {#if successMessage}<div class="alert alert-success">{successMessage}</div>{/if}
    <button class="btn btn-primary w-full" disabled={busy}>
      {busy ? 'Submitting…' : register ? 'Create account' : 'Sign in'}
    </button>
  </form>
  {#if $user?.registration_open}
    <button class="btn btn-link mt-3" onclick={() => { register = !register; error = ''; }}>
      {register ? 'Already have an account? Sign in' : 'Create an account'}
    </button>
  {/if}
  <p class="text-xs opacity-60 mt-4">
    New accounts do not receive editor or reviewer privileges. An administrator grants access.
  </p>
</section>
