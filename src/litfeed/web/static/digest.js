// Digest page: papers grouped by triage tier, with tier/note ratings and Save controls.

const tierNames = {1: 'Tier 1: read carefully', 2: 'Tier 2: skim',
                   3: 'Tier 3: worth knowing it exists', 4: 'Tier 4: probably not interesting'};
const summaries = {};

function updateCounts() {
  for (const [tier, [summary, total]] of Object.entries(summaries)) {
    const rated = summary.parentElement.querySelectorAll('.card.rated').length;
    summary.textContent = `${tierNames[tier]} (${total}; ${rated} rated)`;
  }
}

function digestCard(paper) {
  const rating = data.ratings[paper.paperId] || {};
  const feeds = Object.keys(paper.feeds)
    .filter(feed => feed !== 'citing_me' && feed !== 'flagged_authors').sort().join(', ');
  const flags = [];
  if ((paper.flaggedAuthors || []).length) flags.push('⚑ ' + paper.flaggedAuthors.join(', '));
  if ('citing_me' in paper.feeds) flags.push('↩ cites you');

  const select = el('select', {'aria-label': 'your tier'});
  select.append(el('option', {value: ''}, `— (predicted ${paper.tier})`));
  for (const tier of [1, 2, 3, 4]) select.append(el('option', {value: String(tier)}, `tier ${tier}`));
  select.value = rating.user_tier ? String(rating.user_tier) : '';
  const textarea = el('textarea', {placeholder: 'note (why?)', rows: '1'});
  textarea.value = rating.note || '';
  const status = el('span', {class: 'status'});
  const node = el('div', {class: 'card', id: 'p-' + paper.paperId});
  async function save() {
    status.textContent = '…';
    const {ok} = await postJSON('/api/rate', {paperId: paper.paperId,
      user_tier: select.value ? Number(select.value) : null, note: textarea.value.trim()});
    status.textContent = ok ? 'saved' : 'error';
    node.classList.toggle('rated', Boolean(select.value || textarea.value.trim()));
    updateCounts();
  }
  select.addEventListener('change', save);
  textarea.addEventListener('change', save);
  if (rating.user_tier || rating.note) node.classList.add('rated');

  const parts = [
    el('h3', {}, paper.title),
    metaLine(paper, [feeds ? 'feeds: ' + feeds : null]),
    flags.length ? el('div', {class: 'flag'}, flags.join('  ·  ')) : null,
    el('div', {class: 'why'}, paper.why),
    data.notes[paper.paperId] ? noteElement(data.notes[paper.paperId], paper.tier === 1) : null,
    el('div', {class: 'controls'}, select, textarea, status),
    el('div', {class: 'save'}, ...saveControls(paper).elements),
  ];
  node.append(...parts.filter(part => part != null));
  return node;
}

const root = document.getElementById('tiers');
for (const tier of [1, 2, 3, 4]) {
  const papers = data.papers.filter(paper => paper.tier === tier);
  if (!papers.length) continue;
  const summary = el('summary', {});
  summaries[tier] = [summary, papers.length];
  const section = el('details', {class: 'tier', ...(tier <= 1 ? {open: ''} : {})}, summary);
  for (const paper of papers) section.append(digestCard(paper));
  root.append(section);
}
updateCounts();
bindExpandCollapse();
