// The dashboard (web/home.py): the whole picture at a glance (are the replicas there, when they were last
// synced, are they hashed, how old Drive's lists are), what's running, the phones plugged in, each pair's
// sync status and each inbox (each started from here), and each replica, with its status in colors.
'use strict';

let timer = null;

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

function waiting(text) {
  return el('span', {}, text, el('span', {class: 'dots', style: 'animation-delay:-' + (Date.now() % 1600) + 'ms'}));
}

// A local replica's hashing, as a chip: done, how far, or how many hashes are kept (not counted yet)
function hashChip(replica) {
  const job = replica.hashing;
  if (!replica.there) return '';
  if (!job || !job.state) return chip('none', replica.hashesKept.toLocaleString() + ' hashes kept');
  if (job.state === 'not scanned' || job.state === 'scanning') return chip('warn', waiting('Listing'));
  if (job.state === 'done') return chip('ok', 'All hashed');
  const share = job.files ? Math.floor(100 * job.done / job.files) : 0;
  return chip('warn', job.started ? waiting('Hashing ' + share + '%') : share + '% hashed (paused)');
}

// Each replica's status chips: there, synced, hashed (a local one), its list read (a Drive one)
function statusChips(replica) {
  const synced = age(replica.seen, 7, 30);
  return el('div', {class: 'chips-row'},
    replica.there ? chip('ok', replica.kind === 'drive' ? 'Drive' : 'Mounted') : chip('bad', replica.why),
    chip(replica.seen ? synced.tone : 'none', replica.seen ? 'Synced ' + synced.text : 'Never synced'),
    replica.kind === 'local' ? hashChip(replica) : '',
    replica.kind === 'drive' ? (listed => chip(listed.tone, 'List read ' + listed.text))(age(replica.listedAt, 1, 7)) : '');
}

function replicaCard(replica) {
  const job = replica.hashing;
  const act = pause => async () => { await api('POST', '/api/home/hash', {path: replica.path, pause}); load(); };
  const actions = [];
  if (replica.kind === 'local' && replica.there && !(job && job.state === 'done')) {
    actions.push(el('button', {class: 'small', onclick: act(!!(job && job.started))},
      job && job.started ? 'Pause hashing' : job && job.state ? 'Resume hashing' : 'Hash its files'));
  }
  const entry = replica.lastEntry ? (replica.lastEntry.date ? replica.lastEntry.date + ': ' : '') + replica.lastEntry.text : '';
  return el('div', {class: 'card replica' + (replica.there ? '' : ' away')},
    el('div', {class: 'head'}, icon(replica.inboxOf.length ? 'inbox' : replica.device), el('b', {}, replica.name),
      replica.inboxOf.length ? el('span', {class: 'badge-role'}, 'Inbox') : ''),
    el('div', {class: 'note'}, (replica.inboxOf.length ? 'Sorted into ' + replica.inboxOf.join(', ') + ' · ' : '') +
      (replica.kind === 'drive' ? 'Google Drive' : (replica.device === 'disk' ? 'Disk ' : 'This computer ') + replica.disk)),
    pathLine(replica.path),
    statusChips(replica),
    entry ? el('div', {class: 'entry'}, '“' + entry + '”') : '',
    actions.length ? el('div', {class: 'row2 end'}, actions) : '');
}

function pathLine(full) {
  const whole = el('span', {class: 'fullpath', hidden: true}, full);
  const toggle = el('button', {class: 'tiny', onclick: () => { whole.hidden = !whole.hidden; toggle.textContent = whole.hidden ? 'path' : 'hide'; }}, 'path');
  return el('div', {class: 'where'}, toggle, whole);
}

// A pair's sync status: in step, what each lacked, or not compared yet; and how long ago
function pairStatus(pair) {
  const found = pair.compared;
  if (!found) return chip('none', 'Not compared yet');
  const [onlyA, onlyB] = found.only;
  const when = age(found.when, 7, 30).text;
  if (!onlyA && !onlyB) return chip('ok', 'In step · ' + when);
  return chip('warn', [onlyA ? onlyA + ' only in ' + pair.nameA : '', onlyB ? onlyB + ' only in ' + pair.nameB : '']
    .filter(Boolean).join(', ') + ' · ' + when);
}

// The whole picture: one tile each for the replicas, the syncs, the hashing and Drive's lists
function summary(data) {
  const there = data.replicas.filter(replica => replica.there).length;
  const lastSync = data.pairs.map(pair => pair.compared && pair.compared.when).filter(Boolean).sort().pop();
  const synced = age(lastSync, 7, 30);
  const jobs = data.replicas.filter(replica => replica.hashing && replica.hashing.state);
  const hashing = jobs.find(replica => replica.hashing.started && replica.hashing.state !== 'done');
  const drive = data.replicas.filter(replica => replica.kind === 'drive' && replica.listedAt).map(replica => replica.listedAt).sort()[0];
  const listed = age(drive, 1, 7);
  const tile = (tone, title, value) => el('div', {class: 'tile ' + tone}, el('span', {class: 'tile-title'}, title), el('b', {}, value));
  return el('div', {class: 'tiles'},
    tile(there === data.replicas.length ? 'ok' : 'bad', 'Replicas there', there + ' of ' + data.replicas.length),
    tile(lastSync ? synced.tone : 'none', 'Last sync', lastSync ? synced.text : 'never'),
    tile(hashing ? 'warn' : jobs.length && jobs.every(replica => replica.hashing.state === 'done') ? 'ok' : 'none', 'Hashing',
      hashing ? waiting(hashing.name) : jobs.length ? 'Idle' : 'Not started'),
    drive ? tile(listed.tone, "Drive's oldest list", listed.text) : '');
}

async function load() {
  clearTimeout(timer);
  let data;
  try {
    data = await api('GET', '/api/home');
  } catch (error) {
    document.getElementById('main').replaceChildren(el('p', {}, error.message));
    return;
  }
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  const parts = [summary(data)];
  if (data.running) {
    parts.push(el('div', {class: 'card banner running'}, el('div', {}, el('b', {}, 'Running now'),
      data.running.title ? el('div', {class: 'note'}, data.running.title) : ''),
      el('a', {class: 'button primary', href: '/run'}, 'Open it')));
  }
  if (data.phones.length) {
    parts.push(el('div', {class: 'section-title'}, 'Plugged in'));
    for (const phone of data.phones) {
      parts.push(el('div', {class: 'card banner'}, el('div', {class: 'head'}, icon('phone'),
        el('div', {}, el('b', {}, phone.name), el('div', {class: 'note'}, 'Phone · ' + phone.inner))),
        el('a', {class: 'button primary', href: '/import'}, 'Sort its photos')));
    }
  }
  if (data.pairs.length) {
    parts.push(el('div', {class: 'section-title'}, 'Sync status'), el('div', {class: 'list'}, data.pairs.map(pair =>
      el('div', {class: 'item'}, el('span', {class: 'what'}, el('b', {class: 'pairline'}, pair.favorite ? '★' : '', replicaLabel(pair.a, pair.nameA), '⇄',
        replicaLabel(pair.b, pair.nameB)),
        el('span', {}, pairStatus(pair))),
        el('button', {class: 'small', disabled: !!data.running, onclick: () => start({kind: 'pair', a: pair.a, b: pair.b})}, 'Sync')))));
  }
  if (data.sorts.length) {
    parts.push(el('div', {class: 'section-title'}, 'Inboxes to sort'), el('div', {class: 'list'}, data.sorts.map(sort =>
      el('div', {class: 'item'}, el('span', {class: 'what'}, el('b', {class: 'pairline'}, replicaLabel(sort.inbox, sort.nameInbox, true), '→',
        replicaLabel(sort.root, sort.nameRoot)), el('span', {class: 'note'}, 'Sort the inbox: its photos, or all its files')),
        el('a', {class: 'button small', href: '/import'}, 'Photos'),
        el('button', {class: 'small', disabled: !!data.running, onclick: () => start({kind: 'sort', inbox: sort.inbox, root: sort.root})}, 'All files')))));
  }
  const local = data.replicas.filter(replica => replica.kind === 'local');
  const drive = data.replicas.filter(replica => replica.kind === 'drive');
  if (local.length) parts.push(el('div', {class: 'section-title'}, 'Replicas on disks'), el('div', {class: 'grid'}, local.map(replicaCard)));
  if (drive.length) parts.push(el('div', {class: 'section-title'}, 'Replicas in Google Drive'), el('div', {class: 'grid'}, drive.map(replicaCard)));
  if (!data.replicas.length) parts.push(el('p', {class: 'note'}, 'No replicas yet: sync two folders first (Sync).'));
  const open = [...document.querySelectorAll('.fullpath')].filter(path => !path.hidden).map(path => path.textContent);
  document.getElementById('main').replaceChildren(...parts);
  // (A path shown stays shown across the redraws)
  document.querySelectorAll('.fullpath').forEach(path => { if (open.includes(path.textContent)) { path.hidden = false; path.previousSibling.textContent = 'hide'; } });
  const busy = data.replicas.some(replica => replica.hashing && replica.hashing.started && replica.hashing.state !== 'done');
  timer = setTimeout(load, busy ? 2000 : 8000);
}

tabBar('home');
load();
