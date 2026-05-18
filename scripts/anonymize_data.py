from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "public" / "data" / "dashboard-data.json"
DEFAULT_OUTPUT = ROOT / "public" / "data" / "dashboard-data.demo.json"

sys.path.insert(0, str(ROOT))
from scripts.import_excel import away_aggregates, main_aggregates, unique_sorted  # noqa: E402


FIRST_NAMES = [
    "Alex",
    "Bruno",
    "Caio",
    "Daniel",
    "Eduardo",
    "Felipe",
    "Gabriel",
    "Hugo",
    "Igor",
    "Joao",
    "Lucas",
    "Marco",
    "Nicolas",
    "Otavio",
    "Paulo",
    "Rafael",
    "Sergio",
    "Tiago",
    "Victor",
    "William",
]

LAST_NAMES = [
    "Almeida",
    "Barros",
    "Campos",
    "Duarte",
    "Esteves",
    "Ferreira",
    "Gomes",
    "Henrique",
    "Lima",
    "Mendes",
    "Nunes",
    "Oliveira",
    "Pereira",
    "Rocha",
    "Santos",
    "Teixeira",
    "Vieira",
]

DOCTOR_NAMES = [
    "Dra. Ana Clinica",
    "Dr. Bruno Clinico",
    "Dra. Carla Clinica",
    "Dr. Daniel Clinico",
    "Dra. Elisa Clinica",
    "Dr. Fabio Clinico",
    "Dra. Helena Clinica",
    "Dr. Ivan Clinico",
    "Dra. Laura Clinica",
    "Dr. Marcos Clinico",
    "Dra. Natalia Clinica",
    "Dr. Pedro Clinico",
]


def fake_person(index: int, chapa: str) -> str:
    first = FIRST_NAMES[index % len(FIRST_NAMES)]
    last = LAST_NAMES[(index // len(FIRST_NAMES)) % len(LAST_NAMES)]
    return f"Colaborador {first} {last} - {chapa}"


def fake_chapa(index: int, original: str) -> str:
    prefix = "OF" if str(original).upper().startswith("OF") else "CH"
    return f"{prefix}{index + 1:04d}"


def anonymize(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    chapa_map: dict[str, str] = {}
    person_map: dict[str, str] = {}
    doctor_map: dict[str, str] = {}

    def mapped_chapa(original: str) -> str:
        if original not in chapa_map:
            chapa_map[original] = fake_chapa(len(chapa_map), original)
        return chapa_map[original]

    def mapped_person(original: str, chapa: str) -> str:
        if original not in person_map:
            person_map[original] = fake_person(len(person_map), chapa)
        return person_map[original]

    def mapped_doctor(original: str) -> str:
        if original not in doctor_map:
            doctor_map[original] = DOCTOR_NAMES[len(doctor_map) % len(DOCTOR_NAMES)]
        return doctor_map[original]

    for record in result["records"]["atestados"]:
        chapa = mapped_chapa(record["chapa"])
        record["chapa"] = chapa
        record["nome"] = mapped_person(record["nome"], chapa)
        record["medico"] = mapped_doctor(record["medico"])

    for record in result["records"]["afastados"]:
        chapa = mapped_chapa(record["chapa"])
        record["chapa"] = chapa
        record["colaborador"] = mapped_person(record["colaborador"], chapa)
        record["medico"] = mapped_doctor(record["medico"])

    main_records = result["records"]["atestados"]
    away_records = result["records"]["afastados"]

    result["options"] = {
        "anos": sorted({record["ano"] for record in main_records if record["ano"]}),
        "meses": unique_sorted(main_records + away_records, "mes"),
        "funcoes": unique_sorted(main_records + away_records, "funcao"),
        "chapas": sorted({record["chapa"] for record in main_records + away_records if record["chapa"]}, key=str),
        "medicos": unique_sorted(main_records + away_records, "medico"),
        "capitulosCid": unique_sorted(main_records + away_records, "capituloCid"),
    }
    result["aggregates"] = {
        "atestados": main_aggregates(main_records),
        "afastados": away_aggregates(away_records),
    }
    result["metadata"]["sourceFile"] = "dados-anonimizados-para-demonstracao"
    result["metadata"]["anonymized"] = True
    result["metadata"]["anonymizationNote"] = (
        "Nomes, chapas e medicos foram substituidos por valores ficticios. "
        "Totais, datas, funcoes e CID foram preservados para validacao visual."
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera uma base demonstrativa anonimizada.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    if not source.exists():
        raise FileNotFoundError(f"Base nao encontrada: {source}")

    payload = json.loads(source.read_text(encoding="utf-8"))
    demo = anonymize(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(demo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Base demonstrativa gerada em: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
