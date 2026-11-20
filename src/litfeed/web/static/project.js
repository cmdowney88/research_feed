// Project (deep-dive) page: the synthesis with clickable citations, then the surfaced
// papers grouped by relevance, each with 👍/👎 (edits the linked feed's seeds) and Save.

const labelNames = {core: 'Core', related: 'Related', background: 'Background'};
const summaries = {};

// "👍 also saves to library" toggle (default on), remembered per browser
const autosaveBox = document.getElementById('autosave');
if (autosaveBox) {
  autosaveBox.checked = loadPreference('thumbUpSaves', true);
  autosaveBox.addEventListener('change', () => storePreference('thumbUpSaves', autosaveBox.checked));
}

function updateCounts() {
  for (const [label, [summary, total]] of Object.entries(summaries)) {
    const section = summary.parentElement;
    const up = section.querySelectorAll('button.thumb.up.on').length;
    const down = section.querySelectorAll('button.thumb.down.on').length;
    summary.textContent = `${labelNames[label]} (${total}; ${up} 👍, ${down} 👎)`;
  }
}

function projectCard(paper) {
  const node = el('div', {class: 'card', id: 'p-' + paper.paperId});
  const thumb = data.thumbs[paper.paperId] || {};
  const upButton = el('button', {class: 'thumb up', title: 'definitely relevant: add to feed seeds'}, '👍');
  const downButton = el('button', {class: 'thumb down', title: 'not relevant: remove from feed seeds'}, '👎');
  const badge = el('span', {class: 'badge'}, 'in feed seeds');
  const status = el('span', {class: 'status'});
  const save = saveControls(paper);

  function show(value, inSeeds) {
    upButton.classList.toggle('on', value === 'up');
    downButton.classList.toggle('on', value === 'down');
    node.classList.toggle('rated', value === 'up');
    node.classList.toggle('thumb-down', value === 'down');
    badge.style.display = inSeeds ? '' : 'none';
  }
  async function setThumb(value) {
    status.textContent = '…';
    const {ok, result} = await postJSON('/api/thumb', {paperId: paper.paperId, thumb: value});
    if (!ok) { status.textContent = result.error || 'error'; return; }
    data.thumbs[paper.paperId] = result.entry;
    show(result.entry.thumb, result.entry.in_seeds);
    status.textContent = '';
    updateCounts();
    // only 👍 saves; 👎 and neutral never unsave (that stays a deliberate ★ click)
    if (value === 'up' && autosaveBox && autosaveBox.checked) await save.saveIfNeeded();
  }
  // clicking the active thumb again returns the paper to neutral
  upButton.addEventListener('click', () =>
    setThumb((data.thumbs[paper.paperId] || {}).thumb === 'up' ? null : 'up'));
  downButton.addEventListener('click', () =>
    setThumb((data.thumbs[paper.paperId] || {}).thumb === 'down' ? null : 'down'));
  show(thumb.thumb || null, data.seeds.includes(paper.paperId));

  const thumbControls = data.feed ? [upButton, downButton, badge, status] : [];
  const parts = [
    el('h3', {}, paper.title),
    metaLine(paper, [paper.citationCount != null ? `${paper.citationCount} citations` : null]),
    el('div', {class: 'why'}, el('span', {class: 'aspect'}, paper.aspect + ': '), paper.why),
    data.notes[paper.paperId] ? noteElement(data.notes[paper.paperId], false) : null,
    el('div', {class: 'save'}, ...thumbControls, ...save.elements),
  ];
  node.append(...parts.filter(part => part != null));
  return node;
}

// ---------- pipeline: job progress and the seed checkpoint ----------

const STAGE_NAMES = {search: 'search & scoring', recommend: 'recommendations',
                     notes: 'reading notes', synthesize: 'synthesis'};

function seedChoice(row, checked) {
  const box = el('input', {type: 'checkbox'});
  box.checked = checked;
  box.dataset.paper = row.paperId;
  return el('label', {class: 'result'}, box, ' ',
    el('a', {href: '#p-' + row.paperId, class: 'cite', 'data-paper': row.paperId}, row.title),
    el('span', {class: 'muted'}, ` · ${row.year || 'n.d.'} · ${row.signals} signal(s)`));
}

function checkpoint(pipeline) {
  const byAspect = {};
  for (const row of pipeline.proposed) (byAspect[row.aspect || 'other'] ||= []).push(row);
  const status = el('span', {class: 'status'});
  const panel = el('div', {class: 'panel'},
    el('h2', {}, 'Checkpoint: confirm the seeds'),
    el('p', {class: 'muted'}, 'These core papers seed the all-years recommendation stage, ' +
       'which multiplies whatever is here, so untick anything off-target. Ticking a few ' +
       'related papers can cover an aspect with no core papers. Confirming starts ' +
       'recommendations → notes for the top 15 core papers → synthesis (~$3–5, ~15–30 min).'));
  for (const [aspect, rows] of Object.entries(byAspect)) {
    panel.append(el('h4', {}, `${aspect} (${rows.length})`),
                 ...rows.map(row => seedChoice(row, true)));
  }
  if (pipeline.related.length) {
    panel.append(el('details', {class: 'adder'},
      el('summary', {}, `Related papers you could add (${pipeline.related.length} best-supported)`),
      ...pipeline.related.map(row => seedChoice(row, false))));
  }
  const confirmButton = el('button', {type: 'button', class: 'primary'}, 'Confirm seeds and continue');
  confirmButton.addEventListener('click', async () => {
    const paperIds = [...panel.querySelectorAll('input[type=checkbox]:checked')]
      .map(box => box.dataset.paper);
    if (!paperIds.length) { status.textContent = 'tick at least one seed'; return; }
    confirmButton.disabled = true;
    status.textContent = 'starting…';
    const {ok, result} = await postJSON('/api/deepdive/seeds', {paperIds});
    if (!ok) { status.textContent = result.error || 'error'; confirmButton.disabled = false; return; }
    location.reload();
  });
  panel.append(el('div', {class: 'controls'}, confirmButton, status));
  return panel;
}

function jobPanel(job) {
  const stages = job.stages.map((stage, index) => {
    const state = index < job.current || job.state === 'done' ? '✓'
      : index === job.current ? (job.state === 'running' ? '…' : '✗') : '·';
    return `${state} ${STAGE_NAMES[stage[0]] || stage[0]}`;
  }).join('   ');
  const panel = el('div', {class: 'panel'},
    el('h2', {}, job.state === 'running' ? 'Deep dive running' : `Deep dive ${job.state}`),
    el('p', {}, stages),
    job.error ? el('p', {class: 'flag'}, job.error) : null,
    el('details', {...(job.state === 'running' ? {} : {open: ''})},
       el('summary', {class: 'muted'}, 'log (logs/jobs/' + data.context.project + '.log)'),
       el('pre', {class: 'log'}, job.log_tail || '')));
  if (job.state === 'failed' || job.state === 'interrupted') {
    const status = el('span', {class: 'status'});
    const resume = el('button', {type: 'button', class: 'primary'},
                      `Resume from ${STAGE_NAMES[job.stages[job.current][0]]}`);
    resume.addEventListener('click', async () => {
      status.textContent = 'starting…';
      const {ok, result} = await postJSON('/api/deepdive/resume', {});
      if (!ok) { status.textContent = result.error || 'error'; return; }
      location.reload();
    });
    panel.append(el('div', {class: 'controls'}, resume, status));
  }
  return panel;
}

function renderPipeline() {
  const root = document.getElementById('pipeline');
  const pipeline = data.pipeline;
  const job = pipeline.job;
  if (job && job.state === 'running') {
    root.replaceChildren(jobPanel(job));
    // poll until the stage list finishes, then reload to show the new results
    const timer = setInterval(async () => {
      const {ok, result} = await postJSON('/api/job', {});
      if (!ok || !result.job) return;
      if (result.job.state !== 'running') { clearInterval(timer); location.reload(); return; }
      root.replaceChildren(jobPanel(result.job));
    }, 4000);
  } else if (pipeline.awaitingSeeds) {
    root.replaceChildren(checkpoint(pipeline));
  } else if (job && job.state !== 'done') {
    root.replaceChildren(jobPanel(job));
  } else if (!job && !data.papers.length && !pipeline.hasSynthesis) {
    const start = el('button', {type: 'button', class: 'primary'}, 'Start search');
    start.addEventListener('click', async () => {
      const {ok, result} = await postJSON('/api/deepdive/resume', {});
      if (ok) location.reload(); else alert(result.error || 'error');
    });
    root.replaceChildren(el('div', {class: 'panel'}, el('p', {}, 'No search has run yet.'), start));
  } else if (pipeline.hasSynthesis && !data.feed) {
    root.replaceChildren(el('p', {class: 'muted'}, 'Done. ',
      el('a', {href: '/feeds?project=' + data.context.project}, 'Make a weekly feed from its seeds'),
      ' (links the project, so 👍/👎 here edit that feed).'));
  }
  root.addEventListener('click', event => {
    const link = event.target.closest('a.cite');
    if (!link || !document.getElementById('p-' + link.dataset.paper)) return;
    event.preventDefault();
    revealCard(link.dataset.paper);
  });
}
renderPipeline();

const synthesisRoot = document.getElementById('synthesis');
if (data.synthesis) {
  const body = renderMarkdown(data.synthesis, {cite: data.citations});
  synthesisRoot.append(el('details', {class: 'tier', open: ''},
                          el('summary', {}, 'Synthesis'), el('div', {class: 'synthesis'}, body)));
  synthesisRoot.addEventListener('click', event => {
    const link = event.target.closest('a.cite');
    if (!link) return;
    event.preventDefault();
    revealCard(link.dataset.paper);
  });
}

const root = document.getElementById('papers');
for (const label of ['core', 'related', 'background']) {
  const papers = data.papers.filter(paper => paper.relevance === label);
  if (!papers.length) continue;
  const summary = el('summary', {});
  summaries[label] = [summary, papers.length];
  const section = el('details', {class: 'tier', ...(label === 'core' ? {open: ''} : {})}, summary);
  for (const paper of papers) section.append(projectCard(paper));
  root.append(section);
}
updateCounts();
bindExpandCollapse();
