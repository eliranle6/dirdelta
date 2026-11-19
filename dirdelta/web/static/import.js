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

function inboxCard(inbox) {
  const [iconName, where] = INBOX_KINDS[inbox.kind];
  const progress = inboxProgress(inbox);
  const head = el('div', {class: 'head'}, icon(iconName), el('b', {}, inbox.kind === 'phone' ? 'Photos on ' + inbox.name : inbox.name),
    inbox.kind === 'phone' ? chip(inbox.there ? 'ok' : 'none', inbox.there ? 'Plugged in' : 'Not plugged in') :
      !inbox.there ? chip('bad', 'Not there') : '');
  const parts = [head, inbox.kind === 'phone' ? pathLine(inbox.source.full, where + ' · its ' + inbox.source.inner + ' folder') : pathLine(inbox.path, where),
    el('div', {class: 'note'}, progress.text),
    bar(progress.share, 'sure'),
    progress.checked ? el('div', {class: 'note'}, progress.checked) : ''];
  const dests = inbox.dests;
  if (!dests.length) {
    parts.push(el('p', {class: 'note'}, inbox.kind === 'drive' ? 'Add a replica to sort it into (Replicas).' :
      'Add a replica on this computer or a disk to sort it into (Replicas).'));
    return el('div', {class: 'card inbox'}, parts);
  }
  // Into which replica: the one an import has, else the likeliest; a choice only if there's another
  const ongoing = inbox.imports.find(found => !found.otherDisk);
  let dest = ongoing ? ongoing.dest : dests[0].path;
  const opened = () => inbox.imports.find(found => found.dest === dest && !found.otherDisk);
  const sortPhotos = el('button', {class: 'primary', disabled: !inbox.there && !opened(), onclick: async () => {
    const found = opened();
    if (found) return void (location.href = importLink(found.id));
    const answer = await api('POST', '/api/imports/new', {source: inbox.path, dest});
    if (answer.error) document.getElementById('status').textContent = answer.error;
    else location.href = importLink(answer.id);
  }});
  const named = () => {
    const found = opened();
    sortPhotos.textContent = !found ? 'Sort photos' : importTally(found).left ? 'Continue sorting photos' : 'See its photos';
  };
  named();
  const into = dests.length === 1 ? el('span', {class: 'note'}, 'Into ', el('b', {}, dests[0].name)) :
    el('label', {class: 'note into'}, 'Into ', el('select', {onchange: event => { dest = event.target.value; named(); }},
      dests.map(found => el('option', {value: found.path, selected: found.path === dest}, found.name))));
  parts.push(into, el('div', {class: 'row2'}, sortPhotos,
    inbox.kind !== 'phone' ? el('button', {disabled: !inbox.there, onclick: () => startFlow({kind: 'sort', inbox: inbox.path, root: dest})}, 'Sort all files') : '',
    inbox.added ? forgetButton(inbox.path, 'inbox') : ''));
  return el('div', {class: 'card inbox'}, parts);
}

async function loadList() {
  const data = await api('GET', '/api/imports');
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  // Two kinds, each in a block of its own (so neither is missed): unsorted folders, and phones' photos
  const folders = data.inboxes.filter(inbox => inbox.kind !== 'phone'), phones = data.inboxes.filter(inbox => inbox.kind === 'phone');
  const jump = kindJump, block = (id, iconName, title, text, cards, extra) => kindBlock(id, iconName, title, text, cards, extra || '');
  const parts = [...kindParts([
      {jump: jump('unsorted', 'inbox', 'Unsorted folders', thereOutOf(folders) + ' there', inboxesTone(folders)),
       block: block('unsorted', 'inbox', 'Unsorted folders',
         'Folders new files land in, e.g. unsorted in Google Drive. Sort their photos by day, with previews, or all their files, folder by folder.',
         folders.length ? folders.map(inboxCard) : el('p', {class: 'note'}, 'None yet: add one below.'), folderAdder('inbox'))},
      {jump: jump('phones', 'phone', 'Phones\' photos', thereOutOf(phones) + ' plugged in', inboxesTone(phones)),
       block: block('phones', 'phone', 'Phones\' photos',
         'A phone plugged in by USB: its camera\'s photos and videos, sorted by day, with previews and where they are already.',
         phones.length ? phones.map(inboxCard) : el('div', {class: 'card quiet'}, el('div', {class: 'head'}, icon('phone'), el('b', {}, 'No phone plugged in')),
           el('div', {class: 'note'}, 'Plug one in by USB and choose "File transfer" on it: it shows here within a few seconds.')))}],
      {add: 'unsorted'})];
  const main = document.getElementById('main');
  if (!main.contains(document.activeElement) || document.activeElement === document.body) main.replaceChildren(...parts);
  // (A link to a kind, e.g. Home's to #phones, goes to it once it's drawn: once)
  const kind = !page.scrolled && ['unsorted', 'phones', 'add'].includes(location.hash.slice(1)) ? location.hash.slice(1) : null;
  page.scrolled = true;
  if (kind && layout() !== 'tabs') document.getElementById(kind === 'add' ? 'unsorted' : kind).scrollIntoView();
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
  const shown = view();
  const data = await api('GET', '/api/import?id=' + encodeURIComponent(page.id) + (shown === 'overview' ? '&files=0' : ''));
  if (data.error) throw new Error(data.error);
  if (view() !== shown) return;
  page.data = data;
  const title = sourceName(data.source) + ' → ' + data.destName;
  document.getElementById('where').replaceChildren(' > ', shown === 'overview' ? title :
    el('a', {href: '#'}, title), shown === 'overview' ? '' : ' > ' + filterText());
  document.getElementById('labels').replaceChildren(labelChip(data.label));
  if (shown === 'overview') renderOverview(); else renderImport();
  const reading = data.reading && (data.reading.phase === 'listing' || data.reading.phase === 'copying');
  const hashing = data.replicas.some(replica => replica.reading || (replica.hashing && replica.hashing.started && replica.hashing.state !== 'done'));
  const busy = reading || hashing || (data.applying && !data.applying.done) || data.checking.busy;
  later(busy ? 2 : 10);
}

// The name of a replica of the import shown, with where it is ('eliran (Drive)'), else its dir's
function nameOf(path) {
  const found = page.data && (page.data.replicas || []).find(replica => replica.path === path);
  return found ? found.name : replicaName(path);
}

function plural(count, one, many) { return count === 1 ? one : many; }

// A replica's short name: its dir's (Drive's said so)
function replicaName(path) {
  const parts = path.split('/').filter(Boolean);
  return parts[0] === 'cloud' ? 'Drive: ' + (parts.slice(1).pop() || 'all') : parts.pop() || path;
}

// A text that's waiting for something, with dots that go on (in step across the page's redraws)
function waiting(text) {
  return el('span', {}, text, el('span', {class: 'dots', style: 'animation-delay:-' + (Date.now() % 1600) + 'ms'}));
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
  // A count, linking to its photos; none: no link, and where none is good news, a green check and goodText
  const link = (count, text, kind, replica, cls, goodText) => count ?
    el('a', {class: 'stat' + (cls ? ' ' + cls : ''), href: photosLink(kind, replica)},
      el('b', {}, count), el('span', {}, text), el('span', {class: 'go'}, '›')) :
    el('div', {class: 'stat zero' + (goodText ? ' good' : '')}, el('b', {}, goodText ? '✓' : '0'), el('span', {}, goodText || text));
  const button = (text, onclick, cls) => el('button', {class: cls || '', onclick}, text);
  const cards = [];

  const drive = data.source.drive;
  const thing = data.source.device ? 'phone' : drive ? 'Drive folder' : 'folder';
  const listing = reading && reading.phase === 'listing';
  const [tone, toneText] = !over.total ? ['red', listing ? waiting('Reading the ' + thing) : 'Not read yet'] :
    over.unhashed.files ? ['yellow', reading && reading.phase === 'copying' ? waiting('Hashing') : 'Matched by name & size'] : ['green', 'Hashed'];
  const source = el('div', {class: 'card tone-' + tone},
    el('h2', {}, data.source.device ? 'Photos on ' + data.source.device : drive ? 'Photos in the inbox “' + bareName(data.source) + '”' :
      'Photos in ' + bareName(data.source),
      el('span', {class: 'pill'}, toneText)),
    pathLine(data.source.full, data.source.device ? 'Phone · ' + data.source.inner : drive ? 'Google Drive inbox' : 'Folder'));
  if (listing && !over.total) source.append(el('p', {}, waiting('Listing its files')));
  else {
    source.append(link(over.total, plural(over.total, 'photo or video', 'photos and videos') + (listing ? ' (listing again)' : ''), 'all'));
    source.append(el('div', {class: 'stat'}, el('b', {}, over.hashed), el('span', {}, drive ? 'hashed (by Drive)' : 'hashed (copied to this computer)')),
      el('div', {class: 'meter'}, el('div', {style: 'width:' + percent(over.hashed, over.total)})));
    if (reading && reading.phase === 'copying') {
      source.append(el('p', {}, waiting((drive ? 'Downloading' : 'Copying') + ' and hashing: ' + reading.copied + ' of ' + reading.asked)));
    } else if (over.unhashed.files) {
      source.append(el('p', {class: 'note'}, (over.hashed ? 'The rest are matched by name and size only: ' : 'Matched by name and size only: ') +
        'usually right, not certain. Hashing ' + (drive ? 'downloads' : 'copies') + ' them to this computer (sorting needs that anyway) and compares their contents.'));
      const buttons = el('div', {class: 'row2'});
      if (over.nameOnly.files && over.nameOnly.files < over.unhashed.files) {
        buttons.append(button((drive ? 'Download' : 'Copy') + ' & hash the ' + over.nameOnly.files + ' matched by name (' + size(over.nameOnly.size) + ')',
          () => act('/api/import/read', {which: 'nameOnly'})));
      }
      buttons.append(button((drive ? 'Download' : 'Copy') + ' & hash all ' + over.unhashed.files + ' (' + size(over.unhashed.size) + ')',
        () => act('/api/import/read', {which: 'all'})));
      source.append(buttons);
    }
  }
  if (reading && reading.message) source.append(el('p', {class: 'c-orange'}, reading.message));
  if (!reading || reading.phase === 'done' || reading.phase === 'waiting') {
    source.append(el('div', {class: 'row2'}, el('span', {class: 'note'}, data.listedAgo !== null ? 'Listed ' + ago(data.listedAgo) : ''),
      button(data.source.device ? "List the phone's files again" : drive ? 'Read it from Drive again' : "List the folder's files again",
        () => act('/api/import/read', {which: 'list'}))));
  }
  if (data.otherDisk) {
    cards.push(el('div', {class: 'card tone-red'}, el('h2', {}, 'A different disk is mounted there now'),
      el('p', {}, 'The disk mounted at ' + data.dest + ' now (' + data.destDisk + ') isn\'t the one this import was started with. ' +
        'Nothing is moved until that disk is back; start a new import to sort into this one.')));
  }
  cards.push(source);

  // (A new one for each card: an element is in one place only)
  const checked = () => data.checking.busy ? waiting(over.checked ? 'Checking again' : 'Checking what they have') :
    'Checked ' + ago(data.checking.ago) + '.';
  for (const replica of data.replicas) {
    const counted = over.replicas.find(found => found.path === replica.path);
    const card = el('div', {class: 'card'}, el('h2', {class: 'head'}, icon(replica.kind === 'drive' ? 'drive' : 'disk'), 'Already in ' + replica.name),
      el('p', {class: 'kind'}, replica.kind === 'drive' ? 'Google Drive replica' : 'Local disk replica'),
      pathLine(replica.path));
    if (!over.checked) card.append(el('p', {}, checked()));
    else {
      card.append(el('div', {class: 'stat'}, el('b', {}, counted.have + ' of ' + over.total), el('span', {}, 'are there already')),
        el('div', {class: 'meter'}, el('div', {class: 'sure', style: 'width:' + percent(counted.contents, over.total)}),
          el('div', {class: 'unsure', style: 'width:' + percent(counted.have - counted.contents, over.total)})));
      if (counted.contents) card.append(link(counted.contents, 'the same contents (hashes match)', 'contents', replica.path, 'sure'));
      if (counted.namePhoneUnhashed) card.append(link(counted.namePhoneUnhashed, 'same name and size (not hashed here yet)', 'name', replica.path, 'unsure'));
      if (counted.nameReplicaUnhashed) card.append(link(counted.nameReplicaUnhashed, 'same name and size (its copy isn\'t hashed)', 'name', replica.path, 'unsure'));
      card.append(link(counted.missing, 'not there', 'missing', replica.path, 'missing', 'Nothing missing'));
      card.append(el('p', {class: 'note'}, checked()));
    }
    const buttons = el('div', {class: 'row2'});
    if (replica.kind === 'drive') {
      buttons.append(replica.reading ? el('span', {class: 'note'}, waiting('Reading it from Drive')) :
        button('Read it from Drive again', () => act('/api/import/recheck', {replica: replica.path, how: 'drive'})));
    } else {
      if (!data.checking.busy) buttons.append(button('Check names and sizes again', () => act('/api/import/recheck', {})));
      const job = replica.hashing;
      if (job && job.started && job.state !== 'done') {
        buttons.append(el('span', {class: 'note'}, waiting('Hashing its files: ' + job.done + ' of ' + job.files)));
      } else if (replica.unhashed) {
        buttons.append(button('Hash its ' + replica.unhashed + ' remaining files',
          () => act('/api/import/recheck', {replica: replica.path, how: 'hash'})));
      }
    }
    card.append(buttons);
    cards.push(card);
  }
  if (over.checked && over.replicas.length > 1) {
    cards.push(el('div', {class: 'card'}, el('h2', {}, 'Across all the replicas'),
      link(over.inNone, 'in no replica', 'none', '', 'missing', 'Each is in at least one replica'),
      link(over.inAll, 'in every replica', 'all-in')));
  }
  if (over.checked && over.inAll && over.inAll > over.counts.skipped + over.counts.moved) {
    cards.push(el('div', {class: 'card tone-green'}, el('h2', {}, over.inAll === over.total ? 'Nothing new to sort' : 'Some are there already'),
      el('p', {class: 'note'}, over.inAll === over.total ? 'Every file is in every replica already.' :
        over.inAll + ' of the ' + over.total + ' are in every replica already.'),
      el('div', {class: 'row2'}, button('Skip the ' + over.inAll + ' in every replica', skipInAll))));
  }
  for (const error of data.errors) cards.push(el('p', {class: 'c-red'}, error));

  const counts = over.counts;
  const open = over.total - counts.moved - counts.skipped - over.chosen;
  const end = el('button', {class: 'danger', onclick: async () => {
    if (!end.classList.contains('sure')) {
      end.classList.add('sure');
      end.textContent = 'Yes, end it';
      return;
    }
    const answer = await api('POST', '/api/import/end', {id: page.id});
    if (answer.ok) location.href = '/import'; else document.getElementById('status').textContent = answer.error || "Couldn't end it.";
  }}, 'End this import');
  cards.push(el('div', {class: 'card'}, el('h2', {}, 'Sorting the photos into ' + data.destName),
    link(open, 'with no folder yet', 'open', '', '', 'All decided'), link(over.chosen, 'with a folder chosen, to move', 'chosen'),
    counts.moved ? link(counts.moved, 'moved', 'moved') : '', counts.skipped ? link(counts.skipped, 'skipped', 'skipped') : '',
    el('div', {class: 'row2'}, el('a', {class: 'button primary', href: photosLink(over.checked && over.inNone ? 'none' : 'open')},
      over.checked && over.inNone ? 'Sort the ' + over.inNone + ' not in any replica' : 'Sort them'),
      el('a', {class: 'button', href: photosLink('all')}, 'See all'))));
  if (data.applying) cards.push(el('div', {class: 'lines'}, data.applying.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text))));
  cards.push(el('div', {class: 'card quiet'}, el('h2', {}, 'Done with this import?'),
    el('p', {class: 'note'}, 'Ending it forgets the folders chosen here, and deletes its copies on this computer (unless another import ' +
      'uses them). Nothing on the ' + (data.source.device ? 'phone' : drive ? 'Drive inbox' : 'folder') +
      ' or in your replicas is touched; files already moved stay where they are.'), el('div', {class: 'row2'}, end)));
  if (!document.querySelector('#main button.sure')) document.getElementById('main').replaceChildren(...cards);
  renderFooter();
}

// Where the replicas have the file, in short: each folder (or path, if the name there is another) once,
// after the replicas it's in, and '≈' where it's by name and size only (not hashes)
function have(file) {
  const name = file.rel.split('/').pop();
  const where = new Map();
  for (const found of file.have || []) {
    const there = found.relpath.split('/').pop() === name ? (found.relpath.split('/').slice(0, -1).join('/') || '(top)') : found.relpath;
    if (!where.has(there)) where.set(there, []);
    where.get(there).push(nameOf(found.replica) + (found.how === 'contents' ? '' : ' ≈'));
  }
  return [...where].map(([there, replicas]) => replicas.join(', ') + ' · ' + there);
}

// The filters: [kind, its text (of a replica's name), whether a file passes it]
const FILTERS = {
  'all': ['All', () => true],
  'open': ['No folder yet', file => file.state !== 'moved' && file.state !== 'skipped' && !file.target],
  'chosen': ['Folder chosen', file => !!file.target && file.state !== 'moved' && file.state !== 'skipped'],
  'moved': ['Moved', file => file.state === 'moved'],
  'skipped': ['Skipped', file => file.state === 'skipped'],
  'unhashed': ['Not hashed', file => !file.sha1],
  'have': ['Already in a replica', file => (file.have || []).length > 0],
  'none': ['In no replica', file => file.have !== null && !file.have.length],
  'all-in': ['In every replica', file => new Set((file.have || []).map(found => found.replica)).size === page.data.checked.length],
  'in': [name => 'In ' + name, (file, replica) => haveIn(file, replica).length > 0],
  'contents': [name => 'In ' + name + ' (hashes match)', (file, replica) => haveIn(file, replica).some(found => found.how === 'contents')],
  'name': [name => 'In ' + name + ' (name & size)', (file, replica) => haveIn(file, replica).length > 0 && !haveIn(file, replica).some(found => found.how === 'contents')],
  'missing': [name => 'Not in ' + name, (file, replica) => file.have !== null && !haveIn(file, replica).length],
};

function haveIn(file, replica) { return (file.have || []).filter(found => found.replica === replica); }

function filterText() {
  const [text] = FILTERS[page.filter.kind] || FILTERS.all;
  return typeof text === 'function' ? text(nameOf(page.filter.replica)) : text;
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
  if (!data.indexed || data.errors.length) {
    parts.push(el('div', {class: 'note'}, data.indexed ? '' : waiting('Checking what the replicas have'), data.errors.join('; ')));
  }
  const meter = sortMeter();
  if (!focused) {
    // What's done with the photos selected (a folder for them, or skipping them), once there are any
    const chosen = page.selected.size ? el('div', {class: 'bar'}, el('b', {}, page.selected.size + ' selected'),
      el('input', {type: 'text', id: 'target', list: 'folders', placeholder: 'Folder in ' + data.destName + '…',
        value: page.target, oninput: event => { page.target = event.target.value; }}),
      el('datalist', {id: 'folders'}, data.folders.map(dir => el('option', {value: dir}))),
      el('button', {class: 'primary', onclick: () => assign([...page.selected], page.target)}, 'Put them in this folder'),
      el('button', {onclick: () => assign([...page.selected], null, true)}, 'Skip them'),
      el('button', {onclick: () => { page.selected.clear(); renderImport(); }}, 'Clear')) :
      el('div', {class: 'note'}, 'Tap photos to select them, or use a day\'s buttons.');
    parts.push(el('div', {class: 'sticky'}, meter, chosen));
    const filters = ['all', 'open', 'none', 'have', 'chosen'];
    if (!filters.includes(page.filter.kind)) filters.unshift(page.filter.kind);
    parts.push(el('div', {class: 'chips scroll'}, el('a', {class: 'button', href: '#'}, '‹ Overview'),
      filters.map(key => el('a', {class: 'button' + (page.filter.kind === key ? ' on' : ''),
        href: key === page.filter.kind ? location.hash : photosLink(key)}, key === page.filter.kind ? filterText() : FILTERS[key][0]))));
  } else {
    const sticky = document.querySelector('.sticky');
    sticky.firstChild.replaceWith(meter);
    parts.push(sticky, document.querySelector('.chips'));
  }
  for (const day of data.days) {
    const files = day.files.filter(passes);
    if (!files.length) continue;
    const undecided = files.filter(isUndecided).length;
    const open = day.files.filter(file => file.state !== 'moved').map(file => file.rel);
    const header = el('h2', {}, day.day === 'None' ? 'No date' : day.day, el('small', {}, day.files.length + ' ' + plural(day.files.length, 'file', 'files')),
      el('button', {onclick: () => { open.forEach(rel => page.selected.add(rel)); renderImport(); }}, 'Select the day'),
      day.suggested.map(dir => el('button', {onclick: () => assign(open, dir)}, 'All to ' + dir)),
      open.length && day.files.every(file => file.state === 'moved' || (file.have || []).length) ?
        el('button', {onclick: () => assign(open, null, true)}, 'Skip the day: all there already') : '');
    parts.push(el('div', {class: 'day', 'data-day': day.day === 'None' ? 'No date' : day.day, 'data-undecided': undecided},
      header, el('div', {class: 'grid'}, files.map(photo))));
  }
  if (data.days.length && !data.days.some(day => day.files.some(passes))) parts.push(el('p', {class: 'note'}, 'None.'));
  if (!data.days.length) parts.push(el('p', {class: 'note'}, data.reading && data.reading.phase === 'listing' ? waiting('Listing the files') : 'No media files.'));
  if (data.applying) parts.push(el('div', {class: 'lines'}, data.applying.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, text))));
  main.replaceChildren(...parts);
  renderFooter();
  fitHeader();
  showPosition();
}

function isUndecided(file) { return file.state !== 'moved' && file.state !== 'skipped' && !file.target; }

// How far the sorting is: the files decided (a folder chosen, skipped or moved) of all, a bar, where the
// page is (which day of the ones shown), and a jump to the next day with files left to decide
function sortMeter() {
  const files = page.data.days.flatMap(day => day.files);
  const decided = files.filter(file => !isUndecided(file)).length;
  const share = files.length ? Math.floor(100 * decided / files.length) : 0;
  return el('div', {class: 'sortmeter'},
    el('div', {class: 'big'}, el('b', {}, share + '%'), el('span', {}, decided + ' of ' + files.length + ' decided'),
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

// The footer: how far the sorting is, in plain words, and Move once any file has a folder chosen
function renderFooter() {
  const data = page.data, over = data.overview;
  const status = [over.counts.moved + over.counts.skipped + ' of ' + over.total + ' sorted'];
  if (over.chosen) status.push(over.chosen + ' with a folder, to move');
  if (over.checked && over.inNone !== null) status.push((over.total - over.inNone) + ' already in a replica');
  if (page.selected.size) status.push(page.selected.size + ' selected');
  document.getElementById('status').textContent = status.join(' · ');
  const busy = data.applying && !data.applying.done;
  document.getElementById('actions').replaceChildren(over.chosen ? el('button', {class: 'primary', disabled: busy,
    onclick: () => api('POST', '/api/import/apply', {id: page.id}).then(answer => {
      if (answer.error) document.getElementById('status').textContent = answer.error;
      return loadImport();
    })}, busy ? waiting('Moving') : 'Move ' + over.chosen + ' into ' + data.destName) : '');
}

tabBar('inboxes');
document.title = 'Inboxes';
load();
