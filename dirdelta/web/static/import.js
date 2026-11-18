// The import page (web/importing.py): the imports and the phones plugged in; an import's overview (how
// many files, how many hashed, what each replica has already and how sure that is), each count opening
// its photos (#photos/KIND/REPLICA); the photos by day, each tagged with where the replicas have it,
// chosen a dir (a day at once, or the ones selected), then moved in. The server keeps every choice at once.
'use strict';

const params = new URLSearchParams(location.search);
const page = {id: params.get('id'), data: null, selected: new Set(), filter: {kind: 'all', replica: ''}, timer: null, target: ''};

// What the hash says is shown: the overview (none), or the photos a filter lets through
function view() {
  const [name, kind, replica] = location.hash.slice(1).split('/');
  if (name !== 'photos') return 'overview';
  page.filter = {kind: kind || 'all', replica: replica ? decodeURIComponent(replica) : ''};
  return 'photos';
}

function photosLink(kind, replica) {
  return '#photos/' + kind + (replica ? '/' + encodeURIComponent(replica) : '');
}

window.addEventListener('hashchange', () => { page.selected.clear(); window.scrollTo(0, 0); load(); });

async function api(method, path, body) {
  const response = await fetch(path, method === 'GET' ? {} : {
    method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  if (response.status === 403) throw new Error('This page needs its link, with its key.');
  return response.json();
}

function later(seconds) {
  clearTimeout(page.timer);
  page.timer = setTimeout(load, seconds * 1000);
}

async function load() {
  try {
    if (page.id) await loadImport(); else await loadList();
  } catch (error) {
    document.getElementById('main').replaceChildren(el('p', {}, error.message));
  }
}

// The imports, and starting one (one for each source and replica: the one there is is opened)

function importLink(id) { return '/import?id=' + encodeURIComponent(id); }

// What a source is called: the phone's name, or a local dir's
function sourceName(source) { return source.device || source.full.split('/').filter(Boolean).pop() || source.full; }

// The dir in the source (DCIM), and a small button showing its whole path
function pathLine(inner, full) {
  const whole = el('span', {class: 'fullpath', hidden: true}, full);
  const toggle = el('button', {class: 'tiny', onclick: event => {
    event.preventDefault();
    whole.hidden = !whole.hidden;
    toggle.textContent = whole.hidden ? 'path' : 'hide';
  }}, 'path');
  return el('p', {class: 'where'}, inner ? el('span', {}, inner) : '', toggle, whole);
}

async function loadList() {
  const data = await api('GET', '/api/imports');
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  const destSelect = () => el('select', {class: 'dest'}, data.dests.map(dest =>
    el('option', {value: dest, selected: dest === data.defaultDest}, dest)));
  const start = async (source, select) => {
    const answer = await api('POST', '/api/imports/new', {source, dest: select.value});
    if (answer.error) document.getElementById('status').textContent = answer.error;
    else location.href = importLink(answer.id);
  };
  // A source's row: into which replica, and Start (or Open, if there's an import of it into that one)
  const row = (label, source, select) => {
    const open = () => data.imports.find(found => found.source.full === source() && found.dest === select.value);
    const button = el('button', {class: 'primary', onclick: () => open() ? location.href = importLink(open().id) : start(source(), select)});
    const named = () => { button.textContent = open() ? 'Open its import' : 'Start'; };
    select.addEventListener('change', named);
    if (label) label.addEventListener('input', named);
    named();
    return el('div', {class: 'row2'}, label || '', el('span', {class: 'note'}, 'into'), select, button);
  };
  const cards = [];
  if (!data.dests.length) cards.push(el('div', {class: 'card'}, el('p', {}, 'No local replica is known yet: sync one first.')));
  cards.push(el('div', {class: 'card'}, el('h2', {}, 'Phones plugged in'),
    data.phones.length ? data.phones.map(phone => el('div', {},
      el('b', {}, phone.name), pathLine(phone.inner, phone.full), row(null, () => phone.path, destSelect()))) :
      el('p', {}, 'None. Plug the phone in by USB and choose "File transfer" on it; it shows here (this page checks again every few seconds).')));
  const folder = el('input', {type: 'text', placeholder: '/path/to/a/folder'});
  cards.push(el('div', {class: 'card'}, el('h2', {}, 'Import from a folder'), row(folder, () => folder.value, destSelect())));
  if (data.imports.length) {
    cards.push(el('div', {class: 'card'}, el('h2', {}, 'Imports'), data.imports.map(found => el('div', {class: 'row2'},
      el('a', {href: importLink(found.id)}, sourceName(found.source) + (found.source.device ? ' › ' + found.source.inner : '') +
        ' → ' + replicaName(found.dest)),
      el('span', {class: 'note'}, countsText(found.counts))))));
  }
  const main = document.getElementById('main');
  if (!main.contains(document.activeElement)) main.replaceChildren(...cards);
  later(4);
}

function countsText(counts) {
  return [['pending', 'on the phone only'], ['copied', 'copied'], ['moved', 'moved'], ['skipped', 'skipped']]
    .filter(([key]) => counts[key]).map(([key, text]) => counts[key] + ' ' + text).join(', ') || 'nothing yet';
}

// An import

async function loadImport() {
  const shown = view();
  const data = await api('GET', '/api/import?id=' + encodeURIComponent(page.id) + (shown === 'overview' ? '&files=0' : ''));
  if (data.error) throw new Error(data.error);
  if (view() !== shown) return;
  page.data = data;
  const title = sourceName(data.source) + ' → ' + replicaName(data.dest);
  document.getElementById('where').replaceChildren(' > ', shown === 'overview' ? title :
    el('a', {href: '#'}, title), shown === 'overview' ? '' : ' > ' + filterText());
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  if (shown === 'overview') renderOverview(); else renderImport();
  const reading = data.reading && (data.reading.phase === 'listing' || data.reading.phase === 'copying');
  const hashing = data.replicas.some(replica => replica.reading || (replica.hashing && replica.hashing.started && replica.hashing.state !== 'done'));
  const busy = reading || hashing || (data.applying && !data.applying.done) || data.checking.busy;
  later(busy ? 2 : 10);
}

// A replica's short name: its dir's (Drive's said so)
function replicaName(path) {
  const parts = path.split('/').filter(Boolean);
  return parts[0] === 'cloud' ? 'Drive: ' + (parts.slice(1).pop() || 'all') : parts.pop() || path;
}

function percent(part, whole) { return whole ? Math.floor(100 * part / whole) + '%' : ''; }

function size(bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let at = 0;
  while (bytes >= 1024 && at < units.length - 1) { bytes /= 1024; at++; }
  return (at ? bytes.toFixed(bytes < 10 ? 1 : 0) : bytes) + ' ' + units[at];
}

function ago(seconds) {
  if (seconds === null) return '';
  return seconds < 60 ? 'just now' : seconds < 3600 ? Math.floor(seconds / 60) + ' min ago' : Math.floor(seconds / 3600) + ' h ago';
}

async function act(path, body) {
  const answer = await api('POST', path, Object.assign({id: page.id}, body));
  if (answer.error) document.getElementById('status').textContent = answer.error;
  await load();
}

// The overview: the source's files (by name and size, and hashed once copied), what each replica has
// and how sure that is (with what makes it surer), and the choices made
function renderOverview() {
  const data = page.data, over = data.overview, reading = data.reading;
  const link = (count, text, kind, replica, cls) => el('a', {class: 'stat' + (cls ? ' ' + cls : ''), href: photosLink(kind, replica)},
    el('b', {}, count), el('span', {}, text), el('span', {class: 'go'}, '›'));
  const button = (text, onclick, cls) => el('button', {class: cls || '', onclick}, text);
  const cards = [];

  const source = el('div', {class: 'card'}, el('h2', {}, data.source.device ? 'Photos on ' + data.source.device : 'Photos in ' + sourceName(data.source)),
    pathLine(data.source.device ? data.source.inner : '', data.source.full));
  if (reading && reading.phase === 'listing') source.append(el('p', {}, 'Listing its files…'));
  else {
    source.append(link(over.total, 'files', 'all'));
    source.append(el('div', {class: 'stat'}, el('b', {}, over.hashed), el('span', {}, 'copied here and hashed')),
      el('div', {class: 'meter'}, el('div', {style: 'width:' + percent(over.hashed, over.total)})));
    if (reading && reading.phase === 'copying') {
      source.append(el('p', {}, 'Copying and hashing: ' + reading.copied + ' of ' + reading.asked + '…'));
    } else if (over.unhashed.files) {
      source.append(el('p', {class: 'note'}, over.hashed ? 'The rest are compared by name and size only.' :
        'Compared by name and size only. Copying them here (a temporary copy, used to sort them too) hashes them, to compare by contents:'));
      const buttons = el('div', {class: 'row2'});
      if (over.nameOnly.files && over.nameOnly.files < over.unhashed.files) {
        buttons.append(button('Hash the ' + over.nameOnly.files + ' matched by name (' + size(over.nameOnly.size) + ')',
          () => act('/api/import/read', {which: 'nameOnly'})));
      }
      buttons.append(button('Hash all ' + over.unhashed.files + ' (' + size(over.unhashed.size) + ')', () => act('/api/import/read', {which: 'all'})));
      source.append(buttons);
    }
  }
  if (reading && reading.message) source.append(el('p', {class: 'c-orange'}, reading.message));
  if (!reading || reading.phase === 'done' || reading.phase === 'waiting') {
    source.append(el('div', {class: 'row2'}, button(data.source.device ? 'Look at the phone again' : 'Look at the folder again',
      () => act('/api/import/read', {which: 'list'}))));
  }
  cards.push(source);

  const checked = data.checking.busy ? (over.checked ? 'Checking again…' : 'Checking what they have…') :
    'Checked ' + ago(data.checking.ago) + '.';
  for (const replica of data.replicas) {
    const counted = over.replicas.find(found => found.path === replica.path);
    const card = el('div', {class: 'card'}, el('h2', {}, 'Already in “' + replica.name + '”'),
      el('p', {class: 'kind'}, replica.kind === 'drive' ? 'Google Drive replica' : 'Local disk replica'),
      pathLine('', replica.path));
    if (!over.checked) card.append(el('p', {}, checked));
    else {
      card.append(el('div', {class: 'stat'}, el('b', {}, counted.have + ' of ' + over.total), el('span', {}, 'there')),
        el('div', {class: 'meter'}, el('div', {class: 'sure', style: 'width:' + percent(counted.contents, over.total)}),
          el('div', {class: 'unsure', style: 'width:' + percent(counted.have - counted.contents, over.total)})));
      if (counted.contents) card.append(link(counted.contents, 'the same contents (by hash)', 'contents', replica.path, 'sure'));
      if (counted.namePhoneUnhashed) card.append(link(counted.namePhoneUnhashed, 'same name and size (the phone\'s not hashed)', 'name', replica.path, 'unsure'));
      if (counted.nameReplicaUnhashed) card.append(link(counted.nameReplicaUnhashed, 'same name and size (its copy isn\'t hashed)', 'name', replica.path, 'unsure'));
      card.append(link(counted.missing, 'not there', 'missing', replica.path, counted.missing ? 'missing' : ''));
      card.append(el('p', {class: 'note'}, checked));
    }
    const buttons = el('div', {class: 'row2'});
    if (replica.kind === 'drive') {
      buttons.append(replica.reading ? el('span', {class: 'note'}, 'Reading it from Drive…') :
        button('Read it from Drive again', () => act('/api/import/recheck', {replica: replica.path, how: 'drive'})));
    } else {
      if (!data.checking.busy) buttons.append(button('Check names and sizes again', () => act('/api/import/recheck', {})));
      const job = replica.hashing;
      if (job && job.started && job.state !== 'done') {
        buttons.append(el('span', {class: 'note'}, 'Hashing its files: ' + job.done + ' of ' + job.files + '…'));
      } else if (replica.unhashed) {
        buttons.append(button('Hash its ' + replica.unhashed + ' unhashed files (slower, surer)',
          () => act('/api/import/recheck', {replica: replica.path, how: 'hash'})));
      }
    }
    card.append(buttons);
    cards.push(card);
  }
  if (over.checked && over.replicas.length > 1) {
    cards.push(el('div', {class: 'card'}, el('h2', {}, 'All together'),
      link(over.inNone, 'in none of them', 'none', '', over.inNone ? 'missing' : ''),
      link(over.inAll, 'in all of them', 'all-in')));
  }
  if (over.checked && over.inAll && over.inAll > over.counts.skipped + over.counts.moved) {
    cards.push(el('div', {class: 'card'}, el('p', {}, over.inAll === over.total ?
      'Every file is in every replica already: nothing to sort.' : over.inAll + ' are in every replica already.'),
      el('div', {class: 'row2'}, button('Skip the ' + over.inAll + ' in every replica', skipInAll))));
  }
  for (const error of data.errors) cards.push(el('p', {class: 'c-red'}, error));

  const counts = over.counts;
  const open = over.total - counts.moved - counts.skipped - over.chosen;
  const end = el('button', {class: 'danger', onclick: async () => {
    if (!end.classList.contains('sure')) {
      end.classList.add('sure');
      end.textContent = 'End it: forget its choices and remove its copies';
      return;
    }
    const answer = await api('POST', '/api/import/end', {id: page.id});
    if (answer.ok) location.href = '/import'; else document.getElementById('status').textContent = answer.error || "Couldn't end it.";
  }}, 'End this import');
  cards.push(el('div', {class: 'card'}, el('h2', {}, 'Sorting into “' + replicaName(data.dest) + '”'),
    link(open, 'not chosen a folder yet', 'open'), link(over.chosen, 'chosen, to move', 'chosen'),
    counts.moved ? link(counts.moved, 'moved', 'moved') : '', counts.skipped ? link(counts.skipped, 'skipped', 'skipped') : '',
    el('div', {class: 'row2'}, el('a', {class: 'button primary', href: photosLink(over.checked && over.inNone ? 'none' : 'open')},
      over.checked && over.inNone ? 'Sort the ' + over.inNone + ' not in any replica' : 'Sort them'),
      el('a', {class: 'button', href: photosLink('all')}, 'See all'), end)));
  if (data.applying) cards.push(el('div', {class: 'lines'}, data.applying.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text))));
  if (!document.querySelector('#main button.sure')) document.getElementById('main').replaceChildren(...cards);
  renderFooter();
}

// Where the replicas have the file: the dir (the whole path if the name there is another), and how sure
function have(file) {
  const name = file.rel.split('/').pop();
  return (file.have || []).map(found => {
    const there = found.relpath.split('/').pop() === name ? (found.relpath.split('/').slice(0, -1).join('/') || '(top)') : found.relpath;
    return replicaName(found.replica) + ': ' + there + (found.how === 'contents' ? '' : ' (same name and size)');
  });
}

// The filters: [kind, its text (of a replica's name), whether a file passes it]
const FILTERS = {
  'all': ['All', () => true],
  'open': ['Not chosen a folder', file => file.state !== 'moved' && file.state !== 'skipped' && !file.target],
  'chosen': ['Chosen', file => !!file.target && file.state !== 'moved' && file.state !== 'skipped'],
  'moved': ['Moved', file => file.state === 'moved'],
  'skipped': ['Skipped', file => file.state === 'skipped'],
  'unhashed': ['Not hashed yet', file => !file.sha1],
  'have': ['Have already', file => (file.have || []).length > 0],
  'none': ['In no replica', file => file.have !== null && !file.have.length],
  'all-in': ['In every replica', file => new Set((file.have || []).map(found => found.replica)).size === page.data.checked.length],
  'in': [name => 'In ' + name, (file, replica) => haveIn(file, replica).length > 0],
  'contents': [name => 'In ' + name + ' (same contents)', (file, replica) => haveIn(file, replica).some(found => found.how === 'contents')],
  'name': [name => 'In ' + name + ' by name only', (file, replica) => haveIn(file, replica).length > 0 && !haveIn(file, replica).some(found => found.how === 'contents')],
  'missing': [name => 'Not in ' + name, (file, replica) => file.have !== null && !haveIn(file, replica).length],
};

function haveIn(file, replica) { return (file.have || []).filter(found => found.replica === replica); }

function filterText() {
  const [text] = FILTERS[page.filter.kind] || FILTERS.all;
  return typeof text === 'function' ? text(replicaName(page.filter.replica)) : text;
}

function passes(file) {
  const [, test] = FILTERS[page.filter.kind] || FILTERS.all;
  return test(file, page.filter.replica);
}

function renderImport() {
  const data = page.data;
  const main = document.getElementById('main');
  const focused = document.activeElement && document.activeElement.id === 'target';
  const parts = [];
  parts.push(el('div', {class: 'note'}, sourceName(data.source) + ' → ' + data.dest + '. Checked against: ' + data.checked.map(replicaName).join(', ') +
    (data.indexed ? '' : ' (checking them…)') + (data.errors.length ? '. ' + data.errors.join('; ') : '')));
  if (!focused) {
    const input = el('input', {type: 'text', id: 'target', list: 'folders', placeholder: 'A folder in ' + data.dest.split('/').pop() + ' (type to find one, or a new one)',
      value: page.target, oninput: event => { page.target = event.target.value; }});
    parts.push(el('div', {class: 'bar'}, input, el('datalist', {id: 'folders'}, data.folders.map(dir => el('option', {value: dir}))),
      el('button', {class: 'primary', onclick: () => assign([...page.selected], page.target)}, 'Selected here'),
      el('button', {onclick: () => assign([...page.selected], null, true)}, 'Skip selected'),
      el('button', {onclick: () => { page.selected.clear(); renderImport(); }}, 'Unselect')));
    const filters = [['all', 'All'], ['open', 'Not chosen'], ['none', 'In no replica'], ['have', 'Have already'], ['chosen', 'Chosen']];
    if (!filters.some(([key]) => key === page.filter.kind)) filters.unshift([page.filter.kind, filterText()]);
    parts.push(el('div', {class: 'chips'}, el('a', {class: 'button', href: '#'}, '‹ Overview'),
      filters.map(([key, text]) => el('a', {class: 'button' + (page.filter.kind === key ? ' on' : ''),
        href: key === page.filter.kind ? location.hash : photosLink(key)}, text))));
  } else {
    parts.push(document.querySelector('.bar'), document.querySelector('.chips'));
  }
  for (const day of data.days) {
    const files = day.files.filter(passes);
    if (!files.length) continue;
    const open = day.files.filter(file => file.state !== 'moved').map(file => file.rel);
    const header = el('h2', {}, day.day === 'None' ? 'No date' : day.day, el('small', {}, day.files.length + ' files'),
      el('button', {onclick: () => { open.forEach(rel => page.selected.add(rel)); renderImport(); }}, 'Select the day'),
      day.suggested.map(dir => el('button', {onclick: () => assign(open, dir)}, 'All to ' + dir)),
      open.length && day.files.every(file => file.state === 'moved' || (file.have || []).length) ?
        el('button', {onclick: () => assign(open, null, true)}, 'Skip the day: all there already') : '');
    parts.push(el('div', {class: 'day'}, header, el('div', {class: 'grid'}, files.map(photo))));
  }
  if (data.days.length && !data.days.some(day => day.files.some(passes))) parts.push(el('p', {class: 'note'}, 'None.'));
  if (!data.days.length) parts.push(el('p', {class: 'note'}, data.reading && data.reading.phase === 'listing' ? 'Listing the source…' : 'No media files.'));
  if (data.applying) parts.push(el('div', {class: 'lines'}, data.applying.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text))));
  main.replaceChildren(...parts);
  renderFooter();
}

const VIDEO = /\.(mp4|m4v|mov|3gp|webm|mkv)$/i;
// Each file's picture, kept across the redraws (a video isn't loaded again at each)
const pictures = new Map();

// A file's picture: the server's thumbnail; else, for a video, the browser's own first frame (the
// server may have no ffmpeg); else its name
function picture(file) {
  let image = pictures.get(file.rel);
  if (image) return image;
  const query = '?id=' + encodeURIComponent(page.id) + '&rel=' + encodeURIComponent(file.rel);
  const name = () => el('div', {class: 'noimg'}, file.rel.split('/').pop());
  const keep = node => { pictures.set(file.rel, node); return node; };
  image = keep(el('img', {loading: 'lazy', alt: file.rel, src: '/api/import/thumb' + query}));
  image.addEventListener('error', () => {
    let instead = name();
    if (VIDEO.test(file.rel)) {
      instead = el('video', {muted: true, playsinline: true, preload: 'metadata', src: '/api/import/file' + query + '#t=0.5'});
      instead.addEventListener('error', () => instead.replaceWith(keep(name())));
    }
    image.replaceWith(keep(instead));
  });
  return image;
}

function photo(file) {
  const caption = [];
  if (file.state === 'moved') caption.push(el('div', {class: 'to'}, '✓ moved'));
  else if (file.state === 'skipped') caption.push(el('div', {class: 'skipped'}, 'skipped'));
  else if (file.target) caption.push(el('div', {class: 'to'}, '→ ' + file.target));
  for (const text of have(file)) caption.push(el('div', {class: 'have'}, '✓ in ' + text));
  caption.push(el('div', {}, file.rel.split('/').pop()));
  if (VIDEO.test(file.rel) && file.state !== 'moved') {
    caption.push(el('a', {class: 'play', target: '_blank', onclick: event => event.stopPropagation(),
      href: '/api/import/file?id=' + encodeURIComponent(page.id) + '&rel=' + encodeURIComponent(file.rel)}, '▶ Play'));
  }
  const image = picture(file);
  return el('div', {class: 'photo' + (page.selected.has(file.rel) ? ' sel' : '') + (file.state === 'moved' ? ' done' : ''),
    onclick: () => {
      if (file.state === 'moved') return;
      if (page.selected.has(file.rel)) page.selected.delete(file.rel); else page.selected.add(file.rel);
      renderImport();
    }}, image, (file.have || []).length ? el('span', {class: 'badge'}, 'have') : '', el('div', {class: 'cap'}, caption));
}

// Skip the files every replica has (not the ones chosen a folder or moved)
async function skipInAll() {
  const data = await api('GET', '/api/import?id=' + encodeURIComponent(page.id));
  const rels = data.days.flatMap(day => day.files).filter(file => file.state !== 'moved' && !file.target &&
    new Set((file.have || []).map(found => found.replica)).size === data.checked.length).map(file => file.rel);
  await assign(rels, null, true);
}

async function assign(rels, target, skip) {
  if (!rels.length || (!skip && !target)) return;
  await api('POST', '/api/import/assign', {id: page.id, rels, target, skip: !!skip});
  page.selected.clear();
  await load();
}

function renderFooter() {
  const data = page.data;
  const chosen = data.overview.chosen;
  const status = [countsText(data.counts)];
  if (page.selected.size) status.push(page.selected.size + ' selected');
  document.getElementById('status').textContent = status.join(' · ');
  const buttons = [];
  buttons.push(el('button', {class: 'primary', disabled: !chosen || (data.applying && !data.applying.done),
    onclick: () => api('POST', '/api/import/apply', {id: page.id}).then(loadImport)},
    'Move ' + chosen + ' chosen into “' + replicaName(data.dest) + '”'));
  document.getElementById('actions').replaceChildren(...buttons);
}

load();
