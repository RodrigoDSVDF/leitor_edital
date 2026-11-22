"""Exportadores DOCX, XLSX e PDF para EditalReport — com auditoria e páginas-fonte."""
from __future__ import annotations

import io
import re
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

NAVY = "172334"
ACCENT = "756CF3"
PURPLE = "6158C7"
FAINT = "F3F5F9"
TEXT = "263244"


def _weighted_table(phase_table: pd.DataFrame) -> pd.DataFrame:
    """Calcula pesos exclusivamente em provas objetivas; evita dividir por zero."""
    df = phase_table.copy()
    if df.empty:
        return df.assign(num_itens_num=pd.Series(dtype="float"), **{"peso_%": pd.Series(dtype="float")})
    for col in ["prova", "materia", "num_itens", "carater"]:
        if col not in df:
            df[col] = ""
    df["num_itens_num"] = pd.to_numeric(df["num_itens"], errors="coerce")
    nonobjective = df["prova"].astype(str).str.contains("discursiv|reda[çc][ãa]o|t[ií]tulos|pr[aá]tic|teste f[ií]sico|ta[fí]", case=False, regex=True)
    df["peso_%"] = float("nan")
    obj = df.loc[~nonobjective & df["num_itens_num"].ge(0)].copy()
    if not obj.empty:
        # Cada prova independente; discriminação de tabelas com ID opcional.
        group_cols = ["prova"] + (["tabela_id"] if "tabela_id" in obj.columns else [])
        denom = obj.groupby(group_cols, dropna=False)["num_itens_num"].transform("sum")
        df.loc[obj.index, "peso_%"] = (obj["num_itens_num"].div(denom.where(denom > 0)) * 100).round(1)
    return df


def _flat_topics(report):
    for m in report.materias:
        for t in m.topicos:
            yield [m.cargo, m.grupo, m.nome, m.materia_mae or "", t.codigo, t.nivel, t.texto, t.pagina]


def _plan_rows(report):
    for m in report.materias:
        for t in m.topicos:
            if not t.texto.strip():
                continue
            yield [m.cargo, m.grupo, m.nome, t.codigo, t.nivel, t.texto,
                   "Não iniciado", "Média", "", "", t.pagina]


def build_docx(report, titulo: str = "Relatório de Matérias do Concurso") -> bytes:
    document = Document()
    sec = document.sections[0]
    sec.top_margin = Cm(2)
    sec.bottom_margin = Cm(1.7)
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    style.font.color.rgb = RGBColor(38, 50, 68)

    heading = document.add_heading(titulo, 0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph("Mapeamento de provas, tópicos e auditoria da extração. Conferir sempre as informações no edital original.")
    document.add_paragraph(
        f"{report.paginas} páginas · {len(report.materias)} disciplinas/entradas · "
        f"{sum(len(m.topicos) for m in report.materias)} tópicos · {len(report.issues)} avisos de auditoria"
    )

    document.add_heading("1. Provas e distribuição de itens", 1)
    df = _weighted_table(report.phase_table)
    headers = ["Prova", "Matéria / bloco", "Itens", "Peso", "Página"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Light Shading Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, title in zip(table.rows[0].cells, headers):
        cell.text = title
    if df.empty:
        document.add_paragraph("Tabela de provas não reconhecida no PDF.")
    else:
        for _, row in df.iterrows():
            vals = [str(row.get("prova", "")) + (f" [tab. {int(row['tabela_id'])}]" if pd.notna(row.get("tabela_id")) else ""), str(row.get("materia", "")),
                    str(row.get("num_itens", "")),
                    f"{row['peso_%']:.1f}%" if pd.notna(row.get("peso_%")) else "—",
                    str(row.get("pagina", "")) if pd.notna(row.get("pagina")) else "—"]
            for cell, val in zip(table.add_row().cells, vals):
                cell.text = val

    document.add_heading("2. Conteúdo programático", 1)
    prior = None
    for m in report.materias:
        group = (m.cargo, m.grupo)
        if group != prior:
            document.add_heading(f"{m.cargo}  |  {m.grupo}", 2)
            prior = group
        title = m.nome + (f" (parte de: {m.materia_mae})" if m.materia_mae else "")
        document.add_heading(title, 3)
        for t in m.topicos:
            p = document.add_paragraph()
            p.paragraph_format.left_indent = Cm(max(0, min(t.nivel - 1, 7)) * 0.42)
            p.paragraph_format.space_after = Pt(3)
            if t.codigo:
                r = p.add_run(t.codigo + "  ")
                r.bold = True
                r.font.color.rgb = RGBColor(97, 88, 199)
            p.add_run(t.texto)
            if t.pagina:
                r = p.add_run(f"  [p. {t.pagina}]")
                r.italic = True
                r.font.size = Pt(8)

    document.add_heading("3. Auditoria e ressalvas", 1)
    if not report.issues:
        document.add_paragraph("Nenhum aviso automático gerado. Isso não garante extração perfeita.")
    for issue in report.issues:
        document.add_paragraph(f"[{issue.severidade.upper()}] {issue.mensagem}" +
                               (f" (página {issue.pagina})" if issue.pagina else ""), style="List Bullet")
    footer = sec.footer.paragraphs[0]
    footer.text = "Documento automatizado — conferir com o edital original"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _safe_xlsx(value):
    """Evita execução de fórmulas injetadas em campos vindos do edital."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _append_data(ws, values):
    ws.append([_safe_xlsx(v) for v in values])


def _make_header(ws, labels: list[str]):
    ws.append(labels)
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(name="Aptos", bold=True, color="FFFFFF", size=10)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = "A2"


def _format_sheet(ws, widths: list[int], text_columns: tuple[int, ...] = ()):  # widths em caracteres
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    pale = PatternFill("solid", fgColor="F0F2F9")
    for r in range(2, ws.max_row + 1):
        for c in range(1, len(widths) + 1):
            cell = ws.cell(r, c)
            if r % 2 == 0:
                cell.fill = pale
            cell.font = Font(name="Aptos", size=10, color=TEXT)
            cell.alignment = Alignment(vertical="top", wrap_text=c in text_columns)
        ws.row_dimensions[r].height = 25
    ws.auto_filter.ref = f"A1:{get_column_letter(len(widths))}{max(ws.max_row,1)}"


def build_xlsx(report, plano: pd.DataFrame | None = None) -> bytes:
    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True
    ws = wb.active
    ws.title = "Provas e Pesos"
    _make_header(ws, ["Prova", "Matéria", "Número de itens", "Peso na prova (%)", "Caráter", "Pág. fonte", "Tabela nº"])
    df = _weighted_table(report.phase_table)
    for _, row in df.iterrows():
        _append_data(ws, [row.get("prova"), row.get("materia"),
                   int(row["num_itens_num"]) if pd.notna(row["num_itens_num"]) else None,
                   float(row["peso_%"]) if pd.notna(row.get("peso_%")) else None,
                   row.get("carater"), int(row["pagina"]) if pd.notna(row.get("pagina")) else None,
                   int(row["tabela_id"]) if pd.notna(row.get("tabela_id")) else None])
    _format_sheet(ws, [40, 43, 18, 20, 28, 14, 13], (1, 2, 5))
    for cell in ws["D"][1:]:
        cell.number_format = '0.0"%"'

    ws2 = wb.create_sheet("Conteúdo Programático")
    _make_header(ws2, ["Cargo", "Grupo", "Matéria", "Matéria composta", "Código", "Nível", "Tópico", "Pág. fonte"])
    for row in _flat_topics(report):
        _append_data(ws2, row)
    _format_sheet(ws2, [33, 29, 34, 32, 12, 9, 80, 14], (1, 2, 3, 4, 7))
    for r in range(2, ws2.max_row + 1):
        ws2.cell(r, 7).alignment = Alignment(vertical="top", wrap_text=True, indent=min(max(int(ws2.cell(r, 6).value or 1) - 1, 0), 7))
        ws2.cell(r, 5).font = Font(bold=True, color=PURPLE)

    ws3 = wb.create_sheet("Resumo")
    _make_header(ws3, ["Cargo", "Grupo", "Matéria", "Submatéria de", "Nível 1", "Nível 2", "Nível 3+", "Tópicos", "Pág. fonte"])
    for m in report.materias:
        _append_data(ws3, [m.cargo, m.grupo, m.nome, m.materia_mae or "",
                    sum(t.nivel == 1 for t in m.topicos), sum(t.nivel == 2 for t in m.topicos),
                    sum(t.nivel >= 3 for t in m.topicos), len(m.topicos), m.pagina])
    _format_sheet(ws3, [35, 28, 35, 35, 12, 12, 12, 12, 12], (1, 2, 3, 4))

    ws4 = wb.create_sheet("Auditoria")
    _make_header(ws4, ["Severidade", "Código", "Descrição", "Página"])
    for issue in report.issues:
        _append_data(ws4, [issue.severidade.upper(), issue.codigo, issue.mensagem, issue.pagina])
    _format_sheet(ws4, [16, 28, 105, 12], (3,))

    ws5 = wb.create_sheet("Plano de Estudos")
    _make_header(ws5, ["Cargo", "Grupo", "Matéria", "Código", "Nível", "Tópico", "Status", "Prioridade", "Data revisão", "Observações", "Pág. fonte"])
    if plano is None:
        plan_data = list(_plan_rows(report))
    else:
        expected = ["cargo", "grupo", "materia", "codigo", "nivel", "topico", "status", "prioridade", "data_revisao", "observacoes", "pagina"]
        plan_data = [[v if pd.notna(v) else "" for v in row] for row in plano.reindex(columns=expected).itertuples(index=False, name=None)]
    for row in plan_data:
        _append_data(ws5, row)
    _format_sheet(ws5, [34, 28, 35, 12, 8, 74, 20, 15, 18, 34, 12], (1, 2, 3, 6, 10))
    if ws5.max_row > 1:
        dv = DataValidation(type="list", formula1='"Não iniciado,Em andamento,Concluído"', allow_blank=False)
        ws5.add_data_validation(dv)
        dv.add(f"G2:G{ws5.max_row}")
        dv_priority = DataValidation(type="list", formula1='"Alta,Média,Baixa"', allow_blank=False)
        ws5.add_data_validation(dv_priority)
        dv_priority.add(f"H2:H{ws5.max_row}")

    summary = wb.create_sheet("Painel", 0)
    summary.sheet_view.showGridLines = False
    summary.merge_cells("A1:F2")
    summary["A1"] = "MAPEADOR DE EDITAIS  |  VISÃO GERAL"
    summary["A1"].fill = PatternFill("solid", fgColor=NAVY)
    summary["A1"].font = Font(bold=True, size=17, color="FFFFFF")
    summary["A1"].alignment = Alignment(vertical="center")
    summary["A4"] = "Indicador"
    summary["B4"] = "Valor"
    summary["A5"], summary["B5"] = "Disciplinas", len(report.materias)
    summary["A6"], summary["B6"] = "Tópicos", sum(len(m.topicos) for m in report.materias)
    summary["A7"], summary["B7"] = "Avisos", len(report.issues)
    summary["A8"] = "Itens concluídos"
    summary["B8"] = f'=COUNTIF(\'Plano de Estudos\'!G2:G{max(2,ws5.max_row)},"Concluído")'
    summary["A9"] = "Progresso"
    summary["B9"] = f'=IFERROR(B8/COUNTA(\'Plano de Estudos\'!F2:F{max(2,ws5.max_row)}),0)'
    summary["B9"].number_format = "0.0%"
    summary["A11"] = "Atenção: valores extraídos automaticamente precisam ser conferidos no PDF."
    summary.merge_cells("A11:F11")
    for r in range(4, 10):
        for cell in summary[r][:2]:
            cell.fill = PatternFill("solid", fgColor=FAINT if r % 2 else "E3E7F1")
            cell.font = Font(name="Aptos", size=12, bold=(r == 4), color=TEXT)
    for col in "ABCDEF":
        summary.column_dimensions[col].width = 22
    summary.column_dimensions["A"].width = 27

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _pdf_fonts():
    path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    bold_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if path.exists() and bold_path.exists():
        if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVu", str(path)))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold_path)))
        return "DejaVu", "DejaVu-Bold"
    # Deploy: alternativa nativa com menos suporte Unicode; instalação de fontes recomendada.
    return "Helvetica", "Helvetica-Bold"


def build_pdf(report, titulo: str = "Relatório de Matérias do Concurso") -> bytes:
    normal_font, bold_font = _pdf_fonts()
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.6*cm, bottomMargin=1.6*cm,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            title=titulo, author="Mapeador de Editais")
    styles = {
        "title": ParagraphStyle("t", fontName=bold_font, fontSize=17, leading=23, textColor=colors.HexColor("#172334"), spaceAfter=14),
        "h1": ParagraphStyle("h1", fontName=bold_font, fontSize=12, leading=17, textColor=colors.HexColor("#6158C7"), spaceBefore=13, spaceAfter=7),
        "h2": ParagraphStyle("h2", fontName=bold_font, fontSize=10, leading=15, textColor=colors.HexColor("#172334"), spaceBefore=9, spaceAfter=5),
        "body": ParagraphStyle("body", fontName=normal_font, fontSize=8.5, leading=12.5, spaceAfter=4),
        "small": ParagraphStyle("small", fontName=normal_font, fontSize=7.2, leading=10, spaceAfter=3),
        "table_header": ParagraphStyle("table_header", fontName=bold_font, fontSize=7.2, leading=10, textColor=colors.white),
    }
    story = [Paragraph(escape(titulo), styles["title"]),
             Paragraph(f"{report.paginas} páginas · {len(report.materias)} disciplinas/entradas · "
                       f"{sum(len(m.topicos) for m in report.materias)} tópicos · "
                       f"{len(report.issues)} avisos", styles["body"]),
             Paragraph("Extração automática: confira a íntegra com o edital original.", styles["small"]),
             Paragraph("1. Provas e distribuição", styles["h1"])]
    df = _weighted_table(report.phase_table)
    if not df.empty:
        rows = [[Paragraph(x, styles["table_header"]) for x in ["Prova", "Matéria", "Itens", "Peso"]]]
        for _, row in df.iterrows():
            values = [str(row.get("prova") or "") + (f" [tab. {int(row['tabela_id'])}]" if pd.notna(row.get("tabela_id")) else ""), str(row.get("materia") or ""), str(row.get("num_itens") or ""),
                      f"{row['peso_%']:.1f}%" if pd.notna(row.get("peso_%")) else "—"]
            rows.append([Paragraph(escape(x), styles["small"]) for x in values])
        tab = Table(rows, colWidths=[4*cm, 8.4*cm, 2*cm, 2*cm], repeatRows=1, hAlign="LEFT")
        tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#172334')),
                                 ('TEXTCOLOR',(0,0),(-1,0),colors.white),
                                 ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#F2F4F9')]),
                                 ('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5)]))
        story.append(tab)
    else:
        story.append(Paragraph("Tabela de provas não reconhecida.", styles["body"]))
    story.append(Paragraph("2. Conteúdo programático", styles["h1"]))
    last_group = None
    for m in report.materias:
        group = (m.cargo, m.grupo)
        if group != last_group:
            story.append(Paragraph(escape(f"{m.cargo} · {m.grupo}"), styles["h1"]))
            last_group = group
        story.append(Paragraph(escape(m.nome + (f" — de {m.materia_mae}" if m.materia_mae else "")), styles["h2"]))
        for t in m.topicos:
            page = f" [p. {t.pagina}]" if t.pagina else ""
            content = f"<b>{escape(t.codigo)}</b> " if t.codigo else ""
            content += escape(t.texto + page)
            margin = min(1.8*cm, max(0, t.nivel - 1)*0.3*cm)
            ps = ParagraphStyle("topic", parent=styles["body"], leftIndent=margin)
            story.append(Paragraph(content, ps))
    story.append(Paragraph("3. Auditoria", styles["h1"]))
    if not report.issues:
        story.append(Paragraph("Nenhum aviso automático; a conferência manual ainda é necessária.", styles["body"]))
    for issue in report.issues:
        story.append(Paragraph(escape(f"[{issue.severidade.upper()}] {issue.mensagem}"), styles["small"]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(normal_font, 7.5)
        canvas.setFillColor(colors.HexColor('#778099'))
        canvas.drawRightString(A4[0]-1.5*cm, 0.8*cm, f"Página {doc.page}  ·  Confira o edital original")
        canvas.restoreState()
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
