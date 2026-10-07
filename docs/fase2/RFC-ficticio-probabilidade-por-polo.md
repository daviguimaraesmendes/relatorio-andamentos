# RFC: `tests/ficticio.py` inverte a probabilidade por polo, contra a decisão D6

Autor: WS-11 (achado ao rodar o verificador na carteira fictícia). Situação: **proposta**; o arquivo é do WS-13.

## Problema

`tests/ficticio.py::_ficha_sintetica` lança a probabilidade (campo de julgamento `humano`, ~30% das fichas) com
inversão por polo: para `polo == "ativo"`, improcedência vira "Provável" e procedência vira "Remota". A decisão
D6 (PLANO 7.2, WORKSTREAMS WS-17) é o contrário: a probabilidade é a do **resultado**, sem inversão por polo
(Procedente/Parcial = Provável; Improcedente = Remota).

## Efeito

- `qualidade.verificar` marca esses casos como `probabilidade_x_resultado` (gravidade `info`): ~10 em 200.
- O teste retroativo do WS-17 (`julgamento.concordancia` na carteira fictícia) vai medir divergência artificial
  nos processos de cliente autor, que é culpa do gerador e não da regra.
- O mesmo gerador lança economia em processo de cliente autor (`valor_economizado = causa - estimado`), que o
  verificador aponta como `economia_inflada` (~11 em 200). Isso é um achado legítimo (o PLANO manda deixar
  cliente autor fora do indicador), mas torna a carteira "limpa" não-limpa para esse tipo de verificação.

## Proposta

No gerador, usar a mesma probabilidade para os dois polos e não lançar `valor_economizado` quando
`polo == "ativo"`. Se o WS-13 preferir manter o gerador como está, os testes do WS-17 devem descontar o polo
ativo. Nada em `src/` depende disso.
