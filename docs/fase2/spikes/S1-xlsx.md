# Spike S1 — Inserir linhas e colunas em `.xlsx` com tabela, gráfico e fórmulas

Data: 07/10/2026. Autor: agente do spike S1 (Etapa 0, item 0.5 do `PLANO.md`).
Código: `spikes/s1_xlsx/` (`gerar_modelo.py`, `xlsx_cirurgico.py`, `test_s1.py`). Só dados fictícios.

## 1. Veredito

**Go com ressalvas.** A gravação cirúrgica (editar o XML do pacote e copiar o resto sem mexer) funciona para os três casos pedidos (centenas de linhas novas, várias colunas preenchidas, coluna nova), preserva tabela, gráficos, tabela dinâmica, estilos, validação, formatação condicional, nomes e outras abas, e o LibreOffice abre e recalcula tudo com os valores esperados. **O que não foi provado:** que o Excel abre sem pedir "reparo" e que o Google Sheets abre bem. Só o LibreOffice 24.2 estava disponível. Antes de dar o WS-7 como pronto, alguém precisa abrir as saídas no Excel (Windows e Mac) e no Sheets (checklist na seção 8).

Resultado dos testes: **44 de 44 passando** (`python3 -m unittest spikes/s1_xlsx/test_s1.py`, cerca de 22 s; os testes do LibreOffice são pulados se `/usr/bin/soffice` não existir).

## 2. O que foi construído

- `gerar_modelo.py`: gera, de forma determinística (dois runs dão arquivos idênticos byte a byte), o "modelo B" fictício:
  - aba **Processos** com as 29 colunas pedidas, 10 linhas, Tabela do Excel `tblProcessos` (A1:AC11), três colunas de fórmula (Ativo e Taxa de resolução em A1; Valor Economizado com referência estruturada e declarada como coluna calculada na Tabela), 4 regras de formatação condicional (uma com dois intervalos e uma barra de dados), 3 validações de dados (lista literal, lista vindo de outra aba, decimal), 3 intervalos nomeados;
  - **Parâmetros** (headcount, data de referência, lista de situações), **Indicadores** (COUNTA, COUNTIFS, SUMIFS, AVERAGEIFS, mistura de referência estruturada e A1), **Dashboard** (2 gráficos de barras: um aponta para Indicadores, outro direto para a coluna da tabela), **Dinâmica** (tabela dinâmica montada à mão no XML, com a Tabela como origem);
  - pós-processamento para parecer arquivo salvo pelo Excel: `sharedStrings`, `calcChain`, valores em cache nas fórmulas, `calcPr` sem `fullCalcOnLoad`.
  - Variantes: `sujo` (células sem estilo, linha sem estilo, 6.000 textos em sharedStrings, 29 linhas vazias formatadas depois da tabela, fórmula compartilhada `t="shared"`, tabela sem `tableStyleInfo`) e `preformatado` (a alternativa da seção 6).
- `xlsx_cirurgico.py`: só biblioteca padrão. Edita o texto do XML das partes que precisam mudar; as linhas não tocadas voltam com o texto original.

## 3. O que funcionou (todos com teste)

| Requisito | Resultado |
| --- | --- |
| 200 linhas novas ao fim da tabela | OK. Estilo (`s=`) copiado da última linha; colunas calculadas propagadas (declaradas na Tabela, A1 deslocada por linha, e fórmula compartilhada resolvida a partir do mestre); 5.000 linhas em cerca de 2,4 s |
| `ref` da Tabela, `autoFilter`, `<dimension>` | Atualizados e coerentes (`validar()` confere cabeçalho x nome de coluna, ids únicos, ref x nº de colunas) |
| Formatação condicional e validação de dados | Intervalos que terminam na última linha são estendidos (inclusive vários intervalos num `sqref` e o `xm:sqref` das extensões x14); os que não cobrem a tabela ficam como estão |
| Intervalos nomeados | Os que cobrem a coluna ou a tabela inteira são estendidos (linhas e, para a tabela inteira, colunas); os que apontam para outro lugar ficam iguais |
| Gráficos | Séries que apontam para a coluna da tabela são estendidas; o gráfico de outra aba fica byte a byte igual |
| Fórmulas em outras abas | Referência estruturada (`tblProcessos[Coluna]`) acompanha sozinha. Referência A1 que cobre exatamente a coluna da tabela (`Processos!$K$2:$K$11`) é estendida, como o Excel faria. Sem isso os indicadores ficariam errados em silêncio |
| Tabela dinâmica | Com a Tabela como origem: `refreshOnLoad="1"` e a dinâmica se refaz sozinha (no LibreOffice, a dinâmica mostrou as 210 linhas). Com origem por intervalo: o intervalo é estendido. Ao acrescentar coluna: `cacheField` e `pivotField` são acrescentados (só se o cache não tiver registros salvos) |
| Recálculo ao abrir | `fullCalcOnLoad="1"`; `calcChain.xml` removido (com a relação e o tipo de conteúdo) |
| Campos humanos | `escrever_celulas` nunca sobrescreve campo humano que já tem valor (vai para `Resultado.ignoradas`); fórmula também não é sobrescrita por padrão |
| Coluna nova | Cabeçalho com estilo do cabeçalho vizinho, `tableColumn` com id novo, `calculatedColumnFormula` quando a fórmula é estruturada, largura em `<cols>`, `spans`, nomes que cobrem a tabela inteira, dinâmica |
| Planilha "suja" | OK: células sem estilo continuam sem estilo; as linhas vazias formatadas do fim são reaproveitadas (sem linha duplicada); 6.000 sharedStrings não são tocadas; tabela sem formatação preservada |
| Arquivo estrangeiro | O modelo re-salvo pelo LibreOffice (atributos `aca`, `&quot;`, dinâmica por intervalo com cache de registros, extLst x14) também recebe 100 linhas, valida e recalcula certo |
| Erros explícitos | Coluna que não existe, conteúdo logo abaixo da tabela, linha de totais, texto acima de 32.767 caracteres, aba inexistente, arquivo que não é `.xlsx`, destino igual à origem: tudo vira exceção, sem arquivo de saída e sem tocar o original |
| Determinismo e composição | Mesma entrada, mesma saída (bytes); inserir 100 e depois 100 dá o mesmo pacote que inserir 200 de uma vez |

### Partes do pacote que mudam ao inserir 200 linhas (todas as outras são idênticas byte a byte)

| Parte | Por que muda |
| --- | --- |
| `xl/worksheets/sheet1.xml` (Processos) | linhas novas, `dimension`, `sqref` de CF/DV, cache de fórmulas apagado |
| `xl/tables/table1.xml` | `ref` e `autoFilter` |
| `xl/workbook.xml` | intervalos nomeados e `fullCalcOnLoad` |
| `xl/_rels/workbook.xml.rels`, `[Content_Types].xml` | saída do `calcChain` |
| `xl/calcChain.xml` | removida |
| `xl/charts/chart2.xml` | série que aponta para a coluna da tabela |
| `xl/worksheets/sheet3.xml` (Indicadores) | fórmulas A1 estendidas e cache apagado |

Idênticas: `styles.xml`, `sharedStrings.xml`, tema, `chart1.xml`, desenhos, tabela dinâmica (definição e cache), abas Parâmetros, Dashboard e Dinâmica, propriedades.

## 4. O que NÃO funcionou ou exigiu decisão

1. **O LibreOffice ignora `fullCalcOnLoad`.** Ele confia nos valores em cache: depois da inserção, os Indicadores continuavam mostrando 10 processos em vez de 210 (teste `test_i_...` documenta). O Excel honra `fullCalcOnLoad` (comportamento documentado do formato, mas **não verificado aqui**). Decisão do protótipo: além de ligar `fullCalcOnLoad`, **apagar o valor em cache de todas as fórmulas do arquivo** (`invalidar_cache=True`, padrão). Assim o LibreOffice calcula na hora e nenhum leitor vê número velho.
   Custo: leitores que não calculam (pandas, `openpyxl` com `data_only=True`, prévia do Mac/Gmail/celular) veem vazio nas células de fórmula até alguém abrir e salvar no Excel. Mitigação possível, não implementada: abrir uma **cópia** no LibreOffice só para colher os valores calculados e gravá-los como cache no nosso arquivo.
2. **Tabela dinâmica com cache de registros salvo** (como a que o LibreOffice grava; o Excel grava `pivotCacheRecords` por padrão): ao inserir linhas basta `refreshOnLoad`, mas ao **acrescentar coluna** o protótipo recusa (`NaoSuportado`), porque exigiria descartar o cache. A tabela dinâmica do modelo de teste foi montada à mão, sem registros salvos; não há como saber, aqui, se o Excel a aceita sem reparo.
3. **Linha de totais da Tabela** (`totalsRowCount`): recusada. Linhas novas teriam de entrar antes dos totais e o protótipo não desloca nada para baixo.
4. **Conteúdo logo abaixo da tabela** (notas, totais soltos): recusado, em vez de sobrescrever ou deslocar. Também recusa célula mesclada na faixa nova.
5. **Data gravada em célula sem formato de data** vira número serial: o protótipo só avisa (`Resultado.avisos`). Não cria estilo novo.
6. **Fórmula com referência A1 em coluna nova** é gravada nas células, mas não pode ser declarada como coluna calculada da Tabela (o Excel não herda a fórmula em linha digitada depois). Só fórmula com referência estruturada vira coluna calculada.

## 5. Limites conhecidos (não testados ou não tratados)

- **Excel e Google Sheets não foram testados.** Nenhuma afirmação de que abrem sem aviso. Pontos que mais preocupam no Excel: strings inline em vez de sharedStrings (válido, mas incomum), a tabela dinâmica montada à mão, a remoção do `calcChain` (prática comum de bibliotecas, mas não verificada aqui) e os atributos editados à mão.
- Formatação condicional **complexa**: foram testadas expressão, escala de cor e barra de dados (com extensão x14 no arquivo do LibreOffice). Conjuntos de ícones, regras com referência a outra aba e regras x14 que não sejam barra de dados não foram testados. Só `sqref` e `xm:sqref` são estendidos; a fórmula da regra não é reescrita.
- Validação de dados x14 (`xm:sqref`) é tratada pelo mesmo código da formatação, mas não há fixture com ela.
- Formatação condicional e validação **não são criadas para a coluna nova**; só se estende o que já cobria a tabela inteira.
- Segmentações de dados (slicers), linhas do tempo, comentários, tabelas de consulta, proteção de aba, `.xlsm`, vários `<table>` na mesma aba (exige `tabela=`) e filtro ativo com linhas ocultas (as linhas novas não entram ocultas e o filtro não é reaplicado): não testados.
- Fórmulas A1 em outras abas só são estendidas quando cobrem **exatamente** a coluna da tabela (do cabeçalho ou da primeira linha até a última). Intervalo parcial (`K2:K50`) ou montado com `OFFSET`/`INDIRECT` não é tocado.
- Os valores em cache dos gráficos (`numCache`) ficam velhos; o Excel e o LibreOffice refazem a partir das células, mas isso também não foi verificado no Excel.
- Texto: limite de 32.767 caracteres por célula (a coluna Andamentos de processos muito longos pode estourar; o protótipo recusa em vez de truncar).
- Windows/Mac: nada específico, o formato é o mesmo. Arquivo aberto no Excel (bloqueado) não foi considerado.

## 6. Alternativa: "template com linhas pré-formatadas"

Ideia: o modelo já vem com a Tabela cobrindo, por exemplo, 300 linhas, com estilo e fórmulas prontos; o escritor só preenche células (`escrever_celulas`), sem mudar estrutura. Foi testada com a variante `preformatado` (Tabela A1:AC301).

| Critério | Inserção cirúrgica | Linhas pré-formatadas |
| --- | --- | --- |
| Risco de XML inválido/reparo no Excel | Médio: mexe em `ref`, `sqref`, nomes, séries, workbook | **Baixo**: só células mudam (no teste, tabela, gráficos e dinâmica ficam byte a byte iguais; `workbook.xml` muda só por `fullCalcOnLoad` e as duas abas com fórmulas perdem o cache) |
| Resultado correto | Sim | **Não, sem cuidado extra**: as fórmulas das linhas vazias contam. No teste, "Processos ativos" deu 240 a mais, porque a fórmula de Ativo devolve "Sim" para linha em branco; tabela dinâmica ganha grupo "(vazio)", gráficos ganham categorias vazias, filtros mostram linhas em branco |
| Capacidade | Ilimitada | Fixa (acabou a reserva, volta a precisar de inserção) |
| Serve ao arquivo do cliente (decisão D4: o arquivo do cliente é o molde) | **Sim** | Não: o arquivo do cliente não vem pré-formatado |
| Coluna nova | Resolve | Não resolve |
| Aparência | Igual à do cliente | Mostra centenas de linhas vazias com borda |

**Qual é mais segura?** Para a **integridade do arquivo**, a pré-formatada é mais segura (nada estrutural muda). Para a **correção dos números e para o fluxo real** (arquivo do cliente como molde, crescimento sem teto, coluna nova), a cirúrgica é a única que serve, e os riscos dela são verificáveis: `validar()` + guardar o original + conferência manual no Excel. **Recomendação:** cirúrgica como caminho único para arquivo do cliente; no modelo padrão do fluxo "inicial", gerar o arquivo com 1 linha-modelo e usar a mesma cirurgia (um só caminho de código, um só conjunto de testes). Se o teste no Excel (seção 8) reprovar a inserção, a pré-formatada vira plano B **só para o modelo padrão**, com as fórmulas à prova de linha vazia (`IF(Número="","",...)`) e indicadores que ignorem linhas vazias.

## 7. Riscos e recomendação

| Risco | Efeito | Mitigação |
| --- | --- | --- |
| Excel pede "reparo" ao abrir (não verificado) | Cliente recebe arquivo com aviso | Checklist manual do M5 com as fixtures deste spike; `validar()` como portão antes de entregar; em caso de falha, entregar a cópia e avisar |
| Cache de fórmulas apagado | Prévia/leitor sem cálculo mostra vazio | Opção de colher valores com o LibreOffice numa cópia (ideia, não feita); documentar no guia do usuário |
| Fórmula A1 parcial ou dinâmica em outra aba não estendida | Indicador sem as linhas novas | Verificador do WS-11: comparar contagem de linhas da Tabela com o `ref` das fórmulas A1 que a citam |
| Tabela dinâmica com cache salvo + coluna nova | Recusa | WS-7 decide: descartar cache (com `refreshOnLoad`) ou pedir ao usuário |
| Modelos reais mais "ricos" que o fictício (segmentações, totais, comentários) | Recusa ou perda | Falha explícita, sem saída parcial; rodar `validar()` e a comparação de partes nas 3 planilhas reais do escritório (fora do repositório) antes do piloto |
| Chave por cabeçalho tolerante (acento/caixa) | Coluna errada se houver cabeçalhos quase iguais | Cabeçalho ambíguo vira erro; mapeamento explícito no perfil |

**Recomendação: Go com ressalvas.** Condições para encerrar a ressalva: (1) abrir no Excel (Windows e Mac) e no Google Sheets as saídas listadas abaixo, sem aviso de reparo; (2) decidir a política do cache de fórmulas (seção 4, item 1); (3) rodar o protótipo contra as planilhas reais do escritório, **fora do repositório**, só para ver recusas e avisos.

## 8. Checklist para quem abrir no Excel e no Sheets (leva 15 minutos)

Gerar e abrir (a partir de `spikes/s1_xlsx/`): `python3 gerar_modelo.py /tmp/modelo.xlsx` e, com `from xlsx_cirurgico import *`, `inserir_linhas`, `acrescentar_coluna` e `escrever_celulas` sobre o modelo (os testes fazem isso em pasta temporária; basta copiar os trechos). Conferir:

1. Abre sem a mensagem "encontramos um problema... reparar".
2. A Tabela tem 211 linhas, a faixa e o filtro cobrem tudo; linhas novas com a mesma formatação e fórmulas preenchidas.
3. Aba Indicadores com 210 processos (não 10) logo ao abrir; gráfico "Valor da causa por processo" com 210 barras.
4. Dinâmica atualizada (ou atualiza com "Atualizar tudo"); lista suspensa de Probabilidade/Situação funciona nas linhas novas; formatação condicional vale nas linhas novas.
5. Salvar de novo no Excel e reabrir: nada se perde.
6. Mesmo teste no Google Sheets (importar o `.xlsx`): fórmulas, validação e formatação condicional; anotar o que o Sheets ignora (tabela dinâmica e gráficos costumam mudar).

## 9. Esboço da API para o WS-7 (`src/escritores/xlsx_b.py`)

Contrato (`CONTRATOS.md`, seção 5): `gravar(molde, estado, destino, **opcoes) -> Resultado`. O protótipo já tem um adaptador `gravar(molde, estado, destino, aba=..., campos=..., humanos=...)` que devolve o dict do contrato (`destino`, `processos_atualizados`, `processos_novos`, `mudancas`, `avisos`). Ele só trata fichas com `numero` e `campos[nome]["valor"]`, converte data ISO e dinheiro em texto decimal, preenche **só células vazias** nos processos que já estão na planilha e insere os novos; `molde=None` (criar do modelo padrão) fica para o WS-7.

Primitivas (já existem no protótipo, com os testes):

```python
# uma operação por chamada, ou várias numa Edicao com um único salvar()
inserir_linhas(origem, destino, aba, linhas: list[dict], colunas: dict[str, str] | None = None,
               *, tabela=None, linha_cabecalho=1, sobrescrever_formulas=False) -> Resultado
escrever_celulas(origem, destino, aba, {(linha, coluna): valor}, *, humanos=None,
                 preservar_humanos=True, sobrescrever_formulas=False, ...) -> Resultado   # coluna: letra, cabeçalho ou índice
acrescentar_coluna(origem, destino, aba, cabecalho, valores=None, *, formula=None, estilo_de=None, ...) -> Resultado
ler_coluna(caminho, aba, cabecalho) -> {linha: texto}
validar(caminho) -> list[str]            # portão pós-escrita
class Edicao(origem, aba, tabela=None, linha_cabecalho=1, humanos=None, preservar_humanos=True, invalidar_cache=True)
    .acrescentar_coluna(...)  .escrever_celulas(...)  .inserir_linhas(...)  .salvar(destino) -> Resultado
Formula("SUM(A1:A3)"), LIMPAR              # marcadores de valor
Resultado(destino, linhas_inseridas, primeira_linha, ultima_linha, celulas_escritas,
          ignoradas=[(ref, motivo)], avisos, partes_alteradas, partes_removidas)
Erros: ErroXlsx > NaoSuportado | ColunaDesconhecida | ConflitoDeConteudo
```

Fluxo sugerido para `gravar` do WS-7:

1. Ler a planilha (WS-2) e conferir o molde com `validar(molde)`; recusar se já estiver quebrado.
2. Montar o mapeamento campo da ficha → cabeçalho a partir do perfil (colunas ativas), nunca por posição.
3. `Edicao(molde, aba, humanos=<colunas de julgamento>)`.
4. Colunas do perfil que faltam: `acrescentar_coluna` (antes de inserir linhas).
5. Processos existentes: `escrever_celulas` com os campos coletados/derivados; a regra "humano nunca sobrescreve" fica na Edicao, e a prioridade de origem da ficha (`humano > coletado > migrado > derivado > sugerido`) decide o que entra.
6. Processos novos: `inserir_linhas` (uma chamada, na ordem da carteira).
7. Andamentos: `planilha.py` refatorado para usar `escrever_celulas` (a regra "só acrescenta" e o fecho "Até DD/MM/AAAA sem andamentos" continuam no módulo de texto).
8. `salvar(destino)`; em seguida `validar(destino)`. Se houver problema: apagar o destino, devolver aviso e manter o molde intacto.
9. Preencher `Resultado` do contrato com `mudancas` (antes/depois) e os `avisos` (inclusive `ignoradas`).

Invariantes que o WS-7 deve manter nos testes: partes não editadas idênticas; `validar()` vazio; LibreOffice recalcula com os valores esperados; original nunca alterado; idempotência (gravar o mesmo estado duas vezes não duplica linha).

## 10. Observações de processo

- Os números de processo das fixtures são gerados em tempo de execução (dígito CNJ correto, sequencial `1234567`, fora do que o `empacotar.sh` trata como real); não há número literal novo no repositório.
- O branch do coordenador (`claude/gallant-pasteur-etzpu5`) não foi mesclado neste worktree: três arquivos de instalação com alterações locais (provavelmente fim de linha) impediam o merge, e o spike não toca neles. `CONTRATOS.md` foi lido por `git show`. O protótipo não importa nada de `src/`.
