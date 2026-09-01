# MatrUSP tool semantics

Use this reference when choosing between operations or when exact tool behavior affects the answer. Academic facts come from tool results, not from this file.

## `search_offerings`

Searches current offering bundles by discipline text, professor, campus, unit, department, day, and optional time interval.

Use it primarily for discovery when the exact discipline code or offering is not yet known.

Important semantics:

- Text search can return several different disciplines with similar or identical names.
- `days` matches when at least one meeting occurs on one of the requested days.
- With `window_mode="overlaps"`, at least one relevant meeting must overlap the interval.
- With `window_mode="contained"`, every meeting in the returned bundle must lie within the requested clock interval. If `days` is also supplied, day matching and time containment are separate conditions; containment does not mean every meeting occurs on the requested day.
- By default, incomplete or unknown scheduling data is excluded. `include_unknown` broadens the result set and can expose lower-quality or nonselectable data, so preserve returned warnings and quality fields.
- Pagination uses `next_cursor`; do not assume the first page is exhaustive when a cursor is present.

If curriculum context determines which same-named discipline is intended, resolve that context instead of selecting by text match alone.

## `get_discipline`

Retrieves one exact discipline by code with rich discipline data, current bundles, offering history, curriculum memberships, and related section information.

Use it when rich details of a known discipline can affect the answer.

Do not confuse curriculum membership returned here with curriculum-specific prerequisite structure. Prerequisites belong to curriculum items and are exposed by `get_curriculum`.

## `search_curricula`

Discovers current curricula by course or curriculum text, unit, and campus.

Use it to resolve the correct `curriculum_id` when the user names a course or habilitation rather than an exact curriculum identifier.

A search result identifies the curriculum but does not contain its discipline structure.

## `get_curriculum`

Retrieves a curriculum and its items.

Each item includes the discipline identity and curriculum-specific information such as:

- curriculum item type;
- ideal period;
- aula/work credits;
- prerequisites;
- `has_current_offer`.

This makes `get_curriculum` useful for candidate discovery and filtering, not only for answering curriculum questions.

`has_current_offer=true` means that at least one selectable current bundle exists for that discipline. It does not establish complete schedule quality, registration eligibility, vacancy access, or prerequisite fulfillment.

## `find_gap_fillers`

Finds bundles relative to one explicit day/time window while excluding candidates that conflict with supplied bundle or section selections.

With `window_mode="contained"`, the candidate bundle must have meetings and every meeting must occur on the requested day and fit completely inside the interval.

With `window_mode="overlaps"`, at least one candidate meeting must overlap the interval.

Candidates with conflict or unknown temporal relation to the supplied selections are excluded.

Use this operation for genuine window-filling questions. Its `contained` semantics are intentionally stricter than a search for a bundle that merely has one meeting in the window.

## `check_schedule_conflicts`

Checks pairwise temporal relations among supplied bundle IDs, section IDs, and manual blocks.

Returns:

- overall `state`;
- concrete conflicting pairs and meetings;
- `unknown_pairs` when available data cannot establish a relation.

The relevant states are `no_conflict`, `conflict`, and `unknown`.

Use it when the task is to validate a known selection or identify the meetings responsible for a conflict. It is not necessary merely to revalidate combinations already accepted by schedule generation.

## `generate_schedules`

Generates deterministic top-K schedules for a set of required discipline codes, selecting among their eligible bundles.

Inputs can restrict or augment the search with:

- `allowed_bundle_ids`;
- `existing_bundle_ids`;
- manual `blocks`;
- preferences;
- hard constraints;
- generation limits.

The generator normally considers selectable bundles with complete schedule data. Conflicting and temporally unknown candidates are discarded rather than presented as valid schedules.

The returned schedules are ranked by the generator's score. Inspect `warnings`, `discard_reasons`, and `truncated` when absence of results or completeness of the search matters.

Generation answers bundle-selection problems among required disciplines. It does not currently express a generic requirement such as "choose one discipline from this arbitrary optional set" in one operation, so candidate filtering may still be necessary before generation.

See `scheduling.md` for exact ranking and constraint semantics.

## `compare_schedules`

Evaluates concrete alternatives, where each alternative is a list of bundle IDs, under one common preference model and optional manual blocks.

For each alternative it returns temporal state, score, and metrics.

The output preserves the input alternative order. Do not assume the tool sorts alternatives from best to worst; compare their returned scores and states.

Use it when already known alternatives need a consistent evaluation. Avoid using it solely to recompute the same metrics already obtained from schedule generation under unchanged preferences.
