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

## Atualização v3 — Editais com conteúdo em anexos (exemplo: CNU 2)

**Problema corrigido:** alguns editais principais não apresentam a seção de conteúdo
programático. Eles remetem a anexos em documentos separados. Nesses casos, a
versão anterior interrompia a análise com um erro. Agora o aplicativo:

1. Aceita **vários PDFs ao mesmo tempo** na barra lateral. Envie o edital principal
   e os anexos de seu bloco/cargo em uma única seleção (ou adicione mais PDFs
   pelo mesmo campo do Streamlit).
2. Processa parcialmente o **edital principal**, mesmo sem conteúdo programático.
3. Mostra alertas de **dependências documentais**, sem inventar matérias/tópicos.
4. Preserva a origem dos resultados por arquivo e número de página.
5. Reconhece, no texto corrido do exemplo CNU 2 retificado em 21/11/2025:
   - nível superior: 90 questões (30 de Conhecimentos Gerais e 60 de Conhecimentos Específicos);
   - nível intermediário: 68 questões (sem detalhamento de matérias no arquivo principal);
   - alerta para o fato de que os cinco eixos do nível superior têm 12 questões cada,
     enquanto **pesos de pontuação dependem do cargo e estão nos anexos**.
6. Calcula **participação no número de itens** (33,3% e 66,7% no nível superior),
   mas não confunde esse percentual com o peso na nota final. O total agregado de
   68 questões do nível intermediário **não recebe 100% como se fosse uma matéria**.
7. Exporta o resultado parcial em Word, Excel ou PDF, com avisos de conteúdo ausente.

### Exemplo de uso para o CNU 2

O PDF `edital_concurso-publico-nacional-unificado-2_8aret_21.11.25.pdf`
(56 páginas) **não contém o conteúdo programático dos Blocos 1 a 9**. A
referência aos anexos está no item 8.7, página 28; o quantitativo de questões,
no item 8.9 e 8.10, página 29. Envie também o PDF do(s) anexo(s) do bloco
temático escolhido. Para obter todas as matérias, é necessário dispor dos
anexos correspondentes; não existe extração confiável de conteúdo ausente.

### Notas de confiabilidade

- O reconhecimento narrativo de quantitativos é intencionalmente conservador.
  Não promete funcionar em todo edital sem tabela; pode demandar revisão manual.
- A função `parser.build_reports([(nome_arquivo, caminho), ...])` une diversos PDFs.
  A função histórica `parser.build_report(caminho)` continua funcionando.
- Os testes de integração incluem caso sintético com edital principal + anexo;
  o PDF do CNU 2 foi testado localmente para confirmar o diagnóstico e a
  extração parcial de 30/60/68.
- Se o conteúdo dos anexos estiver em formato pouco padronizado, a ferramenta
  pode retornar trechos não classificados. Confirme a integridade do resultado.
