# Teste de modelos do Claude (corretores)

Ferramentas usadas para comparar modelos e esforços (resultado e recomendação em `docs/claude-no-projeto.md`).

**Os dados de entrada e os gabaritos NÃO ficam no repositório** (vêm de planilha e de documentos reais de clientes). Gere-os numa
pasta temporária, rode o teste e apague depois.

## Como refazer

1. **Entradas**
   - T1 (mapear colunas): `t1_input.json` = `{"campos_destino": [{campo, rotulo, tipo, descricao}], "colunas": [{id, aba, cabecalho, amostras}]}`
     (amostras com nomes e CNPJs mascarados) e `t1_truth.json` = `{id: {"cabecalho", "aceitos": [campos]}}`.
   - T2 (normalizar valores): células `{id, tipo, valor}` e `t2_truth.json` = `{id: {"tipo", "esperado"}}`
     (tipos: dinheiro, percentual, sim_nao, probabilidade, data, cnpj).
   - T3 (extrair de texto livre): `t3_input.json` = `{"vocabularios": {momento_atual, situacao, fase, resultado}, "textos": [{id, texto}]}`
     (vocabulários de `taxonomia.VOCABULARIOS`) e `t3_truth.json` com listas de respostas aceitas por campo.
   - T4 (resumir documentos): documentos coletados -> `extrair.extrair_arquivo` -> `ia.pseudonimizar` -> `resumir.montar_pedido`
     (prompt exato da ferramenta). Gravar em lotes pequenos e legíveis (`t4/sistema.txt` e `t4/loteN.json`, até ~35 KB cada,
     JSON indentado): a ferramenta Read dos candidatos corta arquivos de uma linha só em ~43 mil caracteres.
     Textos completos para o corretor em `t4_textos_para_corretor.json` = `{"textos": {id: texto}, "meta": {id: {tipo, grau}}}`.
2. **Candidatos**: um subagente por configuração (modelo e esforço), só com Read e Write, gravando `respostas/<config>/T1.json`,
   `T2.json`, `T3.json` e `T4v2.json`. Peça que não leiam arquivos de gabarito e que NÃO inventem o que não leram.
3. **Corrigir**: `python corrigir_t1_t3.py` e `python corrigir_t4.py` (a partir da pasta com os dados).
   O T4 também gera `comparacao_t4.md` (resumos lado a lado, modelos embaralhados) para revisão cega por um advogado.

## Cuidados

- Teste só com dados pseudonimizados e consentimento; apague a pasta de trabalho (PDFs reais) ao terminar.
- O corretor de números do T4 compara só a parte numérica (valor "53.990,08" sem "R$" no documento conta como presente) e converte
  datas por extenso. Mantenha essa regra: a versão literal gera falsos alarmes.
