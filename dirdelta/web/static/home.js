// The dashboard (web/home.py), two pages of it: Home, the whole picture at a glance (are the replicas
// there, when they were last synced, are they hashed, how old Drive's lists are), what's running, the
// phones plugged in, each pair's sync status (as the terminal's dashboard's) and each inbox, each started
// from here; and Replicas, each replica with its status in colors, and its hashing to start or pause.
'use strict';

const PAGE = document.body.dataset.page;

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
  if (job.state === 'not scanned' || job.state === 'scanning') return chip('warn', waiting('Listing its files'));
  if (job.state === 'done') return chip('ok', 'All hashed');
  const share = job.files ? Math.floor(100 * job.done / job.files) : 0;
  return chip('warn', job.started ? waiting('Hashing ' + share + '%') : share + '% hashed (paused)');
}

// Each replica's status chips: there, synced, hashed (a local one), its list read (a Drive one)
function statusChips(replica) {
  const synced = age(replica.seen);
  const verb = 'Synced';
  return el('div', {class: 'chips-row'},
    replica.there ? chip('ok', replica.kind === 'drive' ? 'In Drive' : 'Mounted') : chip('bad', replica.why),
    chip(replica.seen ? synced.tone : 'none', replica.seen ? verb + ' ' + synced.text : 'Never ' + verb.toLowerCase()),
    replica.kind === 'local' ? hashChip(replica) : '',
    replica.kind === 'drive' ? (listed => chip(listed.tone, 'File list read ' + listed.text))(age(replica.listedAt)) : '');
}

function replicaCard(replica) {
  const job = replica.hashing;
  const act = pause => async () => { await api('POST', '/api/home/hash', {path: replica.path, pause}); load(); };
  const actions = [];
  if (replica.kind === 'local' && replica.there && !(job && job.state === 'done')) {
    actions.push(el('button', {class: 'small', onclick: act(!!(job && job.started))},
      job && job.started ? 'Pause' : job && job.state ? 'Resume hashing' : 'Hash its files'));
  }
  actions.push(forgetButton(replica.path, 'replica'));
  const entry = replica.lastEntry ? (replica.lastEntry.date ? replica.lastEntry.date + ': ' : '') + replica.lastEntry.text : '';
  return el('div', {class: 'card replica' + (replica.there ? '' : ' away')},
    el('div', {class: 'head'}, icon(replica.device), el('b', {}, replica.fullName)),
    el('div', {class: 'note'}, replica.kind === 'drive' ? 'In Google Drive' : 'On ' + replica.place),
    pathLine(replica.path),
    statusChips(replica),
    entry ? el('div', {class: 'entry'}, el('span', {class: 'entry-label'}, 'Last log entry: '), entry) : '',
    actions.length ? el('div', {class: 'row2 end'}, actions) : '');
}

// A pair's sync status: how much of it is in step (the files both had, of all either had, and what each
// lacked: a bar), as the terminal's dashboard's mark (≡ in sync, » « one ahead, ≠ branched, ? not known);
// and how stale that is: when it was compared (green today, yellow this week, red before), and whether a
// replica changed since (then it may not be so anymore)
const STATE_WORDS = {'in sync': 'In sync', 'a ahead': 'Out of step', 'b ahead': 'Out of step', 'branched': 'Out of step both ways', 'unknown': ''};

function pairRow(pair, isRunning) {
  const synced = pair.synced;
  const compared = age(pair.state.when);
  const parts = [];
  if (!synced) parts.push(el('span', {class: 'note'}, 'Never compared: sync them to know.'));
  else {
    parts.push(el('span', {class: 'statename c-' + pair.state.color}, STATE_WORDS[pair.state.kind] || ''));
    const {onlyA, onlyB, totalA, share} = synced;
    const either = totalA === null ? null : totalA + onlyB;
    const percent = share === null ? null : (share === 1 ? '100' : Math.min(99.9, Math.floor(share * 1000) / 10).toString());
    if (either) {
      parts.push(el('div', {class: 'syncbar'}, el('div', {class: 'both', style: 'width:' + (100 * (either - onlyA - onlyB) / either) + '%'}),
        el('div', {class: 'only', style: 'width:' + (100 * onlyA / either) + '%'}), el('div', {class: 'only', style: 'width:' + (100 * onlyB / either) + '%'})));
    }
    parts.push(el('div', {class: 'syncline'}, percent !== null ? el('b', {}, percent + '% in step') : '',
      el('span', {}, !onlyA && !onlyB ? 'Each has all the other\'s files' :
        [onlyA ? onlyA.toLocaleString() + ' only in ' + pair.nameA : '', onlyB ? onlyB.toLocaleString() + ' only in ' + pair.nameB : '']
          .filter(Boolean).join(' · ')),
      percent === null ? el('span', {class: 'note'}, 'The share in step shows after the next sync.') : ''));
  }
  const fresh = [];
  if (pair.state.when) fresh.push(chip(compared.tone, 'Compared ' + compared.text));
  if (pair.changedSince.length) fresh.push(chip('bad', pair.changedSince.join(' and ') + ' changed since: may be out of date'));
  return el('div', {class: 'item pair'}, el('span', {class: 'syncmark c-' + pair.state.color}, pair.state.mark),
    el('span', {class: 'what'}, el('b', {class: 'pairline'}, pair.favorite ? '★' : '', replicaLabel(pair.a, pair.nameA), '⇄',
      replicaLabel(pair.b, pair.nameB)), parts, fresh.length ? el('div', {class: 'chips-row'}, fresh) : ''),
    el('button', {class: 'small', disabled: isRunning, onclick: () => start({kind: 'pair', a: pair.a, b: pair.b})}, 'Sync'));
}

// The whole picture: one tile each for the replicas, the syncs, the hashing and Drive's lists
function summary(data) {
  const kept = data.replicas;
  const disks = kept.filter(replica => replica.kind === 'local'), inDrive = kept.filter(replica => replica.kind === 'drive');
  const mounted = disks.filter(replica => replica.there).length;
  const there = mounted + (data.drive.connected ? inDrive.length : 0);
  const where = [disks.length ? (mounted === disks.length ? (disks.length === 1 ? 'Its disk is mounted' : 'Every disk is mounted') :
      (disks.length - mounted) + ' disk' + (disks.length - mounted === 1 ? ' isn\'t' : 's aren\'t') + ' mounted') : '',
    inDrive.length ? (data.drive.connected ? 'Drive is connected' : 'Drive isn\'t connected') : ''].filter(Boolean).join(' · ');
  const lastSync = data.pairs.map(pair => pair.compared && pair.compared.when).filter(Boolean).sort().pop();
  const synced = age(lastSync);
  const jobs = data.replicas.filter(replica => replica.hashing && replica.hashing.state);
  const hashing = jobs.find(replica => replica.hashing.started && replica.hashing.state !== 'done');
  const drive = data.replicas.filter(replica => replica.kind === 'drive' && replica.listedAt).map(replica => replica.listedAt).sort()[0];
  const listed = age(drive);
  const tile = (tone, title, value, hint, href) => el(href ? 'a' : 'div', {class: 'tile ' + tone, href},
    el('span', {class: 'tile-title'}, title), el('b', {}, value), hint ? el('span', {class: 'tile-hint'}, hint) : '');
  return el('div', {class: 'tiles'},
    tile(!kept.length ? 'none' : there === kept.length ? 'ok' : 'bad', 'Replicas available', there + ' of ' + kept.length,
      !kept.length ? 'None yet' : where, '/replicas'),
    tile(lastSync ? synced.tone : 'none', 'Last sync', lastSync ? synced.text : 'never', 'Sync status is below', '/replicas'),
    tile(hashing ? 'warn' : jobs.length && jobs.every(replica => replica.hashing.state === 'done') ? 'ok' : 'none', 'File hashes',
      hashing ? waiting(hashing.name) : jobs.length ? 'Up to date' : 'Not computed yet', 'They find moved and renamed files', '/replicas'),
    drive ? tile(listed.tone, 'Drive file lists', 'Read ' + listed.text, listed.tone === 'ok' ? 'Fresh' : 'A sync reads them again', '/replicas') : '');
}

function connectionRow(kind, title, sub, state, action) {
  return el('div', {class: 'item'}, icon(kind),
    el('span', {class: 'what'}, el('b', {}, title), sub ? el('span', {class: 'note'}, sub) : ''), state, action || '');
}

// Which replicas can be reached now: each disk replica (mounted, or not plugged in), and Drive (signed in,
// or not)
function pluggedIn(data) {
  const row = connectionRow;
  const rows = [];
  for (const replica of data.replicas.filter(replica => replica.kind === 'local')) {
    rows.push(row(replica.device, replica.fullName, replica.place === 'this computer' ? 'On this computer\'s own disk' : 'On a separate disk',
      replica.there ? chip('ok', 'Mounted') : chip('bad', 'Not plugged in')));
  }
  const inDrive = data.replicas.filter(replica => replica.kind === 'drive');
  const held = inDrive.map(replica => replica.fullName).concat(
    data.inboxes.filter(inbox => inbox.kind === 'drive').map(inbox => 'the inbox ' + inbox.name));
  rows.push(row('drive', 'Google Drive', inDrive.length ? 'Holds ' + held.join(' and ') : 'Holds no replica of ' + data.user + "'s yet",
    data.drive.connected ? chip('ok', 'Connected') : chip('bad', 'Not connected')));
  return el('div', {class: 'list'}, rows);
}

function homePage(data) {
  const parts = [summary(data)];
  if (!data.replicas.length) {
    // (A new user's: nothing of theirs yet)
    parts.push(el('div', {class: 'card banner'}, el('div', {}, el('b', {}, data.user + ' has no replicas yet'),
      el('div', {class: 'note'}, 'A replica is a copy of ' + data.user + '\'s files: a folder on this computer, on a disk or in Google Drive. ' +
        'Add two, and they\'re kept in step.')),
      el('a', {class: 'button primary', href: '/replicas#add'}, 'Add a replica')));
  }
  if (data.running) {
    parts.push(el('div', {class: 'card banner running'}, el('div', {}, el('b', {}, 'Running now' + (data.running.user && data.running.user !== data.user ? ' (for ' + data.running.user + ')' : '')),
      data.running.title ? el('div', {class: 'note'}, data.running.title) : ''),
      el('a', {class: 'button primary', href: '/run'}, 'Open it')));
  }
  parts.push(el('div', {class: 'section-title'}, 'Replicas plugged in'), pluggedIn(data));
  parts.push(el('div', {class: 'section-title'}, 'Sync status of each replica pair'));
  parts.push(data.pairs.length ? el('div', {class: 'list'}, data.pairs.map(pair => pairRow(pair, !!data.running))) :
    el('p', {class: 'note'}, 'Any two replicas are a pair: add them on Replicas.'));
  // The inboxes (a phone's while it's plugged in, or while it's being sorted), each one's sorting so far
  const inboxes = data.inboxes.filter(inbox => inbox.kind !== 'phone' || inbox.there || inbox.imports.length);
  const rows = inboxes.map(inbox => {
    const progress = inboxProgress(inbox);
    return el('a', {class: 'item', href: '/inboxes'}, icon(inbox.kind === 'phone' ? 'phone' : inbox.kind === 'drive' ? 'inbox' : 'folder'),
      el('span', {class: 'what'}, el('b', {}, inbox.kind === 'phone' ? 'Photos on ' + inbox.name : inbox.name), el('span', {class: 'note'}, progress.text),
        progress.share !== null ? el('span', {class: 'meter'}, el('span', {style: 'width:' + progress.share + '%'})) : ''),
      inbox.kind === 'phone' ? chip(inbox.there ? 'ok' : 'none', inbox.there ? 'Plugged in' : 'Not plugged in') : '',
      el('span', {class: 'go'}, '›'));
  });
  if (!data.inboxes.some(inbox => inbox.kind === 'phone' && inbox.there)) {
    rows.push(connectionRow('phone', 'No phone plugged in', 'Plug one in by USB and choose "File transfer" on it', chip('none', 'None')));
  }
  parts.push(el('div', {class: 'section-title'}, 'Inboxes'), el('div', {class: 'list'}, rows));
  return parts;
}

// The user's replicas: each one's status, adding one; and every two of them, a pair, its sync status and Sync
function replicasPage(data) {
  const local = data.replicas.filter(replica => replica.kind === 'local');
  const drive = data.replicas.filter(replica => replica.kind === 'drive');
  const parts = [el('p', {class: 'note'}, 'Replicas are copies of ' + data.user + '\'s files, kept in step by syncing any two of them.'),
    folderAdder('replica')];
  if (local.length) parts.push(el('div', {class: 'section-title'}, 'Replicas on disks'), el('div', {class: 'grid'}, local.map(replicaCard)));
  if (drive.length) parts.push(el('div', {class: 'section-title'}, 'Replicas in Google Drive'), el('div', {class: 'grid'}, drive.map(replicaCard)));
  parts.push(el('div', {class: 'section-title'}, 'Sync status of each pair'));
  parts.push(data.pairs.length ? el('div', {class: 'list'}, data.pairs.map(pair => pairRow(pair, !!data.running))) :
    el('p', {class: 'note'}, data.replicas.length ? 'Add another replica: any two are a pair to sync.' : 'Add two replicas: any two are a pair to sync.'));
  parts.push(el('div', {class: 'list'}, el('a', {class: 'item', href: '#', onclick: event => { event.preventDefault(); start({}); }},
    el('span', {class: 'what'}, el('b', {}, 'Sync two other folders once…'), el('span', {class: 'note'}, 'Any two, chosen on the terminal\'s screens')),
    el('span', {class: 'go'}, '›'))));
  return parts;
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
  const parts = PAGE === 'replicas' ? replicasPage(data) : homePage(data);
  const open = [...document.querySelectorAll('.pathbutton')].filter(path => path.textContent === path.title).map(path => path.title);
  document.getElementById('main').replaceChildren(...parts);
  // (A path shown whole stays so across the redraws)
  document.querySelectorAll('.pathbutton').forEach(path => { if (open.includes(path.title)) path.textContent = path.title; });
  const busy = data.replicas.some(replica => replica.hashing && replica.hashing.started && replica.hashing.state !== 'done');
  timer = setTimeout(load, busy ? 2000 : 8000);
}

tabBar(PAGE);
load();
