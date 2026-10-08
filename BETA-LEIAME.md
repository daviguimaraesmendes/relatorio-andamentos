# Relatório de Andamentos — versão 2.0.0-beta4

Esta é a primeira versão de teste da **Fase 2**. Ela acrescenta, ao que você já usa, a montagem e a atualização de relatórios completos (texto, planilha e dashboard). O acesso ao jus.br e aos TRTs é o mesmo que já funciona; a aba **Atualizar** da versão anterior continua no painel, como plano B.

## 000. Novo no beta4 (a partir do teste com a planilha de contingências)

**ANTES DE TESTAR: feche o painel e abra de novo.** Depois de copiar um pacote novo por cima, o painel que já estava aberto continua rodando o programa **antigo**, e o número da versão no topo (lido do arquivo) engana. No beta2 e no beta3 isso explicaria "o aviso de captcha não apareceu" e "o login automático falhou de novo" se o painel não foi reaberto. A partir do beta4, se o arquivo da versão mudar com o painel aberto, aparece uma **faixa vermelha**: "Reinicie o painel". Para conferir que o código novo está rodando: o log da coleta do Assistente (`projetos/<relatório>/data/logs/AAAAMMDD-HHMMSS-assistente.log`, novo) começa com "Relatório de Andamentos 2.0.0-beta4".

1. **Planilha fora do modelo (como a de contingências).** Ao importar ou atualizar com uma planilha assim, o programa avisa no alto da conferência e abre **"Conferir e corrigir o mapeamento das colunas"**: você escolhe, coluna por coluna, o campo que ela alimenta (proposta já marcada). Melhorias de leitura: `AUTOR/RECLAMANTE` e `RÉU/RECLAMADO` viram autores e réus; `BREVE RESUMO DO CASO` vira o objeto; a coluna cujo **conteúdo** é um histórico datado (a sua `OBSERVAÇÃO`) é lida como **andamentos**; abas "Arquivados" entram como processos inativos; colunas próprias (passivo, provisão, depósito) **não se perdem**: vão para "Campos não migrados". Sem coluna de momento atual, o momento é deduzido pelas regras do último andamento (origem "derivado", conferir).
2. **Data-base.** Se o arquivo não traz, o programa usa a maior data do fecho "Em DD/MM/AAAA, sem atualizações." dos textos e **mostra um campo para você confirmar ou corrigir** antes de coletar.
3. **Correção importante na coleta.** Processo visto pela primeira vez **sem data-base** voltava **vazio** na coleta real (era tratado como "linha de base"). Agora traz o histórico completo. Isso pode explicar autos acessíveis que "não foram baixados" no relatório inicial e na atualização de processos sem data-base.
4. **Converter relatórios atuais para os modelos novos.** Está em **Assistente → Migrar de modelo** (e num link na própria conferência de importar/atualizar): você escolhe **texto simplificado (.docx)**, **planilha (.xlsx)** e/ou **painel com gráficos (.html)** (novo como destino; o painel lê a planilha, que sai junto). O arquivo original não é alterado; o que não tem destino fica em "Campos não migrados".

**O que eu não consegui ver** (os logs ficam no seu Mac): por que o login automático e o aviso de captcha não funcionaram. Se depois de **reabrir o painel** ainda falhar, me mande (sem nomes): a primeira linha do `*-assistente.log`, o conteúdo de `diagnosticos/login_jusbr_t1.json` e a saída de `python src/diagnostico_rodada.py --projeto <pasta>`.

## 00. Novo no beta3 (corrigido a partir do seu teste com 92 processos)

**O que mudou**

1. **Login do jus.br que explica o que deu errado.** Se o login automático não concluir, o programa grava a tela e o **motivo por passo** em `projetos/<relatório>/data/diagnosticos/` (arquivos `login_jusbr_t1…`), mostra a **faixa vermelha** no topo do painel dizendo o que fazer (por exemplo, abrir o PJe Office) e **pausa a coleta**: antes, cada processo repetia o login inteiro. Depois de resolver, clique em **Retomar** (o processo que estava na vez volta para a fila sem perder tentativa).
2. **Captcha do TRT: uma vez por TRT, não por processo.** A consulta de cada TRT fica aberta durante toda a rodada e o número seguinte é pesquisado pelo próprio formulário; os documentos abrem em outra aba. No fim da rodada o log diz: `captchas pedidos nesta rodada: N no TRT X`.
3. **Aviso de captcha que chama a atenção (Mac).** Notificação do sistema com som, o navegador vem para a frente **em tela cheia**, repete a cada 60 s e o painel mostra a faixa vermelha fixa ("Precisa de você: captcha do TRT 7 aguardando"). Se ninguém resolver em **10 minutos** (`coleta.captcha_espera_min` no `config.json`), o processo é **pulado**, a coleta segue com os demais tribunais e volta ao captcha **no fim da rodada**. No Windows o aviso é só o sinal sonoro do terminal (não testado).
4. **Processo físico.** Quando o processo não é achado no tribunal **e** o DJEN não tem publicação **e** o DataJud não o conhece, ele é marcado como **físico** (sem autos eletrônicos): aparece à parte, não conta como falha e a **taxa de sucesso é calculada só sobre os eletrônicos**. Na dúvida (DataJud desligado ou fora do ar), continua em "conferir à mão". O relatório do físico segue com as publicações do DJEN e o que você lançar à mão.
5. **Graus.** O 2º grau só é lido quando há sinal de recurso (andamento de remessa, recurso ordinário, distribuição ao relator, acórdão, ou o DataJud indicando grau 2), na mesma página, e **a falha nunca mais passa em silêncio** (aviso `grau_nao_lido` na entrega). O **TST** é reconhecido pelo DataJud (mesmo número CNJ): os andamentos do TST entram marcados "TST" e o momento vira "Aguardando julgamento do recurso de revista". Os **documentos** do TST ainda não são coletados (falta ver o acesso real; peço no fim).
6. **Textos dos resumos mais completos.** O modelo local agora é orientado a explicar **o que foi decidido, por quê, o que muda e os valores/prazos** (até 80 palavras, em vez de 40) e o programa avisa quando o resumo vem curto demais. Para imitar o seu jeito de escrever, crie o arquivo `projetos/<relatório>/estilo.md` com 3 a 5 parágrafos de relatórios seus (ou a chave `estilo_redacao` no `config.json`): eles vão junto de cada pedido. Os textos ficam no seu computador. Se a máquina tiver memória, um modelo maior melhora muito o resultado: no `config.json`, `"modelo": "gemma3:12b"` (depois `ollama pull gemma3:12b`).
7. **Estilo colhido do seu relatório modelo.** Medi os andamentos do relatório que você enviou (24 processos): mediana de 87 palavras, uns 5 atos datados por processo, abertura sem data, atos em ordem cronológica, juízo e partes no particípio e **o escritório na primeira pessoa do plural**, valores em R$, prazos e processos relacionados quando existem, fecho "Em <data-base>, sem atualizações.". O pedido à IA local segue esse padrão; `python src/estilo_andamentos.py --avaliar "texto"` aponta o que foge dele, e `--colher relatório.docx` mede outro relatório. Detalhes em `docs/fase2/estilo-andamentos.md`. O leitor de `.docx` leu esse relatório real sem erro (os avisos foram divergências entre o quadro-resumo e o texto).
8. **Diagnóstico da rodada.** `src/diagnostico_rodada.py` lê os logs e o estado e escreve as contagens **sem nomes nem números de processo** (veja `docs/fase2/diagnostico-rodada1.md`).

**O que olhar no teste (o que eu não consigo ver daqui)**

| Onde | O que você deve ver |
| --- | --- |
| Terminar de uma rodada com TRT | no log (Terminal ou aba Atualizar), a linha `captchas pedidos nesta rodada: …` com número bem menor que o de processos de TRT; compare com a rodada anterior |
| Forçar um captcha | notificação do Mac com som, navegador em tela cheia, faixa vermelha no painel; repete a cada minuto até resolver |
| Deixar o PJe Office fechado e iniciar a coleta | faixa vermelha com o motivo ("O diálogo do PJe Office não apareceu…"), coleta em pausa, e `diagnosticos/login_jusbr_t1.json`; abra o PJe Office e clique em **Retomar** |
| Assistente → andamento da coleta | cartão "físicos (sem autos eletrônicos)" e "Taxa de sucesso (só processos eletrônicos)" |
| Entregas → Conferir manualmente | físicos numa lista à parte |
| Processo com recurso | linha `graus lidos: 1º, 2º` no log; se o 2º grau falhar, `2º grau NÃO lido (…)` e um aviso na entrega |
| Resumos | mais completos; os curtos aparecem com o alerta "curto demais" na revisão |

**Limites conhecidos do beta3**: login, captcha, notificação/tela cheia no Mac e a navegação da consulta do TRT (voltar à pesquisa sem recarregar) **só se validam na sua máquina**; foram testados com simulações. Se a consulta do TRT recarregar mesmo assim, o log mostra `consulta recarregada do zero: Nx` e me diga o TRT.

## 0. Novo no beta2: clientes em lote

Importar um relatório de dezenas de processos não pede mais o cliente processo a processo.
- Na **conferência da importação** há o bloco **"Quem é o cliente?"**: o programa lista as partes que mais se repetem (a empresa, ou várias empresas do mesmo grupo, já agrupando as grafias) e deixa **marcado** o candidato óbvio. Um clique em "Confirmar" define, em todos os processos, o **cliente**, o **polo** (autor ou réu) e a **parte contrária**. Há também um campo de **cliente padrão** para o que sobrar.
- Em **Clientes e processos**, quando houver processos sem cliente, aparecem dois botões: **"Identificar os clientes pelas partes dos processos"** (usa os clientes que você cadastrou, com as variações de nome) e **"Aplicar a todos os sem cliente"**.
- Correção: o cliente, o polo e a parte contrária editados à mão em **Clientes e processos** agora valem para os relatórios novos (antes, a edição podia ficar escondida atrás do valor importado).

## 1. O que há de novo

Na aba **Assistente**, quatro caminhos:

1. **Importar relatórios existentes**: você arrasta o relatório em texto (`.docx`) e/ou a planilha (`.xlsx`), ou uma lista de números de processo. O programa mostra o que entendeu (processos, vinculados, números inválidos, duplicados) e, se você confirmar, cria o relatório sem recoletar o histórico que já está escrito.
2. **Elaborar relatório inicial**: gera os três entregáveis (texto `.docx`, planilha `.xlsx` e dashboard `.html`), com profundidade rápida, padrão ou completa. Pode rodar na hora (com aviso de quanto deve demorar) ou nas horas que você escolher.
3. **Atualizar relatório**: você envia o `.docx` e/ou a planilha mais recente; o programa coleta só o que veio depois da data-base, leva à revisão e devolve arquivos novos (o `.html` se alimenta da planilha).
4. **Migrar de modelo**: converte um relatório que está em outro formato para os modelos do programa, mostrando antes o mapeamento das colunas e guardando em uma aba à parte o que não tem destino.

Também há: **Triagem** da revisão (aprovar em lote o que não tem alerta), **Pedidos** (kit para extrair os pedidos das iniciais com uma IA melhor), **IA** (escolha do motor e do consentimento por cliente), **Entregas** (baixar os arquivos e ver o que conferir) e **Perfil** do relatório.

## 2. Como instalar sobre a versão que você já tem (Mac)

Seus dados ficam na pasta `projetos/` e a sua configuração em `config.json`. O pacote **não** contém nenhum dos dois, então não há risco de sobrescrevê-los.

1. **Faça uma cópia de segurança** da pasta inteira do programa atual (botão direito → Duplicar). Isso é o seu caminho de volta.
2. Descompacte `relatorio-andamentos.zip` e copie o conteúdo **por cima** da pasta do programa, escolhendo "Substituir". (Se preferir, descompacte numa pasta nova e copie para ela a sua `projetos/` e o seu `config.json`.)
3. Dois cliques em **`Instalar (Mac).command`** e responda `s`. Ele reaproveita o que já está instalado e só acrescenta o que falta (por exemplo, a biblioteca de Word).
4. **Opcional, recomendado**: instale o LibreOffice. Com ele, as fórmulas da planilha saem já calculadas (sem ele, abrem calculadas no Excel, mas o dashboard embutido perde alguns indicadores).
5. Dois cliques em **`Abrir painel.command`**. No topo da tela deve aparecer "versão 2.0.0-beta4".

**DataJud (opcional)**: a fonte de capa do processo (vara, município, data de ajuizamento, classe) vem ligada, mas precisa da chave pública do CNJ, que está na página "Acesso" da wiki do DataJud. Cole-a em `config.json` (`fontes_externas` → `datajud` → `chave`) ou na variável `DATAJUD_CHAVE`. Sem a chave, o programa segue sem ela.

**Voltar à versão anterior**: feche o painel, apague a pasta nova e use a cópia de segurança.

## 3. Roteiro curto de teste (uns 40 minutos)

Use **um cliente pequeno** (10 a 20 processos) que já tenha relatório em texto e planilha. O roteiro completo, com o que anotar, está em `docs/fase2/piloto.md`. O mínimo:

1. **Assistente → Importar**: arraste o `.docx` e a `.xlsx` do cliente. Veja se a conferência bate com o que você sabe do relatório.
2. **Assistente → Atualizar**: envie os mesmos arquivos, modo **imediato**, e leia o aviso de duração. Revise pela **Triagem**.
3. **Entregas**: baixe os arquivos e abra o `.docx` no Word (ou no Google Docs), a planilha no Excel (ou no Google Planilhas) e o `.html` no navegador. Siga as listas `docs/fase2/conferencia-docx.md` e `docs/fase2/conferencia-xlsx.md`.
4. Confira se **nada sumiu, nada duplicou e o que você escreveu à mão continua lá**.
5. Anote o tempo por processo e tudo que parecer estranho.

## 4. O que ainda não foi testado com casos reais (é para isso que serve o beta)

- A coleta pela **fila** (a aba Atualizar antiga continua sendo o caminho já validado).
- Os arquivos gerados no Word, no Excel e no Google; a leitura de relatórios reais exportados do Google Docs.
- A qualidade do momento atual, do último andamento e das sugestões de julgamento com texto real.
- A IA externa (Claude ou outro serviço) e o prompt dos pedidos das iniciais.
- Windows.

## 5. Como me mandar o resultado do teste

Preencha a planilha de registro de `docs/fase2/piloto.md` e envie **sem nomes de cliente nem números de processo** (use "Cliente A", "Proc 07"). Prints de tela de erro: tape nomes e números. Quando algo falhar, anote a tela, o que você clicou e a mensagem exata.

**Segurança**: nada de cliente sai do seu computador, a menos que você ligue IA externa para aquele cliente na aba IA. Mantenha o disco criptografado (FileVault) e nunca envie a pasta `projetos/`.
