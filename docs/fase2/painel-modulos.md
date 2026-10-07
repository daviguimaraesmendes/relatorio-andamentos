# Painel local: módulos por tela (item 0.4)

`src/revisao.py` é só o ponto de entrada (`python revisao.py`, os atalhos `Abrir painel.*`, porta 5072, bind em 127.0.0.1): cria o app, gera o `TOKEN`, chama o `registrar(app, TOKEN, cabecalho, token_ok)` de cada módulo e sobe o servidor. Cada tela vive em `src/painel/` (cadastro continua em `src/cadastro.py`). Nenhum caminho de URL, texto de tela ou arquivo de dados mudou.

## Mapa rota -> módulo

| Rota | Métodos | Módulo | Função |
| --- | --- | --- | --- |
| (antes de todo pedido) | | `painel/base.py` | `escolher_projeto`: relatório ativo pelo cookie; sem relatório, vai para `/novo` |
| `/p/<slug>` | GET | `painel/projetos.py` | `trocar` (aba de relatório) |
| `/novo` | GET, POST | `painel/projetos.py` | `novo` |
| `/` | GET | `painel/revisao_eventos.py` | `inicio` (Revisar andamentos) |
| `/evento` | POST | `painel/revisao_eventos.py` | `evento` (aprovar, salvar, descartar) |
| `/atualizar` | GET | `painel/atualizar.py` | `atualizar` |
| `/tarefa` | POST | `painel/atualizar.py` | `tarefa` (inicia rodada, conferência, teste de acesso) |
| `/interromper` | POST | `painel/atualizar.py` | `interromper` |
| `/planilha` | GET, POST | `painel/planilha_mes.py` | `planilha_mes` |
| `/mostrar` | POST | `painel/planilha_mes.py` | `mostrar` (abre no Finder/Explorer) |
| `/relatorio` | GET | `painel/relatorio_html.py` | `ver_relatorio` (planilha ou HTML gerado) |
| `/config` | GET, POST | `painel/configuracao.py` | `configuracao` |
| `/documento` | GET | `painel/documentos.py` | `documento` |
| `/print` | GET | `painel/documentos.py` | `ver_print` |
| `/acesso` | GET, POST | `painel/acesso_tela.py` | `pagina_acesso` |
| `/cadastro`, `/cadastro/cliente`, `/cadastro/importar`, `/cadastro/processo`, `/cadastro/completar`, `/cadastro/descobrir`, `/cadastro/pendente` | | `cadastro.py` | inalterado |

Peças comuns em `painel/base.py`: `ESTILO`, `SUBABAS`, `cabecalho`, `_msg`, `_ir`, `criar_token_ok`, `_dentro`, `_tarefa_rodando`, e o estado `TAREFA` (tarefa em andamento) e `WINDOWS`. A barra de abas e o aviso de acesso saem de `cabecalho`; para mexer neles, só `base.py`.

Nomes reservados no `CONTRATOS.md` (seção 12) para as telas novas: `assistente`, `migracao`, `entregas`, `perfil` (WS-9), `revisao_lote`, `processo` (WS-10), `pedidos` (WS-16), `ia` (WS-18). WS-10 também é dono de `revisao_eventos.py` (a tela de revisão atual).

## Como acrescentar uma tela nova

1. Crie `src/painel/<tela>.py` com `def registrar(app, TOKEN, cabecalho, token_ok):` (modelo: `painel/configuracao.py` ou `cadastro.py`).
2. Dentro dele, declare `oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"` e use `@app.get/@app.post("/<prefixo>/...")`; todo POST começa com `token_ok()` e todo formulário leva `{oculto}`.
3. Monte a página com `cabecalho("<chave da aba>")` e `_msg()`; redirecione com `_ir(caminho, mensagem)`; confira caminhos de arquivo com `_dentro(base, caminho)` (todos de `painel.base`).
4. Registre o módulo em `src/revisao.py`: acrescente o import e inclua o módulo na tupla do laço `for tela in (...)`. Só essa linha do `revisao.py` muda. Para aba nova na barra, acrescente em `SUBABAS` (`painel/base.py`).
5. Teste: copie o padrão de `tests/test_painel.py` (cliente `app.test_client()` num relatório temporário) num arquivo de teste seu e, se a tela alterar uma existente, regrave o instantâneo com `PAINEL_GRAVAR=1 python3 -m unittest tests/test_painel.py`.

## Teste de fumaça

`tests/test_painel.py` faz GET em todas as rotas de leitura e POSTs inofensivos (com token, sem rede, sem subir processo) e compara cada resposta (status, redirecionamento, hash do HTML normalizado, estado dos dados gravados, comandos que seriam executados) com `tests/fixtures/painel_instantaneo.json`, gerado antes do fatiamento. `PAINEL_DUMP=<pasta>` grava o HTML normalizado de cada passo, para comparar à mão.
