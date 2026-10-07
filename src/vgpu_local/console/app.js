'use strict';
const $ = id => document.getElementById(id);
const key = location.hash.slice(1);
if (/^[A-Za-z0-9_-]{43}$/.test(key)) sessionStorage.setItem('vgpu-session', key);
history.replaceState(null, '', '/');
const token = sessionStorage.getItem('vgpu-session');
let pending = JSON.parse(localStorage.getItem('vgpu-pending') || 'null');
let busy = false;
async function api(path, body) {
  const response = await fetch('/api/' + path, {method: body ? 'POST' : 'GET', cache: 'no-store',
    headers: {Authorization: 'Bearer ' + token, 'Content-Type': 'application/json'},
    ...(body ? {body: JSON.stringify(body)} : {})});
  const value = await response.json();
  if (!response.ok) {
    const error = new Error(value.error || value.error_code || 'Request failed');
    error.rejectedCommand = value.accepted === false ? value.command_id : null;
    throw error;
  }
  return value;
}
function message(text) { $('message').textContent = text; }
async function deliver() {
  if (!pending || busy) return;
  busy = true;
  $('start').disabled = true;
  try {
    await api('commands', {command: pending});
    pending = null;
    localStorage.removeItem('vgpu-pending');
    message('Request accepted. You can close this page.');
  } catch (error) {
    if (error.rejectedCommand === pending.command_id) {
      pending = null; localStorage.removeItem('vgpu-pending');
      message('Request rejected: ' + error.message + '. No new job was started by this request.');
    } else {
      message('Request not confirmed: ' + error.message + '. Retry uses the same request.');
    }
  } finally { busy = false; await refresh(); }
}
async function command(action, recipe_id, execution_id) {
  if (pending || busy) return;
  busy = true;
  $('start').disabled = true;
  try {
    pending = await api('commands/prepare', {action, ...(recipe_id ? {recipe_id} : {}), ...(execution_id ? {execution_id} : {})});
    localStorage.setItem('vgpu-pending', JSON.stringify(pending));
  } catch (error) { message(error.message); }
  finally { busy = false; }
  await deliver();
}
async function refresh() {
  try {
    const state = await api('status');
    $('connection').textContent = state.mode === 'connected' ? 'Local · Account ' + state.cloud : 'Local · Standalone';
    const selected = $('recipe').value;
    $('recipe').replaceChildren(...state.recipes.map(recipe => {
      const option = document.createElement('option'); option.value = recipe.recipe_id; option.textContent = recipe.title; return option;
    }));
    if (state.recipes.some(recipe => recipe.recipe_id === selected)) $('recipe').value = selected;
    $('start').disabled = busy || !!pending || !state.recipes.length;
    $('retry').hidden = !pending;
    $('jobs').replaceChildren(...state.jobs.map(job => {
      const card = document.createElement('article'); card.dataset.executionId = job.execution_id; card.dataset.state = job.state;
      const title = document.createElement('h3'); title.textContent = job.recipe_id;
      const status = document.createElement('p'); status.textContent = job.state.replaceAll('_', ' ');
      const id = document.createElement('code'); id.textContent = job.execution_id;
      card.append(title, status, id);
      if (job.error_code) { const warning = document.createElement('p'); warning.textContent = job.error_code.replaceAll('_', ' '); card.append(warning); }
      if (Object.keys(job.outputs).length) {
        const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Result metadata';
        const output = document.createElement('pre'); output.textContent = JSON.stringify(job.outputs, null, 2); details.append(summary, output); card.append(details);
      }
      if (!['succeeded', 'failed', 'canceled'].includes(job.state)) {
        const cancel = document.createElement('button'); cancel.textContent = 'Cancel job'; cancel.disabled = busy || !!pending || job.state === 'cancel_requested';
        cancel.addEventListener('click', () => command('cancel', null, job.execution_id)); card.append(cancel);
      }
      return card;
    }));
    if (!state.jobs.length) $('jobs').textContent = 'No jobs yet.';
  } catch (error) {
    $('connection').textContent = 'Connection unavailable'; $('start').disabled = true;
    message(token ? error.message : 'Open this console with vgpu-local runtime open to authorize this browser.');
  }
}
$('start').addEventListener('click', () => command('start', $('recipe').value));
$('retry').addEventListener('click', deliver);
refresh();
setInterval(refresh, 1500);
