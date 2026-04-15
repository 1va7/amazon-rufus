#!/usr/bin/env python3
from __future__ import annotations
"""
Amazon Rufus FAQ → 本地 Excel 导出（标准库，无 pip 依赖）

两张 sheet：
  产品信息   ASIN / 产品名称 / 价格 / 评分 / 采集时间 / 产品链接
  Rufus QA  ASIN / 序号 / 问题 / 答案 / 图片数量 / 图片URLs

用法（与 feishu_upload.py 参数一致）：
  python3 excel_export.py \
    --asin         "B0DN9WR2TX" \
    --product-name "..." \
    --product-url  "https://..." \
    --price        "$10.19" \
    --rating       "4.6 out of 5" \
    --output-dir   "~/Desktop/rufus-faq" \
    --faqs-json    '[{"q":"...","a":"...","imgs":["url"]}]'

输出 JSON：{"ok": true, "file": "/path/to/rufus_faq_B0DN9WR2TX_20240101_120000.xlsx", ...}
"""

import argparse
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime


# ── xlsx XML helpers ───────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    """Escape special XML characters."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


class SharedStrings:
    """Accumulates unique strings; returns 0-based index for each."""

    def __init__(self):
        self._index: dict[str, int] = {}
        self._order: list[str] = []

    def add(self, s: str) -> int:
        s = str(s)
        if s not in self._index:
            self._index[s] = len(self._order)
            self._order.append(s)
        return self._index[s]

    def xml(self) -> str:
        count = len(self._order)
        parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            f' count="{count}" uniqueCount="{count}">',
        ]
        for s in self._order:
            parts.append(f"<si><t xml:space=\"preserve\">{_esc(s)}</t></si>")
        parts.append("</sst>")
        return "\n".join(parts)


def _col_letter(n: int) -> str:
    """Convert 0-based column index to Excel letter (A, B, …, Z, AA, …)."""
    result = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _cell_ref(row: int, col: int) -> str:
    """1-based row, 0-based col → 'A1' style ref."""
    return f"{_col_letter(col)}{row}"


class Sheet:
    """Builds worksheet XML row by row."""

    def __init__(self, name: str, ss: SharedStrings):
        self.name = name
        self._ss = ss
        self._rows: list[list[tuple]] = []  # list of rows; each row = list of (ref, type, value)

    def add_row(self, values: list):
        row_num = len(self._rows) + 1
        cells = []
        for col, val in enumerate(values):
            ref = _cell_ref(row_num, col)
            if isinstance(val, (int, float)):
                cells.append((ref, "n", str(val)))
            else:
                idx = self._ss.add(str(val) if val is not None else "")
                cells.append((ref, "s", str(idx)))
        self._rows.append(cells)

    def xml(self) -> str:
        parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
            "<sheetData>",
        ]
        for r_idx, row in enumerate(self._rows, 1):
            parts.append(f'<row r="{r_idx}">')
            for ref, ctype, cval in row:
                parts.append(f'<c r="{ref}" t="{ctype}"><v>{cval}</v></c>')
            parts.append("</row>")
        parts += ["</sheetData>", "</worksheet>"]
        return "\n".join(parts)


# ── xlsx assembly ──────────────────────────────────────────────────────────────

CONTENT_TYPES = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml"  ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
  <Override PartName="/xl/styles.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

RELS_ROOT = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="产品信息" sheetId="1" r:id="rId1"/>
    <sheet name="Rufus QA" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>"""

WORKBOOK_RELS = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    Target="sharedStrings.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
    Target="styles.xml"/>
</Relationships>"""

STYLES_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills>
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>"""


def build_xlsx(sheets: list[Sheet], ss: SharedStrings) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", RELS_ROOT)
        zf.writestr("xl/workbook.xml", WORKBOOK_XML)
        zf.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        zf.writestr("xl/styles.xml", STYLES_XML)
        for i, sheet in enumerate(sheets, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", sheet.xml())
        zf.writestr("xl/sharedStrings.xml", ss.xml())
    return buf.getvalue()


# ── Main ───────────────────────────────────────────────────────────────────────

def export(asin: str, product_name: str, product_url: str,
           price: str, rating: str, faqs: list[dict],
           output_dir: str) -> str:
    """Build and save xlsx. Returns saved file path."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"rufus_faq_{asin}_{timestamp}.xlsx"
    filepath  = os.path.join(output_dir, filename)

    ss = SharedStrings()

    # ── Sheet 1: 产品信息 ──
    s1 = Sheet("产品信息", ss)
    s1.add_row(["ASIN", "产品名称", "价格", "评分", "采集时间", "产品链接"])
    s1.add_row([
        asin,
        product_name,
        price,
        rating,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        product_url,
    ])

    # ── Sheet 2: Rufus QA ──
    s2 = Sheet("Rufus QA", ss)
    s2.add_row(["ASIN", "序号", "问题", "答案", "图片数量", "图片URLs"])
    for i, faq in enumerate(faqs, 1):
        imgs = faq.get("imgs", [])
        s2.add_row([
            asin,
            i,
            faq.get("q", ""),
            faq.get("a", ""),
            len(imgs),
            " | ".join(imgs),
        ])

    xlsx_bytes = build_xlsx([s1, s2], ss)
    with open(filepath, "wb") as f:
        f.write(xlsx_bytes)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Export Rufus FAQ to local Excel file")
    parser.add_argument("--asin",         required=True)
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--product-url",  required=True)
    parser.add_argument("--price",        default="")
    parser.add_argument("--rating",       default="")
    parser.add_argument("--output-dir",   required=True)
    parser.add_argument("--faqs-json",    required=True,
                        help='JSON: [{"q":"...","a":"...","imgs":["url",...]}]')
    args = parser.parse_args()

    try:
        faqs = json.loads(args.faqs_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"faqs-json 解析失败: {e}"}))
        sys.exit(1)

    output_dir = os.path.expanduser(args.output_dir)
    filepath = export(
        asin=args.asin,
        product_name=args.product_name,
        product_url=args.product_url,
        price=args.price,
        rating=args.rating,
        faqs=faqs,
        output_dir=output_dir,
    )

    result = {
        "ok": True,
        "file": filepath,
        "asin": args.asin,
        "qa_count": len(faqs),
        "qa_with_images": sum(1 for f in faqs if f.get("imgs")),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
