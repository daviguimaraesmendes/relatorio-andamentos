# RFC: chave opcional `consolidacao` na ficha

Autor: WS-1. Status: proposta (a chave já é gravada por `consolidar.py`; contrato não alterado).

## Problema

`consolidar.consolidar` funde duplicatas, reúne linhas vinculadas e leva rótulos ao vocabulário. A regra é "nunca perder
campo humano": o que não pode continuar no campo precisa ficar registrado em algum lugar. `ficha.py` não tem esse lugar.

## Proposta

Documentar em `CONTRATOS.md`, seção 1, uma chave **opcional e aditiva** no nível da ficha, `consolidacao`
(dicionário; qualquer subchave pode faltar; nenhum consumidor é obrigado a lê-la):

| Subchave | Conteúdo |
| --- | --- |
| `numeros_originais` | grafias antigas do número (antes da máscara CNJ) |
| `conflitos` | `{campo, valor_mantido, valor_descartado, origem_descartada, em_descartado}` de duplicatas fundidas |
| `absorvidas` | `{numero, tipo, ficha}`: retrato completo das linhas reunidas ao principal (agravo, apenso, mesma ação) |
| `originais` | `{campo: texto original}` de rótulos ou nomes padronizados |
| `linhas_de_base_descartadas`, `textos_gravados_descartados` | versões mais antigas, quando duas linhas traziam linha de base diferente |

`consolidar.campos_humanos_perdidos(antes, depois)` usa essas chaves para provar que nenhum campo `humano` sumiu
(útil também para o teste de regressão da WS-15).

## Impacto

- Nenhum campo existente muda; a chave só aparece depois de uma consolidação.
- Escritores e dashboards ignoram `consolidacao` (nada do que está nela sai para o cliente).
- `qualidade.verificar` (WS-11) pode usar `absorvidas`/`conflitos` para explicar ao usuário o que foi reunido.
