# RFC: origem do "momento atual" e das colunas mecânicas nos fluxos (WS-14)

Autor: WS-14. Status: proposta (o código já segue a "Proposta"; basta o coordenador confirmar ou pedir a alternativa).

## Problema

A decisão 3 da Onda 2 diz que o momento atual entra em `ficha.definir("momento_atual", ..., "derivado"|"coletado")`.
Mas `ficha.definir` respeita a prioridade `humano 5 > coletado 4 > migrado 3 > derivado 2 > sugerido 1`. Um relatório
migrado grava o momento com origem `migrado` (3). Se a regra gravasse como `derivado` (2), **o momento do relatório antigo
nunca seria atualizado**: o ciclo seguinte coletaria "Trânsito em julgado" e a ficha continuaria dizendo "Aguardando
sentença". O mesmo vale para `situacao`, `fase` e `ultimo_andamento`, que o `docx_a` e o `xlsx_b` tratam como campos
mecânicos (recalculados a cada ciclo).

## Proposta (implementada em `fluxos.aplicar_sintese`)

- Momento por **regra** (movimento do tribunal + evidência citada): origem `coletado` (4). Vence o `migrado`; nunca vence
  `humano`.
- Momento por **IA** (vocabulário fechado, trecho de origem conferido): origem `sugerido` (1), como manda a decisão 3. Não
  substitui `migrado`, `derivado` nem `coletado`: fica como sugestão para a revisão.
- Com momento por regra: `ativo` (campo plano da ficha), `situacao` e `fase` saem do momento
  (`taxonomia.momento_ativo` / `categoria_do_momento`) com origem `coletado`; `ultimo_andamento` sai de
  `sintese.ultimo_andamento`, também `coletado`.
- Campos `humano` nunca são tocados. Quem edita à mão o momento no `.docx` ou na planilha tem o valor trocado no ciclo
  seguinte **com o aviso `edicao_manual_sobrescrita`** (contrato dos escritores); para fixar um valor de verdade, a pessoa o
  define na ficha (origem `humano`).

## Alternativa

Tratar o momento como `derivado` (2) e deixar o valor migrado valer até uma pessoa mexer. Evita sobrescrever o que o
escritório digitou no relatório antigo, mas deixa o relatório desatualizado justamente no campo que mais muda. Se o usuário
preferir, basta trocar `"coletado"` por `"derivado"` em `aplicar_sintese` e aceitar que o primeiro ciclo não atualiza
processos migrados.

## Impacto

- `fluxos.py` apenas. Nenhuma mudança em `ficha.py`, `sintese.py` ou nos escritores.
- Piloto M5: conferir, na primeira atualização real de um relatório migrado, quantos momentos mudam e se os novos estão
  certos (calibra as regras de `taxonomia.REGRAS_DE_MOMENTO`).

## Outra decisão que o WS-14 tomou e vale registrar

`ficha["ultimo_texto_gravado"]` guarda um registro **por entrega** (`por_entrega: {docx_a, xlsx_b}`), porque o texto do
`.docx` e o da planilha têm formatos diferentes e um único registro faria a detecção de edição manual disparar à toa. As
chaves de cima espelham a gravação mais recente (contrato original preservado). Ver o cabeçalho de `ficha.py`.
