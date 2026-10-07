# Status da Fase 2: matriz módulo x estado x pendência

Mantida pelo WS-13. Última atualização: **07/10/2026**, sobre o commit de integração `2a97514` (M1 fechado), com os
testes transversais do WS-13 já no repositório e **nenhum módulo da Onda 1 integrado ainda**.

**Como atualizar a cada merge.** Rode `python3 tests/test_contratos.py --matriz`: ele imprime a coluna "Estado no
repositório" (ausente / só a base da Etapa 0 / presente, no contrato / presente, DIVERGE) de cada módulo. Os testes
transversais **se reativam sozinhos** quando o módulo passa a existir (nada a editar neles); o que mudar de estado nesta
página é só a tabela da seção 1 e a seção 3.

**Situação dos testes em 07/10/2026** (Python 3.13, Linux): base da Fase 1 e do M1 (`test_pipeline`, `test_painel`,
`test_ficha`, `test_ficticio`, `test_simulado`): 76 de 76 passam. Testes transversais do WS-13 (`test_confidencialidade`,
`test_desempenho`, `test_contratos`, `test_empacotamento`): 86 execuções, 25 passam e 61 são **puladas** com mensagem
(módulos da Onda 1 ainda ausentes), nenhuma falha. `tests/test_autos.py` continua falhando por falta de Playwright
(conhecido, anterior a este trabalho).

## 1. Matriz por módulo

Legenda do estado: **integrado** = no branch de integração e testado; **em construção** = workstream da Onda 1 ainda
não integrado (não há o arquivo no repositório); **pronto para conferência** = só falta o roteiro humano.

| WS | Módulo / arquivos | Estado em 07/10/2026 | Teste transversal que o cobre (hoje) | Pendência / depende de teste real |
| --- | --- | --- | --- | --- |
| Etapa 0 | `src/ficha.py`, `src/taxonomia.py` (base), `src/simulado.py`, `tests/ficticio.py`, painel fatiado em `src/painel/` | **integrado** (M1) | `test_contratos` (base da Etapa 0), `test_desempenho` etapa `carteira_e_ficha`, `test_confidencialidade` (painel) | Spikes S3 (cobertura real e DataJud), S4 (tempo real de coleta) e S5 (modelo local) dependem do computador do usuário |
| WS-1 | `src/taxonomia.py` (extensões), `src/consolidar.py` | em construção | `test_contratos` (pula: só a base da Etapa 0 / ausente), `test_desempenho` etapa `consolidacao` (pula) | Vocabulário e sinônimos a calibrar com relatórios reais no piloto (M5) |
| WS-2 | `src/leitores/__init__.py` (+ `detectar`, `docx_a`, `xlsx_b`, `lista`, `tabela_livre`) | em construção | `test_contratos`, `test_desempenho` etapas `leitura_docx_a`, `leitura_xlsx_b`, `leitura_lista` (pulam) | `.docx` **exportado de um Google Doc real** e planilhas reais do escritório: só fixtures sintéticas aqui (M5) |
| WS-3 | `src/fila.py` (+ `ColetorReal` em `coletor.py`/`trt.py`/`rodar.py`) | em construção | `test_contratos`, `test_desempenho` etapa `fila` (pula) | `ColetorReal` **não é testável aqui** (certificado, jus.br, captcha do TRT): validar no piloto (M5/M6); tempos e cobertura reais a medir |
| WS-4 | `src/capa.py` (+ `djen.py`) | em construção | `test_contratos` (pula) | Telas reais do jus.br e do TRT; campos reais do DataJud (spike S3: nota em `docs/fase2/spikes/S3-datajud.md` a conferir) |
| WS-5 | `src/sintese.py` (+ `resumir.py`) | em construção | `test_contratos` (pula) | Qualidade do **modelo de IA real** em "momento atual" e narrativa (S5): só provedor falso aqui |
| WS-6 | `src/escritores/docx_a.py`, `src/modelos/docx_a/`, `docs/fase2/conferencia-docx.md` | em construção | `test_contratos`, `test_desempenho` etapa `escritor_docx_a` (pula), `test_confidencialidade` modelos e saída (pulam) | Abrir no **Word e no Google Docs**: roteiro `conferencia-docx.md`; só LibreOffice aqui |
| WS-7 | `src/escritores/xlsx_b.py`, `src/planilha.py`, `src/modelos/xlsx_b/`, `docs/fase2/conferencia-xlsx.md` | em construção | `test_contratos`, `test_desempenho` etapas `escritor_xlsx_b` e `fase1_planilha_e_relatorio` (esta já roda e vigia a regressão da Fase 1) | Fica **pronto para conferência**, não "pronto", até o usuário abrir no **Excel (Windows e Mac) e no Google Sheets** (M5); cache de fórmulas |
| WS-8 | `src/escritores/dashboard.py`, `src/modelos/dashboard/` | em construção | `test_contratos`, `test_desempenho` etapa `dashboard` (pula), `test_confidencialidade` (templates e saídas; pula) | Navegadores reais do cliente; Playwright/Chromium só no ambiente de desenvolvimento |
| WS-9 | `src/painel/assistente.py`, `src/painel/migracao.py`, `src/painel/entregas.py`, `src/painel/perfil.py` | em construção | `test_contratos` (inclui "registrada em `revisao.py`"), `test_confidencialidade` (rotas `/fluxo`, `/migracao`, `/entregas`, `/perfil`; pulam) | Usabilidade com quem nunca usou o painel; `docs/guia-fase2.md` descreve o **desenho aprovado**, a revisar contra as telas reais |
| WS-10 | `src/triagem.py`, `src/painel/revisao_lote.py`, `src/painel/processo.py` | em construção | `test_contratos` (pula) | Revisão de 600 eventos com pessoas reais; percentual de amostragem a calibrar |
| WS-11 | `src/qualidade.py`, `src/historico.py`, `src/quadros.py` | em construção | `test_contratos`, `test_desempenho` etapa `qualidade` (pula) | Falsos positivos a medir em carteira real |
| WS-16 | `src/pedidos.py`, `src/painel/pedidos.py`, `docs/pedidos-iniciais.md` | em construção | `test_contratos`, `test_confidencialidade` (rota `/pedidos`; pula) | **Prompt não validado com petições reais** (validar no piloto, com a IA que o usuário escolher) |
| WS-17 | `src/julgamento.py` | em construção | `test_contratos` (pula) | Teste retroativo (`concordancia`) contra relatórios migrados reais para decidir quando sugerir sem ressalva |
| WS-18 | `src/ia.py`, `src/painel/ia.py`, `docs/confidencialidade-ia.md` | em construção | `test_contratos`, `test_confidencialidade` (rota `/ia`; pula) | **Chamadas reais** ao provedor externo e ao Ollama: só transporte falso aqui; revisar o texto de confidencialidade com o usuário |
| WS-13 | `tests/test_confidencialidade.py`, `tests/test_desempenho.py`, `tests/test_contratos.py`, `tests/test_empacotamento.py`, `tests/transversal.py`, `tests/confidencialidade_regras.py`, `README.md`, `docs/guia-fase2.md`, `empacotar.sh`, `requirements.txt`, este arquivo | **integrado neste commit** | os próprios | Reler o README e o guia a cada merge (seção 4); guia lido por quem não conhece o projeto (M5) |
| WS-14/15 | `src/fluxos.py` e teste de carga/regressão (Onda 2) | não iniciado | `test_desempenho` já prova 200 processos por etapa; WS-15 acrescenta 3 ciclos e 5 clientes | Orquestração e interrupção/retomada de ponta a ponta |

## 2. O que cada teste transversal faz (e o que pula hoje)

| Arquivo | O que confere | Pulado hoje porque |
| --- | --- | --- |
| `tests/test_confidencialidade.py` | O detector detecta (casos plantados em tempo de execução); nenhum número de processo fora de `0000000`/`9999999`/`1234567-1234570`, nenhum nome de empresa que pareça real (heurística), nenhum CPF/CNPJ/e-mail/telefone real, nenhum segredo, nenhum arquivo proibido (certificado, `config.json`, `projetos/`); `config.exemplo.json` sem quem assina; HTML das telas do painel e do relatório da Fase 1 sem domínio externo; (quando existirem) modelos `.docx`/`.xlsx` lidos por dentro, templates e saídas do dashboard, saída dos escritores só com os números das fichas | Rotas `/fluxo` `/migracao` `/entregas` `/perfil` `/pedidos` `/ia`, `src/modelos/`, `escritores.*` ainda não existem; nomes cadastrados só valem no computador do escritório (sem `projetos/` aqui) |
| `tests/test_desempenho.py` | 200 processos (ajustável): ficha e carteira, **planilha e relatório da Fase 1 (roda hoje)**, lista bruta, leitura de `.docx`/`.xlsx`/lista, consolidação, qualidade, escritores em 2 ciclos, dashboard nos dois modos, fila com coletor simulado e 10% de falha; limites generosos por etapa e no total; tabela de tempos no stderr | Etapas dos módulos ausentes (10 de 12 hoje); o teste `test_99_pipeline_completo` termina "pulado" listando o que falta |
| `tests/test_contratos.py` | Cada módulo da tabela existe, tem as funções do `CONTRATOS.md` com a assinatura combinada e, se for tela do painel, está registrada em `revisao.app`; `--matriz` imprime o estado | Módulos ausentes |
| `tests/test_empacotamento.py` | `empacotar.sh` numa **cópia**: o que entra e o que fica fora, recusa por número de processo (também dentro de `.docx`/`.xlsx`), nome cadastrado, segredo, certificado, HTML externo e erro de sintaxe; todo import de terceiros está em `requirements.txt` com versão mínima; README e guia citam os quatro fluxos e o Windows "não testado"; links relativos e a árvore de arquivos do README existem; este arquivo cita todos os módulos | Links do guia/README e entradas da árvore do README que apontam para arquivos dos outros workstreams (`pedidos-iniciais.md`, `confidencialidade-ia.md`, `conferencia-*.md`, módulos de `src/`) até eles entregarem |

## 3. O que só foi validado com dado fictício e o que depende de ferramenta real

- **Só dado fictício e coletor simulado (todo o código da Onda 1):** nenhum teste usa rede, certificado, jus.br,
  TRT, provedor de IA ou dado de cliente.
- **Depende do computador do usuário (Mac):** login real (certificado A1, PJe Office, autenticador, captcha), tempo real de
  coleta por processo, cobertura real por tribunal, qualidade do modelo local de IA, medição real do `ColetorReal`.
- **Depende dos programas do cliente:** Word, Google Docs, Excel (Windows e Mac), Google Sheets, navegadores. Aqui só
  python-docx, openpyxl, lxml e LibreOffice. Roteiros: `conferencia-docx.md` e `conferencia-xlsx.md` (WS-6 e WS-7).
- **Depende de IA real:** prompt dos pedidos das iniciais, narrativa e "momento atual" com modelo real, provedores
  externos.
- **Windows:** nada testado (instalador, atalhos, a Fase 2 inteira). Item do marco M7.
- **`empacotar.sh`:** testado em Linux (Python 3.13, GNU). No macOS depende só de `bash` e `python3`: a cópia e o `.zip`
  passaram a ser feitos pelo Python (antes dependiam de `rsync` e `zip`; o ambiente de desenvolvimento não tem `rsync`).

## 4. Checklist de integração para o coordenador

1. Após cada merge: `python3 tests/test_contratos.py --matriz` e atualize a seção 1.
2. Registre cada tela nova na tupla de `src/revisao.py` (o teste `test_contrato_painel_*` falha se o módulo existir e
   a rota não): `painel.assistente`, `migracao`, `entregas`, `perfil`, `revisao_lote`, `processo`, `pedidos`, `ia`.
3. Rode o conjunto: `python3 -m unittest discover -s tests` (com `RELATORIO_DESEMPENHO_FATOR=3` em máquina lenta).
   `tests/test_autos.py` falha sem Playwright (conhecido). O instantâneo de `tests/test_painel.py` pode mudar quando
   o WS-9 acrescentar subabas: conferir o diff e regravar só o necessário.
4. Se `test_confidencialidade` barrar um nome fictício novo como "empresa suspeita", acrescente a palavra a `GENERICAS`
   em `tests/confidencialidade_regras.py` (ou troque o nome); se barrar número, troque por `numero_ficticio`.
5. Conferir README e guia contra o que foi integrado: a árvore de arquivos do README, os nomes de botões do guia, os
   links para `pedidos-iniciais.md` e `confidencialidade-ia.md` (WS-16 e WS-18) e `conferencia-*.md` (WS-6 e WS-7).
6. Antes de publicar: `./empacotar.sh` (recusa se achar algo) e abrir o `.zip` em outra pasta.
7. `requirements.txt`: se um workstream acrescentar dependência, `test_empacotamento` aponta; ao integrar WS-8
   (Playwright já consta) e WS-18 (cliente HTTP) confira se algo novo entrou.

## 5. Achados do WS-13 (para o coordenador decidir)

- `tests/test_pipeline.py` (linha do teste de `nome_bate`) usa um nome de empresa que **parece real** (a heurística
  de confidencialidade o aponta). Está numa lista de legado em `confidencialidade_regras.py` (por impressão digital,
  para não repetir o nome) só para o teste não falhar. Recomenda-se trocar por um nome fictício e apagar a linha de
  `LEGADO`.
- `empacotar.sh`: as pastas de dados (`data`, `projetos` etc.) agora são excluídas **só na raiz**; antes `--exclude data`
  tiraria qualquer pasta `data` de dentro de `src/` (por exemplo de um template). Também ficam de fora `spikes/`,
  `.claude/`, `.git/`, `docs/fase2/BRIEFING-AGENTES.md` e `WORKSTREAMS.md` e arquivos de `tests/fixtures` acima de 1 MB.
- O pacote agora **compila todos os `.py`** antes de gerar o `.zip` (erro de sintaxe barra o pacote) e confere o texto
  dentro de `.docx`/`.xlsx` (o `grep -I` antigo ignorava binários, então os modelos sanitizados não eram conferidos).

## 6. Revisão crítica do guia (`docs/guia-fase2.md`)

A segunda leitura (como alguém que nunca usou a ferramenta, e contra `PLANO.md`, `WORKSTREAMS.md` e `CONTRATOS.md`)
corrigiu:

1. A "primeira aba Revisar" não existe: a ordem das abas é Atualizar, Revisar... Agora diz só "aba Revisar".
2. A afirmação de que **Entregas** e **Perfil** "aparecem na barra de abas" não estava na especificação (o WS-9 só pode
   acrescentar subabas); virou "há ainda as telas Entregas e Perfil" e foi dado o endereço `/fluxo` da tela inicial.
3. Nomes de botões inventados ("Confirmar importação", "Começar", "Começar coleta", "Converter") foram trocados por
   descrições ("confirme a importação", "inicie a coleta"); só ficaram em negrito os nomes que a especificação traz
   (os quatro botões do fluxo, Pausar, Retomar, Parar com segurança).
4. "Área pontilhada" era detalhe visual inventado; virou "área de soltar".
5. Os "campos sem destino" da **importação** iam, no rascunho, para a aba "Campos não migrados": isso só é prometido na
   **migração de modelo** (e no modelo `.xlsx`). Na importação eles ficam listados na tela de conferência.
6. Tirados "tempo decorrido e estimativa do que falta" e "quantos têm coleta pendente" (não especificados).
7. "Uma carteira grande leva horas ou dias" virou o que o plano diz: horas, e a carga completa possivelmente mais de um dia,
   com tempos reais a medir no piloto.
8. A cobertura por tribunal deixou de ser "mostrada na tela de progresso": é um relatório.
9. Na tela de Perfil saíram "as opções de IA" (ponto de extensão do WS-18, que tem tela própria).
10. A promessa de "marcar como vinculado" à mão foi trocada pelo que a ferramenta faz (agrupa principal, agravo, apenso e
    "mesma ação") e pede conferência; "escolha o momento na lista" ganhou o caminho real (revisão dos campos do processo).
11. Mensagens de aviso entre aspas (que a especificação não fixa) viraram "aviso de ..." com o **código estável**
    (`formato_nao_reconhecido`, `edicao_manual_sobrescrita`, `andamento_ja_presente`).
12. Dito explicitamente: fecho "Em DD/MM/AAAA, sem atualizações." no texto e "Até DD/MM/AAAA sem atualizações." na planilha.
13. Acrescentados, para quem nunca usou: glossário (relatório, ficha, data-base, histórico, momento atual, profundidade,
    modos, captcha, selo), a diferença entre Importar e Migrar de modelo, e o aviso de que o guia descreve o desenho
    aprovado e que vale a tela real.

14. No README, a frase "Nada roda sozinho" contradizia o modo contínuo (a coleta segue sozinha na janela de horário
    depois que o usuário inicia); virou "Nada começa sozinho", com a explicação do modo contínuo e a condição de o
    computador e o painel estarem ligados. A promessa de confidencialidade ganhou a ressalva da IA externa, e as
    tabelas de situação por plataforma foram separadas (Mac Fase 1 testado; Mac Fase 2 só fictício; Windows não
    testado; programas do cliente não testados).

Ainda **não** feita: leitura por alguém que não conhece o projeto (critério do plano, marco M5).
