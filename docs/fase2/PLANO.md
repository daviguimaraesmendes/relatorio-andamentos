# Fase 2 — Plano de atuação

Status: **plano aprovado** em 07/10/2026, com os ajustes da seção 7 (decisões fechadas). Execução começa pela Etapa 0 (seção 8.2).

Os três modelos de referência, citados aqui por letra (os arquivos reais, com dados de clientes, ficam só no Drive do escritório e **não entram no repositório**):

| Letra | Entrega | Formato real | Quem lê |
| --- | --- | --- | --- |
| **A** | Relatório em texto simplificado | Google Doc / `.docx`: quadro-resumo (nº, assunto, momento atual, último andamento) + uma ficha por processo | Cliente |
| **B** | Relatório em planilha | `.xlsx` com ~29 colunas por processo, abas de parâmetros, indicadores (fórmulas), quadros e esboço de dashboard | Cliente / jurídico interno |
| **C** | Dashboards | `.html` autônomos que **leem o `.xlsx`** arrastado para a página (SheetJS + Chart.js) | Diretoria do cliente |

---

## 1. Resumo

1. A Fase 1 resolve bem **uma coisa**: achar andamentos novos nos autos, resumir, revisar e acrescentar na coluna "Andamentos" de uma planilha existente. É Mac-first, um relatório por vez, sequencial, só escreve `.xlsx`.
2. A Fase 2 precisa de **quatro fluxos** na tela inicial: **Importar relatórios existentes** (migração em massa), **Elaborar relatório inicial** (A + B + C), **Atualizar relatório** (A + B; o C se alimenta do B) e **Migrar de modelo** (converter um relatório existente para os modelos da ferramenta).
3. O que falta não é "mais scraping": é (i) um **modelo de dados único por processo** (a "ficha") que alimente os três entregáveis, (ii) **leitores** dos relatórios que o escritório já tem, (iii) **escritores** de `.docx` e de `.xlsx` completos, (iv) um **gerador de dashboards**, (v) uma **fila de coleta em massa** que sobreviva a horas de execução, e (vi) **revisão por exceção**, porque 200 processos geram centenas de linhas por ciclo.
4. A migração em massa fica barata por uma decisão de projeto: **o relatório antigo é o histórico**. O que já está escrito nele não é recoletado; o sistema só busca o que veio depois da data-base. Só processo novo (sem relatório anterior) paga o custo da leitura completa.
5. Campos de **julgamento** (probabilidade de perda, valor estimado, valor economizado, resultado) passam a ter **sugestão automática por regra** (seção 7.2), sempre marcada como `sugerido` e sujeita à revisão humana; o sistema não grava esses campos como definitivos sozinho.
6. A execução é desenhada para **9 a 10 agentes em paralelo**, separados por arquivo, com uma Etapa 0 curta e sequencial que fixa os contratos (schema da ficha, interfaces, fixtures sintéticas).
7. O que **não dá para validar aqui na nuvem**: login real (certificado A1, PJe Office, jus.br, captcha do TRT). Tudo isso é testado com coletor simulado; a validação real é um **piloto no seu Mac** (marco M5).

---

## 2. Ponto de partida e lacunas

| Tema | Fase 1 (hoje) | Lacuna para a Fase 2 |
| --- | --- | --- |
| Carteira | `carteira.json`: número, tribunal, cliente, polo, parte contrária, responsável. Importa lista/`.xlsx`/texto com validação do dígito CNJ | Falta tudo que os modelos A/B exigem: assunto, partes completas, vara, município, ajuizamento, citação, valor da causa, área, matéria, situação, fase, valores, resultado. Falta noção de **processos vinculados** (principal + agravo + apensos aparecem juntos numa linha no A e no B) |
| Entrada de relatórios | Só indica o `.xlsx` do mês anterior como modelo | Nenhum leitor: não extrai carteira, data-base nem histórico do relatório existente. Não lê `.docx` |
| Coleta | `coletor.py` (jus.br) e `trt.py`, um processo por vez, pausas de 3–5 s, 30 documentos por rodada; estado em `estado_coleta.json` | Sem fila com prioridade, sem retomada por processo com contagem de erros, sem janela noturna, sem relatório de cobertura por tribunal. Os modelos citam TJs de vários estados, TRFs e TRTs: a cobertura real precisa ser medida |
| Resumo | IA local pequena (Ollama), por documento, com checagem de trecho | Não produz "momento atual", "último andamento" nem narrativa de histórico completo. Não extrai capa do processo |
| Revisão | Uma fila de linhas, com alertas por regra | Não escala para centenas de linhas: falta triagem, aprovação em lote por regra, visão por processo, atalhos |
| Planilha | `planilha.py` grava **só a coluna "Andamentos"** por edição cirúrgica do XML (preserva gráficos e tabelas dinâmicas) | Não grava as demais colunas, não insere linhas de processos novos, não cria planilha do zero, não guarda histórico mensal |
| Texto (A) | HTML simples por cliente (`relatorio.py`) | Não existe `.docx` no formato A, nem atualização de um `.docx` existente |
| Dashboards (C) | Inexistente no repositório | Os dois HTML de referência leem o `.xlsx` no navegador e carregam bibliotecas de CDN. Falta gerador, versão offline e perfil por tipo de carteira |
| Base de testes | 3 testes de pipeline passam; `test_autos` exige Playwright (não instalado neste ambiente) | Fixtures sintéticas dos modelos, carteira fictícia de 200 processos, coletor simulado |

### O que os modelos nos ensinam (e que vira requisito)

**Modelo A (texto).** O quadro-resumo e a ficha por processo usam um vocabulário controlado de "momento atual" (aguardando sentença, cumprimento de sentença, aguardando julgamento da apelação, trânsito em julgado, arquivado etc.). Datas ficam em negrito. A frase de fecho é "Em DD/MM/AAAA, sem atualizações." Há linhas com **vários números** (principal, agravo, apenso). Há campos de capa que a Fase 1 não coleta (data de citação, juízo, valor da causa, área, matéria).

**Modelo B (planilha).** A aba de processos tem colunas coletáveis (número, partes, vara, município, tribunal, ajuizamento, valor da causa, andamentos), colunas **derivadas** (situação, ativo, resultado, prazo de resolução, houve recurso) e colunas de **julgamento humano** (probabilidade, valor estimado, valor economizado, depósitos, garantias). Há aba de parâmetros (número de funcionários, data de referência, empresas do grupo) e aba de indicadores com fórmulas.

**Modelo C (dashboards).** Os painéis aceitam variações de cabeçalho (mapeamento tolerante de colunas) e de formato de valor. Dependem de uma segunda planilha (pedidos das iniciais, com aba de cadastro) para o painel de pedidos. Os próprios documentos de apoio admitem que o painel precisa de série mensal ("ao longo do tempo"), o que só existe se o sistema **guardar um retrato a cada atualização**.

**Problemas de qualidade visíveis nas referências** (viram um verificador automático, WS-11):
- o mesmo processo contado duas vezes (reajuizamento, duas abas, linha duplicada);
- rótulos escritos de jeitos diferentes para a mesma matéria ("Reversão Justa Causa", "Reversão da justa causa.");
- grafias diferentes da mesma empresa ("Sitio"/"Sítio");
- linhas-marcador deixadas na base;
- indicador de "economia" inflado por acordo sem valor lançado, por acordo pago por terceiro e por exclusão da lide (as notas dos próprios quadros avisam disso);
- processo encerrado sem resultado; resultado e situação em conflito.

---

## 3. Os fluxos do usuário (alvo de usabilidade)

A tela inicial do painel passa a ter **três botões grandes** e uma pasta de trabalho por relatório (`entrada/` e `saida/`, que funciona bem com Drive para Desktop sincronizado).

### 3.1 Importar relatórios existentes (migração em massa)

1. Arrastar para o painel um ou **vários** arquivos (`.docx` modelo A, `.xlsx` modelo B, `.xlsx`/`.csv`/`.txt` com lista bruta de números; opcionalmente vários meses do mesmo `.xlsx` para reconstruir a série histórica).
2. O sistema **reconhece o formato**, lista o que achou ("187 processos, 6 clientes, data-base 18/09/2026") e mostra a **tela de conferência da migração**: o que foi lido, o que ficou ambíguo, números com dígito errado, duplicados, números vinculados, clientes sem nome padronizado.
3. Ao confirmar: cria o relatório (projeto), a carteira e as fichas, guarda o histórico lido como **linha de base** (não será recoletado) e registra a data-base de cada processo.
4. Processos que vieram **só como lista de números**, sem relatório anterior, entram marcados "novo — precisa de relatório inicial".

Meta de usabilidade: 200 processos migrados em **menos de 30 minutos de trabalho humano** (a coleta posterior roda sem acompanhamento).

### 3.2 Elaborar relatório inicial

1. Escolher o relatório, o **perfil de entrega** (A, B, C, ou os três) e o **nível de profundidade**:
   - *Rápido*: capa do processo + movimentações (sem abrir documentos). Dá "momento atual", "último andamento", dados de capa.
   - *Padrão*: o anterior + leitura dos documentos-chave (inicial, sentenças, acórdãos, decisões com efeito).
   - *Completo*: todos os documentos.
2. Rodar (pode ser em lotes, de madrugada, com pausa e retomada).
3. Revisar **por exceção** (seção 5.3).
4. Receber a pasta `saida/` com A (`.docx`), B (`.xlsx`) e C (`.html`), mais um **relatório de qualidade da base** (o verificador da seção 2) e uma lista "conferir manualmente" (segredo de justiça, não localizado, captcha não resolvido).

### 3.3 Atualizar relatório

1. Soltar o `.docx` e/ou o `.xlsx` mais recente (basta um; o outro é regenerado a partir da ficha). **O HTML não precisa ser enviado**: ele lê o `.xlsx`.
2. O sistema confere o arquivo contra a carteira (processo novo? processo sumiu?), coleta o que veio depois da data-base, resume e leva à revisão.
3. Após a revisão, gera **versões novas** dos arquivos enviados, preservando formatação, gráficos e tabelas, **mais um "o que mudou neste ciclo"** (resumo por processo e por cliente). O arquivo original nunca é sobrescrito.
4. O sistema grava um retrato do mês (série histórica dos dashboards).

Regra de ouro da atualização: **só acrescenta**. Texto que o advogado editou à mão no relatório não é reescrito; se o trecho recente foi alterado à mão, o sistema avisa e não duplica.

### 3.4 Migrar de modelo

Para o relatório que já existe num formato diferente dos modelos da ferramenta (outra planilha, outro texto):

1. Arrastar o arquivo. O leitor extrai a ficha de cada processo.
2. **Tela de mapeamento**: coluna do arquivo antigo → campo da ficha → coluna do modelo novo. O sistema propõe o mapeamento por similaridade de cabeçalho (como os painéis de referência já fazem) e **lista o que não tem destino** (nada se perde em silêncio: coluna sem destino vai para uma aba "Campos não migrados").
3. Escolher o modelo de destino (A, B ou os dois) e o perfil.
4. Receber o relatório convertido, mais o relatório de qualidade da base, para o próprio usuário conferir antes de adotar o novo formato.

Diferença para "Importar": importar adota o relatório **como está** para acompanhar; migrar de modelo **converte** o formato. Os dois usam o mesmo leitor; só o escritor e a tela de mapeamento mudam.


---

## 4. Arquitetura-alvo

```
 relatórios existentes ─► LEITORES ─┐
 lista bruta de números ─► (WS-2)   │
                                    ▼
                          FICHA v2 (por processo) ◄── CAPA/METADADOS (WS-4) ◄─┐
                          + eventos + linha de base                            │
                                    ▲                                          │
 FILA DE COLETA (WS-3) ─► coletor jus.br / TRT / DJEN ─► extração ─► SÍNTESE (WS-5)
                                                                               │
                                    REVISÃO POR EXCEÇÃO (WS-10) ◄──────────────┘
                                    │
                                    ▼ aprovado
              ESCRITORES: DOCX (WS-6) · XLSX (WS-7) · DASHBOARD HTML (WS-8)
                                    │
                         VERIFICADOR DE QUALIDADE (WS-11) ─► pasta saida/
```

### Peças novas (todas em `src/`, no estilo atual: módulos planos em português; telas novas seguem o padrão `registrar(app, TOKEN, cabecalho, token_ok)` de `cadastro.py`)

| Módulo | Função |
| --- | --- |
| `ficha.py` | Schema da ficha v2: união dos campos dos modelos A e B, com origem de cada campo (`coletado`, `derivado`, `humano`, `migrado`) e **vínculos entre processos** |
| `taxonomia.py` | Vocabulários controlados (momento atual, situação, resultado, matéria, área, probabilidade) e normalizadores de rótulo, com sinônimos editáveis |
| `perfil.py` | Perfil do relatório: quais entregas, qual modelo de planilha/texto, colunas ativas, estilo de redação, parâmetros (ex.: nº de funcionários) |
| `leitores/` | `docx_a.py`, `xlsx_b.py`, `lista.py` (evolução de `carteira.py`), `detectar.py` |
| `fila.py` | Fila persistente de coleta: estados por processo, retomada, prioridade, janelas de horário, perfil de ritmo, relatório de cobertura |
| `capa.py` | Extração de dados de capa (vara, município, ajuizamento, citação, valor da causa, assunto, partes, classe) das mesmas telas/consultas já abertas pelo coletor |
| `sintese.py` | Momento atual, último andamento, narrativa (inicial e incremental), leitura em camadas |
| `escritores/` | `docx_a.py`, `xlsx_b.py`, `dashboard.py` |
| `qualidade.py` | Verificador da base e "o que mudou" |
| `fluxos.py` | Orquestração dos três fluxos (`migrar`, `inicial`, `atualizar`) |
| `modelos/` | Ativos versionados: modelo `.docx` e modelo `.xlsx` **sanitizados**, templates de dashboard, bibliotecas JS embutidas (modo offline) |

### Decisões de projeto

- **A ficha é a fonte da verdade.** `.docx`, `.xlsx` e `.html` são **visões** dela. O arquivo que o usuário envia é lido para alimentar a ficha, nunca editado às cegas.
- **Edição cirúrgica preservada.** Para `.xlsx` existente, continua valendo a regra da Fase 1 (bibliotecas comuns de Excel apagam gráficos e tabelas dinâmicas). O `planilha.py` é generalizado para qualquer coluna e para **inserção de linhas**, com recálculo forçado ao abrir (o cache de fórmulas fica velho).
- **`.docx` por edição de estrutura**, preservando runs (negrito das datas), tabelas e estilos.
- **Dashboards autônomos e offline.** Bibliotecas embutidas (hoje vêm de CDN), dois modos: *modelo* (arrasta o `.xlsx`) e *com dados embutidos* (retrato do mês, para enviar por e-mail).
- **IA local continua o padrão.** O motor de IA vira plugável (`sintese.py`); sem mudar a promessa de que nada de cliente sai do computador, a não ser que o usuário opte (decisão D1).
- **Camadas de leitura.** Regras e tabelas fixas primeiro (`movimentos.json`, vocabulário controlado); IA só onde regra não basta, sempre com **vocabulário fechado** para "momento atual" e com citação de trecho para conteúdo.

---

## 5. Escala: 200 processos

### 5.1 Coleta

- **Dois modos de execução** (decisão D2): **contínuo** (a fila roda sozinha em janelas de horário, por exemplo à noite, e retoma no dia seguinte) e **imediato** (roda agora). No imediato, antes de começar o painel mostra uma **estimativa de duração** (processos × tempo médio medido no seu computador) e pede confirmação; o usuário pode restringir por cliente ou por lista de processos. Os dois modos usam a mesma fila e o mesmo ritmo.
- **Sem paralelismo contra o jus.br e os TRTs.** Os termos de uso proíbem acesso automatizado (já assumido na Fase 1: ritmo humano, um por vez). A escala vem de **rodar sem acompanhamento** (lotes, janela noturna, retomada), não de abrir várias sessões.
- **Estimativa a medir no piloto** (não é dado medido): atualização com poucos documentos novos por processo, na ordem de horas para 200 processos; carga inicial "completa", possivelmente mais de um dia de relógio. Daí o nível *Rápido/Padrão/Completo* e os lotes.
- **Fila** com: estado por processo (`pendente`, `coletando`, `coletado`, `erro`, `manual`), contagem e motivo de erro (captcha, segredo de justiça, não localizado, tempo esgotado, sessão expirada), retomada de onde parou, prioridade (processos com prazo próximo, clientes escolhidos), e **parada segura** em qualquer ponto.
- **Captcha do TRT**: a fila agrupa os processos de TRT para pedir o captcha uma vez por rodada e o aviso sonoro continua. Processos de TRT que ficarem sem resolver vão para "conferir manualmente", sem travar o resto.
- **Cobertura por tribunal**: o relatório de cobertura (processos coletados, só publicação via DJEN, manual) diz com clareza o que o sistema **não** cobriu. O DJEN (público) serve de rede de segurança para publicações. O uso do DataJud (API pública do CNJ) para metadados de capa em massa, **sem login**, é um *spike* a validar (WS-4): é preciso confirmar quais campos ele realmente devolve antes de depender dele.

### 5.2 Processamento posterior à coleta

Extração e resumo **não** falam com tribunal e podem rodar em paralelo local, limitados pela memória do modelo. Fila própria, também retomável.

### 5.3 Revisão por exceção

- **Triagem automática**: cada linha ganha um nível (`verde`: sem alertas, tipo de evento de baixo risco, conteúdo checado contra o documento; `amarelo`: algum alerta de regra; `vermelho`: desfavorável, prazo, audiência, valor, ou trecho não confere).
- **Aprovação em lote** só para `verde`, **com amostragem obrigatória** (um percentual de verdes cai na revisão manual, para manter o olho no sistema) e com registro de quem aprovou o lote.
- **Visão por processo** (linha do tempo do que mudou, com print e trecho de origem lado a lado), filtros por cliente, responsável, tribunal, nível; atalhos de teclado.
- **Revisão de campos derivados**: mudanças sugeridas de situação, momento atual, resultado e valores aparecem como um *antes → depois* para aprovar.
- O que **sempre** vai para olho humano, mesmo em lote: decisão desfavorável, mudança de resultado, qualquer valor monetário, audiência e prazo.

---

## 6. Brainstorm: o que mais pode entregar

Priorização: **Agora** (entra na Fase 2), **Depois** (Fase 2, última onda), **Avaliar** (precisa de decisão ou de dado que não temos).

| # | Ideia | Valor | Prioridade |
| --- | --- | --- | --- |
| 1 | **Verificador de qualidade da base** (duplicados, rótulos soltos, resultado sem valor, conflito situação/resultado, DV de número, campos obrigatórios por perfil), antes de entregar | Evita o erro mais caro: indicador errado na mão do cliente | Agora |
| 2 | **"O que mudou neste ciclo"** por processo e por cliente (resumo de uma página; serve de e-mail ao cliente) | Reduz tempo de conferência e de comunicação | Agora |
| 3 | **Série histórica automática**: retrato mensal da carteira (contagens, somas, prazos) alimentando "ao longo do tempo" nos dashboards; reconstruída a partir de vários `.xlsx` antigos na migração | É o que falta para os gráficos temporais dos esboços | Agora |
| 4 | **Perfis por tipo de carteira** (contencioso trabalhista em grupo empresarial, condominial/imobiliário, etc.): colunas, vocabulário, indicadores e dashboard próprios | Um sistema, vários clientes, sem planilha "à mão" | Agora |
| 5 | **Processos vinculados** (principal, recursos, apensos) como unidade de relatório | Fiel aos modelos A e B | Agora |
| 6 | **Alertas**: processo parado há N dias, sentença/trânsito em julgado novo, decisão desfavorável, audiência e prazo próximos | Transforma o relatório em ferramenta de gestão | Depois |
| 7 | **Agenda**: audiências e prazos extraídos viram arquivo `.ics` (importável no Google Calendar) | Pouco código, muito uso | Depois |
| 8 | **Descoberta contínua pelo DJEN**: processo novo do cliente aparece sozinho como sugestão de inclusão (já existe sob demanda) | Carteira não "esquece" processo | Depois |
| 9 | **Quadros analíticos** automáticos (acordos × economia com ressalvas, maiores exposições, condenação × pedido, desfecho por tese), com as "notas metodológicas" geradas junto | Replica o que hoje é montado à mão | Depois |
| 10 | **Exportação em PDF** do relatório A e do dashboard (impressão), e **rascunho de e-mail** ao cliente com anexos | Entrega pronta | Depois |
| 11 | **Pasta observada** (`entrada/` → processa; `saida/` → entrega) integrada a Drive para Desktop | Usabilidade: "soltou, saiu" | Agora (parte do assistente) |
| 12 | **Painel de pedidos das iniciais** (extração dos pedidos e valores de cada petição inicial) | Valioso para contencioso de massa | Avaliar (D5): exige leitura precisa de tabelas de valores; IA local pequena é fraca nisso |
| 13 | **Mais fontes de coleta** para tribunais que o jus.br não cobre bem | Cobertura | Avaliar (depende do relatório de cobertura) |
| 14 | **Sugestão (nunca preenchimento) de campos de julgamento** (probabilidade, valor estimado) com base em decisões já registradas na carteira | Ganho de tempo sem tirar o julgamento do advogado | Avaliar (D6) |
| 15 | **Modo "cliente único, painel só leitura"** (HTML com dados embutidos e senha local) | Entrega mais segura que enviar planilha | Avaliar |

---

## 7. Riscos e decisões em aberto

### Riscos

| Risco | Efeito | Mitigação |
| --- | --- | --- |
| Inserção de linhas e novas colunas em `.xlsx` com tabelas, gráficos e intervalos nomeados | Planilha corrompida ou gráfico quebrado | **Spike S1 antes de tudo** (Etapa 0); testar abrindo no Excel e no Google Sheets; manter o arquivo original intacto |
| Edição de `.docx` com formatação rica (tabelas, negrito de data, "Google Docs exportado") | Formatação perdida | **Spike S2** com amostra sintética; modo "gerar do zero" como alternativa |
| IA local pequena erra "momento atual" e narrativa | Relatório errado ao cliente | Vocabulário fechado, regras primeiro, checagem de trecho, revisão obrigatória; modo opcional de modelo maior (D1) |
| Cobertura de tribunais menor que a esperada | Parte da carteira cai em "manual" | Relatório de cobertura desde o piloto; DJEN como rede de segurança; novas fontes só após medir |
| Termos de uso do jus.br e do gov.br | Bloqueio de conta | Ritmo humano, sem paralelismo, parada segura, aviso claro (já na Fase 1) |
| Dado de cliente enviado a IA externa por engano | Quebra de sigilo | Consentimento **por cliente**, selo visível, registro de envios, pseudonimização opcional, padrão local (7.1) |
| Sugestão de julgamento aceita sem olhar | Indicador errado ao cliente | Marca `sugerido`, evidência por campo, ressalvas automáticas (7.2), revisão obrigatória dos campos monetários, teste retroativo antes de liberar |
| Dados reais de clientes em testes e no repositório | Vazamento | **Só fixtures sintéticas**; o `empacotar.sh` já barra nomes e números reais; modelos sanitizados em `modelos/` passam por revisão antes de entrar |
| Windows nunca testado | Nem todo cliente roda no Mac | Fase 2 é validada no Mac; Windows é item de marco próprio (M7) e fica declarado como "não testado" até alguém testar |
| Edição manual do relatório pelo advogado entre ciclos | Duplicação ou sobrescrita | Regra "só acrescenta", conferência contra o texto existente, aviso de divergência |

### Decisões fechadas (07/10/2026)

| # | Decisão | O que ficou decidido |
| --- | --- | --- |
| **D1** | IA | **Local por padrão**, com modelo maior quando a máquina tiver memória. O motor é **plugável**: o usuário escolhe, por relatório e por cliente, um provedor externo (Claude pela API da Anthropic ou outro serviço com API compatível). Ver 7.1 |
| **D2** | Ritmo da coleta | **Dois modos**: contínuo (janelas, retomada) e imediato (com alerta de duração). Sempre sequencial contra jus.br e TRT |
| **D3** | Entrada do modelo A | `.docx` exportado do Google Doc |
| **D4** | Planilha | Na atualização, o arquivo do cliente é o molde; no inicial, modelo padrão sanitizado. **Novo fluxo "Migrar de modelo"** (3.4) |
| **D5** | Painel de pedidos das iniciais | Fora da extração automática local, mas entra agora o **kit para IA melhor**: prompt, passo a passo e **campo no programa para colar o resultado** (WS-16). Ver 7.3 |
| **D6** | Campos de julgamento | **Sugestão automática por regra**, com revisão humana. Ver 7.2 |

### 7.1 Provedores de IA externos (D1)

- Cadastro de provedores no painel (nome, endereço da API, modelo, chave). A **chave fica no cofre do sistema**, como a senha do certificado.
- **Consentimento por cliente**: um relatório/cliente só usa IA externa se o usuário marcar. O painel mostra um **selo visível** (local / externa) em cada tela de resumo e de revisão, e o rótulo de qual motor produziu cada resumo fica gravado no evento.
- **Minimização do que sai**: só **texto extraído** do documento (nunca prints, certificado ou segredo), com opção de **pseudonimizar** nomes de partes e números de documento antes do envio. Um **registro local** lista o que foi enviado, quando e para qual provedor.
- O README muda: a promessa "nenhum documento de cliente é enviado para a internet" passa a valer **"salvo quando você ativa IA externa para aquele cliente"**.
- Sem chave ou sem rede, o sistema cai sozinho para o motor local e avisa.

### 7.2 Sugestão dos campos de julgamento (D6)

**Princípio**: regras determinísticas primeiro, IA só para ler o teor da decisão. Não há "treinamento" de modelo: o volume de exemplos é pequeno e regra explícita é auditável. A calibração é por **teste retroativo**: ao migrar relatórios que já têm esses campos preenchidos por humano, o sistema compara a sugestão com o que foi lançado e mede a concordância por regra. As regras só passam a "sugerir" sem ressalva quando a concordância for aceitável para você.

| Campo | Regra proposta | Ajustes que acrescentei (por favor confirme) |
| --- | --- | --- |
| **Resultado** | Teor da decisão de mérito mais recente: Procedência, Parcial procedência, Improcedência | Acrescento os desfechos que já existem nas suas referências e não são mérito: **Acordo**, **Extinto sem mérito**, **Arquivado/desistência**, **Incompetência**. Sem decisão: vazio |
| **Probabilidade** (de perda) | Possível = antes de decisão; Provável = decisão de procedência; Remota = decisão de improcedência | **(1)** A regra vale do ponto de vista de quem está sendo demandado. Quando o **cliente é o autor** (polo ativo na ficha), o sentido se inverte (procedência = perda remota). **(2)** **Parcial procedência** conta como Provável. **(3)** Valem a decisão **mais recente** e a instância mais alta: sentença sujeita a recurso fica marcada "sujeita a recurso". **(4)** Processo encerrado por acordo ou extinção: sem probabilidade (campo vazio) |
| **Valor estimado** | Valor da causa, até que sentença (ou acórdão) arbitre valor diverso; então, o valor arbitrado | Em **acordo**, o valor do acordo. Valor arbitrado só quando extraído de decisão com número; sem valor claro, mantém o da causa e marca alerta |
| **Valor economizado** | Valor da causa − Valor estimado | **Diferença em relação ao que você escreveu**: você escreveu "Valor estimado − Valor da causa", que dá zero ou negativo; usei **causa − estimado** (positivo = economia), que é a definição usada no seu modelo B. **Só para processo encerrado** (como no seu modelo). **Não conta** acordo sem valor lançado, acordo pago por terceiro, exclusão da lide e processo em que o cliente é autor: as notas dos seus quadros mostram que esses casos inflam o indicador, e o sistema marca cada um com ressalva |

Cada sugestão carrega: **origem** (`sugerido`), **regra aplicada**, **evidência** (documento e trecho) e, na revisão, aparece como *antes → depois*. Campo que o humano alterou **nunca é sobrescrito** por sugestão nova.

### 7.3 Kit para IA melhor — pedidos das iniciais (D5)

Em vez de extrair os pedidos com o modelo local, o programa **prepara o trabalho para uma IA de maior capacidade** (por exemplo, o Claude no navegador ou pela API) e **recebe o resultado**:

1. **Pacote por processo**: lista dos processos que têm petição inicial e ainda não têm pedidos extraídos, com o PDF da inicial já localizado na pasta do relatório.
2. **Prompt versionado** (`modelos/pedidos/prompt.md`) com o esquema de saída exato: um registro por processo (cadastro: função e categoria do reclamante, empresa do grupo, partes, município, vara, ajuizamento, valor da causa, critério do valor da causa) e uma linha por pedido (matéria padronizada pelo vocabulário do relatório, pedido como formulado, valor atribuído, situação do valor, página do PDF), com regras de arredondamento, tratamento de pedido sem valor, reflexos agrupados e encargos embutidos.
3. **Passo a passo** (`docs/pedidos-iniciais.md`) em linguagem simples, para quem nunca usou: abrir a IA, anexar os PDFs, colar o prompt, copiar a resposta.
4. **Campo "colar resultado"** no painel (e opção de **enviar o prompt direto pela API**, se o provedor externo estiver cadastrado e consentido, seção 7.1). O programa **valida** o que foi colado (formato, matérias fora do vocabulário, soma dos pedidos contra o valor da causa, processo desconhecido, duplicado) e mostra os achados **antes de gravar**.
5. O resultado alimenta a planilha de pedidos (abas de cadastro, pedidos, resumo e parâmetros por matéria) e, depois, o painel de pedidos.

O prompt é escrito aqui com dados fictícios; **a qualidade dele só se confirma no seu piloto**, com petições reais na IA que você escolher.

---

## 8. Execução multiagente

### 8.1 Regras de coordenação

1. **Um coordenador** (sessão principal) é dono dos contratos, do roteiro de integração e de todos os merges.
2. **Cada agente é dono de arquivos.** Dois agentes nunca editam o mesmo arquivo. Telas novas entram como módulos próprios (`registrar(app, ...)`); o `revisao.py` monolítico é fatiado na Etapa 0 para que WS-9 e WS-10 não colidam.
3. **Contratos congelados** ao fim da Etapa 0 (`ficha.py`, `docs/fase2/CONTRATOS.md`, formatos de arquivo). Mudança de contrato passa pelo coordenador, que avisa os agentes afetados.
4. **Um branch por workstream** (`fase2/ws-N-nome`), em worktree isolado; integração no branch `claude/gallant-pasteur-etzpu5`, em ordem de dependência, com testes verdes antes de cada merge.
5. **Todo teste usa fixtures sintéticas** e o coletor simulado. Nenhum dado de cliente em branch, em teste ou em mensagem de commit.
6. **Critério de pronto de um workstream**: testes novos passando, testes antigos intactos (os 3 de pipeline), módulo documentado no cabeçalho (estilo atual), nenhum caminho de rede real nos testes, e a conferência do `empacotar.sh` limpa.

### 8.2 Etapa 0 — Fundação (sequencial; coordenador; desbloqueia tudo)

| Item | Entrega |
| --- | --- |
| 0.1 | `ficha.py` (schema v2, com origem por campo e vínculos) + `taxonomia.py` (vocabulários iniciais) + migração dos projetos da Fase 1 (`carteira.json` → ficha) sem perda |
| 0.2 | `docs/fase2/CONTRATOS.md`: interfaces `Leitor.ler(arquivo) → RelatorioLido`, `Escritor.gravar(molde|None, estado, destino) → Resultado`, API da `Fila`, formato do `perfil.json`, formato do retrato mensal |
| 0.3 | Gerador de **fixtures sintéticas**: relatórios fictícios nos formatos A e B (e uma lista bruta), carteira de **200 processos** fictícios, **coletor simulado** que devolve capa, movimentos e documentos de teste (com falhas aleatórias: captcha, segredo, timeout) |
| 0.4 | Fatiamento do `revisao.py` em módulos por tela; convenção de testes (`tests/`), script único de teste, branches e worktrees |
| 0.5 | **Spikes de risco** (curtos, em paralelo): **S1** inserir linhas e colunas num `.xlsx` sintético com tabela, gráfico e fórmula, preservando tudo e abrindo no Excel/Sheets; **S2** atualizar um `.docx` sintético preservando negrito de data, tabela e estilos; **S3** (precisa de rede e de você) cobertura real por tribunal e campos do DataJud; **S4** (precisa do seu Mac) tempo real de coleta por processo; **S5** (precisa da sua máquina) qualidade do modelo local nos campos de capa e "momento atual" |

Saída da Etapa 0 (marco **M1**): contratos publicados, fixtures e coletor simulado prontos, S1 e S2 resolvidos (S3–S5 agendados com você).

### 8.3 Onda 1 — Construção em paralelo (após M1)

Cada workstream tem um agente. Todos dependem **apenas** dos contratos da Etapa 0 (WS-5, WS-9 e WS-16 usam o stub de provedor de IA até WS-18 chegar).

| WS | Escopo | Arquivos próprios | Aceite (resumo) |
| --- | --- | --- | --- |
| **WS-1** Ficha e taxonomia | Evoluir `ficha.py`/`taxonomia.py`: normalizadores, sinônimos editáveis, regras de "momento atual" por tabela, vínculos entre processos, dedupe | `ficha.py`, `taxonomia.py`, `tests/test_ficha.py` | Normaliza os rótulos soltos das referências (sintéticos); dedupe de vinculados; projetos da Fase 1 abrem sem perda |
| **WS-2** Leitores (migração) | Ler `.docx` modelo A, `.xlsx` modelo B (aba de processos, parâmetros, data-base), lista bruta e **planilhas/textos fora do modelo** (mapeamento por cabeçalho, base do fluxo "Migrar de modelo"); detectar formato; extrair carteira, linha de base, data-base, vínculos; relatório de ambiguidades | `leitores/*`, `tests/test_leitores.py` | 200 processos sintéticos lidos sem erro; ambiguidade nunca vira dado silencioso; ida-e-volta (ler → escrever → ler) preserva a ficha |
| **WS-3** Fila de coleta em massa | `fila.py` + integração com `coletor.py`/`trt.py` sem quebrar o uso atual: estados, retomada, prioridade, janelas, ritmo, parada segura, relatório de cobertura | `fila.py`, ajustes mínimos em `coletor.py`/`trt.py`/`rodar.py`, `tests/test_fila.py` | Com o coletor simulado: 200 processos com falhas aleatórias terminam, retomam após interrupção em qualquer ponto e não repetem trabalho |
| **WS-4** Capa e metadados | `capa.py`: vara, município, ajuizamento, citação, valor da causa, assunto, partes, classe; fontes: telas já abertas (jus.br/TRT), DJEN e, se S3 validar, DataJud | `capa.py`, `djen.py` (extensões), `tests/test_capa.py` | Cada campo com origem e confiança; campo ausente fica vazio (nunca inventado); fixtures de tela cobrem os dois portais |
| **WS-5** Síntese | `sintese.py`: momento atual (regras + IA com vocabulário fechado), último andamento, narrativa **inicial** (camadas: capa → movimentos → documentos-chave) e **incremental**; usa os provedores de WS-18 | `sintese.py`, `resumir.py` (extensões), `tests/test_sintese.py` | Estilo igual ao dos modelos; cada frase com origem; sem citação inventada; o histórico migrado nunca é reescrito |
| **WS-6** Escritor DOCX (A) | Gerar do zero e atualizar `.docx` modelo A: quadro-resumo, fichas por processo, data-base, fecho "sem atualizações", negrito de data | `escritores/docx_a.py`, `modelos/docx_a.*`, `tests/test_docx_a.py` | Atualiza fixture preservando formatação; abre sem aviso no Word e no Google Docs (conferência manual no M5); "só acrescenta" |
| **WS-7** Escritor XLSX (B) | Generalizar `planilha.py`: colunas por perfil, **linhas novas**, recálculo ao abrir, abas de parâmetros e histórico; criar do modelo canônico; campos humanos nunca sobrescritos | `escritores/xlsx_b.py`, `planilha.py` (refatorado), `modelos/xlsx_b.*`, `tests/test_xlsx_b.py` | Gráficos, tabelas dinâmicas e fórmulas intactos (comparação de partes do pacote); 200 linhas inseridas; abre no Excel e no Sheets |
| **WS-8** Dashboards (C) | Gerador de dashboard a partir do `.xlsx`: bibliotecas embutidas (offline), modos "arrastar planilha" e "dados embutidos", perfis (trabalhista de grupo; carteira simples tipo A), série histórica | `escritores/dashboard.py`, `modelos/dashboard/*`, `tests/test_dashboard.py` | Abre sem rede; mesmo `.xlsx` gera os mesmos números que o painel de referência; testado com Playwright |
| **WS-9** Painel e assistente | Tela inicial com os 4 fluxos (inclui tela de mapeamento do "Migrar de modelo"), modo contínuo/imediato com estimativa de duração, arrastar-e-soltar, conferência da migração, progresso em tempo real, pausar/retomar, página de entregas (download), pasta `entrada/`/`saida/`, tela de perfil | `painel/assistente.py`, `painel/migracao.py`, `painel/entregas.py`, `painel/perfil.py` | Fluxos completos com o coletor simulado; sem JavaScript externo; token em todos os formulários, como hoje |
| **WS-10** Revisão em escala | Triagem (verde/amarelo/vermelho), aprovação em lote com amostragem, visão por processo, filtros, atalhos, revisão de campos derivados (antes → depois) | `painel/revisao_lote.py`, `painel/processo.py`, ajustes em `revisao.py` fatiado | 600 linhas sintéticas revisadas com poucos cliques; regra "sempre humano" respeitada; nada aprovado em lote sem registro |
| **WS-11** Qualidade da base | `qualidade.py`: verificador (seção 2), "o que mudou neste ciclo", série histórica (retrato mensal), quadros analíticos | `qualidade.py`, `tests/test_qualidade.py` | Detecta cada problema da lista, em fixtures; falso positivo documentado; retrato mensal reproduzível |
| **WS-16** Kit de pedidos das iniciais | Prompt e esquema de saída versionados, guia passo a passo, pacote por processo, tela "colar resultado", validação (7.3), gravação na planilha de pedidos | `pedidos.py`, `modelos/pedidos/*`, `docs/pedidos-iniciais.md`, `painel/pedidos.py`, `tests/test_pedidos.py` | Validador rejeita cada tipo de erro em fixtures; ida-e-volta com planilha de pedidos sintética; guia legível por leigo |
| **WS-17** Sugestão de julgamento | `julgamento.py`: regras da seção 7.2, evidência por campo, teste retroativo contra relatórios migrados (relatório de concordância por regra), proteção de campo editado | `julgamento.py`, `tests/test_julgamento.py` | Cada regra com casos de teste (inclusive polo ativo, parcial procedência, acordo com ressalva); nada grava como definitivo; campo humano preservado |
| **WS-18** Provedores de IA | Interface de provedores (local, Claude/Anthropic, API compatível), cofre de chaves, consentimento por cliente, selo na tela, registro de envios, pseudonimização opcional, fallback para o local | `ia.py`, `painel/ia.py`, `tests/test_ia.py` | Nenhuma chamada externa sem consentimento (teste); registro completo do que saiu; falha de rede cai no local |
| **WS-13** QA, docs e pacote (contínuo) | Testes de desempenho (200 processos), atualização do README, `empacotar.sh` para novos ativos, checklist de confidencialidade, guia do usuário dos 3 fluxos | `tests/*` transversais, `README.md`, `docs/`, `empacotar.sh` | Pacote gerado limpo; guia testado por quem não conhece o projeto |

### 8.4 Onda 2 — Integração (coordenador + 2 agentes)

| WS | Escopo | Aceite |
| --- | --- | --- |
| **WS-14** `fluxos.py` | Orquestração de `migrar`, `converter`, `inicial` e `atualizar` ligando leitores, fila, capa, síntese, revisão, escritores e verificador | E2E com o coletor simulado e 200 processos: migrar, converter de modelo, atualizar, **interromper e retomar**, entregar A + B (+ C no inicial) |
| **WS-15** Teste de carga e regressão | 200 processos, 5 clientes, 3 ciclos mensais; compara saídas entre ciclos (nada some, nada duplica) | Zero duplicação de andamento; zero perda de campo humano; tempo de processamento (sem coleta) dentro de meta a definir com os números reais |

Marco **M4**: fluxos E2E verdes com coletor simulado.

### 8.5 Onda 3 — Piloto real, extras e acabamento

| Etapa | Quem | Entrega |
| --- | --- | --- |
| **Piloto 1** (marco **M5**) | **Você, no Mac**, com 1 cliente pequeno | Migrar um relatório real, atualizar de verdade, abrir A/B/C no Word, Sheets e navegador; medir tempo por processo e cobertura; calibrar vocabulário e regras |
| **Piloto 2** (marco **M6**) | Você | Carteira de ~200 processos em **lotes noturnos**; ajuste de ritmo, captcha, retomada |
| **WS-12** Extras | Agentes, após M4 | Alertas, agenda `.ics`, descoberta contínua pelo DJEN, PDF, rascunho de e-mail (itens 6, 7, 8, 10 da seção 6) |
| **Pacote v2** (marco **M7**) | Coordenador | README e guia atualizados, pacote limpo, Windows declarado "não testado" (ou testado, se alguém o fizer) |

### 8.6 Grafo de dependências

```
Etapa 0 (contratos, fixtures, spikes S1/S2)
   └─► Onda 1 em paralelo: WS-1 ─ WS-2 ─ WS-3 ─ WS-4 ─ WS-5 ─ WS-6 ─ WS-7 ─ WS-8 ─ WS-9 ─ WS-10 ─ WS-11 ─ WS-13 ─ WS-16 ─ WS-17 ─ WS-18
            (WS-9 e WS-10 usam stubs de fila e de escritores até os módulos reais chegarem)
        └─► Onda 2: WS-14 (fluxos) ─► WS-15 (carga/regressão)   [M4]
              └─► Onda 3: Piloto 1 [M5] ─► Piloto 2 [M6] ─► WS-12 extras ─► Pacote v2 [M7]
```

Ordem de merge sugerida na Onda 1 (para reduzir conflito): WS-1 → WS-18 → WS-2/WS-3/WS-4/WS-5/WS-17 (qualquer ordem) → WS-6/WS-7/WS-8 → WS-11/WS-16 → WS-9/WS-10 → WS-13.

### 8.7 Marcos

| Marco | O que prova |
| --- | --- |
| **M1** | Contratos, fixtures sintéticas, coletor simulado, S1 e S2 resolvidos |
| **M2** | Migração: ler `.docx`/`.xlsx`/lista e criar relatório, carteira e linha de base (fixtures) |
| **M3** | Os três entregáveis gerados a partir de fichas sintéticas |
| **M4** | Fluxos `migrar`, `converter`, `inicial` e `atualizar` ponta a ponta com o coletor simulado, 200 processos, com interrupção e retomada |
| **M5** | Piloto real pequeno no seu Mac |
| **M6** | Piloto de ~200 processos em lotes noturnos |
| **M7** | Pacote v2 com documentação |

### 8.8 O que este ambiente consegue e não consegue fazer

- **Consegue**: escrever e testar todos os módulos com fixtures e coletor simulado; testar `.docx`/`.xlsx` por inspeção do pacote e por abertura em ferramentas de linha de comando; testar o dashboard HTML com Playwright (Chromium já instalado aqui).
- **Não consegue**: entrar no jus.br/TRT (certificado A1, PJe Office, autenticador, captcha), medir tempo real de coleta, avaliar a qualidade do **seu** modelo local de IA, nem abrir os arquivos no Word do seu computador. Esses itens são os spikes S3–S5 e os pilotos M5–M6.

---

## 9. Confidencialidade na construção

- Os modelos de referência contêm dados reais de clientes. Eles foram **lidos nesta sessão só para entender a estrutura**; nada deles foi copiado para o repositório, e este plano usa letras (A, B, C) em vez de nomes.
- Todo teste usa dados **fictícios gerados por script** (nomes e números sintéticos; os números seguem o dígito verificador, mas fora da faixa que o `empacotar.sh` aceita como "real").
- Os ativos em `modelos/` (modelo `.docx`, modelo `.xlsx`, templates de dashboard) são **versões sanitizadas**: sem nomes, sem números, sem valores. A revisão deles é item do aceite de WS-6, WS-7 e WS-8.
