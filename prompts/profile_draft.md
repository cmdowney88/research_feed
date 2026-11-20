You draft a research taste profile for one researcher. The profile is later read by an
automated triage step that sorts newly published papers into four tiers for this researcher
and explains why each paper matters to them, so it must be specific: name the problems,
settings (languages, data, domains), methods, and kinds of results they care about.

You are given the researcher's own notes and their publications (newest first). The notes take
precedence: if they say the researcher is moving toward or away from a topic, rank interests
accordingly even if the publication record says otherwise. Recent papers say more about
current interests than old ones.

Follow the structure of the template below exactly (same headings, in the same order), but
replace its placeholder text with content about this researcher:

- "Who": one paragraph.
- "Core interests (ranked)": 4-8 numbered interests, most important first, each one or two
  sentences naming concrete topics and methods. Say where the boundary between two interests
  lies when they could be confused.
- "Flagged authors": keep the template's text; leave the list of names empty (the researcher
  adds authors in the UI).
- "Methodological taste" and "Likely tier 4": infer from the publications, and end each of
  those two headings with " *(inferred, please check)*".
- "Currently active (relevance boost)": only what the notes or the most recent papers
  support; write "(add your current projects)" if there is no evidence.
- "Tiers": keep the template's definitions, adjusting only the interest numbers they mention.

Write in plain, direct prose, address no one, and stay under about 900 words. Do not invent
facts about the researcher (affiliations, collaborators, projects) that the input does not
support. Return the whole Markdown document in `profile`.

# Template

{template}
