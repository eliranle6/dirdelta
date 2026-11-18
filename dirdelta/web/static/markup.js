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

function labelChip([text, color]) {
  return el('span', {class: 'label b-' + (COLORS.includes(color) ? color : 'grey')}, text);
}

// The pages' tabs, the one shown marked (active: 'home', 'photos', 'sync', 'run'), and Running while a
// flow runs (a sync, a sort, the start menu: its screens are on /run), checked every few seconds
const TABS = [['home', '/', 'Home'], ['photos', '/import', 'Photos'], ['sync', '/sync', 'Sync']];

function tabBar(active) {
  const nav = document.getElementById('tabs');
  if (!nav) return;
  const draw = running => nav.replaceChildren(...TABS.map(([key, href, text]) =>
    el('a', {href, class: key === active ? 'on' : ''}, text)),
    running || active === 'run' ? el('a', {href: '/run', class: (running ? 'running' : 'idle') + (active === 'run' ? ' on' : '')},
      running ? el('span', {class: 'dot'}) : '', 'Running') : '');
  const check = async () => {
    try {
      const answer = await (await fetch('/api/running')).json();
      draw(answer.running);
    } catch (error) { /* (the next check) */ }
    setTimeout(check, 5000);
  };
  draw(false);
  check();
}
