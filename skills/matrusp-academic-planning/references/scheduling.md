# MatrUSP scheduling semantics

Use this reference when exact temporal, generation, ranking, or constraint behavior matters.

## Scheduling units

A bundle is the normal selectable unit. Its meetings are evaluated together.

A section is a lower-level offering component. Use section IDs directly only when the task genuinely concerns a specific component rather than the selectable bundle containing it.

## Temporal states

MatrUSP distinguishes:

- `no_conflict`: available data establishes compatibility;
- `conflict`: available data establishes an overlap;
- `unknown`: available data is insufficient to establish compatibility or conflict.

Never treat `unknown` as `no_conflict`.

Schedule generation is conservative: candidates with incomplete/unknown temporal quality or unknown conflict relations can be excluded instead of being treated as valid.

Therefore, zero generated schedules does not by itself prove mathematical impossibility. Relevant causes can include actual conflicts, schedule quality, unknown relations, hard constraints, or generation limits.

## Existing bundles versus manual blocks

`existing_bundle_ids` represent already selected MatrUSP bundles.

They participate in conflict detection and remain part of the selected schedule used to calculate metrics such as active days and gaps.

Manual `blocks` represent occupied time intervals that cannot or should not be represented as MatrUSP bundles.

They participate in conflict detection but are not themselves bundles used by the schedule metric calculation.

Consequently, metrics returned when the user's existing schedule is represented only by manual blocks do not necessarily describe the user's complete weekly schedule.

The same distinction applies when `compare_schedules` receives manual blocks: blocks affect temporal state, while bundle metrics are computed from the alternative's bundles.

## Generation

`generate_schedules` accepts one or more required discipline codes. For each required discipline it considers eligible current bundles and searches combinations without established conflicts.

`allowed_bundle_ids` restricts the candidate bundle pool. Use it only when a specific set of bundles is intended to be eligible.

`existing_bundle_ids` adds existing selections to every generated alternative.

`blocks` add manual occupied intervals that generated candidates must not conflict with.

The generator returns top-K schedules and diagnostic fields including:

- `truncated`;
- `explored_nodes`;
- `discard_reasons`.

Treat these diagnostics as relevant when making claims about exhaustiveness or impossibility.

## Ranking

For a selected set of bundles, MatrUSP calculates metrics including:

- `active_days`;
- `total_gap_hours`;
- `hours_outside_preferred_windows`;
- matches with avoided professors;
- matches with preferred professors.

The score is weighted:

```text
score =
    days_weight * active_days
  + gaps_weight * total_gap_hours
  + outside_preferred_windows_weight * hours_outside_preferred_windows
  + avoided_professors_weight * avoided_professor_matches
  - preferred_professors_weight * preferred_professor_matches
```

Lower score is better.

Weights express a tradeoff. They do not by themselves create lexicographic optimization. When exact priority ordering matters, choose an approach that actually preserves that ordering rather than assuming an arbitrary weight ratio is mathematically equivalent.

If a preferred-window or professor list is supplied while its corresponding weight is zero, the service assigns that criterion a nonzero default contribution. Do not assume a populated preference list with zero weight is ignored.

## Gap metric

Gap time is calculated from the normalized union of selected bundle meetings, grouped by day, as the positive time between consecutive meeting ranges.

Manual blocks are not included in this metric.

## Hard constraints

The current generator recognizes these scheduling hard-constraint concepts:

- `forbidden_days`;
- `required_days`;
- `max_active_days`;
- `max_total_gap_hours`.

Use only fields supported by the tool contract. Do not invent additional hard-constraint keys.

`forbidden_days` filters generated candidate bundles that meet on those days. It does not retroactively remove supplied existing bundles or manual blocks.

`required_days` means that the resulting selected bundle schedule must include those days. It does not mean that those are the only permitted days.

`max_active_days` and `max_total_gap_hours` constrain the metrics of the selected bundle schedule.

## Preferred windows

Preferred windows affect ranking rather than conflict validity.

A meeting contributes outside-preferred-window time when it is not fully contained in an applicable preferred window for that day.

Do not use preferred windows as a substitute for a hard availability restriction when the user's requirement is absolute.

## Comparing alternatives

`compare_schedules` checks each supplied bundle alternative against optional manual blocks, then computes the same scheduling metrics and weighted score for its bundles.

It does not sort alternatives. Interpret the returned `state`, score, and metrics explicitly.

A `conflict` or `unknown` alternative should not be presented as an established valid schedule merely because its numerical score is attractive.
