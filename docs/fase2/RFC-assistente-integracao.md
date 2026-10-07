# RFC: pontos de integração do assistente dos fluxos (WS-9)

Autor: WS-9. Destinatário: coordenador. Nenhum item abaixo bloqueia o WS-9; cada um tem uma suposição já implementada e testada com stubs.

## 1. Primeiro uso sem relatório nenhum (`painel/base.py`)

**Problema.** `base.escolher_projeto` manda para `/novo` toda rota que não está na lista `("/novo", "/acesso", "/tarefa", "/atualizar", "/interromper")` enquanto não existe relatório. Quem abre o programa pela primeira vez e quer **Importar relatórios existentes** (que cria o relatório) precisa antes criar um relatório vazio em `/novo`.

**Proposta.** Incluir `/fluxo` e `/migracao` na exceção (ou testar `request.path.startswith(("/fluxo", "/migracao"))`). Uma linha em `base.py`; o WS-9 só pôde acrescentar subabas lá.

**Impacto.** Sem a mudança tudo funciona, só com um passo a mais (criar o relatório vazio). As telas do WS-9 já tratam `comum.PROJETO is None` (não quebram; dizem para importar ou criar).

## 2. Instantâneo do painel (`tests/fixtures/painel_instantaneo.json`)

As subabas novas (Assistente, Entregas, Perfil) aparecem em **todas** as páginas e as rotas novas entram na chave `rotas`; o WS-9 regravou o instantâneo (confirmado: o HTML de cada tela, sem as três âncoras novas, tem o mesmo hash de antes). Os WS-10, WS-16 e WS-18 vão mexer no mesmo arquivo (rotas e, se acrescentarem subaba, o HTML). **Proposta:** o coordenador regrava uma vez depois dos merges (`PAINEL_GRAVAR=1 python3 -m unittest tests/test_painel.py`) e descarta as versões dos branches.

## 3. `revisao.py`

Acrescentei os quatro módulos ao import e à tupla do laço `for tela in (...)` (as duas únicas linhas tocadas, como manda `painel-modulos.md`). Conflito certo com WS-10/16/18 (mesma linha): resolver somando os nomes.

## 4. Fila (WS-3)

Suposições feitas sobre `fila.py` (todas isoladas em `painel/entregas.py::abrir_fila` e `painel/assistente.py`):

- `fila.Fila(slug)` recebe o **slug** do relatório (CONTRATOS §6 diz só "projeto").
- `Fila.itens() -> [{"numero", "estado", "erro": {"codigo", "mensagem"}}]` (não está no contrato): a tela "Conferir manualmente" lista os processos em `manual`/`erro` com o motivo. Sem `itens()`, a lista fica vazia.
- `Fila.definir_janela(inicio, fim)` ("HH:MM") para a janela do modo contínuo (também não está no contrato). Sem o método, a janela fica só no perfil (`perfil["janela_coleta"]`).
- `fila.rodar_fila(fila, coletor, ao_progresso=None)` pode **voltar** com pendentes (fora da janela) ou **bloquear**: nos dois casos o painel funciona (no modo contínuo ele espera e chama de novo).
- `fila.ColetorReal()` sem argumentos; só é criado se o acesso (certificado/autenticador) estiver configurado.
- `fila.cobertura(slug)` é usada na tela de progresso se existir.

## 5. Escritores (WS-6/7/8) e o estado

- `estado["parametros"]["campos_nao_migrados"] = [{"coluna", "amostra"}]` é a convenção que o WS-9 usa em "Migrar de modelo" para a aba "Campos não migrados" do WS-7. Combinar com o WS-7.
- O painel (C) é chamado como `dashboard.gravar(xlsx_gerado, destino, perfil)`; a planilha é gerada primeiro e usada como entrada.
- Modelo A sai **um .docx por cliente** (estado com as fichas e os eventos daquele cliente); o `.docx` enviado só serve de molde quando há um único cliente.
- O WS-9 grava `ficha["ultimo_texto_gravado"]` a partir de `Resultado["textos_gravados"]` ao gerar entregas (a seção 5 do contrato atribui isso ao coordenador/fluxos; se o WS-14 assumir, basta remover `_guardar_textos`).

## 6. Leitores (WS-2)

- `leitores.ler(caminho, formato, mapeamento={coluna: campo})` e `RelatorioLido["mapeamento"]` aceitos nos três formatos descritos em `painel/migracao.py::normalizar_mapeamento`. Destinos especiais assumidos: `"numero"` e `"andamentos"`.
- Os avisos são agrupados na conferência pelo **trecho do `codigo`** (`invalido`/`dv_`, `duplic`, `vincul`/`mesma_acao`/`reajuiz`, `grafia`/`nome_parecido`, `ambig`/`vocabulario`/`data_invalida`/`formula`/`campo_`); código fora disso cai em "Outros avisos". Para a escolha de grafia o aviso precisa trazer `candidatos` (lista de nomes). Combinar os códigos reais com WS-1/WS-2.

## 7. Fora do WS-9

- Reconstrução da série histórica na importação de vários meses (`historico.reconstruir`) não foi ligada: depende do WS-11.
- O que a coleta faz com movimentos e documentos (eventos, síntese, revisão) é do WS-14: o WS-9 só grava a capa (origem `coletado`) e oferece o ponto `assistente.AO_COLETAR` (lista de funções `g(slug, processo, resultado)`).
- Troca de relatório (aba) durante uma coleta: o estado do painel é global (`comum.PROJETO`); a thread de coleta grava a capa pelo caminho do relatório que a iniciou, mas a `Fila` real pode depender do relatório ativo. O WS-9 não impede a troca de aba.
