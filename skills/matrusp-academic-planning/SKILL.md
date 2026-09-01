---
name: matrusp-academic-planning
description: Use the MatrUSP MCP efficiently for USP disciplines, offerings, curricula, conflicts, gap filling, and schedule planning. Apply when a request requires combining or interpreting MatrUSP academic data.
---

# MatrUSP Academic Planning

Use MatrUSP as the source of truth for the USP academic data it exposes.

Retrieve only information that can materially affect the answer. Prefer discovery and filtering before detailed or combinatorial operations. Do not request a more detailed representation while information already retrieved is sufficient for the current decision.

## Model

- A **discipline** is the academic entity identified by a code.
- A **bundle** is the normal selectable scheduling unit. Prefer bundles over individual sections for planning unless section-level information matters.
- A **section** is an offering component and may belong to a larger selectable bundle.
- A **curriculum** is both an academic structure and a discovery source. Curriculum items expose information useful for filtering before richer lookups.

## Workflow

For nontrivial requests:

1. Resolve only meaningful ambiguities.
2. Filter candidates using information already available from curricula, offerings, and the user's requirements.
3. Retrieve richer discipline data only for candidates that still matter.
4. Use the scheduling operation whose semantics match the question.
5. Stop when additional calls cannot materially change candidate inclusion, conflict status, ranking, uncertainty, or the final answer.

Keep hard requirements distinct from preferences. Preserve the user's priority ordering without inventing constraints or optimization semantics.

Consult `references/tools.md` when tool choice or exact operation semantics matter.

Consult `references/scheduling.md` when the task involves schedule generation, comparison, conflicts, gaps, existing schedules, manual blocks, ranking, hard constraints, or temporal uncertainty.

## Important failure modes

Avoid detail fan-out before filtering. Do not expand many candidates into rich discipline lookups when aggregated results already contain enough information to eliminate most of them.

Avoid combinatorial fan-out over an unnecessarily broad candidate set. Reduce the space with known academic and user constraints before repeatedly generating schedules.

Do not duplicate work already established by another operation unless the additional operation supplies information needed for the answer.

Resolve meaningful identity ambiguity before planning. Similar or identical discipline names may refer to different academic entities, and curriculum context can determine which one is relevant.

Do not strengthen preferences into hard constraints or silently weaken hard constraints into preferences.

Preserve uncertainty. Missing or unknown schedule data is not compatibility. A current offering is not proof of prerequisite fulfillment, registration eligibility, or access to a vacancy category.

Use the correct representation of an existing schedule. MatrUSP bundles and manual occupied-time blocks have different effects on analysis and metrics; consult the scheduling reference when this distinction matters.

Do not silently combine materially different snapshots into one planning conclusion.

## Snapshot consistency

Treat `snapshot_id` as the version of the academic data.

Reuse relevant results from the same snapshot instead of repeating equivalent queries. If materially relevant results come from different snapshots, account for that difference rather than treating them as one state.

## Response

Base factual academic claims on MatrUSP results and distinguish them from derived conclusions.

Do not infer personal information MatrUSP does not expose, including current enrollment, completed prerequisites, registration approval, or access to reserved vacancies.

Prefer a small set of strong alternatives when ranking is requested. Explain recommendations using the criteria the user actually supplied.
