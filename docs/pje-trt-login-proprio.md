# PJe dos TRTs com login próprio (TRT7): o que foi aprendido

Sessão de aprendizado com Davi em 2026-10-09, no PJe do TRT7 (`https://pje.trt7.jus.br`), com o Chrome dele e a
conta de um sócio do escritório (CPF e senha, "Entrar com PDPJ"). Davi digitou as credenciais; o Claude só
observou a tela e leu as respostas do portal. **Nenhum dado de cliente foi gravado**: este documento traz só a
estrutura. Os TRTs usam o mesmo PJe, então o caminho tende a valer para os demais (trocar `trt7` pelo número).

## Resultado em uma frase

Com o login no PJe, a ferramenta pode ler a **lista de processos, os andamentos e os documentos** pelo próprio
PJe do advogado (`/pjekz/` e `/pje-comum-api/`), **sem captcha**, em vez de passar pela consulta pública
(`/consultaprocessual/`), que pede captcha para abrir os autos.

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
| Painel do advogado | `GET /pje-comum-api/api/paineladvogado/{idAdvogado}/processos?...` | não | listas: Meus Expedientes, Acervo Geral, Arquivados |
| Autos no PJe | `GET /pje-comum-api/api/processos/id/{id}` e `/partes`, `/audiencias`, `/timeline`, `/documentos/id/{idDoc}`, `/documentos/id/{idDoc}/conteudo` | **não** (basta a sessão) | andamentos, documentos, partes, audiências |
| Consulta processual | `GET /pje-consulta-api/api/processos/ultimosandamentos?pagina=&tamanhoPagina=&dias=` | não | todos os processos do advogado com movimento recente, numa chamada |
| Consulta processual (autos) | `GET /pje-consulta-api/api/processos/{id}` e `/documentos/{idDoc}` | **sim** (desafio de captcha; o token vale 1 hora) | evitar: é o caminho que o programa usa hoje |

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

1. **Login:** o programa abre o navegador dele e entra em *Entrar com PDPJ* com a credencial **de cada usuário**,
   guardada **só no cofre do sistema da máquina dele** (Keychain no Mac, Gerenciador de Credenciais no Windows),
   como já é a senha do certificado: nunca no repositório, no `config.json`, em log ou no pacote. Cada pessoa
   cadastra a sua na tela **Acesso**. Se aparecer captcha ou autenticador, vale o mesmo aviso e a faixa vermelha
   de hoje (quem estiver no computador resolve). Ainda a confirmar: a credencial a usar será a de uma conta
   do escritório que concentra as publicações; cada usuário decide qual conta cadastra.
2. **Descobrir o que mudou:** `ultimosandamentos` (ou o painel) lista, numa chamada, os processos com movimento
   no período, no lugar de consultar processo por processo.
3. **Ler os autos:** `timeline` dos processos que mudaram, e `conteudo` dos documentos novos (PDF → texto → resumo,
   como hoje).
4. **Mantém a consulta pública** (com captcha) como alternativa de reserva, e o que for novo no TRT7 vale para
   os outros TRTs (mesmo PJe).
5. **Só leitura:** nenhuma chamada de escrita, nenhum protocolo, nenhuma ciência de expediente.

## Cuidados

- "Ciência" de um expediente muda o prazo: a ferramenta **não abre expediente com ciência automática**. Ao ler os
  autos pelo painel, usar só as chamadas de leitura acima; testar no TRT7 que ler a linha do tempo não registra
  ciência (nas observações desta sessão, só foram feitas chamadas de leitura).
- Ritmo humano e um processo por vez, como no restante da ferramenta.
- Endereços e nomes de campo vêm da versão 2.21.3 do PJe; podem mudar. Guardar o diagnóstico quando uma chamada falhar.
