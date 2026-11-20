// dirdelta's web version: what its session shows now (web/session.py), drawn here and acted on.
// A picker is treepicker's (a menu, a tree of files, or a dir), done here: the server keeps its
// selection, picks and states, and says each change; a messages screen is ui/messages.py's.
'use strict';

const MAX_ROWS = 1500;
const view = {
  version: 0, screen: null, items: [], info: new Map(), children: new Map(), fileCounts: new Map(),
  picked: new Set(), selected: null, sideSelected: null, status: '', previewVersion: -1,
  expanded: new Set(['.']), sideExpanded: new Set(), wentBack: false, search: '', tab: 0, showHelp: false, lazy: new Map(), running: false, log: [],
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
  // (The run's tab, for the breadcrumbs' first part, known before the tab bar's own check)
  if (data.tab) runningTab = data.tab;
  view.version = data.version;
  view.running = data.running;
  view.log = data.log;
  const screen = data.screen;
  clearTimeout(view.noScreen);
  if (!screen) {
    // (While a run goes on, it's often between two screens for a moment: what was shown stays for a second,
    // rather than flashing this page, so e.g. a tree's menu is still shown over the tree)
    if (data.running && view.screen) view.noScreen = setTimeout(() => { view.screen = null; renderHome(); }, 1000);
    else { view.screen = null; renderHome(); }
    return;
  }
  const isNew = !view.screen || view.screen.id !== screen.id;
  if (isNew) newScreen(screen);
  if (screen.kind === 'picker') updatePicker(screen, isNew);
  else renderMessages(screen, isNew);
  if (isNew && view.scrollTo) {
    // (Back where the page was before it was refreshed, once it's drawn, and again once a dir's lists came)
    const top = view.scrollTo;
    view.scrollTo = 0;
    requestAnimationFrame(() => window.scrollTo(0, top));
    setTimeout(() => { if (Math.abs(window.scrollY - top) > 2) window.scrollTo(0, top); }, 600);
  }
}

function newScreen(screen) {
  // (What was shown of the screen before, kept: coming back to it, as the flow does, finds it as it was)
  keepView();
  // (Whether this page showed one before: between two screens the flow may show none for a moment)
  const previous = view.shownOne;
  view.shownOne = true;
  Object.assign(view, {screen, items: [], info: new Map(), children: new Map(), fileCounts: new Map(),
    picked: new Set(), search: '', tab: 0, showHelp: false, previewVersion: -1, lazy: new Map(),
    expanded: new Set(['.']), sideExpanded: null, sideFollowed: undefined, scrollTo: 0, isKept: false});
  // Each screen its own address: a new picker a step of the browser's history (its Back is the screen's
  // Back, see goBack()); one shown on going back, or on a refresh, or a messages screen in its place
  const address = '#screen=' + screen.id;
  if (previous && screen.kind === 'picker' && !view.wentBack && location.hash !== address) history.pushState({step: true}, '', address);
  else history.replaceState(null, '', address);
  view.wentBack = false;
  const kept = keptView(screen);
  if (kept) {
    Object.assign(view, {expanded: new Set(kept.expanded), tab: kept.tab, search: kept.search, scrollTo: kept.scroll, isKept: true,
      sideExpanded: kept.sideExpanded ? new Set(kept.sideExpanded) : null});
  }
  if (screen.items) setItems(screen.items);
  if (screen.mode === 'dir') [...view.expanded].forEach(loadChildren);
}

// The browser's Back (a phone's back gesture) on a flow's screen: the screen's own Back (q), the flow then
// showing what came before it. On a messages screen, which has none, it stays
function goBack() {
  // (A step the browser has: its Back, the same, so the two agree; else the screen's own)
  if (history.state && history.state.step) history.back();
  else act('quit');
}

addEventListener('popstate', () => {
  const screen = view.screen;
  if (!screen) return;
  if (screen.kind !== 'picker') { history.pushState(null, '', '#screen=' + screen.id); return; }
  if (location.hash === '#screen=' + screen.id) return;
  view.wentBack = true;
  act('quit');
});

// What this tab showed of a screen (its open folders, tab, search and scroll), kept in its session's storage
// as it's left (another screen, a refresh, another app), by what the screen is (the flow shows a picker again
// as a new one): the server keeps the rest (the selection, the picks)
function screenName(screen) {
  return [screen.kind, screen.root || screen.title || '', (screen.header || '').split('\n')[0]].join('|');
}

function keepView() {
  if (!view.screen) return;
  try {
    sessionStorage.setItem('dirdelta_view_' + screenName(view.screen), JSON.stringify({
      expanded: [...view.expanded], sideExpanded: view.sideExpanded ? [...view.sideExpanded] : null, tab: view.tab,
      search: view.search, scroll: Math.round(window.scrollY)}));
  } catch (error) { /* (nothing kept: it starts at the top) */ }
}

function keptView(screen) {
  try {
    return JSON.parse(sessionStorage.getItem('dirdelta_view_' + screenName(screen)) || 'null');
  } catch (error) { return null; }
}

// (The page's own scroll, not the browser's: it would scroll before the screen is drawn)
history.scrollRestoration = 'manual';
addEventListener('pagehide', keepView);
document.addEventListener('visibilitychange', () => { if (document.hidden) keepView(); });

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
    // (Opened a level at a time while the next one fits the tree's height, as treepicker does)
    if (!view.isKept && screen.mode === 'tree') {
      openToFit(path => (view.children.get(path) || []).filter(child => inTab(child)), path => view.info.get(path).t === 'd',
        view.expanded, rowsThatFit(document.getElementById('tree')), ['.']);
    }
  }
  renderPickerParts();
  if (screen.previewVersion !== view.previewVersion || isNew) {
    view.previewVersion = screen.previewVersion;
    loadPreview();
  }
}

function renderPickerFrame() {
  const screen = view.screen;
  // (A menu's root is its breadcrumbs; a tree's is its folder: its page has the flow's, where it is)
  setTop(screen.mode !== 'list' && screen.crumbs ? screen.crumbs : screen.root, screen.labels);
  const main = document.getElementById('main');
  const parts = [];
  if (screen.header) parts.push(el('div', {class: 'header'}, segmentsSpan(screen.header)));
  if (screen.tabs.length) parts.push(el('div', {class: 'tabs', id: 'pickertabs'}));
  if (screen.mode !== 'list') {
    parts.push(el('input', {type: 'search', id: 'search', placeholder: 'Search', autocomplete: 'off',
      value: view.search, oninput: event => { view.search = event.target.value; renderTree(); }}));
  }
  const body = el('div', {class: 'split'}, el('div', {id: 'tree'}),
    el('div', {}, el('div', {id: 'preview'}), el('div', {id: 'side'})));
  parts.push(body, el('div', {class: 'footer', id: 'footer'}), el('div', {class: 'help', id: 'help'}));
  // A menu right after a tree (what to do with its picks, then its confirmations): a panel over that tree,
  // dimmed under it, rather than a page of its own; the flow is the same (the panel is this menu's screen)
  const shown = main.dataset.shows;
  if (screen.mode === 'list' && (shown === 'tree' || shown === 'dir' || shown === 'panel')) {
    showPanel(main, parts);
    return;
  }
  main.dataset.shows = screen.mode;
  main.replaceChildren(...parts);
}

function showPanel(main, parts) {
  let sheet = main.querySelector('.panelwrap .sheet');
  if (!sheet) {
    // (The tree as it was, inert: its ids gone, so the panel's parts have them)
    const under = el('div', {class: 'under', inert: true}, [...main.childNodes]);
    under.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
    sheet = el('div', {class: 'sheet', role: 'dialog', 'aria-modal': 'true'});
    main.replaceChildren(under, el('div', {class: 'panelwrap'}, el('div', {class: 'backdrop', onclick: goBack}), sheet));
    placePanel();
  }
  main.dataset.shows = 'panel';
  sheet.replaceChildren(...parts);
  sheet.scrollTop = 0;
}

// The panel between the top bar and the bottom bar (whose heights change)
function placePanel() {
  const top = document.getElementById('top'), bottom = document.getElementById('bottom');
  const root = document.documentElement.style;
  root.setProperty('--panel-top', (top ? top.getBoundingClientRect().bottom : 0) + 'px');
  root.setProperty('--panel-bottom', (bottom ? window.innerHeight - bottom.getBoundingClientRect().top : 0) + 'px');
}

if (window.ResizeObserver) {
  const watch = new ResizeObserver(placePanel);
  for (const id of ['top', 'bottom']) { const node = document.getElementById(id); if (node) watch.observe(node); }
}
addEventListener('resize', placePanel);

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
  const tabs = document.getElementById('pickertabs');
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
    // (A line that isn't an option: a section's heading (── Name ──), a blank line, or what to read, e.g. the
    // sync state and its points)
    if (info.s) {
      const plain = shown(path).replace(/[\x01\x02][^\x01\x02]*[\x01\x02]/g, '').trim();
      return el('div', {class: 'option ' + (!plain ? 'blank' : plain.startsWith('\u2500') ? 'heading' : 'info')}, segmentsSpan(shown(path)));
    }
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
  // (Each row's branch lines, as treepicker draws them: for each level above it, whether that ancestor has
  // more below it (a line down, │), then its own (├, or └ for the last))
  const walk = (path, depth, above) => {
    const shownKids = kids(path).filter(child => {
      const info = view.info.get(child);
      return inTab(child) && !(tabFiles && info.t === 'd' && !tabFiles.has(child));
    });
    shownKids.forEach((child, index) => {
      if (rows.length > MAX_ROWS) return;
      const last = index === shownKids.length - 1;
      rows.push({path: child, depth, guides: [...above, last ? 'elbow' : 'tee']});
      if (view.info.get(child).t === 'd' && view.expanded.has(child)) walk(child, depth + 1, [...above, last ? 'blank' : 'pipe']);
    });
  };
  walk('.', 1, []);
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

function row({path, depth, flat, guides}) {
  const screen = view.screen;
  const info = view.info.get(path) || {t: 'd'};
  const isDir = info.t === 'd';
  const parts = flat ? [] : (guides || []).map(kind => el('span', {class: 'guide ' + kind}));
  parts.push(el('span', {class: 'twisty' + (!isDir && !flat && guides && guides.length ? ' leaf' : ''), onclick: event => {
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

// How many rows of a tree fit from where its box starts to the bottom bar (at least a few)
function rowsThatFit(box) {
  if (!box) return 10;
  const bottom = document.getElementById('bottom');
  const end = bottom ? bottom.getBoundingClientRect().top : window.innerHeight;
  return Math.max(6, Math.floor((end - box.getBoundingClientRect().top) / 40));
}

// Opens a tree's folders a level at a time (into expanded), the whole of the next level while it still fits in
// rows: what's shown at first, as treepicker's (kids(path): what's shown under it; tops: the first level's parents)
function openToFit(kids, isDir, expanded, rows, tops) {
  let shown = tops.length + tops.reduce((sum, top) => sum + kids(top).length, 0);
  let level = tops.flatMap(top => kids(top)).filter(isDir);
  while (level.length) {
    const more = level.reduce((sum, path) => sum + (expanded.has(path) ? 0 : kids(path).length), 0);
    if (shown + more > rows) break;
    level.forEach(path => expanded.add(path));
    shown += more;
    level = level.flatMap(path => kids(path)).filter(isDir);
  }
}

// The side tree (the other replica's folders, to choose one): opened as the picker's, its folders opened and
// closed by their ▸ ▾, with branch lines
function renderSide() {
  const box = document.getElementById('side');
  const side = view.screen.side;
  if (!box) return;
  if (!side) { box.replaceChildren(); return; }
  // (Its folders and files, each under its folder)
  const known = new Set(side.items.filter(item => item.t === 'd').map(item => item.p)), under = new Map();
  for (const {p: path} of side.items) {
    const cut = path.lastIndexOf('/'), parent = cut > 0 && known.has(path.slice(0, cut)) ? path.slice(0, cut) : '';
    if (!under.has(parent)) under.set(parent, []);
    under.get(parent).push(path);
  }
  const kids = path => under.get(path) || [];
  const openTo = path => { while (path.includes('/')) { path = path.slice(0, path.lastIndexOf('/')); if (known.has(path)) view.sideExpanded.add(path); } };
  if (!view.sideExpanded) {
    view.sideExpanded = new Set();
    openTo(view.sideSelected || '');
    // (Its box drawn first, empty, to know where it starts)
    box.replaceChildren(el('div', {class: 'side'}, el('h3', {}, side.root), el('div', {class: 'tree'})));
    openToFit(kids, path => known.has(path), view.sideExpanded, rowsThatFit(box), ['']);
  }
  // It follows the selection on the left (to what the flow thinks it matches there, e.g. the other version of a
  // file that differs): its folders opened to it
  if (view.sideSelected !== view.sideFollowed) {
    view.sideFollowed = view.sideSelected;
    openTo(view.sideSelected || '');
  }
  const ordered = [];
  const walk = (parent, above) => kids(parent).forEach((path, index, all) => {
    if (ordered.length >= MAX_ROWS) return;
    const last = index === all.length - 1;
    ordered.push({path, guides: [...above, last ? 'elbow' : 'tee']});
    if (view.sideExpanded.has(path)) walk(path, [...above, last ? 'blank' : 'pipe']);
  });
  walk('', []);
  const toggle = path => {
    if (view.sideExpanded.has(path)) view.sideExpanded.delete(path); else view.sideExpanded.add(path);
    renderSide();
  };
  const rows = ordered.map(({path, guides}) => el('div', {
    class: 'row' + (path === view.sideSelected ? ' sel' : ''),
    onclick: () => {
      if (path === view.sideSelected && kids(path).length) toggle(path);
      act('sideSelect', {path}).then(() => { view.sideSelected = path; renderSide(); renderPickerActions(); });
    }},
    ...guides.map(kind => el('span', {class: 'guide ' + kind})),
    el('span', {class: 'twisty' + (kids(path).length ? '' : ' leaf'), onclick: event => { event.stopPropagation(); if (kids(path).length) toggle(path); }},
      kids(path).length ? (view.sideExpanded.has(path) ? '▾' : '▸') : ''),
    el('span', {class: 'name' + (known.has(path) ? ' dir' : '')}, baseName(path))));
  box.replaceChildren(el('div', {class: 'side'}, el('h3', {}, side.root), el('div', {class: 'tree'}, rows)));
}

// The keys a picker has for the whole of it, not its selection: shown under Misc (the rest act on what's selected)
const GENERAL_KEYS = new Set(['i', '?']);
// Keys the page has no button for: the menu (:) lists what's selected can have done, each with its key, as the
// buttons here do (with files picked, it's Enter's); the replicas dashboard (#) is the Replicas tab's
const NO_BUTTON_KEYS = new Set([':', '#']);

// The bottom bar, in sections: going back and the main action (Enter's, named for what it's on); what acts
// on the selection; on the side tree's; and Misc (the picker's own keys: the pictures)
function renderPickerActions() {
  const screen = view.screen;
  const main = [];
  const back = screen.hints.find(([key]) => key === 'q');
  main.push(el('button', {onclick: goBack}, back ? capitalized(back[1]) : 'Back'));
  const selected = view.selected ? baseName(view.selected) : screen.root;
  if (screen.mode !== 'list') {
    const enter = screen.hints.find(([key]) => key === 'Enter');
    const what = enter ? capitalized(enter[1]) : 'Choose';
    let label = what + (screen.multi ? '' : ' ' + selected);
    if (screen.states.length) label = 'Done';
    else if (screen.multi) label = view.picked.size ? what + ' with ' + view.picked.size + ' picked' :
      screen.enterPicksSelection ? what + ' with ' + selected : 'Pick some first';
    main.push(el('button', {class: 'primary', disabled: screen.multi && !screen.states.length && !view.picked.size && !screen.enterPicksSelection,
      onclick: () => act('enter')}, label));
  }
  if (screen.hints.length || screen.help.length) {
    main.push(el('button', {class: 'help', title: 'What the keys do', onclick: () => { view.showHelp = !view.showHelp; renderHelp(); }}, '?'));
  }
  const keyButton = (key, onclick) => el('button', {title: key.text, onclick},
    key.text ? short(capitalized(key.text)) : key.name, el('small', {class: 'keyname'}, key.name));
  const onSelection = [], general = [];
  if (screen.states.length && view.selected !== null) {
    for (const state of screen.states) {
      onSelection.push(el('button', {class: 'c-' + state.color, onclick: () => act('state', {paths: [view.selected || '.'], name: state.name})},
        (state.mark.trim() || '·') + ' ', el('small', {}, state.name)));
    }
  }
  for (const key of screen.keys.filter(key => !NO_BUTTON_KEYS.has(key.name))) {
    (GENERAL_KEYS.has(key.name) ? general : onSelection).push(keyButton(key, () => act('press', {key: key.key})));
  }
  const side = [];
  if (screen.side && screen.side.enterPicks) {
    side.push(el('button', {class: 'primary', disabled: !view.sideSelected, onclick: () => act('enter', {side: true})},
      'Into ' + (view.sideSelected || screen.side.root)));
    for (const key of screen.side.keys.filter(key => !NO_BUTTON_KEYS.has(key.name))) side.push(keyButton(key, () => act('enter', {side: true, key: key.key})));
  }
  const section = (title, buttons, extra) => buttons.length ?
    el('div', {class: 'actsec' + (extra ? ' ' + extra : '')}, title ? el('div', {class: 'seclabel'}, title) : '', buttons) : '';
  document.getElementById('actions').replaceChildren(section('', main, 'main'),
    section(screen.mode === 'list' ? '' : 'On ' + selected, onSelection),
    section(screen.side ? 'In ' + screen.side.root : '', side), section('Misc', general));
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

// A key's description on a button (the whole of it is its title): to its first ':' or '(', all of it (it wraps)
function short(text) {
  return text.split(/[:(]/)[0].trim();
}

// A messages screen

function renderMessages(screen, isNew) {
  setTop(screen.title, screen.labels);
  const main = document.getElementById('main');
  if (isNew) { main.dataset.shows = 'messages'; main.replaceChildren(el('div', {class: 'lines', id: 'lines'}), el('div', {id: 'ask'})); }
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
  document.getElementById('main').dataset.shows = 'home';
  document.getElementById('main').replaceChildren(el('div', {class: 'card'},
    el('h2', {}, view.running ? 'Starting' : 'Nothing is running'),
    el('p', {class: 'note'}, view.running ? waitingDots() : 'Sync two replicas from Replicas, or sort an inbox from Inboxes.'),
    view.running ? '' : el('div', {class: 'row2'}, el('a', {class: 'button primary', href: '/replicas'}, 'Go to Replicas'),
      el('a', {class: 'button', href: '/inboxes'}, 'Go to Inboxes'))),
    log.length ? el('div', {class: 'section-title'}, 'What the last run printed') : '', log.length ? el('div', {class: 'lines'}, log) : '');
  document.getElementById('status').replaceChildren();
  document.getElementById('actions').replaceChildren();
}

function waitingDots() { return el('span', {class: 'dots', style: 'animation-delay:-' + (Date.now() % 1600) + 'ms'}); }

// The breadcrumbs (under the tabs: a run is a page of its tab's): the tab first (a sync's Replicas, a sort's
// Inboxes), then where the run is, without dirdelta's own name (the top bar has it)
function setTop(title, labels) {
  const rest = (title || '').replace(/^dirdelta(?: > |$)/, '');
  const tab = runningTab === 'inboxes' ? ['/inboxes', 'Inboxes'] : ['/replicas', 'Replicas'];
  document.getElementById('crumbs').replaceChildren(el('a', {href: tab[0]}, tab[1]),
    rest ? el('span', {id: 'where'}, ' > ', segmentsSpan(rest)) : el('span', {id: 'where'}));
  document.getElementById('labels').replaceChildren(...(labels || []).map(labelChip));
  document.title = (title || 'dirdelta').split(' > ').pop();
}

tabBar('run');
poll();
