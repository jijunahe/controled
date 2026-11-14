"""Catálogo visual. No se guarda hasta que el usuario pulsa Guardar."""

from __future__ import annotations

PATTERN_CATALOG: list[dict] = [
    {
        "id": "nv-rojo-verde",
        "group": "Navidad",
        "name": "Rojo y verde",
        "fx": 0,
        "bands": [
            {"hex": "#C8102E", "weight": 1},
            {"hex": "#006747", "weight": 1},
        ],
    },
    {
        "id": "nv-guirnalda",
        "group": "Navidad",
        "name": "Guirnalda",
        "fx": 13,
        "bands": [
            {"hex": "#C8102E", "weight": 1},
            {"hex": "#D4AF37", "weight": 1},
            {"hex": "#006747", "weight": 1},
        ],
    },
    {
        "id": "nv-nieve",
        "group": "Navidad",
        "name": "Nieve",
        "fx": 2,
        "bands": [{"hex": "#F4F7FB", "weight": 1}],
    },
    {
        "id": "nv-oro",
        "group": "Navidad",
        "name": "Oro y rojo",
        "fx": 12,
        "bands": [
            {"hex": "#D4AF37", "weight": 1},
            {"hex": "#C8102E", "weight": 1},
        ],
    },
    {
        "id": "flag-colombia",
        "group": "Equipos y banderas",
        "name": "Colombia",
        "fx": 0,
        "bands": [
            {"hex": "#FCD116", "weight": 2},
            {"hex": "#003893", "weight": 1},
            {"hex": "#CE1126", "weight": 1},
        ],
    },
    {
        "id": "flag-millonarios",
        "group": "Equipos y banderas",
        "name": "Millonarios",
        "fx": 0,
        "bands": [
            {"hex": "#003DA5", "weight": 1},
            {"hex": "#FFFFFF", "weight": 1},
        ],
    },
    {
        "id": "flag-santafe",
        "group": "Equipos y banderas",
        "name": "Santa Fe",
        "fx": 0,
        "bands": [
            {"hex": "#E10600", "weight": 1},
            {"hex": "#FFFFFF", "weight": 1},
        ],
    },
    {
        "id": "flag-nacional",
        "group": "Equipos y banderas",
        "name": "Nacional",
        "fx": 0,
        "bands": [
            {"hex": "#006633", "weight": 1},
            {"hex": "#FFFFFF", "weight": 1},
        ],
    },
    {
        "id": "flag-america",
        "group": "Equipos y banderas",
        "name": "América de Cali",
        "fx": 0,
        "bands": [{"hex": "#D2122E", "weight": 1}],
    },
    {
        "id": "flag-junior",
        "group": "Equipos y banderas",
        "name": "Junior",
        "fx": 0,
        "bands": [
            {"hex": "#E03A3E", "weight": 1},
            {"hex": "#FFFFFF", "weight": 1},
        ],
    },
    {
        "id": "flag-argentina",
        "group": "Equipos y banderas",
        "name": "Argentina",
        "fx": 0,
        "bands": [
            {"hex": "#74ACDF", "weight": 1},
            {"hex": "#FFFFFF", "weight": 1},
            {"hex": "#74ACDF", "weight": 1},
        ],
    },
    {
        "id": "flag-brasil",
        "group": "Equipos y banderas",
        "name": "Brasil",
        "fx": 0,
        "bands": [
            {"hex": "#009C3B", "weight": 1},
            {"hex": "#FFDF00", "weight": 1},
            {"hex": "#002776", "weight": 1},
        ],
    },
    {
        "id": "flag-mexico",
        "group": "Equipos y banderas",
        "name": "México",
        "fx": 0,
        "bands": [
            {"hex": "#006847", "weight": 1},
            {"hex": "#FFFFFF", "weight": 1},
            {"hex": "#CE1126", "weight": 1},
        ],
    },
    {
        "id": "flag-espana",
        "group": "Equipos y banderas",
        "name": "España",
        "fx": 0,
        "bands": [
            {"hex": "#AA151B", "weight": 1},
            {"hex": "#F1BF00", "weight": 2},
            {"hex": "#AA151B", "weight": 1},
        ],
    },
]

QUICK_EFFECTS = [
    (0, "Sólido"),
    (2, "Respiración"),
    (3, "Barrido"),
    (9, "Arcoíris"),
    (12, "Fundido"),
    (13, "Teatro"),
    (1, "Parpadeo"),
    (15, "Carrera"),
]


def stripe_style(bands: list[dict]) -> str:
    total = sum(int(band["weight"]) for band in bands) or 1
    cursor = 0.0
    stops: list[str] = []
    for band in bands:
        end = cursor + 100.0 * int(band["weight"]) / total
        stops.append(f"{band['hex']} {cursor:.2f}% {end:.2f}%")
        cursor = end
    return "linear-gradient(90deg, " + ", ".join(stops) + ")"


def catalog_groups() -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for item in PATTERN_CATALOG:
        card = dict(item)
        card["stripe"] = stripe_style(item["bands"])
        groups.setdefault(item["group"], []).append(card)
    return [{"name": name, "items": items} for name, items in groups.items()]
