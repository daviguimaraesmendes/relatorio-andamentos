# RFC: convenções dos leitores que o contrato não fixa (WS-2)

Autor: agente do WS-2. Status: proposta; os leitores já seguem a "melhor suposição" abaixo. O coordenador decide e,
se mudar algo, avisa WS-1, WS-6, WS-7, WS-9, WS-14 e WS-17. Nenhuma mudança de `CONTRATOS.md` foi feita por mim.

## 1. Problema

`CONTRATOS.md` §4 define `RelatorioLido` e `ProcessoLido`, mas não diz como representar quatro coisas que os modelos
reais trazem. Sem decisão, cada módulo vai escolher de um jeito.

1. **Qualificador do momento atual.** O modelo A escreve "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)". A ficha só
   guarda o momento do vocabulário (`momento_atual`); não há onde guardar o qualificador, e um ciclo de leitura e
   regravação o perderia.
2. **Escala de `percentual_exito`.** O campo é `numero`, mas "25%" pode ser 25 ou 0,25. O modelo B de referência guarda
   fração com formato de porcentagem.
3. **Frase de fecho no texto de andamentos.** "Em DD/MM/AAAA, sem atualizações." (modelo A) e "Até DD/MM/AAAA sem
   andamentos." (planilha da Fase 1) estão no texto lido. O fecho é recalculado a cada ciclo (exceção mecânica nomeada em
   `CONTRATOS.md` §5); se entrar na linha de base, um documento regenerado ficaria com o fecho no meio do histórico.
4. **Dados que a leitura vê e o contrato não tem lugar para pôr**: coluna "Ativo", frases datadas com a marca de negrito,
   mapeamento de colunas.

## 2. Proposta (já implementada nos leitores)

| # | Convenção | Onde |
| --- | --- | --- |
| 1 | `ProcessoLido["momento_qualificador"]` (texto, chave aditiva). **Sugestão ao coordenador**: acrescentar o campo opcional `momento_qualificador` (texto) a `ficha.CAMPOS`, grupo `situacao`, para o escritor `.docx` poder regravar "(...)" no título e no quadro-resumo (WS-6 hoje só escreve `momento_atual`). `taxonomia.normalizar_momento` do WS-1 deve devolver o mesmo par que `base.separar_qualificador`. | `leitores/base.py` |
| 2 | `percentual_exito` é **fração** (0 a 1). Célula com formato de porcentagem, texto "25%" e número até 1 viram fração; número maior que 1 é lido como pontos percentuais (25 vira 0,25). WS-7 deve gravar fração com formato de porcentagem; WS-8 deve tratar o campo como fração. | `base.converter_numero` |
| 3 | `andamentos_texto` sai **sem** o fecho final; a data do fecho vai em `ProcessoLido["fecho"]` (ISO). O fecho do meio do texto é mantido e avisado (`fecho_fora_do_fim`). | `base.analisar_andamentos` |
| 4 | Chaves aditivas: em `ProcessoLido`, `ativo` (bool, só se a planilha traz a coluna), `fecho`, `andamentos` (`[{"data", "texto", "data_em_negrito"?}]`) e `momento_qualificador`; em `RelatorioLido`, `mapeamento` (planilhas: `[{"aba", "coluna", "campo", "rotulo_campo", "confianca", "aplicado", "candidatos", "ambigua", "amostra", "indice"}]`). Nenhuma é obrigatória; só aparecem quando há conteúdo. | leitores |

Outras decisões de comportamento (para quem consome `RelatorioLido`):

- `ler(caminho, formato=None, mapeamento=None)`: o terceiro argumento, **pedido pela especificação do WS-2** ("`ler(caminho,
  mapeamento=...)` aceita mapeamento corrigido pelo usuário"), é `{cabeçalho do arquivo: campo | None}` ou a lista devolvida em
  `rel["mapeamento"]`. Só vale para planilhas e CSV.
- **Origem**: coluna de julgamento digitada é `humano`; célula de **fórmula** nunca é `humano` (vira `migrado`), porque
  ninguém a digitou. Os campos calculados do modelo B (Ativo, Valor Economizado, Taxa de resolução) entram como `migrado`
  quando há valor em cache.
- **Mesmo número duas vezes**: os dois registros ficam em `processos` e o aviso `numero_repetido` (atenção) lista as
  origens; `numero_em_dois_lugares` quando é principal num lugar e vinculado em outro. Quem funde é o `consolidar` (WS-1).
  Em lista de texto, a repetição é lida uma vez (aviso `info`).
- **Vínculo sem rótulo** ("123 (456)"): tipo `apenso` e aviso `vinculo_tipo_indefinido`. O tipo vem, nesta ordem, do rótulo
  antes do número no título/célula e do rótulo no quadro-resumo.
- **Momento atual fora do vocabulário** não é gravado: aviso `momento_fora_do_vocabulario` com candidatos. Aceita-se
  abreviação do rótulo conhecido ("ARQUIVADO" para "PROCESSO ARQUIVADO", aviso `info`), nunca rótulo com palavra a mais.
  Ampliar os sinônimos (WS-1) reduz esses avisos.
- Coluna "Situação" com um momento atual dentro ("Aguardando sentença") é lida como `momento_atual` (aviso
  `situacao_era_momento`), porque é assim que a planilha de referência do spike S1 a usa.
- Lista de códigos de aviso estáveis: cabeçalho de `src/leitores/base.py`.

## 3. Impacto

- **WS-1**: `taxonomia.normalizar_momento` e os sinônimos novos passam a valer sozinhos (os leitores chamam
  `taxonomia.normalizar`). `consolidar` recebe duplicatas e vínculos como acima.
- **WS-6**: o escritor deve aceitar `momento_qualificador`. O leitor de produção foi conferido contra o `ler_estrutura` do
  protótipo do spike S2 (números, datas, negrito e fecho de cada bloco; `tests/test_leitores.py`); WS-6 pode ter um só
  parser se quiser, mas `leitores/docx_a.py` não depende de nada do WS-6.
- **WS-7**: gravar `percentual_exito` como fração; reconhecer que a planilha lida pode ter colunas de fórmula sem cache
  (aviso `formula_sem_valor`, nível `info`).
- **WS-9**: a tela de conferência usa `avisos` (por `codigo`), `colunas_sem_destino` e `mapeamento`; a tela de mapeamento
  chama `leitores.ler(..., mapeamento=...)` e `leitores.destinos_possiveis()`.
- **WS-14**: ao criar a ficha, `linha_de_base.andamentos_texto` = `andamentos_texto`, `linha_de_base.ultimo_andamento` =
  `ultimo_andamento`, `linha_de_base.data_base` = `rel["data_base"]`; `ativo` e `momento_qualificador` são opcionais.
- **WS-17**: `julgamento.concordancia` lê campos de julgamento com origem `humano` do `ProcessoLido`; células de fórmula
  (por exemplo Valor Economizado) chegam como `migrado` e ficam de fora dessa comparação, de propósito.
