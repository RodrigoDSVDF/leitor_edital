"""ÉDITO Pro — Mapeador e auditor de editais (Streamlit)."""
from __future__ import annotations

import copy
import hashlib
import html
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import parser as P
import report_builder as RB

st.set_page_config(page_title="ÉDITO Pro | Inteligência de Editais", page_icon="📋", layout="wide",
                   initial_sidebar_state="expanded")

ROOT = Path(__file__).parent
st.markdown(f"<style>{(ROOT / 'styles.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def h(s: object) -> str:
    return html.escape(str(s or ""), quote=True)


def metric(label: str, val: str, css: str = "") -> None:
    st.markdown(f'<div class="edito-metric"><small>{h(label)}</small><strong class="{css}">{h(val)}</strong></div>', unsafe_allow_html=True)


def section(name: str, caption: str = "") -> None:
    st.markdown(f'<div class="edito-section"><h3>{h(name)}</h3><span>{h(caption)}</span></div>', unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=8)
def parse_pdf(content: bytes, display_name: str) -> P.EditalReport:
    # Arquivo temporário é sempre limpo, inclusive se o parser lançar exceção.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        filename = tmp.name
    try:
        output = P.build_report(filename)
        output.arquivo = display_name
        return output
    finally:
        Path(filename).unlink(missing_ok=True)


def plan_frame(report: P.EditalReport) -> pd.DataFrame:
    data = []
    for m in report.materias:
        for t in m.topicos:
            data.append({"cargo": m.cargo, "grupo": m.grupo, "materia": m.nome,
                         "codigo": t.codigo, "nivel": t.nivel, "topico": t.texto,
                         "status": "Não iniciado", "prioridade": "Média", "data_revisao": "",
                         "observacoes": "", "pagina": t.pagina})
    return pd.DataFrame(data, columns=["cargo", "grupo", "materia", "codigo", "nivel", "topico", "status", "prioridade", "data_revisao", "observacoes", "pagina"])


st.markdown('''
<div class="edito-top"><div class="edito-icon">◈</div><div class="edito-brand">ÉDITO<span>.</span></div><div class="edito-minor">EXTRACTION INTELLIGENCE / PRO</div></div>
<div class="edito-hero">
 <div class="edito-kicker">Inteligência aplicada a concursos</div>
 <h1>Seu edital, <em>decodificado.</em></h1>
 <p>Transforme centenas de páginas em um mapa de provas, matérias e tópicos — com conferência de origem, planejamento e relatórios profissionais.</p>
 <div class="edito-tags"><span class="edito-tag">PDF → Estrutura</span><span class="edito-tag">Auditoria de extração</span><span class="edito-tag">Planejamento de estudos</span><span class="edito-tag">Word · Excel · PDF</span></div>
</div>
''', unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="edito-top"><div class="edito-icon">◈</div><div class="edito-brand">ÉDITO<span>.</span></div></div>', unsafe_allow_html=True)
    st.caption("WORKSPACE  /  MAPEAMENTO")
    uploaded = st.file_uploader("Enviar edital em PDF", type=["pdf"], help="Para PDFs digitalizados, realize OCR previamente.")
    st.divider()
    st.markdown("**Como funciona**")
    st.caption("01  Envie um PDF pesquisável")
    st.caption("02  Confira alertas e corrija a tabela")
    st.caption("03  Explore os tópicos e planeje")
    st.caption("04  Exporte documentos")
    st.divider()
    st.caption("🔐 Processamento local no servidor Streamlit. IA opcional somente com sua autorização.")

if uploaded is None:
    st.markdown('<div class="edito-empty"><strong>Comece pelo seu edital.</strong>Arraste um PDF pesquisável para o painel lateral para visualizar o mapeamento.</div>', unsafe_allow_html=True)
    st.info("Compatível com layouts de diferentes bancas, mas toda extração deve ser conferida no PDF original. PDFs escaneados exigem OCR prévio.")
    st.stop()

content = uploaded.getvalue()
file_id = hashlib.sha256(content).hexdigest()[:12]
with st.spinner("Analisando páginas, tabelas, cargos e tópicos..."):
    try:
        source_report = parse_pdf(content, uploaded.name)
    except Exception as exc:
        st.error(f"Não foi possível interpretar o edital: {exc}")
        st.caption("Confira se é um PDF pesquisável e se contém uma seção 'Conteúdo programático' ou 'Objetos de avaliação'.")
        st.stop()
report = copy.deepcopy(source_report)

with st.sidebar:
    st.success(f"{uploaded.name}  ·  {report.paginas} pág.")
    options = ["Todos os cargos"] + report.cargos
    cargo_sel = st.selectbox("Visualizar cargo/perfil", options)
    st.caption("A tabela de provas pode abranger cargos distintos. Confirme cada linha na fonte.")

shown = [m for m in report.materias if cargo_sel == "Todos os cargos" or m.cargo == cargo_sel]
count_topics = sum(len(m.topicos) for m in shown)
with st.container():
    cols = st.columns(4)
    with cols[0]: metric("Disciplinas identificadas", str(len(shown)), "glow")
    with cols[1]: metric("Tópicos mapeados", str(count_topics))
    with cols[2]: metric("Páginas analisadas", str(report.paginas), "cyan")
    with cols[3]: metric("Alertas de auditoria", str(len(report.issues)))

if any(i.severidade == "alta" for i in report.issues):
    st.warning("Foram detectadas inconsistências importantes. Consulte a aba **Auditoria** antes de usar os pesos ou planejar os estudos.")

(t_overview, t_provas, t_content, t_plan, t_audit, t_export) = st.tabs([
    "◈  Visão geral", "▤  Provas e pesos", "▣  Conteúdo", "✓  Plano de estudos", "⚑  Auditoria", "⇩  Exportar"
])

with t_overview:
    section("Panorama do edital", "Estrutura encontrada no PDF")
    simple = sum(not bool(m.materia_mae) for m in shown)
    compound = len(shown) - simple
    cols2 = st.columns(3)
    with cols2[0]: st.metric("Matérias simples", simple)
    with cols2[1]: st.metric("Submatérias de blocos compostos", compound)
    with cols2[2]: st.metric("Cargos identificados", len(report.cargos))
    st.divider()
    by_group = pd.DataFrame([{"cargo": m.cargo, "grupo": m.grupo, "materia": m.nome, "topicos": len(m.topicos)} for m in shown])
    if not by_group.empty:
        amounts = by_group.groupby(["cargo", "grupo"], as_index=False)["topicos"].sum().sort_values("topicos", ascending=False)
        fig = px.bar(amounts, x="topicos", y="grupo", color="cargo", orientation="h",
                     labels={"topicos": "Quantidade de tópicos", "grupo": "", "cargo": "Cargo"},
                     template="plotly_dark", color_discrete_sequence=["#9a89ff", "#55d2c6", "#f5b46d", "#ff91bb"])
        fig.update_layout(paper_bgcolor="#080b12", plot_bgcolor="#080b12", font_color="#dce0ed",
                          height=max(260, 55 * len(amounts)), margin=dict(l=15,r=20,t=10,b=40), legend=dict(orientation="h", y=1.17))
        fig.update_xaxes(showgrid=True, gridcolor="#273044")
        fig.update_yaxes(categoryorder="total ascending")
        st.plotly_chart(fig, use_container_width=True)
    st.markdown('<div class="edito-note">Os gráficos refletem somente o que foi reconhecido. Confira a auditoria e a origem das informações antes de tomar decisões de estudo.</div>', unsafe_allow_html=True)

with t_provas:
    section("Distribuição da prova", "Edite os números caso a leitura automática precise de correção")
    df = report.phase_table.copy()
    if df.empty:
        st.warning("Nenhuma tabela de provas e quantidade de itens foi reconhecida automaticamente.")
        df = pd.DataFrame(columns=["prova", "materia", "num_itens", "carater", "pagina"])
    df["num_itens"] = pd.to_numeric(df["num_itens"], errors="coerce")
    base_columns = [c for c in ["prova", "materia", "num_itens", "carater", "pagina", "tabela_id"] if c in df.columns]
    edited = st.data_editor(df[base_columns], hide_index=True, use_container_width=True,
                            num_rows="dynamic", key=f"proof_editor_{file_id}",
                            column_config={
                                "prova": st.column_config.TextColumn("Prova", required=True),
                                "materia": st.column_config.TextColumn("Matéria ou bloco", required=True),
                                "num_itens": st.column_config.NumberColumn("Número de itens", min_value=0, step=1, format="%d"),
                                "carater": st.column_config.TextColumn("Caráter"),
                                "pagina": st.column_config.NumberColumn("Página de origem", disabled=True),
                                "tabela_id": st.column_config.NumberColumn("Tabela nº", disabled=True),
                            })
    # As edições são aplicadas a todos os exports nesta execução.
    report.phase_table = edited.copy()
    report.phase_table = report.phase_table.dropna(subset=["prova", "materia"], how="any")
    if len(report.cargos) > 1:
        st.warning("Há múltiplos cargos. As tabelas de prova não foram vinculadas automaticamente a cada cargo; não some provas de cargos diferentes sem conferir o edital.")
    weights = RB._weighted_table(report.phase_table)
    plots = weights[weights["peso_%"].notna()].copy() if not weights.empty else pd.DataFrame()
    if plots.empty:
        st.info("Não há quantidades de itens objetivas suficientes para calcular percentuais.")
    else:
        keycols = ["prova", "tabela_id"] if "tabela_id" in plots else ["prova"]
        for proofkey, sub in plots.groupby(keycols, sort=False, dropna=False):
            proof = proofkey[0] if isinstance(proofkey, tuple) else proofkey
            table_tag = f" · tabela {int(proofkey[1])}" if isinstance(proofkey, tuple) and pd.notna(proofkey[1]) else ""
            total = sub["num_itens_num"].sum()
            st.markdown(f"**{h(proof)}{h(table_tag)}**  ·  {int(total)} itens identificados")
            sub = sub.sort_values("num_itens_num", ascending=True)
            fig = px.bar(sub, x="num_itens_num", y="materia", orientation="h", text="peso_%",
                         labels={"num_itens_num": "Número de itens", "materia": ""},
                         template="plotly_dark", color_discrete_sequence=["#8f7ef5"])
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside", cliponaxis=False,
                              marker_line_width=0, marker_cornerradius=5)
            fig.update_layout(paper_bgcolor="#080b12", plot_bgcolor="#080b12", font_color="#dce0ed",
                              showlegend=False, height=max(230, 43*len(sub)),
                              margin=dict(l=10,r=50,t=8,b=30))
            fig.update_xaxes(gridcolor="#242b3d", range=[0, max(1, sub["num_itens_num"].max()*1.22)])
            st.plotly_chart(fig, use_container_width=True)
    st.caption("Pesos = itens da linha / soma dos itens reconhecidos na mesma prova. Não corresponde necessariamente ao peso da nota quando há critérios diferentes de pontuação.")

with t_content:
    section("Biblioteca de disciplinas", "Exploração por cargo, grupo e tópico")
    search = st.text_input("Localizar assunto", placeholder="Ex.: licitações, atos administrativos, direitos fundamentais...")
    groups = sorted({m.grupo for m in shown})
    group_filter = st.multiselect("Grupos de conhecimento", groups, default=groups)
    only_composite = st.toggle("Apenas submatérias de disciplinas compostas", value=False)
    results = [m for m in shown if m.grupo in group_filter
               and (bool(m.materia_mae) if only_composite else True)
               and (not search or search.casefold() in (m.nome + " " + " ".join(t.texto for t in m.topicos)).casefold())]
    st.caption(f"{len(results)} disciplina(s) correspondente(s) aos filtros")
    for m in results:
        name = m.nome + (f"  ·  origem: {m.materia_mae}" if m.materia_mae else "")
        with st.expander(f"{name}  ·  {m.grupo}  ·  {len(m.topicos)} tópicos", expanded=False):
            st.caption(f"{m.cargo} · página de referência: {m.pagina or 'não localizada'}")
            topic_html = []
            for t in m.topicos:
                if search and search.casefold() not in t.texto.casefold() and search.casefold() not in m.nome.casefold():
                    continue
                indent = min(max(t.nivel-1, 0), 6)*18
                page = f'<span class="edito-pg">p. {t.pagina}</span>' if t.pagina else ""
                topic_html.append(f'<div class="edito-topic" style="margin-left:{indent}px"><span class="edito-topic-code">{h(t.codigo or "•")}</span><span>{h(t.texto)}</span>{page}</div>')
            if topic_html:
                st.markdown("".join(topic_html), unsafe_allow_html=True)
            else:
                st.info("Nenhum tópico específico corresponde à busca.")
    if not results:
        st.info("Nenhuma disciplina encontrada para estes filtros.")

# Plano permite edição e é compartilhado com exportação XLSX.
with t_plan:
    section("Plano de estudos", "Controle de execução por tópico")
    if f"plan_{file_id}" not in st.session_state:
        st.session_state[f"plan_{file_id}"] = plan_frame(source_report)
    full_plan = st.session_state[f"plan_{file_id}"].copy()
    mask = full_plan["cargo"].eq(cargo_sel) if cargo_sel != "Todos os cargos" else pd.Series(True, index=full_plan.index)
    st.caption("Edite o status, a prioridade, a revisão e suas observações. Essas alterações serão incluídas no Excel exportado; não são salvas na nuvem.")
    view_plan = full_plan.loc[mask].copy()
    view_plan.insert(0, "id_interno", view_plan.index)
    plan_edit = st.data_editor(view_plan, key=f"plan_editor_{file_id}_{hashlib.sha1(cargo_sel.encode()).hexdigest()[:8]}",
                               hide_index=True, use_container_width=True,
                               disabled=["id_interno", "cargo", "grupo", "materia", "codigo", "nivel", "topico", "pagina"],
                               column_config={
                                   "id_interno": None,
                                   "status": st.column_config.SelectboxColumn("Status", options=["Não iniciado", "Em andamento", "Concluído"]),
                                   "prioridade": st.column_config.SelectboxColumn("Prioridade", options=["Alta", "Média", "Baixa"]),
                                   "data_revisao": st.column_config.TextColumn("Revisão (dd/mm/aaaa)"),
                                   "observacoes": st.column_config.TextColumn("Observações", width="large"),
                                   "topico": st.column_config.TextColumn("Tópico", width="large"),
                               })
    if not plan_edit.empty:
        for _, row in plan_edit.iterrows():
            row_id = int(row["id_interno"])
            for key in ("status", "prioridade", "data_revisao", "observacoes"):
                full_plan.at[row_id, key] = row[key]
        st.session_state[f"plan_{file_id}"] = full_plan
    done = int((full_plan.loc[mask, "status"] == "Concluído").sum())
    total = len(full_plan.loc[mask])
    st.progress(done / total if total else 0, text=f"{done} de {total} tópicos concluídos ({(100*done/total if total else 0):.1f}%)")
    st.info("A ordenação dos assuntos por prioridade é definida por você. Os pesos da prova representam itens, não necessariamente a importância pedagógica de cada tópico.")

with t_audit:
    section("Auditoria da extração", "Falhas e pontos a conferir")
    st.caption("Alertas automáticos não substituem a conferência da íntegra do edital.")
    important = sum(i.severidade == "alta" for i in source_report.issues)
    medium = sum(i.severidade == "media" for i in source_report.issues)
    alert_cols = st.columns(3)
    alert_cols[0].metric("Alta prioridade", important)
    alert_cols[1].metric("Revisão recomendada", medium)
    alert_cols[2].metric("Informativos", len(source_report.issues)-important-medium)
    if report.phase_table.shape != source_report.phase_table.shape or not report.phase_table.reset_index(drop=True).equals(source_report.phase_table.reset_index(drop=True)):
        st.info("A tabela foi editada na interface. Os avisos abaixo referem-se à extração original e precisam ser revistos após as correções.")
    if source_report.issues:
        for issue in source_report.issues:
            icon = "🔴" if issue.severidade == "alta" else "🟠" if issue.severidade == "media" else "🔵"
            st.markdown(f"{icon} **{h(issue.codigo)}** — {h(issue.mensagem)}" +
                        (f" · *pág. {issue.pagina}*" if issue.pagina else ""))
    else:
        st.success("Nenhum alerta automático. Ainda é necessário comparar com o PDF original.")
    with st.expander("Prévia da seção capturada — conferência técnica"):
        st.code(source_report.section_preview, language=None)

    st.divider()
    st.subheader("Revisão opcional com IA")
    st.caption("A IA não altera os dados automaticamente. Usa uma amostra limitada da seção e dos avisos; exige uma chave de API própria e sua autorização de envio para um serviço externo.")
    agree = st.checkbox("Autorizo o envio de trechos deste edital e dos alertas para a API escolhida.")
    key = st.text_input("Chave de API OpenAI", type="password", help="Não é gravada em arquivos do projeto.")
    model = st.text_input("Modelo da API", value="gpt-4.1-mini")
    if st.button("Solicitar parecer da IA", disabled=not(agree and key.strip()), type="secondary"):
        try:
            from ai_helper import review_extract
            with st.spinner("Solicitando parecer, sem modificar os dados extraídos..."):
                st.session_state[f"ai_{file_id}"] = review_extract(source_report, key, model)
        except Exception as exc:
            st.error(f"A revisão pela IA não pôde ser concluída: {exc}")
    if f"ai_{file_id}" in st.session_state:
        st.markdown(st.session_state[f"ai_{file_id}"])

with t_export:
    section("Central de exportação", "Relatórios organizados e editáveis")
    title = st.text_input("Título para Word e PDF", value="Relatório de Inteligência de Edital")
    st.caption("O Excel inclui uma aba de planejamento com os status que você editou aqui. Word e PDF incluem a auditoria e as páginas-fonte dos tópicos.")
    a, b, c = st.columns(3)
    with a:
        st.download_button("⇩  Relatório Word", data=RB.build_docx(report, titulo=title),
                           file_name="relatorio_edital.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           use_container_width=True, type="primary")
    with b:
        st.download_button("⇩  Excel + plano", data=RB.build_xlsx(report, plano=st.session_state.get(f"plan_{file_id}")),
                           file_name="mapeamento_edital.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    with c:
        try:
            pdf_bytes = RB.build_pdf(report, titulo=title)
            st.download_button("⇩  Relatório PDF", data=pdf_bytes, file_name="relatorio_edital.pdf",
                               mime="application/pdf", use_container_width=True)
        except Exception as exc:
            st.error(f"Falha na criação do PDF: {exc}")
    st.markdown('<div class="edito-note">Atenção: o sistema não certifica que todos os conteúdos do edital foram encontrados. Compare as matérias, os quantitativos e os itens com o documento original.</div>', unsafe_allow_html=True)
