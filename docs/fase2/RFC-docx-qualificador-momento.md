# RFC: onde fica o qualificador do momento atual e o estilo do texto (WS-6)

Status: proposta do WS-6 ao coordenador e ao WS-1. O contrato **não** foi alterado.

## Problema

1. O modelo A escreve o momento atual com um qualificador opcional entre parênteses ("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)", "PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)"). A ficha v2 tem só `momento_atual` (valor do vocabulário); o WS-1 vai dar `normalizar_momento(texto) -> (canônico, qualificador)` mas o contrato não diz **onde a ficha guarda o qualificador**.
2. `perfil["estilo_texto"]` é `"a | b"` (CONTRATOS 7), mas o escritor entrega dois estilos: o do modelo de referência e o "compacto".

## Proposta e suposição adotada

1. O escritor aceita o qualificador de **três** lugares, nesta ordem: `ficha["campos"]["momento_qualificador"]["valor"]`, `ficha["momento_qualificador"]` (plano) e `ficha["campos"]["momento_atual"]["qualificador"]`; se nenhum existir, tira os parênteses do próprio valor de `momento_atual`. **Recomendação**: o WS-1/coordenador adotar o campo `momento_qualificador` (texto livre, grupo `situacao`, sem vocabulário) em `ficha.CAMPOS`; é o caminho que o escritor lê primeiro. Até lá, nada quebra.
2. Regra de gravação: se o canônico no arquivo é igual ao da ficha e a ficha **não** traz qualificador, o parêntese que o advogado escreveu **fica**; se a ficha traz um qualificador diferente, ele substitui; se o canônico mudou, o qualificador antigo cai (não vale para o momento novo).
3. Estilo: `perfil["estilo_texto"]` `a` -> estilo `a`; `b` -> `compacto` (também aceita `compacto`). Opção explícita `estilo=` vence o perfil. Confirmar o mapeamento (ou renomear os valores do perfil).

## Impacto

- WS-1: definir o campo (ou confirmar outro lugar) e, ao migrar um relatório, separar o qualificador do canônico.
- WS-2 (`docx_a` leitor): `ler_estrutura` já devolve `momento` (canônico), `qualificador` e `momento_atual` (inteiro, como escrito).
- WS-9 (tela de perfil): oferecer os dois estilos de texto.
