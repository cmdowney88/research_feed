// project page at the seed checkpoint: untick one proposed seed, tick one related, confirm.
function log(label, value) { console.log(label + ': ' + JSON.stringify(value)); }
const panel = nodes.pipeline;
log('checkpoint shown', panel.text().includes('Checkpoint: confirm the seeds'));
const boxes = panel.querySelectorAll('input[type=checkbox]');
log('ticked by default', boxes.filter(box => box.checked).length);
boxes[0].checked = false;
boxes[boxes.length - 1].checked = true;
byText(panel, 'BUTTON', 'Confirm seeds')[0].listeners.click()
  .then(() => log('confirm', {url: calls[0], ids: bodies[0].paperIds.length,
                              project: bodies[0].project, reloaded: calls.includes('reload')}),
        error => console.log('ERROR ' + error));
