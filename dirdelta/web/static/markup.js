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

// The pages' tabs, the one shown marked (active: 'home', 'replicas', 'sync', 'photos', 'unsorted',
// 'run'): the two kinds of inbox (a phone's photos, an unsorted folder's) together under 'Inboxes'; and
// Running while a flow runs (a sync, a sort, the start menu: its screens are on /run), checked every few
// seconds. They share the screen's width, a long name on two lines.
const TABS = [['home', '/', 'Home'], ['replicas', '/replicas', 'Replicas'], ['sync', '/sync', 'Sync']];
const INBOX_TABS = [['photos', '/import', 'Photos import'], ['unsorted', '/unsorted', 'Unsorted import']];

// (Called again, it marks another tab: a page may know which only once it's loaded)
let shownTab = null, isRunning = false, runningFor = null;

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
      drawTabs(nav);
    } catch (error) { /* (the next check) */ }
    setTimeout(check, 5000);
  };
  check();
}

function drawTabs(nav) {
  const active = shownTab, running = isRunning;
  // (What's running is part of Sync: its tab has a dot then, and the running flow's page is under it)
  const tab = ([key, href, text]) => el('a', {href: key === 'sync' && running ? '/run' : href,
    class: 'tab' + (key === active || (key === 'sync' && active === 'run') ? ' on' : '')},
    key === 'sync' && running ? el('span', {class: 'dot', title: 'Running now' + (runningFor ? ' (for ' + runningFor + ')' : '')}) : '', text);
  nav.replaceChildren(...TABS.map(tab),
    el('div', {class: 'tabgroup'}, el('span', {class: 'grouplabel'}, 'Inboxes'), el('div', {class: 'grouptabs'}, INBOX_TABS.map(tab))));
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
    document.cookie = 'dirdelta_user=' + encodeURIComponent(value) + '; Path=/; Max-Age=2592000; SameSite=Strict';
    // (To the tab's own page: an import's page is the last user's)
    location.href = location.pathname;
  }},
    el('optgroup', {label: 'Change user'}, found.users.map(name => el('option', {value: name, selected: name === found.current}, name))),
    el('optgroup', {label: found.current},
      el('option', {value: '+email'}, found.email ? 'Email for links…' : 'Set the email for links…'),
      el('option', {value: '+add'}, 'Add a user…')));
  bar.replaceChildren(el('span', {class: 'brand'}, 'dirdelta'),
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

// Small icons of what a replica or source is on (static SVG, drawn in the text's color)
const ICONS = {
  laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
  disk: '<rect x="3" y="7" width="18" height="10" rx="2"/><circle cx="17" cy="12" r="1.2"/><path d="M6 12h6"/>',
  drive: '<path d="M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 9.2 4.5 4.5 0 0 0 7 18z"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2"/><path d="M11 18.5h2"/>',
  inbox: '<path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 2h6l1-2h5"/>',
  folder: '<path d="M3 6.5h6l2 2h10v10.5H3z"/>',
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
function age(when, freshDays = 1, oldDays = 7) {
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
