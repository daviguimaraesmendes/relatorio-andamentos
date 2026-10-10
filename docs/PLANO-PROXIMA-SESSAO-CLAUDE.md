# Plano da próxima sessão: testar o Claude (Sonnet x Haiku) e atualizar um relatório real

Escrito em 2026-10-09, ao fim da sessão que entregou a **2.0.0-beta7** (login do PDPJ, 1º grau, 2º grau e TST pelo PJe,
"Configurar tudo", capa pelo PJe). `main` = `2b867d5` na hora em que isto foi escrito. Dono do projeto: Davi.

## 1. Objetivo da sessão

1. **Decidir, com dados, qual modelo do Claude e qual esforço usar** para resumir os documentos dos processos:
   candidatos **Sonnet 5.5 médio** (padrão provável) e **Haiku 5.5 médio** (mais barato; talvez bastante para os documentos simples).
2. **Atualizar um relatório REAL** do escritório usando o Claude, de ponta a ponta, com revisão humana.

Hipótese de partida (opinião, sem benchmark): Sonnet médio basta; Haiku médio pode bastar para certidões, intimações,
juntadas e despachos, mas é arriscado em sentenças e acórdãos (prazo, valor, resultado). Opus e esforço alto/xhigh/max não se justificam aqui.

## 2. Antes de qualquer coisa (conferir, nesta ordem)

| # | Conferir | Como |
| --- | --- | --- |
| 1 | Estado do repositório | `git fetch && git status -sb`; `git log --oneline -3`; `cat VERSAO` (esperado 2.0.0-beta7 ou mais novo). Mesclar o que outras sessões empurraram para `claude/gallant-pasteur-etzpu5` antes de mexer. |
| 2 | Ambiente de testes | O ambiente do Claude não traz o Flask: criar venv em pasta temporária (`python3 -m venv ... && pip install -r requirements.txt`). Rodar `python -m unittest discover -s tests -p "test_*.py"`: devem falhar só os 2 de navegador (`test_autos`, `test_dashboard`: Playwright). |
| 3 | Painel real | Está em `http://127.0.0.1:5072` (`src/abrir_painel.py`; reinicia sozinho se a versão mudar e não houver coleta). Verificar com `curl /versao.json`. |
| 4 | **Claude Code com login ativo** | O Claude Code que consegui usar nesta sessão estava SEM login. No painel: tela IA -> cadastrar o provedor "Claude pelo Claude Code" -> **Testar**. Se pedir login: abrir o Claude Code (`/login`). Sem isso, nada do plano roda. |
| 5 | Credenciais do PDPJ | `acesso.situacao_pdpj()` deve dar tudo `True`; `pdpj.trava()` deve ser `None`. Se houver trava: conferir os dados e só então liberar (tela Acesso/Configurar tudo). **REGRA DURA: o login do PDPJ roda UMA vez; se falhar, não repetir.** |
| 6 | IA local | NÃO está instalada neste Mac (Ollama/modelo). Sem provedor externo, os documentos entram na revisão "sem resumo automático". Para este plano o resumo vem do Claude; a IA local é opcional (botão "Instalar IA local" em `/ia`). |

## 3. Parte A: teste comparativo Sonnet médio x Haiku médio

### 3.1 O que comparar

O ponto de entrada é `src/resumir.py::resumir_com_provedor(provedor, texto, tipo, quem, frase, ctx, cliente)`, que devolve
`(resultado, alertas, motor)`. O `resultado` segue `ESQUEMA`: `conteudo` (resumo em gerúndio, até 80 palavras), `trecho_origem`,
`prazo`, `audiencia`, `efeito` (enum `EFEITOS`). Os `alertas` vêm de `resumir.conferir` (trecho que não confere com o documento,
prazo/audiência que não aparecem no texto, resumo curto demais, etc.).

### 3.2 Montar o lote de teste (30 a 40 documentos)

- Fonte: os PDFs/textos já coletados. Se for preciso mais, coletar de novo na pasta de teste (ver 3.5) com profundidade "completo"
  nos dois processos de teste do Davi (um só de 1º grau; outro com 1º grau, 2º grau e TST; os números estão na memória local do
  Claude, `relatorio-andamentos-fluxo-git.md`, e NÃO neste arquivo), que somam 40 + 45 + 20 + 11 documentos nos autos. Textos: `extrair.extrair_arquivo(caminho)` (e `extrair.limpar`).
- Estratificar: ~10 certidões/intimações/juntadas, ~10 petições (inicial, contestação, recursos), ~10 decisões/despachos,
  ~10 sentenças/acórdãos/atas (os de maior risco). Registrar o tipo de cada um.
- Tirar o nome do cliente do contexto sensível: usar pseudonimização ligada (padrão) e o cliente fictício do teste.

### 3.3 Provedores do teste

Cadastrar na tela IA (tipo "Claude pelo Claude Code"), sem chave e sem endereço:

| Nome | Modelo | Esforço |
| --- | --- | --- |
| `claude-sonnet-medio` | `sonnet` | `medium` |
| `claude-haiku-medio` | `haiku` | `medium` |
| (referência, opcional) `claude-sonnet-alto` | `sonnet` | `high` |

O cadastro aceita a opção `esforco` (`ia.cadastrar(..., esforco="medium")`); a tela IA ainda não tem o campo "esforço": se
precisar, acrescentar (campo opcional no formulário, em `src/painel/ia.py`) ou cadastrar por `ia.cadastrar` num script.
Alias de modelo e nomes completos: `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-opus-5-5`.

### 3.4 O script de comparação (a escrever na sessão)

`tools/comparar_modelos.py` (ou `src/ia_comparar.py`; pasta nova só para ferramenta de apoio, sem entrar no pacote do usuário):

1. Lê a lista de documentos (caminho, tipo, quem apresentou, frase de abertura, contexto) a partir de `eventos.json` do
   relatório de teste (campos `arquivo`, `tipo`, `descricao`, `data`) e extrai o texto com `extrair`.
2. Para cada provedor e cada documento, chama `resumir_com_provedor` **uma vez** (sem retentativa além da que a própria função já faz),
   com o consentimento do teste (`perfil` com `consentimento_externo: True` só para o cliente de teste, `pseudonimizar: True`).
   Registrar: JSON devolvido, `alertas`, `motor`, tempo, e (se o `claude -p --output-format json` informar) uso/custo.
3. Grava um relatório (CSV + um HTML simples) com uma linha por documento e colunas por modelo: `efeito`, `prazo`, `audiencia`,
   nº de palavras do `conteudo`, alertas, falha de JSON; e a **concordância** entre os modelos campo a campo.
4. Respeita limites: uma chamada por vez, pausa curta entre chamadas, parar no primeiro erro de login/limite da assinatura
   (`ia_login_necessario`, `ia_limite_assinatura`) sem insistir.

### 3.5 Onde rodar

Num ambiente isolado, como foi feito nesta sessão: `RELATORIO_DATA`, `RELATORIO_CARTEIRA`, `RELATORIO_CLIENTES` e
`RELATORIO_PROJETOS` apontando para uma pasta temporária (veja `painel_teste.py`/`e2e_coleta.py` descritos em 7), usando o
cofre real (credenciais). Nunca gravar nada na pasta `projetos/` real.

### 3.6 Como julgar (decidir ANTES de olhar os resultados)

- **Verdade de referência**: Davi (ou o revisor) confere por amostra 15 a 20 documentos, em especial sentenças, acórdãos e atas;
  e usar Sonnet alto como "árbitro" auxiliar nos desacordos.
- **Métricas** (por modelo e por categoria de documento): (1) `efeito` igual ao da referência; (2) `prazo` e `audiencia`
  corretos (a data existe no documento e é a do ato); (3) taxa de resposta inutilizável (JSON inválido/`ValueError`);
  (4) alertas "trecho não confere"; (5) palavras de `conteudo` e aderência ao estilo do escritório (gerúndio); (6) tempo e consumo da cota.
- **Regra de decisão sugerida**: Haiku só entra numa categoria se: 0 erro de prazo/valor/audiência na amostra, `efeito` igual ao
  do Sonnet em pelo menos 95%, e taxa de falha de JSON <= a do Sonnet. Sentenças, acórdãos e documentos com valor em dinheiro:
  Sonnet. Se o Haiku não passar em nenhuma categoria, Sonnet médio para tudo.
- Saída esperada: tabela final com **modelo e esforço por tipo de documento** e a recomendação de configuração
  (um provedor padrão; opcionalmente uma regra "documento simples -> Haiku", que ainda NÃO existe no código: hoje o relatório usa
  um provedor só, definido em `perfil["ia"]["provedor"]`; se a decisão for mista, implementar o roteamento por tipo
  em `resumir_com_provedor`/`sintese.py`).

## 4. Parte B: atualizar um relatório real com o Claude

Só depois da Parte A (ou, se Davi preferir, com o Sonnet médio já escolhido).

1. **Escolher o relatório e o cliente** (Davi). Conferir que o cliente tem consentimento e que a pseudonimização está ligada
   (`/ia`, seção "O que este relatório usa"; `ia.selo_para(perfil, cliente)` deve mostrar "externa: <provedor>").
2. **Cópia de segurança** da pasta do relatório antes (`projetos/<slug>/`) e do arquivo-base (Word/Excel) que será atualizado.
3. Assistente -> **Atualizar relatório** (`/fluxo/atualizar`): enviar o relatório mais recente (xlsx/docx), conferir data-base,
   processos novos e sumidos, **Preparar a coleta**, confirmar. Coleta: Justiça do Trabalho pelo PDPJ (1º grau, 2º grau e TST),
   Estadual/Federal pelo jus.br com certificado (se houver, PJe Office aberto; ainda NÃO testado de ponta a ponta nesta linha).
4. **Revisar**: vermelhos e amarelos um a um (atalhos J/K/A/D/E); verdes em lote (a amostra de 10% fica para conferir).
   Conferir cada resumo contra o documento/print. O programa só prepara rascunho; nada vai a cliente sem aprovação.
5. **Entregas**: gerar docx/xlsx/painel; rodar "Verificar qualidade" e olhar "Conferir manualmente".
6. Comparar com o relatório anterior e com o que Davi sabe dos processos; anotar erros do Claude por categoria (alimenta a decisão da Parte A).
7. Registrar o resultado (o que o Claude acertou/errou, custo em cota, tempo) em `docs/fase2/STATUS.md` ou num novo `docs/RESULTADO-TESTE-CLAUDE.md`.

## 5. Regras que valem em toda a sessão

- **Login do PDPJ: uma tentativa; falhou, parou** (trava em `projetos/.pdpj_trava.json`, `src/pdpj.py`). Nada de laço de repetição.
- Credenciais só no cofre do sistema; nunca em arquivo, log, tela, URL ou commit. Testes usam cofre em memória (`tests/isolamento.py`).
- Fluxo git: tudo vai ao GitHub (branch `claude/gallant-pasteur-etzpu5`); promover a `main` quando Davi validar. Davi pediu
  que a versão atual fique sempre na `main`. Tag/release (`v2.0.0-beta7`) dispara o instalador do Windows: só se ele pedir.
- Commits com `Co-Authored-By: Claude ... <noreply@anthropic.com>`; autor dos commits: o próprio Davi (nome e e-mail já configurados nos commits anteriores: `git log -1 --format=%an,%ae`).
- Confidencialidade: `tests/test_confidencialidade.py` recusa CPF, nome de empresa real e atribuições `SENHA = "..."` em arquivos
  versionados; gerar valores fictícios por cálculo (ver `tests/test_acesso_pdpj.py`).
- Dados de clientes: nada de processo real nos arquivos do repositório; pastas de teste ficam no scratchpad e podem conter PDFs
  reais (apagar quando Davi disser).

## 6. Pendências e ideias (fila, em ordem sugerida)

1. **Teste real do caminho jus.br com certificado** (Estadual e Federal): ainda não exercitado de ponta a ponta depois do "login só quando precisa".
2. **Campo "esforço" na tela IA** e, conforme a decisão da Parte A, **roteamento de modelo por tipo de documento**.
3. **Instalar a IA local** (opcional) e medir contra o Claude, para clientes que não podem enviar texto à Anthropic.
4. Mostrar na tela "Configurar tudo" o resultado do último teste de login (hoje só o log da tarefa atual).
5. Processos fora do Acervo Geral da conta logada caem na consulta pública (com captcha): decidir o tratamento (aviso claro + fila "conferir à mão").
6. Outros sistemas além de 1º grau/2º grau/TST (STF etc.): não mapeados.
7. Windows: o instalador veio da outra linha de trabalho; o PDPJ e o login "só quando precisa" não foram testados lá.
8. Release/tag `v2.0.0-beta7` e notas no GitHub (só com ordem do Davi).
9. (feito em 2026-10-09) A pasta de teste com PDFs reais foi apagada a pedido do Davi.

## 7. Como a sessão anterior testou (para repetir)

- **Painel isolado de teste**: script que seta `RELATORIO_DATA`, `RELATORIO_CARTEIRA`, `RELATORIO_CLIENTES`, `RELATORIO_PROJETOS`
  para uma pasta temporária, importa `revisao` e roda `revisao.app.run(port=5095, threaded=True)` com o venv do projeto
  (`.venv/bin/python`, tem Playwright e as credenciais do cofre real).
- **Coleta real de ponta a ponta sem painel**: `fila.ColetorReal(historico=N)` + `c.coletar({"numero":..., "cliente":...}, "padrao", None)`,
  com `coletor.garantir_login` trocado por uma função que levanta erro (evita cair no certificado se um processo não estiver no acervo).
- O navegador embutido de teste não mostra `confirm()` nem anexa arquivos: aceitar `window.confirm = () => true` por script e enviar
  arquivos pelo mesmo formulário com `curl -F`.
- Os números dos processos reais de teste (do próprio Davi) ficam só na memória local do Claude (fora do repositório) e não devem
  ser copiados para testes, documentos ou commits.
