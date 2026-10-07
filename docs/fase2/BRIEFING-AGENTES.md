# Briefing comum dos agentes (Onda 1)

Você é um agente de construção da Fase 2 do projeto `relatorio-andamentos` (Python, em português). O coordenador é a sessão principal. Execute **um** workstream de `docs/fase2/WORKSTREAMS.md`.

## Antes de começar (nesta ordem)

1. **Alinhe o worktree** (ele nasce no commit inicial): `git reset --hard claude/gallant-pasteur-etzpu5` (ainda não há trabalho seu; é seguro). Se `git status` mostrar arquivos `.bat`/`.ps1` modificados só por fim de linha, rode `git checkout -- .` e repita o reset.
2. Leia `docs/fase2/PLANO.md`, `docs/fase2/CONTRATOS.md`, `docs/fase2/WORKSTREAMS.md` (a sua seção, inteira), `docs/fase2/fixtures.md`, `docs/fase2/painel-modulos.md` e o código citado na sua seção.
3. Rode a base de testes para conhecer o ponto de partida: `python3 -m unittest tests/test_pipeline.py tests/test_painel.py tests/test_ficha.py tests/test_ficticio.py tests/test_simulado.py` (`tests/test_autos.py` falha por falta de Playwright; ignore, a menos que o seu workstream o exija).

## Regras

- **Só mexa nos arquivos que a sua seção lista** (e nos novos que ela autoriza). Arquivo de outro workstream, `ficha.py`, `docs/fase2/CONTRATOS.md`, `PLANO.md` e `WORKSTREAMS.md`: **não edite**. Se achar defeito ou precisar de mudança de contrato, escreva `docs/fase2/RFC-<assunto>.md` (problema, proposta, impacto) e siga com a melhor suposição documentada.
- **Não dê push.** Faça commits locais pequenos, com mensagem em português e **sem** o nome de nenhum modelo de IA. Termine o trabalho com a árvore limpa (tudo commitado) no seu branch.
- **Dados fictícios apenas.** Nunca grave nome, número de processo ou valor de cliente real em arquivo versionado, em teste, em commit ou no relatório final. Números de processo vêm de `tests/ficticio.numero_ficticio` (calculados em tempo de execução). O `empacotar.sh` barra números reais; confira com o mesmo padrão antes de terminar (`grep -rIn -E` sobre os seus arquivos).
- **Sem rede nos testes.** Sem certificado, jus.br, TRT ou provedor de IA reais. Use `src/simulado.py`, `tests/ficticio.py` e provedores/transportes falsos.
- **Compatibilidade**: o painel e o fluxo da Fase 1 continuam funcionando; nenhum teste existente pode quebrar (`tests/test_painel.py` compara o HTML de cada tela com um instantâneo; se uma mudança sua alterar o HTML, regrave **só** o necessário e justifique no relatório).
- Estilo do código: módulos planos em `src/`, nomes e comentários em português, cabeçalho de módulo explicando o propósito e o uso (como `carteira.py`, `planilha.py`), densidade de comentários parecida com a do código atual, sem dependência nova sem necessidade (se precisar, justifique e liste).
- **Erros esperados viram avisos estruturados** (CONTRATOS §0), com `codigo` estável quando aplicável; mensagens ao usuário em português simples.
- **Não prometa o que não testou.** Diga explicitamente o que só foi validado com dado fictício, o que depende do Excel/Word/Google/jus.br reais, e o que ficou de fora.
- Se faltar tempo ou ficar travado, entregue o que está **completo e testado** e liste o resto; não deixe código pela metade sem teste.

## Definição de pronto

Testes novos escritos e passando; testes antigos intactos; módulo documentado no cabeçalho; zero número/nome real; branch limpo e commitado; relatório final enviado.

## Relatório final (máximo ~400 palavras, português)

1. **Veredito** (concluído / concluído com ressalvas / parcial) e o branch/commit.
2. **API pública criada** (assinaturas) e **arquivos**.
3. **Testes**: comando e resultado (passando/total); o que **não** foi testado e por quê.
4. **Desvios do contrato ou da especificação** e RFCs abertos.
5. **Riscos e pendências**, inclusive o que depende de teste real (Excel/Word/Google/jus.br/IA) e o que o coordenador precisa decidir ou integrar.
6. Qualquer **conflito previsto** com outros workstreams (arquivos compartilhados que você teve de tocar).
