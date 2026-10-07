# RFC: campos aditivos no retrato mensal (CONTRATOS §9)

Autor: WS-11. Situação: **suposição já implementada**, sem quebra do contrato; o coordenador decide se a adota.

## Problema

O retrato do contrato §9 não traz o cliente de cada processo. Sem ele, "o que mudou" **por cliente** não funciona
quando o estado anterior vem do retrato (o caso normal: o `.xlsx` antigo pode nem existir mais), e o dashboard
não consegue filtrar a série por cliente. O contrato também não tem versão do formato nem o indicador de
economia já com as ressalvas (acordo sem valor, acordo de terceiro, exclusão da lide, cliente autor).

## Proposta (já implementada em `src/historico.py`)

Só acréscimos; nenhum campo existente muda de nome, tipo ou significado.

- raiz: `"versao": 1`;
- `por_processo[]`: `"cliente": "..."`;
- `totais`: `"valor_economizado_confiavel": "0.00"` (o indicador recomendado de `quadros.py`: só encerrado, sem
  ressalva e com desfecho pecuniário definido). `totais.valor_economizado` continua sendo a soma simples do que
  está lançado.

## Impacto

Quem lê o retrato por chave não percebe nada (WS-8: dashboard em modo `embutido`). Quem validar o JSON com
esquema fechado precisa aceitar as três chaves novas. Nenhum teste existente depende do formato do retrato.
