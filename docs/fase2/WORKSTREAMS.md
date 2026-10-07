# Workstreams da Onda 1 — especificação por agente

Leia primeiro `PLANO.md` (seções 2 a 8), `CONTRATOS.md` (inteiro) e `BRIEFING-AGENTES.md` (regras de trabalho e relatório final). Cada agente executa **uma** seção abaixo e só mexe nos arquivos que ela lista.

Referências de apoio já no repositório: `docs/fase2/fixtures.md` (geradores e coletor simulado), `docs/fase2/painel-modulos.md` (como criar tela), `docs/fase2/spikes/S1-xlsx.md` e `S2-docx.md` (spikes aprovados "com ressalvas"; código em `spikes/s1_xlsx/` e `spikes/s2_docx/`), `src/ficha.py`, `src/taxonomia.py`, `src/simulado.py`, `tests/ficticio.py`.

## Fatos estruturais dos modelos de referência (sem dado de cliente)

**Modelo A (`.docx`)**: título (cliente); "Data-Base: DD/MM/AAAA"; quadro-resumo de 4 colunas (Nº DO PROCESSO | ASSUNTO | MOMENTO ATUAL DO PROCESSO | ÚLTIMO ANDAMENTO); depois uma tabela por processo: título mesclado "PROCESSO Nº ... [ MOMENTO ATUAL ]", Assunto, Autor(es), Réu(s), Ajuizamento + Valor da Causa, Data de citação + Juízo, Área do Direito + Matéria Principal, "Andamentos:" (texto corrido com datas em negrito). Várias linhas têm mais de um número (principal; agravo; apenso). Momento atual vem de vocabulário controlado, às vezes com qualificador entre parênteses (ex.: "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)", "PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)"). Fecho do texto quando não houve novidade: "Em DD/MM/AAAA, sem atualizações."

**Modelo B (`.xlsx`)**: abas de processos (uma ou mais; ex.: ativos e arquivados, trabalhistas e cíveis) com cabeçalho de 29 colunas: Número do Processo, Autor(es), Réu(s), Vara, Município, Tribunal, Data do Ajuizamento, Área do Direito, Matéria Principal, Objeto, Valor da Causa, Andamentos, Situação, Ativo, Valor Arbitrado em Juízo, Probabilidade, Valor Estimado, Valor da Execução, Custas Processuais, Depósitos Recursais, Garantias Processuais, Resultado, Valor Economizado, Data do trânsito em julgado, Taxa de resolução (em dias), Houve recurso da empresa?, Percentual de êxito, Reclamante terceirizado?, Outra(s) Parte(s). Aba de parâmetros (nº de funcionários, data de referência, fator de correção, empresas do grupo). Aba de indicadores (fórmulas): acervo (total, ativos, encerrados, litígios por 100 funcionários, novos ajuizamentos em 12 meses), tempo e recursos (tempo médio e mediana de resolução, recursos da empresa, decididos, taxa de recurso), resultados (improcedentes, arquivadas/desistência, acordos, parcialmente procedentes, procedentes, taxa de êxito = (improcedentes + arquivadas) ÷ decididos, % por acordo), financeiro (valor da causa total e de encerrados, valor realizado de encerrados = arbitrado, ou execução se vazio, economia efetiva = causa − realizado). Aba de dashboard/esboço com gráficos. Abas de quadros analíticos: acordos (com ressalvas por caso), maiores exposições (maior valor entre estimado, arbitrado, execução e causa), condenação × valor da causa, composição e desfecho por tese.

**Modelo C (dashboards HTML)**: dois painéis autônomos que leem o `.xlsx` arrastado para a página (SheetJS + Chart.js via CDN), com mapeamento tolerante de cabeçalhos e de formatos de valor/data, filtros, KPIs, gráficos de rosca e barras, tabela, aba de "qualidade dos dados". Código de referência **com nomes de cliente embutidos em expressões regulares** (a generalizar), fora do repositório: `/tmp/claude-0/-home-user-relatorio-andamentos/8659b6b3-04d4-50b4-97c2-821543565e30/scratchpad/ref/painel-contencioso.html` e `painel-pedidos.html` (somente leitura; **não copie nome de cliente nem número de processo para o repositório**).

---

## WS-1 — Normalização, consolidação e momento atual por regra

**Dono de**: `src/taxonomia.py` (extensões), `src/consolidar.py`, `tests/test_taxonomia.py`, `tests/test_consolidar.py`.

**Entregas**
1. Ampliar vocabulários e sinônimos **sem remover valor canônico existente**: matérias (use a lista inicial e amplie com matérias trabalhistas e cíveis comuns), momentos atuais (inclua o qualificador entre parênteses como parte opcional: `normalizar_momento("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)") -> ("CUMPRIMENTO DE SENTENÇA", "HONORÁRIOS SUSPENSOS")`), resultados, áreas.
2. **Sinônimos editáveis por projeto**: `taxonomia.carregar(projeto)` lê `projetos/<slug>/taxonomia.json` (sobreposição) e `taxonomia.adicionar_sinonimo(vocab, canonico, sinonimo)` grava; `normalizar` passa a respeitar a sobreposição; formato documentado no cabeçalho do módulo.
3. `taxonomia.momento_por_regras(movimentos) -> (momento | None, evidencia)`: tabela de regras sobre o texto dos movimentos mais recentes (use os termos de `movimentos.json`) que escolhe o **momento atual** do vocabulário (ex.: último movimento relevante "conclusos para sentença" → AGUARDANDO SENTENÇA; "distribuído recurso" → recurso; "certidão de trânsito" → TRÂNSITO EM JULGADO; "arquivado" → PROCESSO ARQUIVADO). Sem regra: `None` (a IA fica com o WS-5).
4. `consolidar.consolidar(fichas) -> (fichas, avisos)`: agrupa **vinculados** (mesmo número em dois lugares; "mesma ação" por incompetência/reajuizamento; agravo e apenso viram vínculos do principal), detecta **duplicatas** exatas e prováveis (mesmo número com formatação diferente, mesmo cliente/partes/data), unifica **grafias do mesmo nome** (Chacara/Chácara, com e sem Ltda, caixa) com lista de sugestões para confirmação (nunca funde nomes sem confirmação, só sugere), e nunca perde campo `humano`.
5. Migração de itens da Fase 1 → v2 em lote (`consolidar.migrar_projeto(slug)`), idempotente.

**Aceite**: normaliza os rótulos soltos conhecidos (use `tests/ficticio.gerar_carteira(com_defeitos=True)` como gabarito dos defeitos de matéria e grafia); `consolidar` encontra os defeitos `numero_duplicado`, `materia_dois_rotulos` e `grafias_cliente` das fixtures; idempotência; nenhum campo `humano` perdido; testes antigos intactos.

---

## WS-2 — Leitores (migração de relatórios existentes)

**Dono de**: `src/leitores/` (`__init__.py`, `detectar.py`, `docx_a.py`, `xlsx_b.py`, `lista.py`, `tabela_livre.py`), `tests/test_leitores.py`. Pode **reaproveitar** funções de `carteira.py` sem alterar assinaturas.

**Entregas**: `leitores.detectar` e `leitores.ler` conforme CONTRATOS §4.
- `docx_a`: lê o modelo A (data-base, cliente, quadro-resumo, blocos por processo, números múltiplos, momento atual com qualificador, textos de andamentos, data do último andamento = maior data `DD/MM/AAAA` do texto, datas em negrito). Tolerante a exportação do Google Docs (runs fragmentados, parágrafos vazios, tabelas aninhadas ou mescladas). Reaproveite as ideias de `spikes/s2_docx/docx_atualizador.py::ler_estrutura`.
- `xlsx_b`: lê **todas** as abas de processos (detecte pelo cabeçalho, não pelo nome), mapeia colunas por similaridade de cabeçalho (acento, caixa, pontuação, sinônimos) para campos da ficha; colunas de julgamento entram com origem `humano`, as demais `migrado`; lê parâmetros (headcount, data de referência, empresas do grupo); valores monetários e datas em vários formatos (texto BR, número, data do Excel); células de fórmula: usa o valor em cache quando existir e avisa quando não; ignora linhas-marcador e totais.
- `lista`: texto/e-mail, `.csv` (`,`/`;`/tab), `.xlsx` simples e bagunçado (cabeçalho fora da primeira linha, linhas vazias), como em `carteira.ler_lista`, mas devolvendo `RelatorioLido`.
- `tabela_livre`: planilha/tabela com colunas fora do padrão: devolve o **mapeamento proposto** (coluna → campo, com confiança) em `RelatorioLido["mapeamento"]` e lista `colunas_sem_destino`; base da tela "Migrar de modelo". `ler(caminho, mapeamento=...)` aceita mapeamento corrigido pelo usuário.
- Todos: ambiguidade vira `Aviso` (com `codigo` estável), nunca dado silencioso; DV errado é recusado e listado; duplicado é avisado.

**Aceite**: gere fixtures com `tests/ficticio` + os geradores dos spikes (`spikes/s2_docx/gerar_modelo.py`, `spikes/s1_xlsx/gerar_modelo.py`) e prove: 200 processos lidos nos dois formatos sem erro; **ida e volta** (ler → regravar com o protótipo de escritor do spike → ler) preserva os campos; planilha com cabeçalhos trocados e colunas extras mapeia e lista o que não tem destino; arquivo corrompido/ilegível devolve aviso `erro`, não exceção.

---

## WS-3 — Fila de coleta em massa

**Dono de**: `src/fila.py`, `tests/test_fila.py`; ajustes mínimos em `src/coletor.py`, `src/trt.py`, `src/rodar.py` (sem quebrar o uso atual; o painel atual continua funcionando e `tests/test_painel.py` continua verde).

**Entregas**: API de CONTRATOS §6 e:
- Estado persistido em `data/fila.json` (gravação atômica via `comum.save_json`), retomável após queda em qualquer ponto, nunca repete `coletado`.
- Estados `pendente → coletando → coletado | erro | manual`; `erro` com contagem e código; política de tentativa por código (`timeout`/`sessao_expirada`/`outro`: até N tentativas com espera crescente; `captcha`/`segredo`/`nao_encontrado`: `manual` sem repetir; `captcha` de TRT: agrupar processos do mesmo TRT e pedir uma vez por rodada).
- **Modos** `continuo` (janelas de horário configuráveis, ex. 20h–6h; retoma no dia seguinte) e `imediato` (roda já; `estimativa()` devolve segundos previstos a partir da **média móvel medida** do tempo por processo, com valor padrão conservador na primeira vez; a confirmação ao usuário é feita pelo WS-9, a fila só informa).
- **Sequencial**: um processo por vez; pausa configurável entre processos (reaproveitar `config()["coleta"]`); `parar_com_seguranca()` termina o processo corrente e grava.
- Prioridade (maior primeiro; desempate por ordem de entrada) e filtro por cliente/lista.
- `cobertura()`: por tribunal, quantos `coletado`, `so_djen` (coleta indisponível, só publicações) e `manual`.
- Adaptador `ColetorReal` que implementa o protocolo `Coletor` sobre o código existente (`coletor.py`/`trt.py`) com o mínimo de mudança; **não é testável aqui** (sem certificado/rede): cubra com testes que usam apenas o `ColetorSimulado` (`src/simulado.py`) e deixe o adaptador real fino, com checagem de importação e documentado como "validar no piloto".
- `rodar_fila(fila, coletor, ao_progresso=None)` que consome a fila e chama `ao_progresso(resumo)` a cada transição (o painel usa).

**Aceite** (todos com `ColetorSimulado`): 200 processos com falhas aleatórias terminam; interrupção simulada em 5 pontos diferentes e retomada não repete processo `coletado` (confira `coletor.chamadas_por_numero`); captcha/segredo não travam o resto; modo contínuo respeita a janela (relógio injetável nos testes); estimativa converge com a média medida; `cobertura` correta.

---

## WS-4 — Capa e metadados do processo

**Dono de**: `src/capa.py`, `src/djen.py` (extensões aditivas), `tests/test_capa.py`.

**Entregas**: `capa.extrair(fonte, dados) -> {campo: {"valor", "confianca", "evidencia"}}` com fontes plugáveis:
1. **Autos do jus.br** (HTML/JSON já usado pelo coletor; veja `tests/fixtures/autos_pdpj.html` e `coletor.py`): vara/juízo, município, UF, data de ajuizamento (distribuição), data de citação (quando houver movimento de citação), classe, assunto, partes (autores/réus), valor da causa.
2. **Consulta do TRT** (estrutura que `trt.py` já lê): idem, no que a tela oferecer.
3. **DJEN** (`djen.py`): partes e polos; **só** `autores`/`reus`/`parte_contraria` quando o cliente é identificável.
4. **DataJud (API pública do CNJ)**, atrás de uma flag `fontes_externas.datajud`: **primeiro verifique na documentação pública** (WebSearch/WebFetch, se disponíveis) quais campos a API devolve de fato (classe, assuntos, órgão julgador, data de ajuizamento, movimentos; confirme se há valor da causa) e registre o resultado em `docs/fase2/spikes/S3-datajud.md` com a data da consulta e o que ficou **não verificado**. Implemente o cliente com tolerância e teste com resposta gravada à mão no formato documentado (marque a fixture como "formato conforme documentação, não capturado"). Se a documentação não estiver acessível, entregue só o esqueleto e a nota.
- Regras: campo ausente fica **vazio** (nunca inventado); `polo_cliente` e `parte_contraria` não vêm de tribunal (CONTRATOS §6); cada campo traz origem `coletado` e evidência; valores monetários e datas normalizados por `ficha.parse_*`.
- `capa.aplicar(ficha, capa)` grava na ficha via `ficha.definir(..., "coletado")` (respeitando prioridade) e devolve o que mudou.

**Aceite**: fixtures de tela dos dois portais (derive de `autos_pdpj.html` e crie uma de TRT **fictícia** no formato que `trt.py` consome) produzem os campos esperados; lacunas ficam vazias; nenhuma chamada de rede nos testes.

---

## WS-5 — Síntese: momento atual, último andamento e narrativa

**Dono de**: `src/sintese.py`, extensões em `src/resumir.py` (aditivas; o fluxo atual de resumo continua funcionando), `tests/test_sintese.py`.

**Entregas**
- `sintese.momento_atual(ficha, eventos, movimentos, provedor) -> {"momento", "qualificador", "evidencia", "origem"}`: 1º `taxonomia.momento_por_regras` (WS-1; se ainda não existir quando você começar, use uma função local provisória com a mesma assinatura e deixe um `TODO(WS-1)` e uma nota no relatório); 2º, sem regra, o **provedor de IA** com **vocabulário fechado** (esquema JSON com `enum` dos momentos) e exigência de trecho de origem; sem evidência: `None` + alerta. Nunca devolve valor fora do vocabulário.
- `sintese.ultimo_andamento(eventos, movimentos) -> data ISO` (maior data entre movimentos e documentos, ignorando os de rotina quando houver outro relevante, regra configurável).
- `sintese.narrativa_inicial(ficha, eventos, profundidade, provedor) -> texto` no estilo dos relatórios (reuse `relatorio.linha`/`planilha.frase_planilha`): camadas **capa → movimentos → documentos-chave**; frases só a partir de eventos com origem; cronológica; datas `DD/MM/AAAA`; voz do escritório quando a assinatura for do escritório (reuse `traduzir.autoria`).
- `sintese.narrativa_incremental(ficha, eventos_novos) -> texto` que **só acrescenta** depois do último texto gravado, sem repetir o que consta em `linha_de_base` ou `ultimo_texto_gravado` (use data + núcleo do texto).
- O provedor de IA é recebido como **objeto** com a interface de CONTRATOS §8 (`gerar(sistema, usuario, *, esquema, cliente)`); nos testes use um **provedor falso** determinístico; `ia.py` real é do WS-18 (não dependa dele). Grave em cada evento `motor` e `profundidade`.
- Níveis `rapido|padrao|completo` definem o que entra na narrativa.

**Aceite**: estilo igual ao dos modelos; nenhuma frase sem evidência; nunca reescreve o histórico migrado; momento sempre dentro do vocabulário; resultados determinísticos com o provedor falso; testes de `resumir`/pipeline antigos intactos.

---

## WS-6 — Escritor `.docx` (modelo A)

**Dono de**: `src/escritores/__init__.py` (você cria o pacote; WS-7 e WS-8 só adicionam módulos), `src/escritores/docx_a.py`, `src/modelos/docx_a/` (modelo sanitizado), `tests/test_docx_a.py`.

**Entregas**: transforme o protótipo `spikes/s2_docx/docx_atualizador.py` em módulo de produção, conforme CONTRATOS §5 (`gravar(molde, estado, destino, **opcoes) -> Resultado`), resolvendo as ressalvas de `docs/fase2/spikes/S2-docx.md`:
- **Atualizar** arquivo do cliente (momento atual, último andamento, andamentos acrescentados com datas em negrito, fecho **só quando não houve novidade** — padrão `fecho_apos_novidade=False`, Data-Base, processo novo clonado de bloco-modelo e linha do resumo) e **gerar do zero** a partir de um modelo `.docx` **sanitizado** (crie por script, sem nomes/números/valores reais; dois estilos: A e "compacto").
- Exceções mecânicas nomeadas ao "só acrescenta" (CONTRATOS §5), aviso `edicao_manual_sobrescrita`; `Resultado` com `ignorados`, `textos_gravados` e `avisos` com `codigo`.
- Detecção de duplicata mais robusta: além de "Em DD/MM/AAAA", reconheça "No dia DD/MM/AAAA", "Em DD/MM" e datas por extenso; mantenha a heurística documentada e com limiares configuráveis.
- Processos com **vários números** e qualificadores no momento atual ("(HONORÁRIOS SUSPENSOS)").
- Idempotência, original nunca sobrescrito, fidelidade do pacote (partes não editadas idênticas), recarrega em python-docx, abre no LibreOffice (conversão para PDF).
- `docs/fase2/conferencia-docx.md`: lista curta, em português simples, do que o usuário deve conferir à mão com uma exportação real do Google Docs (Word/Docs não são testáveis aqui).

**Aceite**: toda a suíte do spike migrada para `tests/test_docx_a.py` e ampliada (200 processos, vários ciclos seguidos sem duplicar, edição manual preservada, processo novo, vários números); zero número real; o protótipo em `spikes/` permanece intacto.

---

## WS-7 — Escritor `.xlsx` (modelo B)

**Dono de**: `src/escritores/xlsx_b.py`, `src/planilha.py` (refatorado **mantendo** `planilha.gerar(...)` e o uso atual do painel; `tests/test_painel.py` e `tests/test_pipeline.py` continuam verdes), `src/modelos/xlsx_b/` (modelo padrão sanitizado, gerado por script), `tests/test_xlsx_b.py`.

**Entregas**: transforme o protótipo `spikes/s1_xlsx/xlsx_cirurgico.py` em módulo de produção, conforme CONTRATOS §5, resolvendo as ressalvas de `docs/fase2/spikes/S1-xlsx.md`:
- Atualização do arquivo do cliente: coluna "Andamentos" (comportamento da Fase 1 preservado: fecho `Até DD/MM/AAAA sem atualizações.` só sem novidade), demais colunas **objetivas** (situação, ativo, momento/fase, último andamento, datas, valores coletados) e linhas de processos **novos**; colunas de julgamento só se vazias **e** com origem `sugerido` (campo `humano` nunca é sobrescrito; campo preenchido por humano na planilha é lido como `humano`).
- **Modelo padrão** (criação do zero): abas Processos (as 29 colunas, tabela do Excel, validação de dados em Situação/Probabilidade/Resultado, colunas calculadas: valor economizado e taxa de resolução), Parâmetros, **Indicadores** (fórmulas listadas nos "fatos estruturais" acima, `COUNTIFS/SUMIFS/AVERAGEIFS/MEDIAN`, sem funções que quebrem no Excel; evite `FILTER` ou isole-a em fallback), Dashboard (gráficos básicos), **Histórico** (retrato mensal, CONTRATOS §9) e **Campos não migrados**. Colunas ativas conforme `perfil["colunas_ativas"]`.
- **Política de cache de fórmulas** (decisão do coordenador): padrão `invalidar_cache=True` (o spike mostrou que o LibreOffice ignora `fullCalcOnLoad`); implemente a mitigação opcional: se `soffice` existir, recalcular numa **cópia temporária** e gravar os valores como cache; sem `soffice`, cair no padrão e avisar. A ferramenta **não exige** LibreOffice.
- Todos os limites do spike viram **recusa explícita com mensagem em português** (linha de totais, conteúdo abaixo da tabela, tabela dinâmica com cache ao acrescentar coluna etc.), nunca arquivo corrompido; `validar()` do spike roda como **portão pós-escrita** em todo arquivo gerado.
- `docs/fase2/conferencia-xlsx.md`: checklist de 15 minutos, em português simples, para abrir as saídas no Excel (Windows e Mac) e no Google Sheets (não testáveis aqui). **WS-7 só está "pronto" após essa conferência pelo usuário (marco M5)**; no relatório final, diga que está "pronto para conferência".

**Aceite**: suíte do spike migrada e ampliada; 200 linhas inseridas; partes não editadas idênticas; arquivo do cliente sujo e re-salvo pelo LibreOffice; criação do zero abre no LibreOffice com indicadores corretos conferidos contra um cálculo independente em Python sobre as mesmas fichas; `planilha.gerar` antigo continua funcionando.

---

## WS-8 — Gerador de dashboards (modelo C)

**Dono de**: `src/escritores/dashboard.py`, `src/modelos/dashboard/`, `tests/test_dashboard.py` (com Playwright/Chromium: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`; instale `playwright` com `pip` se faltar, **sem** rodar `playwright install`).

**Entregas**
- Estude os dois painéis de referência (caminho nos "fatos estruturais") e crie **templates próprios** em `src/modelos/dashboard/`: (1) **contencioso** (KPIs, rosca e barras, filtros, tabela, aba "qualidade dos dados", série histórica a partir da aba Histórico); (2) **carteira simples** (estilo do modelo A: processos por momento atual, por área/matéria, por tribunal, prazos de último andamento). Reescreva, **não copie literal**: sem nome de cliente, sem expressões regulares com nomes (parametrize por `perfil["parametros"]["empresas_do_grupo"]`), sem número real.
- **Offline**: SheetJS e Chart.js **embutidos** (baixe as versões fixas de cdnjs.cloudflare.com ou jsdelivr, registre versão e hash em `modelos/dashboard/BIBLIOTECAS.md`; se não houver rede, falhe com mensagem clara e use o pacote do pip/npm local, se existir; nada de CDN no HTML final).
- Dois modos: **`modelo`** (o usuário arrasta o `.xlsx`; mapeamento tolerante de colunas como nas referências, compatível com as 29 colunas de `ficha.CAMPOS`) e **`embutido`** (dados do retrato embutidos, abre já preenchido).
- `dashboard.gravar(xlsx, destino, perfil, **opcoes) -> Resultado` (CONTRATOS §5); fontes tipográficas locais ou fallback do sistema (sem Google Fonts).
- Acessibilidade e impressão (CSS de impressão para gerar PDF); responsivo; textos em português.
- **Integridade dos indicadores** (lições dos documentos de referência): "economia" só de processos encerrados e com valor lançado; acordo sem valor, acordo pago por terceiro e exclusão da lide aparecem **fora** do indicador e sinalizados; nunca contar o mesmo processo duas vezes.

**Aceite**: Playwright abre os dois modos **sem rede** (bloqueie requisições externas no teste) e confere KPIs e contagens contra um cálculo independente em Python sobre as fichas fictícias (200 processos); mesmo `.xlsx` gera os mesmos números nos dois modos; nenhuma referência a domínio externo no HTML final; nenhum nome de cliente.

---

## WS-9 — Painel: assistente dos fluxos

**Dono de**: `src/painel/assistente.py`, `painel/migracao.py`, `painel/entregas.py`, `painel/perfil.py`; edição pontual de `src/painel/base.py` apenas para acrescentar subabas (avise no relatório); `tests/test_painel_assistente.py`.

**Entregas** (padrão de `docs/fase2/painel-modulos.md`; rotas sob `/fluxo`, `/migracao`, `/entregas`, `/perfil`):
- Tela inicial "O que você quer fazer?" com **quatro botões**: Importar relatórios existentes; Elaborar relatório inicial; Atualizar relatório; Migrar de modelo. (A tela de revisão continua sendo `/`.)
- **Importar**: envio de vários arquivos (arrastar e soltar, sem JavaScript externo), detecção de formato (`leitores.detectar`), **tela de conferência da migração** (o que foi lido, ambiguidades, números inválidos, duplicados, vinculados, clientes sem nome padronizado, campos sem destino), confirmação que cria projeto, fichas e linhas de base (via `leitores` e `consolidar`; se algum desses módulos ainda não existir, programe contra a interface do contrato e use um **stub** em `tests/`, documentando no relatório).
- **Migrar de modelo**: tela de **mapeamento** (coluna do arquivo → campo da ficha → coluna do modelo novo, com sugestão automática e lista do que não tem destino) e escolha do modelo de destino; gera pelo escritor (stub se ainda não existir).
- **Elaborar inicial**: perfil de entrega (A, B, C), profundidade (rápido/padrão/completo), modo de coleta (**contínuo** com janela / **imediato** com **alerta de duração estimada** e confirmação; estimativa vem de `Fila.resumo()["estimativa_s"]`), filtro por cliente.
- **Atualizar**: soltar `.docx` e/ou `.xlsx`, conferência contra a carteira (processo novo? sumiu?), início da coleta.
- **Progresso em tempo real** (pausar, retomar, parar com segurança), usando a mesma abordagem de `painel/atualizar.py` para tarefa em segundo plano.
- **Entregas**: página com download dos arquivos de `saida/`, relatório de qualidade e lista "conferir manualmente"; pasta `entrada/`/`saida/` por relatório (funciona com Drive para Desktop).
- **Perfil**: edição de `perfil.json` (entregas, profundidade, modo, parâmetros); a escolha de IA externa e o consentimento são do WS-18 (deixe um ponto de extensão).
- Token em **todos** os formulários; tudo local (127.0.0.1); sem JavaScript externo; textos simples, para quem nunca usou.

**Aceite**: com `app.test_client()` e o coletor simulado/stubs, os quatro fluxos andam do início ao fim; envio de arquivo inválido volta com mensagem clara; `tests/test_painel.py` (instantâneo) continua verde (se precisar mudar o instantâneo por causa de subabas novas, regrave **só** o necessário e explique).

---

## WS-10 — Revisão em escala

**Dono de**: `src/painel/revisao_lote.py`, `src/painel/processo.py`, `src/painel/revisao_eventos.py` (a fatia de revisão já existente; mantenha o comportamento atual como padrão), `src/triagem.py`, `tests/test_triagem.py`, `tests/test_painel_revisao.py`.

**Entregas**
- `triagem.classificar(evento, ficha) -> {"nivel": "verde|amarelo|vermelho", "motivos": [..]}` por regras: **vermelho** = efeito desfavorável, prazo, audiência, qualquer valor monetário, mudança de resultado, trecho de origem que não confere; **amarelo** = qualquer alerta de regra existente (`resumir.conferir`, autoria não identificada, andamento sem tradução etc.); **verde** = o resto.
- Tela de **triagem**: contadores por nível, filtros (cliente, responsável, tribunal, nível, processo), ordenação por risco, **aprovação em lote só de verdes** com **amostragem obrigatória** configurável (por padrão 10% dos verdes vai para revisão manual, escolhidos de modo reprodutável), registro de quem aprovou o lote e quando (`evento["aprovado_por"]`, `["lote"]`).
- **Visão por processo**: linha do tempo dos eventos (data, texto, nível), com print e trecho de origem lado a lado (reuse as rotas `/documento` e `/print`), aprovar/corrigir/descartar por linha.
- **Campos derivados** (situação, momento atual, resultado, probabilidade, valores sugeridos pelo WS-17): bloco *antes → depois* para aprovar; aprovar vira origem `humano`.
- Atalhos de teclado (J/K navegar, A aprovar, D descartar, E editar) sem biblioteca externa.
- Regra "**sempre humano**" respeitada mesmo em lote.

**Aceite**: com 600 eventos fictícios, a triagem separa por nível conforme as regras; lote nunca inclui amarelo/vermelho; amostragem reprodutável; `tests/test_painel.py` verde.

---

## WS-11 — Qualidade da base, "o que mudou" e quadros

**Dono de**: `src/qualidade.py`, `src/historico.py` (retrato mensal), `src/quadros.py`, `tests/test_qualidade.py`, `tests/test_historico.py`, `tests/test_quadros.py`.

**Entregas**
- `qualidade.verificar(fichas, perfil) -> [Achado]` (`{"codigo", "gravidade", "numeros", "mensagem", "sugestao"}`): número CNJ inválido; duplicado/vinculado mal marcado; **mesma ação contada duas vezes**; rótulos fora do vocabulário ou parecidos (matéria, resultado, área); grafias diferentes da mesma parte; acordo sem valor lançado; **acordo pago por terceiro / exclusão da lide / cliente autor** marcados como ressalva (campo `observacoes` ou `outras_partes`; defina a convenção e documente); encerrado sem resultado; resultado e situação em conflito; ativo × momento atual (`ficha.validar`); campos obrigatórios por perfil ausentes; datas incoerentes (ajuizamento depois de último andamento, citação antes do ajuizamento); valor da causa vazio ou zero; linhas-marcador. Use `tests/ficticio.detectar_defeitos` como gabarito mínimo e **vá além dele**.
- `qualidade.o_que_mudou(estado_antes, estado_depois) -> {...}` por processo e por cliente (novos, encerrados, mudanças de momento, decisões, audiências e prazos, valores), com texto de uma página pronto para e-mail ao cliente (sem prometer resultado).
- `historico.gravar_retrato(fichas, data_base, destino)` e `historico.carregar(projeto)` conforme CONTRATOS §9; `historico.reconstruir(relatorios_lidos)` a partir de vários `RelatorioLido` (vários meses) → série mensal.
- `quadros.py`: **quadros analíticos** em estrutura de dados (para o escritor de planilha e o dashboard): acordos × economia **com ressalvas** (total geral, apenas com desembolso do cliente, apenas desfecho pecuniário definido: o indicador recomendado), maiores exposições (maior valor entre estimado, arbitrado, execução e causa), condenação × valor da causa, composição por tese, desfecho por tese (só julgados no mérito); gere junto as **notas metodológicas** em português.

**Aceite**: cada tipo de achado detectado em fixtures; falsos positivos conhecidos documentados no cabeçalho; retrato reproduzível (mesmo estado → mesmo arquivo); quadros conferidos contra cálculo independente em Python.

---

## WS-13 — QA, documentação e empacotamento (contínuo)

**Dono de**: testes transversais (`tests/test_desempenho.py`, `tests/test_confidencialidade.py`), `README.md`, `docs/` (guias do usuário), `empacotar.sh`, `requirements.txt`.

**Entregas**: (1) `requirements.txt` com as dependências novas (python-docx; Playwright já consta); fixe versões mínimas; (2) `tests/test_confidencialidade.py`: nenhum número de processo fora do permitido e nenhum nome parecido com real em arquivos versionados, nenhum domínio externo nos HTML gerados (quando existirem), nenhum segredo; (3) `tests/test_desempenho.py`: carteira de 200 processos fictícios percorre leitura → consolidação → qualidade → escritores em tempo razoável (limite generoso e configurável); (4) `empacotar.sh`: incluir `src/modelos/` e excluir `spikes/`, `.claude/`, `tests/fixtures` volumosos se houver; conferência de confidencialidade ampliada para os novos diretórios; (5) **guia do usuário** `docs/guia-fase2.md` em português simples para os quatro fluxos, com capturas descritas em texto (sem imagens de dados reais) e a seção "o que fazer quando algo dá errado"; (6) **README**: árvore de arquivos, quatro fluxos, IA externa opcional (aviso de confidencialidade), situação de testes por plataforma (Windows continua "não testado"); (7) um `docs/fase2/STATUS.md` com a matriz módulo × estado × pendência.

**Aceite**: `empacotar.sh` gera pacote limpo; guia lido e corrigido por uma segunda leitura crítica (registre as correções); testes novos verdes.

---

## WS-16 — Kit de pedidos das iniciais

**Dono de**: `src/pedidos.py`, `src/modelos/pedidos/` (`prompt.md`, `esquema.json`, `exemplo.json`), `docs/pedidos-iniciais.md`, `src/painel/pedidos.py`, `tests/test_pedidos.py`.

**Entregas** (PLANO 7.3)
- `esquema.json` (JSON Schema) do resultado: `processos: [{numero, cadastro:{reclamante, funcao, categoria_funcao, empresa_principal, outras_empresas, terceiros, municipio, uf, vara, tribunal, data_ajuizamento, valor_causa, criterio_valor_causa, ...}, pedidos:[{materia, pedido_como_formulado, valor_atribuido, situacao_valor, pagina_pdf, entra_nos_totais}], achados:[{tipo, descricao, impacto}]}]`, alinhado às abas de cadastro, pedidos, resumo e parâmetros por matéria das planilhas de pedidos (colunas: cadastro — Processo, Reclamante, Função do reclamante, Categoria da função, Empresa do grupo (principal), Outras empresas do grupo no polo passivo, Terceiros no polo passivo, Município, UF, Vara, Tribunal, Data do ajuizamento, Situação, Fase, Resultado, Valor da causa, Condenação arbitrada, Valor do acordo, Natureza do acordo, Probabilidade, Advogado(a) do reclamante, Tipo de ação, Entra nos totais?, Motivo da exclusão, Processo relacionado, Causa geradora; pedidos — Processo, Tribunal, Reclamante, Reclamada(s), Matéria, Pedido (como formulado na inicial), Valor atribuído, Valor da causa, % do valor da causa, Situação do valor, Pág. PDF, Entra nos totais?; resumo — Processo, valor da causa, soma dos pedidos quantificados, diferença, critério do valor da causa, nº de pedidos, pedidos sem valor, matéria de maior peso, observações/achados, fonte dos valores; parâmetros — Matéria, Tema, Classe, Conta nos rankings, Pode ser causa geradora).
- `prompt.md` versionado (versão no cabeçalho): papel, regras de extração (valor **exatamente como atribuído pelo reclamante**; reflexos agrupados na matéria principal; multas dos arts. 467/477 como matéria própria; "sem valor atribuído" × "fora do valor da causa" × "encargos embutidos na causa"; matéria **somente** do vocabulário `taxonomia.MATERIA` — fora dele, `Outros` + sugestão), formato de saída **só JSON** conforme o esquema, instruções para PDF grande/em lotes, o que fazer quando a página não é legível. Escreva e teste com **dados fictícios** (`exemplo.json`).
- `pedidos.pacote(projeto) -> [{numero, pdf_inicial, ja_extraido}]` (processos com inicial localizada e sem pedidos), exportação para pasta com PDFs e `prompt.md`.
- `pedidos.validar(texto_colado) -> {"ok": bool, "erros": [...], "avisos": [...], "dados": ...}`: JSON válido pelo esquema; matéria fora do vocabulário (sugere a mais próxima); **soma dos pedidos × valor da causa** (diferença > tolerância vira aviso, com o valor); processo desconhecido da carteira; duplicado; valores não numéricos.
- `pedidos.gravar(projeto, dados)`: grava `data/pedidos.json` e atualiza fichas (cadastro → `ficha.definir(..., "humano")` só quando a pessoa confirmar na tela; valor atribuído/matérias ficam em `pedidos.json`); exporta para as abas das planilhas de pedidos quando existir arquivo (use o escritor de `.xlsx` do WS-7 se já houver; senão, deixe a exportação para depois e registre).
- Tela `/pedidos`: lista de processos com/sem pedidos, botão "baixar pacote", campo **"colar resultado"**, **conferência dos achados antes de gravar**, e (se o WS-18 tiver um provedor externo cadastrado e consentido) botão "enviar pelo provedor" — deixe como ponto de extensão com mensagem "indisponível" até lá.
- `docs/pedidos-iniciais.md`: passo a passo em português simples (abrir a IA, anexar os PDFs, colar o prompt, copiar a resposta, colar no programa), com aviso de confidencialidade.

**Aceite**: validador rejeita/avisa cada tipo de erro em fixtures; ida e volta do `exemplo.json`; tela funciona com `app.test_client()`; nenhum número de processo real; o prompt é **claramente marcado como não validado com petições reais** (validação no piloto).

---

## WS-17 — Sugestão dos campos de julgamento

**Dono de**: `src/julgamento.py`, `tests/test_julgamento.py`.

**Entregas** (regras de `PLANO.md` seção 7.2, já corrigidas: **probabilidade é a do resultado, sem inversão por polo**)
- `julgamento.sugerir(ficha, eventos) -> {campo: {"valor", "regra", "evidencia": {"documento", "trecho"}, "ressalvas": [..]}}` para `resultado`, `probabilidade`, `valor_estimado`, `valor_economizado`:
  - **resultado**: teor da decisão de mérito mais recente (Procedente, Parcialmente procedente, Improcedente) e os desfechos Acordo, Extinto sem resolução de mérito, Arquivado/desistência, Incompetência declarada; sem decisão → sem sugestão. Fonte: evento aprovado com `efeito`/`tipo` (`resumir.py` já classifica efeito; leia também o texto do conteúdo e o trecho) e movimentos traduzidos; a leitura do teor com IA fica a cargo do WS-5, aqui entram **regras sobre texto** (palavras de julgamento: "julgo procedente", "julgo parcialmente procedente", "improcedente", "homologo o acordo", "extingo o processo sem resolução do mérito", etc.).
  - **probabilidade**: Possível antes de decisão; Provável com procedência ou parcial procedência; Remota com improcedência; vazia se encerrado por acordo/extinção; vale a decisão mais recente e de instância mais alta, com ressalva "sujeita a recurso" quando a decisão é de 1º grau e há recurso pendente.
  - **valor_estimado**: valor da causa até haver sentença/acórdão com valor arbitrado diferente; então o arbitrado; em acordo, o valor do acordo; sem valor claro → mantém o da causa e ressalva.
  - **valor_economizado** = valor da causa − valor estimado, **só** processo encerrado; **não conta** (e marca ressalva): acordo sem valor lançado, acordo pago por terceiro, exclusão da lide, cliente autor (`polo_cliente == "ativo"`).
- Nunca grava `humano`; devolve só sugestão (o aplicador grava origem `sugerido` via `ficha.definir`); campo já `humano` não aparece na saída.
- `julgamento.aplicar(ficha, sugestoes)`; `julgamento.concordancia(fichas_migradas)`: compara a sugestão com o que está lançado por humano nos relatórios migrados (origem `humano` nos campos de julgamento), por regra: `{campo: {"concordam", "total", "casos_divergentes": [numero]}}`.
- Ressalvas sempre listadas como texto curto em português.

**Aceite**: tabela de casos de teste por regra (inclusive **cliente autor sem inversão**, parcial procedência, acordo com e sem valor, acordo pago por terceiro, extinção, decisão de 1º grau com recurso, decisão do tribunal reformando a de 1º grau, processo sem decisão); campo humano intocado; `concordancia` correta em carteira fictícia com campos `humano` conhecidos.

---

## WS-18 — Provedores de IA

**Dono de**: `src/ia.py`, `src/painel/ia.py`, `tests/test_ia.py`.

**Entregas** (PLANO 7.1; CONTRATOS §8)
- `ia.provedor(perfil, cliente) -> Provedor`, `Provedor.gerar(sistema, usuario, *, esquema=None, cliente) -> {"texto", "json", "motor"}`, `ia.registro_de_envios(projeto)`.
- Provedores: **local** (Ollama, reaproveitando o que já está em `resumir.py`: não duplique, extraia o mínimo), **Anthropic** (API de mensagens, chave no cofre via `acesso.py`/keyring; modelo configurável; saída JSON forçada por esquema quando possível), **compatível com OpenAI** (endereço, chave e modelo configuráveis). Consulte a documentação oficial atual dos serviços (use a skill `claude-api` para o provedor Anthropic) antes de escrever as chamadas; **nada de rede nos testes** (injete um transporte falso).
- **Consentimento**: `perfil["ia"]["consentimento_externo"]` (por relatório) e `ia.por_cliente`; **sem `true` explícito, nenhuma chamada externa** (teste obrigatório, inclusive com perfil malformado); recusa clara quando ausente.
- **Minimização**: só texto extraído; função `pseudonimizar(texto, partes)` reversível apenas localmente (mapa guardado no projeto), aplicada quando `pseudonimizar` for verdadeiro; nunca enviar prints, certificado, segredo ou caminhos.
- **Registro local** de cada envio (quando, provedor, modelo, cliente, número de caracteres, hash do conteúdo — **sem** guardar o texto do cliente no registro), consultável.
- **Fallback**: sem chave, sem rede ou erro do provedor → cai no local e devolve `motor` do que realmente respondeu, com aviso.
- **Selo**: função `ia.selo(motor) -> "local" | "externa: <provedor>"` para as telas.
- Tela `/ia` (módulo `painel/ia.py`): cadastro de provedores (nome, endereço, modelo, chave — a chave nunca é mostrada de volta), botão **Testar**, consentimento por relatório/cliente com explicação clara do que sai do computador, consulta do registro de envios.
- Atualize o texto de confidencialidade para o README **em um arquivo próprio** (`docs/confidencialidade-ia.md`); o WS-13 integra ao README.

**Aceite**: testes com transporte falso para cada provedor; consentimento ausente nunca chama a rede; pseudonimização ida e volta; registro sem texto do cliente; fallback funciona; chave nunca aparece em log nem em HTML.
