// Setup page: a checklist from an empty data directory to a first digest. Each step's card
// shows ✓ when done; actions save immediately and refresh the status.

const root = document.getElementById('setup');
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
let status = data.status;
const cards = {};

function button(text, onClick, attrs) {
  const node = el('button', {type: 'button', ...(attrs || {})}, text);
  node.addEventListener('click', onClick);
  return node;
}

function line(...parts) { return el('p', {}, ...parts); }
function code(text) { return el('code', {}, text); }

// a step card whose heading shows done/not done; `isDone(status)` decides
function step(id, title, isDone, optional, ...body) {
  const mark = el('span', {class: 'mark'});
  const heading = el('h2', {}, mark, ' ', title, optional ? el('span', {class: 'muted'}, ' (optional)') : null);
  const card = el('div', {class: 'card step', id: 'step-' + id}, heading, ...body);
  cards[id] = {mark, isDone, card};
  return card;
}

function renderMarks() {
  for (const {mark, isDone, card} of Object.values(cards)) {
    const done = isDone(status);
    mark.textContent = done ? '✓' : '○';
    card.classList.toggle('done', done);
  }
  readyNote.textContent = status.ready
    ? 'Ready: the weekly run has everything it needs.'
    : 'Not ready yet: the weekly run needs steps 2, 4, and 5.';
}

async function refresh() {
  const {ok, result} = await postJSON('/api/setup/status', {});
  if (ok) { status = result.status; renderMarks(); }
}

// poll a named job until it stops; onUpdate(job) on every tick
function pollJob(name, onUpdate, onDone) {
  const timer = setInterval(async () => {
    const {ok, result} = await postJSON('/api/setup/job', {name});
    if (!ok || !result.job) return;
    onUpdate(result.job);
    if (result.job.state !== 'running') { clearInterval(timer); onDone(result.job); }
  }, 3000);
}

function jobView(job) {
  if (!job) return el('div');
  return el('div', {},
    el('p', {class: job.state === 'failed' ? 'flag' : 'muted'},
       `${job.state}${job.error ? ': ' + job.error : ''}`),
    el('pre', {class: 'log'}, job.log_tail || ''));
}

const readyNote = el('p', {class: 'muted'});
root.append(readyNote);

// ---------- 1. data directory ----------

root.append(step('data', '1. Data directory', () => true, false,
  line('Your feeds, seeds, ratings, digests, notes, and library live in ', code(status.dataDir),
       status.dataDirFromEnv ? ' (from LITFEED_DATA).' : ' (the default; set LITFEED_DATA to use another folder).'),
  el('p', {class: 'muted'}, 'It is separate from the code so you can keep it as its own ' +
     'private git repository (it already has a .gitignore that leaves out keys, caches, and PDFs).')));

// ---------- 2. keys and tools ----------

(function keysStep() {
  const fields = {};
  const rows = [];
  const info = {
    ANTHROPIC_API_KEY: ['Anthropic API key', 'required: triage, notes, and deep dives call Claude ' +
                        '(console.anthropic.com → API keys)'],
    S2_API_KEY: ['Semantic Scholar API key', 'optional but much faster: free from ' +
                 'semanticscholar.org/product/api'],
  };
  for (const [key, [label, help]] of Object.entries(info)) {
    const input = el('input', {type: 'password', size: '40', autocomplete: 'off',
                               placeholder: status.keys[key].set ? `saved ${status.keys[key].hint}` : 'paste key'});
    const result = el('span', {class: 'muted'});
    fields[key] = input;
    rows.push(el('div', {class: 'controls'}, el('label', {}, label, el('br'), input),
      button('Test', async () => {
        result.textContent = 'testing…';
        const {ok, result: response} = await postJSON('/api/setup/test-key', {which: key, value: input.value});
        result.textContent = ok ? (response.ok ? '✓ ' : '✗ ') + response.message : (response.error || 'error');
      }), result), el('p', {class: 'muted'}, help));
  }
  const saveStatus = el('span', {class: 'status'});
  const save = button('Save keys', async () => {
    const body = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value]));
    const {ok, result} = await postJSON('/api/setup/keys', body);
    if (!ok) { saveStatus.textContent = result.error || 'error'; return; }
    for (const [key, input] of Object.entries(fields)) {
      input.value = '';
      input.setAttribute('placeholder', result.keys[key].set ? `saved ${result.keys[key].hint}` : 'paste key');
    }
    saveStatus.textContent = 'saved to .env';
    refresh();
  }, {class: 'primary'});
  const tools = status.tools;
  root.append(step('keys', '2. API keys and tools',
    s => s.keys.ANTHROPIC_API_KEY.set && s.tools.claude !== null, false,
    el('div', {class: 'note'},
      el('p', {}, el('strong', {}, 'Slightly more secure: skip the boxes below. '),
         'Either export the keys in your shell before starting the server, or write them into ',
         code(status.dataDir + '/.env'), ' yourself:'),
      el('pre', {}, 'ANTHROPIC_API_KEY=sk-ant-...\nS2_API_KEY=...'),
      el('p', {}, 'Then restart ', code('scripts/serve_ui.py'), '; this step shows them as set. ' +
         'Pasting here is convenient, but the key passes through your browser (where extensions ' +
         'with access to all sites can read form fields), and this local server has no login yet, ' +
         'so other programs on your machine could replace saved keys or start paid jobs (they ' +
         'cannot read keys back). See the README\'s "Local UI security".')),
    el('p', {class: 'muted'}, 'Keys pasted here are saved to the data directory\'s .env (readable ' +
       'only by you) and never shown again; the page only learns whether a key is set.'),
    ...rows, el('div', {class: 'controls'}, save, saveStatus),
    el('h4', {}, 'Tools'),
    el('ul', {},
      el('li', {}, tools.claude ? `✓ claude (Claude Code CLI) at ${tools.claude}`
        : '✗ claude (Claude Code CLI) not found: install Claude Code, which runs the triage, notes, and deep dives'),
      el('li', {}, tools.pdftotext ? `✓ pdftotext at ${tools.pdftotext}`
        : '○ pdftotext not found (optional: notes then use arXiv sources or abstracts only; macOS: brew install poppler)'))));
})();

// ---------- 3. Semantic Scholar profile ----------

(function authorStep() {
  const current = el('p', {});
  function showCurrent() {
    const id = status.feeds.authorId;
    current.replaceChildren(id
      ? el('span', {}, 'Your S2 author ID: ',
           el('a', {href: 'https://www.semanticscholar.org/author/' + id, target: '_blank'}, id))
      : el('span', {class: 'muted'}, 'Not set.'));
  }
  showCurrent();
  const query = el('input', {placeholder: 'your name as it appears on papers', size: '32'});
  const results = el('div', {class: 'results'});
  const searchStatus = el('span', {class: 'status'});
  async function search() {
    searchStatus.textContent = 'searching…';
    const {ok, result} = await postJSON('/api/authors/search', {query: query.value});
    searchStatus.textContent = ok ? (result.authors.length ? '' : 'no matches') : (result.error || 'error');
    if (!ok) return;
    results.replaceChildren(...result.authors.map(author => {
      const pick = button('This is me', async () => {
        const {ok: saved, result: response} = await postJSON('/api/setup/author', {authorId: author.authorId});
        if (!saved) { searchStatus.textContent = response.error || 'error'; return; }
        status = response.status;
        showCurrent();
        results.replaceChildren();
        renderMarks();
      });
      const facts = [author.affiliations.join('; '), `${author.paperCount} papers`].filter(Boolean).join(' · ');
      return el('div', {class: 'result'}, pick, ' ',
        el('a', {href: 'https://www.semanticscholar.org/author/' + author.authorId, target: '_blank'},
           `${author.name} (${author.authorId})`),
        el('span', {class: 'muted'}, ' · ' + facts),
        el('ul', {class: 'recent'}, ...author.recent.map(title => el('li', {}, title))));
    }));
  }
  query.addEventListener('keydown', event => { if (event.key === 'Enter') search(); });
  root.append(step('author', '3. You on Semantic Scholar', s => Boolean(s.feeds.authorId), true,
    el('p', {class: 'muted'}, 'With your author ID, the weekly run also surfaces new papers citing ' +
       'your work, and steps 4 and 5 can start from your publications. Skip it if you have none. ' +
       'If S2 splits you across profiles, pick the main one.'),
    current, el('div', {class: 'controls'}, query, button('Search S2', search), searchStatus), results));
})();

// ---------- 4. taste profile ----------

(function profileStep() {
  const notes = el('textarea', {rows: '3', placeholder:
    'Optional notes for the draft: current projects, where your work is heading, topics you ' +
    'don\'t want to see. These take precedence over your publication record.'});
  const editor = el('textarea', {rows: '24', class: 'profile-editor'});
  editor.value = data.profileText;
  const draftStatus = el('span', {class: 'status'});
  const saveStatus = el('span', {class: 'status'});
  const draft = button('Draft from my papers', async () => {
    if (status.profile.customized &&
        !confirm('Replace the text in the editor with a new draft? (Nothing is saved until you click Save.)')) return;
    draft.disabled = true;
    draftStatus.textContent = 'drafting… (about a minute)';
    const {ok, result} = await postJSON('/api/setup/draft-profile', {notes: notes.value});
    draft.disabled = false;
    if (!ok) { draftStatus.textContent = result.error || 'error'; return; }
    editor.value = result.profile;
    draftStatus.textContent = `drafted${result.cost != null ? ` ($${result.cost.toFixed(3)})` : ''}: ` +
      'read it, fix what\'s wrong, then Save';
  });
  const save = button('Save profile', async () => {
    const {ok, result} = await postJSON('/api/setup/profile', {text: editor.value});
    saveStatus.textContent = ok ? 'saved' : (result.error || 'error');
    if (ok) { status = result.status; renderMarks(); }
  }, {class: 'primary'});
  root.append(step('profile', '4. Your research taste', s => s.profile.customized, false,
    el('p', {class: 'muted'}, 'Triage reads this to sort papers into tiers and explain why each ' +
       'matters to you, so specifics help: ranked interests, settings, methods, what to skip. ' +
       'Drafting needs step 3 and costs a few cents; your ratings later show where to refine it.'),
    notes, el('div', {class: 'controls'}, draft, draftStatus), editor,
    el('div', {class: 'controls'}, save, saveStatus)));
})();

// ---------- 5. first feeds ----------

(function feedsStep() {
  const summary = el('p', {});
  function showSummary() {
    const counts = Object.entries(status.feeds.seedCounts);
    summary.replaceChildren(counts.length
      ? 'Feeds: ' + counts.map(([name, count]) => `${name} (${count} seeds)`).join(', ')
      : 'No feeds yet.');
  }
  showSummary();
  const jobArea = el('div');
  const candidateArea = el('div');
  const bootstrap = button('Find the papers I cite', async () => {
    const {ok, result} = await postJSON('/api/setup/bootstrap', {});
    if (!ok) { jobArea.replaceChildren(el('p', {class: 'flag'}, result.error || 'error')); return; }
    jobArea.replaceChildren(jobView(result.job));
    pollJob('setup-seeds', job => jobArea.replaceChildren(jobView(job)), job => {
      if (job.state === 'done') { jobArea.replaceChildren(); loadCandidates(); }
    });
  });

  async function loadCandidates() {
    const {ok, result} = await postJSON('/api/setup/candidates', {});
    if (!ok) { candidateArea.replaceChildren(el('p', {class: 'muted'}, result.error || 'error')); return; }
    const boxes = [];
    const list = result.candidates.map(candidate => {
      const box = el('input', {type: 'checkbox'});
      boxes.push([box, candidate]);
      return el('label', {class: 'result'}, box, ' ',
        el('a', {href: 'https://www.semanticscholar.org/paper/' + candidate.paperId, target: '_blank'}, candidate.title),
        el('span', {class: 'muted'}, ` · ${candidate.year || 'n.d.'} · cited in ${candidate.citedIn} of your papers`
          + (candidate.inFeeds.length ? ' · in ' + candidate.inFeeds.join(', ') : '')));
    });
    const name = el('input', {placeholder: 'feed_name', size: '24'});
    const priority = el('select', {}, el('option', {value: 'high'}, 'high priority'),
                        el('option', {value: 'low'}, 'low priority'));
    priority.value = 'high';
    const description = el('textarea', {rows: '3', placeholder:
      'What this feed is about (triage reads it): topics, settings, methods, and what is out of scope.'});
    const createStatus = el('span', {class: 'status'});
    const create = button('Create feed from ticked papers', async () => {
      const rows = boxes.filter(([box]) => box.checked).map(([, candidate]) =>
        ({paperId: candidate.paperId, year: candidate.year, title: candidate.title, source: 'cited'}));
      if (!rows.length) { createStatus.textContent = 'tick some papers first'; return; }
      const {ok: created, result: response} = await postJSON('/api/feeds/create', {
        name: name.value.trim(), priority: priority.value, description: description.value, rows});
      if (!created) { createStatus.textContent = response.error || 'error'; return; }
      createStatus.textContent = `created ${response.feed} with ${response.seeds} seeds`;
      await refresh();
      showSummary();
      loadCandidates();
    }, {class: 'primary'});
    candidateArea.replaceChildren(
      el('p', {class: 'muted'}, 'Ranked by how often and how prominently your papers cite them. ' +
         'Tick the papers that define one line of your interests, then name the feed; repeat for ' +
         'each feed (most people want 3-6 feeds of 10-30 seeds).'),
      el('div', {class: 'candidate-list'}, ...list),
      el('div', {class: 'controls'}, name, priority), el('div', {class: 'controls'}, description),
      el('div', {class: 'controls'}, create, createStatus));
  }

  root.append(step('feeds', '5. Your first feeds', s => s.feeds.seededFeeds > 0, false,
    el('p', {class: 'muted'}, 'A feed is a set of seed papers; every week Semantic Scholar ' +
       'recommends new papers similar to them. Three ways to start:'),
    summary,
    el('ol', {},
      el('li', {}, 'From your citations (needs step 3): ', bootstrap,
         status.feeds.candidates ? el('span', {}, ' or ', button('show the last results', loadCandidates)) : null),
      el('li', {}, 'By pasting papers (links, DOIs, arXiv IDs, or titles) on ',
         el('a', {href: '/feeds'}, 'Feeds & seeds'), ' → New feed.'),
      el('li', {}, 'From a written project description: ', el('a', {href: '/deepdive/new'}, 'New deep dive'),
         ' searches the literature and can turn its results into a feed.')),
    jobArea, candidateArea));
  const running = data.jobs['setup-seeds'];
  if (running && running.state === 'running') {
    jobArea.replaceChildren(jobView(running));
    pollJob('setup-seeds', job => jobArea.replaceChildren(jobView(job)), job => {
      if (job.state === 'done') { jobArea.replaceChildren(); loadCandidates(); }
    });
  }
})();

// ---------- 6. flagged authors ----------

root.append(step('flagged', '6. Authors to follow', () => false, true,
  el('p', {}, 'Papers by flagged authors always reach at least tier 3, and their new papers are ' +
     'fetched directly. Add them on ', el('a', {href: '/feeds'}, 'Feeds & seeds'), ' → Flagged authors.')));
cards.flagged.mark.textContent = '·';

// ---------- 7. weekly schedule ----------

(function scheduleStep() {
  const schedule = status.schedule;
  if (!schedule.supported) {
    root.append(step('schedule', '7. Weekly schedule', () => false, true,
      el('p', {}, 'Automatic weekly runs are macOS-only for now (they use launchd). On other ' +
         'systems, run the four pipeline scripts by hand or from your own scheduler; see the README.')));
    return;
  }
  const weekday = el('select', {}, ...WEEKDAYS.map((day, index) => el('option', {value: String(index)}, day)));
  const hour = el('select', {}, ...Array.from({length: 24}, (_, index) =>
    el('option', {value: String(index)}, `${String(index).padStart(2, '0')}:00`)));
  weekday.value = String(schedule.installed ? schedule.weekday : 3);
  hour.value = String(schedule.installed ? schedule.hour : 11);
  const current = el('p', {});
  function showCurrent(value) {
    current.replaceChildren(value.installed
      ? `Installed: ${WEEKDAYS[value.weekday]}s at ${String(value.hour).padStart(2, '0')}:00 local time.`
      : value.otherDataDir
        ? `A weekly job is installed for another data directory (${value.otherDataDir}); ` +
          'installing here replaces it (one job per user).'
        : 'Not installed.');
  }
  showCurrent(schedule);
  const installStatus = el('span', {class: 'status'});
  const install = button(schedule.installed ? 'Update schedule' : 'Install schedule', async () => {
    const {ok, result} = await postJSON('/api/setup/schedule',
                                        {weekday: Number(weekday.value), hour: Number(hour.value)});
    if (!ok) { installStatus.textContent = result.error || 'error'; return; }
    installStatus.textContent = 'installed';
    status.schedule = result.schedule;
    showCurrent(result.schedule);
    renderMarks();
  }, {class: 'primary'});
  root.append(step('schedule', '7. Weekly schedule', s => s.schedule.installed, true,
    el('p', {class: 'muted'}, 'macOS only for now. A launchd job runs fetch → triage → notes → ' +
       'digest and posts a notification when the digest is ready. If the Mac is asleep at that ' +
       'time, it runs on wake.'),
    current, el('div', {class: 'controls'}, weekday, hour, install, installStatus)));
})();

// ---------- 8. first run ----------

(function firstRunStep() {
  const area = el('div');
  if (!status.schedule.supported) {
    root.append(step('run', '8. First digest', s => s.digests > 0, false,
      el('p', {}, 'The one-click run uses scripts/weekly.sh, which is macOS-only for now. Run the ' +
         'pipeline scripts by hand instead (README → Weekly run), then come back to rate.')));
    return;
  }
  const run = button('Run the weekly pipeline now', async () => {
    if (!confirm('Run fetch → triage → notes → digest now? It takes 5-15 minutes and costs ' +
                 'roughly $1-3 in Claude usage.')) return;
    const {ok, result} = await postJSON('/api/setup/run-weekly', {});
    if (!ok) { area.replaceChildren(el('p', {class: 'flag'}, result.error || 'error')); return; }
    follow(result.job);
  }, {class: 'primary'});
  function follow(job) {
    area.replaceChildren(jobView(job));
    pollJob('weekly', next => area.replaceChildren(jobView(next)), async done => {
      await refresh();
      area.replaceChildren(jobView(done), done.state === 'done'
        ? el('p', {}, 'Done: ', el('a', {href: '/'}, 'open your first digest'), '.') : el('span'));
    });
  }
  root.append(step('run', '8. First digest', s => s.digests > 0, false,
    el('p', {class: 'muted'}, 'Runs the weekly pipeline once now, so you can rate a digest right ' +
       'away. Rate where you disagree; ratings tune later fetches and triage.'),
    el('div', {class: 'controls'}, run), area));
  const running = data.jobs.weekly;
  if (running && running.state === 'running') follow(running);
})();

renderMarks();
