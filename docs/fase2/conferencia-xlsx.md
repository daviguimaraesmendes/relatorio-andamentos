# Conferência manual do relatório em planilha (.xlsx) — 15 minutos

O WS-7 só fica **pronto** (marco M5) depois de você abrir as planilhas abaixo no **Excel (Windows e Mac)** e no **Google Planilhas**. Aqui no ambiente de construção só deu para testar com o LibreOffice; o Excel e o Google nunca abriram estes arquivos.

## 1. Gerar os arquivos de teste (1 minuto)

No terminal, na pasta do projeto:

```
python3 tests/test_xlsx_b.py --exemplos ~/Desktop/conferencia-xlsx
```

Saem 4 planilhas (todas com dados **fictícios**) e um arquivo `LEIA-ME-esperado.txt` com os números que os Indicadores devem mostrar (calculados à parte, em Python):

| Arquivo | O que é |
| --- | --- |
| `1-criada-do-zero.xlsx` | 200 processos no modelo padrão. As fórmulas **não** trazem resultado guardado. |
| `2-criada-do-zero-com-valores-guardados.xlsx` | O mesmo, com os resultados das fórmulas já guardados (precisa do LibreOffice instalado para ser gerado). |
| `3-atualizada-no-ciclo-seguinte.xlsx` | O arquivo 1 depois de um mês: andamentos novos, um processo novo e uma anotação feita à mão. |
| `4-modelo-de-cliente-com-dinamica-e-graficos-atualizado.xlsx` | Uma planilha "de cliente" de teste (tabela dinâmica e gráficos) com 100 processos acrescentados. |

## 2. Roteiro (marque Windows / Mac / Google em cada linha)

**A. Abre sem reclamar** — para cada arquivo: abre sem a mensagem "encontramos um problema… deseja recuperar/reparar"? Se aparecer, anote o texto e o arquivo. *Este é o teste mais importante.*

**B. Arquivo 1**
1. Aba **Processos**: 200 linhas, filtro nos cabeçalhos, 29 colunas visíveis. Botão direito nas letras das colunas > Reexibir: aparecem 8 colunas extras (Momento Atual, Último Andamento etc.), que ficam ocultas de propósito.
2. Colunas **Valor Economizado** e **Taxa de resolução** já vêm preenchidas (fórmula) nos encerrados.
3. Aba **Indicadores**: **sem** `#NOME?`, `#VALOR!` ou `#REF!`. Compare com `LEIA-ME-esperado.txt` (arquivos 1 e 2). Atenção especial a "Processos com recurso da empresa" e "Tempo médio de resolução": usam colunas com `?` e parênteses no nome.
4. Aba **Dashboard**: 4 números no topo e 5 gráficos com barras/linha.
5. Aba **Parâmetros**: funcionários 350, data 07/10/2026, fator 1,05, empresas. Troque o número de funcionários e veja "Litígios por 100 funcionários" mudar.
6. Aba **Histórico**: uma linha (07/10/2026). Cabeçalhos: Data-base, Total de processos, Processos ativos, Processos encerrados, Valor da causa, Valor estimado, Valor economizado.
7. Digite um processo novo na linha logo abaixo da tabela (ou Tab na última célula): a tabela cresce, as duas colunas de fórmula se preenchem sozinhas, as listas suspensas de Situação, Probabilidade e Resultado funcionam e a cor da Probabilidade aparece.
8. Salve, feche e reabra: nada se perde (gráficos, indicadores, ocultação das colunas).

**C. Arquivo 2** — igual ao 1, e a prévia do arquivo (Finder/Explorador/e-mail do celular) já mostra os números dos Indicadores. No arquivo 1 a prévia mostra células vazias nos Indicadores: é esperado.

**D. Arquivo 3** (compare com o final de `LEIA-ME-esperado.txt`)
1. Processo com andamento novo: o texto da coluna Andamentos termina na frase nova, **sem** "Até … sem atualizações".
2. Processo com anotação à mão: a anotação continua no começo e a frase nova vem depois.
3. Os demais: "Até 07/11/2026 sem atualizações." no fim.
4. Processo novo: última linha da tabela, com a mesma formatação das outras.
5. **Histórico**: duas linhas (07/10 e 07/11) e o gráfico "Evolução do acervo" com os dois pontos. **Parâmetros**: data de referência 07/11/2026.
6. Indicadores batem com o segundo bloco de `LEIA-ME-esperado.txt`.

**E. Arquivo 4**
1. Abre sem reparo; a tabela tem 110 linhas.
2. Aba **Dinâmica**: clique em Dados > Atualizar tudo; a contagem total passa a 110.
3. Indicadores mostram 110 processos; gráfico "Valor da causa por processo" com 110 barras.

**F. Google Planilhas** — importe cada arquivo (Arquivo > Importar > Carregar). Anote o que muda: tabela dinâmica e gráficos costumam mudar; fórmulas dos Indicadores devem calcular; listas suspensas e cores condicionais devem continuar. Se algum Indicador der erro só no Google, anote qual.

## 3. O que anotar e onde

Para cada linha acima, escreva "ok" ou o que viu (e uma captura **sem dados reais**; estes arquivos são fictícios) e mande ao coordenador. Qualquer "reparo" no Excel é bloqueio do marco M5.

## 4. O que **não** foi verificado aqui

- Excel (Windows e Mac) e Google Planilhas: nada. Pontos de maior risco: fórmulas com nomes de coluna entre colchetes duplos (`Tabela[[Houve recurso da empresa?]]`), tabela dinâmica montada à mão no arquivo 4, textos gravados como "texto em linha" (válido, mas incomum), remoção da cadeia de cálculo (calcChain).
- Planilhas reais do escritório: rode `gravar` contra cópias delas, **fora do repositório**, só para ver as recusas e os avisos.
- Tabela dinâmica com dados guardados + coluna nova (recusada), segmentações, linha de totais, macros e abas protegidas (recusados com mensagem; o comportamento da recusa foi testado, mas não com arquivos reais).
