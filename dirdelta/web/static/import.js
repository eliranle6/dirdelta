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

// The imports, and starting one

async function loadList() {
  const data = await api('GET', '/api/imports');
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  const destSelect = () => el('select', {class: 'dest'}, data.dests.map(dest =>
    el('option', {value: dest, selected: dest === data.defaultDest}, dest)));
  const start = async (source, select) => {
    const answer = await api('POST', '/api/imports/new', {source, dest: select.value});
    if (answer.error) alert(answer.error); else location.href = '/import?id=' + encodeURIComponent(answer.id);
  };
  const cards = [];
  if (!data.dests.length) cards.push(el('div', {class: 'card'}, el('p', {}, 'No local replica is known yet: sync one first.')));
  cards.push(el('div', {class: 'card'}, el('h2', {}, 'Phones plugged in'),
    data.phones.length ? data.phones.map(phone => {
      const select = destSelect();
      const earlier = () => data.imports.find(found => found.source === phone.path && found.dest === select.value);
      const button = el('button', {class: 'primary', onclick: () => start(phone.path, select)});
      const label = () => { button.textContent = earlier() ? 'Go on with ' + earlier().id : 'Import'; };
      select.addEventListener('change', label);
      label();
      return el('div', {class: 'row2'}, el('span', {}, phone.name), '→', select, button);
    }) : el('p', {}, 'None. Plug the phone in by USB and choose "File transfer" on it; it shows here (this page checks again every few seconds).')));
  const folder = el('input', {type: 'text', placeholder: '/path/to/a/folder'});
  const folderDest = destSelect();
  cards.push(el('div', {class: 'card'}, el('h2', {}, 'Import from a folder'),
    el('div', {class: 'row2'}, folder, '→', folderDest, el('button', {onclick: () => start(folder.value, folderDest)}, 'Import'))));
  if (data.imports.length) {
    cards.push(el('div', {class: 'card'}, el('h2', {}, 'Imports'), data.imports.map(found => el('div', {class: 'row2'},
      el('a', {href: '/import?id=' + encodeURIComponent(found.id)}, found.id),
      el('span', {class: 'note'}, found.source + ' → ' + found.dest + ': ' + countsText(found.counts))))));
  }
  const main = document.getElementById('main');
  if (!main.contains(document.activeElement)) main.replaceChildren(...cards);
  later(4);
}

function countsText(counts) {
  return [['pending', 'to copy'], ['copied', 'copied'], ['moved', 'moved'], ['skipped', 'skipped']]
    .filter(([key]) => counts[key]).map(([key, text]) => counts[key] + ' ' + text).join(', ') || 'nothing yet';
}

// An import

async function loadImport() {
  const shown = view();
  const data = await api('GET', '/api/import?id=' + encodeURIComponent(page.id) + (shown === 'overview' ? '&files=0' : ''));
  if (data.error) throw new Error(data.error);
  if (view() !== shown) return;
  page.data = data;
  document.getElementById('where').replaceChildren(' > ', shown === 'overview' ? data.id :
    el('a', {href: '#'}, data.id), shown === 'overview' ? '' : ' > ' + filterText());
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  if (shown === 'overview') renderOverview(); else renderImport();
  const busy = (data.copying && data.copying.phase !== 'done' && data.copying.phase !== 'waiting') ||
    (data.applying && !data.applying.done) || !data.indexed || data.counts.pending;
  later(busy ? 2 : 10);
}

// A replica's short name: its dir's (Drive's said so)
function replicaName(path) {
  const parts = path.split('/').filter(Boolean);
  return parts[0] === 'cloud' ? 'Drive: ' + (parts.slice(1).pop() || 'all') : parts.pop() || path;
}

function percent(part, whole) { return whole ? Math.floor(100 * part / whole) + '%' : ''; }

// The overview: the source's files and their hashing, what each replica has, and the choices made
function renderOverview() {
  const data = page.data, over = data.overview;
  const link = (count, text, kind, replica, cls) => el('a', {class: 'stat' + (cls ? ' ' + cls : ''), href: photosLink(kind, replica)},
    el('b', {}, count), el('span', {}, text), el('span', {class: 'go'}, '›'));
  const bar = (part, whole, cls) => el('div', {class: 'meter'}, el('div', {class: cls || '', style: 'width:' + percent(part, whole)}));
  const cards = [];
  const copyingNow = data.copying;
  const source = el('div', {class: 'card'}, el('h2', {}, replicaName(data.source)), el('p', {}, data.source));
  if (copyingNow && copyingNow.phase === 'listing') source.append(el('p', {}, 'Listing its files…'));
  else {
    source.append(link(over.total, 'files on it', 'all'));
    const unhashed = over.total - over.hashed;
    source.append(el('div', {class: 'stat'}, el('b', {}, over.hashed), el('span', {},
      unhashed ? 'hashed so far (each is hashed as it\'s copied here)' : 'hashed: all of them')), bar(over.hashed, over.total));
    if (unhashed) source.append(link(unhashed, 'not hashed yet' + (copyingNow && copyingNow.phase === 'copying' ? ': hashing…' : ''), 'unhashed'));
  }
  if (copyingNow && copyingNow.message) source.append(el('p', {class: 'c-orange'}, copyingNow.message));
  cards.push(source);
  if (!over.checked) {
    cards.push(el('div', {class: 'card'}, el('h2', {}, 'Your replicas'),
      el('p', {}, 'Checking what ' + data.checked.map(replicaName).join(', ') + ' have…')));
  } else {
    for (const replica of over.replicas) {
      const card = el('div', {class: 'card'}, el('h2', {}, 'In ' + replicaName(replica.path)), el('p', {}, replica.path));
      card.append(el('div', {class: 'stat'}, el('b', {}, replica.have + ' of ' + over.total), el('span', {}, 'there already')),
        el('div', {class: 'meter'}, el('div', {class: 'sure', style: 'width:' + percent(replica.contents, over.total)}),
          el('div', {class: 'unsure', style: 'width:' + percent(replica.have - replica.contents, over.total)})));
      if (replica.contents) card.append(link(replica.contents, 'the same contents (by hash)', 'contents', replica.path, 'sure'));
      if (replica.namePhoneUnhashed) card.append(link(replica.namePhoneUnhashed, 'by name and size only: the phone\'s not hashed yet', 'name', replica.path, 'unsure'));
      if (replica.nameReplicaUnhashed) card.append(link(replica.nameReplicaUnhashed, 'by name and size only: its copy isn\'t hashed', 'name', replica.path, 'unsure'));
      card.append(link(replica.missing, 'not there', 'missing', replica.path, replica.missing ? 'missing' : ''));
      cards.push(card);
    }
    if (over.replicas.length > 1) {
      cards.push(el('div', {class: 'card'}, el('h2', {}, 'All together'),
        link(over.inNone, 'in none of them', 'none', '', over.inNone ? 'missing' : ''),
        link(over.inAll, 'in all of them', 'all-in')));
    }
    if (over.inAll && over.inAll > over.counts.skipped + over.counts.moved) {
      cards.push(el('div', {class: 'card'}, el('p', {}, over.inAll === over.total ?
        'Every file is in every replica already: nothing to sort.' : over.inAll + ' are in every replica already.'),
        el('div', {class: 'row2'}, el('button', {onclick: skipInAll}, 'Skip the ' + over.inAll + ' in every replica'))));
    }
  }
  for (const error of data.errors) cards.push(el('p', {class: 'c-red'}, error));
  const counts = over.counts;
  const open = over.total - counts.moved - counts.skipped - over.chosen;
  cards.push(el('div', {class: 'card'}, el('h2', {}, 'Sorting into ' + replicaName(data.dest)),
    link(open, 'not chosen a folder yet', 'open'), link(over.chosen, 'chosen, to move', 'chosen'),
    counts.moved ? link(counts.moved, 'moved', 'moved') : '', counts.skipped ? link(counts.skipped, 'skipped', 'skipped') : '',
    el('div', {class: 'row2'}, el('a', {class: 'button primary', href: photosLink(over.checked && over.inNone ? 'none' : 'open')},
      over.checked && over.inNone ? 'Sort the ' + over.inNone + ' not in any replica' : 'Sort them'),
      el('a', {class: 'button', href: photosLink('all')}, 'See all'))));
  if (data.applying) cards.push(el('div', {class: 'lines'}, data.applying.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text))));
  document.getElementById('main').replaceChildren(...cards);
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
  parts.push(el('div', {class: 'note'}, data.source + ' → ' + data.dest + '. Checked against: ' + data.checked.join(', ') +
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
  if (!data.days.length) parts.push(el('p', {class: 'note'}, data.copying && data.copying.phase === 'listing' ? 'Listing the source…' : 'No media files.'));
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
  if (file.state === 'pending') caption.push(el('div', {class: 'skipped'}, 'copying…'));
  caption.push(el('div', {}, file.rel.split('/').pop()));
  if (VIDEO.test(file.rel) && file.state !== 'pending' && file.state !== 'moved') {
    caption.push(el('a', {class: 'play', target: '_blank', onclick: event => event.stopPropagation(),
      href: '/api/import/file?id=' + encodeURIComponent(page.id) + '&rel=' + encodeURIComponent(file.rel)}, '▶ Play'));
  }
  const image = file.state === 'pending' ? el('div', {class: 'noimg'}, 'not copied yet') : picture(file);
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
  const chosen = data.overview.ready;
  const status = [countsText(data.counts)];
  if (page.selected.size) status.push(page.selected.size + ' selected');
  if (data.copying && data.copying.message) status.push(data.copying.message);
  document.getElementById('status').textContent = status.join(' · ');
  const buttons = [];
  if (data.copying && data.copying.phase === 'waiting' || (!data.copying && data.counts.pending)) {
    buttons.push(el('button', {onclick: () => api('POST', '/api/import/copy', {id: page.id}).then(loadImport)}, 'Copy the rest'));
  }
  buttons.push(el('button', {class: 'primary', disabled: !chosen || (data.applying && !data.applying.done),
    onclick: () => api('POST', '/api/import/apply', {id: page.id}).then(loadImport)},
    'Move ' + chosen + ' chosen into ' + data.dest.split('/').pop()));
  document.getElementById('actions').replaceChildren(...buttons);
}

load();
