// New deep dive: title + slug + description → projects/<slug>/description.md, then the
// search stage starts in the background and the project page shows its progress.

const titleInput = document.getElementById('dive-title');
const slugInput = document.getElementById('dive-slug');
const textInput = document.getElementById('dive-text');
const status = document.getElementById('dive-status');
let slugEdited = false;

function slugify(text) {
  return text.toLowerCase().normalize('NFKD').replace(/[^\w\s-]/g, '')
    .trim().split(/[\s_-]+/).filter(Boolean).slice(0, 5).join('-');
}

titleInput.addEventListener('input', () => {
  if (!slugEdited) slugInput.value = slugify(titleInput.value);
});
slugInput.addEventListener('input', () => { slugEdited = true; });

document.getElementById('dive-form').addEventListener('submit', async event => {
  event.preventDefault();
  status.textContent = 'starting…';
  const {ok, result} = await postJSON('/api/deepdive/create', {
    slug: slugInput.value.trim(), title: titleInput.value, description: textInput.value});
  if (ok) { location.href = '/project/' + result.slug; return; }
  status.textContent = result.error || 'error';
  // the project exists even when the job couldn't start; its page can start it later
  if (result.error && result.error.includes('project created')) {
    setTimeout(() => { location.href = '/project/' + slugInput.value.trim(); }, 2500);
  }
});
