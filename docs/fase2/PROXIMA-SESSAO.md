# Como retomar a Fase 2 na próxima sessão

Atualizado em 07/10/2026, ao fim da Onda 1. **Nenhum agente está rodando.** Tudo está commitado e enviado ao branch `claude/gallant-pasteur-etzpu5`.

## Onde estamos

| Etapa | Estado |
| --- | --- |
| Etapa 0 (contratos, fixtures, coletor simulado, painel fatiado, spikes S1/S2) | Concluída (M1) |
| Onda 1 (15 workstreams) | Concluída e integrada; suíte completa verde (1.183 testes, 2 pulados) |
| **Onda 2** (WS-14 fluxos ponta a ponta, WS-15 regressão e carga) | **Especificada em `ONDA-2.md`, não iniciada** |
| Onda 3 (pilotos M5/M6 no Mac do usuário, extras, pacote v2) | Depende do usuário e da Onda 2 |

Documentos de referência, nesta ordem: `PLANO.md` (o quê e por quê), `CONTRATOS.md` (interfaces), `WORKSTREAMS.md` (Onda 1, já feita), `ONDA-2.md` (o que falta), `STATUS.md` (matriz de módulos), `fixtures.md` (dados fictícios e coletor simulado), `painel-modulos.md` (como criar tela), `spikes/` (S1 planilha, S2 Word, S3 DataJud), os `RFC-*.md` (decisões e convenções propostas pelos agentes).

## Preparar o ambiente (cada sessão nova começa limpa)

1. `git fetch origin claude/gallant-pasteur-etzpu5 && git checkout claude/gallant-pasteur-etzpu5` (ou continue no branch já clonado).
2. Dependências de teste que o ambiente em nuvem não traz prontas: `pip install flask openpyxl keyring pyotp pypdf python-docx lxml` (o `flask` pode exigir `--ignore-installed blinker`) e `pip install playwright==1.56.0` (a versão tem que casar com o Chromium instalado em `/opt/pw-browsers`; **não** rode `playwright install`). LibreOffice (`soffice`) e `pdftotext` já existem no ambiente.
3. Conferir a base: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 -m unittest discover -s tests -p "test_*.py"` deve terminar `OK` (2 testes pulados: OCR sem `tesseract` e um condicionado ao ambiente).
4. Os dois painéis de referência (com nomes de cliente embutidos) **não estão no repositório**. Foram usados só pelo WS-8 e já viraram templates próprios em `src/modelos/dashboard/`. Não é preciso recriá-los.

## Lançar a Onda 2

1. **WS-14** (um agente, em worktree isolado): prompt pronto abaixo. É o caminho crítico; só ele pode começar agora.
2. **WS-15** (um agente): só depois de integrar o WS-14.
3. Depois de cada agente: `git merge` do branch `worktree-agent-<id>` no branch do coordenador, suíte completa, `git push`. Se o `git push` devolver `Internal Server Error` do GitHub (aconteceu várias vezes em 07/10/2026), repetir com esperas de 30 a 120 s; costuma passar na terceira a quinta tentativa.

Prompt do WS-14 (copiar para a ferramenta de agentes, com `isolation: worktree`):

> Você é o agente do WS-14 (fluxos ponta a ponta) da Onda 2 da Fase 2 do projeto relatorio-andamentos. PRIMEIRO PASSO: no seu worktree rode `git reset --hard claude/gallant-pasteur-etzpu5` (o worktree nasce no commit inicial; ainda não há trabalho seu). Depois leia `docs/fase2/BRIEFING-AGENTES.md`, `docs/fase2/PLANO.md`, `docs/fase2/CONTRATOS.md`, `docs/fase2/STATUS.md`, `docs/fase2/fixtures.md`, `docs/fase2/painel-modulos.md` e execute a seção "WS-14" de `docs/fase2/ONDA-2.md`. Instale as dependências de teste conforme `docs/fase2/PROXIMA-SESSAO.md` (Playwright 1.56.0). Siga o briefing à risca (sem push, dados fictícios, relatório final no formato pedido). Os módulos da Onda 1 já passam nos seus testes: ligue-os, não os reescreva.

Prompt do WS-15 (depois do WS-14): idem, trocando a seção por "WS-15" e acrescentando "O WS-14 já está integrado em `src/fluxos.py`".

## Decisões do usuário já tomadas (não reabrir)

- IA: local por padrão (modelo maior se houver memória); provedores externos (Claude, API compatível com OpenAI) só por escolha do usuário, com consentimento por cliente.
- Coleta: sequencial; modo contínuo (janelas de horário) e modo imediato (com aviso de duração). Nunca paralelo contra jus.br e TRT.
- Entrada do modelo A: `.docx` exportado do Google Doc. Planilha: o arquivo do cliente é o molde na atualização; modelo padrão sanitizado no inicial; fluxo "Migrar de modelo".
- Pedidos das iniciais: kit para IA melhor (prompt, guia, "colar resultado"), feito; extração automática local fica de fora.
- Julgamento: sugestão por regra, sempre revisada; **probabilidade é a do resultado, sem inversão por polo**; valor economizado = valor da causa − valor estimado, só de processo encerrado e sem os casos com ressalva.
- Fecho "sem atualizações" só quando não houve novidade no ciclo.

## Pendências que dependem do usuário

1. **DataJud** (API pública do CNJ): fica desligado; o termo de uso diz "fins não comerciais". Decidir se o uso do escritório se enquadra e, se sim, informar a chave do CNJ em `config.json` (`fontes_externas.datajud`).
2. **Excel e Google Planilhas**: abrir as planilhas geradas (`python3 tests/test_xlsx_b.py --exemplos PASTA` cria quatro de exemplo) e seguir `conferencia-xlsx.md`. Pontos de maior risco: tabela dinâmica montada à mão, textos gravados em linha, fórmulas com colunas de nome longo (`#NOME?`).
3. **Word e Google Docs**: gerar um `.docx` e abrir seguindo `conferencia-docx.md`; testar a ida e volta com uma exportação real do Google Doc (rótulos, título `[ MOMENTO ]` e frase de fecho ainda são suposições).
4. **Piloto M5/M6 no Mac** (jus.br, TRT, captcha, tempo real por processo, cobertura por tribunal, qualidade do modelo de IA local, prompt de pedidos com petições reais). O roteiro sai do WS-15.
5. Convenção das ressalvas de economia: escrever em Observações os marcadores `[acordo pago por terceiro]` e `[exclusão da lide]`; sem isso o sistema não os adivinha.

## Riscos conhecidos para lembrar

- Tudo foi validado com dados fictícios e com ferramentas de linha de comando (python-docx, openpyxl, LibreOffice, Chromium). Nada com Word, Excel, Google, jus.br, TRT, Ollama ou API de IA reais.
- Limiares e regras (detecção de duplicata, qualidade, triagem, momento atual por regra, mapeamento de cabeçalhos) foram calibrados só com texto fictício.
- O Windows continua "não testado".
- O limite mensal de gasto da conta já foi atingido uma vez (7 de outubro); confira o limite antes de lançar agentes em paralelo.
