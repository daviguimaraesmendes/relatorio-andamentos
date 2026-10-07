# RFC: qualificador do momento atual não tem lugar na ficha

Autor: WS-1. Status: proposta (contrato não alterado).

## Problema

O modelo A escreve o momento atual com um qualificador opcional entre parênteses
(`CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)`, `PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)`).
`taxonomia.normalizar_momento(texto)` já separa os dois pedaços, e `taxonomia.formatar_momento(momento, qualificador)`
junta de volta. Mas `ficha.CAMPOS["momento_atual"]` guarda só o valor do vocabulário: `ficha.definir` normaliza
"CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)" para "CUMPRIMENTO DE SENTENÇA" e o qualificador se perde. Sem lugar
para ele, o leitor (WS-2) não consegue preservá-lo e o escritor (WS-6) não consegue regravá-lo (ida e volta quebra).

## Proposta

Em `ficha.py` (dono: coordenador), acrescentar um campo de texto livre, sem vocabulário:

```python
"momento_qualificador": ("Momento atual: qualificador", "situacao", "texto", None),
```

- Leitores (WS-2): `momento, qualificador = taxonomia.normalizar_momento(texto)`; gravam `momento_atual` e, se houver,
  `momento_qualificador` (origem `migrado`).
- Síntese (WS-5): `sintese.momento_atual` já devolve `{"momento", "qualificador", ...}`; o fluxo grava os dois.
- Escritores (WS-6/WS-7): exibem `taxonomia.formatar_momento(obter(f, "momento_atual"), obter(f, "momento_qualificador"))`.
- Quando o momento muda por coleta/regra, o qualificador antigo deve ser limpo (`ficha.limpar`), porque descreve o
  momento anterior; só o humano o repõe.

## Impacto

- `ficha.CAMPOS` ganha 1 entrada (aditivo; nada existente muda). `ficha.validar` não precisa mudar.
- Até a decisão, `taxonomia.momento_ativo`/`categoria_do_momento` já aceitam o texto com qualificador, e
  `consolidar` preserva o parêntese quando o campo `momento_atual` o traz (por exemplo, um relatório migrado que o
  escreveu inteiro).
- Sem a mudança, a melhor suposição é: o qualificador entra em `observacoes` com o prefixo "Momento atual: ".
