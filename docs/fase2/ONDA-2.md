# Onda 2 — Integração (especificação pronta para delegar)

Status: **não iniciada**. Esta página é o que será delegado quando a sessão seguinte começar. Leia primeiro `PROXIMA-SESSAO.md` (como retomar) e `BRIEFING-AGENTES.md` (regras de trabalho e formato do relatório final, valem aqui também).

Pré-requisito já cumprido: os 15 workstreams da Onda 1 estão integrados no branch `claude/gallant-pasteur-etzpu5` e a suíte completa passa (1.183 testes, 2 pulados).

---

## WS-14 — Fluxos ponta a ponta (`src/fluxos.py`)

**Dono de**: `src/fluxos.py`, `tests/test_fluxos.py`, `tests/test_fluxos_painel.py`; edições **pontuais** em `src/painel/assistente.py`, `painel/migracao.py`, `painel/entregas.py`, `painel/perfil.py` (só para ligar os ganchos aos módulos reais, sem mudar telas) e em `docs/fase2/STATUS.md` (matriz). Os demais módulos já existem e passam nos seus testes: **não os reescreva**; se achar defeito neles, corrija o mínimo e registre no relatório (ou abra RFC em `docs/fase2/RFC-<assunto>.md`).

**Objetivo**: ligar os módulos da Onda 1 nos quatro fluxos de `PLANO.md` §3 e prová-los com o coletor simulado, em 200 processos, sem rede.

**Funções públicas** (cada uma devolve um dict `{"ok", "resumo", "avisos", "arquivos", ...}` e aceita `ao_progresso=None`; também têm CLI `python3 src/fluxos.py migrar|converter|inicial|atualizar ... --projeto SLUG`):

- `migrar(arquivos, projeto=None, *, confirmar=True, cliente_padrao=None)`: `leitores.ler` de cada arquivo → `consolidar.consolidar` (vinculados e duplicatas; grafias só como sugestão) → cria/atualiza o projeto, as fichas (`ficha.definir(..., origem do leitor)`), a `linha_de_base` (`andamentos_texto`, `ultimo_andamento`, `data_base`, `arquivo`) e marca os processos "só lista" como "novo — precisa de relatório inicial"; vários meses do mesmo `.xlsx` → `historico.reconstruir`; devolve o relatório de ambiguidades e `colunas_sem_destino`.
- `converter(arquivo, destino_modelo, mapeamento=None, projeto=None)`: `leitores.ler(..., mapeamento)` → escritor de destino (`docx_a` ou `xlsx_b`) a partir do modelo padrão; coluna sem destino vai para a aba "Campos não migrados"; nada se perde em silêncio.
- `inicial(projeto, *, profundidade, modo, entregas, cliente=None, coletor=None)`: enfileira (`fila.Fila`) os processos sem relatório anterior (ou todos), roda `fila.rodar_fila` com o `coletor` (real ou `ColetorSimulado`); em cada resultado, `capa.aplicar`; grava movimentos e documentos como eventos (reaproveitando `coletor`, `traduzir`, `extrair` e `resumir` da Fase 1, e `ia.provedor` conforme perfil e consentimento); `sintese.momento_atual`, `ultimo_andamento`, `narrativa_inicial`; `julgamento.sugerir` e `aplicar` (só com eventos aprovados); pára na **revisão** (triagem) e, após aprovação, gera as entregas.
- `atualizar(projeto, arquivos=None, *, ...)`: opcionalmente lê o `.docx`/`.xlsx` enviado (processo novo? sumiu? divergência de texto desde `ultimo_texto_gravado` → avisos), coleta **só o que veio depois** da data-base de cada processo (`desde`), `sintese.narrativa_incremental`, revisão, e gera **versões novas** dos arquivos enviados (A e/ou B) e **regenera o outro** a partir da ficha; o `.html` não precisa ser enviado.
- `entregar(projeto, entregas, *, data_base)`: chama `escritores.docx_a.gravar`, `escritores.xlsx_b.gravar` e `escritores.dashboard.gravar`, depois `qualidade.verificar`, `qualidade.o_que_mudou` e `historico.gravar_retrato`; coloca tudo em `saida/` (a pasta do relatório ou a do perfil).

**Decisões de integração já tomadas** (siga e documente no cabeçalho do módulo):

1. Eventos seguem o fluxo da Fase 1: `coletado → extraido → rascunho → aprovado → relatado`. O resumo da síntese **não** devolve a `rascunho` um evento já aprovado; evento novo entra como rascunho.
2. Os escritores devolvem `textos_gravados`, `campos_gravados` e `valores_gravados`; o fluxo os guarda na ficha em `ultimo_texto_gravado` (e `ultimo_texto_gravado.campos`) e `ultimos_valores_gravados`. Documente as chaves no cabeçalho de `ficha.py` (aditivo). Sem isso a detecção de edição manual fica cega no segundo ciclo.
3. Momento atual: `ficha.definir("momento_atual", ..., "derivado"|"coletado")`; o qualificador já é separado por `ficha.definir`. Valor vindo da síntese por IA entra como `sugerido`. `ativo` é derivado do momento (`taxonomia.momento_ativo`).
4. Avisos `ignorados`, `numero_repetido`, `numero_em_dois_lugares`, `andamento_ja_presente`, `edicao_manual_sobrescrita`: aparecem na página de Entregas e na lista "conferir manualmente"; nenhum derruba o fluxo.
5. Campos de julgamento: só `sugerido`, e só depois da revisão; `humano` nunca é tocado.
6. IA: `ia.provedor(perfil, cliente)`; sem consentimento, só local. Grave `motor` e `profundidade` no evento e mostre o selo (`ia.selo`). `motor == "regra"` significa "sem IA".
7. Pastas e `perfil.json` conforme CONTRATOS §7; `painel/perfil.py` já edita o perfil.
8. Tudo é **retomável**: a fila persiste; interromper em qualquer ponto e rodar de novo não repete trabalho nem duplica andamento.
9. `movimentos.json`: cadastrar a tradução de "Homologado o acordo entre as partes" (hoje fica sem tradução e vira alerta no nível rápido). Ajuste o teste de cobertura de tradução do simulado (85% a 100%, exclusive) se necessário e justifique.

**Ligações do painel** (o WS-9 deixou ganchos): `assistente.FABRICA_DE_COLETOR`, `assistente.AO_COLETAR`, `entregas.gerar`, `migracao`. Troque os stubs por chamadas a `fluxos.*` e confirme, com `app.test_client()`, que os quatro fluxos andam do início ao fim com o `ColetorSimulado`. Também: liberar `/fluxo` e `/migracao` na exceção de primeiro uso de `painel/base.py::escolher_projeto` (hoje quem não tem relatório é mandado para `/novo`). Mantenha `tests/test_painel.py` verde (regrave o instantâneo só se a diferença for esperada, com `PAINEL_GRAVAR=1`, e justifique).

**Aceite**

- `tests/test_fluxos.py` (coletor simulado, 200 processos, 5 clientes, sem rede):
  - migrar `.docx` modelo A + `.xlsx` modelo B + lista bruta → fichas, linhas de base, vínculos, relatório de ambiguidades; reconstrução de série com 3 meses;
  - converter de modelo: `.xlsx` fora do padrão → modelo B; `.docx` → B e B → A, com "Campos não migrados";
  - inicial: três profundidades; entregas A, B e C abrem (python-docx, openpyxl, Playwright sem rede) e batem com um cálculo independente em Python;
  - atualizar: 3 ciclos seguidos sem duplicar andamento, sem perder campo `humano`, sem sobrescrever edição manual no texto; processo novo na carteira entra; interrupção e retomada em 5 pontos distintos sem repetir `coletado`;
  - IA: sem consentimento nada sai (provedor falso conta chamadas); com consentimento por cliente, só aquele cliente usa o externo;
  - falhas injetadas (captcha, segredo, timeout) viram "conferir manualmente" sem travar o resto;
  - `qualidade.verificar` e `o_que_mudou` rodam no fim; retrato mensal gravado.
- `tests/test_fluxos_painel.py`: os quatro fluxos pelo painel, incluindo o primeiro uso (sem relatório) e a página de Entregas.
- Suíte completa verde: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 -m unittest discover -s tests -p "test_*.py"`.
- `docs/fase2/STATUS.md` atualizado (matriz e pendências reais para o piloto).

---

## WS-15 — Teste de carga e regressão entre ciclos

**Depende de**: WS-14 integrado. **Dono de**: `tests/test_regressao_ciclos.py`, `tests/test_carga.py`, `docs/fase2/piloto.md`.

**Entregas**

- **Regressão**: 200 processos, 5 clientes, **3 ciclos mensais** consecutivos com o coletor simulado e mudanças injetadas entre ciclos (decisões, acordos, trânsito, processo novo, processo sumido, edição manual no `.docx` e na planilha). Compare as saídas de ciclo para ciclo: nada some, nada duplica, nada humano é sobrescrito, indicadores recalculados batem com Python independente, o retrato mensal é coerente e `o_que_mudou` bate com as mudanças injetadas.
- **Carga**: tempo de processamento (sem coleta) por etapa com 200 e com 1.000 processos fictícios; limites generosos e configuráveis; relatório de gargalos.
- **`docs/fase2/piloto.md`**: roteiro de piloto no Mac do usuário, em português simples, nesta ordem: preparar (instalar, acesso, 1 cliente pequeno); **M5** (migrar um relatório real, atualizar de verdade, conferir os arquivos no Word, Excel e Google com `conferencia-docx.md` e `conferencia-xlsx.md`, medir tempo por processo e cobertura por tribunal, validar o prompt de pedidos com 2 ou 3 petições, calibrar vocabulário e limiares); **M6** (carteira de cerca de 200 processos em lotes noturnos); critérios de "pode seguir"; e o que anotar (planilha de registro do piloto).

**Aceite**: testes verdes e determinísticos; o roteiro foi lido criticamente numa segunda passada (registre as correções no fim do arquivo).

---

## Fora do escopo da Onda 2 (Onda 3 / extras)

Alertas (processo parado, audiência e prazo próximos), agenda `.ics`, descoberta contínua pelo DJEN, PDF e rascunho de e-mail ao cliente (WS-12); abas de **quadros analíticos** no modelo padrão de planilha (`quadros.gerar` já existe, falta o escritor criar a aba); painel de pedidos das iniciais (exige o piloto do prompt); pacote v2 com Windows declarado "não testado". Os pilotos M5 e M6 dependem do Mac do usuário.
