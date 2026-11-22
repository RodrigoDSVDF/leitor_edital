"""Leitor determinístico e auditável de editais brasileiros de concursos.

Compatível com a API original: build_report(caminho_pdf) -> EditalReport.
O parser não inventa conteúdo nem percentuais: preserva a proveniência (página)
e registra alertas quando o documento não puder ser interpretado com segurança.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd
import pdfplumber

PHASE_COLUMNS = ["prova", "materia", "num_itens", "carater", "pagina", "tabela_id"]


def _norm(s: object) -> str:
    value = str(s or "")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value).strip().upper()


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


@dataclass
class Topico:
    codigo: str
    nivel: int
    texto: str
    pagina: int | None = None
    arquivo: str = ""


@dataclass
class Materia:
    grupo: str
    nome: str
    texto: str
    topicos: list[Topico]
    materia_mae: str | None = None
    subsecoes: list[tuple[str, list[Topico]]] | None = None
    cargo: str = "Geral"
    pagina: int | None = None
    arquivo: str = ""


@dataclass
class AuditIssue:
    severidade: str  # alta / media / informativa
    codigo: str
    mensagem: str
    pagina: int | None = None


@dataclass
class EditalRaw:
    full_text: str
    pages_text: list[str] = field(default_factory=list)
    tables_by_page: dict[int, list[list[list[str | None]]]] = field(default_factory=dict)
    page_offsets: list[int] = field(default_factory=list)

    def page_at(self, offset: int) -> int | None:
        if not self.page_offsets:
            return None
        return max(1, bisect.bisect_right(self.page_offsets, offset))


@dataclass
class EditalReport:
    phase_table: pd.DataFrame
    materias: list[Materia]
    section_preview: str
    section_text: str
    issues: list[AuditIssue] = field(default_factory=list)
    paginas: int = 0
    arquivo: str = ""
    totais_declarados: dict[str, int] = field(default_factory=dict)
    documentos: list[str] = field(default_factory=list)
    documentos_pendentes: list[str] = field(default_factory=list)
    notas_provas: list[str] = field(default_factory=list)

    @property
    def cargos(self) -> list[str]:
        return sorted({m.cargo for m in self.materias})


def _clean_page(text: str, page_number: int) -> str:
    """Mantém quebras de linha (essenciais para distinguir cabeçalhos)."""
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    lines = text.splitlines()
    # Remove apenas número igual à página nas extremidades, nunca no corpo do texto.
    for idx in range(min(2, len(lines))):
        if lines[idx].strip() == str(page_number):
            lines[idx] = ""
    for idx in range(max(0, len(lines) - 2), len(lines)):
        if lines[idx].strip() == str(page_number):
            lines[idx] = ""
    return "\n".join(lines)


def extract_raw(pdf_path: str | Path) -> EditalRaw:
    pages: list[str] = []
    tables: dict[int, list] = {}
    offsets: list[int] = []
    pos = 0
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            offsets.append(pos)
            content = _clean_page(page.extract_text(x_tolerance=2, y_tolerance=3) or "", i + 1)
            pages.append(content)
            pos += len(content) + 1
            # Detecção de tabelas pode falhar em PDFs com células desenhadas como texto.
            try:
                found = page.extract_tables() or []
            except Exception:
                found = []
            if found:
                tables[i] = found
    return EditalRaw("\n".join(pages), pages, tables, offsets)


_HEADER_KEYWORDS = {
    "prova": ("PROVA", "TIPO DE PROVA", "AVALIACAO", "FASE"),
    "materia": ("DISCIPLINA", "MATERIA", "AREA DE CONHECIMENTO", "CONHECIMENTOS", "COMPONENTE"),
    "num_itens": ("NUMERO DE ITENS", "N DE ITENS", "Nº DE ITENS", "ITENS", "QUESTOES", "QUANTIDADE DE QUESTOES", "QTD"),
    "carater": ("CARATER", "ELIMINATORIO", "CLASSIFICATORIO"),
}


def _header_mapping(row: list) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(row):
        name = _norm(cell)
        if not name:
            continue
        for key, choices in _HEADER_KEYWORDS.items():
            if key not in mapping and any(choice in name for choice in choices):
                mapping[key] = idx
                break
    return mapping


def _number(text: object) -> int | None:
    value = _clean(text)
    if not value or value in {"-", "—", "–"}:
        return None
    m = re.fullmatch(r"(\d{1,4})(?:\s*(?:itens|quest[oõ]es))?", value, flags=re.I)
    return int(m.group(1)) if m else None


def _label_prova(s: str) -> str:
    s = _clean(s)
    m = re.search(r"\bP\s*(\d+)\b\s*[-–]?\s*(Objetiva|Discursiva)?", s, flags=re.I)
    if m:
        suffix = s[m.end():].strip(" -–")
        kind = (m.group(2) or "").capitalize()
        return f"P{m.group(1)}" + (f" - {kind}" if kind else "") + (f" - {suffix}" if suffix else "")
    return s


def extract_phase_table(raw: EditalRaw) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict] = []
    totals: dict[str, int] = {}
    table_counter = 0
    for page_index, tables in raw.tables_by_page.items():
        for table in tables:
            if not table:
                continue
            mapping: dict[str, int] = {}
            header_index = -1
            for i, candidate in enumerate(table[:4]):
                proposed = _header_mapping(candidate)
                if {"materia", "num_itens"}.issubset(proposed):
                    mapping, header_index = proposed, i
                    break
            if header_index < 0:
                continue
            table_counter += 1
            last_prova = "Prova objetiva"
            last_carater = ""
            for raw_row in table[header_index + 1:]:
                if not raw_row:
                    continue
                def cell(key: str) -> str:
                    at = mapping.get(key, -1)
                    return _clean(raw_row[at] if 0 <= at < len(raw_row) else "")
                prova, materia, count, carater = cell("prova"), cell("materia"), cell("num_itens"), cell("carater")
                if prova:
                    last_prova = _label_prova(prova)
                if carater:
                    last_carater = carater
                count_number = _number(count)
                if "TOTAL" in _norm(materia) and count_number is not None:
                    totals[f"{table_counter}|{last_prova}"] = count_number
                    continue
                if not materia or _norm(materia) in {"DISCIPLINA", "MATERIA", "AREA DE CONHECIMENTO", "CONHECIMENTOS"}:
                    continue
                if not count and not carater:
                    continue
                rows.append({"prova": last_prova, "materia": materia,
                             "num_itens": count_number if count_number is not None else count,
                             "carater": last_carater, "pagina": page_index + 1, "tabela_id": table_counter})
    return pd.DataFrame(rows, columns=PHASE_COLUMNS), totals


# Não supor que o primeiro resultado seja a seção real: muitos PDFs possuem sumário.
_START = [
    re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?(?:DOS?\s+)?OBJETOS?\s+DE\s+AVALIA[ÇC][ÃA]O\b", re.I | re.M),
    re.compile(r"^\s*(?:ANEXO\s+[IVXLCDM\d]+\s*[-–—:]?\s*)?(?:DOS?\s+)?CONTE[ÚU]DOS?\s+PROGRAM[ÁA]TICOS?\b", re.I | re.M),
    re.compile(r"^\s*PROGRAMA\s+DAS?\s+PROVAS\b", re.I | re.M),
]
_END = [
    re.compile(r"^\s*ANEXO\s+[IVXLCDM\d]+\s*[-–—]\s*(?!CONTE[ÚU]DO|OBJETOS?)\S", re.I | re.M),
    re.compile(r"^\s*(?:DOS?\s+RECURSOS?|DAS?\s+DISPOSI[ÇC][ÕO]ES\s+(?:FINAIS|GERAIS)|DA\s+HOMOLOGA[ÇC][ÃA]O)\b", re.I | re.M),
]


def find_section(full_text: str) -> tuple[int, int, str]:
    candidates: dict[int, int] = {}
    for pat in _START:
        for m in pat.finditer(full_text):
            candidates[m.start()] = m.end()
    if not candidates:
        raise ValueError("Não foi localizada uma seção identificável como 'Conteúdo programático' ou 'Objetos de avaliação'.")
    # Prefere candidato que possua matérias e numeração logo depois do cabeçalho.
    def rank(pair: tuple[int, int]) -> tuple[int, int]:
        start, end = pair
        sample = full_text[end:end + 6000]
        header_count = len(re.findall(r"(?m)^\s*[A-ZÀ-Ü][A-ZÀ-Ü /,&()-]{4,70}:\s*", sample))
        topics = len(re.findall(r"(?m)^\s*\d+(?:\.\d+)*\s+[A-ZÀ-Üa-zà-ü]", sample))
        return (header_count * 4 + topics, start)
    start, _ = max(candidates.items(), key=rank)
    # O encerramento é o primeiro cabeçalho terminal válido depois de 300 caracteres.
    ends = [m.start() for pattern in _END for m in pattern.finditer(full_text, start + 300)]
    end = min(ends) if ends else len(full_text)
    if end <= start:
        end = len(full_text)
    return start, end, full_text[start:end]


_CARGO_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?(CARGO|PERFIL)\s+(\d+)\s*[:\-–]\s*(.{3,130})\s*$", re.I)
_GROUP_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?(CONHECIMENTOS\s+(?:B[ÁA]SICOS|ESPEC[ÍI]FICOS|GERAIS)(?:\s+PARA\s+TODOS\s+OS\s+CARGOS)?|M[ÓO]DULO\s+(?:I|II|III|IV|V)(?:\s*[-–]\s*CONHECIMENTOS\s+.+)?|EIXO\s+TEM[ÁA]TICO\s+\d+(?:\s*[-–:]\s*[^\n]{3,90})?)\s*:?\s*$", re.I)


def _split_contexts(section_text: str) -> list[tuple[str, str, str, int]]:
    """Retorna (cargo, grupo, texto_do_bloco, offset_relativo_no_section_text)."""
    blocks: list[tuple[str, str, str, int]] = []
    cargo = "Geral"
    grupo = "Conteúdo Programático"
    last_content_start = 0
    pos = 0
    for line in section_text.splitlines(keepends=True):
        stripped = line.strip()
        cargo_hit = _CARGO_RE.fullmatch(stripped)
        group_hit = _GROUP_RE.fullmatch(stripped)
        if cargo_hit or group_hit:
            if section_text[last_content_start:pos].strip():
                blocks.append((cargo, grupo, section_text[last_content_start:pos], last_content_start))
            if cargo_hit:
                cargo = f"{cargo_hit.group(1).capitalize()} {cargo_hit.group(2)} — {_clean(cargo_hit.group(3))}"
                grupo = "Conteúdo Programático"
            else:
                grupo = _clean(group_hit.group(1)).title()
            last_content_start = pos + len(line)
        pos += len(line)
    if section_text[last_content_start:].strip():
        blocks.append((cargo, grupo, section_text[last_content_start:], last_content_start))
    return blocks or [("Geral", "Conteúdo Programático", section_text, 0)]


_SUBJECT_RE = re.compile(
    r"^\s*(?:\d{1,3}(?:\.\d{1,3}){0,5}\s+)?"
    r"(?P<name>[A-ZÀ-Ü][A-ZÀ-Ü0-9 /,()&º°ª+\-–.]{3,100}?)\s*:\s*(?P<tail>.*)$"
)
_ROMAN_RE = re.compile(r"^\s*(?P<roman>X{0,3}(?:IX|IV|V?I{0,3})|X{1,3}|XL|L|C)\s+(?P<name>[A-ZÀ-Ü][A-ZÀ-Ü /,()&\-]{3,90})\s*:\s*(?P<tail>.*)$")
_SUBJECT_BLOCKLIST = {"CONHECIMENTOS", "CONHECIMENTOS BASICOS", "CONHECIMENTOS ESPECIFICOS", "CONHECIMENTOS GERAIS", "OBJETOS DE AVALIACAO", "CONTEUDO PROGRAMATICO", "PROVA OBJETIVA", "PROVA DISCURSIVA", "HABILIDADES"}


def _is_subject(name: str) -> bool:
    norm = _norm(name)
    if norm in _SUBJECT_BLOCKLIST or norm.startswith(("CARGO ", "PERFIL ", "ANEXO ", "TOTAL ")):
        return False
    if re.match(r"^(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\s+", norm):
        return False
    if len(name.split()) > 14 or len(name) > 100 or re.search(r"[.!?]\s+[A-ZÀ-Ü]", name):
        return False
    if name.count("(") != name.count(")"):
        return False
    return len(name) >= 4 and any(c.isalpha() for c in name)


def _find_subjects(text: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        m = _SUBJECT_RE.match(line.rstrip("\r\n"))
        if m and _is_subject(m.group("name")):
            # end at colon: remainder on same line belongs to subject's content.
            colon_end = cursor + m.start("tail")
            found.append((cursor, colon_end, _clean(m.group("name"))))
        cursor += len(line)
    return found


_TOPIC_START_RE = re.compile(
    r"(?m)^[ \t]*(?P<code>\d{1,3}(?:\.\d{1,3}){0,6})\.?[ \t]+(?=[\wÀ-ü(\"“])"
    r"|(?<=[.;])\s+(?P<inline>\d{1,3}(?:\.\d{1,3}){0,6})\.?\s+(?=[A-ZÀ-Ü(\"“])"
)


def extract_topics_hierarchical(content: str, locate: Callable[[int], int | None] | None = None) -> list[Topico]:
    """Extrai até sete níveis, preservando um item não numerado antes da lista."""
    if not content or not content.strip():
        return []
    matches = list(_TOPIC_START_RE.finditer(content))
    if not matches:
        return [Topico("", 0, _clean(content), locate(0) if locate else None)]
    topics: list[Topico] = []
    preface = _clean(content[:matches[0].start()])
    if preface:
        topics.append(Topico("", 0, preface, locate(0) if locate else None))
    for i, m in enumerate(matches):
        code = m.group("code") or m.group("inline")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        fragment = content[m.end():end]
        description = _clean(fragment)
        if description:
            topics.append(Topico(code, code.count(".") + 1, description,
                                 locate(m.start()) if locate else None))
    return topics


def _split_romans(content: str) -> list[tuple[str, str, int]]:
    hits: list[tuple[int, int, str]] = []
    pos = 0
    for line in content.splitlines(keepends=True):
        m = _ROMAN_RE.match(line)
        if m and _norm(m.group("roman")) in {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"}:
            hits.append((pos, pos + m.start("tail"), f"{m.group('roman')} {m.group('name')}"))
        pos += len(line)
    if len(hits) < 2 or hits[0][0] > 150:
        return []
    result: list[tuple[str, str, int]] = []
    for i, (_, after_header, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(content)
        result.append((name, content[after_header:end], after_header))
    return result


def _parse_block(cargo: str, grupo: str, text: str, offset: int, raw: EditalRaw, section_offset: int) -> list[Materia]:
    headers = _find_subjects(text)
    output: list[Materia] = []
    if not headers:
        # Não transforme o próprio título da seção em disciplina fictícia.
        noncontent = re.sub(r"(?im)^\s*(?:ANEXO\s+[IVXLCDM\d]+\s*[-–—:]?\s*)?(?:CONTE[ÚU]DO\s+PROGRAM[ÁA]TICO|OBJETOS?\s+DE\s+AVALIA[ÇC][ÃA]O)\s*$", "", text)
        if not noncontent.strip():
            return []
        # Evita descartar conteúdos de formato fora do padrão: usuário pode revisar.
        topicos = extract_topics_hierarchical(noncontent, lambda at: raw.page_at(section_offset + offset + at))
        return [Materia(grupo, "Conteúdo não classificado", _clean(noncontent), topicos,
                        cargo=cargo, pagina=raw.page_at(section_offset + offset))] if topicos else []
    for idx, (start, after_header, nome) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(text)
        content = text[after_header:end]
        location_base = section_offset + offset + after_header
        roman_parts = _split_romans(content)
        if roman_parts:
            for sub_name, sub_content, sub_off in roman_parts:
                topics = extract_topics_hierarchical(sub_content, lambda at, n=sub_off: raw.page_at(location_base + n + at))
                if topics:
                    output.append(Materia(grupo, sub_name, _clean(sub_content), topics,
                                          materia_mae=nome, cargo=cargo,
                                          pagina=raw.page_at(location_base + sub_off)))
        else:
            topics = extract_topics_hierarchical(content, lambda at: raw.page_at(location_base + at))
            if topics:
                output.append(Materia(grupo, nome, _clean(content), topics, cargo=cargo,
                                      pagina=raw.page_at(section_offset + offset + start)))
    return output


def _validate(report: EditalReport, raw: EditalRaw) -> None:
    issues = report.issues
    if not report.phase_table.empty:
        df = report.phase_table.copy()
        df["valor"] = pd.to_numeric(df["num_itens"], errors="coerce")
        for (table_id, prova), group in df.groupby(["tabela_id", "prova"], dropna=False):
            known = int(group["valor"].sum())
            no_number = int(group["valor"].isna().sum())
            if no_number:
                issues.append(AuditIssue("media", "ITENS_SEM_NUMERO", f"{prova}: {no_number} linha(s) sem número de itens verificável."))
            declared = report.totais_declarados.get(f"{table_id}|{prova}")
            if declared is not None and known != declared:
                issues.append(AuditIssue("alta", "TOTAL_DIVERGENTE", f"{prova}: foram extraídos {known} itens, mas a tabela declara {declared}."))
            elif declared is None and not re.search(r"discursiv|reda[çc][ãa]o|t[ií]tulos|pr[aá]tic|teste f[ií]sico|taf", str(prova), re.I):
                issues.append(AuditIssue("informativa", "TOTAL_NAO_DECLARADO", f"{prova}: total utilizado no gráfico ({known}) é calculado pelas linhas reconhecidas; confira o edital."))
    else:
        issues.append(AuditIssue("alta", "SEM_TABELA", "Tabela de provas e itens não reconhecida. O conteúdo pode ser mapeado, mas os pesos não foram calculados."))
    if not report.materias:
        issues.append(AuditIssue("alta", "SEM_MATERIAS", "Nenhuma matéria foi identificada no conteúdo programático."))
    for m in report.materias:
        if m.nome == "Conteúdo não classificado":
            issues.append(AuditIssue("media", "SEM_CABECALHO", f"Trecho de {m.cargo} / {m.grupo} não pôde ser classificado por disciplina.", m.pagina))
        numbered = [t for t in m.topicos if t.codigo]
        if not numbered:
            issues.append(AuditIssue("media", "SEM_NUMERACAO", f"{m.nome}: tópicos sem numeração reconhecida; revisão recomendada.", m.pagina))
        codes = {t.codigo for t in numbered}
        if len(codes) != len(numbered):
            issues.append(AuditIssue("media", "CODIGOS_REPETIDOS", f"{m.nome}: há códigos de tópico repetidos.", m.pagina))
        for topic in numbered:
            if topic.nivel > 1:
                parent = topic.codigo.rsplit(".", 1)[0]
                if parent not in codes:
                    issues.append(AuditIssue("informativa", "PAI_AUSENTE", f"{m.nome}: tópico {topic.codigo} não tem o item pai {parent} reconhecido.", topic.pagina))
                    break
    # Páginas com pouco texto são uma indicação, não uma confirmação, de PDF escaneado.
    thin_pages = [i + 1 for i, txt in enumerate(raw.pages_text) if len(txt.strip()) < 40]
    if thin_pages:
        issues.append(AuditIssue("media", "PAGINAS_POUCO_TEXTO", f"{len(thin_pages)} página(s) sem texto pesquisável suficiente: {', '.join(map(str, thin_pages[:12]))}. Podem ser imagens ou páginas em branco."))




def _provas_narrativas(raw: EditalRaw) -> tuple[pd.DataFrame, list[str]]:
    """Reconhece quantitativos expressos em parágrafos, sem criar matérias fictícias.

    Abrange a redação encontrada no edital principal do CPNU2; outros layouts
    continuam dependendo de regras de extração adicionais ou revisão manual.
    """
    texto = raw.full_text
    horizontal = re.sub(r"\s+", " ", texto)
    rows: list[dict] = []
    notas: list[str] = []

    def pagina_para(trecho: str) -> int | None:
        m = re.search(re.escape(trecho), texto, re.I)
        return raw.page_at(m.start()) if m else None

    # Não confunde distribuição de questões com os pesos da pontuação.
    sup = re.search(
        r"Para os cargos de N[íi]vel Superior, a Prova Objetiva será composta por\s*"
        r"(\d+)\s*\([^)]*\)\s*questões,\s*sendo\s*"
        r"(\d+)\s*\([^)]*\)\s*questões de Conhecimentos Gerais\s+e\s*"
        r"(\d+)\s*\([^)]*\)\s*questões de Conhecimentos Específicos",
        horizontal, re.I,
    )
    if sup:
        total, gerais, especificos = (int(x) for x in sup.groups())
        if total == gerais + especificos and total > 0:
            page = pagina_para("8.9.")
            for materia, itens in [("Conhecimentos Gerais", gerais), ("Conhecimentos Específicos", especificos)]:
                rows.append({"prova": "Nível Superior — Prova objetiva", "materia": materia,
                             "num_itens": itens, "carater": "Eliminatório e classificatório",
                             "pagina": page, "tabela_id": 9001, "escopo": "bloco", "origem_tipo": "texto"})
            notas.append(f"Nível superior: {total} questões = {gerais} gerais + {especificos} específicas (item 8.9).")
            if re.search(r"5\s*\(cinco\)\s*eixos temáticos, cada\s+um contendo\s*12\s*\(doze\)\s*questões", horizontal, re.I):
                notas.append("As 60 questões específicas são distribuídas em 5 eixos de 12 questões; os pesos na pontuação dependem do cargo/especialidade (itens 8.9.1 a 8.9.3).")

    inter = re.search(
        r"Para os cargos de N[íi]vel Intermediário, a Prova Objetiva será composta por\s*(\d+)\s*\([^)]*\)\s*questões",
        horizontal, re.I,
    )
    if inter:
        total = int(inter.group(1))
        if total > 0:
            rows.append({"prova": "Nível Intermediário — Prova objetiva", "materia": "Total — disciplinas especificadas nos anexos",
                         "num_itens": total, "carater": "Eliminatório e classificatório",
                         "pagina": pagina_para("8.10."), "tabela_id": 9002,
                         "escopo": "total", "origem_tipo": "texto"})
            notas.append(f"Nível intermediário: {total} questões; distribuição por matéria requer os anexos VIII e IX (item 8.10).")

    return pd.DataFrame(rows, columns=PHASE_COLUMNS + ["escopo", "origem_tipo"]), notas


def _documentos_complementares(text: str) -> list[str]:
    """Aponta dependências textuais explícitas, nunca supõe conteúdo ausente."""
    norm = _norm(text)
    if re.search(r"CONTEUDOS? PROGRAMATICOS?.{0,110}ANEXOS? I A IX", norm) or re.search(
        r"CONTEUDOS? PROGRAMATICOS? APRESENTADOS NOS ANEXOS? I A IX", norm
    ):
        return ["Anexos I a IX — conteúdos programáticos e distribuição por bloco/cargo"]
    if re.search(r"CONTEUDOS? PROGRAMATICOS?.{0,110}ANEXOS?", norm):
        return ["Anexos citados no edital — conferir e enviar os PDFs contendo o conteúdo programático"]
    return []


def build_reports(documents: list[tuple[str, str | Path]]) -> EditalReport:
    """Une vários PDFs, preservando a identificação de origem de cada extração."""
    if not documents:
        raise ValueError("Envie ao menos um arquivo PDF.")
    reports: list[EditalReport] = []
    for nome, caminho in documents:
        result = build_report(caminho)
        result.arquivo = nome
        result.documentos = [nome]
        for m in result.materias:
            m.arquivo = nome
            for t in m.topicos:
                t.arquivo = nome
        if not result.phase_table.empty:
            result.phase_table["arquivo"] = nome
        reports.append(result)
    if len(reports) == 1:
        return reports[0]
    frames: list[pd.DataFrame] = []
    totals: dict[str, int] = {}
    for ix, r in enumerate(reports):
        if not r.phase_table.empty:
            df = r.phase_table.copy()
            if "tabela_id" in df:
                # IDs únicos por arquivo evitam que a interface some tabelas diferentes.
                df["tabela_id"] = pd.to_numeric(df["tabela_id"], errors="coerce").fillna(0).astype(int) + ix*10000
            frames.append(df)
        for key, val in r.totais_declarados.items():
            token, sep, prova = key.partition("|")
            if sep:
                totals[f"{int(token) + ix*10000}|{prova}"] = val
    notes = list(dict.fromkeys(note for r in reports for note in r.notas_provas))
    issues: list[AuditIssue] = []
    for r in reports:
        for issue in r.issues:
            issues.append(AuditIssue(issue.severidade, issue.codigo, f"[{r.arquivo}] {issue.mensagem}", issue.pagina))
    return EditalReport(
        phase_table=pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PHASE_COLUMNS),
        materias=[m for r in reports for m in r.materias],
        section_preview="\n\n".join(f"=== {r.arquivo} ===\n{r.section_preview}" for r in reports),
        section_text="\n\n".join(r.section_text for r in reports if r.section_text),
        issues=issues, paginas=sum(r.paginas for r in reports),
        arquivo=f"{len(reports)} documentos", totais_declarados=totals,
        documentos=[name for name, _ in documents],
        documentos_pendentes=list(dict.fromkeys(n for r in reports for n in r.documentos_pendentes)),
        notas_provas=notes,
    )


def build_report(pdf_path: str | Path) -> EditalReport:
    raw = extract_raw(pdf_path)
    if not raw.full_text.strip():
        raise ValueError("PDF sem texto pesquisável. Converta uma cópia escaneada para PDF pesquisável antes do envio.")
    phase_table, totals = extract_phase_table(raw)
    notes: list[str] = []
    if phase_table.empty:
        phase_table, notes = _provas_narrativas(raw)
        # Totais explicitamente declarados no texto, não calculados por suposição.
        for (ident, prova), part in phase_table.groupby(["tabela_id", "prova"]):
            totals[f"{ident}|{prova}"] = int(part["num_itens"].sum())
    elif "escopo" not in phase_table:
        phase_table["escopo"] = "disciplina"
    if "origem_tipo" not in phase_table:
        phase_table["origem_tipo"] = "tabela"
    deps = _documentos_complementares(raw.full_text)
    issues: list[AuditIssue] = []
    try:
        start, _, section_text = find_section(raw.full_text)
    except ValueError:
        # Ausência de conteúdo no PDF principal não invalida suas outras informações.
        start, section_text = 0, ""
        if deps:
            issues.append(AuditIssue("alta", "CONTEUDO_EM_ANEXOS",
                "O documento remete a anexos externos para o conteúdo programático; envie também os arquivos complementares."))
        else:
            issues.append(AuditIssue("alta", "SECAO_NAO_LOCALIZADA",
                "A seção de conteúdo programático não foi reconhecida. Não foram criadas disciplinas fictícias."))
    materias: list[Materia] = []
    if section_text:
        for cargo, grupo, block, offset in _split_contexts(section_text):
            materias.extend(_parse_block(cargo, grupo, block, offset, raw, start))
    result = EditalReport(
        phase_table=phase_table, materias=materias,
        section_preview=section_text[:4000], section_text=section_text,
        issues=issues,
        paginas=len(raw.pages_text), arquivo=Path(pdf_path).name,
        documentos=[Path(pdf_path).name], documentos_pendentes=deps,
        notas_provas=notes, totais_declarados=totals,
    )
    _validate(result, raw)
    return result
