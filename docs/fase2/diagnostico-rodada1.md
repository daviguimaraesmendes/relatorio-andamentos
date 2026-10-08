# Diagnóstico da rodada 1 (teste prático do beta2, 92 processos)

Escrito em 08/10/2026. **ANONIMIZADO**: só contagens, códigos e textos genéricos; nenhum nome, número de processo ou texto de autos.

## Situação desta análise

**A parte com números não pôde ser feita nesta sessão.** Os logs e o estado da rodada ficam no Mac do usuário (pasta do programa instalado, `projetos/<relatório>/data/`); a sessão de desenvolvimento roda em nuvem e não os alcança, e o combinado foi só ler a pasta, sem copiá-la. Em vez de adivinhar números, entreguei:

1. **a leitura do código** (abaixo), que explica as observações do usuário e aponta as causas prováveis;
2. **`src/diagnostico_rodada.py`**, que produz no Mac, em segundos, todas as tabelas pedidas já anonimizadas (seção "Como obter os números").

Nada abaixo é medida da rodada; é o que o código **garante ou permite** que tenha acontecido. Onde há hipótese, está dito.

## Como obter os números (no Mac, 1 minuto)

```
cd "/Users/davimendes/Projetos Claude Code/relatorio-clientes"
.venv/bin/python src/diagnostico_rodada.py --projeto <nome-da-pasta-do-relatório-em-projetos> --saida ~/Desktop/diagnostico-rodada.md
```

Só lê `logs/*.log`, `fila.json`, `estado_coleta.json`, `eventos.json`, `fluxo.json` e os **nomes** dos arquivos de `diagnosticos/`; não grava nada na pasta de dados. Mascara número de processo, sequências de maiúsculas (nomes de parte), valores em R$, caminhos e dígitos. **Releia antes de colar o resultado numa conversa**: a máscara é heurística. As tabelas respondem, nesta ordem, às perguntas do roteiro:

| Seção | Pergunta |
| --- | --- |
| 1 Totais | processos, coletados, manuais, erros, físicos; taxa de sucesso só sobre eletrônicos (nas versões anteriores, "não encontrado" é tirado do denominador como hipótese de físico) |
| 2 Erros | por tipo e por tribunal (fila) e mensagens de falha dos logs |
| 3 Captchas | quantos por TRT e se vieram no 1º processo do bloco do TRT ou nos seguintes |
| 4 Login | falhas, pedidos de ajuda manual, o diálogo do PJe Office, mensagens (e os `login_*.json` do beta 3 dizem o passo) |
| 5 Tempo | média, mediana e máximo por grupo (TRT, demais) da fila; por etapa, a partir do beta 3 (`tempo:` nos logs) |
| 6 Graus | tramitações lidas por grau; processos de TRT com andamento de recurso e sem o 2º grau lido |
| 7 Sem tradução | textos genéricos de andamento sem regra em `movimentos.json` |
| 8 Clientes | processos sem cliente e avisos do ciclo (ambiguidades da migração) |

O bloco "Quem é o cliente?" não deixa rastro em log: para saber se funcionou, a seção 8 mostra quantos processos ficaram sem cliente no fim (zero = funcionou).

## O que o código explica (causas prováveis)

### Captcha do TRT pedido várias vezes

Confirmado no código do beta2: `trt.coletar_processo` abria **uma página nova por processo** e a fechava no fim, e `_abrir_autos_trt` fazia `page.goto` da consulta completa **a cada processo**; a tentativa do 2º grau fazia **mais um `goto`**. Se o desafio do captcha está ligado ao carregamento da consulta (hipótese do usuário), cada processo o dispara de novo. O esperado nos números: captchas pedidos ≈ processos de TRT lidos (compare as seções 1 e 3). **Correção no beta 3**: uma página de consulta por TRT durante a rodada, pesquisa pelo formulário, documentos em aba própria (item 2.2).

### Login automático do jus.br

O que o código mostra:

- Os **dois caminhos usam a mesma função** (`coletor.logar` → `acesso.login_automatico`): a aba Atualizar roda `rodar.py` num processo à parte e o Assistente roda `fila.ColetorReal` numa thread do painel. Diferem no processo e na thread, não no login.
- No beta2, **qualquer falha ao abrir o navegador/logar virava `sessao_expirada` para cada processo**: a fila tentava o próximo, que **repetia o login inteiro** (2 tentativas automáticas e até 300 s de espera pela pessoa) e assim por diante. Uma única causa (por exemplo, PJe Office fechado) aparecia como dezenas de falhas e muitos pedidos de login ao jus.br.
- A mensagem do motivo ia só para o **terminal** (`print`), não para o painel nem para `diagnosticos/`; por isso faltaram detalhes. Hipóteses de causa, em ordem de probabilidade: PJe Office fechado ("O diálogo do PJe Office não apareceu"); permissão de Acessibilidade do Mac para o aplicativo que abre o painel (o `osascript` que preenche a senha falha em silêncio); janela do login minimizada sem a pessoa ver ("Termine o login..."); código do autenticador recusado.
- **Correção no beta 3** (item 2.1): o motivo por passo é gravado (`login_jusbr_t*.json`, tela e texto em `diagnosticos/`), a faixa vermelha do painel diz o que fazer, a falha de login **pausa a fila** (nada de login em cada processo) e o processo volta à fila sem gastar tentativa.

### Processo físico

No beta2 o físico caía em `nao_encontrado` (ou `manual`) com a mesma mensagem de um eletrônico que falhou, e entrava na taxa de sucesso. **Beta 3**: motivo próprio `fisico`, só marcado quando o DJEN e o DataJud respondem e os dois estão vazios (item 2.4).

### Graus (1º, 2º, TST)

- O **2º grau** era tentado em todo processo, por mais um `goto`, e **`except Exception: pass` engolia qualquer falha** (captcha, tempo esgotado, sessão): um recurso existente podia ficar sem leitura **sem aviso**. A seção 6 conta os candidatos (andamento de recurso e nenhum 2º grau lido).
- O **TST nunca foi consultado**; só o alias `tst` do DataJud existia em `capa.py`.
- **Beta 3**: 2º grau só com indício de recurso, falha vira o aviso `grau_nao_lido`, TST pelo DataJud (item 2.5).

### Andamentos sem tradução

A lista real vem da seção 7 do script (textos genéricos, mascarados). Cadastrar as regras em `movimentos.json` é trabalho para depois de ver a lista; não foi feito às cegas.

### Texto fraco dos resumos

O pedido ao modelo local limitava o resumo a **uma frase de até 40 palavras**, sem exigir motivo, efeito ou valores, e o resumo só entra no relatório quando o trecho de origem confere; um modelo pequeno que erra o trecho deixa só a frase de regra ("Foi proferida sentença."). **Beta 3**: pedido de até 80 palavras com motivo, efeito prático e dados concretos, exemplos de redação do escritório (`estilo.md`), alerta quando o resumo vem curto (item "Texto da IA").

## O que falta para fechar esta análise

Rodar `diagnostico_rodada.py` na pasta real e conferir os números contra as hipóteses acima, principalmente: (a) captchas ≈ processos de TRT? (b) quantos "não encontrado" (físicos) em cada tribunal; (c) quantos candidatos a 2º grau sem leitura; (d) a lista de andamentos sem tradução.
