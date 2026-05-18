from __future__ import annotations

import argparse
import datetime as dt
import json
import posixpath
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "ATESTADOS OPERAÇÃO 2026 cópia.xlsx"
DEFAULT_OUTPUT = ROOT / "public" / "data" / "dashboard-data.json"

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
RID = f"{{{NS['r']}}}id"

MONTH_ORDER = [
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]


def read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(zf.read(name))


def resolve_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def rels_path(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def load_rels(zf: zipfile.ZipFile, part: str) -> dict[str, dict[str, str]]:
    rp = rels_path(part)
    if rp not in zf.namelist():
        return {}
    root = read_xml(zf, rp)
    result: dict[str, dict[str, str]] = {}
    for rel in root.findall("rel:Relationship", NS):
        result[rel.attrib["Id"]] = {
            "type": rel.attrib.get("Type", "").split("/")[-1],
            "target": resolve_target(part, rel.attrib.get("Target", "")),
        }
    return result


def col_to_num(col: str) -> int:
    value = 0
    for char in col.upper():
        value = value * 26 + ord(char) - 64
    return value


def num_to_col(num: int) -> str:
    value = ""
    while num:
        num, rem = divmod(num - 1, 26)
        value = chr(65 + rem) + value
    return value


def split_cell_ref(ref: str) -> tuple[int, int]:
    match = re.match(r"([A-Z]+)(\d+)$", ref)
    if not match:
        raise ValueError(f"Referencia de celula invalida: {ref}")
    return col_to_num(match.group(1)), int(match.group(2))


def cell_addr(col: int, row: int) -> str:
    return f"{num_to_col(col)}{row}"


def parse_range(ref: str) -> tuple[int, int, int, int]:
    start, end = ref.split(":")
    col1, row1 = split_cell_ref(start)
    col2, row2 = split_cell_ref(end)
    return col1, row1, col2, row2


def load_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = read_xml(zf, "xl/sharedStrings.xml")
    values = []
    for item in root.findall("m:si", NS):
        values.append("".join(text.text or "" for text in item.findall(".//m:t", NS)))
    return values


def cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//m:t", NS))

    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return None

    raw = value.text
    if cell_type == "s":
        return shared_strings[int(raw)]
    if cell_type == "b":
        return raw == "1"
    if re.fullmatch(r"-?\d+(\.\d+)?", raw):
        number = float(raw)
        return int(number) if number.is_integer() else number
    return raw


def excel_date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(value))).date()
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def period_value(value: Any) -> str:
    date_value = excel_date(value)
    if date_value:
        return date_value.strftime("%d/%m/%Y")
    return "" if value is None else str(value)


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def number_value(value: Any) -> float:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0


def first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row.get(key)
    return None


def year_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and value > 30000:
        date_value = excel_date(value)
        return date_value.year if date_value else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_main_record(row: dict[str, Any]) -> dict[str, Any]:
    start = excel_date(row.get("Data Inicial"))
    end = excel_date(row.get("Data Final"))
    return {
        "id": f"atestados-{row['_excelRow']}",
        "excelRow": row["_excelRow"],
        "chapa": text_value(row.get("Chapa")),
        "nome": text_value(row.get("Nome")),
        "funcao": text_value(row.get("Função")),
        "periodo": period_value(row.get("Período")),
        "dataInicial": start.isoformat() if start else "",
        "dataFinal": end.isoformat() if end else "",
        "totalNoMes": int(number_value(row.get("Total no mês"))),
        "ano": year_value(row.get("Ano")),
        "atestados": int(number_value(first_present(row, "Atestados", " Atestados"))),
        "mes": text_value(row.get("Mês")),
        "medico": text_value(row.get("Médico")),
        "capituloCid": text_value(row.get("Capítulo CID")),
        "subcategoriaCid": text_value(row.get("Subcategoria do CID")),
    }


def normalize_away_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"afastados-{row['_excelRow']}",
        "excelRow": row["_excelRow"],
        "colaborador": text_value(row.get("Colaboradores")),
        "chapa": text_value(row.get("Chapa")),
        "funcao": text_value(row.get("Função")),
        "periodo": period_value(row.get("Período")),
        "total": int(number_value(row.get("Total"))),
        "mes": text_value(row.get("Mês")),
        "medico": text_value(row.get("Médico")),
        "capituloCid": text_value(row.get("Capitulo CID")),
        "subcategoriaCid": text_value(row.get("Subcategoria CID")),
    }


def parse_workbook(zf: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    workbook = read_xml(zf, "xl/workbook.xml")
    workbook_rels = load_rels(zf, "xl/workbook.xml")
    sheets: dict[str, str] = {}
    tables: dict[str, dict[str, Any]] = {}

    for sheet in workbook.findall(".//m:sheets/m:sheet", NS):
        sheet_name = sheet.attrib["name"]
        sheet_part = workbook_rels[sheet.attrib[RID]]["target"]
        sheets[sheet_name] = sheet_part
        sheet_rels = load_rels(zf, sheet_part)
        for rel in sheet_rels.values():
            if rel["type"] != "table":
                continue
            table_root = read_xml(zf, rel["target"])
            table = {
                "name": table_root.attrib.get("name"),
                "displayName": table_root.attrib.get("displayName"),
                "ref": table_root.attrib["ref"],
                "part": rel["target"],
                "sheetName": sheet_name,
                "sheetPart": sheet_part,
            }
            tables[table["name"]] = table
            tables[table["displayName"]] = table

    return sheets, tables


def sheet_cells(zf: zipfile.ZipFile, sheet_part: str, shared_strings: list[str]) -> dict[str, Any]:
    root = read_xml(zf, sheet_part)
    return {
        cell.attrib["r"]: cell_value(cell, shared_strings)
        for cell in root.findall(".//m:c", NS)
        if "r" in cell.attrib
    }


def table_rows(zf: zipfile.ZipFile, table: dict[str, Any], shared_strings: list[str]) -> list[dict[str, Any]]:
    cells = sheet_cells(zf, table["sheetPart"], shared_strings)
    col1, row1, col2, row2 = parse_range(table["ref"])
    headers = [text_value(cells.get(cell_addr(col, row1))) for col in range(col1, col2 + 1)]
    rows: list[dict[str, Any]] = []
    for row_num in range(row1 + 1, row2 + 1):
        record = {
            headers[index]: cells.get(cell_addr(col1 + index, row_num))
            for index in range(len(headers))
        }
        record["_excelRow"] = row_num
        rows.append(record)
    return rows


def group_sum(records: list[dict[str, Any]], key: str, value: str, order: list[str] | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        label = text_value(record.get(key)) or "Nao informado"
        current = grouped.setdefault(label, {"label": label, "registros": 0, "valor": 0})
        current["registros"] += 1
        current["valor"] += number_value(record.get(value))

    values = list(grouped.values())
    if order:
        order_index = {label: index for index, label in enumerate(order)}
        return sorted(values, key=lambda item: order_index.get(item["label"], 999))
    return sorted(values, key=lambda item: (-item["valor"], item["label"]))


def group_metrics(records: list[dict[str, Any]], key: str, order: list[str] | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        label = text_value(record.get(key)) or "Nao informado"
        current = grouped.setdefault(label, {"label": label, "registros": 0, "dias": 0, "atestados": 0})
        current["registros"] += 1
        current["dias"] += int(number_value(record.get("totalNoMes")))
        current["atestados"] += int(number_value(record.get("atestados")))

    values = list(grouped.values())
    if order:
        order_index = {label: index for index, label in enumerate(order)}
        return sorted(values, key=lambda item: order_index.get(item["label"], 999))
    return sorted(values, key=lambda item: (-item["dias"], item["label"]))


def top_metrics(records: list[dict[str, Any]], key: str, limit: int = 15) -> list[dict[str, Any]]:
    return group_metrics(records, key)[:limit]


def top_count(records: list[dict[str, Any]], key: str, limit: int = 15) -> list[dict[str, Any]]:
    counts = Counter(text_value(record.get(key)) or "Nao informado" for record in records)
    return [{"label": label, "valor": count} for label, count in counts.most_common(limit)]


def unique_sorted(records: list[dict[str, Any]], key: str) -> list[str]:
    values = {text_value(record.get(key)) for record in records if text_value(record.get(key))}
    if key == "mes":
        month_index = {month: index for index, month in enumerate(MONTH_ORDER)}
        return sorted(values, key=lambda item: month_index.get(item, 999))
    return sorted(values, key=lambda item: item.casefold())


def main_aggregates(records: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [record["dataInicial"] for record in records if record["dataInicial"]]
    end_dates = [record["dataFinal"] for record in records if record["dataFinal"]]
    return {
        "registros": len(records),
        "dias": sum(record["totalNoMes"] for record in records),
        "atestados": sum(record["atestados"] for record in records),
        "chapasUnicas": len({record["chapa"] for record in records if record["chapa"]}),
        "colaboradoresUnicos": len({record["nome"] for record in records if record["nome"]}),
        "periodo": {
            "inicio": min(dates) if dates else "",
            "fim": max(end_dates) if end_dates else "",
        },
        "porAno": group_metrics(records, "ano"),
        "porMes": group_metrics(records, "mes", MONTH_ORDER),
        "porFuncao": group_metrics(records, "funcao"),
        "topColaboradores": top_metrics(records, "nome", 20),
        "topMedicos": top_count(records, "medico", 20),
        "topCapitulosCid": top_metrics(records, "capituloCid", 20),
        "topSubcategoriasCid": top_metrics(records, "subcategoriaCid", 20),
    }


def away_aggregates(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "registros": len(records),
        "dias": sum(record["total"] for record in records),
        "chapasUnicas": len({record["chapa"] for record in records if record["chapa"]}),
        "colaboradoresUnicos": len({record["colaborador"] for record in records if record["colaborador"]}),
        "medicosUnicos": len({record["medico"] for record in records if record["medico"]}),
        "porMes": group_sum(records, "mes", "total", MONTH_ORDER),
        "porFuncao": group_sum(records, "funcao", "total"),
        "topColaboradores": group_sum(records, "colaborador", "total")[:15],
        "topMedicos": top_count(records, "medico", 15),
        "topCapitulosCid": group_sum(records, "capituloCid", "total")[:15],
    }


def validate_main(records: list[dict[str, Any]], total_row: dict[str, Any] | None) -> dict[str, Any]:
    total_dias = sum(record["totalNoMes"] for record in records)
    total_atestados = sum(record["atestados"] for record in records)
    required = [
        "chapa",
        "nome",
        "funcao",
        "periodo",
        "dataInicial",
        "dataFinal",
        "mes",
        "medico",
        "capituloCid",
        "subcategoriaCid",
    ]
    missing = {
        field: [record["excelRow"] for record in records if not text_value(record.get(field))]
        for field in required
    }
    missing = {field: rows for field, rows in missing.items() if rows}

    checks = {
        "registrosImportados": len(records),
        "somaDiasImportada": total_dias,
        "somaAtestadosImportada": total_atestados,
        "camposObrigatoriosVazios": missing,
    }

    if total_row:
        expected_days = int(number_value(total_row.get("Total no mês")))
        expected_certificates = int(number_value(first_present(total_row, "Atestados", " Atestados")))
        checks.update(
            {
                "linhaTotalExcel": total_row.get("_excelRow"),
                "somaDiasEsperada": expected_days,
                "somaAtestadosEsperada": expected_certificates,
                "somaDiasConfere": total_dias == expected_days,
                "somaAtestadosConfere": total_atestados == expected_certificates,
            }
        )

    checks["status"] = "ok" if not missing and checks.get("somaDiasConfere", True) and checks.get("somaAtestadosConfere", True) else "atencao"
    return checks


def cid_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: defaultdict[str, set[str]] = defaultdict(set)
    for record in records:
        label = record["capituloCid"]
        key = re.sub(r"\s+", " ", label.casefold().replace("—", "-")).strip()
        normalized[key].add(label)
    variants = [sorted(values) for values in normalized.values() if len(values) > 1]
    return {
        "capitulosCidDistintos": len({record["capituloCid"] for record in records}),
        "subcategoriasCidDistintas": len({record["subcategoriaCid"] for record in records}),
        "possiveisVariacoesTextoCid": variants[:20],
    }


def build_payload(source: Path) -> dict[str, Any]:
    with zipfile.ZipFile(source) as zf:
        shared_strings = load_shared_strings(zf)
        _, tables = parse_workbook(zf)

        if "Tabela324" not in tables:
            raise RuntimeError("Tabela324 nao encontrada no arquivo.")
        if "Tabela328" not in tables:
            raise RuntimeError("Tabela328 nao encontrada no arquivo.")

        main_rows = table_rows(zf, tables["Tabela324"], shared_strings)
        total_row = next((row for row in reversed(main_rows) if not text_value(row.get("Chapa"))), None)
        main_records = [normalize_main_record(row) for row in main_rows if text_value(row.get("Chapa"))]

        away_rows = table_rows(zf, tables["Tabela328"], shared_strings)
        away_records = [normalize_away_record(row) for row in away_rows if text_value(row.get("Chapa"))]

    options = {
        "anos": sorted({record["ano"] for record in main_records if record["ano"]}),
        "meses": unique_sorted(main_records + away_records, "mes"),
        "funcoes": unique_sorted(main_records + away_records, "funcao"),
        "chapas": sorted({record["chapa"] for record in main_records + away_records if record["chapa"]}, key=str),
        "medicos": unique_sorted(main_records + away_records, "medico"),
        "capitulosCid": unique_sorted(main_records + away_records, "capituloCid"),
    }

    return {
        "metadata": {
            "sourceFile": str(source),
            "generatedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "schemaVersion": 1,
        },
        "sourceTables": {
            "atestados": {
                "sheet": " ATESTADOS GERAL",
                "table": "Tabela324",
                "records": len(main_records),
            },
            "afastados": {
                "sheet": "AFASTADOS",
                "table": "Tabela328",
                "records": len(away_records),
            },
        },
        "validation": {
            "atestados": validate_main(main_records, total_row),
            "qualidadeCid": cid_quality(main_records),
        },
        "options": options,
        "aggregates": {
            "atestados": main_aggregates(main_records),
            "afastados": away_aggregates(away_records),
        },
        "records": {
            "atestados": main_records,
            "afastados": away_records,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa o Excel de atestados para JSON.")
    parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE), help="Caminho do arquivo .xlsx")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Arquivo JSON de saida")
    parser.add_argument("--check", action="store_true", help="Apenas valida a leitura, sem gravar JSON")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()

    if not source.exists():
        print(f"Arquivo Excel nao encontrado: {source}", file=sys.stderr)
        return 2

    payload = build_payload(source)
    validation = payload["validation"]["atestados"]

    print("Importacao analisada:")
    print(f"- registros de atestados: {payload['sourceTables']['atestados']['records']}")
    print(f"- registros de afastados: {payload['sourceTables']['afastados']['records']}")
    print(f"- dias importados: {validation['somaDiasImportada']}")
    print(f"- atestados importados: {validation['somaAtestadosImportada']}")
    print(f"- status: {validation['status']}")

    if validation["status"] != "ok":
        print(json.dumps(validation, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    if not args.check:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON gerado em: {output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
