// project page while a job runs: progress line, then a poll that sees "done" reloads.
function log(label, value) { console.log(label + ': ' + JSON.stringify(value)); }
log('progress', byText(nodes.pipeline, 'P', 'recommendations')[0].text());
log('polling', intervals.length);
responses['/api/job'] = () => ({job: Object.assign({}, data.pipeline.job, {state: 'done'})});
intervals[0]().then(() => log('reload after done', calls), error => console.log('ERROR ' + error));
