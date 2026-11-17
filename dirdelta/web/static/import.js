// The import page (web/importing.py): the imports and the phones plugged in; an import's photos by day,
// each tagged with where the replicas have it already, chosen a dir (a day at once, or the ones
// selected), then moved in. The server keeps every choice at once.
'use strict';

const params = new URLSearchParams(location.search);
const page = {id: params.get('id'), data: null, selected: new Set(), filter: 'all', timer: null, target: ''};

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
      return el('div', {class: 'row2'}, el('span', {}, phone.name), '→', select,
        el('button', {class: 'primary', onclick: () => start(phone.path, select)}, 'Import'));
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
  const data = await api('GET', '/api/import?id=' + encodeURIComponent(page.id));
  if (data.error) throw new Error(data.error);
  page.data = data;
  document.getElementById('where').textContent = ' > ' + data.id;
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  renderImport();
  const busy = (data.copying && data.copying.phase !== 'done' && data.copying.phase !== 'waiting') ||
    (data.applying && !data.applying.done) || !data.indexed;
  later(busy ? 2 : 10);
}

function allFiles() { return page.data.days.flatMap(day => day.files); }

// Where the replicas have the file: the dir (the whole path if the name there is another), and how sure
function have(file) {
  const name = file.rel.split('/').pop();
  return (file.have || []).map(found => {
    const there = found.relpath.split('/').pop() === name ? (found.relpath.split('/').slice(0, -1).join('/') || '(top)') : found.relpath;
    return found.replica.split('/').pop() + ': ' + there + (found.how === 'same contents' ? '' : ' (same name and size)');
  });
}

function passes(file) {
  if (page.filter === 'open') return file.state !== 'moved' && file.state !== 'skipped' && !file.target;
  if (page.filter === 'have') return (file.have || []).length > 0;
  if (page.filter === 'chosen') return !!file.target || file.state === 'moved';
  return true;
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
    const filters = [['all', 'All'], ['open', 'Not chosen'], ['have', 'Have already'], ['chosen', 'Chosen']];
    parts.push(el('div', {class: 'chips'}, filters.map(([key, text]) => el('button', {class: page.filter === key ? 'on' : '',
      onclick: () => { page.filter = key; renderImport(); }}, text))));
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
  if (!data.days.length) parts.push(el('p', {class: 'note'}, data.copying && data.copying.phase === 'listing' ? 'Listing the source…' : 'No media files.'));
  if (data.applying) parts.push(el('div', {class: 'lines'}, data.applying.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text))));
  main.replaceChildren(...parts);
  renderFooter();
}

function photo(file) {
  const caption = [];
  if (file.state === 'moved') caption.push(el('div', {class: 'to'}, '✓ moved'));
  else if (file.state === 'skipped') caption.push(el('div', {class: 'skipped'}, 'skipped'));
  else if (file.target) caption.push(el('div', {class: 'to'}, '→ ' + file.target));
  for (const text of have(file)) caption.push(el('div', {class: 'have'}, '✓ in ' + text));
  if (file.state === 'pending') caption.push(el('div', {class: 'skipped'}, 'copying…'));
  caption.push(el('div', {}, file.rel.split('/').pop()));
  const image = file.state === 'pending' ? el('div', {class: 'noimg'}, 'not copied yet') :
    el('img', {loading: 'lazy', alt: file.rel, src: '/api/import/thumb?id=' + encodeURIComponent(page.id) + '&rel=' + encodeURIComponent(file.rel)});
  image.addEventListener('error', () => image.replaceWith(el('div', {class: 'noimg'}, file.rel.split('/').pop())));
  return el('div', {class: 'photo' + (page.selected.has(file.rel) ? ' sel' : '') + (file.state === 'moved' ? ' done' : ''),
    onclick: () => {
      if (file.state === 'moved') return;
      if (page.selected.has(file.rel)) page.selected.delete(file.rel); else page.selected.add(file.rel);
      renderImport();
    }}, image, (file.have || []).length ? el('span', {class: 'badge'}, 'have') : '', el('div', {class: 'cap'}, caption));
}

async function assign(rels, target, skip) {
  if (!rels.length || (!skip && !target)) return;
  await api('POST', '/api/import/assign', {id: page.id, rels, target, skip: !!skip});
  page.selected.clear();
  await loadImport();
}

function renderFooter() {
  const data = page.data;
  const files = allFiles();
  const chosen = files.filter(file => file.target && file.state === 'copied').length;
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
