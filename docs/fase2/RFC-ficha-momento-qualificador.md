# RFC: momento atual com qualificador entre parênteses não cabe na ficha

Autor: WS-11. Situação: **proposta** para o WS-1/coordenador (`ficha.py`, `taxonomia.py`).

## Problema

Os modelos de referência escrevem o momento atual com qualificador, por exemplo
"CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)" e "PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)" (WORKSTREAMS, fatos
do modelo A). Hoje `ficha.definir(f, "momento_atual", ...)` **recusa** esse texto (`_normalizar_valor` só aceita
valor exato ou reconhecido por `taxonomia.normalizar`), e `taxonomia.momento_ativo` devolve `None` para ele. O
leitor do modelo A (WS-2) terá de descartar o qualificador (perdendo informação) ou gravar fora do campo.

## Como o WS-11 lida com isso

`qualidade.py` aceita o qualificador: compara só o trecho antes do parêntese (`qualidade.momento_ativo`,
`_base_do_momento`). Se a ficha vier a guardar o qualificador, o verificador, o retrato e os quadros já funcionam.

## Proposta

Guardar o momento com qualificador intacto em `momento_atual` (valor canônico + `" (" + qualificador + ")"`),
fazendo `ficha.definir` e `taxonomia.momento_ativo`/`categoria_do_momento` olharem o trecho antes do parêntese.
Alternativa: campo novo `momento_qualificador`. Decisão é do coordenador (mexe em `ficha.py`).
