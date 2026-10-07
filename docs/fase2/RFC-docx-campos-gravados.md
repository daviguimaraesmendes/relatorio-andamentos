# RFC: o que o escritor `.docx` devolve e guarda entre ciclos (WS-6)

Status: proposta do WS-6 ao coordenador. O contrato (`CONTRATOS.md`, seções 4 e 5) **não** foi alterado; o código já funciona com estas suposições e todas são aditivas.

## Problema

O aviso `edicao_manual_sobrescrita` (CONTRATOS 5) só é possível se o escritor souber o **último valor que o próprio sistema gravou** em cada campo mecânico: "momento atual", "último andamento", data do fecho e Data-Base. O contrato já prevê guardar o **texto** de andamentos (`textos_gravados` -> `ficha["ultimo_texto_gravado"]`), o que cobre o fecho e a detecção de edição no texto. Faltam o momento atual e o último andamento **como estão no arquivo**. Sem eles, o aviso só dispara quando o título e o quadro-resumo já divergiam entre si.

## Proposta

1. `Resultado["campos_gravados"] = {numero: {"momento_atual": "...", "ultimo_andamento": "DD/MM/AAAA"}}` (valores como ficaram no arquivo, com o qualificador entre parênteses, se houver). O coordenador guarda em `ficha["ultimo_texto_gravado"]["campos"]`, junto com `data_base`, `texto` e `arquivo` (já previstos).
2. No ciclo seguinte, `escritores.docx_a.gravar` lê sozinha `ficha["ultimo_texto_gravado"]` (`texto` -> `textos_conhecidos`, `campos` -> `campos_conhecidos`, `data_base` -> `data_base_conhecida`); quem preferir passa as opções explicitamente. Sem esses dados, tudo funciona; só o aviso fica menos sensível.
3. Extras aditivos do `Resultado`, já implementados: `gravado` (bool; `False` quando o molde é ilegível, caso em que há um aviso `molde_ilegivel` de nível `erro` e nada é gravado) e `nao_encontrados` (números pedidos que não estão no arquivo e não vieram como processo novo).

## Impacto

- `fluxos.py` (coordenador): gravar `campos_gravados` ao lado de `textos_gravados` em cada ficha.
- WS-7 (`xlsx_b`): nenhum; pode devolver o mesmo campo se quiser a mesma proteção.
- Nenhum teste existente muda.

## Suposição documentada

`Resultado["textos_gravados"]` e `["campos_gravados"]` usam como chave o **número da ficha** (principal) em `gravar`, mesmo que o título do bloco comece por outro número do mesmo processo.
