// /feeds: stage a ticked seed, remove a seed, add via lookup, create a feed, flag an author.
function log(label, value) { console.log(label + ': ' + JSON.stringify(value)); }
const feedNames = data.feeds.map(feed => feed.name);
log('feed sections', document.querySelectorAll('details.tier').length - 2 === feedNames.length);
const first = data.feeds[0], second = data.feeds[1];
const firstSection = document.getElementById('feed-' + first.name);
log('seed rows in first feed', firstSection.querySelectorAll('div.seed-row').length === first.seeds.length);
firstSection.querySelectorAll('input[type=checkbox]')[0].checked = true;
byText(nodes['new-feed'], 'BUTTON', 'Add ticked seeds')[0].listeners.click();
log('staged after ticking', byText(nodes['new-feed'], 'H4', 'Seeds for the new feed')[0].text());

const removedId = first.seeds[1].paperId;
responses['/api/seeds/remove'] = body => ({removed: {}, seeds: first.seeds.filter(row => row.paperId !== body.paperId)});
const secondSection = document.getElementById('feed-' + second.name);
responses['/api/resolve'] = () => ({results: [
  {input: 'arXiv:1706.03762', how: 'id', paper: {paperId: 'a'.repeat(40), title: 'Found', year: 2017,
   authors: ['A. Author'], inFeeds: []}},
  {input: 'zzz', how: 'no title match', paper: null}]});
responses['/api/seeds/add'] = body => ({added: body.rows, seeds: second.seeds.concat(body.rows)});
responses['/api/feeds/create'] = body => ({feed: body.name, seeds: body.rows.length});
responses['/api/authors/search'] = () => ({authors: [
  {authorId: '1', name: 'X One', affiliations: ['Uni'], paperCount: 3, hIndex: 1, recent: ['P (2025)'], flagged: false},
  {authorId: '2', name: 'X Two', affiliations: [], paperCount: 9, hIndex: 2, recent: [], flagged: false}]});
responses['/api/authors/add'] = body => ({ids: body.ids});

byText(firstSection, 'BUTTON', '✕')[1].listeners.click()
  .then(() => {
    log('removed and re-rendered', firstSection.querySelectorAll('div.seed-row').length === first.seeds.length
        && !first.seeds.some(row => row.paperId === removedId));
    secondSection.querySelectorAll('textarea')[0].value = 'arXiv:1706.03762\nzzz';
    return byText(secondSection, 'BUTTON', 'Look up')[0].listeners.click();
  })
  .then(() => {
    log('lookup shows missing line', byText(secondSection, 'DIV', '✗ zzz').length > 0);
    return byText(secondSection, 'BUTTON', 'Add ticked papers to')[0].listeners.click();
  })
  .then(() => {
    log('seeds/add body', bodies[bodies.length - 1].rows.map(row => row.paperId.slice(0, 3)));
    const newFeed = nodes['new-feed'];
    findAll(newFeed, n => n.attrs.placeholder === 'feed_name')[0].value = 'my_feed';
    findAll(newFeed, n => n.tagName === 'TEXTAREA' && (n.attrs.placeholder || '').startsWith('What'))[0].value = 'About X.';
    return byText(newFeed, 'BUTTON', 'Create feed')[0].listeners.click();
  })
  .then(() => {
    const body = bodies[bodies.length - 1];
    log('feeds/create', {name: body.name, rows: body.rows.length, priority: body.priority,
                         linkProject: body.linkProject, reloaded: calls.includes('reload')});
    const flagged = nodes.flagged;
    findAll(flagged, n => n.attrs.placeholder === 'author name')[0].value = 'X';
    return byText(flagged, 'BUTTON', 'Search S2')[0].listeners.click();
  })
  .then(() => {
    nodes.flagged.querySelectorAll('input[type=checkbox]')[1].checked = true;
    return byText(nodes.flagged, 'BUTTON', 'Flag ticked profiles')[0].listeners.click();
  })
  .then(() => {
    log('authors/add', bodies[bodies.length - 1]);
    log('flagged list updated', 'X' in data.flagged);
    log('calls', calls);
  }, error => console.log('ERROR ' + error + '\n' + error.stack));
