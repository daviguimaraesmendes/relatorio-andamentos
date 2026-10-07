# RFC — Memória dos valores gravados no `.xlsx` e chaves opcionais do estado

Autor: WS-7. Status: proposta (o código já funciona sem ela).

## Problema

CONTRATOS §5 manda avisar `edicao_manual_sobrescrita` quando o sistema troca um campo "mecânico" cujo valor anterior **já divergia do último que o sistema gravou**. Para o texto de andamentos existe `ficha["ultimo_texto_gravado"]`. Para as colunas mecânicas da planilha (situação, ativo, houve recurso, momento atual, último andamento, fase) não há onde guardar o último valor gravado; sem isso o aviso fica cego (e o escritor não consegue distinguir uma troca legítima de uma edição à mão).

## Proposta

1. `Resultado["valores_gravados"] = {numero: {campo: "valor em texto"}}` — o que o `xlsx_b.gravar` já devolve, só para os campos mecânicos escritos ou confirmados no ciclo.
2. O coordenador (fluxos) guarda em `ficha["ultimos_valores_gravados"] = {campo: valor}` (ao lado de `ultimo_texto_gravado`).
3. No ciclo seguinte o escritor lê essa chave (já implementado): se a célula tem um valor diferente do guardado **e** do novo, troca e devolve `edicao_manual_sobrescrita`; sem a chave, troca sem aviso.

## Impacto

- `ficha.py` (coordenador): chave opcional nova, sem validação obrigatória. Nenhum campo existente muda.
- `fluxos.py`: copiar `valores_gravados` para as fichas depois de gravar.
- Sem a mudança, nada quebra; só não há aviso de edição manual nessas colunas.

## Outras chaves aditivas (já aceitas pelo `xlsx_b`, nenhuma obrigatória)

- `estado["historico"]`: lista de retratos mensais (CONTRATOS §9, por exemplo `historico.carregar(projeto)`); os meses que faltam na aba Histórico são acrescentados ao fim, em ordem. O retrato do ciclo vem de `historico.retrato` (WS-11).
- `estado["campos_nao_migrados"]`: como `RelatorioLido["colunas_sem_destino"]`, com `"valores": {numero: valor}` opcional; alimenta a aba "Campos não migrados" (só existe no modelo padrão).
- `Resultado`: chaves extras `valores_gravados`, `partes_alteradas`, `partes_removidas`, `cache_formulas` (`invalidado|recalculado|mantido`).
- `perfil["colunas_ativas"]`: lista de nomes de campo da ficha (`ficha.CAMPOS`); no modelo padrão, colunas fora da lista ficam ocultas (exceto as que os indicadores leem).
