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
  // (A sync's two replicas, on every screen of it: their names shown in their colors, colorNames())
  view.sides = pairSides(screen);
  if (screen.kind === 'picker') updatePicker(screen, isNew);
  else if (screen.kind === 'merge') renderMerge(screen, isNew);
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
  closeGrid();
  // (Whether this page showed one before: between two screens the flow may show none for a moment)
  const previous = view.shownOne;
  view.shownOne = true;
  Object.assign(view, {screen, items: [], info: new Map(), children: new Map(), fileCounts: new Map(),
    picked: new Set(), search: '', tab: 0, showHelp: false, previewVersion: -1, lazy: new Map(),
    expanded: new Set(['.']), sideExpanded: null, sideFollowed: undefined, scrollTo: 0, isKept: false, sides: null});
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
  else quitScreen();
}

// The screen's own Back: q, or a tree's key that goes back keeping what was marked (the combined tree's Ctrl-Q:
// q would drop its marks)
const KEEPING_BACK = /keeping/;
function quitScreen() {
  const keep = view.screen && view.screen.keys.find(key => key.ends && KEEPING_BACK.test(key.text || ''));
  return keep ? act('press', {key: keep.key}) : act('quit');
}

addEventListener('popstate', () => {
  const screen = view.screen;
  if (!screen) return;
  if (screen.kind !== 'picker') { history.pushState(null, '', '#screen=' + screen.id); return; }
  if (location.hash === '#screen=' + screen.id) return;
  view.wentBack = true;
  quitScreen();
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
  view.sides = pairSides(screen);
  if (isNew && screen.mode === 'list' && view.pendingKey) {
    // (An action's button pressed (quickActions()): its option chosen, the menu not shown, the tree left as it is;
    // unless it's greyed out there, then the menu's shown, saying why)
    const key = view.pendingKey;
    view.pendingKey = null;
    const path = [...optionKeys()].find(([, one]) => one === key);
    if (path && !view.info.get(path[0]).d) { chooseOption(path[0]); return; }
  }
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
  const sides = pairSides(screen);
  const search = screen.mode !== 'list' ? el('input', {type: 'search', id: 'search', placeholder: 'Search', autocomplete: 'off',
    value: view.search, oninput: event => { view.search = event.target.value; renderTree(); }}) : '';
  if (sides && screen.states.length) {
    // A sync's tree of states: its head kept in sight as the tree scrolls, in two rows: the pair and what the
    // arrows do, with the plan so far; the tabs (each with its count) and the search
    parts.push(el('div', {class: 'statehead'}, el('div', {class: 'headrow'}, pairLegend(sides)),
      el('div', {class: 'headrow'}, screen.tabs.length ? el('div', {class: 'tabs', id: 'pickertabs'}) : '', search)));
  } else {
    if (screen.header) parts.push(el('div', {class: 'header'}, segmentsSpan(screen.header)));
    if (screen.tabs.length) parts.push(el('div', {class: 'tabs', id: 'pickertabs'}));
    if (search) parts.push(search);
  }
  // On a wide screen the trees side by side, and what's shown of the selection (its details, a diff, the AI's
  // suggestion) in the bottom bar, right of the buttons (placePreview()); on a phone, under the tree
  const inBar = isWide() && screen.mode !== 'list';
  // (No side tree: the tree (or the menu) takes the whole width, a tree's details in the bottom bar)
  const body = el('div', {class: 'split' + (!screen.side && (inBar || screen.mode === 'list') ? ' single' : '')}, el('div', {id: 'tree'}),
    el('div', {}, inBar ? '' : el('div', {id: 'preview'}), el('div', {id: 'side'})));
  parts.push(body, el('div', {class: 'footer', id: 'footer'}), el('div', {class: 'help', id: 'help'}));
  placePreview(inBar);
  // A menu right after a tree (what to do with its picks, then its confirmations): a panel over that tree,
  // dimmed under it, rather than a page of its own; the flow is the same (the panel is this menu's screen)
  // (Only a menu the tree's own buttons asked for (Enter, an action, Merge): Back from the tree to the menu before
  // it isn't one, nor is any other)
  const shown = main.dataset.shows;
  if (screen.mode === 'list' && (view.menuAsked && (shown === 'tree' || shown === 'dir') || shown === 'panel')) {
    showPanel(main, parts);
    return;
  }
  view.menuAsked = false;
  main.dataset.shows = screen.mode;
  document.body.style.minHeight = '';
  main.replaceChildren(...parts);
}

// Whether the screen's wide enough for the trees side by side and the selection's details in the bottom bar
const WIDE = window.matchMedia('(min-width: 900px)');
function isWide() { return WIDE.matches; }

// The bottom bar with the selection's details on the right of its buttons (wide), or without them
function placePreview(inBar) {
  const bottom = document.getElementById('bottom');
  const there = bottom.querySelector(':scope > #preview');
  bottom.classList.toggle('withpreview', inBar);
  if (inBar && !there) bottom.append(el('div', {id: 'preview'}));
  if (!inBar && there) there.remove();
}

// (Turning a phone sideways, or a window's width: the picker drawn again for it)
WIDE.addEventListener('change', () => {
  if (view.screen && view.screen.kind === 'picker' && document.getElementById('main').dataset.shows !== 'panel') {
    renderPickerFrame(); renderPickerParts(); view.previewVersion = -1; loadPreview();
  }
});

function showPanel(main, parts) {
  let sheet = main.querySelector('.panelwrap .sheet');
  if (!sheet) {
    // (The page keeps its height while the panel's open: the bar under it shrinks, and the page's scrollbar would go
    // and come back, a jolt)
    document.body.style.minHeight = document.documentElement.scrollHeight + 'px';
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
  renderPlan();
  renderGrid();
  renderTabs();
  renderTree();
  renderSide();
  const footer = document.getElementById('footer');
  if (footer) footer.replaceChildren(view.screen.footer ? segmentsSpan(view.screen.footer) : '');
  document.getElementById('status').replaceChildren(segmentsSpan(NARROW.matches ? shortStatus(view.status) : view.status));
  markHashingNow(document.getElementById('status'));
  renderPickerActions();
  renderHelp();
  colorNames(document.getElementById('main'));
  colorNames(document.getElementById('bottom'));
}

// The status line on a phone: each replica's hashing without its files' counts ("63% hashed (1,204/1,911)" -> "63%
// hashed", with dots while it goes on; "(…, paused)" -> "(paused)")
const HASH_COUNTS = /% hashed( \u2713)? \((?:[\d,]+\/[\d,]+)(?:, ([^)]*))?\)/g;
const HASHING_NOW = '\u2063';
function shortStatus(status) {
  return (status || '').replace(HASH_COUNTS, (all, done, how) => '% hashed' + (done || '') + (how ? ' (' + how + ')' : done ? '' : HASHING_NOW));
}

// A sync's two replicas named in its texts (menus, headers, messages, previews, buttons): each name with its icon
// in its color, as the combined tree shows them, rather than plain text
function colorNames(root) {
  if (!root || !view.sides) return;
  const names = view.sides.filter(side => side.name).sort((one, other) => other.name.length - one.name.length);
  if (!names.length) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode: node =>
    node.parentElement && !node.parentElement.closest('.pairname, input, textarea, select, option, .pairside, b, .markrow') &&
    names.some(side => node.data.includes(side.name)) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT});
  const found = [];
  while (walker.nextNode()) found.push(walker.currentNode);
  for (const node of found) {
    const parts = [];
    let rest = node.data;
    while (rest) {
      let at = -1, side = null;
      for (const one of names) {
        const where = rest.indexOf(one.name);
        if (where >= 0 && (at < 0 || where < at)) { at = where; side = one; }
      }
      if (at < 0) { parts.push(rest); break; }
      if (at) parts.push(rest.slice(0, at));
      parts.push(sideName(side));
      rest = rest.slice(at + side.name.length);
    }
    node.replaceWith(...parts);
  }
}

function renderTabs() {
  const tabs = document.getElementById('pickertabs');
  if (!tabs) return;
  // (Each with how many files it shows)
  const count = tab => view.items.filter(path => { const info = view.info.get(path); return info.t === 'f' && (!tab.groups.length || tab.groups.includes(info.g)); }).length;
  // (A sync's tree: a dropdown beside the search, "Show: All (13)", rather than a row of tabs of its own)
  if (view.sides && view.screen.states.length) {
    const pick = el('select', {'aria-label': 'Which files to show', onchange: event => { view.tab = +event.target.value; renderPickerParts(); }},
      view.screen.tabs.map((tab, i) => el('option', {value: String(i)}, tab.title + ' (' + count(tab) + ')')));
    pick.value = String(view.tab);
    tabs.classList.add('tabselect');
    tabs.replaceChildren(el('label', {}, 'Show ', pick));
    return;
  }
  tabs.replaceChildren(...view.screen.tabs.map((tab, i) => el('button', {class: i === view.tab ? 'on' : '',
    onclick: () => { view.tab = i; renderPickerParts(); }}, tab.title, el('span', {class: 'tabcount'}, ' ' + count(tab)))));
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

// A menu's option's icon, by what it does: a files' menu's (what to do with them), the sync menu's (all of it in one
// tree, a kind of difference at a time, reading the replicas anew, the pair's own), and going back
const ACTION_ICONS = [[/^(Nothing|Back)/, 'back'], [/^Ask AI/, 'ai'], [/^Copy/, 'copy'], [/^Replace/, 'swap'], [/^Merge/, 'merge'],
  [/^(Remove|Delete|Trash)/, 'trash'], [/^Rename/, 'pencil'], [/^Open/, 'open'],
  [/^(Read .* anew|See what changed|Refresh|Rescan)/, 'refresh'], [/^Explore/, 'zip'], [/^Move/, 'move'],
  [/^(Skip|Leave)/, 'skip'], [/^Sync: /, 'sync'], [/^Files only in /, 'onlyhere'], [/^Files that differ/, 'differ'],
  [/^Compare/, 'equal'], [/^(Add to|Remove from) favorites/, 'star'], [/^Not now/, 'clock'], [/^(Name|Label)/, 'pencil'],
  [/^Replicas dashboard/, 'replicas'], [/^Hash/, 'hash'], [/^Pause/, 'clock']];

async function chooseOption(path) {
  if (view.screen.previewBelow && view.selected !== path) { await act('select', {path}); return; }
  // (Chosen: it says so, with the dots, until the next screen comes; the menu's other options off meanwhile)
  const box = document.getElementById('tree');
  const button = box && [...box.querySelectorAll('button.option')].find(one => one.dataset.path === path);
  if (button) {
    box.classList.add('choosing');
    button.classList.add('chosen');
    button.append(el('span', {class: 'dots'}));
  }
  await act('select', {path});
  await act('enter');
}

// A menu option's key, as the flow writes it before the text ('[a] Ask AI...'): the key, and the text without it
const KEY_PREFIX = /^(?:\x02[^\x02]*\x02)?\[([^\]]+)\](?:\x02[^\x02]*\x02)?\s*/;
function withoutKeyPrefix(label) { return label.replace(KEY_PREFIX, '').replace(/^\s+/, ''); }

// The keys of a files' menu's options: the flow's own (a picker's key that does it too: a, cc, e, Ctrl-R), else
// one as the sync's screens have it (> to the other replica and < from it, as the combined tree's; d removes,
// as in the tree on the right; m and M rename to match, there and here; Esc goes back; Ctrl-X opens), else
// 1-9, in their order: {path: key}
const INVENTED_KEYS = [[/^Nothing/, 'Esc'], [/^Copy/, '>'], [/^Replace/, '<'], [/^Merge/, 'g'], [/^(Remove|Delete|Trash)/, 'd'],
  [/^Rename the files matching/, 'm'], [/^Rename .* their matches/, 'M'], [/^Open/, 'Ctrl-X'], [/^Ask AI/, 'a'],
  [/^Explore/, 'e'], [/^(Read .* anew|See what changed)/, 'Ctrl-R']];

function optionKeys() {
  const found = new Map(), used = new Set();
  const options = view.items.filter(path => !view.info.get(path).s);
  for (const path of options) {
    const own = KEY_PREFIX.exec(plainOf(shown(path)).replace(/^\s+/, ''));
    if (own) { found.set(path, own[1]); used.add(own[1]); }
  }
  for (const path of options) {
    if (found.has(path)) continue;
    const text = withoutKeyPrefix(plainOf(shown(path)));
    const hit = INVENTED_KEYS.find(([pattern, key]) => pattern.test(text) && !used.has(key));
    if (hit) { found.set(path, hit[1]); used.add(hit[1]); }
  }
  let digit = 1;
  for (const path of options) {
    if (!found.has(path) && digit <= 9) found.set(path, String(digit++));
  }
  return found;
}

// A key pressed on a files' menu: its option chosen (cc: c twice, quickly)
document.addEventListener('keydown', event => {
  if (!view.optionKeys || !view.optionKeys.size || document.getElementById('main').dataset.shows !== 'panel') return;
  if (event.target.closest && event.target.closest('input, textarea')) return;
  let name = event.key === 'Escape' ? 'Esc' : event.ctrlKey && event.key.length === 1 ? 'Ctrl-' + event.key.toUpperCase() : event.key;
  if (name === 'c' && !event.ctrlKey) {
    const now = Date.now();
    if (view.lastC && now - view.lastC < 800) { name = 'cc'; view.lastC = 0; } else { view.lastC = now; return; }
  }
  for (const [path, key] of view.optionKeys) {
    if (key === name && !view.info.get(path).d) { event.preventDefault(); chooseOption(path); return; }
  }
});

function actionIcon(label) {
  const text = label.replace(/^\s*\[[^\]]*\]\s*/, '').trim();
  const found = ACTION_ICONS.find(([pattern]) => pattern.test(text));
  return found ? found[1] : null;
}

function menuList() {
  const screen = view.screen;
  const inPanel = document.getElementById('main').dataset.shows === 'panel';
  const keys = inPanel ? optionKeys() : new Map();
  view.optionKeys = keys;
  return el('div', {class: 'list'}, view.items.map(path => {
    const info = view.info.get(path);
    // (A line that isn't an option: a section's heading (── Name ──), a blank line, or what to read, e.g. the
    // sync state and its points)
    if (info.s) {
      const plain = shown(path).replace(/[\x01\x02][^\x01\x02]*[\x01\x02]/g, '').trim();
      return el('div', {class: 'option ' + (!plain ? 'blank' : plain.startsWith('\u2500') ? 'heading' : 'info')}, segmentsSpan(shown(path)));
    }
    const classes = ['option', path === view.selected ? 'sel' : '', info.d ? 'disabled' : '', info.c ? 'c-' + info.c : ''];
    const glyph = actionIcon(plainOf(shown(path)));
    // (A files' menu: its key on the right, not before the text)
    const key = inPanel ? keys.get(path) : null;
    const text = inPanel ? withoutKeyPrefix(shown(path)) : shown(path);
    return el('button', {class: classes.join(' ') + (glyph ? ' withicon' : ''), disabled: info.d, 'data-path': path, onclick: () => chooseOption(path)},
      glyph ? icon(glyph) : '', segmentsSpan(text), key ? el('kbd', {}, key) : '');
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

// A sync's tree of what to do with each file (the combined tree): its two replicas, as the flow says them (A first),
// each with its icon and color, so what ⇒ and ⇐ do is plain: ⇒ changes B (to be like A), ⇐ changes A. Neither colored
// (or both alike), A's blue and B's orange, so the two are told apart
const PAIR_COLORS = ['#2563eb', '#ea580c'];
function pairSides(screen) {
  const replicas = screen.replicas;
  if (!replicas || replicas.length !== 2) return null;
  const sides = replicas.map((replica, i) => ({name: replica.name, icon: replica.drive ? 'drive' : (replica.look.icon || 'disk'),
    color: lookColor(replica.look) || PAIR_COLORS[i]}));
  if (sides[0].color === sides[1].color) sides.forEach((side, i) => { side.color = PAIR_COLORS[i]; });
  return sides;
}

function sideName(side) {
  // (Its color as a box around its name, its text as any's: a colored text reads as a link)
  return el('span', {class: 'pairname rtag', style: '--rc:' + side.color}, icon(side.icon), side.name);
}

// A title naming the pair ('A ⇄ B', as the tree's root and the breadcrumbs say it): each name with its icon in its
// color, or null if it doesn't name them
function pairTitle(text, sides) {
  const [a, b] = sides, pair = a.name + ' ⇄ ' + b.name, at = text.indexOf(pair);
  if (at < 0) return null;
  return el('span', {}, text.slice(0, at), sideName(a), ' ⇄ ', sideName(b), text.slice(at + pair.length));
}

// Above the tree: A on the left, B on the right, and between them what each arrow does
function pairLegend(sides) {
  const [a, b] = sides;
  const box = side => el('span', {class: 'pairside', style: '--side:' + side.color}, icon(side.icon), el('span', {}, side.name));
  return el('div', {class: 'pairlegend', title: '⇒ changes ' + b.name + ' to match ' + a.name + '; ⇐ changes ' + a.name + ' to match ' + b.name},
    // (Between the two, the ways files go: ⇒ into B, ⇐ into A, each with how many are marked so, renderPlan())
    box(a), el('span', {class: 'pairarrows', id: 'pairarrows'}), box(b),
    el('span', {class: 'pairways'}, el('b', {}, '⇒'), ' changes ', sideName(b),
      el('span', {class: 'tip'}, ' · '), el('b', {}, '⇐'), ' changes ', sideName(a)));
}

// The tag after a file's name that says it's only in one replica: its badge says so instead
const ONLY_IN_TAG = /\x02grey\x02  only in [^\x01\x02]*/;

// Where a file is: only in A (A's icon and color), only in B, in both but differing, or moved
function groupBadge(group, sides) {
  const [a, b] = sides;
  const badge = (content, color, title) => el('span', {class: 'gbadge', style: '--rc:' + color, title}, content);
  if (group === 'only-a') return badge([icon(a.icon), 'only'], a.color, 'Only in ' + a.name);
  if (group === 'only-b') return badge([icon(b.icon), 'only'], b.color, 'Only in ' + b.name);
  if (group === 'differ') return badge('≠ differ', 'var(--yellow)', 'Both have it, and their versions differ');
  if (group === 'moved') return badge('↔ moved', 'var(--cyan)', 'Both have it, at other paths');
  return '';
}

// What a file's arrow will do (see plan.py's plan_of()): ⇒ changes B, ⇐ changes A: a copy into it, a removal from
// it, its version replaced, or its file moved to the other's path. {kind, color, parts} or null (left as is)
const PLANNED_WORDS = {copy: ['Copy to ', 'green'], remove: ['Remove from ', 'red'], replace: ['Replace in ', 'yellow'], move: ['Move in ', 'cyan']};
// (On a phone, the commands' short names: cp, rm, mv; a replacement's as it is)
const PLANNED_SHORT = {copy: ['cp to ', 'green'], remove: ['rm from ', 'red'], replace: ['Replace in ', 'yellow'], move: ['mv in ', 'cyan']};
const NARROW = window.matchMedia('(max-width: 600px)');
const PLANNED = new Proxy({}, {get: (target, kind) => (NARROW.matches ? PLANNED_SHORT : PLANNED_WORDS)[kind]});
function plannedKind(group, state) {
  if (state !== 'to-b' && state !== 'to-a') return null;
  if (group === 'differ') return 'replace';
  if (group === 'moved') return 'move';
  if (group === 'only-a') return state === 'to-b' ? 'copy' : 'remove';
  if (group === 'only-b') return state === 'to-a' ? 'copy' : 'remove';
  return null;
}

function plannedChip(group, state, sides) {
  const kind = plannedKind(group, state);
  if (!kind) return '';
  const changed = state === 'to-b' ? sides[1] : sides[0];
  return el('span', {class: 'planned c-' + PLANNED[kind][1]}, PLANNED[kind][0], sideName(changed));
}

// The plan so far: {kind|changed side (0 A, 1 B): how many} under path ('.' all of it)
function plannedCounts(path) {
  const counts = new Map();
  const prefix = path === '.' ? '' : path + '/';
  for (const p of view.items) {
    const info = view.info.get(p);
    if (info.t !== 'f' || !p.startsWith(prefix)) continue;
    const kind = plannedKind(info.g, info.st);
    if (!kind) continue;
    const key = kind + '|' + (info.st === 'to-b' ? 1 : 0);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

function plannedParts(counts, sides, long) {
  return [...counts].map(([key, count]) => {
    const [kind, side] = key.split('|');
    const files = count + (long ? (count === 1 ? ' file' : ' files') : '');
    const verb = PLANNED[kind][0].trim().split(' ');
    return el('span', {class: 'c-' + PLANNED[kind][1]}, verb[0] + ' ' + files + ' ' + verb.slice(1).join(' ') + ' ', sideName(sides[+side]));
  });
}

// A folder's row: what's planned under it, in short
function plannedUnder(path, sides) {
  const counts = plannedCounts(path);
  if (!counts.size) return '';
  return el('span', {class: 'planned dirplan'}, plannedParts(counts, sides, false).flatMap((part, i) => i ? [' · ', part] : [part]));
}

// Under the legend: the whole plan, as it is now
// The plan so far, in the arrows between the pair: how many files are marked each way, and all of it in words as
// their tooltip ("Copy 2 files to usb disk · Remove 1 file from work laptop"); a row of its own would take a line
function renderPlan() {
  const arrows = document.getElementById('pairarrows');
  if (!arrows || !view.sides) return;
  const marked = name => view.items.filter(path => { const info = view.info.get(path); return info.t === 'f' && info.st === name; }).length;
  const counts = plannedCounts('.');
  const plan = counts.size ? plannedParts(counts, view.sides, true).map(part => part.textContent.replace(/\s+/g, ' ').trim()).join(' · ') :
    'nothing marked yet: tap a file\'s · to mark it ⇒ or ⇐';
  const way = (mark, name) => {
    const count = marked(name);
    return el('span', {class: 'way' + (count ? ' on' : '')}, mark, count ? el('small', {}, String(count)) : '');
  };
  arrows.title = 'Plan: ' + plan;
  arrows.replaceChildren(way('⇒', 'to-b'), way('⇐', 'to-a'));
}

// A folder's photos side by side (a picker whose files have pictures, see PickerScreen.picture()): a folder holding
// GRID_MIN_PHOTOS of them, most of its files, has a button for it on its row. Each tile is its photo, marked as the tree
// marks it (a tree of states: its mark and badge, a tap the next mark; else its checkbox, a tap checks it); ⤢ shows it
// whole. What's done there is the tree's own: closing it shows it there
const PHOTO_EXTENSIONS = /\.(jpe?g|jfif|png|gif|webp|bmp|tiff?|heic|heif|mp4|mov|m4v|3gp|mkv|webm|avi)$/i;
const GRID_MIN_PHOTOS = 4, GRID_SIZE = 320, WHOLE_SIZE = 1600;

function gridPhotos(dir) {
  const files = (view.children.get(dir) || []).filter(path => (view.info.get(path) || {}).t === 'f' && inTab(path));
  const photos = files.filter(path => PHOTO_EXTENSIONS.test(path));
  return photos.length >= GRID_MIN_PHOTOS && photos.length * 2 >= files.length ? photos : null;
}

function pictureUrl(path, size) {
  return '/api/picture?screen=' + view.screen.id + '&size=' + size + '&path=' + encodeURIComponent(path);
}

function openGrid(dir) {
  view.gridDir = dir;
  view.gridTiles = null;
  placePanel();
  renderGrid();
}

function closeGrid() {
  view.gridDir = null;
  view.gridTiles = null;
  const box = document.getElementById('grid');
  if (box) box.remove();
}

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || !view.gridDir) return;
  event.preventDefault();
  const whole = document.getElementById('gridwhole');
  if (whole) whole.remove(); else closeGrid();
});

function toggleTile(path) {
  const screen = view.screen;
  if (screen.states.length) {
    const next = nextState(path);
    act('select', {path}).then(() => act('state', {paths: [path], name: next}));
  } else if (screen.multi) {
    const on = !view.picked.has(path);
    act('select', {path}).then(() => act('pick', {paths: [path], on}));
  } else act('select', {path});
}

function showWhole(path) {
  act('select', {path});
  const old = document.getElementById('gridwhole');
  if (old) old.remove();
  const box = el('div', {id: 'gridwhole', onclick: () => box.remove()},
    el('img', {src: pictureUrl(path, WHOLE_SIZE), alt: baseName(path)}), el('div', {class: 'caption'}, path + ' · tap to close'));
  document.body.append(box);
}

function renderGrid() {
  if (!view.gridDir) return;
  const screen = view.screen, dir = view.gridDir;
  const photos = gridPhotos(dir);
  if (!photos) { closeGrid(); return; }
  let box = document.getElementById('grid');
  if (!box || !view.gridTiles) {
    // Built once; then only each tile's mark changes (its picture isn't asked for again)
    if (box) box.remove();
    view.gridTiles = new Map();
    const tiles = photos.map(path => {
      const mark = el('span', {class: 'tilemark'});
      const tile = el('div', {class: 'phototile', title: baseName(path), onclick: () => toggleTile(path)},
        el('img', {src: pictureUrl(path, GRID_SIZE), loading: 'lazy', alt: baseName(path)}),
        el('button', {class: 'tilewhole', title: 'Show it whole', onclick: event => { event.stopPropagation(); showWhole(path); }}, '⤢'),
        mark, el('div', {class: 'tilename'}, view.sides && screen.states.length ? groupBadge((view.info.get(path) || {}).g, view.sides) : '',
          el('span', {}, baseName(path))));
      view.gridTiles.set(path, {tile, mark});
      return tile;
    });
    const hint = screen.states.length ? 'Tap a photo for its next mark: ⇒, ⇐, or none' : screen.multi ? 'Tap a photo to check it' : '';
    // All of them at once: checked or not (a files tree), or each mark (a tree of states)
    const all = screen.states.length ? screen.states.map(state => el('button', {class: 'small c-' + state.color,
      onclick: () => act('state', {paths: photos, name: state.name})}, 'All ' + (state.mark.trim() || '·'))) :
      screen.multi ? [el('button', {class: 'small', onclick: () => act('pick', {paths: photos, on: true})}, '✓ Check all'),
        el('button', {class: 'small', onclick: () => act('pick', {paths: photos, on: false})}, 'Uncheck all')] : [];
    box = el('div', {id: 'grid'}, el('div', {class: 'gridhead'},
      el('b', {}, (dir === '.' ? screen.root : dir) + ' · ' + photos.length + ' photos'), el('span', {class: 'note'}, hint), ...all,
      el('button', {class: 'primary', onclick: closeGrid}, 'Back to the tree')), el('div', {class: 'gridtiles'}, tiles));
    document.getElementById('main').append(box);
  }
  for (const [path, {tile, mark}] of view.gridTiles) {
    tile.classList.toggle('sel', path === view.selected);
    if (screen.states.length) {
      const {mark: shown, color} = stateMark(path), info = view.info.get(path) || {};
      const planned = view.sides ? plannedChip(info.g, info.st, view.sides) : '';
      mark.className = 'tilemark c-' + color + (shown.trim() ? ' on' : '');
      mark.replaceChildren(shown.trim() || '', planned);
      tile.classList.toggle('marked', !!shown.trim());
    } else if (screen.multi) {
      const on = view.picked.has(path);
      mark.className = 'tilemark check' + (on ? ' on' : '');
      mark.textContent = on ? '✓' : '';
      tile.classList.toggle('marked', on);
      tile.classList.toggle('checked', on);
    }
  }
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
    // (Tapping it selects its row too, so the buttons below act on what was just touched)
    parts.push(el('button', {class: 'mark c-' + color, title: 'Tap for the next: ⇒, ⇐, or leave it', onclick: event => {
      event.stopPropagation();
      const next = nextState(path);
      act('select', {path: path === '.' ? '' : path}).then(() => act('state', {paths: [path], name: next}));
    }}, mark.trim() || '·'));
    if (view.sides && info.t === 'f') parts.push(groupBadge(info.g, view.sides));
  } else if (screen.multi) {
    const count = info.t === 'f' ? (view.picked.has(path) ? 1 : 0) : pickedUnder(path);
    const total = info.t === 'f' ? 1 : (view.fileCounts.get(path) || 0);
    // (Checking a row selects it too: what was just touched is what the details show)
    const box = el('input', {type: 'checkbox', onclick: event => {
      event.stopPropagation();
      const on = event.target.checked;
      act('select', {path: path === '.' ? '' : path}).then(() => act('pick', {paths: [path], on}));
    }});
    box.checked = total > 0 && count === total;
    box.indeterminate = count > 0 && count < total;
    parts.push(box);
  }
  let text = flat && path !== '.' ? path : shown(path);
  // (The root of a sync's tree: its two replicas, each with its icon in its color)
  if (path === '.' && view.sides) text = pairTitle(plainOf(text), view.sides) || text;
  // (Where a file is, said by its badge: not again in grey after its name)
  if (view.sides && screen.states.length && info.t === 'f') text = text.replace(ONLY_IN_TAG, '');
  const name = el('span', {class: 'name' + (isDir ? ' dir' : '') + (info.c ? ' c-' + info.c : '')}, typeof text === 'string' ? segmentsSpan(text) : text);
  // A folder of photos: its grid
  const photos = isDir && !flat && screen.hasPictures ? gridPhotos(path) : null;
  if (photos) name.append(el('button', {class: 'gridbutton', title: 'See its photos side by side, and ' + (screen.states.length ? 'mark' : 'check') + ' them there',
    onclick: event => { event.stopPropagation(); openGrid(path); }}, icon('grid'), 'Grid · ' + photos.length + ' photos'));
  // What's planned for it, on its right, or under its name where there's no room (a phone); the root's is the plan
  // line above the tree
  const planned = view.sides && screen.states.length && path !== '.' ?
    (info.t === 'f' ? plannedChip(info.g, info.st, view.sides) : plannedUnder(path, view.sides)) : '';
  parts.push(planned ? el('span', {class: 'namewrap'}, name, planned) : name);
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
  // (Only blank lines, as a folder's may be: no box for them)
  const lines = (found.lines || []).some(line => plainOf(line).trim()) ? found.lines : [];
  const content = [];
  // (Which node it's of: the selected one, the row tapped, not the ones checked)
  if (lines.length || found.image) {
    content.push(el('div', {class: 'previewhead'}, 'Selected: ', el('span', {class: 'target selected'}, view.selected ? baseName(view.selected) : screen.root),
      el('button', {class: 'maxbutton', title: view.previewMax ? 'Back to its place (Esc)' : 'Fill the screen with it',
        'aria-pressed': String(!!view.previewMax), onclick: () => maximizePreview(!view.previewMax)}, view.previewMax ? '⤡' : '⤢')));
  }
  if (lines.length) content.push(el('pre', {}, lines.map(line => [plainOf(line).startsWith('Diff: ') ? diffToggle(line) : previewLine(line), '\n'])));
  if (found.image) { const canvas = pictureCanvas(found.image); if (canvas) content.push(canvas); }
  box.replaceChildren(content.length ? el('div', {class: 'preview'}, content) : '');
  box.classList.toggle('max', !!view.previewMax && content.length > 0);
  colorNames(box);
}

// The selection's details filling the screen (under the top bar), to read a long diff, or back in their place; it
// stays so as the selection moves, until it's put back (its button, or Esc)
function maximizePreview(on) {
  view.previewMax = on;
  placePanel();
  view.previewVersion = -1;
  loadPreview();
}

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && view.previewMax && document.getElementById('main').dataset.shows !== 'panel') {
    event.preventDefault();
    maximizePreview(false);
  }
});

function plainOf(line) { return styledParts(line).map(part => part.text).join(''); }

// A diff's title ('Diff: [changes] · a · b  (Ctrl-T: next)', see versions.title_line()) as a row of buttons, one a
// view, the one shown on: a tap presses Ctrl-T as many times as it takes to get there
function diffToggle(line) {
  const labels = plainOf(line).slice('Diff: '.length).split('  (')[0].split(' · ');
  const shown = labels.findIndex(label => label.startsWith('['));
  // (Merging the two: g, on this file, the selected one whose diff this is, whatever's checked)
  const merge = view.screen.keys.some(key => key.name === 'g') ? el('button', {class: 'mergebutton',
    onclick: () => act('press', {key: 'g'})}, icon('merge'), 'Merge…') : '';
  return el('span', {class: 'difftoggle'}, el('b', {}, 'Diff'), merge, labels.map((label, i) => {
    const name = label.replace(/^\[(.*)\]$/, '$1');
    return el('button', {class: i === shown ? 'on' : '', onclick: async () => {
      for (let n = (i - shown + labels.length) % labels.length; n > 0; n--) await act('press', {key: '\x14'});
    }}, i === shown ? name : name);
  }));
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
const NO_BUTTON_KEYS = new Set([':', '#', 'Ctrl-T', 'g', 'Ctrl-Q']);  // (Ctrl-Q: the combined tree's Back, keeping its marks, quitScreen())  // (g: the diff's Merge..., diffToggle())  // (Ctrl-T: the diff's views, in its title, diffToggle())
// Keys whose buttons are shown only where they do something: exploring a zip on one, a diff's views on a diff
const KEY_APPLIES = {
  'e': () => /\.zip$/i.test(view.selected || ''),
};
const applies = key => !NO_BUTTON_KEYS.has(key.name) && (!KEY_APPLIES[key.name] || KEY_APPLIES[key.name]());

// The bottom bar, in sections: going back and the main action (Enter's, named for what it's on); what acts
// on the selection; on the side tree's; and Misc (the picker's own keys: the pictures)
// Whether the tree's Enter opens a menu of what to do with its files (a sync's, an inbox's): its panel's shown at
// once, before the menu comes (openingPanel()), so the tap shows something, however slow the network
function opensMenu(screen) {
  const enter = screen.hints.find(([key]) => key === 'Enter');
  return screen.mode !== 'list' && !screen.states.length && !!enter && /what to do/i.test(enter[1]);
}

function openingPanel() {
  view.menuAsked = true;
  const main = document.getElementById('main');
  if (main.dataset.shows !== 'tree' && main.dataset.shows !== 'dir') return;
  showPanel(main, [el('p', {class: 'note'}, 'Opening', el('span', {class: 'dots'}))]);
}

// A sync's file tree (what one replica lacks, or has otherwise): its Enter's menu is what to do with the files
function isSyncFilesTree(screen) {
  return screen.mode === 'tree' && screen.multi && !screen.states.length && !!screen.side && screen.side.enterPicks &&
    /(^|> )Sync /.test(screen.crumbs || '');
}

function actionsOpen() {
  try { return localStorage.getItem('dirdelta_actions') === 'open'; } catch (error) { return false; }
}

function setActionsOpen(open) { kept('dirdelta_actions', open ? 'open' : ''); }

// The menu's actions as buttons, each choosing its option at once (by its key, see optionKeys()): the menu opened
// and that option chosen, not shown; what it asks then (a confirmation) shown as ever. One greyed out there shows
// the menu, which says why
const QUICK_ACTIONS = [
  ['copy', '>', screen => 'Copy to ' + screen.side.root],
  ['swap', '<', screen => 'Replace with ' + screen.side.root + "'s"],
  ['merge', 'g', () => 'Merge the two versions…'],
  ['trash', 'd', () => 'Remove'],
  ['pencil', 'cc', () => 'Rename…'],
  ['pencil', 'm', () => 'Rename the match there'],
  ['pencil', 'M', () => 'Rename to the match'],
  ['ai', 'a', () => 'Ask AI'],
  ['open', 'Ctrl-X', () => 'Open'],
  ['refresh', 'Ctrl-R', () => 'Read anew'],
  ['zip', 'e', () => 'Explore the zip'],
];

function quickActions(screen, selected) {
  return [el('div', {class: 'acton'}, view.picked.size ? ['These act on ', targetChip(screen, selected)] : 'These act on the checked files: check some first')].concat(
    QUICK_ACTIONS.filter(([, key]) => key !== 'e' || /\.zip$/i.test(view.selected || '')).map(([glyph, key, text]) =>
      el('button', {class: 'quick', disabled: !view.picked.size, onclick: () => { view.pendingKey = key; view.menuAsked = true; act('enter'); }},
        icon(glyph), text(screen), el('small', {class: 'keyname'}, key))));
}

// What an action acts on, in its color: the checked files (green, as their checkboxes); a single tree's (one node
// chosen, no checkboxes) the selected one (blue, as its row and the details' header)
function targetChip(screen, selected) {
  if (screen.multi && view.picked.size) return el('span', {class: 'target checked'}, '✓ ' + view.picked.size + ' checked');
  return el('span', {class: 'target selected'}, selected);
}

// With files checked: how many, and unchecking them all (checks left over are how the wrong files get acted on)
function checkedLine(screen) {
  if (!screen.multi || screen.states.length || !view.picked.size) return '';
  return el('div', {class: 'checkedline'}, targetChip(screen, ''),
    el('button', {class: 'tiny', onclick: () => act('pick', {paths: ['.'], on: false})}, '✕ Uncheck all'));
}

function renderPickerActions() {
  const screen = view.screen;
  const main = [];
  // (Back is first in the row above, of where it is: setTop())
  const selected = view.selected ? baseName(view.selected) : screen.root;
  if (screen.mode !== 'list') {
    const enter = screen.hints.find(([key]) => key === 'Enter');
    const what = enter ? capitalized(enter[1]) : 'Choose';
    // (Named for what it acts on, in that one's color: the checked files, green, or else the selected one, blue)
    let label = [what + ' ', screen.multi ? '' : targetChip(screen, selected)];
    // (A tree of states: what Enter does next is showing the plan of what's marked, to confirm)
    const marked = screen.states.length ? markedCount() : 0;
    if (screen.states.length) label = marked ? 'Review plan (' + marked + ')' : 'Nothing marked yet';
    // (With nothing checked it's off: what it acts on is the checked files, an empty set then, never the selection,
    // which the terminal's Enter takes then, but which surprised: the whole tree, with the top selected)
    else if (screen.multi) label = view.picked.size ? [what + ' with ', targetChip(screen, selected)] : 'Check files first';
    const enterButton = el('button', {class: 'primary', disabled: screen.multi && (screen.states.length ? !marked : !view.picked.size),
      onclick: () => { if (opensMenu(screen)) openingPanel(); act('enter'); }}, label);
    // (A sync's file tree: ▾ beside it shows its menu's actions as buttons, see quickActions())
    main.push(isSyncFilesTree(screen) || screen.states.length ? el('span', {class: 'splitbutton'}, enterButton,
      el('button', {class: 'primary more' + (actionsOpen() ? ' on' : ''), title: actionsOpen() ? 'Hide the actions' : 'Show all the actions',
        'aria-expanded': String(actionsOpen()), onclick: () => { setActionsOpen(!actionsOpen()); renderPickerActions(); }}, actionsOpen() ? '▴' : '▾')) :
      enterButton);
  }
  if (screen.hints.length || screen.help.length) {
    main.push(el('button', {class: 'help', title: 'What the keys do', onclick: () => { view.showHelp = !view.showHelp; renderHelp(); }}, '?'));
  }
  const keyButton = (key, onclick) => el('button', {title: key.text, onclick},
    key.text ? short(capitalized(key.text)) : key.name, el('small', {class: 'keyname'}, key.name));
  const onSelection = [], general = [], marks = [];
  if (screen.states.length && view.selected !== null) {
    for (const state of screen.states) {
      marks.push(el('button', {class: 'c-' + state.color, onclick: () => act('state', {paths: [view.selected || '.'], name: state.name})},
        stateButtonLabel(state, view.selected || '.')));
    }
  }
  for (const key of screen.keys.filter(applies)) {
    (GENERAL_KEYS.has(key.name) ? general : onSelection).push(keyButton(key, () => act('press', {key: key.key})));
  }
  // (A tree of states: its marks for the selection always shown; its other actions (the AI's, the diff, the
  // pictures) under ▾, as a files tree's, see actionsOpen())
  if (screen.states.length) {
    if (actionsOpen()) onSelection.push(...general.splice(0));
    else { onSelection.length = 0; general.length = 0; }
    // (A sync's tree: in one short row, markRow(); first in the bottom bar's part about the selection, under its name)
    if (view.sides) onSelection.unshift(markRow(screen));
    else onSelection.unshift(...marks);
  }
  const side = [];
  if (screen.side && screen.side.enterPicks) {
    side.push(el('button', {class: 'primary', disabled: !view.sideSelected, onclick: () => act('enter', {side: true})},
      'Into ' + (view.sideSelected || screen.side.root)));
    for (const key of screen.side.keys.filter(key => !NO_BUTTON_KEYS.has(key.name))) side.push(keyButton(key, () => act('enter', {side: true, key: key.key})));
  }
  const section = (title, buttons, extra) => buttons.length ?
    el('div', {class: 'actsec' + (extra ? ' ' + extra : '')}, title ? el('div', {class: 'seclabel'}, title) : '', buttons) : '';
  document.getElementById('actions').replaceChildren(checkedLine(screen), section('', main, 'main'),
    isSyncFilesTree(screen) && actionsOpen() ? section('', quickActions(screen, selected), 'quick') : '',
    section(screen.mode === 'list' ? '' : 'On ' + selected, onSelection),
    section(screen.side ? 'In ' + screen.side.root : '', side), section('Misc', general));
}

// The selection's way in a sync's tree, in one short row (it fits a phone's 360px), in the bottom bar's part about the
// selection, which names it: · Leave, ⇒ B, ⇐ A, each saying all of what it does as its tooltip (stateButtonLabel())
function markRow(screen) {
  const path = view.selected || '.';
  const buttons = screen.states.map(state => {
    const changed = state.name === 'to-b' ? view.sides[1] : state.name === 'to-a' ? view.sides[0] : null;
    const full = el('span', {}, stateButtonLabel(state, path));
    // (The replica by its name, in plain text, and its color as the button's edge: a box in a button doesn't shrink)
    return el('button', {class: 'small' + (changed ? ' toward' : ''), style: changed ? '--rc:' + changed.color : '',
      title: full.textContent.replace(/\s+/g, ' ').trim(), onclick: () => act('state', {paths: [path], name: state.name})},
      (state.mark.trim() || '·') + ' ', changed ? changed.name : el('span', {class: 'leaveword'}, 'Leave'));
  });
  return el('div', {class: 'markrow'}, ...buttons);
}

// How many files are marked (in a state but the first, "leave as is")
function markedCount() {
  const first = view.screen.states[0].name;
  return view.items.filter(path => { const info = view.info.get(path); return info.t === 'f' && info.st && info.st !== first; }).length;
}

// A mark's button, named for what it does to the selection: on a file, what its arrow will do ("⇒ Copy to D");
// on a folder (or the whole tree), which replica it changes and how many files each way ("⇐ Make C like D: copy 3 ·
// remove 4"); the first, "Leave as is"
function stateButtonLabel(state, path) {
  const mark = (state.mark.trim() || '·') + ' ';
  if (!view.sides) return [mark, el('small', {}, state.name)];
  if (state.name === view.screen.states[0].name) return [mark, 'Leave as is'];
  const changed = state.name === 'to-b' ? view.sides[1] : view.sides[0], other = state.name === 'to-b' ? view.sides[0] : view.sides[1];
  const info = view.info.get(path) || {};
  if (info.t === 'f') {
    const kind = plannedKind(info.g, state.name);
    return kind ? [mark, el('span', {class: 'c-' + PLANNED[kind][1]}, PLANNED[kind][0]), sideName(changed)] : [mark, 'Change ', sideName(changed)];
  }
  const prefix = path === '.' ? '' : path + '/', counts = new Map();
  for (const p of view.items) {
    const file = view.info.get(p);
    if (file.t !== 'f' || !p.startsWith(prefix)) continue;
    const kind = plannedKind(file.g, state.name);
    if (kind) counts.set(kind, (counts.get(kind) || 0) + 1);
  }
  const parts = [...counts].map(([kind, count]) => el('span', {class: 'c-' + PLANNED[kind][1]},
    PLANNED[kind][0].trim().split(' ')[0].toLowerCase() + ' ' + count));
  return [mark, path === '.' ? 'All: make ' : 'Make ', sideName(changed), ' like ', sideName(other),
    parts.length ? ': ' : '', ...parts.flatMap((part, i) => i ? [' · ', part] : [part])];
}

function renderHelp() {
  const box = document.getElementById('help');
  if (!box) return;
  const screen = view.screen;
  // (A tree of states: what its marks mean first, the keys after; the keys hidden on a touch screen, which has none)
  const keys = isTouch() ? [] : screen.hints.map(([key, text]) => el('div', {}, key.padEnd(10) + text));
  const lines = screen.help.map(line => el('div', {}, styledSpan(line)));
  box.replaceChildren(view.showHelp ? el('div', {class: 'preview'}, screen.states.length ? [lines, keys] : [keys, lines]) : '');
}

function isTouch() { return window.matchMedia('(hover: none)').matches; }

function capitalized(text) { return text ? text[0].toUpperCase() + text.slice(1) : text; }

// A key's description on a button (the whole of it is its title): to its first ':' or '(', all of it (it wraps)
function short(text) {
  return text.split(/[:(]/)[0].trim();
}

// A messages screen

// A merge of two versions of a text file (web/merging.py): each block where they differ shown with both sides, and
// which to keep (one, the other, both in either order); the result, built from those choices (a block not chosen yet
// keeps both, between conflict marks), and edited at will; the AI's merge to start from; Save writes it to both
const MERGE_MARKS = ['<<<<<<< ', '=======', '>>>>>>> '];
const MERGE_CHOICES = [['a', 'This one'], ['b', 'That one'], ['ab', 'Both'], ['ba', 'Both, that first']];

function renderMerge(screen, isNew) {
  setTop(screen.crumbs || screen.title, screen.labels);
  if (isNew) {
    placePreview(false);
    document.body.style.minHeight = '';
    view.merge = {choices: screen.blocks.map(() => null), edited: false, aiShown: null};
    const main = document.getElementById('main');
    main.dataset.shows = 'merge';
    const [nameA, nameB] = screen.names;
    const blocks = screen.blocks.map((block, index) => block.same ? sameBlock(block.same) : differBlock(block, index, nameA, nameB));
    const result = el('textarea', {id: 'mergeresult', spellcheck: 'false', 'aria-label': 'The merged text',
      oninput: () => { view.merge.edited = true; mergeStatus(screen); }});
    main.replaceChildren(
      el('div', {class: 'mergehead'}, el('div', {class: 'note'}, 'Where the two versions differ, choose what to keep: ',
        el('span', {class: 'side-a'}, nameA), ' or ', el('span', {class: 'side-b'}, nameB), ', or both. Then check the result below, edit it if you like, and save it to both.'),
        screen.canSuggest ? el('div', {id: 'mergeai'}) : ''),
      el('div', {class: 'mergeblocks'}, blocks),
      el('div', {class: 'section-title'}, 'The result'),
      el('div', {class: 'note', id: 'mergeresultnote'}),
      result);
    buildMergeResult(screen);
  }
  renderMergeAI(screen);
  mergeStatus(screen);
  document.getElementById('actions').replaceChildren(el('div', {class: 'actsec main'},
    el('button', {onclick: () => act('merge', {merge: {action: 'cancel'}})}, 'Cancel'),
    el('button', {class: 'primary', onclick: () => act('merge', {merge: {action: 'save', text: document.getElementById('mergeresult').value}})},
      'Save the merge to both')));
}

function sameBlock(lines) {
  // (Only empty lines alike: said, rather than a box with nothing in it)
  if (lines.every(line => !line.trim())) return el('div', {class: 'mergesame blank'}, lines.length + ' empty line' + (lines.length === 1 ? '' : 's') + ' alike');
  // (Long alike stretches folded: their first and last lines shown, the rest on a tap)
  const shown = lines.length <= 6 ? lines : lines.slice(0, 2).concat(['…'], lines.slice(-2));
  const box = el('pre', {class: 'mergesame'}, shown.join('\n'));
  if (lines.length > 6) {
    box.title = 'Show all ' + lines.length + ' lines';
    box.classList.add('folded');
    box.onclick = () => { box.textContent = lines.join('\n'); box.classList.remove('folded'); box.onclick = null; };
  }
  return box;
}

function differBlock(block, index, nameA, nameB) {
  const side = (lines, cls, name) => el('div', {class: 'mergeside ' + cls}, el('div', {class: 'mergename'}, name),
    el('pre', {}, lines.length ? lines.join('\n') : '(nothing here)'));
  const choices = el('div', {class: 'mergechoices'}, MERGE_CHOICES.map(([key, text]) =>
    el('button', {class: 'small', 'data-key': key, onclick: () => chooseBlock(index, key)},
      text === 'This one' ? nameA : text === 'That one' ? nameB : key === 'ab' ? 'Both' : 'Both, ' + nameB + ' first')));
  return el('div', {class: 'mergediff', id: 'mergeblock' + index}, el('div', {class: 'mergesides'}, side(block.a, 'side-a', nameA), side(block.b, 'side-b', nameB)), choices);
}

function chooseBlock(index, key) {
  const screen = view.screen;
  // (Your edits to the result give way to it, rebuilt from the choices: the note says so)
  view.merge.dropped = view.merge.edited;
  view.merge.choices[index] = key;
  view.merge.edited = false;
  document.querySelectorAll('#mergeblock' + index + ' .mergechoices button').forEach(button =>
    button.classList.toggle('on', button.dataset.key === key));
  buildMergeResult(screen);
}

function buildMergeResult(screen) {
  const [nameA, nameB] = screen.names, lines = [];
  screen.blocks.forEach((block, index) => {
    if (block.same) { lines.push(...block.same); return; }
    const key = view.merge.choices[index];
    if (key === 'a') lines.push(...block.a);
    else if (key === 'b') lines.push(...block.b);
    else if (key === 'ab') lines.push(...block.a, ...block.b);
    else if (key === 'ba') lines.push(...block.b, ...block.a);
    else lines.push(MERGE_MARKS[0] + nameA, ...block.a, MERGE_MARKS[1], ...block.b, MERGE_MARKS[2] + nameB);
  });
  document.getElementById('mergeresult').value = lines.join('\n');
  mergeStatus(screen);
}

function mergeStatus(screen) {
  const total = screen.blocks.filter(block => !block.same).length;
  const chosen = view.merge.choices.filter(Boolean).length;
  const text = document.getElementById('mergeresult').value;
  const marked = text.split('\n').some(line => line.startsWith(MERGE_MARKS[0]) || line === MERGE_MARKS[1] || line.startsWith(MERGE_MARKS[2]));
  const note = document.getElementById('mergeresultnote');
  if (note) note.textContent = (view.merge.edited ? 'Edited by you. ' : view.merge.dropped ? 'Rebuilt from your choices (your edits to it dropped). ' : '') + (marked ? 'Blocks not chosen yet are in it with both versions, between <<<<<<< and >>>>>>> marks.' : 'No conflict marks left.');
  document.getElementById('status').replaceChildren(chosen + ' of ' + total + ' differing block' + (total === 1 ? '' : 's') + ' chosen' +
    (view.merge.edited ? '; the result edited' : ''));
}

function renderMergeAI(screen) {
  const box = document.getElementById('mergeai');
  if (!box) return;
  const ai = screen.ai;
  // (What the user tells the AI of the merge, kept as it's typed, across the box's redraws)
  const askBox = buttonText => {
    const context = el('textarea', {class: 'mergecontext', rows: 2, placeholder: "Anything the AI should know (optional): e.g. keep the newer prices; the Drive one's order is right",
      oninput: event => { view.merge.context = event.target.value; }});
    context.value = view.merge.context || '';
    return [context, el('button', {onclick: () => act('merge', {merge: {action: 'suggest', context: view.merge.context || ''}})}, icon('ai'), ' ' + buttonText)];
  };
  if (!ai) {
    box.replaceChildren(...askBox('Ask AI to merge them'));
    return;
  }
  if (ai.status === 'asking') { box.replaceChildren(el('div', {class: 'note'}, 'Claude is merging them', el('span', {class: 'dots'}))); return; }
  if (ai.status === 'failed') {
    box.replaceChildren(el('div', {class: 'note c-red'}, "The AI couldn't merge them: " + ai.error), ...askBox('Ask again'));
    return;
  }
  const use = () => {
    view.merge.dropped = false;
    document.getElementById('mergeresult').value = ai.lines.join('\n');
    view.merge.edited = true;
    view.merge.aiShown = true;
    mergeStatus(screen);
    document.getElementById('mergeresult').scrollIntoView({block: 'start', behavior: 'smooth'});
  };
  box.replaceChildren(el('div', {class: 'mergeainotes'}, el('b', {}, "The AI's merge"), ' (' + ai.lines.length + ' lines): ', ai.notes || ''),
    el('button', {class: 'small primary', onclick: use}, 'Put it in the result, to review'), ...askBox('Ask again, with this'));
}

function renderMessages(screen, isNew) {
  setTop(screen.crumbs || screen.title, screen.labels);
  const main = document.getElementById('main');
  if (isNew) placePreview(false);
  if (isNew) { main.dataset.shows = 'messages'; document.body.style.minHeight = ''; main.replaceChildren(el('div', {class: 'lines', id: 'lines'}), el('div', {id: 'ask'})); }
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
  colorNames(main);
  if (!screen.asking) window.scrollTo(0, document.body.scrollHeight);
}

// Nothing shown: a flow ended (what it printed last), or none ran

function renderHome() {
  setTop('Running', []);
  const log = view.log.map(([text, color]) => el('div', {class: color ? 'c-' + color : ''}, segmentsSpan(text)));
  placePreview(false);
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

// (The status line's marks where a replica's hashing goes on, made dots once it's drawn: see shortStatus())
function markHashingNow(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const found = [];
  while (walker.nextNode()) if (walker.currentNode.data.includes(HASHING_NOW)) found.push(walker.currentNode);
  for (const node of found) {
    const [before, after] = node.data.split(HASHING_NOW);
    node.replaceWith(before, waitingDots(), after);
  }
}

// The breadcrumbs (under the tabs: a run is a page of its tab's): the tab first (a sync's Replicas, a sort's
// Inboxes), then where the run is, without dirdelta's own name (the top bar has it)
function setTop(title, labels) {
  const rest = (title || '').replace(/^dirdelta(?: > |$)/, '');
  const tab = runningTab === 'inboxes' ? ['/inboxes', 'Inboxes'] : ['/replicas', 'Replicas'];
  // (A sync's tree: its two replicas named with their icons and colors)
  const where = view.sides && view.screen && view.screen.kind === 'picker' && pairTitle(plainOf(rest), view.sides);
  // A picker's way back (its q: Back, or the start menu's Quit), first in the row of where it is: leaving the screen
  // is the page's, not one of the bottom bar's actions on what's selected
  const screen = view.screen && view.screen.kind === 'picker' ? view.screen : null;
  const back = screen && screen.hints.find(([key]) => key === 'q');
  document.getElementById('crumbs').replaceChildren(
    screen ? el('button', {class: 'crumbback', title: 'Back to where you were (the browser\'s Back too)', onclick: goBack},
      '\u2190 ' + (back ? capitalized(back[1]) : 'Back')) : '',
    el('a', {href: tab[0]}, tab[1]),
    rest ? el('span', {id: 'where'}, ' > ', where || segmentsSpan(rest)) : el('span', {id: 'where'}));
  document.getElementById('labels').replaceChildren(...(labels || []).map(labelChip));
  document.title = (title || 'dirdelta').split(' > ').pop();
}

// The bottom bar's height: at most a third of the screen (CSS's --bar-h), or as tall as it's dragged by its top edge
// (a double-click puts it back), kept for this browser
const BAR_KEY = 'dirdelta_bar_height';
let barHeight = 0;
function setBarHeight(px) {
  barHeight = px;
  const bottom = document.getElementById('bottom');
  if (px) document.documentElement.style.setProperty('--bar-h', px + 'px');
  else document.documentElement.style.removeProperty('--bar-h');
  bottom.classList.toggle('sized', !!px);
  placePanel();
}

function barHandle() {
  const bottom = document.getElementById('bottom');
  const handle = el('div', {class: 'barhandle', title: 'Drag to make this bar taller or shorter (double-click: back to its size)'});
  bottom.prepend(handle);
  try {
    const kept = Number(localStorage.getItem(BAR_KEY));
    if (kept) setBarHeight(Math.min(kept, Math.round(innerHeight * 0.85)));
  } catch (error) { /* (its own size) */ }
  handle.addEventListener('pointerdown', event => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    handle.classList.add('dragging');
    const move = moved => setBarHeight(Math.round(Math.max(90, Math.min(innerHeight * 0.85, innerHeight - moved.clientY))));
    const up = () => {
      handle.classList.remove('dragging');
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', up);
      try { localStorage.setItem(BAR_KEY, String(barHeight)); } catch (error) { /* (not kept) */ }
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  });
  handle.addEventListener('dblclick', () => {
    setBarHeight(0);
    try { localStorage.removeItem(BAR_KEY); } catch (error) { /* (nothing kept) */ }
  });
}

barHandle();
tabBar('run');
poll();
