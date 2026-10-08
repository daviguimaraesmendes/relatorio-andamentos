# Como retomar a Fase 2 na próxima sessão

Atualizado em 07/10/2026, ao fim da Onda 1. **Nenhum agente está rodando.** Tudo está commitado e enviado ao branch `claude/gallant-pasteur-etzpu5`.

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

Anotadas em 08/10/2026 enquanto a análise de um relatório real roda. **Sem ação por enquanto** (esperar a análise terminar e ver o que mais aparece).

1. **Login automático do jus.br falhou.** Faltam detalhes para diagnosticar: mensagem exata na tela do navegador de automação ou no Terminal, se o PJe Office estava aberto, se foi na primeira consulta ou depois de um tempo, e se a aba Atualizar da versão anterior (caminho já validado) faz o login normalmente na mesma máquina. Hipótese a checar: o caminho novo (`fila.ColetorReal`, chamado pelo painel em outra thread) chama `coletor.logar` fora da mesma ordem/estado da aba Atualizar. O login está em `coletor.logar` → `acesso.login_automatico` (diálogo do PJe Office).
2. **Captcha do TRT não chama a atenção.** A janela é trazida de volta por `janela.mostrar` (restaura, posiciona 1100×800 e `page.bring_to_front()`) e há um aviso sonoro, mas no Mac isso pode não passar por cima do Terminal/painel. Ideias, da mais simples à mais forte: (a) `osascript` com notificação do sistema ("Captcha do TRT: precisa de você") e `activate` do navegador de automação; (b) maximizar/tela cheia em vez de 1100×800; (c) faixa vermelha fixa no painel ("Precisa de você: captcha do TRT 7 aguardando") com atualização automática; (d) repetir o aviso a cada 60 s até ser resolvido; (e) enquanto espera, **pular o processo** e seguir com os demais, voltando ao captcha no fim (a fila já agrupa por TRT). Código: `trt.esperar_captcha_humano`, `janela.mostrar`.

**Contexto do relatório de teste (usuário, 08/10/2026)**: tem **muitos processos físicos** (sem autos eletrônicos). Ao analisar os diagnósticos, "não encontrado", "conferir manualmente" e coleta vazia nesses processos são esperados e **não** indicam defeito do programa. Melhoria a avaliar depois da análise: separar na fila um motivo próprio, "físico / sem autos eletrônicos" (hoje cai em `nao_encontrado` ou `manual`), para o relatório de cobertura e o "conferir manualmente" distinguirem físico de erro de coleta; para físico, o relatório continua só com o que vier do DJEN e do que o advogado lançar à mão. Também medir quantos dos ~92 processos do teste são físicos antes de avaliar tempo por processo e taxa de sucesso (a taxa de sucesso só vale sobre os eletrônicos). Previsão: faltavam cerca de 40 processos quando o usuário avisou; ele avisa quando concluir.

Ao retomar: pedir ao usuário os detalhes do item 1 (sem nomes de cliente) e decidir quais ideias do item 2 implementar. É trabalho pequeno (coordenador, sem agente).

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
