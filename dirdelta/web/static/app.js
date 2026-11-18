// dirdelta's web version: what its session shows now (web/session.py), drawn here and acted on.
// A picker is treepicker's (a menu, a tree of files, or a dir), done here: the server keeps its
// selection, picks and states, and says each change; a messages screen is ui/messages.py's.
'use strict';

const MAX_ROWS = 1500;
const view = {
  version: 0, screen: null, items: [], info: new Map(), children: new Map(), fileCounts: new Map(),
  picked: new Set(), selected: null, sideSelected: null, status: '', previewVersion: -1,
  expanded: new Set(['.']), search: '', tab: 0, showHelp: false, lazy: new Map(), running: false, log: [],
};

async function api(method, path, body) {
  const response = await fetch(path, method === 'GET' ? {} : {
    method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  if (response.status === 403) throw new Error('forbidden');
  return response.json();
}

function act(action, extra) {
  return api('POST', '/api/act', Object.assign({screen: view.screen && view.screen.id, action}, extra || {}));
}

// Polling: what changed since the last version seen

async function poll() {
  for (;;) {
    try {
      const data = await api('GET', '/api/state?since=' + view.version + '&screen=' + (view.screen ? view.screen.id : ''));
      apply(data);
    } catch (error) {
      if (error.message === 'forbidden') {
        document.getElementById('main').replaceChildren(el('p', {}, 'This page needs its link, with its key.'));
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }
}

function apply(data) {
  view.version = data.version;
  view.running = data.running;
  view.log = data.log;
  const screen = data.screen;
  if (!screen) {
    if (view.screen !== null || !document.querySelector('.home')) { view.screen = null; renderHome(); }
    else renderHome();
    return;
  }
  const isNew = !view.screen || view.screen.id !== screen.id;
  if (isNew) newScreen(screen);
  if (screen.kind === 'picker') updatePicker(screen, isNew);
  else renderMessages(screen, isNew);
}

function newScreen(screen) {
  Object.assign(view, {screen, items: [], info: new Map(), children: new Map(), fileCounts: new Map(),
    picked: new Set(), search: '', tab: 0, showHelp: false, previewVersion: -1, lazy: new Map(),
    expanded: new Set(['.'])});
  if (screen.items) setItems(screen.items);
  if (screen.mode === 'dir') loadChildren('.');
}

function setItems(items) {
  view.items = items.map(item => item.p);
  for (const item of items) view.info.set(item.p, item);
  view.children = new Map([['.', []]]);
  for (const path of view.items) {
    const parent = parentOf(path);
    if (!view.children.has(parent)) view.children.set(parent, []);
    view.children.get(parent).push(path);
  }
  view.fileCounts = new Map();
  for (const path of view.items) {
    if (view.info.get(path).t !== 'f') continue;
    for (const dir of ancestors(path)) view.fileCounts.set(dir, (view.fileCounts.get(dir) || 0) + 1);
  }
}

function parentOf(path) {
  const i = path.lastIndexOf('/');
  return i < 0 ? '.' : path.slice(0, i);
}

function ancestors(path) {
  const found = ['.'];
  let i = path.indexOf('/');
  while (i >= 0) { found.push(path.slice(0, i)); i = path.indexOf('/', i + 1); }
  return found;
}

function baseName(path) { return path === '.' ? view.screen.root : path.slice(path.lastIndexOf('/') + 1); }

async function loadChildren(path) {
  if (view.lazy.has(path)) return;
  view.lazy.set(path, []);
  const found = await api('GET', '/api/children?screen=' + view.screen.id + '&path=' + encodeURIComponent(path === '.' ? '' : path));
  view.lazy.set(path, found.map(item => item.p));
  for (const item of found) view.info.set(item.p, item);
  renderTree();
}

// A picker

function updatePicker(screen, isNew) {
  for (const item of screen.changes || []) view.info.set(item.p, Object.assign(view.info.get(item.p) || {}, item));
  view.picked = new Set(screen.picked);
  view.selected = screen.selected;
  view.sideSelected = screen.sideSelected;
  view.status = screen.status;
  if (isNew) {
    // Started on a node deep in the tree (--select): its dirs open, so it's seen
    if (view.selected && view.selected !== '.') ancestors(view.selected).forEach(dir => view.expanded.add(dir));
    renderPickerFrame();
  }
  renderPickerParts();
  if (screen.previewVersion !== view.previewVersion || isNew) {
    view.previewVersion = screen.previewVersion;
    loadPreview();
  }
}

function renderPickerFrame() {
  const screen = view.screen;
  setTop(screen.root, screen.labels);
  const main = document.getElementById('main');
  const parts = [];
  if (screen.header) parts.push(el('div', {class: 'header'}, segmentsSpan(screen.header)));
  if (screen.tabs.length) parts.push(el('div', {class: 'tabs', id: 'tabs'}));
  if (screen.mode !== 'list') {
    parts.push(el('input', {type: 'search', id: 'search', placeholder: 'Search', autocomplete: 'off',
      oninput: event => { view.search = event.target.value; renderTree(); }}));
  }
  const body = el('div', {class: 'split'}, el('div', {id: 'tree'}),
    el('div', {}, el('div', {id: 'preview'}), el('div', {id: 'side'})));
  parts.push(body, el('div', {class: 'footer', id: 'footer'}), el('div', {class: 'help', id: 'help'}));
  main.replaceChildren(...parts);
}

function renderPickerParts() {
  renderTabs();
  renderTree();
  renderSide();
  const footer = document.getElementById('footer');
  if (footer) footer.replaceChildren(view.screen.footer ? segmentsSpan(view.screen.footer) : '');
  document.getElementById('status').replaceChildren(segmentsSpan(view.status));
  renderPickerActions();
  renderHelp();
}

function renderTabs() {
  const tabs = document.getElementById('tabs');
  if (!tabs) return;
  tabs.replaceChildren(...view.screen.tabs.map((tab, i) => el('button', {class: i === view.tab ? 'on' : '',
    onclick: () => { view.tab = i; renderPickerParts(); }}, tab.title)));
}

function shown(path) {
  const info = view.info.get(path) || {};
  if (info.x !== undefined && info.x !== null) return info.x;
  return view.screen.mode === 'list' ? path : baseName(path);
}

function renderTree() {
  const box = document.getElementById('tree');
  if (!box) return;
  const screen = view.screen;
  if (screen.mode === 'list') { box.replaceChildren(menuList()); return; }
  const rows = visibleRows();
  const list = el('div', {class: 'tree'}, rows.slice(0, MAX_ROWS).map(row));
  if (rows.length > MAX_ROWS) list.append(el('div', {class: 'more'}, (rows.length - MAX_ROWS) + ' more: search to find them'));
  box.replaceChildren(list);
}

function menuList() {
  const screen = view.screen;
  return el('div', {class: 'list'}, view.items.map(path => {
    const info = view.info.get(path);
    if (info.s) return el('div', {class: 'option ' + (shown(path).trim() ? 'heading' : 'blank')}, segmentsSpan(shown(path)));
    const classes = ['option', path === view.selected ? 'sel' : '', info.d ? 'disabled' : '', info.c ? 'c-' + info.c : ''];
    return el('button', {class: classes.join(' '), disabled: info.d, onclick: async () => {
      if (screen.previewBelow && view.selected !== path) { await act('select', {path}); return; }
      await act('select', {path});
      await act('enter');
    }}, segmentsSpan(shown(path)));
  }));
}

function inTab(path) {
  const tab = view.screen.tabs[view.tab];
  if (!tab || !tab.groups.length) return true;
  const info = view.info.get(path);
  return info && info.t === 'f' ? tab.groups.includes(info.g) : true;
}

function visibleRows() {
  const screen = view.screen;
  const query = view.search.trim();
  if (query) {
    const smart = query !== query.toLowerCase();
    const has = text => smart ? text.includes(query) : text.toLowerCase().includes(query.toLowerCase());
    const all = screen.mode === 'dir' ? [...view.info.keys()] : view.items;
    return all.filter(path => inTab(path) && (has(baseName(path)) || has(shown(path)))).map(path => ({path, depth: 0, flat: true}));
  }
  const rows = [{path: '.', depth: 0}];
  const kids = path => (screen.mode === 'dir' ? view.lazy.get(path) : view.children.get(path)) || [];
  const tabFiles = view.screen.tabs.length ? new Set(view.items.filter(p => view.info.get(p).t === 'f' && inTab(p)).flatMap(ancestors)) : null;
  const walk = (path, depth) => {
    for (const child of kids(path)) {
      const info = view.info.get(child);
      if (!inTab(child) || (tabFiles && info.t === 'd' && !tabFiles.has(child))) continue;
      rows.push({path: child, depth});
      if (info.t === 'd' && view.expanded.has(child)) walk(child, depth + 1);
      if (rows.length > MAX_ROWS) return;
    }
  };
  walk('.', 1);
  return rows;
}

function pickedUnder(path) {
  let count = 0;
  const prefix = path === '.' ? '' : path + '/';
  for (const picked of view.picked) if (path === '.' || picked.startsWith(prefix)) count++;
  return count;
}

function stateMark(path) {
  const screen = view.screen;
  const markOf = (name, group) => {
    const special = screen.stateMarks.find(([state, g]) => state === name && g === group);
    const state = screen.states.find(s => s.name === name) || screen.states[0];
    return special ? {mark: special[2], color: special[3]} : {mark: state.mark, color: state.color};
  };
  const info = view.info.get(path) || {};
  if (info.t === 'f') return markOf(info.st || screen.states[0].name, info.g || '');
  const names = new Set(view.items.filter(p => (p.startsWith(path === '.' ? '' : path + '/')) && view.info.get(p).t === 'f')
    .map(p => view.info.get(p).st || screen.states[0].name));
  return names.size === 1 ? markOf([...names][0], '') : {mark: '·', color: 'grey'};
}

function nextState(path) {
  const screen = view.screen;
  const names = screen.states.map(s => s.name);
  const files = path === '.' || (view.info.get(path) || {}).t !== 'f'
    ? view.items.filter(p => view.info.get(p).t === 'f' && (path === '.' || p.startsWith(path + '/'))) : [path];
  if (!files.length) return names[0];
  const first = view.info.get(files[0]);
  const allowed = first.a && first.a.length ? first.a : names;
  const at = allowed.indexOf(first.st || names[0]);
  return allowed[(at + 1) % allowed.length];
}

function row({path, depth, flat}) {
  const screen = view.screen;
  const info = view.info.get(path) || {t: 'd'};
  const isDir = info.t === 'd';
  const parts = [];
  parts.push(el('span', {class: 'twisty', onclick: event => {
    event.stopPropagation();
    if (!isDir || path === '.') return;
    if (view.expanded.has(path)) view.expanded.delete(path);
    else { view.expanded.add(path); if (screen.mode === 'dir') loadChildren(path); }
    renderTree();
  }}, isDir && path !== '.' ? (view.expanded.has(path) ? '▾' : '▸') : ''));
  if (screen.states.length) {
    const {mark, color} = stateMark(path);
    parts.push(el('button', {class: 'mark c-' + color, onclick: event => {
      event.stopPropagation();
      act('state', {paths: [path], name: nextState(path)});
    }}, mark.trim() || '·'));
  } else if (screen.multi) {
    const count = info.t === 'f' ? (view.picked.has(path) ? 1 : 0) : pickedUnder(path);
    const total = info.t === 'f' ? 1 : (view.fileCounts.get(path) || 0);
    const box = el('input', {type: 'checkbox', onclick: event => { event.stopPropagation(); act('pick', {paths: [path], on: event.target.checked}); }});
    box.checked = total > 0 && count === total;
    box.indeterminate = count > 0 && count < total;
    parts.push(box);
  }
  const text = flat && path !== '.' ? path : shown(path);
  parts.push(el('span', {class: 'name' + (isDir ? ' dir' : '') + (info.c ? ' c-' + info.c : '')}, segmentsSpan(text)));
  const picked = info.t === 'f' && view.picked.has(path);
  return el('div', {class: 'row' + (path === view.selected || (path === '.' && view.selected === '') ? ' sel' : '') + (picked ? ' picked' : ''),
    style: 'padding-left:' + (10 + (flat ? 0 : depth) * 16) + 'px',
    onclick: () => {
      if (isDir && path !== '.' && view.selected === path) {
        if (view.expanded.has(path)) view.expanded.delete(path); else { view.expanded.add(path); if (screen.mode === 'dir') loadChildren(path); }
        renderTree();
      }
      act('select', {path: path === '.' ? '' : path});
    }}, parts);
}

async function loadPreview() {
  const box = document.getElementById('preview');
  if (!box) return;
  const screen = view.screen;
  if (!screen.hasPreviews && !screen.previewBelow) { box.replaceChildren(); return; }
  const found = await api('GET', '/api/preview?screen=' + screen.id + '&path=' + encodeURIComponent(view.selected || ''));
  const lines = found.lines || [];
  const content = [];
  if (lines.length) content.push(el('pre', {}, lines.map(line => [previewLine(line), '\n'])));
  if (found.image) { const canvas = pictureCanvas(found.image); if (canvas) content.push(canvas); }
  box.replaceChildren(content.length ? el('div', {class: 'preview'}, content) : '');
}

function renderSide() {
  const box = document.getElementById('side');
  const side = view.screen.side;
  if (!box) return;
  if (!side) { box.replaceChildren(); return; }
  const rows = side.items.filter(item => item.t === 'd').slice(0, MAX_ROWS).map(item => el('div', {
    class: 'row' + (item.p === view.sideSelected ? ' sel' : ''), style: 'padding-left:' + (10 + item.p.split('/').length * 12) + 'px',
    onclick: () => act('sideSelect', {path: item.p}).then(() => { view.sideSelected = item.p; renderSide(); renderPickerActions(); })},
    el('span', {class: 'name dir'}, baseName(item.p))));
  box.replaceChildren(el('div', {class: 'side'}, el('h3', {}, side.root), el('div', {}, rows)));
}

function renderPickerActions() {
  const screen = view.screen;
  const buttons = [];
  const back = screen.hints.find(([key]) => key === 'q');
  buttons.push(el('button', {onclick: () => act('quit')}, back ? capitalized(back[1]) : 'Back'));
  if (screen.mode !== 'list') {
    let label = 'Choose';
    if (screen.states.length) label = 'Done';
    else if (screen.multi) label = view.picked.size ? 'Done · ' + view.picked.size + ' picked' : (screen.enterPicksSelection ? 'This one' : 'Pick some first');
    buttons.push(el('button', {class: 'primary', disabled: screen.multi && !screen.states.length && !view.picked.size && !screen.enterPicksSelection,
      onclick: () => act('enter')}, label));
  }
  if (screen.states.length && view.selected !== null) {
    for (const state of screen.states) {
      buttons.push(el('button', {class: 'c-' + state.color, onclick: () => act('state', {paths: [view.selected || '.'], name: state.name})},
        (state.mark.trim() || '·') + ' ', el('small', {}, state.name)));
    }
  }
  for (const key of screen.keys) {
    buttons.push(el('button', {title: key.text, onclick: () => act('press', {key: key.key})},
      key.text ? short(capitalized(key.text)) : key.name, el('small', {}, key.name)));
  }
  if (screen.side && screen.side.enterPicks) {
    buttons.push(el('button', {class: 'primary', disabled: !view.sideSelected, onclick: () => act('enter', {side: true})},
      'Into ' + (view.sideSelected || screen.side.root)));
    for (const key of screen.side.keys) {
      buttons.push(el('button', {onclick: () => act('enter', {side: true, key: key.key})}, key.text || key.name));
    }
  }
  if (screen.hints.length || screen.help.length) {
    buttons.push(el('button', {onclick: () => { view.showHelp = !view.showHelp; renderHelp(); }}, '?'));
  }
  document.getElementById('actions').replaceChildren(...buttons);
}

function renderHelp() {
  const box = document.getElementById('help');
  if (!box) return;
  const screen = view.screen;
  box.replaceChildren(view.showHelp ? el('div', {class: 'preview'},
    screen.hints.map(([key, text]) => el('div', {}, key.padEnd(10) + text)),
    screen.help.map(line => el('div', {}, styledSpan(line)))) : '');
}

function capitalized(text) { return text ? text[0].toUpperCase() + text.slice(1) : text; }

// A key's description, cut to fit a button (the whole of it is its title): to its first ':' or '(', or 28 characters
function short(text) {
  const cut = text.split(/[:(]/)[0].trim();
  return cut.length > 28 ? cut.slice(0, 27).trimEnd() + '…' : cut;
}

// A messages screen

function renderMessages(screen, isNew) {
  setTop(screen.title, screen.labels);
  const main = document.getElementById('main');
  if (isNew) main.replaceChildren(el('div', {class: 'lines', id: 'lines'}), el('div', {id: 'ask'}));
  const lines = document.getElementById('lines');
  lines.replaceChildren(...screen.lines.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, segmentsSpan(text))));
  const ask = document.getElementById('ask');
  if (screen.asking && !document.getElementById('answer')) {
    const input = el('input', {type: 'text', id: 'answer', value: screen.asking.default});
    ask.replaceChildren(el('form', {onsubmit: event => { event.preventDefault(); act('answer', {text: input.value}); }},
      el('label', {}, screen.asking.prompt), input));
    input.focus();
  } else if (!screen.asking) ask.replaceChildren();
  document.getElementById('status').replaceChildren(screen.status || '');
  const buttons = [];
  if (screen.asking) {
    buttons.push(el('button', {onclick: () => act('answer', {text: ''})}, 'Back'));
    buttons.push(el('button', {class: 'primary', onclick: () => act('answer', {text: document.getElementById('answer').value})}, 'Done'));
  } else if (screen.waiting) buttons.push(el('button', {class: 'primary', onclick: () => act('continue')}, 'Continue'));
  else if (screen.stoppable) buttons.push(el('button', {onclick: () => act('stop')}, 'Stop'));
  document.getElementById('actions').replaceChildren(...buttons);
  if (!screen.asking) window.scrollTo(0, document.body.scrollHeight);
}

// Nothing shown: a flow ended (what it printed last), or none ran

function renderHome() {
  setTop('Running', []);
  const log = view.log.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, segmentsSpan(text)));
  document.getElementById('main').replaceChildren(el('div', {class: 'card'},
    el('h2', {}, view.running ? 'Starting' : 'Nothing is running'),
    el('p', {class: 'note'}, view.running ? waitingDots() : 'Start a sync or a sort from Sync.'),
    view.running ? '' : el('div', {class: 'row2'}, el('a', {class: 'button primary', href: '/sync'}, 'Go to Sync'))),
    log.length ? el('div', {class: 'lines'}, el('div', {class: 'section-title'}, 'What the last run printed'), log) : '');
  document.getElementById('status').replaceChildren();
  document.getElementById('actions').replaceChildren();
}

function waitingDots() { return el('span', {class: 'dots', style: 'animation-delay:-' + (Date.now() % 1600) + 'ms'}); }

function setTop(title, labels) {
  document.getElementById('crumbs').replaceChildren(segmentsSpan(title || ''));
  document.getElementById('labels').replaceChildren(...(labels || []).map(labelChip));
  document.title = (title || 'dirdelta').split(' > ').pop();
}

tabBar('run');
poll();
