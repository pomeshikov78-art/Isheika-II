"""Минимальный PDF-писатель на стандартной библиотеке (ТЗ-01 §7: экспорт PDF).

Особенности:
  * кириллица поддерживается встраиванием TrueType-шрифта DejaVu Sans
    (Identity-H, CIDFontType2, ToUnicode CMap) — текст остаётся выделяемым
    и искомым, а не картинкой;
  * разбивка на страницы A4, колонтитулы, таблицы с переносом строк,
    простая векторная инфографика (шкала TRL, столбчатые диаграммы);
  * если в окружении установлен WeasyPrint, используется он (типографика
    из HTML-версии), иначе — этот встроенный генератор.

Лицензия шрифта: assets/LICENSE_DEJAVU.txt (Bitstream Vera / DejaVu).
"""
from __future__ import annotations

import os
import struct
import zlib
from datetime import datetime

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_PATH = os.path.join(ASSETS, "DejaVuSans.ttf")

PAGE_W, PAGE_H = 595.28, 841.89      # A4
MARGIN = 46.0
CONTENT_W = PAGE_W - 2 * MARGIN


# ------------------------------------------------------------------ TrueType
class TrueType:
    """Разбор таблиц TTF, необходимых для встраивания и измерения текста."""

    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        num = struct.unpack(">H", d[4:6])[0]
        self.tables: dict[str, tuple[int, int]] = {}
        for i in range(num):
            off = 12 + 16 * i
            tag = d[off:off + 4].decode("latin1")
            o, ln = struct.unpack(">II", d[off + 8:off + 16])
            self.tables[tag] = (o, ln)
        head = self.tables["head"][0]
        self.units = struct.unpack(">H", d[head + 18:head + 20])[0]
        self.bbox = struct.unpack(">hhhh", d[head + 36:head + 44])
        hhea = self.tables["hhea"][0]
        self.ascent, self.descent = struct.unpack(">hh", d[hhea + 4:hhea + 8])
        self.num_hmetrics = struct.unpack(">H", d[hhea + 34:hhea + 36])[0]
        maxp = self.tables["maxp"][0]
        self.num_glyphs = struct.unpack(">H", d[maxp + 4:maxp + 6])[0]
        self.cmap = self._read_cmap()
        self.widths = self._read_widths()
        self._used: dict[int, str] = {}

    def _read_cmap(self) -> dict[int, int]:
        d, (base, _) = self.data, self.tables["cmap"]
        n = struct.unpack(">H", d[base + 2:base + 4])[0]
        best = None
        for i in range(n):
            pid, eid, off = struct.unpack(">HHI", d[base + 4 + 8 * i:base + 12 + 8 * i])
            score = {(3, 10): 5, (3, 1): 4, (0, 4): 3, (0, 3): 3}.get((pid, eid), 1)
            if best is None or score > best[0]:
                best = (score, base + off)
        if best is None:
            return {}
        sub = best[1]
        fmt = struct.unpack(">H", d[sub:sub + 2])[0]
        out: dict[int, int] = {}
        if fmt == 4:
            segx2 = struct.unpack(">H", d[sub + 6:sub + 8])[0]
            seg = segx2 // 2
            ends = struct.unpack(">" + "H" * seg, d[sub + 14:sub + 14 + segx2])
            sp = sub + 16 + segx2
            starts = struct.unpack(">" + "H" * seg, d[sp:sp + segx2])
            dp = sp + segx2
            deltas = struct.unpack(">" + "h" * seg, d[dp:dp + segx2])
            rp = dp + segx2
            ranges = struct.unpack(">" + "H" * seg, d[rp:rp + segx2])
            for i in range(seg):
                for c in range(starts[i], min(ends[i], 0xFFFF) + 1):
                    if ranges[i] == 0:
                        g = (c + deltas[i]) & 0xFFFF
                    else:
                        gi = rp + 2 * i + ranges[i] + 2 * (c - starts[i])
                        if gi + 2 > len(d):
                            continue
                        g = struct.unpack(">H", d[gi:gi + 2])[0]
                        if g:
                            g = (g + deltas[i]) & 0xFFFF
                    if g:
                        out[c] = g
        elif fmt == 12:
            ngroups = struct.unpack(">I", d[sub + 12:sub + 16])[0]
            for i in range(ngroups):
                o = sub + 16 + 12 * i
                sc, ec, sg = struct.unpack(">III", d[o:o + 12])
                for c in range(sc, min(ec, sc + 65535) + 1):
                    out[c] = sg + (c - sc)
        return out

    def _read_widths(self) -> list[int]:
        d = self.data
        hmtx = self.tables["hmtx"][0]
        w: list[int] = []
        for i in range(self.num_hmetrics):
            w.append(struct.unpack(">H", d[hmtx + 4 * i:hmtx + 4 * i + 2])[0])
        last = w[-1] if w else self.units // 2
        w += [last] * max(0, self.num_glyphs - len(w))
        return w

    def gid(self, ch: str) -> int:
        g = self.cmap.get(ord(ch), 0)
        if g and g not in self._used:
            self._used[g] = ch
        return g

    def advance(self, gid: int) -> int:
        return self.widths[gid] if gid < len(self.widths) else self.units // 2

    def text_width(self, text: str, size: float) -> float:
        return sum(self.advance(self.gid(c)) for c in text) * size / self.units

    def wrap(self, text: str, size: float, width: float) -> list[str]:
        lines: list[str] = []
        for para in str(text).split("\n"):
            cur = ""
            for word in para.split(" "):
                probe = (cur + " " + word).strip()
                if self.text_width(probe, size) <= width or not cur:
                    cur = probe
                else:
                    lines.append(cur)
                    cur = word
            lines.append(cur)
        return lines or [""]


# ------------------------------------------------------------------ PDF
class PDFDoc:
    def __init__(self, title: str, subject: str = "", font: TrueType | None = None):
        self.font = font or TrueType(FONT_PATH)
        self.title = title
        self.subject = subject
        self.pages: list[list[str]] = []
        self.footer = ""
        self.y = MARGIN          # координата сверху вниз
        self.new_page()

    # -------- примитивы (координаты сверху вниз)
    def new_page(self) -> None:
        self.pages.append([])
        self.y = MARGIN

    @property
    def cur(self) -> list[str]:
        return self.pages[-1]

    def _esc_hex(self, text: str) -> str:
        return "".join(f"{self.font.gid(c):04X}" for c in text)

    def text(self, x: float, y_top: float, text: str, size: float = 10, gray: float = 0.0) -> None:
        if not text:
            return
        y = PAGE_H - y_top
        self.cur.append(f"BT /F1 {size:.2f} Tf {gray:.2f} g 1 0 0 1 {x:.2f} {y:.2f} Tm "
                        f"<{self._esc_hex(text)}> Tj ET")

    def rect(self, x: float, y_top: float, w: float, h: float, gray: float = 0.85, stroke: bool = False) -> None:
        y = PAGE_H - y_top - h
        op = "S" if stroke else "f"
        self.cur.append(f"{gray:.2f} {'G' if stroke else 'g'} {x:.2f} {y:.2f} {w:.2f} {h:.2f} re {op}")

    def line(self, x1: float, y_top: float, x2: float, y2_top: float, gray: float = 0.7) -> None:
        self.cur.append(f"{gray:.2f} G 0.6 w {x1:.2f} {PAGE_H - y_top:.2f} m {x2:.2f} {PAGE_H - y2_top:.2f} l S")

    # -------- высокоуровневая вёрстка
    def ensure(self, need: float) -> None:
        if self.y + need > PAGE_H - MARGIN - 26:
            self.new_page()

    def para(self, text: str, size: float = 9.5, gray: float = 0.0, indent: float = 0.0, space_after: float = 4) -> None:
        for ln in self.font.wrap(text, size, CONTENT_W - indent):
            self.ensure(size + 3)
            self.text(MARGIN + indent, self.y, ln, size, gray)
            self.y += size + 3
        self.y += space_after

    def heading(self, text: str, level: int = 1) -> None:
        size = {0: 20, 1: 13, 2: 11}.get(level, 10)
        self.ensure(size + 14)
        self.y += 6 if level else 0
        self.text(MARGIN, self.y, text, size, 0.0)
        self.y += size + 4
        if level <= 1:
            self.line(MARGIN, self.y, PAGE_W - MARGIN, self.y, 0.75)
            self.y += 7

    def kv(self, pairs: list[tuple[str, str]]) -> None:
        for k, v in pairs:
            self.ensure(13)
            self.text(MARGIN, self.y, k + ":", 9, 0.35)
            w = self.font.text_width(k + ": ", 9)
            for i, ln in enumerate(self.font.wrap(str(v), 9, CONTENT_W - w)):
                if i:
                    self.ensure(12)
                self.text(MARGIN + w, self.y, ln, 9)
                self.y += 12
        self.y += 4

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float] | None = None,
              size: float = 8.5, max_rows: int = 60) -> None:
        n = len(headers)
        widths = widths or [CONTENT_W / n] * n
        scale = CONTENT_W / sum(widths)
        widths = [w * scale for w in widths]
        self.ensure(30)
        x = MARGIN
        self.rect(MARGIN, self.y - 2, CONTENT_W, size + 7, 0.92)
        for h, w in zip(headers, widths):
            self.text(x + 2, self.y, self.font.wrap(h, size, w - 4)[0], size, 0.15)
            x += w
        self.y += size + 7
        for row in rows[:max_rows]:
            cells = [self.font.wrap("" if c is None else str(c), size, w - 4) for c, w in zip(row, widths)]
            h = max(len(c) for c in cells) * (size + 2) + 3
            self.ensure(h + 4)
            x = MARGIN
            for cell, w in zip(cells, widths):
                yy = self.y
                for ln in cell:
                    self.text(x + 2, yy, ln, size)
                    yy += size + 2
                x += w
            self.y += h
            self.line(MARGIN, self.y - 2, PAGE_W - MARGIN, self.y - 2, 0.85)
        if len(rows) > max_rows:
            self.para(f"… показано {max_rows} из {len(rows)} строк (полный список — в CSV/XLSX-приложении)", 8, 0.4)
        self.y += 6

    def bars(self, items: list[tuple[str, float]], title: str = "", unit: str = "") -> None:
        if not items:
            return
        self.ensure(30 + 13 * len(items))
        if title:
            self.para(title, 9, 0.25, space_after=2)
        top = max(v for _, v in items) or 1
        label_w = 110
        for label, value in items:
            self.ensure(14)
            self.text(MARGIN, self.y, self.font.wrap(str(label), 8, label_w - 4)[0], 8)
            w = (CONTENT_W - label_w - 46) * (value / top)
            self.rect(MARGIN + label_w, self.y - 1, max(0.8, w), 8, 0.55)
            self.text(MARGIN + label_w + max(0.8, w) + 4, self.y, f"{value:g}", 8, 0.2)
            self.y += 13
        if unit:
            self.para("Единицы: " + unit, 7.5, 0.45, space_after=2)
        self.y += 4

    def trl_ladder(self, achieved: int) -> None:
        self.ensure(46)
        w = CONTENT_W / 9
        for lvl in range(1, 10):
            x = MARGIN + (lvl - 1) * w
            self.rect(x, self.y, w - 3, 24, 0.80 if lvl <= achieved else 0.94)
            self.text(x + 4, self.y + 6, str(lvl), 11)
            self.text(x + 4, self.y + 17, "✓" if lvl <= achieved else "·", 7, 0.3)
        self.y += 32
        self.para(f"TRL = {achieved}: максимальный уровень с выполненными обязательными критериями. "
                  f"Усреднение уровней не применялось.", 8, 0.35)

    # -------- сборка файла
    def _tounicode(self) -> str:
        items = sorted(self.font._used.items())
        lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
                 "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
                 "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
                 "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
        for i in range(0, len(items), 100):
            chunk = items[i:i + 100]
            lines.append(f"{len(chunk)} beginbfchar")
            for gid, ch in chunk:
                lines.append(f"<{gid:04X}> <{ord(ch):04X}>")
            lines.append("endbfchar")
        lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
        return "\n".join(lines)

    def save(self, path: str) -> str:
        f = self.font
        # колонтитулы
        total = len(self.pages)
        for i, page in enumerate(self.pages, 1):
            foot = f"{self.footer}   ·   стр. {i} из {total}"
            page.append(f"BT /F1 7.5 Tf 0.45 g 1 0 0 1 {MARGIN:.2f} {MARGIN - 12:.2f} Tm "
                        f"<{self._esc_hex(foot)}> Tj ET")
            page.append(f"0.8 G 0.5 w {MARGIN:.2f} {MARGIN - 4:.2f} m {PAGE_W - MARGIN:.2f} {MARGIN - 4:.2f} l S")

        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_stream = zlib.compress(f.data)
        ff = add(b"<< /Length " + str(len(font_stream)).encode() + b" /Length1 " + str(len(f.data)).encode()
                 + b" /Filter /FlateDecode >>\nstream\n" + font_stream + b"\nendstream")
        widths_arr = " ".join(f"{gid} [{f.advance(gid) * 1000 / f.units:.1f}]" for gid, _ in sorted(f._used.items()))
        scale = 1000 / f.units
        bbox = [round(v * scale) for v in f.bbox]
        fd = add(b"<< /Type /FontDescriptor /FontName /DejaVuSans /Flags 32 /FontBBox ["
                 + " ".join(str(v) for v in bbox).encode() + b"] /ItalicAngle 0 /Ascent "
                 + str(round(f.ascent * scale)).encode() + b" /Descent " + str(round(f.descent * scale)).encode()
                 + b" /CapHeight " + str(round(f.ascent * scale)).encode() + b" /StemV 80 /FontFile2 "
                 + str(ff).encode() + b" 0 R >>")
        cid = add(b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /DejaVuSans /CIDSystemInfo "
                  b"<< /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor "
                  + str(fd).encode() + b" 0 R /DW " + str(round(f.advance(0) * scale)).encode()
                  + b" /W [" + widths_arr.encode() + b"] /CIDToGIDMap /Identity >>")
        tu = self._tounicode().encode()
        tu_z = zlib.compress(tu)
        tu_obj = add(b"<< /Length " + str(len(tu_z)).encode() + b" /Filter /FlateDecode >>\nstream\n" + tu_z + b"\nendstream")
        t0 = add(b"<< /Type /Font /Subtype /Type0 /BaseFont /DejaVuSans /Encoding /Identity-H /DescendantFonts ["
                 + str(cid).encode() + b" 0 R] /ToUnicode " + str(tu_obj).encode() + b" 0 R >>")

        pages_obj = len(objects) + 1 + 2 * len(self.pages)
        kids = []
        for i, content in enumerate(self.pages):
            stream = zlib.compress("\n".join(content).encode("latin1", "replace"))
            cs = add(b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\nstream\n" + stream + b"\nendstream")
            pg = add(b"<< /Type /Page /Parent " + str(pages_obj).encode() + b" 0 R /MediaBox [0 0 "
                     + f"{PAGE_W:.2f} {PAGE_H:.2f}".encode() + b"] /Resources << /Font << /F1 "
                     + str(t0).encode() + b" 0 R >> >> /Contents " + str(cs).encode() + b" 0 R >>")
            kids.append(pg)
        assert pages_obj == len(objects) + 1
        pages = add(b"<< /Type /Pages /Count " + str(len(kids)).encode() + b" /Kids ["
                    + " ".join(f"{k} 0 R" for k in kids).encode() + b"] >>")
        info = add(b"<< /Title (" + self.title.encode("utf-16-be").hex().encode()
                   + b") /Author (ISHEIKA-NTR-AI) /Creator (ISHEIKA-NTR-AI 0.1) /Producer (stdlib pdf writer) >>")
        catalog = add(b"<< /Type /Catalog /Pages " + str(pages).encode() + b" 0 R >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode()
        out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root " + str(catalog).encode()
                + b" 0 R /Info " + str(info).encode() + b" 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
        with open(path, "wb") as fh:
            fh.write(bytes(out))
        return path


# ------------------------------------------------------------------ отчёт
def _fmt(v, digits: int = 2) -> str:
    if v is None:
        return "нет данных"
    if isinstance(v, (int, float)):
        return f"{v:.{digits}f}".rstrip("0").rstrip(".") if digits else str(v)
    return str(v)


def build_pdf(data: dict, path: str) -> str:
    """Печатная версия отчёта. Содержание совпадает с HTML-версией."""
    try:                                   # необязательная типографская вёрстка
        from weasyprint import HTML        # type: ignore
        from .builder import build_html
        HTML(string=build_html(data)).write_pdf(path)
        return path
    except Exception:
        pass

    r = data["research"] or {}
    pp = (data["passport"] or {}).get("passport") or {}
    trl = data["trl"] or {}
    fea = data["feasibility"] or {}
    fc = data["forecast"] or {}
    m = data["methodology"]
    reg = data.get("methodology_registry") or {}
    from ..analytics import methodologies as M
    rel = reg.get("RELEVANCE") or M.active("RELEVANCE")
    fea_m = reg.get("FEASIBILITY") or M.active("FEASIBILITY")
    doc = PDFDoc(title=r.get("title") or "Отчёт ИЩЕЙКА НТР AI")
    doc.footer = f"ИЩЕЙКА НТР AI · методика {m['version']} · {data['generated_at'][:19]}"

    doc.heading("ИЩЕЙКА НТР AI — аналитический отчёт", 0)
    doc.para(r.get("title") or "", 13)
    doc.kv([("Идентификатор исследования", r.get("id")),
            ("Дата формирования", data["generated_at"][:19].replace("T", " ")),
            ("Комплект методик", m["version"] + " (" + m["status"] + "); версии по семействам — раздел 2"),
            ("Версия ПО / API", f"{data['app_version']} / {data['api_version']}"),
            ("Горизонт прогноза", f"{r.get('forecast_horizon_years')} лет"),
            ("Стран в охвате", len(r.get("country_codes") or [])),
            ("Языки", ", ".join(r.get("language_codes") or []))])

    doc.heading("1. Постановка задачи", 1)
    doc.kv([("Запрос", (data["query"] or {}).get("raw_text")),
            ("Цель", r.get("goal") or "не задана"),
            ("Тип объекта", r.get("research_type")),
            ("Период", f"{r.get('period_from') or '—'} … {r.get('period_to') or '—'}")])

    doc.heading("2. Методика и версии", 1)
    doc.para("Релевантность (" + rel["code"] + " " + rel["version"] + "): "
             + str(rel["formula_definition"].get("expression") or "") + ". Пороги: DIRECT ≥ "
             + str(rel["thresholds"]["DIRECT"]) + ", ADJACENT ≥ "
             + str(rel["thresholds"]["ADJACENT"]) + ", иначе BELOW_THRESHOLD.")
    doc.para("TRL: максимальный уровень с выполненными обязательными критериями; усреднение запрещено. "
             "Реализуемость (" + fea_m["code"] + " " + fea_m["version"] + "): "
             + str(fea_m["formula_definition"].get("expression") or "")
             + "; неизвестные факторы исключаются, покрытие снижается.")
    doc.para("Реестр методик (версии, применённые в расчётах): " + "; ".join(
        k + " — " + v["code"] + " " + v["version"] + " (" + str(v.get("approval_status") or "") + ")"
        for k, v in reg.items()) + ".")
    doc.para("Прогноз: P(T≤t) не убывает; на горизонтах 20–50 лет приводятся только качественные сценарии. "
             "Статус калибровки: " + m["status"] + ".")

    doc.heading("3. Поисковая стратегия и охват источников", 1)
    branches = ((data["query"] or {}).get("branches") or [])
    if branches:
        doc.table(["Ветвь", "Выражение"], [[b.get("name"), b.get("expression")] for b in branches], [1, 3])
    sj = data["search_jobs"] or []
    ok = sum(1 for j in sj if j["status"] == "completed")
    doc.para(f"Заданий поиска: {len(sj)}, успешно: {ok}, с ошибками: {len(sj) - ok}. "
             f"Документов получено: {len(data['documents'])}.")
    if sj:
        doc.table(["Коннектор", "Статус", "Найдено", "Ошибка"],
                  [[j["connector_code"], j["status"], j["found_count"], j["error_code"] or "—"] for j in sj],
                  [2, 1.4, 1, 2.4], max_rows=30)

    doc.heading("4. Описание технологии", 1)
    doc.kv([("Объект", (pp.get("identification") or {}).get("name") or r.get("title")),
            ("Принцип действия", (pp.get("purpose_and_principle") or {}).get("principle")),
            ("Научная база", (pp.get("science_base") or {}).get("documents")),
            ("Патентная база", (pp.get("patent_base") or {}).get("documents"))])

    doc.heading("5. TRL 1–9", 1)
    if trl:
        doc.trl_ladder(int(trl.get("trl") or 1))
        doc.kv([("Уверенность", _fmt(trl.get("confidence"))), ("Хеш входов", trl.get("input_hash"))])
        crit = [c for c in (trl.get("criteria") or []) if c["level"] <= int(trl.get("trl") or 1) + 1]
        if crit:
            doc.table(["Ур.", "Критерий", "Подтв.", "Увер."],
                      [[c["level"], c["text"], "да" if c["confirmed"] else "нет", _fmt(c["confidence"])]
                       for c in crit], [0.5, 4, 0.8, 0.8], max_rows=40)
        gaps = trl.get("gaps") or []
        if gaps:
            doc.heading("Пробелы TRL", 2)
            doc.table(["Ур.", "Критерий", "Причина"],
                      [[g["level"], g["text"], g["reason"]] for g in gaps], [0.5, 3, 2.5], max_rows=25)
    else:
        doc.para("TRL не рассчитан: этап математического ядра не выполнялся.", 9, 0.3)

    doc.heading("6. Реализуемость", 1)
    if fea:
        doc.kv([("F", _fmt(fea.get("score")) + " %"), ("Покрытие C", _fmt((fea.get("coverage") or 0) * 100) + " %"),
                ("Диапазон", f"{_fmt(fea.get('range_low'))} … {_fmt(fea.get('range_high'))}"),
                ("Интерпретация", fea.get("interpretation"))])
        doc.table(["Фактор", "Вес", "Оценка", "Статус"],
                  [[f["name"], _fmt(f["weight"]), _fmt(f.get("x")), f["assessment"]] for f in (fea.get("factors") or [])],
                  [3, 0.7, 0.8, 1.2], max_rows=15)
        doc.para("F — оценка возможности достижения технического состояния, а не вероятность успеха. "
                 "Неизвестный фактор не приравнивается к нулю.", 8, 0.35)
    else:
        doc.para("Реализуемость не рассчитана.", 9, 0.3)

    doc.heading("7. Барьеры и альтернативы", 1)
    bs = data["barriers"] or []
    if bs:
        doc.table(["Барьер", "Критичность", "Вероятность"],
                  [[b["barrier_type"], _fmt(b["criticality"]), _fmt(b["probability"])] for b in bs], [3, 1, 1])
    else:
        doc.para("Барьеры не выявлены — это пробел поиска, а не доказательство их отсутствия.", 9, 0.3)
    alts = data["alternatives"] or []
    if alts:
        doc.table(["Альтернатива", "Принцип действия"],
                  [[a["name"], (a.get("criteria") or {}).get("принцип действия") or "неизвестно"] for a in alts], [2, 3], max_rows=15)

    doc.heading("8. Тренды", 1)
    series = (data["trends"] or {}).get("publications") or []
    pts = [(str(p["year"]), p["value"]) for p in series if p["value"] is not None]
    if pts:
        doc.bars(pts[-15:], "Публикации по годам", "документов в год")
    cov = data["coverage"] or []
    have = [c for c in cov if not c["gap"]]
    if have:
        doc.bars([(c["iso2"], c["documents"]) for c in sorted(have, key=lambda x: -x["documents"])[:12]],
                 "Покрытие по странам", "документов")
    gaps = [c["iso2"] for c in cov if c["gap"]]
    if gaps:
        doc.para("Карта пробелов (нет данных): " + ", ".join(gaps), 8, 0.35)

    doc.heading("9. Прогноз 0–50 лет", 1)
    if fc:
        doc.para("Метод: " + str(fc.get("method")) + ". Монотонность P(T≤t): "
                 + ("соблюдена" if fc.get("monotonic_ok") else "нарушена") + ".", 9)
        rows = []
        for target, scen in (fc.get("scenarios") or {}).items():
            for name in ("optimistic", "base", "pessimistic"):
                for p in scen.get(name, []):
                    rows.append([target, name, f"{p['years_from']}–{p['years_to']}",
                                 _fmt(p["probability"]) if p["probability"] is not None else (p["qualitative"] or "нет данных")])
        doc.table(["Цель", "Сценарий", "Горизонт, лет", "P(T≤t) / качественно"], rows, [2, 1.2, 1.2, 2.6], max_rows=72)
        for a in (fc.get("assumptions") or []):
            doc.para("• " + a["text"], 8, 0.25, space_after=1)
    else:
        doc.para("Прогноз не построен.", 9, 0.3)

    doc.heading("10. Доказательная база", 1)
    es = data["evidence_summary"] or {}
    doc.kv([("Всего доказательств", es.get("total")), ("Независимых групп", es.get("independence_groups")),
            ("По статусам", ", ".join(f"{k}: {v}" for k, v in (es.get("by_status") or {}).items())),
            ("Утверждений", len(data["claims"] or []))])
    docs = data["documents"] or []
    if docs:
        doc.heading("Приложение А. Документы (топ по релевантности)", 2)
        doc.table(["Название (рус.)", "Тип", "Страна", "R", "Класс"],
                  [[d.get("title_ru") or d["title"], d["doc_type"], d["country_code"] or "—",
                    _fmt(d.get("score"), 3), d.get("rclass") or d["state"]]
                   for d in docs], [4, 1, 0.7, 0.6, 0.9], max_rows=50)
        trn = data.get("translation") or {}
        if trn.get("translated"):
            doc.para(f"Технический перевод: {trn['translated']} материалов, "
                     f"требуют вычитки {trn.get('review_required', 0)}; словарь {trn.get('glossary_version')}. "
                     "Терминологический режим — черновик: числа, единицы и обозначения сохранены, "
                     "формулировки требуют вычитки специалистом.", 8.5, 0.15, space_after=2)

    doc.heading("11. Ограничения и предупреждения", 1)
    from .builder import warnings
    for w in warnings(data):
        doc.para("⚠ " + w, 9, 0.15, space_after=2)
    for lim in (pp.get("limitations") or []):
        doc.para("• " + lim, 8.5, 0.25, space_after=1)

    doc.heading("12. Выводы", 1)
    concl = []
    if trl:
        concl.append(f"Подтверждённый уровень готовности технологии — TRL {trl.get('trl')} "
                     f"(уверенность {_fmt(trl.get('confidence'))}); дальнейший рост требует закрытия пробелов.")
    if fea:
        concl.append(f"Техническая реализуемость F = {_fmt(fea.get('score'))}% при покрытии факторов "
                     f"{_fmt((fea.get('coverage') or 0) * 100)}%; диапазон {_fmt(fea.get('range_low'))}–{_fmt(fea.get('range_high'))}%.")
    if not concl:
        concl.append("Данных недостаточно для обоснованных выводов: расширьте охват источников и уточните запрос.")
    concl.append("Все выводы опираются на открытые источники; отсутствие данных не является отрицательным фактом.")
    for c in concl:
        doc.para("• " + c, 9.5)
    return doc.save(path)
