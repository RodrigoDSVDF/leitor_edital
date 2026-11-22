# ÉDITO Pro — Mapeador de Editais

Aplicação Streamlit com interface escura premium, extração de tabelas de provas, leitura de múltiplos cargos, divisão de disciplinas compostas, tópicos hierárquicos com indicação da página, auditoria, editor de provas, planejamento editável e relatórios Word, Excel e PDF.

## Rodar localmente

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Publicar no Streamlit Community Cloud

1. Envie todos os arquivos deste diretório para um repositório GitHub, mantendo a pasta `.streamlit`.
2. No painel de apps do Streamlit, aponte **Main file path** para `app.py`.
3. Configure o projeto como público se quiser que visitantes acessem sem autorização.
4. Não inclua chaves de API em `requirements.txt`, `app.py`, no Git ou no histórico do projeto.

## Principais arquivos

| Arquivo | Função |
|---|---|
| `app.py` | Interface Streamlit, filtros, gráficos, edição e download |
| `styles.css` | Visual escuro responsivo |
| `parser.py` | Extração, estrutura, páginas e auditoria |
| `report_builder.py` | Exportação Word, Excel com checklist e PDF |
| `ai_helper.py` | Parecer opcional via API OpenAI, somente com consentimento |
| `tests/test_pipeline.py` | Testes sintéticos de hierarquia, cargos, pesos e exportações |
| `.streamlit/config.toml` | Tema e limite de upload |

## O que foi melhorado

- Linhas preservadas durante o reconhecimento: o aplicativo não colapsa prematuramente todos os parágrafos.
- Níveis hierárquicos até sete componentes (`1.2.3.4`, etc.).
- Grupos por cargo/perfil, além de Conhecimentos Básicos/Gerais/Específicos.
- Seções romanas em matérias compostas.
- Origem por página (estimada por posição do texto extraído).
- Análise de inconsistências: falta de tabela, faltas de número de itens, divergência com total declarado, cabeçalhos sem classificação, códigos repetidos e tópicos com pais ausentes.
- **Sem percentuais fictícios:** na ausência de números válidos não calcula; prova discursiva não entra no peso objetivo.
- Tabela de prova editável no Streamlit (modificações incluídas na exportação).
- Plano de estudo por tópico, com status e prioridades; exportação do progresso para Excel.
- Excel com folhas `Painel`, `Provas e Pesos`, `Conteúdo Programático`, `Resumo`, `Auditoria` e `Plano de Estudos`.
- DOCX e PDF com seção de auditoria.
- Arquivo temporário é removido automaticamente após o processamento.

## Limitações / cuidados importantes

- O parser é baseado em regras e não garante cobertura universal de todos os modelos de editais; tabelas complexas, colunas e PDFs com linhas quebradas ainda requerem conferência.
- PDFs escaneados exigem OCR **prévio**: esta versão não instala nem executa OCR automaticamente.
- A porcentagem calculada representa **a proporção de itens reconhecidos**, não necessariamente o peso na nota (especialmente quando há valores distintos de pontuação).
- Quando há múltiplos cargos, as linhas da tabela de provas **não são vinculadas automaticamente** ao cargo: confira-as na origem.
- A página de origem é uma estimativa obtida pela posição no texto extraído; valide nos documentos complexos.
- A auditoria descreve a extração original. Após edição manual, confira os avisos novamente.
- A edição do plano fica na sessão do navegador e no Excel exportado, **não** em um banco de dados externo. O progresso não é persistido entre novas sessões.
- A IA opcional só recebe um trecho parcial com consentimento e sua própria chave de API. Ela não modifica automaticamente conteúdo ou pontuação.

## Executar testes

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests/
```

Os testes usam um edital **sintético** gerado durante a execução; não substituem testes com editais reais de diferentes bancas.
