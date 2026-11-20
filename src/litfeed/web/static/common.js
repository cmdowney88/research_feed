// Shared helpers for the digest and project pages. Pages embed their data as JSON in
// <script id="data" type="application/json">; `data.context` is {digest: name} or
// {project: slug} and is sent with every API request.

const data = JSON.parse(document.getElementById('data').textContent);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === 'class') node.className = value; else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child == null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

async function postJSON(url, body) {
  const response = await fetch(url, {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({...data.context, ...body})});
  let result = {};
  try { result = await response.json(); } catch (error) { result = {}; }
  return {ok: response.ok, result};
}

// Inline Markdown: **bold**, and (when `cite` maps citation numbers to paper IDs) [3] or
// [12, 17] citations rendered as links to the paper cards.
function inline(text, cite) {
  const span = el('span');
  const pattern = /(\*\*[^*]+\*\*|\[\d+(?:\s*,\s*\d+)*\])/;
  for (const part of text.split(pattern)) {
    if (!part) continue;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      span.append(el('strong', {}, inline(part.slice(2, -2), cite)));
    } else if (cite && /^\[\d+(?:\s*,\s*\d+)*\]$/.test(part)) {
      const numbers = part.slice(1, -1).split(',').map(value => value.trim());
      span.append('[');
      numbers.forEach((number, index) => {
        if (index) span.append(', ');
        const paperId = cite[number];
        span.append(paperId
          ? el('a', {href: '#p-' + paperId, class: 'cite', 'data-paper': paperId}, number)
          : number);
      });
      span.append(']');
    } else {
      span.append(part);
    }
  }
  return span;
}

// Block Markdown: headings (## → h<2+offset>), "- " and "1. " lists, paragraphs.
function renderMarkdown(text, {headingOffset = 0, cite = null} = {}) {
  const body = el('div');
  let list = null;
  for (const line of text.split('\n')) {
    const heading = line.match(/^(#{2,4}) (.*)$/);
    const bullet = line.match(/^\s*- (.*)$/);
    const numbered = line.match(/^\s*\d+\. (.*)$/);
    if (heading) {
      list = null;
      body.append(el('h' + Math.min(6, heading[1].length + headingOffset), {},
                     inline(heading[2], cite)));
    } else if (bullet || numbered) {
      const tag = bullet ? 'ul' : 'ol';
      if (!list || list.tagName.toLowerCase() !== tag) { list = el(tag); body.append(list); }
      list.append(el('li', {}, inline((bullet || numbered)[1], cite)));
    } else if (line.trim()) {
      list = null;
      body.append(el('p', {}, inline(line, cite)));
    } else {
      list = null;
    }
  }
  return body;
}

function noteElement(note, open) {
  const body = renderMarkdown(note, {headingOffset: 2});
  body.className = 'note-body';
  return el('details', {class: 'note', ...(open ? {open: ''} : {})},
            el('summary', {}, 'Reading note'), body);
}

function metaLine(paper, extra) {
  const links = [el('a', {href: 'https://www.semanticscholar.org/paper/' + paper.paperId,
                          target: '_blank'}, 'S2')];
  const arxiv = (paper.externalIds || {}).ArXiv;
  if (arxiv) links.push(' · ', el('a', {href: 'https://arxiv.org/abs/' + arxiv,
                                        target: '_blank'}, 'arXiv'));
  const authors = (paper.authors || []).slice(0, 5).join(', ') +
                  ((paper.authors || []).length > 5 ? ', et al.' : '');
  const parts = [authors, paper.venue, String(paper.publicationDate || paper.year || 'n.d.'),
                 ...(extra || [])].filter(Boolean);
  return el('div', {class: 'meta'}, parts.join(' · '), ' · ', ...links);
}

// ☆ Save button + collection dropdown (see litfeed.library). Returns the elements to show
// and `saveIfNeeded()`, which saves to the selected collection unless already saved.
function saveControls(paper) {
  const saved = data.library[paper.paperId];
  const star = el('button', {class: 'star' + (saved ? ' on' : '')}, saved ? '★ Saved' : '☆ Save');
  const collection = el('select', {'aria-label': 'library collection'});
  for (const name of data.collections) {
    collection.append(el('option', {value: name}, name + '.bib'));
  }
  collection.value = saved ? saved.collection : paper.defaultCollection;
  const status = el('span', {class: 'muted'}, saved ? (saved.pdf ? 'with PDF' : 'no PDF found') : '');
  async function request(target) {
    status.textContent = 'working…';
    const {ok, result} = await postJSON('/api/save', {paperId: paper.paperId, collection: target});
    if (!ok) { status.textContent = result.error || 'error'; return; }
    data.library[paper.paperId] = result.row || undefined;
    star.classList.toggle('on', Boolean(result.row));
    star.textContent = result.row ? '★ Saved' : '☆ Save';
    status.textContent = result.row
      ? `${result.row.key} · ${result.row.pdf ? 'with PDF' : 'no PDF found'}` : '';
  }
  star.addEventListener('click', () =>
    request(data.library[paper.paperId] ? null : collection.value));
  collection.addEventListener('change', () => {
    if (data.library[paper.paperId]) request(collection.value);
  });
  async function saveIfNeeded() {
    if (!data.library[paper.paperId]) await request(collection.value);
  }
  return {elements: [star, collection, status], saveIfNeeded};
}

// Per-browser preference stored in localStorage; storage can be unavailable (private
// windows, blocked site data), so every access falls back to the default.
function loadPreference(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value);
  } catch (error) {
    return fallback;
  }
}

function storePreference(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) { /* ignore */ }
}

// Open any collapsed sections containing the target card, scroll to it, and flash it.
function revealCard(paperId) {
  const card = document.getElementById('p-' + paperId);
  if (!card) return;
  for (let node = card.parentElement; node; node = node.parentElement) {
    if (node.tagName && node.tagName.toLowerCase() === 'details') node.open = true;
  }
  card.scrollIntoView({behavior: 'smooth', block: 'start'});
  card.classList.add('highlight');
  setTimeout(() => card.classList.remove('highlight'), 1500);
}

function bindExpandCollapse() {
  const expand = document.getElementById('expand');
  const collapse = document.getElementById('collapse');
  if (expand) expand.onclick = () =>
    document.querySelectorAll('details.tier').forEach(node => node.open = true);
  if (collapse) collapse.onclick = () =>
    document.querySelectorAll('details.tier').forEach(node => node.open = false);
}
