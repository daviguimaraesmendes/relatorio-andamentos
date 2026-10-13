# Relatório de Andamentos

Prepara e atualiza os relatórios de andamento processual dos clientes a partir
dos autos eletrônicos. A ferramenta entra **no jus.br** (Justiça Estadual e
Federal, com o seu certificado digital) e **no PJe da Justiça do Trabalho**
(1º grau, 2º grau e TST, com o seu login do PDPJ), encontra os andamentos e
documentos novos de cada processo (inclusive os que ainda não saíram no
Diário), resume o teor com uma inteligência artificial que roda **no seu
próprio computador** (ou, se você ligar, no Claude) e deixa tudo numa fila de
revisão. Só o que você aprova entra no relatório.

O relatório pode sair em três formas: **texto** (`.docx`, para o cliente ler),
**planilha** (`.xlsx`, com indicadores, passivo contingente e provisão) e
**painel** (`.html`, para a diretoria).

Nenhum documento de cliente é enviado para a internet, **salvo quando você
ativa IA externa para aquele cliente** (veja a seção 8). A senha do
certificado e o segredo do autenticador ficam no cofre do próprio sistema
operacional.

Cada relatório (um grupo de clientes ou um cliente só) é independente e tem a
sua aba no painel.

> **Versão atual: 2.0.0-beta8 (versão de teste).** Os quatro fluxos da seção 6,
> o texto `.docx`, a planilha, o painel `.html`, a fila de coleta e a IA externa
> opcional existem e foram exercitados com dados fictícios; a leitura dos
> processos trabalhistas pelo PJe (1º grau, 2º grau e TST) e a migração da
> planilha de contingências já foram testadas com dados reais, mas o piloto
> completo com o Claude ainda está por fazer. O que mudou em cada versão está em
> `BETA-LEIAME.md`; o que está pronto e o que depende de teste real, em
> `docs/fase2/STATUS.md`. O passo a passo para quem vai usar está em
> `docs/guia-fase2.md`.

---

## 1. O que você precisa ter antes

| Item | Observação |
| --- | --- |
| Mac (macOS) ou Windows 10/11 | No Mac, a ferramenta foi testada em uso real. No Windows, a instalação e o login estão preparados, **mas ainda não foram testados** (veja a seção 11). |
| Certificado digital A1 instalado no **PJe Office Pro** | O mesmo que você usa para peticionar. O PJe Office precisa estar aberto quando a ferramenta for ao jus.br. |
| Autenticador do jus.br configurado no celular | E o **segredo** dele (veja abaixo). É o que permite à ferramenta gerar o código de 6 dígitos sozinha. |
| Para processos **trabalhistas**: login do **PDPJ** | CPF, senha e o **segredo do autenticador do PDPJ**. Pode ser de outra pessoa do escritório e **é um segredo diferente do do jus.br**. Sem isso, os processos do trabalho ficam "conferir manualmente". |
| Cerca de 6 GB livres e internet na instalação | Para o modelo de IA (2 a 3,5 GB) e o navegador de automação. |

### Como obter o segredo do autenticador

O segredo é o código de letras e números (16 a 32 caracteres) que o jus.br
mostra quando você cadastra um aplicativo autenticador. Na tela de cadastro
com o QR Code, a opção **"Não foi possível ler o QR Code?"** exibe esse código
em texto.

- Se você ainda vai cadastrar o autenticador: copie esse código antes de
  concluir o cadastro e use o mesmo código no app do celular e na ferramenta.
- Se o autenticador já está cadastrado e você não tem o código: refaça o
  cadastro do autenticador na sua conta e, desta vez, copie o código.

Trate esse código como uma senha: quem o tiver gera os seus códigos de acesso.
A ferramenta o guarda no cofre do sistema e nunca o mostra de volta.

## 2. Instalação no Mac

1. Descompacte o arquivo `relatorio-andamentos.zip` (por exemplo, em Documentos).
2. Dois cliques em **`Instalar (Mac).command`**.
   - Se o Mac avisar que o arquivo é de um desenvolvedor não identificado:
     clique com o botão direito no arquivo, escolha **Abrir** e confirme.
3. Responda às perguntas na janela do Terminal (`s` para sim). O instalador
   pergunta antes de cada download: Homebrew (se faltar; pede a senha do Mac),
   Python, leitura de documentos digitalizados (OCR), o motor de IA (Ollama) e
   o modelo de IA. Para o uso completo, responda `s` a todas.
   - Nas perguntas do próprio Homebrew, responda `y` (ele não aceita `s`).
4. No fim, o painel abre no navegador. Siga para a seção 4.

## 3. Instalação no Windows

1. Descompacte o arquivo `relatorio-andamentos.zip` (por exemplo, em Documentos).
2. Dois cliques em **`Instalar (Windows).bat`**.
   - Se o Windows mostrar "O Windows protegeu o computador": clique em
     **Mais informações** e depois em **Executar assim mesmo**.
3. Responda às perguntas (`s` para sim). O instalador usa o `winget` (que já
   vem no Windows 10/11) para instalar o Python e o Ollama, se faltarem, e
   baixa o modelo de IA.
4. No fim, o painel abre no navegador. Siga para a seção 4.

No Windows, documentos digitalizados (imagem, sem texto) não são lidos
automaticamente: entram na revisão com alerta, para leitura no próprio PDF.

## 4. Primeiro uso (cerca de 10 minutos)

O painel fica em **http://127.0.0.1:5072**. Para abri-lo de novo depois: dois
cliques em **`Abrir painel.command`** (Mac) ou **`Abrir painel.bat`**
(Windows). Deixe a janela do Terminal (Mac) ou do Prompt (Windows) aberta
enquanto usa o painel.

0. **Configurar tudo** (botão na tela **Início**): uma tela guiada para cadastrar,
   num só lugar, os seus dados, a conta do PDPJ, o certificado do jus.br, a IA e
   o escritório. É o jeito mais simples de começar; os itens abaixo descrevem o
   que cada parte faz.
1. **Acesso e escritório** (link no canto superior direito):
   - senha (PIN) do certificado, a mesma que você digita no PJe Office;
   - segredo do autenticador. Depois de salvar, o painel mostra o código de 6
     dígitos daquele momento: confira se é igual ao do app no celular;
   - quem assina pelo escritório: um por linha, o nome completo e o número da
     OAB (ex.: `Fulano de Tal` e `12.345`). É assim que a ferramenta escreve
     "apresentamos" nas petições do escritório e "a parte contrária
     apresentou" nas demais;
   - clique em **Salvar** e depois em **Testar acesso** (com o PJe Office
     aberto). Deve aparecer "ACESSO OK".
2. **+ Novo relatório**: dê um nome (ex.: "Grupo Exemplo").
3. **Clientes e processos**:
   - cadastre os clientes com a razão social exatamente como aparece nos
     processos e, em "variações", siglas e nomes fantasia;
   - em "Importar processos", cole os números (de uma lista, de um e-mail) ou
     envie uma planilha, escolha o cliente e o polo, e importe. Números com
     erro de digitação são recusados e listados;
   - "Completar pelo DJEN" preenche a parte contrária dos processos que têm
     publicação.
4. **Configuração**: indique a planilha do último relatório enviado (o
   arquivo `.xlsx`) e a data dele.
5. **Atualizar**: na primeira vez, informe a data do último relatório; a
   ferramenta só traz o que veio depois dela. O navegador trabalha minimizado
   no canto da tela; acompanhe pelo painel.
6. **Revisar**: confira cada linha com o print, o documento e o trecho em que
   o resumo se baseia. Aprove, corrija ou descarte.
7. **Planilha**: gere a planilha do mês. Ela é uma cópia da anterior com os
   andamentos aprovados acrescentados na coluna **Andamentos** da aba
   **Processos**; gráficos, tabelas dinâmicas e demais abas ficam iguais. A
   planilha nova vira a referência do mês seguinte.

## 5. Dia a dia

| Quando | O que fazer |
| --- | --- |
| Para atualizar um relatório | Abrir o painel, escolher a aba do relatório, **Atualizar**, depois **Revisar**. |
| No fechamento do mês | **Planilha**: gerar e conferir antes de enviar ao cliente. |
| Uma vez por semana (opcional) | **Atualizar > Conferência**: separa, por responsável, o que entrou nos autos e ainda não foi para relatório, com PDFs e prints. |
| Processo novo do cliente | **Clientes e processos**: importar o número, ou "Descoberta no DJEN" para achar os que ficaram de fora. |

Nada começa sozinho: a ferramenta só trabalha quando alguém clica. (No modo
"contínuo" da Fase 2, depois que você inicia, a coleta segue sozinha dentro da
janela de horário que você definiu, por exemplo à noite, e retoma no dia
seguinte; o computador e o painel precisam estar ligados.)

### Justiça do Trabalho (TRTs)

Processos trabalhistas (com `.5.` no número, no padrão
`NNNNNNN-DD.AAAA.5.TT.VVVV`) são lidos **dentro do PJe do advogado**, depois do
login no **PDPJ** com o seu CPF, senha e autenticador (cadastrados em
**Configurar tudo**). Não há captcha. A ferramenta lê o **1º grau**, o **2º
grau** e o **TST**, e a capa (vara, classe, partes, ajuizamento, município)
vem do próprio PJe.

- **O 2º grau e o TST só são lidos quando há sinal de recurso**: o PJe do 1º
  grau mostra que o processo está em outra instância, ou o campo **Grau de
  tramitação** do relatório diz "2º grau" ou "TST". A ferramenta atualiza esse
  campo a cada coleta e nunca troca o que você escreveu.
- **O login é tentado uma única vez por rodada.** Se falhar, a ferramenta para e
  trava novas tentativas, para não bloquear a conta; você confere os dados e
  libera pela tela **Acesso e escritório**.
- Processos da Justiça **Estadual e Federal** continuam entrando pelo jus.br
  com o certificado, e o login do jus.br só acontece quando algum processo
  precisa dele.

## 6. Os quatro fluxos da Fase 2

Na tela inicial do painel a pergunta é **"O que você quer fazer?"**, com quatro
botões. O passo a passo, com o que aparece em cada tela, está em
`docs/guia-fase2.md`; aqui vai o resumo.

| Botão | Para que serve | O que você entrega e o que recebe |
| --- | --- | --- |
| **Importar relatórios existentes** | Trazer para a ferramenta os relatórios que o escritório já tem (texto `.docx`, planilha `.xlsx`, lista de números) e começar a acompanhar a partir deles. | Você solta os arquivos; confere o que foi lido (ambiguidades, números inválidos, duplicados, clientes com grafia diferente); confirma. O que já está escrito no relatório antigo **não é recoletado**: vira o histórico. |
| **Elaborar relatório inicial** | Preparar o primeiro relatório de processos novos. | Você escolhe o formato (texto, planilha, painel), a profundidade (rápido, padrão, completo) e o modo de coleta (contínuo, em janelas de horário, ou imediato, com aviso da duração estimada). Recebe a pasta de saída com os arquivos, um relatório de qualidade da base e a lista "conferir manualmente". |
| **Atualizar relatório** | Acrescentar o que veio depois da última data-base. Há dois jeitos de trabalhar, escolhidos na tela: **Montagem completa** (coleta tudo desde o início, resume com IA, monta texto, planilha e painel; é o modo pesado, para montar o relatório) e **Atualização leve** (só o que mudou desde a última vez; é o modo do dia a dia). O atalho **Atualizar planilha e painéis agora (sem coletar)** refaz a planilha e o painel só com o que já está aprovado, sem tribunal, sem login e sem IA. | Você solta o último `.docx` e/ou `.xlsx`; a ferramenta coleta, resume, você revisa, e ela grava **cópias novas** dos arquivos (o original nunca é sobrescrito) mais um resumo "o que mudou neste ciclo". |
| **Migrar de modelo** | Converter um relatório que está num formato diferente (inclusive planilhas "desformatadas", como a de **contingências jurídicas**) para os modelos da ferramenta. | Você solta o arquivo; confere a tela de mapeamento (coluna do arquivo antigo, campo da ficha, coluna do modelo novo); o que não tem destino vai para uma aba "Campos não migrados", sem se perder. A ferramenta mostra o quadro **"O que falta para a transição"** (o que veio, o que ela busca nos tribunais, o que deduz pelas regras ou IA e precisa da sua confirmação, e o que só você sabe); o mesmo quadro vai para a aba **Faltas da migração** da planilha. |

Regras que valem nos quatro fluxos:

- **Só acrescenta.** O texto que o advogado escreveu à mão no relatório não é
  reescrito; se o trecho recente foi alterado à mão, a ferramenta avisa e não
  duplica. O arquivo que você envia nunca é sobrescrito: sai sempre uma cópia.
- **Revisão humana obrigatória.** Decisão desfavorável, mudança de resultado,
  qualquer valor em dinheiro, audiência e prazo **sempre** passam pelos seus
  olhos, mesmo na aprovação em lote. A aprovação em lote dos "verdes" vale só
  para o que não tem nenhum alerta e sempre deixa uma amostra para conferência
  manual. Na Triagem há também **Aprovar todas as atualizações**, que mostra
  quantas linhas têm alerta e só aprova depois de você marcar "li os alertas";
  o que é bloqueado por regra (sem frase, sem texto legível) continua de fora.
- **Probabilidade, valor estimado, valor economizado e resultado** aparecem
  como **sugestão** (marcada como tal, com o trecho de origem e as ressalvas).
  Nada disso é gravado como definitivo sem a sua aprovação, e o que você
  escreveu nunca é sobrescrito.
- **Um processo por vez contra o jus.br e os TRTs**, em ritmo humano, como na
  Fase 1. A escala vem de rodar sem acompanhamento (janela noturna, retomada
  depois de uma queda), não de abrir várias sessões.
- **Cobertura.** O relatório de cobertura diz quantos processos foram
  coletados, quantos só têm publicação (DJEN) e quantos ficaram para
  conferência manual (captcha, segredo de justiça, não localizado).

## 7. Como a ferramenta escreve

Exemplos de linhas geradas, no estilo das planilhas do escritório:

> Em 18/08/2026 foi proferido despacho determinando que o processo volte a tramitar normalmente, após a suspensão anterior. Audiência: 06/10/2026 11:40.
>
> Em 17/08/2026 foi cancelada a audiência una de 28/10/2026 09:15.

- **Quem fez e o quê** sai por regra fixa: tradução dos andamentos
  (`movimentos.json`) e autoria pela assinatura do documento.
- **O conteúdo** é resumido pela IA (por padrão, a local), do ponto de vista do
  cliente (ela sabe quem é o cliente, o polo e a parte contrária) e precisa
  citar o trecho do documento em que se baseou.
- **Ruído descartado automaticamente**, com o motivo visível na ferramenta: a
  mesma informação repetida no mesmo dia ou em dias seguidos, documento
  repetido, andamento que só anuncia uma decisão já resumida, intimações e
  certidões de rotina.
- Processo com recurso: o 1º grau, o 2º grau e o TST são lidos quando há sinal
  de recurso (veja a seção 5), e o texto diz "no 2º grau" ou "no TST" quando o
  andamento é do recurso.
- **Momento atual** do processo (aguardando sentença, cumprimento de sentença,
  trânsito em julgado...) sai de uma lista fechada, primeiro por regra sobre os
  andamentos e só depois pela IA; sem evidência, fica em branco com alerta.

### Alertas na revisão (por regra, não pela IA)

| Alerta | Quando |
| --- | --- |
| Trecho não encontrado | O trecho que a IA citou não existe no documento. |
| Prazo ou data | Número informado pela IA que não aparece no documento. |
| Data de audiência | A data informada não aparece junto da palavra "audiência" (ou é a data da certidão ou da assinatura). |
| Desfavorável | A IA classificou o resultado como desfavorável ao cliente: avalie contato pessoal antes de enviar. |
| Nome ausente | O nome do cliente não aparece no documento. |
| Polo não informado | Sem o polo, o ponto de vista do resumo não é confiável. |
| Texto do print | O documento não baixou; o resumo saiu da parte visível na tela. |
| Autoria não identificada | Petição sem assinatura reconhecível. |
| Andamento sem tradução | Texto de andamento ainda não cadastrado em `movimentos.json`. |

**A revisão humana é obrigatória.** O modelo de IA local é pequeno (roda no
notebook) e às vezes erra o sentido do documento; o trecho de origem fica logo
abaixo de cada resumo para a conferência. Cada resumo traz o selo do motor que
o produziu (local ou externo).

## 8. IA: local por padrão, externa só se você ativar

- **Padrão: IA local** (Ollama, no próprio computador). Nada sai do computador.
- **Opcional: IA externa**, para resumir melhor onde o modelo local é fraco.
  Há três tipos de provedor, e você escolhe qual cadastrar:
  1. **Claude pela API da Anthropic** (nome, modelo e chave de API);
  2. **Claude pelo Claude Code deste computador**, **sem chave de API**: usa o
     Claude Code já instalado e conectado à sua conta (`/login`), e o consumo
     entra no limite da sua assinatura. Modelo e caminho do programa são
     opcionais (em branco, a ferramenta procura sozinha e usa o padrão da
     conta). Roda sem ferramentas, sem ler arquivos seus e sem gravar sessão, e
     o texto vai pela entrada padrão, não pela linha de comando. **Não é IA
     local**: o texto continua indo à Anthropic, só que pela assinatura e não
     pela API, com termos de uso e de retenção que podem ser diferentes. Vale
     o mesmo aviso de confidencialidade abaixo;
  3. **Outro serviço com API compatível com a da OpenAI** (endereço, modelo, chave).

  Qual modelo escolher: para **resumir documentos de processo**, o **Sonnet 5.5
  em esforço médio** foi o melhor equilíbrio no nosso teste; o **Haiku 5.5
  médio** basta para mapear colunas, normalizar valores e extrair campos de
  textos curtos (e é aceitável em certidões e intimações). Em sentenças,
  acórdãos e valores, sempre confira. Números, limites e como configurar:
  `docs/claude-no-projeto.md`.

  Você cadastra o provedor no painel (tela **IA**) e
  **liga por relatório e, havendo vários clientes, por cliente**. Sem ligar
  explicitamente, **nada** é enviado.
- **O que sai quando está ligada:** somente o **texto extraído** dos documentos
  daquele cliente (nunca prints, certificado, senha ou caminhos de arquivo). Há
  a opção de **pseudonimizar** nomes de partes e números de documento antes do
  envio; o mapa para desfazer fica só no seu computador.
- **Registro local** de cada envio (quando, para qual provedor, qual modelo, quantos
  caracteres e uma impressão digital do conteúdo; o texto do cliente não é guardado no registro).
- **Selo visível** nas telas de resumo e de revisão ("local" ou "externa: <provedor>").
- **Sem chave, sem rede ou com erro do provedor**, a ferramenta volta sozinha
  para o motor local e avisa. Os documentos que ficaram só com a frase
  automática (sem IA) podem ser resumidos depois, pelo botão **"Resumir os que
  ficaram sem IA"** na tela Revisar, com a estimativa de chamadas antes de confirmar.
- A chave da API fica no cofre do sistema, como a senha do certificado, e nunca
  é mostrada de volta.

**Aviso de confidencialidade.** Ao ligar a IA externa, trechos de documentos de
processo do cliente passam a ser enviados à empresa do provedor, fora do seu
computador. Antes de ligar, confira o dever de sigilo profissional, o contrato
e a política do escritório com aquele cliente e os termos do provedor sobre
guarda e uso dos dados. O mesmo vale para o "kit de pedidos das iniciais"
(`docs/pedidos-iniciais.md`): ali **você mesmo** anexa os PDFs das petições na
IA que escolher, fora do programa. O que a ferramenta promete é só o que ela
própria faz: nada sai sem a sua marcação explícita, e tudo o que sai fica
registrado. Detalhes: `docs/confidencialidade-ia.md`.

## 9. Segurança

- **Só leitura.** A ferramenta lê, tira print e baixa. Nenhum clique de
  protocolo, assinatura ou peticionamento.
- **Segredos no cofre do sistema** (Keychain no Mac, Gerenciador de
  Credenciais no Windows). Não ficam em arquivo, não aparecem em tela nem em
  registro de diagnóstico.
- **Dados de clientes ficam no computador**, na pasta `projetos/`. Mantenha a
  criptografia do disco ligada (FileVault no Mac, BitLocker no Windows) e
  **nunca envie a pasta `projetos/`** a outra pessoa. O pacote gerado por
  `empacotar.sh` nunca a inclui.
- **Painel só local.** Atende apenas em 127.0.0.1 (este computador), com token
  nos formulários e sem carregar nada de endereços externos (as páginas, os
  relatórios HTML e os painéis são autônomos).
- **O que vai para a internet:** o login no jus.br e no PDPJ (PJe dos TRTs e do TST), as consultas aos
  autos, o nome do cliente para a busca pública do CNJ se você usar "Descoberta
  no DJEN" e, **somente se você ligar IA externa**, o texto descrito na seção 8.
- **Captcha e telas desconhecidas** param a tarefa e pedem ação humana; nada é
  contornado.
- **Termos de uso.** O gov.br e o jus.br proíbem acesso automatizado nos seus
  Termos de Uso. O uso desta ferramenta é um risco assumido por quem a usa, em
  ritmo humano (pausas entre processos, um processo por vez).

## 10. Problemas comuns

| Situação | O que fazer |
| --- | --- |
| "Testar acesso" não conclui | Confira se o PJe Office está aberto e com o certificado. Se aparecer uma janela pedindo ação (captcha, confirmação), conclua nela. |
| O código do painel é diferente do celular | O segredo foi digitado errado ou é de outro cadastro: salve de novo em **Acesso e escritório**. |
| O navegador diz que não consegue acessar 127.0.0.1:5072 | O painel não está aberto: dois cliques em `Abrir painel`. |
| "Processo em segredo de justiça" (TRT) | A consulta processual não mostra esses autos; o processo fica como "conferir manualmente". |
| "Processo não encontrado na consulta do jus.br" | Confira o número; se estiver certo, o processo fica para conferência manual. |
| Mac: "desenvolvedor não identificado" | Botão direito no arquivo > **Abrir** > confirmar. |
| Windows: o login para no diálogo do PJe Office | No Windows o preenchimento automático desse diálogo ainda não foi testado. Digite a senha na janela do PJe Office; a ferramenta segue depois. Avise quem mantém a ferramenta. |
| Um arquivo `.docx` ou `.xlsx` enviado "não foi reconhecido" | Confirme que é o arquivo exportado (Google Docs: Arquivo > Fazer download > Microsoft Word) e não um atalho ou PDF; se for de outro modelo, use **Migrar de modelo**. Mais casos no guia (`docs/guia-fase2.md`, "o que fazer quando algo dá errado"). |

## 11. Para quem mantém

Situação por plataforma e por parte (atualizada em 13/10/2026):

| Parte | Situação |
| --- | --- |
| Mac: instalação, login (certificado + autenticador), jus.br, resumo, revisão, planilha (Fase 1) | Testado em uso real |
| Mac: login do PDPJ e leitura do processo trabalhista pelo PJe (1º grau, 2º grau e TST), capa pelo PJe, "Configurar tudo" | Testado em uso real (TRT7 e TST), sem captcha |
| Mac: migração da planilha de contingências (campos de passivo e provisão, quadro "o que falta", dois modos de atualização) | Testado com a planilha real; coleta e resumo por IA nessa planilha ainda por testar |
| Claude pelo Claude Code deste computador | Escrito e testado só com simulação; teste real depende do `/login` do Claude Code |
| Mac: demais partes dos quatro fluxos da Fase 2 (fila, escritores `.docx`/`.xlsx`/`.html`, IA externa) | Exercitado com dados fictícios e coletor simulado (ver `docs/fase2/STATUS.md`); piloto completo pendente |
| Windows: instalador (`instalar.ps1`), preenchimento do diálogo do PJe Office (pywinauto), atalhos `.bat` e a Fase 2 inteira | Escrito, **não testado** em máquina Windows |
| Linux (ambiente de desenvolvimento na nuvem) | Testes automáticos com dados fictícios, sem rede, sem certificado e sem jus.br; abre `.docx`/`.xlsx` no LibreOffice, não no Word nem no Excel |
| Arquivos gerados no Word, no Google Docs, no Excel (Windows e Mac) e no Google Sheets | **Não testados**: use os roteiros de conferência de `docs/fase2/` antes de enviar a um cliente |
| OCR de documentos digitalizados | Mac com Homebrew; no Windows, não |
| Conferência semanal | jus.br; processos trabalhistas ainda não (ficam "conferir manualmente") |
| Cobertura real por tribunal, tempo real de coleta, qualidade do modelo local | A medir no piloto |

```
relatorio-andamentos/
├── Instalar (Mac).command  /  Instalar (Windows).bat   instalação
├── Abrir painel.command  /  Abrir painel.bat           painel
├── instalar.sh  /  instalar.ps1                        o que os instaladores rodam
├── rodar.sh  /  conferir.sh                            o mesmo que os botões, pelo Terminal do Mac
├── empacotar.sh                                        gera o .zip sem dados de clientes (e o confere)
├── requirements.txt                                    dependências Python (versões mínimas)
├── config.exemplo.json                                 porta, modelo de IA, ritmo da coleta (o config.json fica fora do pacote)
├── movimentos.json                                     tradução dos andamentos (editável)
├── src/                                                código (Python, módulos planos em português)
│   ├── ficha.py  /  taxonomia.py  /  consolidar.py     ficha de cada processo, vocabulários, consolidação
│   ├── leitores/                                       leem relatórios existentes (.docx, .xlsx, listas)
│   ├── escritores/                                     gravam o .docx (texto), o .xlsx (planilha) e o .html (painel)
│   ├── modelos/                                        modelos padrão sanitizados (sem nome, número ou valor)
│   ├── fila.py  /  capa.py                             fila de coleta em massa e dados de capa do processo
│   ├── pdpj.py  /  pje_trt.py  /  acesso.py             login do PDPJ, leitura pelo PJe (1º, 2º grau, TST), cofre de credenciais
│   ├── fluxos.py  /  lacunas.py                         os fluxos e modos de trabalho; quadro "o que falta" da migração
│   ├── sintese.py  /  julgamento.py  /  triagem.py     momento atual e narrativa, sugestão de julgamento, triagem
│   ├── qualidade.py  /  historico.py  /  quadros.py    verificador da base, retrato mensal, quadros analíticos
│   ├── pedidos.py  /  ia.py                            kit de pedidos das iniciais, provedores de IA
│   └── painel/                                         telas do painel (uma por arquivo)
├── tests/                                              testes automáticos (não tocam em dados reais)
├── tools/benchmark_modelos/                            corretores do teste de modelos do Claude (sem dados reais)
├── CLAUDE.md  /  BETA-LEIAME.md  /  VERSAO             regras para o Claude Code, notas de cada versão, versão atual
├── docs/                                               guias (guia-fase2.md, claude-no-projeto.md, pje-trt-login-proprio.md,
│                                                       identidade-visual.md, confidencialidade-ia.md, pedidos-iniciais.md)
│   └── fase2/                                          plano, contratos, status e roteiros de conferência
└── projetos/<relatório>/                               dados de cada relatório (fica fora do pacote)
```

Pelo terminal, de dentro de `src/`, com o Python do ambiente
(`../.venv/bin/python` no Mac, `..\.venv\Scripts\python.exe` no Windows):

```
python rodar.py --projeto <pasta> [--desde DD/MM/AAAA] [--processo N1,N2]   atualizar
python conferencia.py --projeto <pasta> [--dias 7]                         conferência
python coletor.py --testar-login                                           testar acesso
python coletor.py --explorar <número>        diagnóstico da tela dos autos (jus.br)
python trt.py --explorar <número>            diagnóstico da consulta do TRT
```

### Testes

Da raiz do projeto (todos usam dados fictícios gerados na hora; nenhum faz
chamada de rede nem usa o certificado):

```
.venv/bin/python -m unittest discover -s tests          # tudo
.venv/bin/python -m unittest tests/test_pipeline.py tests/test_painel.py tests/test_ficha.py tests/test_ficticio.py tests/test_simulado.py
.venv/bin/python tests/test_contratos.py --matriz       # que módulos da Fase 2 já existem e se seguem o contrato
```

- `tests/test_autos.py` (e `tests/test_dashboard.py`, quando existir) precisam
  do Playwright com o Chromium instalado; sem ele, `test_autos.py` falha.
- Os testes transversais (`test_confidencialidade.py`, `test_desempenho.py`,
  `test_contratos.py`, `test_empacotamento.py`) **pulam com uma mensagem clara**
  o que depende de módulo ainda inexistente. Em computador lento:
  `RELATORIO_DESEMPENHO_FATOR=3`.
- `test_confidencialidade.py` varre o que está versionado atrás de número de
  processo fora do permitido, nome de cliente cadastrado neste computador,
  segredo e domínio externo em HTML gerado.

Para gerar o pacote: `./empacotar.sh` (copia só o que deve ir, confere o pacote
e recusa gerá-lo se encontrar nome de cliente cadastrado, número de processo
real, segredo, certificado ou referência externa em modelo HTML; o texto dentro
dos `.docx`/`.xlsx` também é lido).
