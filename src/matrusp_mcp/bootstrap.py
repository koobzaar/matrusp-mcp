"""Gera um snapshot mínimo verificável para desenvolvimento e imagem Docker."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from pathlib import Path

from .bundles import derive_bundles
from .domain import Curriculum, CurriculumItem, Discipline, Meeting, Professor, Section, Unit
from .snapshot import SnapshotData, SnapshotMetadata, build_snapshot


def bootstrap_data() -> SnapshotData:
    observed = datetime(2026, 8, 25, tzinfo=UTC)
    first, last = date(2026, 8, 1), date(2026, 12, 20)
    sections = (
        Section(
            "section:MAC0101:20262A",
            "MAC0101",
            "20262A",
            "20262",
            first,
            last,
            "Teórica",
            "",
            "complete",
            (Meeting("mon", 600, 720, first, last, "10:00", "12:00"),),
            (Professor.from_source("(R) Ada Lovelace"),),
        ),
        Section(
            "section:MAC0101:20262P",
            "MAC0101",
            "20262P",
            "20262",
            first,
            last,
            "Prática",
            "",
            "complete",
            (Meeting("wed", 600, 720, first, last, "10:00", "12:00"),),
            (Professor.from_source("Grace Hopper"),),
            "20262A",
        ),
        Section(
            "section:MAC0102:20262A",
            "MAC0102",
            "20262A",
            "20262",
            first,
            last,
            "Teórica",
            "",
            "complete",
            (Meeting("tue", 480, 600, first, last, "08:00", "10:00"),),
            (Professor.from_source("Alan Turing"),),
        ),
    )
    metadata = SnapshotMetadata(
        "bootstrap-20260825",
        1,
        observed,
        observed,
        observed,
        "bootstrap",
        ("https://uspdigital.usp.br/jupiterweb/",),
    )
    units = (Unit("45", "Instituto de Matemática e Estatística", "São Paulo", None, "bootstrap"),)
    disciplines = (
        Discipline("MAC0101", "Introdução à Programação", "45", "Computação", "1", 4, 0),
        Discipline("MAC0102", "Cálculo Diferencial", "45", "Matemática", "1", 4, 0),
        Discipline(
            "MAC9999", "Tópicos sem oferta corrente", "45", "Computação", "1", 2, 0, is_stub=True
        ),
    )
    curriculum = Curriculum(
        "curriculum:CC:bacharelado",
        "CC",
        "bacharelado",
        "Ciência da Computação",
        "45",
        "São Paulo",
        "2026",
        (
            CurriculumItem("curriculum:CC:bacharelado", "1", "MAC0101", "obrigatoria"),
            CurriculumItem("curriculum:CC:bacharelado", "1", "MAC0102", "obrigatoria"),
        ),
    )
    return SnapshotData(
        metadata, units, disciplines, sections, derive_bundles(sections), (curriculum,)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_snapshot(bootstrap_data(), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
