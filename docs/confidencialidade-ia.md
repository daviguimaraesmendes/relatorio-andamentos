# Confidencialidade e IA (texto para o README)

Este texto substitui, no README, a promessa "Nenhum documento de cliente é enviado para a internet" e a
linha "IA local ... nada é enviado a serviço de IA externo" (seções de abertura e de segurança). O WS-13
integra ao README.

## Texto proposto

**Nenhum documento de cliente é enviado para a internet, salvo quando você ativa IA externa para aquele
cliente.** Por padrão, o resumo dos documentos é feito pelo Ollama, no seu próprio computador. A IA externa
(Claude, pela API da Anthropic, ou outro serviço com API compatível com a da OpenAI) só é usada se você:

1. cadastrar o provedor na tela **IA** (nome, endereço, modelo e chave; a chave vai para o cofre do sistema e
   nunca mais aparece na tela);
2. escolher esse provedor para o relatório; e
3. marcar o consentimento do relatório ou **de cada cliente** e confirmar que entendeu o que será enviado.

Sem essas três coisas, nada sai do computador. Cada relatório e cada cliente decidem sozinhos: autorizar um
cliente não autoriza os outros, e quem tem marcação própria vale mais do que a marcação do relatório.

### O que sai do computador quando você autoriza

- **Só texto**: o texto extraído dos documentos do processo (até cerca de 9.000 caracteres por documento), o tipo
  do documento, quem o apresentou e o lado do cliente no processo.
- Com a opção **"trocar nomes e números por pseudônimos"** (ligada por padrão), nomes das partes e dos clientes
  cadastrados, CPF, CNPJ, e-mail e número de processo são trocados por marcadores (`[PARTE_1]`, `[CPF_1]`...)
  antes do envio, e a resposta volta com os nomes de volta. O mapa marcador -> nome fica **só** no computador
  (`data/ia/mapa_pseudonimos.json`, dentro da pasta do relatório). Isso reduz o risco, **não o elimina**: um nome
  escrito de forma diferente da cadastrada (apelido, abreviação, erro de digitação) passa sem troca, e o contexto
  do texto ainda pode identificar o caso.
- **Nunca sai**: print de tela, certificado digital, senha do certificado, segredo do autenticador, chave de API,
  caminhos de arquivo, planilhas, a carteira de processos. A ferramenta barra o envio se o texto contiver uma
  senha ou chave guardada no cofre, e troca por "[CAMINHO]" qualquer caminho do computador que apareça no texto.

### O que o provedor externo passa a saber

O provedor recebe o texto enviado e o seu endereço de rede, e o trata segundo os termos dele (retenção,
treinamento, localização dos servidores). Leia esses termos antes de autorizar, e avalie se o contrato com o
cliente e o dever de sigilo profissional permitem o envio. Esta ferramenta não substitui essa avaliação.

### Selo e registro

- Cada tela de resumo e de revisão mostra o selo do motor que respondeu: **local** ou **externa: <provedor>**; o
  motor também fica gravado em cada evento (`motor`).
- **Registro de envios** (tela IA e `data/ia/envios.jsonl`): para cada envio, quando, provedor, modelo, cliente,
  número de caracteres e uma impressão digital (SHA-256) do que foi enviado. O registro **não guarda o texto**.
  Se o registro não puder ser gravado, nada é enviado.
- **Sem chave, sem rede ou com erro do provedor**, o sistema cai sozinho para o motor local e avisa na tela.

### O que continua indo para a internet, como antes

O login no jus.br e nos TRTs, as consultas aos autos e, se você usar "Descoberta no DJEN", o nome do cliente para
a busca pública do CNJ.

## O que foi validado

Tudo com dados fictícios e provedores falsos (transporte HTTP e cliente do SDK substituídos nos testes). O
formato do pedido ao SDK da Anthropic foi conferido contra um servidor local de mentira, não contra a API
real. Não foi testado com a API da Anthropic, com serviço compatível com OpenAI nem com Ollama reais.
