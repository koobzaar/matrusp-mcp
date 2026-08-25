"""Derivação estável de alternativas selecionáveis a partir das turmas."""

from __future__ import annotations

from collections import defaultdict

from .domain import Bundle, Section


def derive_bundles(sections: tuple[Section, ...] | list[Section]) -> tuple[Bundle, ...]:
    ordered = sorted(sections, key=lambda item: item.id)
    by_code = {(item.discipline_code, item.section_code): item for item in ordered}
    practices_by_theory: dict[tuple[str, str], list[Section]] = defaultdict(list)
    for item in ordered:
        if item.linked_theory_section_code is not None:
            practices_by_theory[(item.discipline_code, item.linked_theory_section_code)].append(
                item
            )

    bundles: list[Bundle] = []
    linked_practices: set[str] = set()
    for key in sorted(practices_by_theory, key=lambda item: (by_code.get(item) is None, item)):
        practices = sorted(practices_by_theory[key], key=lambda item: item.section_code)
        theory = by_code.get(key)
        for practice in practices:
            linked_practices.add(practice.id)
            if theory is None:
                bundles.append(
                    Bundle(
                        id=f"bundle:{practice.discipline_code}:{practice.section_code}",
                        discipline_code=practice.discipline_code,
                        section_ids=(practice.id,),
                        meetings=practice.meetings,
                        professors=practice.professors,
                        selectable=False,
                        schedule_status=practice.schedule_status,
                        data_quality_flags=("orphan_practice_link",),
                    )
                )
                continue
            flags = tuple(sorted(set(theory.data_quality_flags + practice.data_quality_flags)))
            status = (
                "complete"
                if theory.schedule_status == practice.schedule_status == "complete"
                else "partial"
            )
            bundles.append(
                Bundle(
                    id=f"bundle:{practice.discipline_code}:{theory.section_code}+{practice.section_code}",
                    discipline_code=practice.discipline_code,
                    section_ids=(theory.id, practice.id),
                    meetings=theory.meetings + practice.meetings,
                    professors=theory.professors + practice.professors,
                    # Partial or unknown schedules are queryable for provenance but
                    # never selectable by temporal search or combinations.
                    selectable=theory.schedule_status == "complete"
                    and practice.schedule_status == "complete",
                    schedule_status=status,
                    data_quality_flags=flags,
                )
            )

    for section in ordered:
        if section.id in linked_practices:
            continue
        if practices_by_theory.get((section.discipline_code, section.section_code)):
            continue
        flags = tuple(section.data_quality_flags)
        selectable = section.schedule_status == "complete" and not any(
            flag in {"theory_without_practice", "orphan_theory_link"} for flag in flags
        )
        bundles.append(
            Bundle(
                id=f"bundle:{section.discipline_code}:{section.section_code}",
                discipline_code=section.discipline_code,
                section_ids=(section.id,),
                meetings=section.meetings,
                professors=section.professors,
                selectable=selectable,
                schedule_status=section.schedule_status,
                data_quality_flags=flags,
            )
        )
    return tuple(bundles)
