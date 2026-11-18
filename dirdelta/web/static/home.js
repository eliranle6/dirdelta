// The dashboard (web/home.py): what's running, the phones plugged in, and each replica: its disk,
// whether it's there, its hashing (to start or pause), its log's last entry and when it was synced.
'use strict';

let timer = null;

async function api(method, path, body) {
  const response = await fetch(path, method === 'GET' ? {} : {
    method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  if (response.status === 403) throw new Error('This page needs its link, with its key.');
  return response.json();
}

// 'YYYY-MM-DD HH:MM' as how long ago
function since(when) {
  if (!when) return '';
  const then = new Date(when.replace(' ', 'T'));
  const days = Math.floor((Date.now() - then) / 86400000);
  return days < 1 ? 'today' : days === 1 ? 'yesterday' : days < 60 ? days + ' days ago' : then.toLocaleDateString();
}

function waiting(text) {
  return el('span', {}, text, el('span', {class: 'dots', style: 'animation-delay:-' + (Date.now() % 1600) + 'ms'}));
}

// A local replica's hashing: how far, and Start/Pause
function hashLine(replica) {
  const job = replica.hashing;
  if (!replica.there) return '';
  const act = pause => async () => { await api('POST', '/api/home/hash', {path: replica.path, pause}); load(); };
  if (!job || !job.state) return el('div', {class: 'line'}, el('span', {class: 'note'}, 'Hashes: not looked at since the daemon started'),
    el('button', {class: 'small', onclick: act(false)}, 'Hash its files'));
  if (job.state === 'not scanned' || job.state === 'scanning') return el('div', {class: 'line note'}, waiting('Listing its files'));
  const percent = job.files ? Math.floor(100 * job.done / job.files) : 100;
  return el('div', {class: 'line'},
    el('div', {class: 'meter'}, el('div', {style: 'width:' + percent + '%'})),
    el('span', {class: 'note'}, job.state === 'done' ? 'All ' + job.files + ' hashed' :
      job.started ? waiting('Hashing: ' + job.done + ' of ' + job.files) : job.done + ' of ' + job.files + ' hashed'),
    job.state !== 'done' ? el('button', {class: 'small', onclick: act(job.started)}, job.started ? 'Pause' : 'Resume') : '');
}

function replicaCard(replica) {
  const status = replica.there ? el('span', {class: 'state ok'}, replica.kind === 'drive' ? 'Drive' : 'There') :
    el('span', {class: 'state off'}, replica.why);
  const entry = replica.lastEntry ? (replica.lastEntry.date ? replica.lastEntry.date + ': ' : '') + replica.lastEntry.text : '';
  return el('div', {class: 'card replica' + (replica.there ? '' : ' away')},
    el('div', {class: 'head'}, el('b', {}, replica.name), status),
    el('div', {class: 'note'}, replica.disk + (replica.kind === 'drive' ? '' : ' · ' + replica.path)),
    replica.seen ? el('div', {class: 'note'}, 'Synced ' + since(replica.seen) + (replica.changed ? ', changed ' + since(replica.changed) : '')) : '',
    entry ? el('div', {class: 'entry'}, '“' + entry + '”') : '',
    replica.kind === 'local' ? hashLine(replica) : '');
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
  const parts = [];
  if (data.running) {
    parts.push(el('div', {class: 'card banner'}, el('div', {}, el('b', {}, 'Something is running'),
      data.running.title ? el('div', {class: 'note'}, data.running.title) : ''),
      el('a', {class: 'button primary', href: '/run'}, 'Open it')));
  }
  if (data.phones.length) {
    parts.push(el('div', {class: 'section-title'}, 'Plugged in'));
    for (const phone of data.phones) {
      parts.push(el('div', {class: 'card banner'}, el('div', {}, el('b', {}, phone.name), el('div', {class: 'note'}, phone.inner)),
        el('a', {class: 'button primary', href: '/import'}, 'Sort its photos')));
    }
  }
  const local = data.replicas.filter(replica => replica.kind === 'local');
  const drive = data.replicas.filter(replica => replica.kind === 'drive');
  parts.push(el('div', {class: 'section-title'}, 'Replicas on disks'), el('div', {class: 'grid'}, local.map(replicaCard)));
  if (drive.length) parts.push(el('div', {class: 'section-title'}, 'Replicas in Drive'), el('div', {class: 'grid'}, drive.map(replicaCard)));
  if (!data.replicas.length) parts.push(el('p', {class: 'note'}, 'No replicas yet: sync two folders first (Sync).'));
  document.getElementById('main').replaceChildren(...parts);
  const busy = data.replicas.some(replica => replica.hashing && replica.hashing.started && replica.hashing.state !== 'done');
  timer = setTimeout(load, busy ? 2000 : 8000);
}

tabBar('home');
load();
