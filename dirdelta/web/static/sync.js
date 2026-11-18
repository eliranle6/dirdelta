// The Sync page (web/home.py): the favorite pairs and the recent ones, each synced with a tap (its screens
// then on /run); or the start menu, to choose two other replicas. (Inboxes are sorted under Unsorted import.)
'use strict';

async function api(method, path, body) {
  const response = await fetch(path, method === 'GET' ? {} : {
    method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  if (response.status === 403) throw new Error('This page needs its link, with its key.');
  return response.json();
}

async function start(body) {
  const answer = await api('POST', '/api/start', body);
  if (answer.ok) location.href = '/run';
}

// What the pair's last sync found: what each lacked, and when
function compared(pair) {
  const found = pair.compared;
  if (!found) return 'Not compared yet';
  const [onlyA, onlyB] = found.only;
  const what = !onlyA && !onlyB ? 'In step' : [onlyA ? onlyA + ' only in ' + pair.nameA : '', onlyB ? onlyB + ' only in ' + pair.nameB : '']
    .filter(Boolean).join(', ');
  return what + ' · compared ' + age(found.when).text;
}

function row(title, note, onclick, disabled) {
  return el('button', {class: 'item', disabled, onclick}, el('span', {class: 'what'}, el('b', {class: 'pairline'}, title), el('span', {class: 'note'}, note)),
    el('span', {class: 'go'}, '›'));
}

async function load() {
  let data;
  try {
    data = await api('GET', '/api/sync');
  } catch (error) {
    document.getElementById('main').replaceChildren(el('p', {}, error.message));
    return;
  }
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  const busy = data.running;
  const pairRow = pair => row(pair.nameA + '  ⇄  ' + pair.nameB, compared(pair), () => start({kind: 'pair', a: pair.a, b: pair.b}), busy);
  const parts = [];
  if (busy) parts.push(el('div', {class: 'card banner running'}, el('b', {}, 'Running now'), el('a', {class: 'button primary', href: '/run'}, 'Open it')));
  // Syncing two replicas
  const pairs = data.favorites.map(pair => Object.assign({favorite: true}, pair)).concat(data.recent);
  parts.push(el('div', {class: 'section-title'}, 'Replica pairs to sync'), el('div', {class: 'list'},
    pairs.map(pair => row([pair.favorite ? '★' : '', replicaLabel(pair.a, pair.nameA), '⇄', replicaLabel(pair.b, pair.nameB)], compared(pair),
      () => start({kind: 'pair', a: pair.a, b: pair.b}), busy)),
    row('Two other replicas…', 'Choose any two: folders on disks or in Drive', () => start({}), busy)));
  parts.push(el('p', {class: 'note'}, 'To sort an inbox into its tree, see Unsorted import.'));
  document.getElementById('main').replaceChildren(...parts);
  setTimeout(load, 8000);
}

tabBar('sync');
load();
