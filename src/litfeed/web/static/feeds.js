// Feeds page: inspect and edit each feed's seeds (add by identifier, remove, save to the
// library), flag authors, and create a feed from seeds gathered from four sources.

const staged = new Map();  // paperId → seed row for the new feed
let stagedView = null;

function s2Link(paperId, text) {
  return el('a', {href: 'https://www.semanticscholar.org/paper/' + paperId, target: '_blank'}, text);
}

function button(text, onClick, attrs) {
  const node = el('button', {type: 'button', ...(attrs || {})}, text);
  node.addEventListener('click', onClick);
  return node;
}

// Textarea of identifiers → S2 lookup → checklist of matches → onConfirm(rows).
// `excluded(paperId)` returns a reason a paper should start unticked (e.g. already a seed).
function resolveWidget(confirmLabel, onConfirm, excluded) {
  const textarea = el('textarea', {rows: '3', placeholder:
    'one per line: S2 / arXiv / DOI / ACL Anthology links or IDs, or paper titles'});
  const status = el('span', {class: 'status'});
  const results = el('div', {class: 'results'});
  async function lookUp() {
    status.textContent = 'looking up… (S2 allows ~1 request/s)';
    results.replaceChildren();
    const {ok, result} = await postJSON('/api/resolve', {text: textarea.value});
    if (!ok) { status.textContent = result.error || 'error'; return; }
    status.textContent = '';
    const boxes = [];
    for (const item of result.results) {
      if (!item.paper) {
        results.append(el('div', {class: 'result missing'}, `✗ ${item.input}: ${item.how}`));
        continue;
      }
      const paper = item.paper;
      const reason = excluded ? excluded(paper.paperId) : null;
      const box = el('input', {type: 'checkbox'});
      box.checked = !reason;
      boxes.push([box, paper]);
      const notes = [item.how === 'title match' ? `title match for “${item.input}”` : null,
                     paper.inFeeds.length ? 'seed in: ' + paper.inFeeds.join(', ') : null,
                     reason].filter(Boolean);
      results.append(el('label', {class: 'result'}, box, ' ', s2Link(paper.paperId, paper.title),
        el('span', {class: 'muted'}, ` · ${(paper.authors || []).join(', ')} · ${paper.year || 'n.d.'}`
          + (notes.length ? ' · ' + notes.join(' · ') : ''))));
    }
    if (boxes.length) {
      results.append(el('div', {}, button(confirmLabel, async () => {
        const rows = boxes.filter(([box]) => box.checked).map(([, paper]) =>
          ({paperId: paper.paperId, year: paper.year || '', title: paper.title, source: 'ui'}));
        if (!rows.length) return;
        await onConfirm(rows);
        textarea.value = '';
        results.replaceChildren();
      }, {class: 'primary'})));
    }
  }
  return el('div', {class: 'resolver'}, textarea,
            el('div', {}, button('Look up', lookUp), status), results);
}

// ---------- feeds and their seeds ----------

function seedRow(feed, row) {
  const pick = el('input', {type: 'checkbox', title: 'tick to copy into a new feed (below)'});
  pick.dataset.feed = feed.name;
  pick.dataset.paper = row.paperId;
  const remove = button('✕', async () => {
    if (!confirm(`Remove “${row.title}” from ${feed.name}?`)) return;
    const {ok, result} = await postJSON('/api/seeds/remove', {feed: feed.name, paperId: row.paperId});
    if (!ok) { alert(result.error || 'error'); return; }
    feed.seeds = result.seeds;
    renderFeed(feed);
  }, {class: 'icon', title: 'remove from this feed'});
  const save = saveControls({paperId: row.paperId, defaultCollection: feed.name});
  return el('div', {class: 'seed-row'},
    el('div', {}, pick, ' ', s2Link(row.paperId, row.title || row.paperId),
       el('span', {class: 'muted'}, ` · ${row.year || 'n.d.'} · ${row.source || ''}`)),
    el('div', {class: 'save'}, ...save.elements, remove));
}

const feedSections = {};

function renderFeed(feed) {
  const section = feedSections[feed.name];
  const summary = el('summary', {},
    `${feed.name} (${feed.seeds.length} seeds${feed.negatives ? `, ${feed.negatives} negative` : ''}`
    + ` · ${feed.priority} priority)`);
  const adder = resolveWidget('Add ticked papers to ' + feed.name, async rows => {
    const {ok, result} = await postJSON('/api/seeds/add', {feed: feed.name, rows});
    if (!ok) { alert(result.error || 'error'); return; }
    feed.seeds = result.seeds;
    renderFeed(feed);
  }, paperId => feed.seeds.some(row => row.paperId === paperId) ? 'already a seed here' : null);
  section.replaceChildren(summary,
    el('p', {class: 'muted'}, feed.description || ''),
    el('details', {class: 'adder'}, el('summary', {}, '+ Add papers'), adder),
    ...feed.seeds.map(row => seedRow(feed, row)));
}

const feedsRoot = document.getElementById('feeds');
feedsRoot.append(el('h2', {}, 'Feeds'));
for (const feed of data.feeds) {
  feedSections[feed.name] = el('details', {class: 'tier', id: 'feed-' + feed.name});
  feedsRoot.append(feedSections[feed.name]);
  renderFeed(feed);
}

// ---------- flagged authors ----------

function renderFlagged(list) {
  list.replaceChildren(...Object.entries(data.flagged).map(([name, ids]) =>
    el('li', {}, name + ' ', el('span', {class: 'muted'}, '(',
      ...ids.flatMap((id, index) => [index ? ', ' : '',
        el('a', {href: 'https://www.semanticscholar.org/author/' + id, target: '_blank'}, id)]),
      ')'))));
}

(function flaggedSection() {
  const root = document.getElementById('flagged');
  const list = el('ul');
  renderFlagged(list);
  const query = el('input', {placeholder: 'author name', size: '28'});
  const displayName = el('input', {placeholder: 'name to file under', size: '28'});
  const status = el('span', {class: 'status'});
  const results = el('div', {class: 'results'});
  async function search() {
    status.textContent = 'searching…';
    results.replaceChildren();
    const {ok, result} = await postJSON('/api/authors/search', {query: query.value});
    if (!ok) { status.textContent = result.error || 'error'; return; }
    status.textContent = result.authors.length ? '' : 'no matches';
    if (!displayName.value) displayName.value = query.value.trim();
    const boxes = [];
    for (const author of result.authors) {
      const box = el('input', {type: 'checkbox'});
      boxes.push([box, author]);
      const facts = [author.affiliations.join('; '), `${author.paperCount} papers`,
                     `h-index ${author.hIndex}`, author.flagged ? 'already flagged' : null]
        .filter(Boolean).join(' · ');
      results.append(el('label', {class: 'result'}, box, ' ',
        el('a', {href: 'https://www.semanticscholar.org/author/' + author.authorId, target: '_blank'},
           `${author.name} (${author.authorId})`),
        el('span', {class: 'muted'}, ' · ' + facts),
        el('ul', {class: 'recent'}, ...author.recent.map(title => el('li', {}, title)))));
    }
    if (!boxes.length) return;
    results.append(el('div', {}, button('Flag ticked profiles', async () => {
      const ids = boxes.filter(([box]) => box.checked).map(([, author]) => author.authorId);
      if (!ids.length) return;
      const name = displayName.value.trim();
      const {ok: added, result: response} = await postJSON('/api/authors/add', {name, ids});
      if (!added) { status.textContent = response.error || 'error'; return; }
      data.flagged[name] = response.ids;
      renderFlagged(list);
      results.replaceChildren();
      status.textContent = `flagged ${name}`;
    }, {class: 'primary'})));
  }
  query.addEventListener('keydown', event => { if (event.key === 'Enter') search(); });
  root.append(el('details', {class: 'tier'},
    el('summary', {}, `Flagged authors (${Object.keys(data.flagged).length})`),
    el('p', {class: 'muted'}, 'Papers by flagged authors get at least tier 3, and their new ' +
       'papers are fetched directly. S2 often splits one person across several profiles: tick ' +
       'every profile whose recent papers are theirs. Adding to an existing name merges IDs.'),
    list,
    el('div', {class: 'controls'}, query, button('Search S2', search), displayName, status),
    results));
})();

// ---------- new feed ----------

function stage(rows) {
  for (const row of rows) if (!staged.has(row.paperId)) staged.set(row.paperId, row);
  renderStaged();
}

function renderStaged() {
  stagedView.replaceChildren(el('h4', {}, `Seeds for the new feed (${staged.size})`),
    ...[...staged.values()].map(row => el('div', {class: 'seed-row'},
      el('div', {}, s2Link(row.paperId, row.title || row.paperId),
         el('span', {class: 'muted'}, ` · ${row.year || 'n.d.'} · ${row.source || ''}`)),
      button('✕', () => { staged.delete(row.paperId); renderStaged(); }, {class: 'icon'}))));
}

(function newFeedSection() {
  const root = document.getElementById('new-feed');
  const params = new URLSearchParams(location.search);
  const name = el('input', {placeholder: 'feed_name', size: '24', pattern: '[a-z][a-z0-9_]*'});
  const priority = el('select', {}, el('option', {value: 'high'}, 'high priority'),
                      el('option', {value: 'low'}, 'low priority'));
  priority.value = 'high';
  const description = el('textarea', {rows: '4', placeholder:
    'What this feed is about. Triage reads this to judge relevance, so be specific about ' +
    'what is in and out of scope.'});
  const status = el('span', {class: 'status'});
  stagedView = el('div', {class: 'staged'});

  // source 1: ticked seeds from the feeds above
  const fromTicked = button('Add ticked seeds from the feeds above', () => {
    const rows = [];
    document.querySelectorAll('.seed-row input[type=checkbox]:checked').forEach(box => {
      const feed = data.feeds.find(item => item.name === box.dataset.feed);
      const row = feed && feed.seeds.find(item => item.paperId === box.dataset.paper);
      if (row) rows.push(row);
    });
    if (!rows.length) { status.textContent = 'tick seeds in the feeds above first'; return; }
    stage(rows);
  });

  // source 2: pasted identifiers
  const pasted = resolveWidget('Add ticked papers', async rows => stage(rows),
                               paperId => staged.has(paperId) ? 'already added' : null);

  // source 3: a deep-dive project's confirmed seeds
  const projectSelect = el('select', {}, el('option', {value: ''}, '— project —'),
    ...data.projects.filter(project => project.seeds.length).map(project =>
      el('option', {value: project.slug}, `${project.title} (${project.seeds.length} seeds)`)));
  const linkBox = el('input', {type: 'checkbox', checked: ''});
  const fromProject = button('Add project seeds', () => {
    const project = data.projects.find(item => item.slug === projectSelect.value);
    if (project) stage(project.seeds);
  });

  // source 4: a library collection
  const collectionSelect = el('select', {}, el('option', {value: ''}, '— library collection —'),
    ...Object.entries(data.libraryCollections).map(([collection, count]) =>
      el('option', {value: collection}, `${collection}.bib (${count})`)));
  const fromCollection = button('Add collection papers', async () => {
    if (!collectionSelect.value) return;
    status.textContent = 'looking up…';
    const {ok, result} = await postJSON('/api/collection-rows', {collection: collectionSelect.value});
    status.textContent = ok ? '' : (result.error || 'error');
    if (ok) stage(result.rows);
  });

  const create = button('Create feed', async () => {
    const project = data.projects.find(item => item.slug === projectSelect.value);
    const linkProject = project && !project.feed && linkBox.checked &&
      [...staged.values()].some(row => row.source === `deepdive:${project.slug}`) ? project.slug : null;
    status.textContent = 'creating…';
    const {ok, result} = await postJSON('/api/feeds/create', {name: name.value.trim(),
      priority: priority.value, description: description.value, rows: [...staged.values()],
      linkProject});
    if (!ok) { status.textContent = result.error || 'error'; return; }
    location.href = '/feeds#feed-' + result.feed;
    location.reload();
  }, {class: 'primary'});

  root.append(el('details', {class: 'tier', id: 'new-feed-section',
                             ...(params.get('project') ? {open: ''} : {})},
    el('summary', {}, 'New feed'),
    el('div', {class: 'controls'}, name, priority),
    el('div', {class: 'controls'}, description),
    el('h4', {}, 'Gather seeds (any mix of these)'),
    el('div', {class: 'controls'}, fromTicked),
    el('details', {class: 'adder'}, el('summary', {}, 'Paste identifiers'), pasted),
    el('div', {class: 'controls'}, projectSelect, fromProject,
       el('label', {class: 'muted'}, linkBox, ' link the project to the new feed (its 👍/👎 then edit it)')),
    el('div', {class: 'controls'}, collectionSelect, fromCollection),
    stagedView,
    el('div', {class: 'controls'}, create, status)));
  renderStaged();

  if (params.get('project')) {
    projectSelect.value = params.get('project');
    document.getElementById('new-feed-section').scrollIntoView();
  }
})();

// open the feed named in the URL hash (after creating one)
if (location.hash.startsWith('#feed-')) {
  const section = document.getElementById(location.hash.slice(1));
  if (section) { section.open = true; section.scrollIntoView(); }
}
bindExpandCollapse();
