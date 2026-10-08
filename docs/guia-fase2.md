# Guia da Fase 2: os quatro fluxos, passo a passo

Este guia é para quem vai usar a ferramenta no dia a dia e nunca a usou. Não
precisa saber programar. Cada fluxo diz **o que você faz**, **o que aparece na
tela** (descrito em palavras) e **o que conferir antes de seguir**.

> **Leia isto primeiro.** Os nomes de botões e telas abaixo seguem o desenho
> aprovado da Fase 2. A ferramenta ainda está em integração e foi exercitada só
> com dados fictícios: se alguma tela real for diferente do que está escrito
> aqui, vale a tela, e vale avisar quem mantém a ferramenta para corrigir o guia.
> O estado de cada parte está em `fase2/STATUS.md`. Antes de enviar qualquer
> arquivo gerado a um cliente, abra-o no Word, no Excel ou no Google (seção 11):
> a abertura nesses programas ainda não foi testada.

## 1. Antes de começar

Você precisa ter feito a **Primeira vez** do `README.md` (seção 4): acesso e
escritório configurados e "ACESSO OK" na tela de acesso. Para coletar nos
autos, o PJe Office precisa estar aberto com o certificado, como antes.

Palavras que aparecem nas telas:

| Palavra | O que quer dizer |
| --- | --- |
| **Relatório** | Um grupo de clientes (ou um cliente só) com a sua aba no painel. É o que antes se chamava "projeto". |
| **Ficha** | O cadastro completo de um processo dentro da ferramenta (partes, vara, valor, momento atual, andamentos...). Os três arquivos de saída (texto, planilha, painel) são "visões" da ficha. |
| **Data-base** | A data até a qual um relatório está em dia. A ferramenta só busca o que veio **depois** dela. |
| **Histórico (linha de base)** | O que já estava escrito no relatório antigo. É guardado como está e **nunca é recoletado nem reescrito**. |
| **Momento atual** | Em que pé o processo está (aguardando sentença, cumprimento de sentença, trânsito em julgado...). Vem de uma lista fixa de opções. |
| **Profundidade** | *Rápido*: capa do processo e movimentações, sem abrir documentos. *Padrão*: o anterior mais os documentos-chave (inicial, sentenças, acórdãos, decisões com efeito). *Completo*: todos os documentos. |
| **Modo contínuo / imediato** | *Contínuo*: a coleta roda sozinha em janelas de horário que você define (por exemplo, das 20h às 6h) e retoma no dia seguinte. *Imediato*: roda agora, depois de você confirmar a duração estimada. |
| **Captcha** | As letras numa imagem que o TRT às vezes pede. A ferramenta para e espera você digitar. |
| **Selo local / externa** | Mostra se o resumo de um andamento foi feito pela IA do seu computador ou por um provedor externo que você ativou (seção 9). |

## 2. A tela inicial: "O que você quer fazer?"

A tela inicial do assistente (se não a encontrar na barra de abas, o endereço é
`http://127.0.0.1:5072/fluxo`) mostra a pergunta **"O que você quer fazer?"** e
**quatro botões grandes**:

1. **Importar relatórios existentes**
2. **Elaborar relatório inicial**
3. **Atualizar relatório**
4. **Migrar de modelo**

Como escolher:

- Você **já tem** relatórios prontos (texto, planilha ou só uma lista de
  números) e quer que a ferramenta passe a acompanhá-los: **Importar**.
- Você tem **processos novos**, sem relatório anterior: **Elaborar relatório
  inicial**.
- Você tem um relatório **que já está em dia na ferramenta** e chegou o fim do
  mês: **Atualizar relatório**.
- Você tem um relatório **num formato diferente** do usado pela ferramenta e
  quer convertê-lo: **Migrar de modelo**.

A tela de **revisar andamentos** (aprovar, corrigir, descartar) continua na aba
**Revisar**, como antes. Há ainda as telas **Entregas** e **Perfil** (seção 10).

## 3. Fluxo 1: Importar relatórios existentes

**Para quê.** Trazer de uma vez os relatórios que o escritório já tem. O que
está escrito neles vira o histórico: não será buscado de novo nos autos. A meta
do projeto é que 200 processos sejam importados com menos de 30 minutos de
trabalho seu (a coleta que vem depois roda sem acompanhamento).

**Passo a passo**

1. Clique em **Importar relatórios existentes**.
2. **Arraste os arquivos** para a área de soltar da tela. Pode soltar vários de
   uma vez:
   - o texto do relatório (`.docx` exportado do Google Docs);
   - a planilha do relatório (`.xlsx`);
   - uma lista de números de processo (`.txt` colado de e-mail, `.csv` ou `.xlsx`);
   - opcionalmente, vários meses do mesmo `.xlsx`, para a ferramenta montar a
     série histórica dos gráficos "ao longo do tempo".
3. A ferramenta **reconhece o formato** de cada arquivo e mostra uma frase como
   "187 processos, 6 clientes, data-base 18/09/2026". Arquivo que não for
   reconhecido volta com uma mensagem clara (veja a seção 12).
4. Abre a **tela de conferência da migração**. Ela é uma página com blocos:
   - **O que foi lido**: totais por arquivo, cliente e data-base;
   - **Ambiguidades**: lugares em que a ferramenta não teve certeza (por
     exemplo, o mesmo número aparece duas vezes com dados diferentes);
   - **Números inválidos**: processos cujo dígito verificador não bate (erro de
     digitação); ficam fora até você corrigir;
   - **Duplicados**: o mesmo processo em duas linhas ou duas abas;
   - **Vinculados**: principal, agravo e apenso que serão tratados como **uma**
     linha do relatório;
   - **Clientes sem nome padronizado**: "Chacara" e "Chácara", com e sem "Ltda",
     maiúsculas e minúsculas. A ferramenta **sugere** a junção; só junta se você
     confirmar;
   - **Campos sem destino**: colunas do arquivo que a ferramenta não sabe onde
     guardar. Nada se perde em silêncio: elas ficam listadas aqui, com uma
     amostra do conteúdo, para você decidir.
5. Resolva o que quiser em cada bloco e **confirme** a importação (o botão de
   confirmar fica no fim da tela).
6. A ferramenta cria o relatório, as fichas e o histórico de cada processo e
   registra a data-base de cada um. Processos que vieram **só como número** (sem
   relatório anterior) entram marcados **"novo: precisa de relatório inicial"**.

**O que conferir antes de confirmar**

- O número de processos lidos é o que você esperava?
- Os clientes aparecem uma vez cada, com o nome certo?
- Todos os números inválidos foram revistos (digitação, ou processo que não
  existe)?
- Os "campos sem destino" não incluem nada importante? (Se incluírem, o caminho
  é o fluxo **Migrar de modelo**, que leva essas colunas para uma aba "Campos não
  migrados".)

**Depois**: para os processos "novos", use **Elaborar relatório inicial**; para
os demais, no mês seguinte, **Atualizar relatório**.

## 4. Fluxo 2: Elaborar relatório inicial

**Para quê.** Produzir o primeiro relatório de processos que ainda não têm
histórico escrito: a ferramenta lê os autos, preenche as fichas e gera os
arquivos.

**Passo a passo**

1. Clique em **Elaborar relatório inicial**.
2. Escolha:
   - **O que entregar**: texto (`.docx`), planilha (`.xlsx`), painel (`.html`), ou
     os três. O painel é gerado a partir da planilha.
   - **Profundidade**: rápido, padrão ou completo (tabela da seção 1). Quanto
     mais fundo, mais demorado. Para uma carteira grande, comece pelo *rápido* e
     aprofunde depois.
   - **Filtro** (opcional): um cliente específico ou uma lista de processos.
   - **Modo de coleta**:
     - **Contínuo**: informe a janela de horário (por exemplo, 20h às 6h). A
       coleta roda sozinha dentro dela e retoma no dia seguinte. O computador e o
       painel precisam estar ligados.
     - **Imediato**: roda agora. Antes de começar, a tela mostra **"Duração
       estimada: ..."** e pede confirmação. A estimativa vem do tempo médio
       **medido no seu computador**; na primeira vez, usa um valor prudente (e
       provavelmente longo), que melhora conforme a ferramenta mede.
3. Inicie a coleta. A tela de progresso (seção 7) mostra o andamento.
4. Quando terminar, **revise por exceção** (seção 8). Só o que você aprova entra
   no relatório.
5. Receba a pasta de saída (seção 10) com os arquivos, o **relatório de qualidade
   da base** e a lista **"conferir manualmente"**.

**O que conferir**

- A lista "conferir manualmente": segredo de justiça, processo não localizado,
  captcha que ninguém resolveu. Esses processos **não** foram cobertos.
- O relatório de qualidade da base (seção 8): duplicados, matéria escrita de
  dois jeitos, acordo sem valor, encerrado sem resultado, etc.
- Os campos de julgamento sugeridos (seção 9) antes de enviar ao cliente.

## 5. Fluxo 3: Atualizar relatório

**Para quê.** No fechamento do mês, acrescentar ao relatório o que veio depois
da última data-base.

**Passo a passo**

1. Clique em **Atualizar relatório**.
2. **Solte o arquivo mais recente**: o `.docx` e/ou o `.xlsx` (basta um; o outro
   é refeito a partir das fichas). **Não precisa enviar o painel `.html`**: ele
   lê a planilha.
3. A tela de **conferência contra a carteira** mostra:
   - **Processo novo**: está no arquivo, mas ainda não na carteira;
   - **Processo que sumiu**: estava na carteira e não está no arquivo (apagado de
     propósito ou sem querer?).
4. Inicie a coleta e acompanhe o progresso (seção 7).
5. Revise (seção 8).
6. A ferramenta grava **novas versões** dos arquivos que você enviou, com
   formatação, gráficos e tabelas preservados, mais um resumo **"o que mudou
   neste ciclo"** (por processo e por cliente, em uma página, que pode servir de
   base para o e-mail ao cliente; ele não promete resultado).
7. Ela também guarda um **retrato do mês** da carteira, que alimenta os gráficos
   de série histórica.

**Regras que a ferramenta segue (e que você pode contar com)**

- **Só acrescenta.** O que o advogado escreveu à mão no texto de andamentos não
  é reescrito. Se o trecho mais recente foi alterado à mão, a ferramenta avisa
  e não duplica.
- **O arquivo original nunca é sobrescrito.** Sai sempre uma cópia com outro nome.
- O que a ferramenta **troca** a cada ciclo é só o que ela mesma calcula: a data
  da frase "Em DD/MM/AAAA, sem atualizações.", o momento atual, o "último
  andamento" e a Data-Base. Se você tinha alterado algum desses à mão, vem um
  aviso.
- A frase "sem atualizações" só entra no processo que **não** teve andamento novo
  no ciclo ("Em DD/MM/AAAA, sem atualizações." no texto; "Até DD/MM/AAAA sem
  atualizações." na coluna Andamentos da planilha).

## 6. Fluxo 4: Migrar de modelo

**Para quê.** Converter um relatório que está **num formato diferente** (outra
planilha, outro texto) para os modelos da ferramenta, para você conferir antes de
adotar o novo formato.

**Diferença para "Importar":** importar adota o relatório **como está** para
acompanhar; migrar de modelo **converte o formato**. Os dois leem o arquivo do
mesmo jeito; muda o que sai no fim.

**Passo a passo**

1. Clique em **Migrar de modelo**.
2. Arraste o arquivo (planilha ou texto) para a área de soltar da tela.
3. A tela de **mapeamento** mostra uma tabela com três colunas:
   **coluna do seu arquivo** → **campo da ficha** → **coluna do modelo novo**.
   A ferramenta propõe o mapeamento pela semelhança dos cabeçalhos e mostra, ao
   lado, o quanto confia em cada sugestão. Corrija o que estiver errado em cada
   linha.
4. Abaixo da tabela fica a lista **"sem destino"**: colunas do seu arquivo que
   não correspondem a nenhum campo. Nada se perde: elas vão para a aba **Campos
   não migrados** do modelo novo.
5. Escolha o **modelo de destino** (texto, planilha ou os dois) e o perfil.
6. Confirme a conversão. Você recebe o relatório convertido e o relatório de
   qualidade da base.

**O que conferir**: compare algumas linhas do arquivo antigo e do novo (número,
partes, valores, datas) e leia a aba "Campos não migrados".

## 7. Acompanhar o andamento (progresso em tempo real)

Depois que a coleta começa, a tela de progresso mostra, em tempo real:

- quantos processos estão **pendentes**, **coletando**, **coletados**, **com
  erro** e **para conferir manualmente**;
- os comandos **Pausar**, **Retomar** e **Parar com segurança**.

**Parar com segurança** termina o processo que está sendo coletado e grava o
estado; nada fica pela metade. **Se a luz cair ou o computador desligar**, ao
abrir o painel de novo a fila **retoma de onde parou**, sem repetir o que já foi
coletado.

A coleta é **sempre um processo por vez**, com pausa entre eles, para respeitar
o ritmo humano que o jus.br e os TRTs exigem. Por isso uma carteira grande leva
horas, e a carga inicial "completa" pode passar de um dia de relógio (os tempos
reais ainda serão medidos no piloto). A ferramenta foi pensada para rodar à
noite e sem você.

**Captcha.** Se houver processos de TRT, a ferramenta junta todos do mesmo TRT e
pede o captcha **uma vez por rodada**, com um aviso sonoro. Se ninguém digitar,
esses processos vão para "conferir manualmente" e o resto continua.

A ferramenta também prepara o **relatório de cobertura por tribunal**: quantos
processos foram coletados, quantos só têm publicação (DJEN) e quantos ficaram
para conferência manual. Ele diz com clareza o que a ferramenta **não** cobriu.

## 8. Revisar por exceção

Com muitos processos, ler tudo seria inviável. A revisão se organiza por cores,
em uma tela que mostra o contador de cada uma:

| Cor | Quando | O que fazer |
| --- | --- | --- |
| **Vermelho** | Decisão desfavorável, prazo, audiência, qualquer valor em dinheiro, mudança de resultado, ou trecho de origem que não confere com o documento. | **Sempre** lido por você, um a um. Nunca entra em lote. |
| **Amarelo** | Algum alerta de regra (autoria não identificada, andamento sem tradução, nome do cliente ausente...). | Revise um a um. |
| **Verde** | Sem alertas, tipo de evento de baixo risco, conteúdo conferido com o documento. | Pode aprovar **em lote**, mas uma **amostra** (por padrão, 10%) vai para a sua revisão manual, escolhida de modo reprodutável. A aprovação em lote fica registrada (quem e quando). |

**Visão por processo.** Para cada processo há uma linha do tempo com a data, o
texto, a cor, e ao lado o **print** e o **trecho de origem**. Em cada linha: aprovar,
corrigir ou descartar. Atalhos de teclado: **J** e **K** para navegar, **A**
aprovar, **D** descartar, **E** editar.

**Campos que a ferramenta recalcula** (situação, momento atual, resultado,
valores sugeridos) aparecem como **antes → depois** para você aprovar. O que você
aprova passa a valer como decisão sua.

**Filtros**: por cliente, responsável, tribunal, cor e processo.

**Relatório de qualidade da base.** Antes de entregar, a ferramenta procura
problemas que costumam passar despercebidos: o mesmo processo contado duas vezes
(reajuizamento, duas abas, linha repetida); matéria escrita de jeitos diferentes
("Reversão Justa Causa" e "Reversão da justa causa."); grafias diferentes da
mesma empresa; acordo sem valor lançado; acordo pago por terceiro, exclusão da
lide e processo em que o cliente é autor (que **distorcem o indicador de
economia** e aparecem com ressalva); encerrado sem resultado; resultado em
conflito com a situação; datas incoerentes; valor da causa vazio ou zero;
linhas-marcador deixadas na planilha. Cada achado diz onde está e o que fazer.
**Leia esse relatório antes de enviar a planilha ou o painel ao cliente**: o
erro mais caro é um indicador errado na mão do cliente.

## 9. Campos de julgamento, IA externa e pedidos das iniciais

**Campos de julgamento (sugestão, nunca decisão).** Resultado, probabilidade,
valor estimado e valor economizado são **sugeridos por regra**, a partir do que
as decisões dizem, sempre com o **trecho de origem** e **ressalvas** em palavras
(por exemplo, "sujeita a recurso", "acordo sem valor lançado: fora do
indicador"). A sugestão aparece marcada como tal e **só vale depois da sua
aprovação**. O que você escreveu **nunca** é sobrescrito. A probabilidade é a do
**resultado do processo** (provável, possível, remota), a mesma regra para quem é
autor e para quem é réu: ela não se inverte conforme o polo do cliente. O valor
economizado é o valor da causa menos o valor estimado, e só conta processos
encerrados, sem os casos que inflariam o indicador.

**IA externa (opcional).** Por padrão, tudo é resumido no seu computador. Se
você cadastrar um provedor externo e **marcar o consentimento do relatório (ou do
cliente)**, os textos extraídos dos documentos daquele cliente passam a ser
enviados ao provedor. O painel mostra o **selo** (local ou externa) em cada
resumo, guarda o **registro local** do que foi enviado e oferece **pseudonimizar**
os nomes antes do envio. Leia o aviso de confidencialidade do `README.md`
(seção 8) **antes** de ligar.

**Pedidos das iniciais.** Para extrair os pedidos e valores das petições
iniciais com uma IA melhor, existe um passo a passo próprio:
[Pedidos das iniciais](pedidos-iniciais.md). Nele **você** anexa os PDFs na IA
que escolher (fora do programa) e cola a resposta no programa, que confere
formato, matérias e somas antes de gravar.

## 10. Entregas, pastas e perfil

**Entregas.** A aba **Entregas** lista os arquivos de cada relatório para
**baixar**: texto, planilha, painel, o relatório de qualidade e a lista "conferir
manualmente". Cada relatório tem uma pasta **entrada/** (onde você solta o que
quer processar) e uma pasta **saida/** (onde a ferramenta entrega), ambas na
pasta do relatório no seu computador. Funcionam bem dentro de uma pasta do
**Google Drive para Desktop**, para o resultado já sincronizar.

**Perfil.** A aba **Perfil** guarda as escolhas padrão de cada relatório: quais
entregas gerar, a profundidade, o modo de coleta (contínuo ou imediato), o número
de funcionários e as empresas do grupo (usados nos indicadores). Mudou de ideia?
Altere aqui; vale para os próximos ciclos. A escolha de IA externa e o
consentimento ficam na tela **IA** (seção 9).

**O painel `.html`** é um arquivo único que abre no navegador **sem internet**.
Há dois jeitos: o **modelo**, em que você arrasta a planilha `.xlsx` para dentro
da página, e o **embutido**, que já traz os dados do mês e serve para mandar por
e-mail. Ele também imprime bem (use "Imprimir > Salvar como PDF").

## 11. Antes de enviar ao cliente: conferência de 5 minutos

A ferramenta checa a estrutura dos arquivos, mas **os programas que o cliente
usa ainda não foram testados**. Antes do primeiro envio de cada tipo de arquivo:

1. **Texto (`.docx`)**: abra no Word ou no Google Docs. Veja se as datas estão em
   negrito, se o quadro-resumo e os blocos por processo estão alinhados e se não
   há aviso ao abrir. Roteiro completo: `fase2/conferencia-docx.md`.
2. **Planilha (`.xlsx`)**: abra no Excel (e no Google Sheets, se o cliente usa).
   Veja se a aba **Indicadores** mostra números (se aparecer vazia ou com valores
   antigos, peça recálculo; no Excel: Fórmulas > Calcular agora), se os gráficos
   aparecem e se a tabela de processos filtra. Roteiro completo:
   `fase2/conferencia-xlsx.md`.
3. **Painel (`.html`)**: abra em outro computador, sem internet, e confira que os
   números batem com a planilha.
4. Leia o **relatório de qualidade da base** e a lista **"conferir manualmente"**.
5. Confira, por amostragem, 3 ou 4 processos: andamento, valores e momento atual
   contra os autos.

## 12. O que fazer quando algo dá errado

| O que você vê | O que quer dizer | O que fazer |
| --- | --- | --- |
| Ao importar: aviso de formato não reconhecido (código formato_nao_reconhecido) | O arquivo não é um texto `.docx`, uma planilha `.xlsx` ou uma lista que a ferramenta entenda, ou está corrompido. | Confirme que é `.docx` (no Google Docs: Arquivo > Fazer download > Microsoft Word) ou `.xlsx`, e não um PDF ou atalho. Abra o arquivo no Word/Excel: se nem lá abre, está corrompido. Se for de outro modelo, use **Migrar de modelo**. |
| "Número de processo inválido" | O dígito verificador não bate: erro de digitação. | Corrija o número no arquivo e importe de novo. O processo fica fora enquanto isso. |
| "Duplicado" ou "mesmo processo em duas abas" | O mesmo número aparece mais de uma vez. | Confira qual linha vale e mantenha uma. A ferramenta agrupa como **vinculados** o principal, o agravo e o apenso, e os casos de "mesma ação" (reajuizamento); confira esses grupos na tela de conferência. |
| Cliente aparece com dois nomes ("Chacara" e "Chácara") | Grafias diferentes da mesma empresa. | Na conferência da migração, aceite a junção sugerida. A ferramenta nunca junta sem a sua confirmação. |
| "Campos sem destino" | Há colunas no arquivo que a ferramenta não conhece. | Confirme que nada importante está ali. Ao **migrar de modelo**, elas vão para a aba "Campos não migrados"; se forem importantes, mapeie-as na tela de mapeamento. |
| Momento atual em branco, com alerta | A ferramenta não achou evidência clara nos andamentos. | Defina o momento você mesmo, na revisão dos campos do processo, pela lista de opções; a ferramenta nunca inventa uma opção fora da lista. |
| Processo em "conferir manualmente": **captcha** | O TRT pediu o captcha e ninguém digitou. | Inicie de novo; digite o captcha quando a janela aparecer. |
| "Conferir manualmente": **segredo de justiça** | A consulta pública não mostra esses autos. | Consulte o processo direto no sistema do tribunal e lance a mão. |
| "Conferir manualmente": **não localizado** | O número não foi achado na consulta. | Confira o número; se estiver certo, consulte direto no tribunal. |
| Erro **tempo esgotado** ou **sessão expirada** | O jus.br ou o TRT demorou ou desconectou. | A fila tenta de novo sozinha algumas vezes, com espera maior a cada vez. Se persistir, confira se o PJe Office está aberto, rode **Testar acesso** e tente depois. |
| A estimativa de duração está muito longa | Na primeira vez usa valor prudente; depois mede o seu computador. | Use o modo **contínuo** (à noite), restrinja por cliente ou por lista, ou escolha profundidade *rápido*. |
| O computador desligou no meio | Nada se perdeu. | Abra o painel; a fila **retoma** e não repete o que já foi coletado. |
| Aviso de campo alterado à mão (código edicao_manual_sobrescrita) | Você tinha editado a mão um campo que a ferramenta recalcula a cada ciclo (a data da frase de fecho, o momento atual, o último andamento ou a Data-Base). | Confira o valor novo; se o antigo era o certo, corrija no arquivo gerado. O texto de andamentos que você escreveu nunca é tocado. |
| Aviso de andamento já presente (código andamento_ja_presente) | O andamento novo já estava escrito (talvez à mão). | Nada: a ferramenta não repete. Confira se o texto existente está correto. |
| A planilha abre com a aba Indicadores vazia ou com números antigos | O Excel ainda não recalculou as fórmulas. | No Excel: Fórmulas > Calcular agora. Se persistir, avise quem mantém a ferramenta e diga qual programa usou. |
| O painel `.html` abre vazio | No modo "modelo", a planilha ainda não foi arrastada para a página. | Arraste o `.xlsx`. Se o problema for no modo "embutido", avise quem mantém. |
| A planilha ou o texto do cliente "ficou diferente" do original | A ferramenta grava sempre uma **cópia**; o original não muda. | Compare a cópia com o original; se faltou algo, avise com o nome do arquivo e do processo. |
| Apareceu um aviso de confidencialidade da IA externa | Há IA externa ligada para esse cliente. | Confira em **IA** o consentimento e o registro de envios; se não foi você, desligue. |
| O painel diz "indisponível" para "enviar pelo provedor" | Não há provedor externo cadastrado e consentido. | Use o passo a passo manual de [Pedidos das iniciais](pedidos-iniciais.md). |
| Nada disto resolve | | Anote o nome do arquivo, o processo e a mensagem exata da tela, e avise quem mantém a ferramenta. **Nunca envie a pasta `projetos/`.** |

## 13. O que a ferramenta não faz

- Não protocola nem assina nada: só lê, tira print e baixa.
- Não decide sozinha o que vai ao cliente: tudo passa pela sua revisão, e
  decisão desfavorável, valor, prazo e audiência sempre passam pelos seus olhos.
- Não cobre tudo: o que ficou em "conferir manualmente" ou "só publicação"
  precisa de você.
- Não promete resultado: o texto "o que mudou neste ciclo" informa fatos.
- Não foi testada no Windows nem nos programas do cliente (Word, Excel, Google
  Docs e Sheets). O estado real de cada parte está em `fase2/STATUS.md`.

## Clientes em lote (beta2)

Ao importar um relatório, o programa propõe o cliente a partir das partes dos processos e o aplica a todos de uma vez, junto com o polo e a parte contrária. Na tela "Clientes e processos" há os botões "Identificar os clientes pelas partes dos processos" e "Aplicar a todos os sem cliente". Cliente que você definiu à mão nunca é trocado pela identificação automática. Se a mesma empresa aparecer dos dois lados do processo, o polo fica em branco para você conferir.
