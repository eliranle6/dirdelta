// The import page (web/importing.py): the inboxes, the user's phones (and any plugged in that isn't one of theirs) and
// unsorted folders; and an import, one screen: the photos and videos the replica it goes into doesn't have (those it has
// hidden, but on asking), in their groups (a phone's camera's, WhatsApp's images, its videos) and by day, each group and
// day with the folders suggested for it, chosen a folder (all at once, or the ones selected), then moved in. The server
// keeps every choice at once.
'use strict';

const params = new URLSearchParams(location.search);
const page = {id: params.get('id'), data: null, selected: new Set(), timer: null, target: '', showAll: false,
  group: null, nrDays: 0, openDirs: new Set()};
page.group = groupInAddress();

// The group shown (its key, in the address: #group=whatsapp-images), one at a time: each is big on its own
function groupInAddress() { const found = /group=([\w-]+)/.exec(location.hash); return found ? found[1] : null; }
window.addEventListener('hashchange', () => {
  page.group = groupInAddress();
  page.nrDays = DAYS_AT_ONCE;
  if (page.data) { renderImport(); window.scrollTo(0, 0); }
});
// How many of a group's days are drawn at first, and more each time the end of them is scrolled to
const DAYS_AT_ONCE = 15;

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

// The inboxes: the phones plugged in and the user's own (a Drive folder, a folder here), each sorted into
// a replica (any: they're copies of one tree; the likeliest is offered first): its photos by day (an
// import, its page here), or all its files folder by folder (the sort's own screens, on /run)

function importLink(id) {
  return '/inboxes?id=' + encodeURIComponent(id);
}

// What a source is called: the phone's name, or a local dir's
function bareName(source) { return sourceName(source); }

function sourceName(source) {
  return source.device || source.full.split('/').filter(Boolean).pop() || source.full;
}

const INBOX_KINDS = {phone: ['phone', 'Phone'], drive: ['inbox', 'In Google Drive'], folder: ['folder', 'On this computer']};

// A phone plugged in that isn't one of the user's: said so, in a look of its own, with its name to give it and Add
function newPhoneCard(inbox) {
  const name = el('input', {type: 'text', value: inbox.name, 'aria-label': 'Its name'});
  const status = el('span', {class: 'note'});
  const add = el('button', {class: 'primary', onclick: async () => {
    const answer = await api('POST', '/api/phones/add', {phone: inbox.phone, name: name.value});
    if (answer.ok) loadList(); else status.textContent = answer.error;
  }}, 'Add this phone');
  return el('div', {class: 'card inbox newphone'},
    el('div', {class: 'head'}, icon('phone'), el('b', {}, 'New phone: ' + inbox.name), chip('warn', 'Not one of yours yet')),
    el('div', {class: 'note'}, 'A phone is plugged in that dirdelta doesn\'t know. Add it to import its photos and videos: ',
      (inbox.source.folders || ['DCIM']).join(', '), '.'),
    el('label', {class: 'note phonename'}, 'Call it ', name), el('div', {class: 'row2'}, add, status));
}

// One of the user's phones: its name, edited in place, and Remove (not while an import of it is kept)
function phoneActions(inbox) {
  const box = el('span', {class: 'forget'});
  const status = el('span', {class: 'note'});
  const idle = () => box.replaceChildren(
    el('button', {class: 'small quiet', onclick: editName}, 'Edit name…'),
    el('button', {class: 'small quiet', onclick: ask}, 'Remove…'), status);
  const editName = () => {
    const name = el('input', {type: 'text', value: inbox.name, 'aria-label': 'Its name'});
    box.replaceChildren(name, el('button', {class: 'small', onclick: async () => {
      const answer = await api('POST', '/api/phones/add', {phone: inbox.phone, name: name.value});
      if (answer.ok) loadList(); else status.textContent = answer.error;
    }}, 'Save'), el('button', {class: 'small', onclick: idle}, 'Cancel'), status);
    name.focus();
  };
  const ask = () => box.replaceChildren(el('span', {class: 'note'}, 'Remove ' + inbox.name + ' from your phones? Nothing on it is changed.'),
    el('button', {class: 'small danger sure', onclick: async () => {
      const answer = await api('POST', '/api/phones/remove', {phone: inbox.phone});
      if (answer.ok) loadList(); else { idle(); status.textContent = answer.error; }
    }}, 'Remove'), el('button', {class: 'small', onclick: idle}, 'Keep'));
  idle();
  return box;
}

function inboxCard(inbox) {
  if (inbox.kind === 'newphone') return newPhoneCard(inbox);
  return inbox.kind === 'phone' ? phoneCard(inbox) : folderCard(inbox);
}

// Where an inbox's files go: the main replica (the dests' first), else the one chosen; a choice only if there's another
function intoChoice(dests, dest, onchange) {
  return dests.length === 1 ? el('span', {class: 'note'}, 'Into ', el('b', {}, dests[0].name)) :
    el('label', {class: 'note into'}, 'Into ', el('select', {onchange: event => onchange(event.target.value)},
      dests.map(found => el('option', {value: found.path, selected: found.path === dest}, found.name))));
}

// One of the user's phones: its photos and videos (its camera's, WhatsApp's) imported into a replica, how far that is,
// and its name to edit, or it to remove
function phoneCard(inbox) {
  const progress = inboxProgress(inbox);
  const folders = inbox.source.folders || [inbox.source.inner];
  const parts = [el('div', {class: 'head'}, icon('phone'), el('b', {}, inbox.name),
      chip(inbox.there ? 'ok' : 'none', inbox.there ? 'Plugged in' : 'Not plugged in')),
    el('div', {class: 'note'}, 'Its photos and videos: ' + folders.join(', ')),
    inbox.imports.length ? el('div', {class: 'note'}, progress.text) : '',
    inbox.imports.length ? bar(progress.share, 'sure') : ''];
  const dests = inbox.dests;
  if (!dests.length) {
    parts.push(el('p', {class: 'note'}, 'Add a replica on this computer or a disk to import into (Replicas).'), phoneActions(inbox));
    return el('div', {class: 'card inbox'}, parts);
  }
  // (Into the main replica, else the one chosen; the import of it, if there is one, continued)
  let dest = dests[0].path;
  const opened = () => inbox.imports.find(found => found.dest === dest && !found.otherDisk);
  const go = el('button', {class: 'primary', onclick: async () => {
    const found = opened();
    if (found) return void (location.href = importLink(found.id));
    const answer = await api('POST', '/api/imports/new', {source: inbox.path, dest});
    if (answer.error) document.getElementById('status').textContent = answer.error;
    else location.href = importLink(answer.id);
  }});
  const named = () => {
    const found = opened();
    go.disabled = !inbox.there && !found;
    go.textContent = !found ? 'Import photos' : importTally(found).left ? 'Continue importing' : 'See what was imported';
  };
  named();
  parts.push(intoChoice(dests, dest, value => { dest = value; named(); }), el('div', {class: 'row2'}, go, phoneActions(inbox)));
  return el('div', {class: 'card inbox'}, parts);
}

// An unsorted folder (on a disk, or in Drive): its files, of any kind, sorted into a replica (the sort's own screens, with
// Claude's suggestions); an earlier photo import of it, if there is one, still opened from here
function folderCard(inbox) {
  const [iconName, where] = INBOX_KINDS[inbox.kind];
  const parts = [el('div', {class: 'head'}, icon(iconName), el('b', {}, inbox.name), !inbox.there ? chip('bad', 'Not there') : ''),
    pathLine(inbox.path, where)];
  // How far its sorting is: the files its sorts took out of it of those and the ones left, as the last sort ended
  const sorting = inbox.sorting;
  if (sorting && sorting.left !== null) {
    const all = sorting.sorted + sorting.left;
    parts.push(el('div', {class: 'note'}, (sorting.sorted ? sorting.sorted.toLocaleString() + ' sorted · ' : '') +
      (sorting.left ? sorting.left.toLocaleString() + ' ' + (sorting.left === 1 ? 'file' : 'files') + ' left to sort' : 'Nothing left to sort') +
      (sorting.when ? ' · last sorted ' + age(sorting.when).text : sorting.sorted ? '' : ' · not sorted here yet')),
      bar(all ? 100 * sorting.sorted / all : 100, 'sure'));
  }
  const dests = inbox.dests;
  if (!dests.length) {
    parts.push(el('p', {class: 'note'}, inbox.kind === 'drive' ? 'Add a replica to sort it into (Replicas).' :
      'Add a replica on this computer or a disk to sort it into (Replicas).'));
    return el('div', {class: 'card inbox'}, parts);
  }
  let dest = dests[0].path;
  parts.push(intoChoice(dests, dest, value => { dest = value; }),
    el('div', {class: 'row2'}, el('button', {class: 'primary', disabled: !inbox.there, onclick: () => startFlow({kind: 'sort', inbox: inbox.path, root: dest})}, 'Sort files'),
      inbox.added ? forgetButton(inbox.path, 'inbox') : ''));
  const earlier = inbox.imports.find(found => !found.otherDisk);
  if (earlier) parts.push(el('div', {class: 'note'}, 'An earlier photo import of it into ' + earlier.destName + ': ',
    el('a', {href: importLink(earlier.id)}, 'open it')));
  return el('div', {class: 'card inbox'}, parts);
}

// Adding a phone: it's the one plugged in (shown above as new, to add there); else how to plug one in
function phoneAdder(newPhones) {
  return el('div', {class: 'card quiet adder'}, el('div', {class: 'head'}, icon('phone'), el('b', {}, '+ Add a phone')),
    el('div', {class: 'note'}, newPhones.length ? 'The phone plugged in is above: name it and press Add this phone.' :
      'Plug it in by USB and choose "File transfer" on it: it shows above within a few seconds, to add.'));
}

async function loadList() {
  const data = await api('GET', '/api/imports');
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  // Two kinds, each in a block of its own (so neither is missed): unsorted folders, and phones' photos
  const folders = data.inboxes.filter(inbox => !['phone', 'newphone'].includes(inbox.kind));
  // (The user's phones, counted; and any plugged in that isn't one of theirs, first, to add)
  const phones = data.inboxes.filter(inbox => inbox.kind === 'phone'), newPhones = data.inboxes.filter(inbox => inbox.kind === 'newphone');
  const jump = kindJump, block = (id, iconName, title, text, cards, extra) => kindBlock(id, iconName, title, text, cards, extra || '');
  const parts = [...kindParts([
      {jump: jump('unsorted', 'inbox', 'Unsorted folders', thereOutOf(folders) + ' there', inboxesTone(folders)),
       block: block('unsorted', 'inbox', 'Unsorted folders',
         '',
         folders.length ? folders.map(inboxCard) : el('p', {class: 'note'}, 'None yet: add one below.'), folderAdder('inbox'))},
      {jump: jump('phones', 'phone', 'Phones\' photos', newPhones.length ? 'A new phone is plugged in' : thereOutOf(phones) + ' plugged in',
         newPhones.length ? 'warn' : inboxesTone(phones)),
       block: block('phones', 'phone', 'Phones\' photos',
         '',
         newPhones.concat(phones).length ? newPhones.concat(phones).map(inboxCard) : el('p', {class: 'note'}, 'No phones yet.'),
         phoneAdder(newPhones))}],
      {add: 'unsorted'})];
  const main = document.getElementById('main');
  if (!main.contains(document.activeElement) || document.activeElement === document.body) main.replaceChildren(...parts);
  // (A link to a kind, e.g. Home's to #phones, goes to it once it's drawn: once)
  const kind = !page.scrolled && ['unsorted', 'phones', 'add'].includes(location.hash.slice(1)) ? location.hash.slice(1) : null;
  page.scrolled = true;
  if (kind && layout() === 'blocks') document.getElementById(kind === 'add' ? 'unsorted' : kind).scrollIntoView();
  later(5);
}

// Start a flow (the sort's own screens, or the start menu), shown on /run
async function startFlow(body) {
  const answer = await api('POST', '/api/start', body);
  if (answer.ok) location.href = '/run';
  else document.getElementById('status').textContent = 'Something is running already: see Running, in the top bar.';
}

// How many files are in each state (source: where they come from, said of the ones not copied yet)
function countsText(counts, source) {
  const only = source && source.drive ? 'in Drive only' : source && !source.device ? 'not copied' : 'on the phone only';
  return [['pending', only], ['copied', 'copied'], ['moved', 'moved'], ['skipped', 'skipped']]
    .filter(([key]) => counts[key]).map(([key, text]) => counts[key] + ' ' + text).join(', ') || 'nothing yet';
}

// An import

async function loadImport() {
  const data = await api('GET', '/api/import?id=' + encodeURIComponent(page.id));
  if (data.error) throw new Error(data.error);
  page.data = data;
  document.getElementById('where').replaceChildren(' > ', sourceName(data.source) + ' → ' + data.destName);
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  // (The photos drawn again only if anything about them changed: a poll while files are copied changes counts alone)
  const signature = filesSignature(data);
  if (signature === page.signature && document.querySelector('#main .importhead') && !document.querySelector('#main button.sure')) refreshHead();
  else renderImport();
  page.signature = signature;
  const reading = data.reading && (data.reading.phase === 'listing' || data.reading.phase === 'copying');
  const busy = reading || (data.applying && !data.applying.done) || (data.removing && !data.removing.done) || data.checking.busy;
  later(busy ? 2 : 10);
}

// What the photos shown depend on: each file's state, folder and whether the replica has it
function filesSignature(data) {
  let text = '';
  for (const group of data.groups) for (const day of group.days) for (const file of day.files) {
    text += file.rel + '|' + file.state + '|' + (file.target || '') + '|' + (file.have ? file.have.length : '-') + '\n';
  }
  return text.length + ':' + hashText(text);
}

function hashText(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return hash;
}

// The head, and the footer, drawn again alone (what's being done, the counts)
function refreshHead() {
  const files = allFiles();
  const counts = {new: files.filter(isNew).length, undecided: files.filter(isUndecided).length, there: files.filter(file => isThere(file) && !isDone(file)).length,
    ready: files.filter(isReady).length, moved: files.filter(file => file.state === 'moved').length,
    skipped: files.filter(file => file.state === 'skipped').length};
  const head = document.querySelector('#main .importhead');
  if (!head.contains(document.activeElement)) head.replaceWith(importHead(page.data, counts));
  renderFooter(counts);
  showSelection();
}

function plural(count, one, many) { return count === 1 ? one : many; }

function ago(seconds) {
  if (seconds === null || seconds === undefined) return '';
  return seconds < 60 ? 'just now' : seconds < 3600 ? Math.floor(seconds / 60) + ' min ago' : Math.floor(seconds / 3600) + ' h ago';
}

// A text that's waiting for something, with dots that go on (in step across the page's redraws)
function waiting(text) {
  return el('span', {}, text, el('span', {class: 'dots', style: 'animation-delay:-' + (Date.now() % 1600) + 'ms'}));
}

async function act(path, body) {
  const answer = await api('POST', path, Object.assign({id: page.id}, body));
  if (answer.error) document.getElementById('status').textContent = answer.error;
  await load();
}

// A file's place: the replica has it (by contents, or by name and size: ≈), it's to be moved (a folder chosen), moved,
// skipped, or new (none of those)
function isThere(file) { return !!(file.have && file.have.length); }
function isDone(file) { return file.state === 'moved' || file.state === 'skipped'; }
function isNew(file) { return !isThere(file) && !isDone(file); }
function isReady(file) { return !!file.target && !isDone(file); }
function isUndecided(file) { return isNew(file) && !file.target; }
// What's shown: the new ones, and those to be moved (one the replica has too said so), else, on asking, all of them
function isShown(file) {
  if (page.group === THERE) return isInReplica(file);
  if (page.group === READY) return isReady(file);
  // (A group's: what's left to decide; what's decided is in Ready to move, or skipped; all of it on asking)
  return page.showAll || isUndecided(file);
}
// The Ready-to-move tab's: the files given a folder, by folder, to look over before Move
const READY = 'ready';
// The Already-in tab's: the files the replica has (found there, or moved into it), to remove from the source
const THERE = 'there';
function isInReplica(file) { return isThere(file) || file.state === 'moved'; }
// How sure that is: moved in, or the same contents (hashes match), or the same name and size only
function isStrong(file) { return file.state === 'moved' || (file.have || []).some(found => found.how === 'contents'); }

function allFiles() { return page.data.groups.flatMap(group => group.days.flatMap(day => day.files)); }

// Where the replica has the file, in short: its folder (or path, if its name there is another), '≈' by name and size only
function have(file) {
  const name = file.rel.split('/').pop();
  return (file.have || []).map(found => {
    const there = found.relpath.split('/').pop() === name ? (found.relpath.split('/').slice(0, -1).join('/') || '(top)') : found.relpath;
    return there + (found.how === 'contents' ? '' : ' ≈');
  });
}

// The import, one screen: where from and into (another replica chosen there), what's new and what's there already (hidden
// but on asking), what's being done; then the groups, each by day; and its end
function renderImport() {
  const data = page.data;
  const main = document.getElementById('main');
  const focused = document.activeElement && document.activeElement.id === 'target';
  const files = allFiles();
  const group = shownGroup();
  const groupFiles = group ? group.days.flatMap(day => day.files) : [];
  const counts = {new: files.filter(isNew).length, undecided: files.filter(isUndecided).length, there: files.filter(file => isThere(file) && !isDone(file)).length,
    ready: files.filter(isReady).length, moved: files.filter(file => file.state === 'moved').length,
    skipped: files.filter(file => file.state === 'skipped').length};
  const parts = [];
  if (!focused) {
    parts.push(importHead(data, counts));
    parts.push(el('div', {class: 'sticky'}, groupTabs(), [THERE, READY].includes(page.group) ? el('div', {class: 'sortmeter'}) : sortMeter(groupFiles), selectionRow()));
  } else {
    const sticky = document.querySelector('.sticky');
    sticky.querySelector('.sortmeter').replaceWith([THERE, READY].includes(page.group) ? el('div', {class: 'sortmeter'}) : sortMeter(groupFiles));
    parts.push(document.querySelector('.importhead'), sticky);
  }
  if (group) parts.push(...groupParts(group));
  if (!files.length) parts.push(el('p', {class: 'note'}, data.reading && data.reading.phase === 'listing' ? waiting('Listing the files') : 'No photos or videos.'));
  else if (group && group.key !== READY && !group.days.some(day => day.files.some(isShown))) parts.push(el('p', {class: 'note'},
    group.key === THERE ? 'None.' : group.days.some(day => day.files.some(isReady)) ? 'All decided: see ' + readyTitle() + '.' : 'Nothing new here.'));
  parts.push(endCard(data));
  if (!document.querySelector('#main button.sure')) main.replaceChildren(...parts);
  renderFooter(counts);
  fitHeader();
  fitSelectionRow();
  showPosition();
}

// What's done with the photos selected (a folder for them, or skipping them), once there are any; else how to select
// them. One height either way, so nothing under it moves as the first is selected
function selectionRow(asBar) {
  const data = page.data;
  if (page.group === THERE) return el('div', {class: 'selrow'}, removeBar(asBar));
  if (page.group === READY) {
    return el('div', {class: 'selrow'}, page.selected.size || asBar ? el('div', {class: 'bar'}, el('b', {}, page.selected.size + ' selected'),
      el('button', {onclick: () => undecide([...page.selected])}, 'Back to undecided'),
      el('button', {class: 'primary', onclick: () => chooseFolder(dir => assign([...page.selected], dir))}, 'Change folder…'),
      el('button', {onclick: () => assign([...page.selected], null, true)}, 'Skip them'),
      el('button', {onclick: () => { page.selected.clear(); showSelection(); }}, 'Clear')) :
      el('div', {class: 'note'}, 'Open a folder and tap files to change them, or Undo all of a folder.'));
  }
  // (The folders they were last put in, a tap each; any other chosen in the folder dialog)
  const recent = (data.recentDirs || []).slice(0, MAX_RECENT_SHOWN);
  const row = page.selected.size || asBar ? el('div', {class: 'bar'}, el('b', {}, page.selected.size + ' selected'),
    el('button', {class: 'primary', onclick: () => chooseFolder(dir => assign([...page.selected], dir))}, 'Choose folder…'),
    recent.map(dir => el('button', {class: 'recentdir', title: 'Put them in ' + dir, onclick: () => assign([...page.selected], dir)}, '→ ' + shortDir(dir))),
    el('button', {onclick: () => assign([...page.selected], null, true)}, 'Skip them'),
    el('button', {class: 'danger quiet', onclick: removeSelected}, 'Remove…'),
    el('button', {onclick: () => { page.selected.clear(); showSelection(); }}, 'Clear')) :
    el('div', {class: 'note'}, 'Tap photos to select them, or use a group\'s or a day\'s buttons.');
  return el('div', {class: 'selrow'}, row);
}

// The selection's row as tall as its bar is at this width (it wraps on a phone): measured on a hidden one, as the page
// is drawn and when its width changes
function fitSelectionRow() {
  const sticky = document.querySelector('.sticky');
  if (!sticky || !page.data) return;
  const probe = selectionRow(true);
  probe.style.cssText = 'position:absolute; visibility:hidden; left:0; right:0; min-height:0';
  sticky.append(probe);
  document.documentElement.style.setProperty('--selrow-h', probe.offsetHeight + 'px');
  probe.remove();
}
window.addEventListener('resize', fitSelectionRow);

// The Already-in tab's selection bar: Remove from the source (asked: removeSelected()), and Clear; else how to select them
function removeBar(asBar) {
  const data = page.data;
  const source = data.source.device || (data.source.drive ? 'the Drive inbox' : 'the folder');
  if (!page.selected.size && !asBar) return el('div', {class: 'note'}, 'Tap the ones to remove from ' + source + ', or select a day\'s or all of a kind.');
  return el('div', {class: 'bar'}, el('b', {}, page.selected.size + ' selected'),
    el('button', {class: 'danger', onclick: removeSelected}, 'Remove from ' + source + '…'),
    el('button', {onclick: () => { page.selected.clear(); showSelection(); }}, 'Clear'));
}

const MAX_RECENT_SHOWN = 5;

// A folder's last two parts (its whole path in its tooltip)
function shortDir(dir) {
  const parts = dir.split('/');
  return parts.length > 2 ? '…/' + parts.slice(-2).join('/') : dir;
}

// The folder dialog: the replica's folders, browsed (each folder's own, a tap going into it, Up going out) or searched
// (any folder whose path has what's typed), the recent ones on top, a new one made under the one shown; done calls
// done(the folder's path in the replica) once one is chosen
function chooseFolder(done) {
  const data = page.data, all = data.folders || [];
  let at = '', query = '';
  const box = el('div', {class: 'dialog'}), overlay = el('div', {class: 'overlay', onclick: event => { if (event.target === overlay) close(); }}, box);
  const close = () => { overlay.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = event => { if (event.key === 'Escape') close(); };
  const choose = dir => { close(); done(dir); };
  const children = dir => {
    const prefix = dir ? dir + '/' : '';
    return [...new Set(all.filter(path => path.startsWith(prefix) && path.length > prefix.length).map(path => prefix + path.slice(prefix.length).split('/')[0]))].sort((a, b) => a.localeCompare(b));
  };
  const row = (dir, text) => el('div', {class: 'folderrow'}, el('button', {class: 'link', onclick: () => { at = dir; query = ''; draw(); }}, icon('folder'), text),
    el('button', {class: 'small', onclick: () => choose(dir)}, 'Choose'));
  const draw = () => {
    const search = el('input', {type: 'search', placeholder: 'Search the folders of ' + data.destName, value: query,
      oninput: event => { query = event.target.value; draw(); }});
    const found = query ? all.filter(path => path.toLowerCase().includes(query.toLowerCase())).slice(0, 200) : children(at);
    const recent = data.recentDirs || [];
    const crumbs = [el('button', {class: 'link', onclick: () => { at = ''; draw(); }}, data.destName)];
    at.split('/').filter(Boolean).forEach((part, i, parts) => crumbs.push(' / ', el('button', {class: 'link', onclick: () => { at = parts.slice(0, i + 1).join('/'); draw(); }}, part)));
    const newName = el('input', {type: 'text', placeholder: 'New folder in ' + (at ? at.split('/').pop() : data.destName)});
    box.replaceChildren(
      el('div', {class: 'dialoghead'}, el('b', {}, 'Choose a folder in ' + data.destName), el('button', {class: 'small quiet', onclick: close}, '✕')),
      !query && recent.length ? el('div', {class: 'recent'}, el('div', {class: 'note'}, 'Recent'), recent.map(dir => row(dir, dir))) : '',
      search,
      query ? el('div', {class: 'note'}, found.length + (found.length === 200 ? '+' : '') + ' found') : el('div', {class: 'crumbs'}, crumbs),
      el('div', {class: 'folders'}, found.length ? found.map(dir => row(dir, query ? dir : dir.split('/').pop())) : el('div', {class: 'note'}, query ? 'None.' : 'No folders in it.')),
      query ? '' : el('div', {class: 'dialogfoot'}, newName,
        el('button', {onclick: () => { const name = newName.value.trim().replace(/^\/+|\/+$/g, ''); if (name) choose((at ? at + '/' : '') + name); }}, 'Make it and choose it'),
        at ? el('button', {class: 'primary', onclick: () => choose(at)}, 'Choose ' + at.split('/').pop()) : ''));
    if (query) { search.focus(); search.setSelectionRange(query.length, query.length); }
  };
  document.addEventListener('keydown', onKey);
  draw();
  document.body.append(overlay);
}

// A question over the page (Escape, or a tap outside it, is No): resolves to whether the user said yes
function confirmDialog(title, lines, yesText, noText) {
  return new Promise(resolve => {
    const done = answer => { overlay.remove(); document.removeEventListener('keydown', onKey); resolve(answer); };
    const onKey = event => { if (event.key === 'Escape') done(false); };
    const no = el('button', {onclick: () => done(false)}, noText || 'Cancel');
    const overlay = el('div', {class: 'overlay', onclick: event => { if (event.target === overlay) done(false); }},
      el('div', {class: 'dialog', role: 'alertdialog', 'aria-label': title}, el('div', {class: 'dialoghead'}, el('b', {}, title)),
        ...lines.map(line => typeof line === 'string' ? el('p', {}, line) : line),
        el('div', {class: 'dialogfoot'}, no, el('button', {class: 'danger sure', onclick: () => done(true)}, yesText))));
    document.addEventListener('keydown', onKey);
    document.body.append(overlay);
    no.focus();
  });
}

// Removing the files selected from the source (the phone, the folder, the Drive inbox): asked; and asked again, saying so,
// if any isn't in the replica (removed, it's gone: a phone has no trash)
async function removeSelected() {
  const data = page.data, rels = [...page.selected];
  if (!rels.length) return;
  const source = data.source.device || (data.source.drive ? 'the Drive inbox' : 'the folder');
  const byRel = new Map(allFiles().map(file => [file.rel, file]));
  const notIn = rels.filter(rel => byRel.has(rel) && !isInReplica(byRel.get(rel))).length;
  const weak = rels.filter(rel => byRel.has(rel) && isInReplica(byRel.get(rel)) && !isStrong(byRel.get(rel))).length;
  const isDry = data.label[0] === 'DRY RUN';
  const lines = [rels.length + ' ' + plural(rels.length, 'file', 'files') + ' will be removed from ' + source + '.'];
  if (weak) lines.push(weak + ' of them ' + plural(weak, 'is', 'are') + ' in ' + data.destName + ' by name and size only: likely, not sure.');
  if (notIn) lines.push(el('p', {class: 'c-red'}, notIn + ' of them ' + plural(notIn, "isn't", "aren't") + ' in ' + data.destName + ': removed, ' +
    plural(notIn, 'it', 'they') + ' will be gone for good.'));
  lines.push(isDry ? 'A dry run: nothing will be removed.' : data.source.drive ? 'They go to Drive\'s trash (30 days).' : 'A phone or a folder here has no trash: this can\'t be undone.');
  if (!await confirmDialog('Remove from ' + source + '?', lines, 'Remove ' + rels.length)) return;
  if (notIn && !isDry && !await confirmDialog('Are you sure?', [el('p', {class: 'c-red'}, notIn + ' ' + plural(notIn, 'file', 'files') +
      ' that ' + data.destName + ' doesn\'t have will be deleted from ' + source + ', for good.')], 'Yes, delete them', 'No, keep them')) return;
  const answer = await api('POST', '/api/import/remove', {id: page.id, rels, evenNotInReplica: notIn > 0});
  if (answer.error) document.getElementById('status').textContent = answer.error; else page.selected.clear();
  await load();
}

// A change of the selection shown at once: the photos' marks and the selection's row, nothing else drawn again (a
// page of thousands of photos takes a second to draw)
function showSelection() {
  for (const node of document.querySelectorAll('#main .photo')) node.classList.toggle('sel', page.selected.has(node.dataset.rel));
  for (const [button, rels] of dayToggles) {
    if (button.isConnected) labelDayToggle(button, rels); else dayToggles.delete(button);
  }
  const row = document.querySelector('.sticky .selrow');
  const focused = document.activeElement && document.activeElement.id === 'target';
  if (row && !(focused && page.selected.size)) row.replaceWith(selectionRow());
  else if (row) row.querySelector('b').textContent = page.selected.size + ' selected';
  const status = document.getElementById('status').textContent.replace(/ · \d+ selected$/, '');
  document.getElementById('status').textContent = status + (page.selected.size ? ' · ' + page.selected.size + ' selected' : '');
}

// Something going on (or done): its bar with its percentage, dots while it goes on, and what it said (if anything), at
// most LINES_SHOWN lines high, scrolled to its end (where it was, if it was scrolled up)
const LINES_SHOWN = 10;
function progress(title, count, total, isDone, lines) {
  count = count || 0;
  total = total || 0;
  const share = total ? Math.min(100, Math.floor(100 * count / total)) : (isDone ? 100 : 0);
  const box = el('div', {class: 'progress' + (isDone ? ' done' : '')},
    el('div', {class: 'progresshead'}, isDone ? el('b', {}, title) : waiting(title), el('span', {class: 'note'}, count.toLocaleString() + ' of ' + total.toLocaleString())),
    bar(share, isDone ? 'sure' : ''));
  if (lines && lines.length) {
    const log = el('div', {class: 'lines', style: '--lines:' + LINES_SHOWN}, lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text)));
    const old = document.querySelector('#main .progress .lines');
    const wasAtEnd = !old || old.scrollTop + old.clientHeight >= old.scrollHeight - 4;
    const oldTop = old ? old.scrollTop : 0;
    requestAnimationFrame(() => { log.scrollTop = wasAtEnd ? log.scrollHeight : oldTop; });
    box.append(log);
  }
  return box;
}

// The import's head: from where into which replica (another chosen there: its own import), how many are new and how
// many the replica has already (shown on asking), and what's being done (listing, copying the new ones, checking)
function importHead(data, counts) {
  const drive = data.source.drive;
  const thing = data.source.device ? 'phone' : drive ? 'Drive folder' : 'folder';
  const into = (data.dests || []).length > 1 ? el('select', {'aria-label': 'Into', onchange: async event => {
    const answer = await api('POST', '/api/imports/new', {source: data.source.full, dest: event.target.value});
    if (answer.error) document.getElementById('status').textContent = answer.error; else location.href = importLink(answer.id);
  }}, data.dests.map(found => el('option', {value: found.path, selected: found.path === data.dest}, found.name))) : el('b', {}, data.destName);
  const notes = [];
  const reading = data.reading;
  if (reading && reading.phase === 'listing') notes.push(waiting('Listing the ' + thing + '\'s files'));

  if (reading && reading.message) notes.push(el('span', {class: 'c-orange'}, reading.message));
  if (data.checking.busy && data.indexed) notes.push(waiting('Checking what ' + data.destName + ' has again'));
  for (const error of data.errors) notes.push(el('span', {class: 'c-red'}, error));
  // (Given a folder, then found in the replica already: moved, they'd be a second copy; said, and skipped on asking)
  const twice = allFiles().filter(file => isReady(file) && isThere(file)).map(file => file.rel);
  const head = el('div', {class: 'card importhead'},
    el('div', {class: 'head'}, icon(data.source.device ? 'phone' : drive ? 'inbox' : 'folder'), el('b', {}, sourceName(data.source)), ' → ', into),
    // (Until what the replica has is known, how many there are, not how many are new)
    !data.indexed ? el('div', {class: 'counts'}, el('b', {}, allFiles().length.toLocaleString() + ' photos and videos'),
      el('span', {}, waiting('finding which ' + data.destName + ' lacks'))) :
    el('div', {class: 'counts'}, el('b', {}, counts.undecided.toLocaleString() + ' to decide'),
      counts.ready ? el('span', {}, counts.ready + ' ready to move') : '',
      el('span', {}, counts.there.toLocaleString() + ' already in ' + data.destName + (page.showAll ? '' : ' (hidden)')),
      counts.moved ? el('span', {}, counts.moved + (verb() === 'move' ? ' moved' : ' copied in')) : '', counts.skipped ? el('span', {}, counts.skipped + ' skipped') : '',
      el('label', {class: 'showall'}, el('input', {type: 'checkbox', checked: page.showAll, onchange: event => { page.showAll = event.target.checked; renderImport(); }}),
        ' Show them all')),
    notes.length ? el('div', {class: 'note'}, ...notes.flatMap((note, i) => i ? [' · ', note] : [note])) : '',
    el('div', {class: 'row2'}, el('span', {class: 'note'}, data.listedAgo !== null ? 'Listed ' + ago(data.listedAgo) : ''),
      !reading || reading.phase === 'done' || reading.phase === 'waiting' ? el('button', {class: 'small quiet', onclick: () => act('/api/import/read', {which: 'list'})},
        data.source.device ? 'List the phone again' : drive ? 'Read it from Drive again' : 'List it again') : ''));
  if (twice.length) head.append(el('div', {class: 'row2 c-orange'}, twice.length + ' ' + plural(twice.length, 'file', 'files') +
    ' with a folder chosen ' + plural(twice.length, 'is', 'are') + ' in ' + data.destName + ' already: moved, ' + plural(twice.length, 'it', 'they') + '\'d be a second copy.',
    el('button', {class: 'small', onclick: () => assign(twice, null, true)}, 'Skip ' + plural(twice.length, 'it', 'them'))));
  // What's going on, each with its bar (and, copying into the replica or removing, what it said, the last lines shown)
  if (reading && reading.phase === 'copying') {
    head.append(progress((drive ? 'Downloading' : 'Copying') + ' the new ones here, to compare their contents', reading.copied, reading.asked, false));
  }
  if (data.applying) head.append(progress(data.applying.done ? 'Done' : (data.applying.moves ? 'Moving' : 'Copying') + ' into ' + data.destName,
    data.applying.count, data.applying.total, data.applying.done, data.applying.lines));
  if (data.removing) head.append(progress(data.removing.done ? 'Done' : 'Removing from ' + (data.source.device || 'the source'),
    data.removing.count, data.removing.total, data.removing.done, data.removing.lines));
  // (Removing from the source: what the replica has already, in its tab)
  const nrThere = allFiles().filter(isInReplica).length;
  if (nrThere && page.group !== THERE) head.append(el('div', {class: 'row2'}, el('a', {class: 'button', href: '#group=' + THERE},
    'Remove from ' + (data.source.device || (data.source.drive ? 'the Drive inbox' : 'the folder')) + ' what ' + data.destName + ' has (' + nrThere.toLocaleString() + ')…')));
  if (data.otherDisk) head.append(el('p', {class: 'c-red'}, 'Another disk is mounted where ' + data.destName + ' was (' + data.destDisk +
    '): nothing is moved until that disk is back.'));
  return head;
}

// A group (a phone's camera's, WhatsApp's images or videos; a folder's files are one): its new files' count, the folders
// suggested for it (where the replica keeps its kind), and its days
// The group shown: the one in the address, else the first with anything new (else the first)
function shownGroup() {
  const groups = page.data.groups;
  if (page.group === THERE) return thereGroup();
  if (page.group === READY) return {key: READY, title: readyTitle(), days: [], suggested: []};
  return groups.find(group => group.key === page.group) ||
    groups.find(group => group.days.some(day => day.files.some(isNew))) || groups[0] || null;
}

// The files the replica has, of every group, by day: the Already-in tab's
function thereGroup() {
  const days = new Map();
  for (const group of page.data.groups) for (const day of group.days) {
    const files = day.files.filter(isInReplica);
    if (!files.length) continue;
    if (!days.has(day.day)) days.set(day.day, {day: day.day, files: [], suggested: []});
    days.get(day.day).files.push(...files);
  }
  const sorted = [...days.values()].sort((a, b) => (a.day === 'None') - (b.day === 'None') || a.day.localeCompare(b.day));
  return {key: THERE, title: 'Already in ' + page.data.destName, days: sorted, suggested: []};
}

// The groups as tabs (a phone's camera's, WhatsApp's images, its videos), each with how many are new, and the files the
// replica has already (to remove from the source)
function groupTabs() {
  const groups = page.data.groups;
  const shown = shownGroup();
  const tab = (key, title, count, isOn) => el('a', {class: 'button' + (isOn ? ' on' : '') + (key === THERE ? ' theretab' : ''), role: 'tab',
    'aria-selected': String(isOn), href: '#group=' + key}, title, el('span', {class: 'tabcount'}, count));
  const nrThere = allFiles().filter(isInReplica).length, nrReady = allFiles().filter(isReady).length;
  return el('div', {class: 'grouptabs', role: 'tablist'}, groups.length > 1 ? groups.map(group => {
    const nrLeft = group.days.reduce((sum, day) => sum + day.files.filter(isUndecided).length, 0);
    return tab(group.key, group.title, nrLeft ? nrLeft.toLocaleString() + ' to decide' : 'all decided', group === shown);
  }) : groups.length ? tab(groups[0].key, 'To decide', allFiles().filter(isUndecided).length.toLocaleString(), shown === groups[0]) : '',
    nrReady ? tab(READY, readyTitle(), nrReady.toLocaleString(), page.group === READY) : '',
    nrThere ? tab(THERE, 'Already in ' + page.data.destName, nrThere.toLocaleString(), page.group === THERE) : '');
}

// The group's head (its suggestions for all of it) and its days, the first DAYS_AT_ONCE of them, more as the end of them
// is scrolled to
function groupParts(group) {
  if (group.key === THERE) return thereParts(group);
  if (group.key === READY) return readyParts();
  const files = group.days.flatMap(day => day.files);
  const undecided = files.filter(isUndecided).map(file => file.rel);
  const parts = [el('div', {class: 'group'}, el('h2', {}, group.title, el('small', {}, undecided.length ? undecided.length.toLocaleString() + ' to decide' : 'all decided')),
    undecided.length ? el('button', {onclick: () => { undecided.forEach(rel => page.selected.add(rel)); showSelection(); }}, 'Select all ' + undecided.length) : '',
    undecided.length ? group.suggested.map(dir => el('button', {onclick: () => assign(undecided, dir)}, 'All ' + undecided.length + ' to ' + dir)) : '',
    undecided.length ? el('button', {onclick: () => chooseFolder(dir => assign(undecided, dir))}, 'All to…') : '')];
  const days = group.days.filter(day => day.files.some(isShown));
  if (!page.nrDays) page.nrDays = DAYS_AT_ONCE;
  parts.push(...days.slice(0, page.nrDays).map(dayPart));
  // (Scrolled to, the next days drawn after the ones there: the page isn't drawn again)
  if (days.length > page.nrDays) parts.push(moreDays(days));
  return parts;
}

// The Already-in tab: what it's for, how sure each is (strong: the same contents; weak: the same name and size only, which
// copying the phone's file, to hash it, makes sure of), selecting all of either, and the days
function thereParts(group) {
  const files = group.days.flatMap(day => day.files);
  const strong = files.filter(isStrong).map(file => file.rel), weak = files.filter(file => !isStrong(file)).map(file => file.rel);
  const select = rels => { rels.forEach(rel => page.selected.add(rel)); showSelection(); };
  const source = page.data.source.device ? page.data.source.device : 'the inbox';
  const parts = [el('div', {class: 'group'}, el('h2', {}, group.title, el('small', {}, files.length.toLocaleString() + ' on ' + source + ' too')),
    strong.length ? el('button', {onclick: () => select(strong)}, '✓ Select the ' + strong.length.toLocaleString() + ' with the same contents') : '',
    weak.length ? el('button', {onclick: () => select(weak)}, '≈ Select the ' + weak.length.toLocaleString() + ' with the same name and size') : '',
    weak.length && !page.data.source.drive ? el('button', {class: 'quiet', title: 'Copies them here and hashes them: needs the phone plugged in',
      onclick: () => act('/api/import/read', {which: 'nameOnly'})}, 'Compare their contents') : ''),
    el('p', {class: 'note'}, 'Pick what to remove from ' + source + ': ✓ the same contents in ' + page.data.destName +
      ' (sure), ≈ the same name and size only (likely, not sure).')];
  const days = group.days;
  if (!page.nrDays) page.nrDays = DAYS_AT_ONCE;
  parts.push(...days.slice(0, page.nrDays).map(dayPart));
  if (days.length > page.nrDays) parts.push(moreDays(days));
  return parts;
}

// The Ready-to-move tab: the files given a folder, by folder, each folder a row that opens to its photos (drawn once it's
// opened), with Undo (back to deciding); Move, in the footer, moves them all
function readyParts() {
  const byDir = new Map();
  for (const file of allFiles().filter(isReady)) {
    if (!byDir.has(file.target)) byDir.set(file.target, []);
    byDir.get(file.target).push(file);
  }
  const dirs = [...byDir.keys()].sort((a, b) => a.localeCompare(b));
  if (!dirs.length) return [el('p', {class: 'note'}, 'Nothing yet: give files a folder in the other tabs.')];
  const total = dirs.reduce((sum, dir) => sum + byDir.get(dir).length, 0);
  return [el('div', {class: 'group'}, el('h2', {}, readyTitle() + ' into ' + page.data.destName,
      el('small', {}, total.toLocaleString() + ' in ' + dirs.length + ' ' + plural(dirs.length, 'folder', 'folders')))),
    el('p', {class: 'note'}, 'Open a folder to look at its files; ' + capitalized(verb()) + ', below, ' + verb() + 's them all' +
      (page.data.source.drive ? '.' : ' (the ' + (page.data.source.device ? 'phone' : 'folder') + ' keeps its own).')),
    ...dirs.map(dir => {
      const files = byDir.get(dir), rels = files.map(file => file.rel);
      // (Its files drawn once it's opened; opened, it stays so as the page is drawn again: a change, a move)
      const isOpen = page.openDirs.has(dir);
      const grid = el('div', {class: 'grid'}, isOpen ? files.map(photo) : []);
      const folder = el('details', {class: 'readydir', open: isOpen, ontoggle: () => {
        if (folder.open) page.openDirs.add(dir); else page.openDirs.delete(dir);
        if (folder.open && !grid.childElementCount) grid.replaceChildren(...files.map(photo));
      }}, el('summary', {}, el('span', {class: 'readyname'}, icon('folder'), '→ ' + dir), el('small', {}, files.length + ' ' + plural(files.length, 'file', 'files')),
        el('span', {class: 'readyacts'}, dayToggle(rels),
          el('button', {onclick: event => { event.preventDefault(); undecide(rels); }}, 'Undo all'))), grid);
      return folder;
    })];
}

// Back to deciding: no folder, not skipped
async function undecide(rels) {
  if (!rels.length) return;
  await api('POST', '/api/import/assign', {id: page.id, rels, target: null, skip: false});
  page.selected.clear();
  await load();
}

// What putting files into the replica does to them: a Drive inbox's are moved (out of it), a phone's or a folder's copied
function verb() { return page.data.source.drive ? 'move' : 'copy'; }
function capitalized(text) { return text ? text[0].toUpperCase() + text.slice(1) : text; }
function readyTitle() { return 'Ready to ' + verb(); }

// The next days, drawn as the end of the ones there is scrolled to
function moreDays(days) {
  const more = el('div', {class: 'note more'}, 'Showing ' + page.nrDays + ' of ' + days.length + ' days…');
  new IntersectionObserver((seen, observer) => {
    if (!seen.some(entry => entry.isIntersecting)) return;
    observer.disconnect();
    const next = days.slice(page.nrDays, page.nrDays + DAYS_AT_ONCE);
    page.nrDays += next.length;
    more.before(...next.map(dayPart));
    if (page.nrDays >= days.length) more.remove(); else { more.textContent = 'Showing ' + page.nrDays + ' of ' + days.length + ' days…'; observer.observe(more); }
  }, {rootMargin: '600px'}).observe(more);
  return more;
}

// A day's toggle: all its files shown selected, or none of them (☐ Select all 12 / ☑ All 12 selected)
const dayToggles = new Map();
function dayToggle(rels) {
  const button = el('button', {class: 'daytoggle', onclick: event => {
    // (In a folder's row, not opening it too)
    event.preventDefault();
    const all = rels.every(rel => page.selected.has(rel));
    rels.forEach(rel => all ? page.selected.delete(rel) : page.selected.add(rel));
    showSelection();
  }});
  dayToggles.set(button, rels);
  labelDayToggle(button, rels);
  return button;
}
function labelDayToggle(button, rels) {
  const all = rels.every(rel => page.selected.has(rel));
  button.textContent = all ? '☑ All ' + rels.length + ' selected' : '☐ Select all ' + rels.length;
  button.classList.toggle('on', all);
}

function dayPart(day) {
  const dayFiles = day.files.filter(isShown);
  const open = dayFiles.filter(isUndecided).map(file => file.rel);
  const selectable = dayFiles.filter(file => file.state !== 'moved' || page.group === THERE).map(file => file.rel);
  const header = el('h3', {}, day.day === 'None' ? 'No date' : day.day, el('small', {}, dayFiles.length + ' ' + plural(dayFiles.length, 'file', 'files')),
    selectable.length ? dayToggle(selectable) : '',
    open.length ? day.suggested.map(dir => el('button', {onclick: () => assign(open, dir)}, 'All to ' + dir)) : '',
    open.length ? el('button', {onclick: () => chooseFolder(dir => assign(open, dir))}, 'All to…') : '');
  return el('div', {class: 'day', 'data-day': day.day === 'None' ? 'No date' : day.day, 'data-undecided': open.length},
    header, el('div', {class: 'grid'}, dayFiles.map(photo)));
}

// Ending the import: what it forgets, and what it doesn't touch; asked twice
function endCard(data) {
  const end = el('button', {class: 'small danger', onclick: async () => {
    if (!end.classList.contains('sure')) {
      end.classList.add('sure');
      end.textContent = 'Yes, end it';
      return;
    }
    const answer = await api('POST', '/api/import/end', {id: page.id});
    if (answer.ok) location.href = '/inboxes'; else document.getElementById('status').textContent = answer.error || "Couldn't end it.";
  }}, 'End this import');
  return el('div', {class: 'card quiet endimport'}, el('span', {class: 'note'}, 'Done with this import? Ending it forgets its choices and its copies here; nothing on the ' +
    (data.source.device ? 'phone' : data.source.drive ? 'Drive inbox' : 'folder') + ' or in ' + data.destName + ' is touched.'), end);
}

// How far the sorting is: the new files decided (a folder chosen, skipped or moved) of all of them, a bar, where the
// page is (which day of the ones shown), and a jump to the next day with files left to decide
function sortMeter(files) {
  const toSort = files.filter(file => !isThere(file) || isDone(file));
  const decided = toSort.filter(file => !isUndecided(file)).length;
  const share = toSort.length ? Math.floor(100 * decided / toSort.length) : 100;
  return el('div', {class: 'sortmeter'},
    el('div', {class: 'big'}, el('b', {}, share + '%'), el('span', {}, decided + ' of ' + toSort.length + ' new decided'),
      el('button', {onclick: () => window.scrollTo({top: 0, behavior: 'smooth'})}, 'Top'),
      el('button', {onclick: nextUndecided}, 'Next undecided ›')),
    el('div', {class: 'meter thick'}, el('div', {class: 'sure', style: 'width:' + share + '%'})),
    el('div', {id: 'position', class: 'note'}));
}

// The day at the top of what's shown (under the sticky bar), and its number among the days shown
function currentDay() {
  const days = [...document.querySelectorAll('#main .day')];
  const under = (document.querySelector('.sticky') || {getBoundingClientRect: () => ({bottom: 0})}).getBoundingClientRect().bottom;
  let at = 0;
  days.forEach((day, index) => { if (day.getBoundingClientRect().top <= under + 20) at = index; });
  return {days, at};
}

function showPosition() {
  const shown = document.getElementById('position');
  if (!shown) return;
  const {days, at} = currentDay();
  shown.textContent = days.length ? 'Day ' + (at + 1) + ' of ' + days.length + ' · ' + days[at].dataset.day : '';
}

function nextUndecided() {
  const {days, at} = currentDay();
  const next = days.slice(at + 1).concat(days.slice(0, at + 1)).find(day => +day.dataset.undecided > 0);
  if (next) next.scrollIntoView({behavior: 'smooth'});
}

// The sticky bar sits under the header, whatever its height (the tabs may wrap)
function fitHeader() {
  document.documentElement.style.setProperty('--head', document.getElementById('top').offsetHeight + 'px');
}

window.addEventListener('scroll', () => requestAnimationFrame(showPosition), {passive: true});
window.addEventListener('resize', fitHeader);

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
  for (const text of have(file)) caption.push(el('div', {class: 'have'}, '✓ in ' + page.data.destName + ' · ' + text));
  caption.push(el('div', {}, file.rel.split('/').pop()));
  if (VIDEO.test(file.rel) && file.state !== 'moved') {
    caption.push(el('a', {class: 'play', target: '_blank', onclick: event => event.stopPropagation(),
      href: '/api/import/file?id=' + encodeURIComponent(page.id) + '&rel=' + encodeURIComponent(file.rel)}, '▶ Play'));
  }
  const image = picture(file);
  return el('div', {class: 'photo' + (page.selected.has(file.rel) ? ' sel' : '') + (file.state === 'moved' ? ' done' : ''),
    'data-rel': file.rel, onclick: () => {
      if (file.state === 'moved' && page.group !== THERE) return;
      if (page.selected.has(file.rel)) page.selected.delete(file.rel); else page.selected.add(file.rel);
      showSelection();
    }}, image, isInReplica(file) ? el('span', {class: 'badge ' + (isStrong(file) ? 'strong' : 'weak'),
      title: isStrong(file) ? 'The same contents in ' + page.data.destName : 'The same name and size in ' + page.data.destName + ' (not sure)'},
      isStrong(file) ? '✓ same' : '≈ likely') : '', el('div', {class: 'cap'}, caption));
}

async function assign(rels, target, skip) {
  if (!rels.length || (!skip && !target)) return;
  await api('POST', '/api/import/assign', {id: page.id, rels, target, skip: !!skip});
  page.selected.clear();
  await load();
}

// The footer: how far it is, in plain words, and Move once any file is ready to move
function renderFooter(counts) {
  const data = page.data;
  const status = [counts.undecided.toLocaleString() + ' to decide'];
  if (counts.ready) status.push(counts.ready + ' ready to move');
  if (counts.moved) status.push(counts.moved + (verb() === 'move' ? ' moved' : ' copied in'));
  if (page.selected.size) status.push(page.selected.size + ' selected');
  document.getElementById('status').textContent = status.join(' · ');
  const busy = data.applying && !data.applying.done;
  document.getElementById('actions').replaceChildren(counts.ready ? el('button', {class: 'primary', disabled: busy,
    onclick: () => api('POST', '/api/import/apply', {id: page.id}).then(answer => {
      if (answer.error) document.getElementById('status').textContent = answer.error;
      return loadImport();
    })}, busy ? waiting(capitalized(verb()) + 'ing') : capitalized(verb()) + ' ' + counts.ready + ' into ' + data.destName) : '');
}

tabBar('inboxes');
document.title = 'Inboxes';
load();
