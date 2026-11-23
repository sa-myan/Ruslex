<script lang="ts">
  import {user,refreshUser,mutate,navigate} from '../lib/api';
  let username='';let password='';let email='';let register=false;let error='';let done='';
  async function submit(){error='';done='';try{
    if(register){await mutate('/api/auth/signup','POST',{username,email,password});done='Account created. You can sign in now.';register=false;password='';}
    else{await mutate('/api/auth/login','POST',{username,password});await refreshUser();navigate('/');}
  }catch(e){error=(e as Error).message;}}
</script>
<section class="surface p-6 max-w-md mx-auto"><p class="kicker">Account</p><h2 class="text-2xl font-bold my-3">{register?'Create an account':'Sign in'}</h2>
  <form class="space-y-4" on:submit|preventDefault={submit}>
    <label class="field"><span>Username</span><input bind:value={username} required maxlength="150" autocomplete="username"/></label>
    {#if register}<label class="field"><span>Email</span><input type="email" bind:value={email} required autocomplete="email" /></label>{/if}
    <label class="field"><span>Password</span><input type="password" bind:value={password} required autocomplete={register?'new-password':'current-password'}/></label>
    {#if error}<div class="alert alert-error">{error}</div>{/if}{#if done}<div class="alert alert-success">{done}</div>{/if}
    <button class="btn btn-primary w-full">{register?'Create account':'Sign in'}</button>
  </form>
  {#if $user?.registration_open}<button class="btn btn-link mt-3" on:click={()=>{register=!register;error='';}}>{register?'Already have an account? Sign in':'Create an account'}</button>{/if}
  <p class="text-xs opacity-60 mt-4">New accounts do not receive editor or reviewer privileges. An administrator grants access.</p>
</section>
