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
DEFAULT_COMPANY_SOURCE = ROOT.parent / "Planilha Monitoramento dos Atestados Médicos .xlsx"
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

MONTH_ALIASES = {
    "JAN": 1,
    "JANEIRO": 1,
    "FEV": 2,
    "FEVEREIRO": 2,
    "MAR": 3,
    "MARÇO": 3,
    "MARCO": 3,
    "ABR": 4,
    "ABRIL": 4,
    "MAI": 5,
    "MAIO": 5,
    "JUN": 6,
    "JUNHO": 6,
    "JUL": 7,
    "JULHO": 7,
    "AGO": 8,
    "AGOSTO": 8,
    "SET": 9,
    "SETEMBRO": 9,
    "OUT": 10,
    "OUTUBRO": 10,
    "NOV": 11,
    "NOVEMBRO": 11,
    "DEZ": 12,
    "DEZEMBRO": 12,
}

IMPORT_YEARS = {2025, 2026}
OPERATIONAL_FUNCTIONS = ("MOTORISTA", "COBRADOR")

SOURCE_OPERATION = "operacao"
SOURCE_COMPANY = "empresa"
SOURCE_CONSOLIDATED = "consolidado"

SOURCE_LABELS = {
    SOURCE_OPERATION: "Operação",
    SOURCE_COMPANY: "Empresa",
    SOURCE_CONSOLIDATED: "Consolidado",
}

IGNORED_COMPANY_SHEETS = {"atestados", "Plan1"}


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


def month_name(date_value: dt.date | None) -> str:
    if not date_value:
        return ""
    return MONTH_ORDER[date_value.month - 1]


def normalized_lookup(value: Any) -> str:
    return (
        text_value(value)
        .upper()
        .replace("Á", "A")
        .replace("À", "A")
        .replace("Â", "A")
        .replace("Ã", "A")
        .replace("É", "E")
        .replace("Ê", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ô", "O")
        .replace("Õ", "O")
        .replace("Ú", "U")
        .replace("Ç", "C")
    )


def is_operational_function(value: Any) -> bool:
    normalized = normalized_lookup(value)
    return any(re.search(rf"\b{function}\b", normalized) for function in OPERATIONAL_FUNCTIONS)


def record_year(record: dict[str, Any]) -> int | None:
    year = year_value(record.get("ano"))
    if year:
        return year
    for field in ("dataInicial", "dataRecebimento"):
        date_value = excel_date(record.get(field))
        if date_value:
            return date_value.year
    return None


def in_import_years(record: dict[str, Any]) -> bool:
    return record_year(record) in IMPORT_YEARS


def add_month(date_value: dt.date) -> dt.date:
    year = date_value.year + (1 if date_value.month == 12 else 0)
    month = 1 if date_value.month == 12 else date_value.month + 1
    return dt.date(year, month, 1)


def sheet_month_year(sheet_name: str, fallback: dt.date) -> dt.date:
    normalized = (
        re.sub(r"\s+", " ", sheet_name.upper().replace("Ç", "C"))
        .replace("(", " ")
        .replace(")", " ")
        .replace("-", " ")
        .strip()
    )
    parts = normalized.split()
    month = None
    year = None

    for part in parts:
        if part in MONTH_ALIASES:
            month = MONTH_ALIASES[part]
        elif re.fullmatch(r"\d{2,4}", part):
            number = int(part)
            year = 2000 + number if number < 100 else number

    if month and year:
        return dt.date(year, month, 1)
    if month:
        if fallback.month == month:
            return fallback
        return dt.date(fallback.year, month, 1)
    return fallback


def parse_period_dates(value: Any) -> tuple[dt.date | None, dt.date | None, str]:
    raw = period_value(value)
    date_value = excel_date(value)
    if date_value:
        return date_value, date_value, raw

    matches = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{2,5})", raw)
    dates: list[dt.date] = []
    for day, month, year in matches:
        year_number = int(year[:2] + year[-2:]) if len(year) > 4 and year.startswith("20") else int(year)
        if year_number < 100:
            year_number += 2000
        try:
            dates.append(dt.date(year_number, int(month), int(day)))
        except ValueError:
            continue

    if dates:
        return dates[0], dates[-1], raw
    return None, None, raw


def duration_value(value: Any) -> tuple[int, str, str]:
    raw = text_value(value)
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return int(float(raw)), "dias", raw
    if raw.casefold() == "horas":
        return 0, "horas", raw
    return 0, "indefinido", raw


def safe_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "sheet"


def cid_chapter(value: Any) -> str:
    text = text_value(value)
    normalized = text.casefold()
    if not text or "sem cid" in normalized or "não especificado" in normalized or "nao especificado" in normalized:
        return "CID Não especificado"

    match = re.search(r"\b([A-Z])\s*\.?\s*(\d{2})", text.upper())
    if not match:
        return "CID Não especificado"

    letter = match.group(1)
    number = int(match.group(2))
    if letter in {"A", "B"}:
        return "A00-B99 — Algumas doenças infecciosas e parasitárias"
    if letter == "C" or (letter == "D" and number <= 48):
        return "C00-D48 — Neoplasias (tumores)"
    if letter == "D":
        return "D50-D89 — Doenças do sangue e órgãos hematopoéticos"
    if letter == "E":
        return "E00-E90 — Doenças endócrinas, nutricionais e metabólicas"
    if letter == "F":
        return "F00-F99 — Transtornos mentais e comportamentais"
    if letter == "G":
        return "G00-G99 — Doenças do sistema nervoso"
    if letter == "H" and number <= 59:
        return "H00-H59 — Doenças do olho e anexos"
    if letter == "H":
        return "H60-H95 — Doenças do ouvido e da apófise mastoide"
    if letter == "I":
        return "I00-I99 — Doenças do aparelho circulatório"
    if letter == "J":
        return "J00-J99 — Doenças do aparelho respiratório"
    if letter == "K":
        return "K00-K93 — Doenças do aparelho digestivo"
    if letter == "L":
        return "L00-L99 — Doenças da pele e do tecido subcutâneo"
    if letter == "M":
        return "M00-M99 — Doenças do sistema osteomuscular e do tecido conjuntivo"
    if letter == "N":
        return "N00-N99 — Doenças do aparelho geniturinário"
    if letter == "O":
        return "O00-O99 — Gravidez, parto e puerpério"
    if letter == "P":
        return "P00-P96 — Afecções originadas no período perinatal"
    if letter == "Q":
        return "Q00-Q99 — Malformações congênitas"
    if letter == "R":
        return "R00-R99 — Sint sinais e achad anorm ex clín e laborat"
    if letter in {"S", "T"}:
        return "S00-T98 — Lesões, enven. e outras conseq. de causas ext."
    if letter in {"V", "W", "X", "Y"}:
        return "V01-Y98 — Causas externas de morbidade e mortalidade"
    if letter == "Z":
        return "Z00-Z99 — Contatos com serviços de saúde"
    return "CID Não especificado"


def record_dedupe_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        text_value(record.get("chapa")).casefold(),
        text_value(record.get("dataInicial")),
        text_value(record.get("dataFinal")),
    )


def normalize_main_record(row: dict[str, Any]) -> dict[str, Any]:
    start = excel_date(row.get("Data Inicial"))
    end = excel_date(row.get("Data Final"))
    total = int(number_value(row.get("Total no mês")))
    return {
        "id": f"atestados-{row['_excelRow']}",
        "excelRow": row["_excelRow"],
        "sourceSheet": " ATESTADOS GERAL",
        "origem": SOURCE_OPERATION,
        "origemLabel": SOURCE_LABELS[SOURCE_OPERATION],
        "dataRecebimento": "",
        "chapa": text_value(row.get("Chapa")),
        "nome": text_value(row.get("Nome")),
        "funcao": text_value(row.get("Função")),
        "periodo": period_value(row.get("Período")),
        "dataInicial": start.isoformat() if start else "",
        "dataFinal": end.isoformat() if end else "",
        "totalNoMes": total,
        "diasAfastamentoOriginal": str(total),
        "tipoDuracao": "dias",
        "ano": year_value(row.get("Ano")),
        "atestados": int(number_value(first_present(row, "Atestados", " Atestados"))),
        "mes": text_value(row.get("Mês")),
        "medico": text_value(row.get("Médico")),
        "crmMedico": "",
        "afastamentoInss": "",
        "capituloCid": text_value(row.get("Capítulo CID")),
        "subcategoriaCid": text_value(row.get("Subcategoria do CID")),
        "observacaoGestores": "",
        "tratativaSeguranca": "",
        "tratativaDiretoria": "",
        "tratativaJonilton": "",
    }


def normalize_away_record(row: dict[str, Any]) -> dict[str, Any]:
    start, end, _ = parse_period_dates(row.get("Período"))
    return {
        "id": f"afastados-{row['_excelRow']}",
        "excelRow": row["_excelRow"],
        "sourceSheet": "AFASTADOS",
        "origem": SOURCE_OPERATION,
        "origemLabel": SOURCE_LABELS[SOURCE_OPERATION],
        "colaborador": text_value(row.get("Colaboradores")),
        "chapa": text_value(row.get("Chapa")),
        "funcao": text_value(row.get("Função")),
        "periodo": period_value(row.get("Período")),
        "dataInicial": start.isoformat() if start else "",
        "dataFinal": end.isoformat() if end else "",
        "ano": start.year if start else year_value(row.get("Ano")),
        "total": int(number_value(row.get("Total"))),
        "mes": text_value(row.get("Mês")),
        "medico": text_value(row.get("Médico")),
        "capituloCid": text_value(row.get("Capitulo CID")),
        "subcategoriaCid": text_value(row.get("Subcategoria CID")),
    }


def normalize_company_record(sheet_name: str, sheet_reference: dt.date, row_num: int, cells: dict[str, Any]) -> dict[str, Any] | None:
    chapa = text_value(cells.get(cell_addr(2, row_num)))
    nome = text_value(cells.get(cell_addr(3, row_num)))
    if not chapa and not nome:
        return None
    if chapa.casefold() in {"chapa", "total"}:
        return None

    received = excel_date(cells.get(cell_addr(1, row_num)))
    start, end, periodo = parse_period_dates(cells.get(cell_addr(5, row_num)))
    total, duration_type, duration_raw = duration_value(cells.get(cell_addr(6, row_num)))
    reference_date = sheet_reference
    cid_text = text_value(cells.get(cell_addr(10, row_num)))

    return {
        "id": f"empresa-{safe_id(sheet_name)}-{row_num}",
        "excelRow": row_num,
        "sourceSheet": sheet_name,
        "origem": SOURCE_COMPANY,
        "origemLabel": SOURCE_LABELS[SOURCE_COMPANY],
        "dataRecebimento": received.isoformat() if received else "",
        "chapa": chapa,
        "nome": nome,
        "funcao": text_value(cells.get(cell_addr(4, row_num))),
        "periodo": periodo,
        "dataInicial": start.isoformat() if start else "",
        "dataFinal": end.isoformat() if end else "",
        "totalNoMes": total,
        "diasAfastamentoOriginal": duration_raw,
        "tipoDuracao": duration_type,
        "ano": reference_date.year if reference_date else None,
        "atestados": 1,
        "mes": month_name(reference_date),
        "medico": text_value(cells.get(cell_addr(7, row_num))),
        "crmMedico": text_value(cells.get(cell_addr(8, row_num))),
        "afastamentoInss": text_value(cells.get(cell_addr(9, row_num))),
        "capituloCid": cid_chapter(cid_text),
        "subcategoriaCid": cid_text or "Não especificado",
        "observacaoGestores": text_value(cells.get(cell_addr(11, row_num))),
        "tratativaSeguranca": text_value(cells.get(cell_addr(12, row_num))),
        "tratativaDiretoria": text_value(cells.get(cell_addr(13, row_num))),
        "tratativaJonilton": text_value(cells.get(cell_addr(14, row_num))),
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


def parse_company_records(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    sheet_summaries: list[dict[str, Any]] = []

    with zipfile.ZipFile(source) as zf:
        shared_strings = load_shared_strings(zf)
        sheets, _ = parse_workbook(zf)
        sheet_reference = dt.date(2022, 10, 1)

        for sheet_name, sheet_part in sheets.items():
            if sheet_name in IGNORED_COMPANY_SHEETS:
                sheet_summaries.append({"sheet": sheet_name, "records": 0, "imported": False})
                continue

            sheet_reference = sheet_month_year(sheet_name, sheet_reference)
            if sheet_reference.year not in IMPORT_YEARS:
                sheet_summaries.append({
                    "sheet": sheet_name,
                    "records": 0,
                    "imported": False,
                    "referenceMonth": sheet_reference.isoformat(),
                    "reason": "fora_do_recorte_2025_2026",
                })
                sheet_reference = add_month(sheet_reference)
                continue

            cells = sheet_cells(zf, sheet_part, shared_strings)
            if "chapa" not in text_value(cells.get("B2")).casefold() or "nome" not in text_value(cells.get("C2")).casefold():
                sheet_summaries.append({"sheet": sheet_name, "records": 0, "imported": False})
                sheet_reference = add_month(sheet_reference)
                continue

            row_numbers = [
                split_cell_ref(address)[1]
                for address, value in cells.items()
                if text_value(value)
            ]
            imported = 0
            operational_ignored = 0
            if row_numbers:
                for row_num in range(3, max(row_numbers) + 1):
                    record = normalize_company_record(sheet_name, sheet_reference, row_num, cells)
                    if not record:
                        continue
                    if is_operational_function(record.get("funcao")):
                        operational_ignored += 1
                        continue
                    records.append(record)
                    imported += 1

            sheet_summaries.append({
                "sheet": sheet_name,
                "records": imported,
                "imported": imported > 0,
                "operationalIgnored": operational_ignored,
                "referenceMonth": sheet_reference.isoformat(),
            })
            sheet_reference = add_month(sheet_reference)

    return records, sheet_summaries


def build_consolidated_records(operation_records: list[dict[str, Any]], company_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    consolidated = [dict(record, origemConsolidada=SOURCE_OPERATION) for record in operation_records]
    operation_keys = {record_dedupe_key(record) for record in operation_records if record_dedupe_key(record)[0]}

    for record in company_records:
        key = record_dedupe_key(record)
        if key[0] and key in operation_keys:
            continue
        consolidated.append(dict(record, origemConsolidada=SOURCE_COMPANY))

    return consolidated


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
        "porOrigem": group_metrics(records, "origemLabel"),
        "porTipoDuracao": group_metrics(records, "tipoDuracao"),
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


def validate_main(records: list[dict[str, Any]], total_row: dict[str, Any] | None, ignored_by_year: int = 0) -> dict[str, Any]:
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
        "anosImportados": sorted({record["ano"] for record in records if record.get("ano")}),
        "linhasForaDoRecorteIgnoradas": ignored_by_year,
    }

    if total_row and ignored_by_year == 0:
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
    elif total_row:
        checks.update(
            {
                "linhaTotalExcel": total_row.get("_excelRow"),
                "comparacaoLinhaTotalExcel": "ignorada_por_recorte_2025_2026",
            }
        )

    checks["status"] = "ok" if not missing and checks.get("somaDiasConfere", True) and checks.get("somaAtestadosConfere", True) else "atencao"
    return checks


def validate_company(records: list[dict[str, Any]], sheet_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    required = ["chapa", "nome", "funcao", "medico", "subcategoriaCid"]
    missing = {
        field: [f"{record['sourceSheet']}!{record['excelRow']}" for record in records if not text_value(record.get(field))]
        for field in required
    }
    missing = {field: rows[:50] for field, rows in missing.items() if rows}
    duration_counts = Counter(record["tipoDuracao"] for record in records)
    undated = [
        f"{record['sourceSheet']}!{record['excelRow']}"
        for record in records
        if not record["dataRecebimento"] and not record["dataInicial"]
    ]
    return {
        "registrosImportados": len(records),
        "somaDiasImportada": sum(record["totalNoMes"] for record in records),
        "somaAtestadosImportada": sum(record["atestados"] for record in records),
        "chapasUnicas": len({record["chapa"] for record in records if record["chapa"]}),
        "funcoesUnicas": len({record["funcao"] for record in records if record["funcao"]}),
        "abasImportadas": sum(1 for sheet in sheet_summaries if sheet["imported"]),
        "abasProcessadas": sum(1 for sheet in sheet_summaries if sheet["imported"] or sheet.get("operationalIgnored", 0)),
        "abasIgnoradas": [sheet["sheet"] for sheet in sheet_summaries if not sheet["imported"] and not sheet.get("operationalIgnored", 0)],
        "linhasOperacionaisIgnoradas": sum(sheet.get("operationalIgnored", 0) for sheet in sheet_summaries),
        "tiposDuracao": dict(duration_counts),
        "camposObrigatoriosVazios": missing,
        "linhasSemData": undated[:50],
        "alertas": {
            "camposObrigatoriosVazios": sum(len(rows) for rows in missing.values()),
            "linhasSemData": len(undated),
        },
        "status": "ok" if records else "nao_importado",
    }


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


def build_payload(source: Path, company_source: Path | None = DEFAULT_COMPANY_SOURCE) -> dict[str, Any]:
    with zipfile.ZipFile(source) as zf:
        shared_strings = load_shared_strings(zf)
        _, tables = parse_workbook(zf)

        if "Tabela324" not in tables:
            raise RuntimeError("Tabela324 nao encontrada no arquivo.")
        if "Tabela328" not in tables:
            raise RuntimeError("Tabela328 nao encontrada no arquivo.")

        main_rows = table_rows(zf, tables["Tabela324"], shared_strings)
        total_row = next((row for row in reversed(main_rows) if not text_value(row.get("Chapa"))), None)
        raw_main_records = [normalize_main_record(row) for row in main_rows if text_value(row.get("Chapa"))]
        main_records = [record for record in raw_main_records if in_import_years(record)]
        main_ignored_by_year = len(raw_main_records) - len(main_records)

        away_rows = table_rows(zf, tables["Tabela328"], shared_strings)
        raw_away_records = [normalize_away_record(row) for row in away_rows if text_value(row.get("Chapa"))]
        away_records = [record for record in raw_away_records if not record_year(record) or in_import_years(record)]
        away_ignored_by_year = len(raw_away_records) - len(away_records)

    company_records: list[dict[str, Any]] = []
    company_sheets: list[dict[str, Any]] = []
    if company_source and company_source.exists():
        company_records, company_sheets = parse_company_records(company_source)

    consolidated_records = build_consolidated_records(main_records, company_records)
    duplicated_by_period = len(company_records) + len(main_records) - len(consolidated_records)
    dashboard_records = consolidated_records if consolidated_records else main_records
    option_records = dashboard_records + away_records

    options = {
        "anos": sorted({record["ano"] for record in option_records if record.get("ano")}),
        "meses": unique_sorted(option_records, "mes"),
        "funcoes": unique_sorted(option_records, "funcao"),
        "chapas": sorted({record["chapa"] for record in option_records if record.get("chapa")}, key=str),
        "medicos": unique_sorted(option_records, "medico"),
        "capitulosCid": unique_sorted(option_records, "capituloCid"),
        "origens": [
            {"value": SOURCE_CONSOLIDATED, "label": SOURCE_LABELS[SOURCE_CONSOLIDATED]},
            {"value": SOURCE_OPERATION, "label": SOURCE_LABELS[SOURCE_OPERATION]},
            {"value": SOURCE_COMPANY, "label": SOURCE_LABELS[SOURCE_COMPANY]},
        ],
    }

    return {
        "metadata": {
            "sourceFile": str(source),
            "companySourceFile": str(company_source) if company_source else "",
            "generatedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "schemaVersion": 2,
            "importYears": sorted(IMPORT_YEARS),
            "companyOperationalFunctionsIgnored": list(OPERATIONAL_FUNCTIONS),
        },
        "sourceTables": {
            "atestados": {
                "sheet": " ATESTADOS GERAL",
                "table": "Tabela324",
                "records": len(main_records),
                "ignoredByYear": main_ignored_by_year,
            },
            "afastados": {
                "sheet": "AFASTADOS",
                "table": "Tabela328",
                "records": len(away_records),
                "ignoredByYear": away_ignored_by_year,
            },
            "funcionarios": {
                "sheet": "abas mensais",
                "table": "",
                "records": len(company_records),
                "operationalIgnored": sum(sheet.get("operationalIgnored", 0) for sheet in company_sheets),
                "sheets": company_sheets,
            },
            "consolidado": {
                "sheet": "Operação + Empresa",
                "table": "",
                "records": len(consolidated_records),
                "duplicadosPorChapaPeriodo": duplicated_by_period,
            },
        },
        "validation": {
            "atestados": validate_main(main_records, total_row, main_ignored_by_year),
            "funcionarios": validate_company(company_records, company_sheets) if company_records else {
                "registrosImportados": 0,
                "status": "nao_importado",
            },
            "consolidado": {
                "registrosImportados": len(consolidated_records),
                "duplicadosPorChapaPeriodo": duplicated_by_period,
                "status": "ok",
            },
            "qualidadeCid": cid_quality(main_records),
            "qualidadeCidConsolidado": cid_quality(dashboard_records),
        },
        "options": options,
        "aggregates": {
            "consolidado": main_aggregates(dashboard_records),
            "atestados": main_aggregates(main_records),
            "funcionarios": main_aggregates(company_records),
            "afastados": away_aggregates(away_records),
        },
        "records": {
            "consolidado": dashboard_records,
            "atestados": main_records,
            "funcionarios": company_records,
            "afastados": away_records,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa o Excel de atestados para JSON.")
    parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE), help="Caminho do arquivo .xlsx")
    parser.add_argument("--company-source", default=str(DEFAULT_COMPANY_SOURCE), help="Caminho da planilha geral de funcionarios")
    parser.add_argument("--no-company", action="store_true", help="Nao importa a planilha geral de funcionarios")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Arquivo JSON de saida")
    parser.add_argument("--check", action="store_true", help="Apenas valida a leitura, sem gravar JSON")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    company_source = None if args.no_company else Path(args.company_source).resolve()
    output = Path(args.output).resolve()

    if not source.exists():
        print(f"Arquivo Excel nao encontrado: {source}", file=sys.stderr)
        return 2
    if company_source and not company_source.exists():
        print(f"Planilha geral nao encontrada: {company_source}", file=sys.stderr)
        return 2

    payload = build_payload(source, company_source)
    validation = payload["validation"]["atestados"]
    company_validation = payload["validation"]["funcionarios"]
    consolidated_validation = payload["validation"]["consolidado"]

    print("Importacao analisada:")
    print(f"- registros de atestados: {payload['sourceTables']['atestados']['records']}")
    print(f"- registros gerais de funcionarios: {payload['sourceTables']['funcionarios']['records']}")
    print(f"- linhas operacionais ignoradas na Empresa: {company_validation.get('linhasOperacionaisIgnoradas', 0)}")
    print(f"- registros consolidados: {payload['sourceTables']['consolidado']['records']}")
    print(f"- registros de afastados: {payload['sourceTables']['afastados']['records']}")
    print(f"- dias importados: {validation['somaDiasImportada']}")
    print(f"- atestados importados: {validation['somaAtestadosImportada']}")
    print(f"- duplicados por chapa/periodo no consolidado: {consolidated_validation['duplicadosPorChapaPeriodo']}")
    print(f"- status operacao: {validation['status']}")
    print(f"- status funcionarios: {company_validation['status']}")

    if validation["status"] != "ok" or company_validation["status"] not in {"ok", "nao_importado"}:
        print(json.dumps(payload["validation"], ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    if not args.check:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON gerado em: {output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
