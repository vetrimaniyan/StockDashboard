"""Export writers (SRS section 8).

FR-9.6: every export carries data_as_of, generation timestamp, screen name and
version, and the universe definition. An undated screen export is
indistinguishable from a stale one a week later.
"""

from __future__ import annotations

import csv
import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from alpha500.config import settings
from alpha500.metrics import registry

DISCLAIMER = (
    "Computed estimates for planning purposes. Not investment or tax advice, "
    "and not a substitute for professional advice."
)


@dataclass(frozen=True, slots=True)
class Provenance:
    screen_name: str
    screen_version: int
    definition: dict[str, Any]
    data_as_of: date | None
    generated_at: datetime
    universe: str
    row_count: int

    def as_rows(self) -> list[tuple[str, str]]:
        return [
            ("Screen name", self.screen_name),
            ("Screen version", str(self.screen_version)),
            ("Data as of", str(self.data_as_of)),
            ("Generated at", self.generated_at.isoformat(timespec="seconds")),
            ("Universe", self.universe),
            ("Row count", str(self.row_count)),
            ("Disclaimer", DISCLAIMER),
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "screen_name": self.screen_name,
            "screen_version": self.screen_version,
            "definition": self.definition,
            "data_as_of": str(self.data_as_of),
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
            "universe": self.universe,
            "row_count": self.row_count,
            "disclaimer": DISCLAIMER,
        }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "screen"


def build_filename(screen_name: str, data_as_of: date | None,
                   generated_at: datetime, ext: str) -> str:
    """FR-9.7: ``{slug}_{data_as_of:YYYYMMDD}_{generated:HHMMSS}.{ext}``."""
    as_of = data_as_of.strftime("%Y%m%d") if data_as_of else "nodate"
    return f"{_slug(screen_name)}_{as_of}_{generated_at.strftime('%H%M%S')}.{ext}"


def _provenance(
    screen_name: str, definition: dict[str, Any], data_as_of: date | None, rows: int
) -> Provenance:
    universe = str((definition.get("universe") or {}).get("index", settings.index_name))
    return Provenance(
        screen_name=screen_name,
        screen_version=int(definition.get("version", 1)),
        definition=definition,
        data_as_of=data_as_of,
        generated_at=datetime.now(),
        universe=universe,
        row_count=rows,
    )


def export_csv(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
    screen_name: str,
    definition: dict[str, Any],
    data_as_of: date | None,
    out_dir: Path | None = None,
) -> Path:
    """FR-9.4: UTF-8 with BOM, ISO dates, raw numerics, sidecar metadata."""
    prov = _provenance(screen_name, definition, data_as_of, len(rows))
    out_dir = out_dir or settings.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / build_filename(screen_name, data_as_of, prov.generated_at, "csv")

    # BOM so Excel opens it as UTF-8 rather than the system codepage.
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    c: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                    for c, v in row.items()
                    if c in set(columns)
                }
            )

    sidecar = path.with_suffix(".meta.json")
    sidecar.write_text(json.dumps(prov.as_dict(), indent=2), encoding="utf-8")
    return path


def export_xlsx(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
    screen_name: str,
    definition: dict[str, Any],
    data_as_of: date | None,
    out_dir: Path | None = None,
) -> Path:
    """FR-9.3: three sheets, correct numeric types, native table with autofilter."""
    import xlsxwriter

    prov = _provenance(screen_name, definition, data_as_of, len(rows))
    out_dir = out_dir or settings.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / build_filename(screen_name, data_as_of, prov.generated_at, "xlsx")

    book = xlsxwriter.Workbook(str(path), {"default_date_format": "yyyy-mm-dd"})
    header_fmt = book.add_format({"bold": True, "bg_color": "#1a2330", "font_color": "#ffffff"})
    pct_fmt = book.add_format({"num_format": "0.00%"})
    inr_fmt = book.add_format({"num_format": '₹#,##0.00'})
    int_fmt = book.add_format({"num_format": "#,##0"})
    wrap_fmt = book.add_format({"text_wrap": True, "valign": "top"})

    def fmt_for(column: str):  # type: ignore[no-untyped-def]
        unit = registry.get(column).unit if registry.get(column) else None
        if unit == "percent":
            return pct_fmt
        if unit == "currency":
            return inr_fmt
        if unit == "integer":
            return int_fmt
        return None

    sheet = book.add_worksheet("Screen Results")
    sheet.freeze_panes(1, 1)
    for col_index, column in enumerate(columns):
        definition_entry = registry.get(column)
        sheet.write(0, col_index, definition_entry.label if definition_entry else column,
                    header_fmt)
        sheet.set_column(col_index, col_index, 16, fmt_for(column))

    for row_index, row in enumerate(rows, start=1):
        for col_index, column in enumerate(columns):
            value = row.get(column)
            if isinstance(value, (date, datetime)):
                sheet.write_datetime(row_index, col_index, value)
            elif isinstance(value, bool):
                sheet.write_boolean(row_index, col_index, value)
            elif value is None:
                sheet.write_blank(row_index, col_index, None)
            elif isinstance(value, (int, float)):
                # Never write a number as text.
                sheet.write_number(row_index, col_index, value)
            else:
                sheet.write_string(row_index, col_index, str(value))

    if rows:
        sheet.autofilter(0, 0, len(rows), len(columns) - 1)
        # Colour scales mirroring the on-screen treatment.
        for col_index, column in enumerate(columns):
            entry = registry.get(column)
            if entry and entry.unit in {"percent", "number", "ratio"}:
                sheet.conditional_format(
                    1, col_index, len(rows), col_index,
                    {"type": "3_color_scale",
                     "min_color": "#f8d7da", "mid_color": "#ffffff", "max_color": "#d4edda"},
                )

    meta = book.add_worksheet("Screen Definition")
    meta.set_column(0, 0, 22)
    meta.set_column(1, 1, 90)
    for row_index, (key, value) in enumerate(prov.as_rows()):
        meta.write(row_index, 0, key, header_fmt)
        meta.write(row_index, 1, value, wrap_fmt)
    offset = len(prov.as_rows()) + 1
    meta.write(offset, 0, "Filter JSON", header_fmt)
    meta.write(offset, 1, json.dumps(definition, indent=2), wrap_fmt)

    glossary = book.add_worksheet("Metric Glossary")
    glossary.set_column(0, 0, 24)
    glossary.set_column(1, 1, 46)
    glossary.set_column(2, 2, 80)
    for col_index, title in enumerate(("Column", "Formula", "Meaning")):
        glossary.write(0, col_index, title, header_fmt)
    row_index = 1
    for column in columns:
        entry = registry.get(column)
        glossary.write(row_index, 0, entry.label if entry else column)
        glossary.write(row_index, 1, entry.formula if entry else "")
        glossary.write(row_index, 2, entry.description if entry else "", wrap_fmt)
        row_index += 1

    book.close()
    return path


def export_html(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
    screen_name: str,
    definition: dict[str, Any],
    data_as_of: date | None,
    out_dir: Path | None = None,
) -> Path:
    """FR-9.5: fully self-contained single file, inline CSS, no external assets."""
    prov = _provenance(screen_name, definition, data_as_of, len(rows))
    out_dir = out_dir or settings.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / build_filename(screen_name, data_as_of, prov.generated_at, "html")

    def cell(column: str, value: Any) -> str:
        if value is None:
            return "—"
        entry = registry.get(column)
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (int, float)) and entry and entry.unit == "percent":
            return f"{value * 100:.2f}%"
        if isinstance(value, float):
            return f"{value:,.2f}"
        return html.escape(str(value))

    head = "".join(
        f"<th onclick=\"sortTable({i})\" title=\"{html.escape(registry.get(c).formula) if registry.get(c) else ''}\">"
        f"{html.escape(registry.get(c).label if registry.get(c) else c)}</th>"
        for i, c in enumerate(columns)
    )
    body = "".join(
        "<tr>" + "".join(f"<td>{cell(c, row.get(c))}</td>" for c in columns) + "</tr>"
        for row in rows
    )
    provenance_rows = "".join(
        f"<div><span>{html.escape(k)}</span><strong>{html.escape(v)}</strong></div>"
        for k, v in prov.as_rows()
    )

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(screen_name)} — {prov.data_as_of}</title>
<style>
 body{{font:13px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;
      background:#0b0f16;color:#e6edf5;padding:20px}}
 h1{{margin:0 0 4px;font-size:19px}}
 .prov{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
        gap:6px;margin:12px 0 18px;padding:12px;background:#131a24;
        border:1px solid #263242;border-radius:6px}}
 .prov div{{display:flex;flex-direction:column}}
 .prov span{{color:#8fa3ba;font-size:11px}}
 table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
 th,td{{padding:5px 8px;border-bottom:1px solid #263242;text-align:right;
        white-space:nowrap}}
 th:first-child,td:first-child{{text-align:left}}
 th{{background:#1a2330;position:sticky;top:0;cursor:pointer;user-select:none}}
 tr:hover td{{background:#161e2a}}
 footer{{margin-top:16px;color:#8fa3ba;font-size:11px}}
</style></head><body>
<h1>{html.escape(screen_name)}</h1>
<div class="prov">{provenance_rows}</div>
<div style="overflow:auto"><table id="t"><thead><tr>{head}</tr></thead>
<tbody>{body}</tbody></table></div>
<footer>{html.escape(DISCLAIMER)}</footer>
<script>
function sortTable(n){{
  var t=document.getElementById('t'),rows=Array.from(t.tBodies[0].rows);
  var dir=t.dataset.dir==='asc'&&t.dataset.col==String(n)?'desc':'asc';
  rows.sort(function(a,b){{
    var x=a.cells[n].innerText,y=b.cells[n].innerText;
    var nx=parseFloat(x.replace(/[^0-9.-]/g,'')),ny=parseFloat(y.replace(/[^0-9.-]/g,''));
    var r=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y);
    return dir==='asc'?r:-r;
  }});
  rows.forEach(function(r){{t.tBodies[0].appendChild(r)}});
  t.dataset.dir=dir;t.dataset.col=n;
}}
</script></body></html>"""

    path.write_text(document, encoding="utf-8")
    return path
