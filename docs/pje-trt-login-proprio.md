# PJe dos TRTs com login próprio (TRT7): o que foi aprendido

Sessão de aprendizado com Davi em 2026-10-09, no PJe do TRT7 (`https://pje.trt7.jus.br`), com o Chrome dele e a
conta de um sócio do escritório (CPF e senha, "Entrar com PDPJ"). Davi digitou as credenciais; o Claude só
observou a tela e leu as respostas do portal. **Nenhum dado de cliente foi gravado**: este documento traz só a
estrutura. Os TRTs usam o mesmo PJe, então o caminho tende a valer para os demais (trocar `trt7` pelo número).

## Atualização (2026-10-09, tarde): a Consulta Processual passou a pedir captcha; novo caminho

O PJe mudou: a **Consulta Processual** (`/consultaprocessual/`) agora pede captcha mesmo pela entrada do menu. O
caminho que continua sem captcha é o **próprio PJe do advogado** (`/pjekz/`), que Davi mostrou:

1. Login no PDPJ (feito por `src/pdpj.py`, uma tentativa).
2. No painel (`/pjekz/painel/usuario-externo`), pesquisar o **número do processo** no campo "Pesquisa por número do
   processo" (ou abrir direto `/pjekz/painel/usuario-externo/acervo-geral/{numero}`): o **Acervo Geral** lista o processo.
3. Clicar no processo abre os **autos no PJe**: `/pjekz/processo/{idProcesso}/detalhe`, em outra aba.

Por trás disso (testado, só sessão, sem captcha, sem cabeçalhos especiais):

| Passo | Chamada (prefixo `https://pje.trtN.jus.br/pje-comum-api/api`) | Devolve |
| --- | --- | --- |
| número -> processo | `GET /paineladvogado/{idUsuario}/processos?numeroProcesso={CNJ com pontuação}&pagina=1&tamanhoPagina=10&tipoPainelAdvogado=1&ordenacaoCrescente=false&data={ms}&idPainelAdvogadoEnum=...` | `{resultado:[{id, numeroProcesso, classeJudicial, descricaoOrgaoJulgador, nomeParteAutora, nomeParteRe, dataAutuacao, segredoDeJustica, ...}]}` |
| andamentos e documentos | `GET /processos/id/{id}/timeline?somenteDocumentosAssinados=false&buscarMovimentos=true&buscarDocumentos=true` | lista de itens `{id, idUnicoDocumento, titulo, tipo, data, documento, expediente, nomeResponsavel, tipoPolo, documentoSigiloso, ...}` |
| documento | `GET /processos/id/{id}/documentos/id/{idDoc}/conteudo?incluirCapa=false&grau=1&incluirAssinatura=false` | o arquivo (`application/pdf`) |
| partes, audiências | `GET /processos/id/{id}/partes?...`, `/audiencias?status=...` | dados do processo |

- `{idUsuario}` é o campo `id` do `access_token` (JWT) da sessão, o mesmo que a página usa na URL do painel; o papel
  vem como `Advogado`. O token vale cerca de 1 hora.
- `tipoPainelAdvogado=1` é o Acervo Geral (`2`, Meus Expedientes; fora do escopo).
- As chamadas devem sair **de dentro da página do PJe** (`fetch` no navegador do programa), como o próprio PJe faz:
  chamadas "de fora" do navegador podem ser barradas pelo CloudFront do TRT (já vimos 403 em navegador sem tela).

A parte abaixo ("Resultado em uma frase" e adiante) descreve o caminho pela Consulta Processual, que **deixou de
servir**; fica como registro histórico.

## Resultado em uma frase

Com o login no PDPJ e **entrando pelo menu do PJe (Consulta → Consulta Processual)**, a Consulta Processual do TRT
mostra os autos **sem pedir captcha**. A ferramenta deve consultar **os processos da própria lista (a carteira)**, um
a um, por essa porta, como já faz hoje, só que logada. Painel de expedientes, acervo e "últimos andamentos" **não
são a fonte** deste programa (é uma ferramenta de relatório, não de checagem geral de andamentos).

**Atenção (testado):** abrir `/consultaprocessual/detalhe-processo/...` **direto pela URL**, mesmo com login ativo,
mostra o captcha (`/consultaprocessual/captcha/...`). O que dispensa o captcha é a **entrada pelo menu do PJe**: ali o
portal entrega os cookies `captchaToken` e `acessoTerceirosToken`, que valem por 1 hora (o front grava `captchaToken`
a partir do cabeçalho de resposta e o reenvia como `tokenCaptcha`). Passo a confirmar: que a entrada pelo menu
sempre os entrega, e o que acontece depois de 1 hora (reentrar pelo menu).

## Caminho feito à mão (o que Davi clicou)

1. `https://pje.trt7.jus.br/primeirograu/login.seam` → **Entrar com PDPJ** (CPF + senha; sem captcha nesse caminho).
2. Cai em `/pjekz/painel/usuario-externo` ("Meu Painel"): cartões **Acervo Geral**, **Meus Expedientes**,
   **Arquivados**.
3. Menu (hambúrguer) → **Consulta** → **Consulta Processual**: abre `/consultaprocessual/` em outra aba, já logada.
   Serviços ali: busca por número, **Meus processos**, **Últimos andamentos**, consulta de terceiros, pautas.
4. Do painel, clicar no número de um processo abre os **autos completos** em outra aba:
   `/pjekz/processo/{idProcesso}/detalhe` (linha do tempo à esquerda, documento à direita).

## Três portas de dados, e o que cada uma exige

| Porta | Endereço (prefixo `https://pje.trtN.jus.br`) | Captcha? | Serve para |
| --- | --- | --- | --- |
| Painel do advogado (fora do escopo) | `GET /pje-comum-api/api/paineladvogado/{idAdvogado}/processos?...` | não | listas de expedientes e acervo: **não usar**, só registro do que existe |
| Autos no PJe | `GET /pje-comum-api/api/processos/id/{id}` e `/partes`, `/audiencias`, `/timeline`, `/documentos/id/{idDoc}`, `/documentos/id/{idDoc}/conteudo` | **não** (basta a sessão) | andamentos, documentos, partes, audiências |
| Consulta processual: últimos andamentos (fora do escopo) | `GET /pje-consulta-api/api/processos/ultimosandamentos?pagina=&tamanhoPagina=&dias=` | não | checagem geral de andamentos: **não usar** |
| **Consulta processual (autos): a porta a usar** | `GET /pje-consulta-api/api/processos/dadosbasicos/{numeroSemPontuacao}`, `.../processos/{id}`, `.../processos/{id}/documentos/{idDoc}` (com `tokenCaptcha`) | não, se entrou **pelo menu do PJe**; **sim** se entrou direto pela URL | os processos da lista da ferramenta |

Detalhes observados:

- **Sessão:** as chamadas funcionam com os cookies da sessão (`credentials: include`); a consulta processual ainda
  usa um `access_token` obtido em `GET /pje-consulta-api/api/auth/pje` com o cabeçalho `X-Grau-Instancia: 1`.
- **Painel** (`.../processos`): parâmetros `agrupadorExpediente` (`I` e `N`), `pagina`, `tamanhoPagina`,
  `tipoPainelAdvogado` (2 = Meus Expedientes), `ordenacaoCrescente`, `data` (carimbo de tempo) e o id do painel.
  Cada linha traz classe e número, partes, órgão julgador, data de criação, audiência, ciência e prazo final.
- **Linha do tempo:** `.../processos/id/{id}/timeline?somenteDocumentosAssinados=false&buscarMovimentos=true&buscarDocumentos=true`
  devolve uma lista; cada item tem `id`, `idUnicoDocumento` (o código curto que aparece na tela, ex. `8672afd`),
  `titulo`, `tipo`, `data`, `documento` (é documento ou só movimento), `expediente`, `nomeResponsavel`,
  `tipoPolo`, `documentoSigiloso` e `instancia`.
- **Documento:** `.../documentos/id/{idDoc}/conteudo?incluirCapa=false&grau=1&incluirAssinatura=false` entrega o
  arquivo (PDF) do documento. `.../documentos/id/{idDoc}?incluirAssinatura=...&incluirAnexos=...&grau=...` traz os dados.
- **Últimos andamentos:** resposta paginada `{pagina, tamanhoPagina, qtdPaginas, totalRegistros, resultado[]}`; cada
  item tem `id`, `numero`, `classe`, `orgaoJulgador`, `autuadoEm`, `movimentos[] {id, descricao, atualizadoEm}`,
  `resumoPoloAtivo`, `resumoPoloPassivo` e `juizoDigital`. É o jeito mais barato de saber "o que mexeu hoje".
- **Número do processo:** a consulta usa o CNJ sem pontuação (`dadosbasicos/{numero}` devolve o `id` interno).
  O painel já traz o `id` interno de cada processo.

## Como a ferramenta deve usar isso (proposta)

1. **Login:** o programa abre o navegador e entra em *Entrar com PDPJ* com a credencial **de cada usuário** (CPF,
   senha e o segredo do autenticador/TOTP), guardada **só no cofre do sistema da máquina dele** (Keychain no Mac,
   Gerenciador de Credenciais no Windows), como já é a senha do certificado: nunca no repositório, no
   `config.json`, em log ou no pacote. Cada pessoa cadastra os seus na tela **Acesso e escritório** (campos
   `pdpj_cpf`, `pdpj_senha` e `pdpj_totp`). **O autenticador do PDPJ (`pdpj_totp`) é independente do do jus.br
   (`totp_secret`)**: as contas podem ser de pessoas diferentes, cada uma com o seu segredo. Se aparecer captcha, vale o aviso e a faixa vermelha de hoje.
2. **Entrar pelo menu:** em `/pjekz/painel/usuario-externo`, menu → **Consulta** → **Consulta Processual** (abre
   `/consultaprocessual/` em outra aba, já com os tokens). Conferir que o cookie `captchaToken` existe.
3. **Para cada processo da lista da ferramenta:** pesquisar o número na Consulta Processual e abrir o detalhe; ler a
   linha do tempo e baixar os documentos novos (PDF → texto → resumo, como hoje). O desenho de leitura atual
   (`trt.py`) continua valendo; muda só a entrada (logada, sem captcha).
4. **Renovar:** o token vale 1 hora; ao expirar (a página volta para `/consultaprocessual/captcha/...`), reentrar
   pelo menu em vez de pedir captcha. Sessão do PJe também expira por inatividade (cai em `/pjekz/acesso-negado`): refazer o login.
5. **Mantém a consulta pública** com captcha como alternativa de reserva. O que vale para o TRT7 vale para os
   demais TRTs (mesmo PJe, só muda `trt7`).
6. **Só leitura:** nenhuma chamada de escrita, nenhum protocolo, nenhuma ciência de expediente.

## Cuidados

- "Ciência" de um expediente muda o prazo: a ferramenta **não abre expediente com ciência automática**. Ao ler os
  autos pelo painel, usar só as chamadas de leitura acima; testar no TRT7 que ler a linha do tempo não registra
  ciência (nas observações desta sessão, só foram feitas chamadas de leitura).
- Ritmo humano e um processo por vez, como no restante da ferramenta.
- Endereços e nomes de campo vêm da versão 2.21.3 do PJe; podem mudar. Guardar o diagnóstico quando uma chamada falhar.
