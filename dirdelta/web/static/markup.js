// treepicker's text markup, as dirdelta sends it (ui/picker/styles.py): segments() (\x01COLOR\x01TEXT,
// a status's or label's colored parts) and styled() (\x02STYLE\x02TEXT: a color, grey, orange and/or
// bold), made into spans. Text goes in as textContent, never as HTML.
'use strict';

const COLORS = ['red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'grey', 'orange', 'white'];

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (name === 'class') node.className = value;
    else if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
    else if (value !== undefined && value !== null && value !== false) node.setAttribute(name, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

// [{text, style}] of a styled() text (no marks: one plain part)
function styledParts(text) {
  if (!text.includes('\x02')) return [{text, style: ''}];
  const parts = [];
  const pieces = text.split('\x02');
  if (pieces[0]) parts.push({text: pieces[0], style: ''});
  for (let i = 1; i + 1 < pieces.length; i += 2) {
    if (pieces[i + 1]) parts.push({text: pieces[i + 1], style: pieces[i]});
  }
  return parts;
}

// A span of a styled() text (each part in its color and/or bold)
function styledSpan(text) {
  const span = el('span');
  for (const {text: part, style} of styledParts(text || '')) {
    const classes = (style || '').split(',').filter(Boolean)
      .map(name => COLORS.includes(name) ? 'c-' + name : name === 'bold' ? 'bold' : '');
    span.append(classes.length ? el('span', {class: classes.join(' ')}, part) : document.createTextNode(part));
  }
  return span;
}

// A span of a segments() text: each part in its color (as a label's text color)
function segmentsSpan(text) {
  if (!text || !text.includes('\x01')) return styledSpan(text || '');
  const span = el('span');
  const pieces = text.split('\x01');
  if (pieces[0]) span.append(styledSpan(pieces[0]));
  for (let i = 1; i + 1 < pieces.length; i += 2) {
    const color = pieces[i];
    span.append(el('span', {class: 'seg' + (COLORS.includes(color) ? ' c-' + color : '')}, styledSpan(pieces[i + 1])));
  }
  return span;
}

// A preview's line: highlighted (\x01COLOR\x01 at its start: bold on the color, across the column), or styled
function previewLine(line) {
  const match = /^\x01([a-z]*)\x01([^\x01]*)$/.exec(line);
  if (match) return el('span', {class: 'highlight b-' + (COLORS.includes(match[1]) ? match[1] : 'grey')}, match[2]);
  return segmentsSpan(line);
}

// A canvas of a preview's picture: 'W H' and its pixels (RGB) in hex
function pictureCanvas(encoded) {
  const [width, height, hex] = encoded.split(' ');
  const w = parseInt(width, 10), h = parseInt(height, 10);
  if (!w || !h || !hex || hex.length < w * h * 6) return null;
  const canvas = el('canvas', {width: w, height: h});
  const context = canvas.getContext('2d');
  const image = context.createImageData(w, h);
  for (let i = 0, j = 0; i < w * h; i++, j += 6) {
    image.data[i * 4] = parseInt(hex.substr(j, 2), 16);
    image.data[i * 4 + 1] = parseInt(hex.substr(j + 2, 2), 16);
    image.data[i * 4 + 2] = parseInt(hex.substr(j + 4, 2), 16);
    image.data[i * 4 + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  canvas.style.width = Math.min(w * 2, 480) + 'px';
  return canvas;
}

// What the mode labels mean, said when one is tapped
const LABEL_NOTES = {
  'DRY RUN': 'Dry run: every button only says what it would do. No file is copied, moved or removed.',
  'LIVE': 'Live: buttons really copy, move and remove files.',
};

function labelChip([text, color]) {
  const chipped = el('span', {class: 'label b-' + (COLORS.includes(color) ? color : 'grey'), title: LABEL_NOTES[text] || ''}, text);
  if (LABEL_NOTES[text]) {
    chipped.classList.add('tappable');
    chipped.addEventListener('click', () => {
      const header = document.getElementById('top');
      const shown = document.getElementById('modenote');
      if (shown) shown.remove();
      else header.append(el('div', {id: 'modenote', class: 'modenote c-' + color}, LABEL_NOTES[text]));
    });
  }
  return chipped;
}

// A path, shortened to its last parts, the whole shown on a tap (and hidden on the next)
function pathLine(full, before) {
  const parts = full.split('/').filter(Boolean);
  const short = parts.length > 2 ? '…/' + parts.slice(-2).join('/') : full;
  const shown = el('button', {class: 'pathbutton', title: full, onclick: event => {
    event.preventDefault();
    shown.textContent = shown.textContent === full ? short : full;
  }}, short);
  return el('div', {class: 'where'}, before ? el('span', {}, before) : '', shown);
}

// The pages' tabs, the one shown marked (active: 'home', 'replicas', 'inboxes', 'run'): what the user
// has, at a glance; their replicas (synced); their inboxes (sorted into them). A flow running (a sync, a
// sort, the start menu: its screens are on /run) is checked every few seconds: a dot on its tab, and
// "Running" in the top bar leading to it.
const TABS = [['home', '/', 'Home'], ['replicas', '/replicas', 'Replicas'], ['inboxes', '/inboxes', 'Inboxes']];

// (Called again, it marks another tab: a page may know which only once it's loaded)
let shownTab = null, isRunning = false, runningFor = null, runningTab = 'replicas';

function tabBar(active) {
  const nav = document.getElementById('tabs');
  if (!nav) return;
  const isFirst = shownTab === null;
  shownTab = active;
  if (!isFirst) return drawTabs(nav);
  drawTabs(nav);
  userBar();
  const check = async () => {
    try {
      const found = await (await fetch('/api/running')).json();
      isRunning = found.running;
      runningFor = found.user;
      runningTab = found.tab || 'replicas';
      drawTabs(nav);
    } catch (error) { /* (the next check) */ }
    setTimeout(check, 5000);
  };
  check();
}

function drawTabs(nav) {
  const active = shownTab === 'run' ? runningTab : shownTab, running = isRunning;
  // (What's running is under its tab (a sync Replicas', a sort Inboxes'): a dot on it then; the top bar
  // leads to it)
  const tab = ([key, href, text]) => el('a', {href, class: 'tab' + (key === active ? ' on' : '')},
    running && key === runningTab ? el('span', {class: 'dot', title: 'Running now'}) : '', text);
  nav.replaceChildren(...TABS.map(tab));
  const pill = document.getElementById('runningpill');
  if (pill) {
    pill.hidden = !running || shownTab === 'run';
    pill.title = runningFor ? 'Running for ' + runningFor : 'Running';
  }
}

// The top bar: whose dirdelta this is (each user's replicas, pairs, sorts and imports are their own),
// a menu to change to another user, add one, or set where links are emailed to them
async function userBar() {
  const header = document.getElementById('top');
  if (!header || document.getElementById('userbar')) return;
  const bar = el('div', {id: 'userbar'});
  const form = el('div', {id: 'userform'});
  header.prepend(bar, form);
  let found;
  try {
    found = await (await fetch('/api/users')).json();
  } catch (error) { return; }
  const pick = el('select', {id: 'userpick', 'aria-label': 'User', onchange: () => {
    const value = pick.value;
    pick.value = found.current;
    if (value === '+add') return showForm('add');
    if (value === '+email') return showForm('email');
    if (value.startsWith('+layout:')) {
      setLayout(value.slice('+layout:'.length));
      return void location.reload();
    }
    document.cookie = 'dirdelta_user=' + encodeURIComponent(value) + '; Path=/; Max-Age=2592000; SameSite=Strict';
    // (To the tab's own page: an import's page is the last user's)
    location.href = location.pathname;
  }},
    el('optgroup', {label: 'Change user'}, found.users.map(name => el('option', {value: name, selected: name === found.current}, name))),
    el('optgroup', {label: found.current},
      el('option', {value: '+email'}, found.email ? 'Email for links…' : 'Set the email for links…'),
      el('option', {value: '+add'}, 'Add a user…')),
    el('optgroup', {label: 'Layout'}, Object.entries(LAYOUTS).map(([key, text]) =>
      el('option', {value: '+layout:' + key}, (key === layout() ? '✓ ' : '') + text))));
  // (The mode's label, DRY RUN or LIVE, in this bar: the page's title is its tab's, so no row of its own)
  bar.replaceChildren(el('span', {class: 'brand'}, 'dirdelta'), document.getElementById('labels') || '',
    el('a', {id: 'runningpill', href: '/run', hidden: !isRunning || shownTab === 'run'}, el('span', {class: 'dot'}), 'Running'),
    el('label', {class: 'userpick'}, icon('person'), el('span', {class: 'whose'}, 'Replicas of'), pick));

  function showForm(kind) {
    const input = el('input', {type: kind === 'add' ? 'text' : 'email', placeholder: kind === 'add' ? "The new user's name, e.g. hagit" : 'name@example.com',
      value: kind === 'email' ? (found.email || '') : '', autocomplete: 'off'});
    const note = el('span', {class: 'note'});
    const submit = async event => {
      event.preventDefault();
      const answer = await (await fetch(kind === 'add' ? '/api/users/add' : '/api/users/email', {method: 'POST',
        body: JSON.stringify(kind === 'add' ? {name: input.value} : {address: input.value})})).json();
      if (!answer.ok) return note.replaceChildren(answer.error);
      if (kind === 'add') document.cookie = 'dirdelta_user=' + encodeURIComponent(answer.name) + '; Path=/; Max-Age=2592000; SameSite=Strict';
      location.href = location.pathname;
    };
    form.replaceChildren(el('form', {onsubmit: submit},
      el('span', {class: 'formtitle'}, kind === 'add' ? 'Add a user, with replicas of their own:' : 'Email links for ' + found.current + ' to:'),
      input, el('button', {type: 'submit', class: 'primary'}, kind === 'add' ? 'Add and switch to them' : 'Save'),
      el('button', {type: 'button', onclick: () => form.replaceChildren()}, 'Cancel'), note));
    input.focus();
  }
}

// Adding a replica or an inbox (as: 'replica' or 'inbox'): its folder browsed on this computer or in
// Google Drive. One element for each page, kept across its redraws (so what's browsed stays); open at
// once on a link to #add.
const adders = {};

function folderAdder(as) {
  if (adders[as]) return adders[as];
  const box = el('div', {class: 'pairadder'});
  const what = as === 'inbox' ? 'an inbox' : 'a replica';
  let browsing = null, isOpen = location.hash === '#add', note = '';

  async function go(path) {
    browsing = {path, loading: true};
    draw();
    const found = await (await fetch('/api/browse?path=' + encodeURIComponent(path || ''))).json();
    if (browsing) browsing = Object.assign({path}, found);
    draw();
  }

  async function add(path) {
    const answer = await (await fetch('/api/add', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path, as})})).json();
    if (!answer.ok) { note = answer.error; return draw(); }
    location.href = location.pathname;
  }

  function browser() {
    const b = browsing;
    if (b.loading) return el('div', {class: 'browser'}, el('p', {class: 'note'}, 'Reading', el('span', {class: 'dots'})));
    if (b.shortcuts) {
      return el('div', {class: 'browser'}, el('div', {class: 'note'}, 'Start from:'),
        el('div', {class: 'dirs'}, b.shortcuts.map(place => el('button', {class: 'dir', onclick: () => go(place.path)},
          icon(place.path.startsWith('/mnt') || place.path.startsWith('/media') ? 'disk' : 'laptop'), place.name)),
          el('button', {class: 'dir', onclick: () => go('/')}, icon('folder'), '/ (everything)')));
    }
    const rows = [];
    if (b.parent !== null && b.parent !== undefined) rows.push(el('button', {class: 'dir up', onclick: () => go(b.parent)}, '↑ Up'));
    for (const name of b.dirs || []) {
      rows.push(el('button', {class: 'dir', onclick: () => go(b.path === '/' ? '/' + name : b.path + '/' + name)}, icon('folder'), name));
    }
    if (b.dirs && !b.dirs.length) rows.push(el('div', {class: 'note'}, 'No folders in it.'));
    const isRoot = b.path === '/' || b.path === 'cloud';
    return el('div', {class: 'browser'},
      el('div', {class: 'browsing'}, icon(b.path.startsWith('cloud') ? 'drive' : 'folder'), el('b', {}, b.path === 'cloud' ? 'Google Drive' : b.path),
        b.known ? chip('ok', 'Already yours') : ''),
      b.error ? el('div', {class: 'note bad'}, b.error) : '',
      el('div', {class: 'dirs'}, rows),
      note ? el('div', {class: 'note bad'}, note) : '',
      el('div', {class: 'row2'}, el('button', {class: 'primary', disabled: isRoot || !!b.error || b.known, onclick: () => add(b.path)},
        isRoot ? 'Open a folder to choose it' : as === 'inbox' ? 'Add this unsorted folder' : 'Add this folder as ' + what),
        el('button', {onclick: () => { browsing = null; note = ''; draw(); }}, 'Back')));
  }

  function draw() {
    if (!isOpen) {
      box.replaceChildren(el('button', {class: 'addbutton', onclick: () => { isOpen = true; draw(); }}, '+ Add ' + (as === 'inbox' ? 'an unsorted folder' : what)));
      return;
    }
    box.replaceChildren(el('div', {class: 'card'},
      el('div', {class: 'section-title'}, 'Add ' + (as === 'inbox' ? 'an unsorted folder' : what)),
      el('p', {class: 'note'}, as === 'inbox' ?
        'A folder new files come into, to be sorted into your replicas: e.g. unsorted in Google Drive. (A phone needs no adding: it\'s here while it\'s plugged in.)' :
        'A copy of your files: a folder on this computer, on a disk, or in Google Drive.'),
      browsing ? browser() : el('div', {class: 'row2'},
        el('button', {onclick: () => go('')}, icon('laptop'), 'On this computer'),
        el('button', {onclick: () => go('cloud')}, icon('drive'), 'In Google Drive'),
        el('button', {onclick: () => { isOpen = false; draw(); }}, 'Cancel'))));
  }

  draw();
  adders[as] = box;
  return box;
}

// Forget a replica or inbox (what: 'replica' or 'inbox'): not the user's any more, nothing in it changed.
// Asked again on the button itself (no dialog).
function forgetButton(path, what) {
  const box = el('span', {class: 'forget'});
  const ask = () => box.replaceChildren(el('span', {class: 'note'}, 'Forget this ' + what + '? Nothing in it is changed.'),
    el('button', {class: 'small danger', onclick: async () => {
      await fetch('/api/forget', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path})});
      location.href = location.pathname;
    }}, 'Forget'), el('button', {class: 'small', onclick: idle}, 'Keep'));
  const idle = () => box.replaceChildren(el('button', {class: 'small quiet', onclick: ask}, 'Forget…'));
  idle();
  return box;
}

// A progress bar, share (0-100) filled (in tone's color: '' blue, 'sure' green), with the share beside it
function bar(share, tone = '') {
  const shown = Math.max(0, Math.min(100, Math.floor(share || 0)));
  return el('div', {class: 'bar'}, el('div', {class: 'meter'}, el('div', {class: tone, style: 'width:' + shown + '%'})), el('b', {}, shown + '%'));
}

// How many inboxes of a kind are there now, out of how many the user has (a phone: plugged in, of the
// ones known: plugged in, or with an import): 'N out of M'
function thereOutOf(inboxes) {
  return inboxes.filter(inbox => inbox.there).length + ' out of ' + inboxes.length;
}

// An import's files: {sorted (moved or skipped), there (not sorted, but a replica has them already, as last
// checked: sure, by contents; byName, by name and size only), left (neither), total}
function importTally(found) {
  const counts = found.counts, already = found.already || {contents: 0, name: 0};
  const there = already.contents + already.name;
  return {sorted: counts.moved + counts.skipped, there, sure: already.contents, byName: already.name,
    left: counts.pending + counts.copied - there, total: counts.pending + counts.copied + counts.moved + counts.skipped};
}

// The tallies of imports added up
function tallies(imports) {
  const sum = {sorted: 0, there: 0, sure: 0, byName: 0, left: 0, total: 0};
  for (const found of imports) {
    const tally = importTally(found);
    for (const key in sum) sum[key] += tally[key];
  }
  return sum;
}

// How far an inbox's sorting is: {text, share (0-100: sorted or in a replica already; null if nothing's
// started)}, with when the replicas were last checked
function inboxProgress(inbox) {
  if (!inbox.imports.length) return {text: inbox.there ? 'Not sorted yet' : 'Not plugged in', share: null};
  const sum = tallies(inbox.imports);
  if (!sum.total) return {text: 'Listing its files', share: 0};
  const done = sum.sorted + sum.there, share = Math.floor(100 * done / sum.total);
  const parts = [];
  if (sum.sorted) parts.push(sum.sorted.toLocaleString() + ' sorted');
  if (sum.there) parts.push(sum.there.toLocaleString() + ' in a replica already' + (sum.byName ? ' (' + sum.byName.toLocaleString() + ' by name and size only)' : ''));
  parts.push(sum.left ? sum.left.toLocaleString() + ' left to sort' : 'none left to sort');
  const checked = inbox.imports.map(found => found.already && found.already.checked).filter(Boolean).sort()[0];
  return {text: parts.join(' · ') + ' (of ' + sum.total.toLocaleString() + ')', share,
    checked: checked ? 'Replicas checked ' + age(checked).text : 'Replicas not checked yet'};
}

// How a tab's parts are laid out (this browser's choice, kept in its storage): 'tabs' (the default), a row of
// sub-tabs on top, one part shown at a time; or 'blocks', all of them one after another with a jump to each on top
const LAYOUTS = {tabs: 'Parts as sub-tabs', blocks: 'Parts one after another'};

function layout() {
  try {
    const kept = localStorage.getItem('dirdelta_layout');
    return kept in LAYOUTS ? kept : 'tabs';
  } catch (error) {
    return 'tabs';
  }
}

function setLayout(key) {
  try { localStorage.setItem('dirdelta_layout', key); } catch (error) { /* (the default, then) */ }
}

// The part shown of each page's, as sub-tabs: {page: id}, chosen once (from the link's #, e.g. Home's to
// #phones; aliases: {'#': id}), then by a tap on its sub-tab (and kept in the address, for reloading)
const shownPart = {};

// A tab's parts ([{jump: kindJump(), block: kindBlock()}]), laid out as layout() says
function kindParts(parts, aliases = {}) {
  const jumps = parts.map(part => part.jump), blocks = parts.map(part => part.block);
  if (layout() !== 'tabs') return [el('div', {class: 'kindjumps'}, jumps), ...blocks];
  const ids = blocks.map(block => block.id), page = location.pathname;
  if (!ids.includes(shownPart[page])) {
    const hash = location.hash.slice(1);
    shownPart[page] = ids.includes(aliases[hash] || hash) ? aliases[hash] || hash : ids[0];
  }
  const show = id => {
    shownPart[page] = id;
    history.replaceState(null, '', '#' + id);
    jumps.forEach((jump, index) => jump.classList.toggle('on', ids[index] === id));
    blocks.forEach(block => { block.hidden = block.id !== id; });
    // (The row draws the shown part's top edge, in its color: the tab shown covers it, joined to the part)
    row.className = 'kindtabs kind-' + id;
  };
  jumps.forEach((jump, index) => {
    jump.onclick = event => { event.preventDefault(); show(ids[index]); };
    jump.setAttribute('role', 'tab');
  });
  const row = el('div', {class: 'kindtabs', role: 'tablist'}, jumps);
  const shown = [el('div', {class: 'kindtabbed'}, row, ...blocks)];
  show(shownPart[page]);
  return shown;
}

// A tab's part, a block of its own in its color (.kind-ID), and a jump to it for the top of the tab
// (tone: its status dot's, 'ok' green, 'warn' yellow, 'bad' red; none if not given)
function kindJump(id, iconName, title, note, tone) {
  return el('a', {class: 'kindjump kind-' + id, href: '#' + id, onclick: event => {
    event.preventDefault();
    document.getElementById(id).scrollIntoView({behavior: 'smooth'});
  }}, icon(iconName), el('span', {class: 'jumptext'}, el('span', {}, title), el('span', {class: 'note'}, note)),
    tone ? el('span', {class: 'status ' + tone, title: STATUS_WORDS[tone]}) : '');
}

const STATUS_WORDS = {ok: 'All good', warn: 'Something to do', bad: 'Needs attention'};

// An inbox kind's status: green, all sorted (or in a replica already); yellow, files left to sort; red, none there and nothing
// to sort
function inboxesTone(inboxes) {
  const left = tallies(inboxes.flatMap(inbox => inbox.imports)).left;
  return left ? 'warn' : inboxes.some(inbox => inbox.there || inbox.imports.length) ? 'ok' : 'bad';
}

function kindBlock(id, iconName, title, text, ...children) {
  return el('section', {class: 'kind kind-' + id, id},
    el('div', {class: 'kindhead'}, icon(iconName), el('div', {}, el('h2', {}, title), el('p', {}, text))), ...children);
}

// Small icons of what a replica or source is on (static SVG, drawn in the text's color)
const ICONS = {
  laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
  disk: '<rect x="3" y="7" width="18" height="10" rx="2"/><circle cx="17" cy="12" r="1.2"/><path d="M6 12h6"/>',
  drive: '<path d="M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 9.2 4.5 4.5 0 0 0 7 18z"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2"/><path d="M11 18.5h2"/>',
  inbox: '<path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 2h6l1-2h5"/>',
  folder: '<path d="M3 6.5h6l2 2h10v10.5H3z"/>',
  replicas: '<rect x="3" y="8" width="13" height="12" rx="1.5"/><path d="M8 5h11.5a1.5 1.5 0 0 1 1.5 1.5V16"/>',
  sync: '<path d="M4 10a8 8 0 0 1 14-4l2 2"/><path d="M20 4v4h-4"/><path d="M20 14a8 8 0 0 1-14 4l-2-2"/><path d="M4 20v-4h4"/>',
  hash: '<path d="M9 4L7 20M17 4l-2 16M4 9h16M3 15h16"/>',
  equal: '<circle cx="12" cy="12" r="9"/><path d="M8 10h8M8 14h8"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  person: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
};

function icon(name) {
  const span = document.createElement('span');
  span.className = 'icon';
  span.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || ICONS.folder) + '</svg>';
  return span;
}

// How old a time ('YYYY-MM-DD HH:MM') is, in words, and its tone, the same scale everywhere: within a
// day fresh (green), within a week oldish (yellow), older old (red)
function age(when, freshDays = 2, oldDays = 30) {
  if (!when) return {text: 'never', tone: 'none'};
  const then = new Date(when.replace(' ', 'T'));
  const hours = (Date.now() - then) / 3600000;
  const days = Math.floor(hours / 24);
  const text = hours < 1 ? 'just now' : hours < 24 ? Math.floor(hours) + ' h ago' : days === 1 ? 'yesterday' : days + ' days ago';
  return {text, tone: hours < freshDays * 24 ? 'ok' : hours < oldDays * 24 ? 'warn' : 'bad'};
}

// A small status chip: a dot of its tone (ok, warn, bad, none) and its text
function chip(tone, text) {
  return el('span', {class: 'chip ' + tone}, el('span', {class: 'dot'}), text);
}

// A replica's name after its icon: Drive's (its 'cloud/' then left out) or a disk's
function replicaLabel(path, name, isInbox) {
  const isDrive = path.startsWith('cloud/') || path === 'cloud';
  return el('span', {class: 'rname'}, icon(isInbox ? 'inbox' : isDrive ? 'drive' : 'disk'), name);
}
