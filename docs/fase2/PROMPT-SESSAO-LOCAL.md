# Roteiro para continuar no Claude Code local (Mac)

Este arquivo tem duas partes: **A) passo a passo para o usuário** e **B) o texto para colar no Claude Code local**.

---

## A) Passo a passo para o usuário

1. **Atualize o clone do projeto no Mac** (a pasta do programa que você instalou como repositório; se não tem clone, faça um):
   ```
   git clone https://github.com/daviguimaraesmendes/relatorio-andamentos.git
   cd relatorio-andamentos
   git checkout claude/gallant-pasteur-etzpu5
   git pull
   ```
   Se já tem o clone: `git status` deve estar limpo; depois `git checkout claude/gallant-pasteur-etzpu5 && git pull`.
2. **Prepare o ambiente de teste do clone** (uma vez só):
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/pip install flask playwright
   .venv/bin/python -m playwright install chromium
   ```
   (O programa instalado pelo `Instalar (Mac).command` já tem um `.venv`; se o clone for a mesma pasta do programa, pule este passo.)
3. **Separe os logs da rodada**: deixe a pasta `projetos/<relatório>/data/` acessível no Mac (ela já fica fora do git: `projetos/` está no `.gitignore`, então nada vai ao GitHub sem querer). Anote o caminho completo, por exemplo `/Users/voce/Documents/relatorio-andamentos/projetos/meu-relatorio/data`.
4. **Abra o Claude Code na pasta do clone**:
   - opção 1 (traz a conversa desta sessão): `claude --teleport` e escolha a sessão; ou, em claude.ai/code, menu da sessão → **Open in → Terminal**;
   - opção 2 (sessão nova, recomendada se o teleport der problema): apenas `claude` dentro da pasta.
5. **Cole o texto da parte B** (troque `CAMINHO_DOS_LOGS` pelo caminho do passo 3).
6. **Durante o trabalho**, o Claude local vai pedir para você: (a) autorizar leitura da pasta de logs; (b) rodar uma consulta real de teste no TRT, com o PJe Office aberto e você presente para o captcha (ele vai explicar); (c) abrir o beta3 gerado nos programas de sempre.
7. **No fim**, ele gera o `relatorio-andamentos.zip` do beta3 e faz `git push` do branch. Instale por cima como das outras vezes (`BETA-LEIAME.md`).

Cuidados: não cole senha, segredo do autenticador nem certificado no chat. Os logs podem ter nomes e números de processo; o Claude local lê, mas **nada de cliente deve ir para arquivo versionado** (as regras abaixo e os testes de confidencialidade barram isso).

---

## B) Texto para colar no Claude Code local

```
Você vai continuar a Fase 2 do projeto relatorio-andamentos (Python, em português) neste clone, no branch claude/gallant-pasteur-etzpu5.

LEIA PRIMEIRO, nesta ordem: docs/fase2/PROXIMA-SESSAO.md (estado, decisões do usuário, observações do teste prático, itens 1 a 4), docs/fase2/PLANO.md (seções 3 a 7), docs/fase2/CONTRATOS.md, BETA-LEIAME.md, docs/fase2/STATUS.md. Depois rode a suíte de testes para conhecer a base (ela deve passar; 2 testes pulados):
  PLAYWRIGHT_BROWSERS_PATH=... .venv/bin/python -m unittest discover -s tests -p "test_*.py"
(Para acelerar, rode os arquivos de teste em 4 processos paralelos; cada processo cria a sua própria pasta temporária.)

CONTEXTO: o usuário testou o beta2 num relatório real de 92 processos (muitos físicos). O scraping de jus.br e TRT já tinha sido validado por ele; o foco é montar e atualizar relatórios completos. As observações dele e as minhas propostas aceitas por ele estão em PROXIMA-SESSAO.md. Os logs e o estado da rodada estão em: CAMINHO_DOS_LOGS (pasta data/ do relatório: logs/*.log, estado_coleta.json, fila.json, diagnosticos/).

REGRAS INEGOCIÁVEIS
1. CONFIDENCIALIDADE: os logs têm dado real de cliente. Pode ler. NUNCA copie nome de cliente, parte, número de processo real, texto de autos, senha, chave ou segredo para arquivo versionado, teste, commit, mensagem de commit ou resumo. Nos documentos, use contagens e códigos ("Proc A", "TRT 7"). Testes só com dados fictícios (tests/ficticio.py, src/simulado.py; números 1234567..1234570 ou gerados em tempo de execução). Rode tests/test_confidencialidade.py antes de cada commit.
2. NÃO commite projetos/, config.json, logs, certificados, nada de dist/.
3. A chave pública do DataJud NÃO vai no repositório (config.json ou variável DATAJUD_CHAVE).
4. Poucos agentes: faça direto; use no máximo 1 agente por vez e só para trabalho grande e isolado. Commits pequenos; push no fim de cada etapa (se o push der "Internal Server Error", repita com esperas de 30 a 120 s).
5. O que não dá para provar sem o tribunal real (captcha, login, janelas do Mac) você NÃO deve afirmar que funciona: implemente, teste a lógica com doubles e peça ao usuário para validar na máquina dele, dizendo exatamente o que ele vai ver.

ETAPA 1 — ANÁLISE DOS LOGS (antes de mexer em código)
Leia todos os logs e estados da rodada e escreva docs/fase2/diagnostico-rodada1.md ANONIMIZADO, com: totais (processos, físicos, eletrônicos, coletados, manuais, erros) e taxa de sucesso só sobre eletrônicos; erros por tipo e por tribunal (jus.br, cada TRT); quantos captchas foram pedidos por TRT e em que momentos (a cada processo? ao trocar de TRT? após tempo?); o login automático do jus.br (quantas vezes falhou, mensagem exata sem dados pessoais, em que passo, se o PJe Office estava aberto, se o fluxo antigo da aba Atualizar passa pelo mesmo caminho); tempo médio por processo (eletrônico) e por etapa; processos com 2º grau/TST (quantos foram lidos, quantos tentaram e falharam sem aviso); movimentos sem tradução em movimentos.json (liste os TEXTOS dos andamentos, que são genéricos, não os dados do processo); ambiguidades da migração e clientes (o bloco "Quem é o cliente?" funcionou?). Aponte causas prováveis. Mostre o resumo ao usuário e siga.

ETAPA 2 — IMPLEMENTAÇÕES (todas aceitas pelo usuário), nesta ordem, cada uma com testes e commit:
 2.1 LOGIN DO JUS.BR: corrija a causa que os logs mostrarem (hipótese: o caminho novo, fila.ColetorReal chamado pelo painel em outra thread, executa coletor.logar fora do estado/ordem da aba Atualizar antiga; login em coletor.logar -> acesso.login_automatico). Garanta que os dois caminhos usam o mesmo login, com diagnóstico claro quando falhar (tela/mensagem salva em diagnosticos/, aviso no painel com o que o usuário deve fazer).
 2.2 CAPTCHA REPETIDO NO TRT: em trt.py, hoje coletar_processo abre uma página nova por processo (janela.nova_pagina) e a fecha no fim, e _abrir_autos_trt faz page.goto da consulta completa a cada processo. Mantenha UMA página de consulta por TRT durante toda a rodada (guardada junto do contexto do coletor/ColetorReal), pesquise o próximo número pelo formulário (buscar_numero) sem recarregar; só recarregue se o campo sumir. Documentos/PDF abrem em outra aba e fecham sem tocar a página de consulta. Registre no log "captchas pedidos nesta rodada: N por TRT" e compare com a rodada anterior.
 2.3 AVISO DE CAPTCHA QUE CHAME A ATENÇÃO (Mac): ao pedir captcha: (a) notificação do sistema via osascript ("Captcha do TRT N: precisa de você"), (b) ativar/trazer o navegador de automação (osascript activate) e abrir em tela cheia/maximizado, (c) repetir o aviso sonoro e a notificação a cada 60 s até resolver, (d) no painel, faixa vermelha fixa e atualizada automaticamente ("Precisa de você: captcha do TRT N aguardando"), (e) se não for resolvido em X minutos (configurável, padrão 10), PULAR o processo, seguir com os demais e voltar ao captcha no fim da rodada (a fila agrupa por TRT). Windows: faça o equivalente simples (msg/toast) ou deixe declarado "não testado".
 2.4 PROCESSO FÍSICO: motivo próprio "fisico" (sem autos eletrônicos) na fila (fila.py), em cobertura() e no "conferir manualmente"; relatório de cobertura mostra físicos à parte e a taxa de sucesso só sobre eletrônicos; para físico o relatório segue com o DJEN e o que o advogado lançar à mão. Detecção por: não encontrado na consulta + sem publicação/ DataJud sem registro + (se houver) indício na capa; nunca marcar físico por engano um eletrônico com erro de coleta (na dúvida, "manual").
 2.5 GRAUS NOS TRIBUNAIS TRABALHISTAS (1º, 2º, TST): (a) registrar quais graus foram lidos e quais falharam (aviso grau_nao_lido; não engolir exceções); (b) tentar o 2º grau só com indício (movimento de remessa/distribuição ao 2º grau, ou DataJud indicar grau 2), reaproveitando a página; (c) detectar o TST pelo DataJud (alias tst, mesmo número CNJ) em capa.py, trazer os movimentos e marcar "no TST"; (d) acrescentar "TST" aos graus do evento e momentos como AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA ao vocabulário (taxonomia.py) e às regras de momento; (e) NÃO implemente o coletor de documentos do TST sem antes pedir ao usuário que abra a consulta do TST e descreva (captcha? login?); deixe o gancho e a nota.
 2.6 Qualquer outro defeito que os logs mostrarem e for pequeno: corrija; se for grande, registre em PROXIMA-SESSAO.md com proposta.

ETAPA 3 — ENTREGA
 - Atualize VERSAO para 2.0.0-beta3, BETA-LEIAME.md (o que mudou e o que o usuário deve olhar), docs/fase2/PROXIMA-SESSAO.md (estado, o que ficou pendente) e docs/fase2/STATUS.md.
 - Rode a suíte completa (em paralelo) e tests/test_confidencialidade.py: tudo verde.
 - Gere o pacote com ./empacotar.sh e diga o caminho do relatorio-andamentos.zip.
 - Faça git push do branch e resuma ao usuário: o que foi feito, o que depende de validação dele no Mac (com o passo exato), riscos.

COMECE pela leitura dos documentos e pela ETAPA 1; mostre o diagnóstico antes de implementar.
```
