# Claude no projeto: qual modelo e qual esforço para cada tarefa

Atualizado em 2026-10-10, depois de um teste com seis configurações de modelo sobre uma planilha real de contingências e
24 documentos reais de dois processos (dados pseudonimizados; nada disso está neste repositório). **É um teste pequeno e
indicativo, não conclusivo**: veja os limites na seção 3.

## 1. Recomendação (resumo)

| Tarefa | Modelo e esforço | Por quê |
| --- | --- | --- |
| Mapear colunas de uma planilha desformatada para os campos do modelo B | **Haiku 5.5, médio** (com a tela de conferência humana) | 22 a 26 de 26 colunas certas em todas as configurações; as divergências foram em colunas ambíguas. |
| Normalizar valores de células (R$, %, sim/não, datas, CNPJ, "grau - justificativa") | **Haiku 5.5, médio** (ou só regras) | 47 de 47 em todas as seis configurações, inclusive Haiku baixo. As regras determinísticas (`leitores/grade.py`) já cobrem quase tudo; a IA fica para o resto. |
| Extrair o estado atual de um texto narrativo (momento, situação, fase, recurso, resultado, última data) | **Haiku 5.5, médio** | 70 a 71 de 72; nenhum valor fora do vocabulário; nenhum campo inventado onde o texto não dizia nada. |
| **Resumir documentos de processo** (a tarefa de maior risco) | **Sonnet 5.5, médio** como padrão | Resultado igual ao do Opus médio (mesmo `efeito` nos 24 documentos), com 0 a 1 data fora do documento. Opus não se justificou. |
| Resumir certidão, intimação, juntada, despacho e outros atos simples | **Haiku 5.5, médio** é aceitável, com as conferências do programa ligadas | No teste concordou com o Opus nesses tipos; ficou pior em ata de audiência, esclarecimentos de laudo e peças de recurso. |
| Sentença, acórdão, ata com valores e prazos | **Sonnet 5.5, médio + revisão humana** | Erro aqui custa caro: sempre revisar contra o documento. |

**Esforço:** médio para tudo. **Evite esforço baixo no resumo de documentos**: o Haiku baixo variou muito no `efeito`
(concordou com o Opus em só 15 de 24) e o Sonnet baixo marcou "favorável" em duas decisões que eram neutras (uma só recebia o
recurso). Esforço alto só vale a pena se o médio falhar numa categoria que importa (no teste o alto não trouxe ganho claro no
resumo; no mapeamento de colunas foi o único a acertar 26 de 26, mas num ponto em que a resposta certa é discutível).
Opus: não usar de rotina.

Padrão sugerido no cadastro do provedor: **Sonnet 5.5, esforço médio** para o resumo. Um segundo provedor "leve"
(**Haiku 5.5, médio**) para mapeamento, normalização e extração. Hoje o relatório usa um provedor só
(`perfil["ia"]["provedor"]`); escolher o leve por tarefa é uma melhoria a implementar (seção 6).

## 2. O que foi medido

Seis configurações (Haiku baixo e médio; Sonnet baixo, médio e alto; Opus médio), todas com o mesmo pedido e o mesmo gabarito.
O gabarito dos testes 1 a 3 foi escrito à mão a partir da própria planilha (aceitando mais de uma resposta quando o caso é ambíguo).

| Teste | O que é | Haiku baixo | Haiku médio | Sonnet baixo | Sonnet médio | Sonnet alto | Opus médio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | 26 colunas: qual campo do modelo | 22/26 | 24/26 | 24/26 | 24/26 | 26/26 | 24/26 |
| T2 | 47 valores: normalizar | 47/47 | 47/47 | 47/47 | 47/47 | 47/47 | 47/47 |
| T3 | 12 textos narrativos: 6 campos cada (72) | 71/72 | 70/72 | 70/72 | 70/72 | 71/72 | 70/72 |
| **Total** | | 96,6% | 97,2% | 97,2% | 97,2% | 99,3% | 97,2% |

Leitura: **os testes 1 a 3 são fáceis demais para separar os modelos** (diferenças de 1 ou 2 itens, dentro do ruído e de
ambiguidades do gabarito). Por isso a decisão pesa no teste 4.

**T4: resumo de 24 documentos reais** (sentenças, ata, decisões, recursos, certidões, intimações; 1º e 2º grau), com o prompt
exato da ferramenta (`resumir.sistema()` e `resumir.montar_pedido`), sem gabarito humano: checagens automáticas + comparação com o Opus.

| Medida | Haiku baixo | Haiku médio | Sonnet baixo | Sonnet médio | Opus médio |
| --- | --- | --- | --- | --- | --- |
| `efeito` igual ao do Opus | 15/24 | 22/24 | 22/24 | **24/24** | (referência) |
| Trecho de origem literal no documento | 23/24 | 23/24 | 24/24 | 24/24 | 24/24 |
| Começa em gerúndio (como pedido) | 24/24 | 24/24 | 17/24 | 22/24 | 24/24 |
| Sem alerta de `resumir.conferir` | 18/24 | 20/24 | 22/24 | 22/24 | 22/24 |
| Valor, data ou % do resumo que não está no documento | 1 de 30 | 1 de 32 | 0 de 47 | 1 de 49 | 0 de 39 |
| Tamanho dentro do limite | 24/24 | 24/24 | 24/24 | 24/24 | 24/24 |

Observações qualitativas (documentos de maior risco, lidos um a um):
- Os cinco acertaram o essencial das sentenças e da ata (valores, prazos, o que foi decidido).
- **Haiku** tem viés para "desfavorável" (tratou um acordo em ata como desfavorável) e, em um documento, escreveu uma data que
  não está no texto (ambos os Haiku, a mesma data); também preencheu `audiencia` com audiência já realizada (o campo é para audiência marcada).
- **Sonnet baixo** foi otimista: "favorável" para uma decisão que só recebeu o recurso. Em esforço baixo seguiu menos o formato (gerúndio).
- **Sonnet médio e Opus médio** foram os mais consistentes; o Sonnet médio concordou com o Opus em todos os `efeito`.
- Falhas de embalagem do teste mostraram um comportamento bom nos modelos: ao não conseguir ler um arquivo inteiro, eles avisaram em
  vez de inventar o resto.

## 3. Limites deste teste (leia antes de confiar)

- **Amostra pequena**: 26 colunas, 47 valores, 12 textos e 24 documentos de dois processos de uma mesma empresa e da Justiça do Trabalho.
  Não vale como garantia para outras áreas (cível, tributário) nem para documentos longos de outros tribunais.
- **Sem gabarito humano no T4**: o "padrão" foi o Opus mais as checagens automáticas. A revisão cega por um advogado ainda está pendente
  (há um arquivo de comparação lado a lado, com os modelos embaralhados, só na máquina de quem rodou o teste).
- **Candidatos rodaram como subagentes do Claude Code**, não pelo caminho real do programa (`claude -p` com o login da assinatura).
  O comportamento deve ser parecido, mas o esforço e o prompt de sistema do Claude Code podem diferir. **Repita o T4 pelo provedor
  real assim que o Claude Code estiver com login.**
- Tempo e consumo por modelo não foram medidos de forma limpa (execuções em paralelo).
- Pseudonimização: o nome da parte em outra caixa de letras ("Fulana" em vez de "FULANA") passou sem troca em alguns trechos. É o limite
  já documentado em `docs/confidencialidade-ia.md`: cadastre as variações do nome.
- Documentos assinados pelo nosso lado foram classificados como "parte contrária" porque não havia "quem assina pelo escritório"
  configurado (`Acesso e escritório`, também em "Configurar tudo"). Sem isso, a frase inicial do resumo sai errada, qualquer que seja o modelo.

## 4. Como configurar o Claude no painel

1. Abra o **Claude Code** do computador e faça `/login` (a conta da assinatura). Sem isso o provedor responde "não conectado".
2. Painel -> **IA** -> cadastrar provedor, tipo **"Claude pelo Claude Code deste computador"**: nome (por exemplo `claude-sonnet`),
   modelo `sonnet` (ou `haiku`, `opus`; também aceita o nome completo, por exemplo `claude-sonnet-5-5`), caminho em branco.
   O **esforço** (`medium`) hoje é uma opção do cadastro (`ia.cadastrar(..., esforco="medium")`); a tela ainda não tem o campo.
3. **Testar** (uma frase fixa, sem dado de cliente). Depois escolha o provedor para o relatório, marque o consentimento do cliente
   e deixe **pseudonimizar** ligado.
4. O consumo entra no limite da assinatura. O texto dos documentos vai à Anthropic (não é IA local): confira os termos da sua conta.

## 5. Como usar o Claude Code para desenvolver este projeto

- Instruções gerais e regras de segurança: `CLAUDE.md` na raiz.
- Subagentes: modelo e esforço conforme a tarefa. **Código e revisão**: Sonnet médio é o padrão; escrita de código novo
  grande ou revisão de segurança: Sonnet alto ou Opus médio. **Pesquisa e leitura de arquivos**: Haiku médio. Cada subagente num
  conjunto de arquivos diferente, em worktree, sem login real e sem tocar no cofre.
- Para medir um modelo: use o método da seção 6 (tarefas com gabarito e checagens automáticas), não impressão.

## 6. Como repetir o teste e o que falta

- Ferramentas em `tools/benchmark_modelos/` (corretores T1 a T4). As entradas e os gabaritos dependem de dados reais e NÃO ficam no
  repositório: gere-os de uma planilha e de documentos coletados, numa pasta temporária, e apague depois.
- Falta: (1) repetir o T4 pelo provedor real do programa (login); (2) revisão cega por um advogado; (3) ampliar o lote (30 a 60
  documentos, mais tipos e outras áreas); (4) **roteamento por tarefa** (provedor leve para mapeamento/normalização/extração e
  provedor padrão para resumos); (5) campo "esforço" na tela IA; (6) módulo de migração assistida por IA (mapeamento de colunas,
  normalização e extração de texto livre) usando Haiku médio, sempre com a tela de conferência humana, e as regras determinísticas primeiro.
