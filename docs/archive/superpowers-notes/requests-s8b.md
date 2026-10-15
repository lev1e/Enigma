# Requests from S8B
- detectors.py / service (S8A or orchestrator): surface `ner.take_notes()` as a visible job note. ner.person_spans now records a note (text > ner.MAX_TEXT = 50 MB, or model unavailable) instead of skipping silently; call `ner.take_notes()` once per job (after scanning) and append the strings to the job warnings. The existing `self.ner_unavailable` flag keeps working unchanged.
- MAX_TEXT 400k skip is gone: scan units between 400k and 1.5M chars (detectors.CHUNK_THRESHOLD) now get NER. Nothing to change on your side.
