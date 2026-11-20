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
    replica.kind === 'drive' ? (replica.reading ? chip('warn', waiting('Reading its file list')) :
      (listed => chip(listed.tone, 'File list read ' + listed.text))(age(replica.listedAt))) : '');
}

// How far a replica's hashing (a local one's) or its file list's reading (a Drive one's) is, as a bar; or ''
function workBar(replica) {
  const job = replica.hashing;
  if (replica.reading) return el('div', {}, el('div', {class: 'note'}, readText(replica.reading)), bar(readShare(replica.reading)));
  if (job && job.files && job.state !== 'done' && job.state !== 'not scanned' && job.state !== 'scanning') {
    return el('div', {}, el('div', {class: 'note'}, job.done.toLocaleString() + ' of ' + job.files.toLocaleString() + ' files hashed'),
      bar(100 * job.done / job.files));
  }
  return '';
}

// A Drive list's reading: how far, in words, and its share (of about how many there are)
function readText(reading) {
  return 'Reading Drive\'s file list: ' + reading.read.toLocaleString() + (reading.expected ? ' of about ' + reading.expected.toLocaleString() : '') + ' files and folders';
}

function readShare(reading) {
  return reading.expected ? Math.min(99, 100 * reading.read / reading.expected) : 0;
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
    workBar(replica),
    entry ? el('div', {class: 'entry'}, el('span', {class: 'entry-label'}, 'Last log entry: '), entry) : '',
    actions.length ? el('div', {class: 'row2 end'}, actions) : '');
}

// A pair's sync status: how much of it is in step (the files both had, of all either had, and what each
// lacked: a bar), as the terminal's dashboard's mark (≡ in sync, » « one ahead, ≠ branched, ? not known);
// and how stale that is: when it was compared (green today, yellow this week, red before), and whether a
// replica changed since (then it may not be so anymore)
const STATE_WORDS = {'in sync': 'In sync', 'a ahead': 'Out of step', 'b ahead': 'Out of step', 'branched': 'Out of step both ways', 'unknown': ''};

// Whether what's running is this pair's sync (started from its Sync, by this user)
function isSyncing(pair, running, user) {
  const what = running && running.what;
  return !!what && what.kind === 'pair' && running.user === user &&
    ((what.a === pair.a && what.b === pair.b) || (what.a === pair.b && what.b === pair.a));
}

function pairRow(pair, running, user) {
  const synced = pair.synced;
  const syncing = isSyncing(pair, running, user);
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
      el('span', {class: 'note'}, 'As of the last sync: files added since aren\'t counted, only its age tells.' +
        (percent === null ? ' A % shows from the next sync.' : ''))));
  }
  const fresh = [];
  if (pair.state.when) fresh.push(chip(compared.tone, 'Compared ' + compared.text));
  if (pair.changedSince.length) fresh.push(chip('bad', pair.changedSince.join(' and ') + ' changed since: may be out of date'));
  // (While a run goes on, one at a time: this pair's sync is gone back to; any other run is offered to open)
  const button = syncing ? el('a', {class: 'button small primary', href: '/run'}, 'Go back to ongoing sync') :
    running ? el('a', {class: 'button small', href: '/run', title: 'One runs at a time: finish or leave it to sync these'},
      'Another sync is running: open it') :
    el('button', {class: 'small', onclick: () => start({kind: 'pair', a: pair.a, b: pair.b})}, 'Sync');
  return el('div', {class: 'item pair' + (syncing ? ' syncing' : '')}, el('span', {class: 'syncmark c-' + pair.state.color}, pair.state.mark),
    el('span', {class: 'what'}, el('b', {class: 'pairline'}, pair.favorite ? '★' : '', replicaLabel(pair.a, pair.nameA), '⇄',
      replicaLabel(pair.b, pair.nameB)), syncing ? el('div', {class: 'insync'}, waiting('Sync in progress')) : '',
      parts, fresh.length ? el('div', {class: 'chips-row'}, fresh) : ''),
    button);
}

// The whole picture, in three sections of tiles, two to a row, the replicas' left and the inboxes' right
// (each leading to its tab): how up to date they are (in step, sorted; the last sync and sort); what's
// there now; and the indexing: the hashing and Drive's lists
function summary(data) {
  const kept = data.replicas;
  const disks = kept.filter(replica => replica.kind === 'local'), inDrive = kept.filter(replica => replica.kind === 'drive');
  const there = disks.filter(replica => replica.there).length + (data.drive.connected ? inDrive.length : 0);
  const jobs = data.replicas.filter(replica => replica.hashing && replica.hashing.state);
  const hashing = jobs.find(replica => replica.hashing.started && replica.hashing.state !== 'done');
  const drive = data.replicas.filter(replica => replica.kind === 'drive' && replica.listedAt).map(replica => replica.listedAt).sort()[0];
  const listed = age(drive);
  const tile = (tone, glyph, title, value, hint, href) => el(href ? 'a' : 'div', {class: 'tile ' + tone, href},
    el('span', {class: 'tile-title'}, icon(glyph), title), el('b', {}, value), hint ? el('span', {class: 'tile-hint'}, hint) : '');
  const hashes = tile(hashing ? 'warn' : jobs.length && jobs.every(replica => replica.hashing.state === 'done') ? 'ok' : 'none', 'hash', 'File hashes',
    hashing ? waiting(hashing.name) : jobs.length ? 'Up to date' : 'Not computed yet', 'They find moved and renamed files', '/replicas');
  if (hashing && hashing.hashing.files) hashes.append(bar(100 * hashing.hashing.done / hashing.hashing.files));
  if (!drive) hashes.classList.add('wide');
  const section = (title, ...tiles) => [el('div', {class: 'section-title'}, title), el('div', {class: 'tiles'}, tiles)];
  return [
    ...section('How up to date',
      inStepTile(data, tile), sortedTile(data, tile),
      lastSyncTile(data, tile), lastSortTile(data, tile)),
    ...section('Available now',
      tile(!kept.length ? 'none' : there === kept.length ? 'ok' : 'bad', 'replicas', 'Replicas available', there + ' out of ' + kept.length, '', '/replicas'),
      inboxesTile(data, tile)),
    ...section('Indexing',
      hashes,
      drive ? driveTile(data, tile, listed) : '')];
}

// How old Drive's oldest list is, or how far reading one again is (a bar)
function driveTile(data, tile, listed) {
  const reading = data.drive.reading[0];
  if (!reading) return tile(listed.tone, 'drive', 'Drive file lists', 'Read ' + listed.text, 'Read again once a day, when opened', '/replicas');
  const found = tile('warn', 'drive', 'Drive file lists', waiting('Reading now'), readText(reading), '/replicas');
  found.append(bar(readShare(reading)));
  return found;
}

// How alike the replicas are, as far as is known: of the files either replica of a pair had when it was
// last compared, the share both had, over every pair compared (by files, so a big pair counts more). A
// guess: it's as of each comparison, and a replica may have changed since
function inStepTile(data, tile) {
  let both = 0, either = 0, counted = 0, changed = false, apart = null;
  for (const pair of data.pairs) {
    const synced = pair.synced;
    if (synced) apart = (apart || 0) + synced.onlyA + synced.onlyB;
    if (!synced || synced.share === null) continue;
    both += synced.totalA - synced.onlyA;
    either += synced.totalA + synced.onlyB;
    counted += 1;
    changed = changed || pair.changedSince.length > 0;
  }
  if (!counted && apart !== null) {
    // (Compared before the totals were noted: only how many files were apart is known)
    return tile(apart ? 'warn' : 'ok', 'equal', 'Replicas in step', apart ? apart.toLocaleString() + ' file' + (apart === 1 ? '' : 's') + ' apart' : 'In step',
      'As of the last sync; a % from the next one', '/replicas');
  }
  if (!counted) {
    return tile('none', 'equal', 'Replicas in step', 'Not known yet', data.pairs.length ? 'A sync compares them' : 'Add two replicas', '/replicas');
  }
  const share = either ? both / either : 1;
  const percent = share === 1 ? '100%' : Math.min(99.9, Math.floor(share * 1000) / 10) + '%';
  return tile(share >= 0.99 ? 'ok' : share >= 0.9 ? 'warn' : 'bad', 'equal', 'Replicas in step', percent,
    'Files in both as of the last sync, newer ones not counted (' + counted + ' of ' + data.pairs.length + ' pair' + (data.pairs.length === 1 ? '' : 's') + ')' +
      (changed ? '; changed since' : ''), '/replicas');
}

// When the replica synced longest ago was last synced (each replica's last sync: its pairs' latest), and
// which one it is; the latest sync of any pair too, if it was later
function lastSyncTile(data, tile) {
  const latest = {};
  for (const pair of data.pairs) {
    const when = pair.compared && pair.compared.when;
    for (const path of [pair.a, pair.b]) {
      if (!(path in latest) || (when && (!latest[path] || when > latest[path]))) latest[path] = when || latest[path] || null;
    }
  }
  const replicas = data.replicas.filter(replica => replica.path in latest);
  if (!replicas.length) return tile('none', 'sync', 'Last sync', 'never', 'Of any two replicas', '/replicas');
  const stalest = replicas.reduce((one, other) => !latest[other.path] || (latest[one.path] && latest[other.path] < latest[one.path]) ? other : one);
  const newest = Object.values(latest).filter(Boolean).sort().pop();
  const when = latest[stalest.path], found = age(when);
  const everyone = replicas.every(replica => latest[replica.path] === when);
  const hint = everyone ? (replicas.length === 2 ? 'Both replicas' : 'All ' + replicas.length + ' replicas') :
    'The one longest ago: ' + stalest.fullName + (when ? '' : ' was never synced') + (newest && newest !== when ? '; the latest ' + age(newest).text : '');
  return tile(when ? found.tone : 'bad', 'sync', 'Last sync', when ? found.text : 'never', hint, '/replicas');
}

// How much of the inboxes' files are sorted (moved into the tree, or skipped) or in a replica already (as
// last checked), of the ones being sorted
function sortedTile(data, tile) {
  const sum = tallies(data.inboxes.flatMap(inbox => inbox.imports));
  if (!sum.total) return tile('none', 'check', 'Inboxes sorted', 'Not started', 'Sort one on Inboxes', '/inboxes');
  const share = (sum.sorted + sum.there) / sum.total;
  return tile(sum.left ? 'warn' : 'ok', 'check', 'Inboxes sorted', Math.floor(share * 100) + '%',
    (sum.left ? sum.left.toLocaleString() + ' of ' + sum.total.toLocaleString() + ' files left' : 'All ' + sum.total.toLocaleString() + ' files') +
      (sum.there ? '; ' + sum.there.toLocaleString() + ' were in a replica already' : ''), '/inboxes');
}

// When a file of an inbox was last sorted (or skipped), and which inbox's
function lastSortTile(data, tile) {
  let when = null, where = null;
  for (const inbox of data.inboxes) {
    for (const found of inbox.imports) {
      if (found.changed && (!when || found.changed > when)) {
        when = found.changed;
        where = inbox.kind === 'phone' ? 'Photos on ' + inbox.name : inbox.name;
      }
    }
  }
  const found = age(when);
  return tile(when ? found.tone : 'none', 'clock', 'Last sort', when ? found.text : 'never', where || 'Of any inbox', '/inboxes');
}

// The inboxes there now, of each kind (unsorted folders, phones plugged in), and how many of their files
// are left to sort (of the ones started)
function inboxesTile(data, tile) {
  const folders = data.inboxes.filter(inbox => inbox.kind !== 'phone');
  const phones = data.inboxes.filter(inbox => inbox.kind === 'phone');
  const there = folders.concat(phones).filter(inbox => inbox.there).length;
  const value = el('span', {class: 'tile-lines'}, el('span', {}, thereOutOf(folders) + ' unsorted folders'), el('span', {}, thereOutOf(phones) + ' phones'));
  return tile(there ? 'ok' : 'none', 'inbox', 'Inboxes available', value, '', '/inboxes');
}

function homePage(data) {
  const parts = [];
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
  // (Each pair's sync status is on Replicas)
  return parts.concat(summary(data));
}

// The user's replicas: each one's status, adding one; and every two of them, a pair, its sync status and Sync
function replicasPage(data) {
  const local = data.replicas.filter(replica => replica.kind === 'local');
  const drive = data.replicas.filter(replica => replica.kind === 'drive');
  const there = data.replicas.filter(replica => replica.there).length;
  const apart = data.pairs.filter(pair => ['a ahead', 'b ahead', 'branched'].includes(pair.state.kind)).length;
  const unknown = data.pairs.filter(pair => pair.state.kind === 'unknown').length;
  const pairs = data.pairs.length ? el('div', {class: 'list'}, data.pairs.map(pair => pairRow(pair, data.running, data.user))) :
    el('p', {class: 'note'}, data.replicas.length ? 'Add another replica: any two are a pair to sync.' : 'Add two replicas: any two are a pair to sync.');
  const other = el('div', {class: 'list'}, el('a', {class: 'item', href: '#', onclick: event => { event.preventDefault(); start({}); }},
    el('span', {class: 'what'}, el('b', {}, 'Sync two other folders once…'), el('span', {class: 'note'}, 'Any two, chosen on the terminal\'s screens')),
    el('span', {class: 'go'}, '›')));
  const cards = [];
  if (local.length) cards.push(el('div', {class: 'kindlabel'}, 'On disks'), el('div', {class: 'grid'}, local.map(replicaCard)));
  if (drive.length) cards.push(el('div', {class: 'kindlabel'}, 'In Google Drive'), el('div', {class: 'grid'}, drive.map(replicaCard)));
  // Two parts, each in a block of its own: every two replicas' sync status (what's done here, first), and
  // the replicas themselves
  return [...kindParts([
      {jump: kindJump('pairs', 'sync', 'Sync status', !data.pairs.length ? 'No pair yet' : apart ? apart + ' out of ' + data.pairs.length + ' out of step' : unknown ? unknown + ' out of ' + data.pairs.length + ' not synced yet' : 'All in step',
        !data.pairs.length || data.pairs.some(pair => pair.state.kind === 'branched') ? 'bad' : apart || unknown ? 'warn' : 'ok'),
       block: kindBlock('pairs', 'sync', 'Sync status', '', pairs, other)},
      {jump: kindJump('replicas', 'replicas', 'Replicas', there + ' out of ' + data.replicas.length + ' available',
        !data.replicas.length || !there ? 'bad' : there < data.replicas.length ? 'warn' : 'ok'),
       block: kindBlock('replicas', 'replicas', 'Replicas', '', ...cards, folderAdder('replica'))}],
      {add: 'replicas'})];
}

// (A link to a part, e.g. Home's to #add, goes to it once it's drawn: once)
let scrolled = false;
function scrollToPart() {
  const part = !scrolled && ['pairs', 'replicas', 'add'].includes(location.hash.slice(1)) ? location.hash.slice(1) : null;
  scrolled = true;
  if (part && document.getElementById(part === 'add' ? 'replicas' : part)) document.getElementById(part === 'add' ? 'replicas' : part).scrollIntoView();
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
  if (PAGE === 'replicas' && layout() === 'blocks') scrollToPart();
  const busy = data.replicas.some(replica => replica.hashing && replica.hashing.started && replica.hashing.state !== 'done');
  timer = setTimeout(load, busy ? 2000 : 8000);
}

tabBar(PAGE);
load();
