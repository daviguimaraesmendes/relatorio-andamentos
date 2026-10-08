# Como retomar a Fase 2 na próxima sessão

Atualizado em 08/10/2026, ao fim do **beta 3** (seção "Beta 2.0.0-beta3" abaixo). **Nenhum agente está rodando.** Tudo está commitado e enviado ao branch `claude/gallant-pasteur-etzpu5`.

## Onde estamos

| Etapa | Estado |
| --- | --- |
| Etapa 0 (contratos, fixtures, coletor simulado, painel fatiado, spikes S1/S2) | Concluída (M1) |
| Onda 1 (15 workstreams) | Concluída e integrada; suíte completa verde (1.183 testes, 2 pulados) |
| **Onda 2** | **WS-14 (fluxos ponta a ponta) concluído e integrado** (`src/fluxos.py`, 4 fluxos + painel ligado; suíte completa 1.215 testes, 2 pulados). **WS-15** virou o roteiro `piloto.md` (escrito pelo coordenador) + os testes de 3 ciclos e retomada que o WS-14 já inclui; carga de 1.000 processos fica opcional |
| Onda 3 (pilotos M5/M6 no Mac do usuário, extras, pacote v2) | Depende do usuário e da Onda 2 |

Documentos de referência, nesta ordem: `PLANO.md` (o quê e por quê), `CONTRATOS.md` (interfaces), `WORKSTREAMS.md` (Onda 1, já feita), `ONDA-2.md` (o que falta), `STATUS.md` (matriz de módulos), `fixtures.md` (dados fictícios e coletor simulado), `painel-modulos.md` (como criar tela), `spikes/` (S1 planilha, S2 Word, S3 DataJud), os `RFC-*.md` (decisões e convenções propostas pelos agentes).

## Preparar o ambiente (cada sessão nova começa limpa)

1. `git fetch origin claude/gallant-pasteur-etzpu5 && git checkout claude/gallant-pasteur-etzpu5` (ou continue no branch já clonado).
2. Dependências de teste que o ambiente em nuvem não traz prontas: `pip install flask openpyxl keyring pyotp pypdf python-docx lxml` (o `flask` pode exigir `--ignore-installed blinker`) e `pip install playwright==1.56.0` (a versão tem que casar com o Chromium instalado em `/opt/pw-browsers`; **não** rode `playwright install`). LibreOffice (`soffice`) e `pdftotext` já existem no ambiente.
3. Conferir a base: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 -m unittest discover -s tests -p "test_*.py"` deve terminar `OK` (2 testes pulados: OCR sem `tesseract` e um condicionado ao ambiente).
4. Os dois painéis de referência (com nomes de cliente embutidos) **não estão no repositório**. Foram usados só pelo WS-8 e já viraram templates próprios em `src/modelos/dashboard/`. Não é preciso recriá-los.

## (Histórico) Lançar a Onda 2

1. **WS-14** (um agente, em worktree isolado): prompt pronto abaixo. É o caminho crítico; só ele pode começar agora.
2. **WS-15** (um agente): só depois de integrar o WS-14.
3. Depois de cada agente: `git merge` do branch `worktree-agent-<id>` no branch do coordenador, suíte completa, `git push`. Se o `git push` devolver `Internal Server Error` do GitHub (aconteceu várias vezes em 07/10/2026), repetir com esperas de 30 a 120 s; costuma passar na terceira a quinta tentativa.

Prompt do WS-14 (copiar para a ferramenta de agentes, com `isolation: worktree`):

> Você é o agente do WS-14 (fluxos ponta a ponta) da Onda 2 da Fase 2 do projeto relatorio-andamentos. PRIMEIRO PASSO: no seu worktree rode `git reset --hard claude/gallant-pasteur-etzpu5` (o worktree nasce no commit inicial; ainda não há trabalho seu). Depois leia `docs/fase2/BRIEFING-AGENTES.md`, `docs/fase2/PLANO.md`, `docs/fase2/CONTRATOS.md`, `docs/fase2/STATUS.md`, `docs/fase2/fixtures.md`, `docs/fase2/painel-modulos.md` e execute a seção "WS-14" de `docs/fase2/ONDA-2.md`. Instale as dependências de teste conforme `docs/fase2/PROXIMA-SESSAO.md` (Playwright 1.56.0). Siga o briefing à risca (sem push, dados fictícios, relatório final no formato pedido). Os módulos da Onda 1 já passam nos seus testes: ligue-os, não os reescreva.

Prompt do WS-15 (depois do WS-14): idem, trocando a seção por "WS-15" e acrescentando "O WS-14 já está integrado em `src/fluxos.py`".

## Observações do teste prático (usuário, beta2)

Anotadas em 08/10/2026 enquanto a análise de um relatório real roda. **Tratadas no beta 3** (seção acima); o texto original fica como registro das hipóteses.

1. **Login automático do jus.br falhou.** Faltam detalhes para diagnosticar: mensagem exata na tela do navegador de automação ou no Terminal, se o PJe Office estava aberto, se foi na primeira consulta ou depois de um tempo, e se a aba Atualizar da versão anterior (caminho já validado) faz o login normalmente na mesma máquina. Hipótese a checar: o caminho novo (`fila.ColetorReal`, chamado pelo painel em outra thread) chama `coletor.logar` fora da mesma ordem/estado da aba Atualizar. O login está em `coletor.logar` → `acesso.login_automatico` (diálogo do PJe Office).
2. **Captcha do TRT não chama a atenção.** A janela é trazida de volta por `janela.mostrar` (restaura, posiciona 1100×800 e `page.bring_to_front()`) e há um aviso sonoro, mas no Mac isso pode não passar por cima do Terminal/painel. Ideias, da mais simples à mais forte: (a) `osascript` com notificação do sistema ("Captcha do TRT: precisa de você") e `activate` do navegador de automação; (b) maximizar/tela cheia em vez de 1100×800; (c) faixa vermelha fixa no painel ("Precisa de você: captcha do TRT 7 aguardando") com atualização automática; (d) repetir o aviso a cada 60 s até ser resolvido; (e) enquanto espera, **pular o processo** e seguir com os demais, voltando ao captcha no fim (a fila já agrupa por TRT). Código: `trt.esperar_captcha_humano`, `janela.mostrar`.

**Contexto do relatório de teste (usuário, 08/10/2026)**: tem **muitos processos físicos** (sem autos eletrônicos). Ao analisar os diagnósticos, "não encontrado", "conferir manualmente" e coleta vazia nesses processos são esperados e **não** indicam defeito do programa. Melhoria a avaliar depois da análise: separar na fila um motivo próprio, "físico / sem autos eletrônicos" (hoje cai em `nao_encontrado` ou `manual`), para o relatório de cobertura e o "conferir manualmente" distinguirem físico de erro de coleta; para físico, o relatório continua só com o que vier do DJEN e do que o advogado lançar à mão. Também medir quantos dos ~92 processos do teste são físicos antes de avaliar tempo por processo e taxa de sucesso (a taxa de sucesso só vale sobre os eletrônicos). Previsão: faltavam cerca de 40 processos quando o usuário avisou; ele avisa quando concluir.

3. **Captcha do TRT pedido várias vezes** (hipótese do usuário: o captcha resolvido vale para as consultas seguintes, mas a página de consulta é aberta e fechada a cada processo em vez de só voltar e pesquisar de novo). **Leitura do código confirma o padrão**: `trt.coletar_processo` abre uma página nova por processo (`janela.nova_pagina(context)`, linha ~313) e a fecha no fim (`page.close()`, ~390), e `_abrir_autos_trt` faz `page.goto(.../consultaprocessual/)` completo a cada processo (~257), recarregando a consulta do zero. Se o desafio do captcha estiver ligado ao estado da página (ou ao carregamento inicial da consulta), cada processo o dispara de novo. Correção proposta, a validar num TRT real: manter **uma página de consulta por TRT** aberta durante toda a rodada (guardada no contexto do coletor), e para o processo seguinte usar o próprio formulário da consulta (voltar à pesquisa/"nova consulta" e `buscar_numero`) em vez de `goto`; só recarregar se o campo do número sumir. Os documentos/PDF devem abrir em outra aba e fechar, sem tocar na página de consulta. Medir antes e depois: captchas pedidos por rodada. Como a fila já agrupa os processos do mesmo TRT, o ganho tende a ser grande. Código: `trt.py` (`coletar_processo`, `_abrir_autos_trt`, `buscar_numero`), `janela.nova_pagina`.

4. **Instâncias nos tribunais trabalhistas: 1º grau, 2º grau e TST** (pedido do usuário). **Leitura do código (`trt.coletar_processo`)**: o 1º grau é lido pela pesquisa da consulta do TRT; o **2º grau é tentado** em seguida pela mesma consulta, trocando o grau na URL (`/detalhe-processo/<número>/2`), e só entra se o `id` dos autos for diferente do 1º; se a pesquisa já abrir direto o 2º grau, os autos ficam sob o grau 2. **O TST não é consultado em lugar nenhum**: não há tratamento de host do TST (`consultaprocessual.tst.jus.br` ou equivalente); o único contato é o alias `tst` do DataJud em `capa.py`, só para metadados. Dois pontos fracos na parte do 2º grau: (a) `except Exception: pass` engole qualquer falha (captcha, tempo esgotado, sessão) na tentativa do 2º grau, então um recurso que existe pode ficar sem leitura **sem nenhum aviso**; (b) essa tentativa faz **mais um `page.goto`** por processo, o que pode contribuir para os captchas repetidos do item 3. Proposta: (1) registrar no evento/estado qual grau foi lido e qual falhou, com aviso `grau_nao_lido`; (2) só tentar o 2º grau quando houver indício de recurso (movimento de remessa/distribuição ao 2º grau, ou o DataJud indicar processo no grau 2) e reutilizar a mesma página; (3) detectar o **TST** de forma barata e sem captcha pelo **DataJud** (índice `tst`, mesmo número CNJ): se existir, trazer os movimentos do TST e marcar o processo "no TST"; (4) se o usuário quiser os **documentos** do TST (acórdãos, decisões), implementar o coletor da consulta do TST num segundo momento, depois de ver o acesso real (captcha/login). Os eventos já têm o campo `grau` ("1º grau", "2º grau"); acrescentar "TST" e o momento atual "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA" (ou similar) ao vocabulário. A matéria dos graus superiores também importa para o relatório (momento atual, último andamento, resultado e probabilidade usam a decisão mais recente e de instância mais alta).

Ao retomar: rodar `src/diagnostico_rodada.py` no Mac (ver `diagnostico-rodada1.md`), conferir as hipóteses e validar o beta 3 (lista acima).

## Beta 2.0.0-beta4 (08/10/2026): planilha de contingências, data-base e painel desatualizado

Origem: o usuário rodou o beta (provavelmente o beta2/beta3 com o painel já aberto) num relatório em **planilha de contingências** (não é modelo A nem B) e relatou: (a) login automático não funcionou (senha e autenticador manuais), (b) autos acessíveis não baixados, (c) sem aviso de captcha, (d) "atualizar" não funcionou, (e) pediu a conversão para os modelos novos (texto simplificado e painel). **Os logs ficam no Mac do usuário e a sessão em nuvem não os alcança**: (a) e (c) não foram diagnosticados com dados.

- **Hipótese mais forte para (a) e (c)**: o painel não foi reiniciado depois de copiar o pacote, então rodou código antigo; o topo do painel mostra a versão lida do arquivo `VERSAO` a cada pedido (enganava). Agora `painel.base.VERSAO_CARREGADA` compara com o arquivo e mostra a faixa "Reinicie o painel". A coleta do Assistente passou a gravar `data/logs/*-assistente.log` (antes só ia ao Terminal) com a versão na primeira linha.
- **(b)/(d) com causa em código achada**: `fila.ColetorReal` tratava processo visto pela primeira vez sem `desde` como "linha de base" (nada coletado), e a conferência da atualização não pedia data-base; o arquivo do usuário vinha sem data-base e só com o número lido (planilha fora do modelo, colunas de baixa confiança descartadas sem aviso). Corrigido: histórico completo sem `desde`; campo de data-base na conferência; `leitores.base.finalizar` deduz a data-base do fecho; `grade.py` lê "A/B" como o mesmo campo, "breve resumo do caso" como objeto e a coluna de histórico pelo conteúdo; aba "Arquivados" = inativo; momento deduzido pelas regras; `/fluxo/mapear` e `/fluxo/migrar` nas conferências de importar e atualizar.
- **(e)**: já existia (`/migracao`, `fluxos.converter`); agora o painel (`dashboard`) é destino também e há atalho a partir da conferência.
- **Pendente de dados reais**: login (passo que falha), captcha (aviso), downloads dos documentos dos TRTs na aba própria (mudança do beta3 ainda não validada com o tribunal real; se a aba nova pedir captcha de novo ou não entregar o PDF, voltar a abrir o documento na página de consulta).
- **Lacuna conhecida**: as colunas próprias do cliente (passivo potencial, provisão, depósito) só sobrevivem em "Campos não migrados"; não há campo na ficha para elas. Se o escritório quiser acompanhá-las no modelo novo, definir campos (`ficha.CAMPOS`) e colunas.

## Beta 2.0.0-beta3 (08/10/2026): o que foi feito a partir do teste de 92 processos

Feito numa sessão em nuvem **sem acesso aos logs reais** (ficam no Mac do usuário): o diagnóstico numérico ficou como script (`src/diagnostico_rodada.py`) e o documento `diagnostico-rodada1.md` traz a leitura do código. Tudo abaixo foi testado só com doubles (`tests/test_beta3.py`, 53 testes); **o que depende de tribunal, captcha, login e janelas do Mac está em "Validar no Mac"**.

| Item | Onde |
| --- | --- |
| 2.1 Login: motivo por passo (`acesso.ULTIMO`/`ORIENTACAO`), diagnóstico em `diagnosticos/login_jusbr_t*.{png,html,txt,json}`, `LoginFalhou`, erro `fatal` pausa a fila (`Fila.devolver`) e o painel passa a "Retomar"; o painel assistente fecha o navegador no fim | `acesso.py`, `coletor.logar`, `fila.ColetorReal/rodar_fila`, `painel/assistente.py`, `rodar.py` |
| 2.2 Uma página de consulta por TRT por rodada, pesquisa pelo formulário (escada: campo já pronto → "nova consulta" → voltar no histórico → recarregar, contada em `RECARGAS`), documentos em aba própria, log `captchas pedidos nesta rodada` | `trt.py` |
| 2.3 Captcha que chama a atenção: `atencao.py` (arquivo `data/atencao.json` + faixa vermelha `/atencao.json` em todas as telas), notificação e som por `osascript`, navegador à frente e maximizado (`janela.mostrar(maximizar=True)`), lembrete a cada 60 s, espera `coleta.captcha_espera_min` (padrão 10), depois o processo é **adiado** (`erro.adiavel`) e a fila volta ao TRT no fim da rodada | `atencao.py`, `trt.py`, `fila.py`, `painel/base.py` |
| 2.4 Físico: código `fisico` (`fila.parece_fisico`: DJEN vazio **e** DataJud vazio; na dúvida, manual), `cobertura()` com `fisico`, `taxa_de_sucesso()`, cartões e listas à parte no painel | `fila.py`, `painel/assistente.py`, `painel/entregas.py` |
| 2.5 Graus: 2º grau só com indício (`trt.indicio_de_recurso`, DataJud grau G2), pela rota da aplicação (sem recarregar), falha vira aviso `grau_nao_lido` (vai ao ciclo e a `ficha.ultima_coleta.graus`); TST pelo DataJud (`capa.consultar_tst/no_tst/movimentos_do_tst`, `fila._acrescentar_tst`), grau "TST", `taxonomia.GRAUS`, momento "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA", `julgamento` trata TST como grau 3 | `trt.py`, `capa.py`, `fila.py`, `taxonomia.py`, `julgamento.py`, `fluxos.py` |
| Texto da IA local: pedido de 25 a 80 palavras com motivo, efeito e dados concretos, exemplos de redação do escritório (`estilo.md` ou `estilo_redacao`), alerta de resumo curto (`resumir.MINIMO_PALAVRAS`) | `resumir.py` |
| Diagnóstico anonimizado da rodada; linhas `tempo:` por etapa nos logs | `diagnostico_rodada.py`, `trt.py`, `coletor.py` |

**Gancho do TST (não implementado, a pedido do usuário)**: o coletor de **documentos** do TST (acórdãos, decisões) só será escrito depois que o usuário abrir a consulta do TST e descrever o acesso (captcha? login?). Hoje só há os movimentos do TST pelo DataJud e a marca `no_tst`. O lugar natural é um `tst.py` no estilo de `trt.py` (uma página de consulta por rodada, `coletar_processo(context, proc, estado, lista, historico, cota, desde, relato)`), chamado por `fila._acrescentar_tst` quando `no_tst`.

**Estilo dos andamentos (colhido do relatório modelo, 08/10/2026)**: parâmetros em `estilo-andamentos.md` e `src/estilo_andamentos.py` (`PARAMETROS`, `avaliar`, `colher`); o pedido à IA local foi alinhado (voz do escritório na 1ª pessoa do plural, valores, prazos, norma só quando decide). A régua `avaliar` ainda **não está ligada à revisão/triagem**. O relatório modelo real foi lido pelo leitor `docx_a` (24 processos): vocabulário ampliado com "AGUARDANDO CITAÇÃO DO EXECUTADO" e "AGUARDANDO PAGAMENTO DO SALDO DEVEDOR"; **pendente de decisão do usuário**: o rótulo "DECISÃO" (hoje lido como "CONCLUSOS PARA DECISÃO") e o tipo dos vínculos escritos como "PROCESSO Nº A, B, C" (marcados "apenso").

### Validar no Mac (o que o usuário vai ver)

1. **PJe Office fechado + iniciar a coleta**: faixa vermelha com o motivo, coleta em pausa, `diagnosticos/login_jusbr_t1.json` com `"passo": "dialogo"`; abrir o PJe Office, clicar **Retomar**.
2. **Captcha**: notificação com som, navegador maximizado na frente do Terminal, faixa vermelha; repete a cada 60 s. Deixar passar 10 min num TRT: o processo é pulado, os outros tribunais seguem e o TRT volta no fim.
3. **Captchas por rodada**: a linha `captchas pedidos nesta rodada` deve mostrar bem menos que o número de processos de TRT. Se a consulta recarregar (`consulta recarregada do zero: Nx`), a navegação por formulário (botão "nova consulta" ou voltar no histórico) não funcionou naquele TRT: me dizer qual, e abrir `diagnosticos/` para ver a tela.
4. **2º grau**: `graus lidos: 1º, 2º` em processo com recurso; a navegação do 1º para o 2º é por rota da aplicação (`pushState`); se não vierem os autos em 8 s, cai no `goto` (que pode pedir captcha).
5. **Físicos**: conferir se os marcados como físicos são mesmo físicos (a regra é conservadora).
6. **TST**: com a chave do DataJud, processos no TST mostram "no TST" nos avisos do ciclo e andamentos com grau TST.

### Riscos e pendências do beta 3

- A navegação do TRT (escada de `preparar_busca`, rota de grau, aba de documento) segue suposições sobre o PJe (campo `#nrProcessoInput`, SPA que aceita `pushState`/`popstate`); só o TRT real confirma.
- `osascript` para notificação e para trazer o navegador à frente precisa de permissão (Acessibilidade/Automação) para o aplicativo que abre o painel; sem ela o aviso sonoro da notificação pode falhar em silêncio (a faixa vermelha do painel continua).
- Windows: o aviso é só o sinal sonoro do terminal; **não testado**.
- `rodar.py --fila` (caminho antigo da fila) não grava os movimentos do TST (só o fluxo `fluxos.processar_resultado` os grava).
- **Defeito de desenho conhecido, não corrigido**: o `comum.PROJETO` é global e a coleta roda numa thread do painel; trocar de relatório (aba) durante uma coleta no Assistente pode gravar eventos no relatório errado. Proposta: a thread de coleta fixar o projeto (como `fluxos._em(slug)`) ou o painel bloquear a troca de aba enquanto a coleta roda.
- O resumo curto só avisa; a qualidade real do texto depende do modelo (testar `gemma3:12b` ou maior se a memória permitir) e dos exemplos em `estilo.md`.
- Andamentos sem tradução: a lista real sai do script de diagnóstico; cadastrar as regras em `movimentos.json` só depois de ver a lista.

## Beta 2.0.0-beta2 (08/10/2026): clientes em lote

O primeiro teste do usuário (relatório de 92 processos) mostrou que o cliente tinha de ser informado processo a processo. Corrigido em `src/clientes.py` (candidatos a partir das partes, identificação em lote com polo e parte contrária, aplicação em lote), no bloco "Quem é o cliente?" da conferência da importação (`painel/assistente.py`), no `fluxos.migrar` (automático: clientes cadastrados, empresas do grupo da planilha, candidato óbvio, cliente padrão), e nos botões de lote em `cadastro.py`. Também corrigido: edição de cliente/polo/parte contrária no cadastro ficava escondida atrás de `campos` (`carteira.gravar_plano`). Testes em `tests/test_clientes.py`.

## Beta 2.0.0-beta1 (08/10/2026)

Pacote gerado com `./empacotar.sh` (`dist/relatorio-andamentos.zip`, ~1,4 MB, sem dados de cliente; confidencialidade verificada). Instruções de instalação por cima da versão anterior e roteiro curto de teste em `BETA-LEIAME.md`; roteiro completo em `piloto.md`. A versão aparece no topo do painel (arquivo `VERSAO`). DataJud vem ligado no exemplo de configuração, mas a chave pública do CNJ **não** vai no repositório (o sistema bloqueou a gravação por ser credencial): o usuário a cola em `config.json` ou em `DATAJUD_CHAVE`. Validei hoje, de fora do repositório, que o endpoint público responde com a chave publicada na wiki e que o formato bate com o que `capa.py` espera.

**Aguardando o usuário**: teste prático do beta no Mac (nada mais a construir antes disso). O que ele devolver (planilha de registro anonimizada) define a calibração e o beta2.

## Próximos passos sugeridos (foco: relatórios mais completos)

Em ordem de valor, **um agente por vez** (ou direto pelo coordenador quando for pequeno):

1. **Piloto M5** (usuário, Mac): seguir `piloto.md`. É o que mais reduz risco; traz dados reais para calibrar.
2. **Aba de quadros analíticos** no modelo B (`quadros.gerar` já existe; falta o escritor `xlsx_b` criar a aba com acordos × economia, maiores exposições, condenação × causa, composição e desfecho por tese). Pequeno; coordenador ou 1 agente.
3. **Tela Atualizar do painel** passar a usar a conferência de arquivo dos fluxos (hoje `texto_editado_a_mao` só aparece por código/CLI) e expor `dashboard_modo` (modelo × embutido) na tela de Entregas.
4. **Planilha (modelo B)**: coluna de cliente e tipo dos vínculos (hoje `migrar` avisa `processo_sem_cliente`; aceita `cliente_padrao`).
5. **Extras (WS-12)**: alertas (processo parado, audiência e prazo próximos), agenda `.ics`, descoberta contínua pelo DJEN, PDF e rascunho de e-mail ao cliente.
6. **Calibração** com os dados do piloto: vocabulário, limiares (duplicata, qualidade, triagem), regras de momento atual, mapeamento de cabeçalhos, prompt de pedidos.
7. **Pacote v2** (README, guia, `empacotar.sh`) e Windows declarado "não testado".

RFCs decididos nesta rodada: o momento atual por regra entra como `coletado` (prioridade 4) para poder atualizar um valor `migrado`; por IA entra como `sugerido`. O texto gravado por ciclo fica em `ultimo_texto_gravado` com `por_entrega` (docx_a e xlsx_b). Propostas dos agentes em `RFC-*.md` que não conflitam com isto seguem como convenção.

## Decisões do usuário já tomadas (não reabrir)

- IA: local por padrão (modelo maior se houver memória); provedores externos (Claude, API compatível com OpenAI) só por escolha do usuário, com consentimento por cliente.
- Coleta: sequencial; modo contínuo (janelas de horário) e modo imediato (com aviso de duração). Nunca paralelo contra jus.br e TRT.
- Entrada do modelo A: `.docx` exportado do Google Doc. Planilha: o arquivo do cliente é o molde na atualização; modelo padrão sanitizado no inicial; fluxo "Migrar de modelo".
- Pedidos das iniciais: kit para IA melhor (prompt, guia, "colar resultado"), feito; extração automática local fica de fora.
- Julgamento: sugestão por regra, sempre revisada; **probabilidade é a do resultado, sem inversão por polo**; valor economizado = valor da causa − valor estimado, só de processo encerrado e sem os casos com ressalva.
- Fecho "sem atualizações" só quando não houve novidade no ciclo.

## Decisões do usuário, segunda parte (07/10/2026)

- O **scraping** (jus.br e TRT, acesso já validado) funcionou bem: o foco agora é **montar e atualizar relatórios mais completos** (fluxos, escritores, qualidade, quadros). Limitações de obtenção de dados ficam para os testes com casos reais.
- **Saídas** (arquivos gerados na máquina do usuário) estão autorizadas.
- **Limite de gasto**: usar poucos agentes. Arranjo adotado: **um agente por vez, só no caminho crítico** (hoje o WS-14); o que for pequeno o coordenador faz direto; WS-15 só depois, e talvez reduzido. Ao chegar perto do limite: **parar tudo, commitar, empurrar e atualizar este arquivo** (estado, o que está em andamento, próximo passo) antes de qualquer outra coisa.

## Pendências que dependem do usuário

1. **DataJud**: o usuário confirmou (07/10/2026) que o uso **não é comercial**; a fonte vem **ligada** em `config.exemplo.json` (`fontes_externas.datajud.ativo`). Falta só a chave pública do CNJ (wiki do DataJud) em `config.json` (`chave`) ou na variável `DATAJUD_CHAVE`; sem ela a fonte avisa e segue sem DataJud. Não traz partes nem valor da causa.
2. **Excel e Google Planilhas**: abrir as planilhas geradas (`python3 tests/test_xlsx_b.py --exemplos PASTA` cria quatro de exemplo) e seguir `conferencia-xlsx.md`. Pontos de maior risco: tabela dinâmica montada à mão, textos gravados em linha, fórmulas com colunas de nome longo (`#NOME?`).
3. **Word e Google Docs**: gerar um `.docx` e abrir seguindo `conferencia-docx.md`; testar a ida e volta com uma exportação real do Google Doc (rótulos, título `[ MOMENTO ]` e frase de fecho ainda são suposições).
4. **Piloto M5/M6 no Mac** (jus.br, TRT, captcha, tempo real por processo, cobertura por tribunal, qualidade do modelo de IA local, prompt de pedidos com petições reais). O roteiro sai do WS-15.
5. Convenção das ressalvas de economia: escrever em Observações os marcadores `[acordo pago por terceiro]` e `[exclusão da lide]`; sem isso o sistema não os adivinha.

## Riscos conhecidos para lembrar

- Tudo foi validado com dados fictícios e com ferramentas de linha de comando (python-docx, openpyxl, LibreOffice, Chromium). Nada com Word, Excel, Google, jus.br, TRT, Ollama ou API de IA reais.
- Limiares e regras (detecção de duplicata, qualidade, triagem, momento atual por regra, mapeamento de cabeçalhos) foram calibrados só com texto fictício.
- O Windows continua "não testado".
- O limite mensal de gasto da conta já foi atingido uma vez (7 de outubro); confira o limite antes de lançar agentes em paralelo.
