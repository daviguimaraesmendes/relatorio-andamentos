# Estilo dos andamentos: parâmetros colhidos do relatório modelo

Colhido em 08/10/2026 do relatório modelo do escritório (modelo A, data-base 18/09/2026, **24 processos de um cliente condominial, TJCE**). Só números e padrões; os exemplos abaixo são **fictícios**. A medida é de UM relatório: antes de tratar como regra geral, rode `src/estilo_andamentos.py --colher` em outros relatórios do escritório.

```
cd "/Users/davimendes/Projetos Claude Code/relatorio-clientes"
.venv/bin/python src/estilo_andamentos.py --colher caminho/do/relatorio.docx     # só agregados, sem nomes
.venv/bin/python src/estilo_andamentos.py --avaliar "texto do andamento" --data-base 18/09/2026
```

## Parâmetros (`estilo_andamentos.PARAMETROS`)

| Parâmetro | Medida no relatório modelo |
| --- | --- |
| Tamanho do texto de andamentos | mediana 87 palavras (58 a 181); média 97; faixa de aviso 50 a 200 |
| Atos datados por processo | média 4,7 (1 a 12), mediana 4 |
| Orações (separadas por ponto ou ponto e vírgula) | média 6,9 (4 a 17) |
| Formato da data | sempre `DD/MM/AAAA`; mês/ano (`11/2025`) só quando vários atos caem no mesmo mês; nunca por extenso |
| Abertura | 21 de 24 abrem **sem data**, resumindo o que foi pedido e as tutelas (13 por particípio: "Deferida tutela...", "Ajuizada ação..."; os demais por substantivo: "Execução de taxas...", "Ação de...") |
| Atos datados | "Em DD/MM/AAAA, ..." no começo da oração (ou "(DD/MM/AAAA)" no meio), em **ordem cronológica** |
| Fecho | 17 de 24 terminam com "Em <data-base>, sem atualizações."; os 7 restantes terminam no último ato do ciclo |
| Voz do juízo e das partes | particípio ou passiva: "Deferida a tutela...", "foi proferida sentença...", "a parte contrária apelou" |
| Voz do escritório | **primeira pessoa do plural**: "apresentamos contrarrazões", "requeremos", "informamos", "comunicamos" (27 verbos nos 24 textos) |
| Cliente | terceira pessoa, pelo nome curto ("o Condomínio") |
| Dados concretos | 4 textos com valor em reais ("R$ 1.979,91"), 3 com percentual, 3 citam outro processo ("processo nº ..."), 2 citam norma só quando ela decide o caso |
| Vocabulário de momento | "AGUARDANDO …", "CUMPRIMENTO DE SENTENÇA", "TRÂNSITO EM JULGADO", "PROCESSO ARQUIVADO", com qualificador entre parênteses ("(DECISÃO FAVORÁVEL)", "(HONORÁRIOS SUSPENSOS)") |

## Exemplo no padrão (fictício)

> Execução de cotas condominiais ajuizada contra o proprietário da unidade 000 pelo não pagamento de R$ 3.000,00 (janeiro a março/2026). Rejeitada a exceção de pré-executividade em 10/05/2026, com determinação de prosseguimento. O executado depositou R$ 1.000,00 como pagamento parcial, o que impugnamos por insuficiência, requerendo o prosseguimento pelo saldo de R$ 2.000,00; em 15/07/2026, o Juízo autorizou o levantamento do valor incontroverso. Em 02/09/2026, apresentamos nova memória de cálculo. Em 18/09/2026, sem atualizações.

## O que mudou no programa por causa disto

1. **Pedido à IA local** (`resumir.SISTEMA_BASE` e `montar_pedido`): data `DD/MM/AAAA`; passiva/particípio para juízo e partes, primeira pessoa do plural para o escritório; valores, percentuais, unidades, prazos e processo relacionado quando constarem; lei ou portaria só quando decidir o caso (antes o pedido proibia qualquer citação de norma, o que o relatório modelo contraria; o alerta "A IA citou dispositivo legal" continua para a pessoa conferir).
2. **Régua de estilo** (`estilo_andamentos.avaliar`): avisa texto curto (< 50 palavras) ou longo (> 200), data por extenso, texto sem data, atos fora de ordem, escritório em terceira pessoa, frases vagas e fecho com data-base errada. Não reescreve nada. Ainda **não está ligada** à revisão: é para uso em `--avaliar` e para calibrar; ligar à triagem é um próximo passo se o usuário gostar do resultado.
3. **Vocabulário de momento**: entraram "AGUARDANDO CITAÇÃO DO EXECUTADO" e "AGUARDANDO PAGAMENTO DO SALDO DEVEDOR", que o relatório modelo usa e o leitor deixava fora ("momento_fora_do_vocabulario").
4. **Leitor do `.docx`** testado com um relatório real (24 processos): leu tudo; os avisos foram divergências entre o quadro-resumo e o texto (últimos andamentos e momentos), vínculos de tipo indefinido ("PROCESSO Nº A, B, C" vira apenso, a conferir) e o rótulo "DECISÃO" (lido como "CONCLUSOS PARA DECISÃO"; se for outro momento, é preciso decidir o vocabulário).

## Pendências

- Os exemplos que o usuário gravou em `estilo.md` entram no pedido; vale colar neles 3 a 5 textos do modelo (os melhores) para o modelo local imitar.
- A régua de estilo mede forma, não fidelidade ao processo: a conferência do trecho de origem continua sendo o que garante que o texto não inventa.
