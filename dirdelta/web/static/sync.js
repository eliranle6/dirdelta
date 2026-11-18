// The Sync page (web/home.py): the favorite pairs, the recent ones and the inbox sorts, each started with
// a tap (its screens then on /run); or the start menu, to choose other replicas.
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
  return what + ' · ' + found.when.split(' ')[0];
}

function row(title, note, onclick, disabled) {
  return el('button', {class: 'item', disabled, onclick}, el('span', {class: 'what'}, el('b', {}, title), el('span', {class: 'note'}, note)),
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
  if (busy) parts.push(el('div', {class: 'card banner'}, el('b', {}, 'Something is running'), el('a', {class: 'button primary', href: '/run'}, 'Open it')));
  if (data.favorites.length) parts.push(el('div', {class: 'section-title'}, 'Favorites'), el('div', {class: 'list'}, data.favorites.map(pairRow)));
  if (data.recent.length) parts.push(el('div', {class: 'section-title'}, 'Recent'), el('div', {class: 'list'}, data.recent.map(pairRow)));
  if (data.sorts.length) {
    parts.push(el('div', {class: 'section-title'}, 'Sort an inbox'), el('div', {class: 'list'}, data.sorts.map(sort =>
      row(sort.nameInbox + '  →  ' + sort.nameRoot, 'Sort its files into ' + sort.nameRoot, () => start({kind: 'sort', inbox: sort.inbox, root: sort.root}), busy))));
  }
  parts.push(el('div', {class: 'section-title'}, 'Something else'), el('div', {class: 'list'},
    row('Choose other replicas', 'Any two folders, on disks or in Drive, or another inbox', () => start({}), busy)));
  document.getElementById('main').replaceChildren(...parts);
  setTimeout(load, 8000);
}

tabBar('sync');
load();
