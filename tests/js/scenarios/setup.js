// /setup: every step renders; keys, author, profile draft, bootstrap → candidates → new feed,
// schedule, and first run each send the right request.
function log(label, value) { console.log(label + ': ' + JSON.stringify(value)); }
function sent(url) { return bodies[calls.lastIndexOf(url)]; }
log('steps', Object.keys(cards));
log('marks', Object.values(cards).map(card => card.mark.textContent).join(''));
const page = nodes.setup;
responses['/api/setup/keys'] = () => ({keys: {ANTHROPIC_API_KEY: {set: true, hint: '…1234'},
  S2_API_KEY: {set: false, hint: ''}, LITFEED_PYTHON: {set: true, hint: ''}}});
responses['/api/setup/status'] = () => ({status: Object.assign({}, status, {ready: true})});
responses['/api/authors/search'] = () => ({authors: [{authorId: '42', name: 'Me', affiliations: [],
  paperCount: 3, hIndex: 1, recent: [], flagged: false}]});
responses['/api/setup/author'] = () => ({status: Object.assign({}, status,
  {feeds: Object.assign({}, status.feeds, {authorId: '42'})})});
responses['/api/setup/draft-profile'] = () => ({profile: '# Drafted profile', cost: 0.012});
responses['/api/setup/bootstrap'] = () => ({job: {state: 'running', log_tail: 'working'}});
responses['/api/setup/job'] = () => ({job: {state: 'done', log_tail: 'done'}});
responses['/api/setup/candidates'] = () => ({candidates: [
  {paperId: 'b'.repeat(40), year: '2020', title: 'Cited paper', citedIn: '3', inFeeds: []},
  {paperId: 'c'.repeat(40), year: '2019', title: 'Other paper', citedIn: '1', inFeeds: ['x']}]});
responses['/api/feeds/create'] = body => ({feed: body.name, seeds: body.rows.length});
responses['/api/setup/schedule'] = body => ({schedule: {supported: true, installed: true,
  weekday: body.weekday, hour: body.hour}});
responses['/api/setup/run-weekly'] = () => ({job: {state: 'running', log_tail: ''}});

const keysCard = cards.keys.card;
keysCard.querySelectorAll('input')[0].value = 'sk-ant-test';
byText(keysCard, 'BUTTON', 'Save keys')[0].listeners.click()
  .then(() => {
    log('keys body', sent('/api/setup/keys'));
    const authorCard = cards.author.card;
    findAll(authorCard, n => n.tagName === 'INPUT')[0].value = 'Me';
    return byText(authorCard, 'BUTTON', 'Search S2')[0].listeners.click();
  })
  .then(() => byText(cards.author.card, 'BUTTON', 'This is me')[0].listeners.click())
  .then(() => {
    log('author body', sent('/api/setup/author'));
    return byText(cards.profile.card, 'BUTTON', 'Draft from my papers')[0].listeners.click();
  })
  .then(() => {
    log('editor after draft', findAll(cards.profile.card, n => (n.className || '').includes('profile-editor'))[0].value);
    return byText(cards.feeds.card, 'BUTTON', 'Find the papers I cite')[0].listeners.click();
  })
  .then(() => intervals[intervals.length - 1]())
  .then(() => new Promise(resolve => resolve()))
  .then(() => {
    const feeds = cards.feeds.card;
    const boxes = feeds.querySelectorAll('input[type=checkbox]');
    log('candidates shown', boxes.length);
    boxes[0].checked = true;
    findAll(feeds, n => n.attrs.placeholder === 'feed_name')[0].value = 'first_feed';
    return byText(feeds, 'BUTTON', 'Create feed from ticked papers')[0].listeners.click();
  })
  .then(() => {
    const feed = sent('/api/feeds/create');
    log('feed body', {name: feed.name, rows: feed.rows.length, source: feed.rows[0].source});
    const card = cards.schedule.card;
    if (!byText(card, 'BUTTON', 'schedule').length) { log('schedule', 'not offered'); return; }
    return byText(card, 'BUTTON', 'schedule')[0].listeners.click()
      .then(() => log('schedule body', sent('/api/setup/schedule')));
  })
  .then(() => {
    const run = byText(cards.run.card, 'BUTTON', 'Run the weekly pipeline now');
    return run.length ? run[0].listeners.click() : null;
  })
  .then(() => log('calls', calls), error => console.log('ERROR ' + error + '\n' + error.stack));
