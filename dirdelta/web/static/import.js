// The import page (web/importing.py): the inboxes, the user's phones (and any plugged in that isn't one of theirs) and
// unsorted folders; and an import, one screen: the photos and videos the replica it goes into doesn't have (those it has
// hidden, but on asking), in their groups (a phone's camera's, WhatsApp's images, its videos) and by day, each group and
// day with the folders suggested for it, chosen a folder (all at once, or the ones selected), then moved in. The server
// keeps every choice at once.
'use strict';

const params = new URLSearchParams(location.search);
const page = {id: params.get('id'), data: null, selected: new Set(), timer: null, target: '', showAll: false};

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
  renderImport();
  const reading = data.reading && (data.reading.phase === 'listing' || data.reading.phase === 'copying');
  const busy = reading || (data.applying && !data.applying.done) || data.checking.busy;
  later(busy ? 2 : 10);
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
function isShown(file) { return page.showAll || isNew(file) || isReady(file); }

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
  const counts = {new: files.filter(isNew).length, there: files.filter(file => isThere(file) && !isDone(file)).length,
    ready: files.filter(isReady).length, moved: files.filter(file => file.state === 'moved').length,
    skipped: files.filter(file => file.state === 'skipped').length};
  const parts = [];
  if (!focused) {
    parts.push(importHead(data, counts));
    // What's done with the photos selected (a folder for them, or skipping them), once there are any
    const chosen = page.selected.size ? el('div', {class: 'bar'}, el('b', {}, page.selected.size + ' selected'),
      el('input', {type: 'text', id: 'target', list: 'folders', placeholder: 'Folder in ' + data.destName + '…',
        value: page.target, oninput: event => { page.target = event.target.value; }}),
      el('datalist', {id: 'folders'}, data.folders.map(dir => el('option', {value: dir}))),
      el('button', {class: 'primary', onclick: () => assign([...page.selected], page.target)}, 'Put them in this folder'),
      el('button', {onclick: () => assign([...page.selected], null, true)}, 'Skip them'),
      el('button', {onclick: () => { page.selected.clear(); renderImport(); }}, 'Clear')) :
      el('div', {class: 'note'}, 'Tap photos to select them, or use a group\'s or a day\'s buttons.');
    parts.push(el('div', {class: 'sticky'}, sortMeter(files), chosen));
  } else {
    const sticky = document.querySelector('.sticky');
    sticky.firstChild.replaceWith(sortMeter(files));
    parts.push(document.querySelector('.importhead'), sticky);
  }
  for (const group of data.groups) parts.push(...groupParts(group, data.groups.length > 1));
  if (!files.length) parts.push(el('p', {class: 'note'}, data.reading && data.reading.phase === 'listing' ? waiting('Listing the files') : 'No photos or videos.'));
  else if (!files.some(isShown)) parts.push(el('p', {class: 'note'}, counts.there ? 'Nothing new: ' + data.destName + ' has them all.' : 'All sorted.'));
  if (data.applying) parts.push(el('div', {class: 'lines'}, data.applying.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text))));
  parts.push(endCard(data));
  if (!document.querySelector('#main button.sure')) main.replaceChildren(...parts);
  renderFooter(counts);
  fitHeader();
  showPosition();
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
  else if (reading && reading.phase === 'copying') notes.push(waiting((drive ? 'Downloading' : 'Copying') + ' the new ones, to compare their contents: ' + reading.copied + ' of ' + reading.asked));
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
    el('div', {class: 'counts'}, el('b', {}, counts.new.toLocaleString() + ' new'),
      counts.ready ? el('span', {}, counts.ready + ' ready to move') : '',
      el('span', {}, counts.there.toLocaleString() + ' already in ' + data.destName + (page.showAll ? '' : ' (hidden)')),
      counts.moved ? el('span', {}, counts.moved + ' moved') : '', counts.skipped ? el('span', {}, counts.skipped + ' skipped') : '',
      el('label', {class: 'showall'}, el('input', {type: 'checkbox', checked: page.showAll, onchange: event => { page.showAll = event.target.checked; renderImport(); }}),
        ' Show them all')),
    notes.length ? el('div', {class: 'note'}, ...notes.flatMap((note, i) => i ? [' · ', note] : [note])) : '',
    el('div', {class: 'row2'}, el('span', {class: 'note'}, data.listedAgo !== null ? 'Listed ' + ago(data.listedAgo) : ''),
      !reading || reading.phase === 'done' || reading.phase === 'waiting' ? el('button', {class: 'small quiet', onclick: () => act('/api/import/read', {which: 'list'})},
        data.source.device ? 'List the phone again' : drive ? 'Read it from Drive again' : 'List it again') : ''));
  if (twice.length) head.append(el('div', {class: 'row2 c-orange'}, twice.length + ' ' + plural(twice.length, 'file', 'files') +
    ' with a folder chosen ' + plural(twice.length, 'is', 'are') + ' in ' + data.destName + ' already: moved, ' + plural(twice.length, 'it', 'they') + '\'d be a second copy.',
    el('button', {class: 'small', onclick: () => assign(twice, null, true)}, 'Skip ' + plural(twice.length, 'it', 'them'))));
  if (data.otherDisk) head.append(el('p', {class: 'c-red'}, 'Another disk is mounted where ' + data.destName + ' was (' + data.destDisk +
    '): nothing is moved until that disk is back.'));
  return head;
}

// A group (a phone's camera's, WhatsApp's images or videos; a folder's files are one): its new files' count, the folders
// suggested for it (where the replica keeps its kind), and its days
function groupParts(group, isTitled) {
  const files = group.days.flatMap(day => day.files);
  const shown = files.filter(isShown);
  const undecided = files.filter(isUndecided).map(file => file.rel);
  const newCount = files.filter(isNew).length;
  const parts = [];
  if (isTitled) {
    parts.push(el('div', {class: 'group'}, el('h2', {}, group.title, el('small', {}, newCount ? newCount.toLocaleString() + ' new' : 'nothing new')),
      undecided.length ? el('button', {onclick: () => { undecided.forEach(rel => page.selected.add(rel)); renderImport(); }}, 'Select the ' + undecided.length) : '',
      undecided.length ? group.suggested.map(dir => el('button', {onclick: () => assign(undecided, dir)}, 'All ' + undecided.length + ' to ' + dir)) : ''));
  }
  if (!shown.length) return parts;
  for (const day of group.days) {
    const dayFiles = day.files.filter(isShown);
    if (!dayFiles.length) continue;
    const open = dayFiles.filter(isUndecided).map(file => file.rel);
    const header = el('h3', {}, day.day === 'None' ? 'No date' : day.day, el('small', {}, dayFiles.length + ' ' + plural(dayFiles.length, 'file', 'files')),
      open.length ? el('button', {onclick: () => { open.forEach(rel => page.selected.add(rel)); renderImport(); }}, 'Select the day') : '',
      open.length ? day.suggested.map(dir => el('button', {onclick: () => assign(open, dir)}, 'All to ' + dir)) : '');
    parts.push(el('div', {class: 'day', 'data-day': (isTitled ? group.title + ' · ' : '') + (day.day === 'None' ? 'No date' : day.day),
      'data-undecided': open.length}, header, el('div', {class: 'grid'}, dayFiles.map(photo))));
  }
  return parts;
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
    onclick: () => {
      if (file.state === 'moved') return;
      if (page.selected.has(file.rel)) page.selected.delete(file.rel); else page.selected.add(file.rel);
      renderImport();
    }}, image, isThere(file) ? el('span', {class: 'badge'}, 'have') : '', el('div', {class: 'cap'}, caption));
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
  const status = [counts.new.toLocaleString() + ' new'];
  if (counts.ready) status.push(counts.ready + ' ready to move');
  if (counts.moved) status.push(counts.moved + ' moved');
  if (page.selected.size) status.push(page.selected.size + ' selected');
  document.getElementById('status').textContent = status.join(' · ');
  const busy = data.applying && !data.applying.done;
  document.getElementById('actions').replaceChildren(counts.ready ? el('button', {class: 'primary', disabled: busy,
    onclick: () => api('POST', '/api/import/apply', {id: page.id}).then(answer => {
      if (answer.error) document.getElementById('status').textContent = answer.error;
      return loadImport();
    })}, busy ? waiting('Moving') : 'Move ' + counts.ready + ' into ' + data.destName) : '');
}

tabBar('inboxes');
document.title = 'Inboxes';
load();
