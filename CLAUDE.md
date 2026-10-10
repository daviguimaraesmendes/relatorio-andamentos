# Relatório de Andamentos: instruções para o Claude Code neste projeto

Ferramenta local (Python/Flask, em português) de um escritório de advocacia: acompanha processos de clientes, coleta andamentos
e documentos nos tribunais, resume com IA e gera três entregas (Word = modelo A, planilha Excel = modelo B, painel HTML = modelo C).
O dono é o advogado Davi; os usuários finais NÃO são técnicos. Tudo o que o usuário vê é em português simples.

## Regras que valem sempre (quebrar qualquer uma é erro grave)

1. **Login do PDPJ: UMA tentativa.** Se falhar depois de enviar credencial, não repetir: a conta pode ser bloqueada. A trava
   (`projetos/.pdpj_trava.json`, `src/pdpj.py`) só sai pelo botão "Liberar" depois de conferir os dados. Nunca escreva laço de
   repetição em torno de login. Rodar login real só quando o Davi pedir/autorizar para aquele teste.
2. **Credenciais só no cofre do sistema** (`src/acesso.py`, keyring). Nunca em arquivo, log, tela, URL, mensagem de erro, commit ou
   pacote. Testes usam cofre em memória (`tests/isolamento.py`); nenhum teste lê o cofre real.
3. **Dados de clientes nunca vão ao repositório**: nada de números de processo reais, nomes de partes, CPF/CNPJ, e-mails ou PDFs em
   código, testes, docs ou commits. Use valores fictícios gerados por cálculo (`tests/ficticio.py::numero_ficticio`). O teste
   `tests/test_confidencialidade.py` recusa CPF/CNPJ/e-mail reais, nomes de empresa que pareçam reais e `SENHA = "..."`.
4. **Só leitura nos tribunais**: nenhuma chamada de escrita, protocolo, assinatura ou ciência de expediente.
5. **IA externa só com consentimento** por relatório/cliente, com pseudonimização ligada (`src/ia.py`). Claude pelo Claude Code
   NÃO é IA local: o texto vai à Anthropic (só muda o contrato: assinatura em vez de API).
6. **Revisão humana é obrigatória**: a IA só prepara rascunho; nada vai a cliente sem aprovação em Revisar.

## Como trabalhar aqui

- Português em tudo (código, comentários, mensagens, commits). Comentário explica o porquê, não o quê.
- Antes de mexer: `git fetch && git status -sb`; outras sessões empurram na mesma branch (`claude/gallant-pasteur-etzpu5`).
  Trabalho vai para essa branch; **promover para `main` só quando o Davi validar** (ele pede "promover para main"). Tag/release
  dispara o instalador do Windows: só se ele pedir. Commits terminam com `Co-Authored-By: Claude ... <noreply@anthropic.com>`.
- Versão em `VERSAO` (hoje 2.0.0-beta7); subir quando o código muda para o painel dos usuários reiniciar sozinho. Notas em `BETA-LEIAME.md`.
- Testes: crie um venv de apoio fora do repositório (`python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r requirements.txt`),
  depois `/tmp/venv/bin/python -m unittest discover -s tests -p "test_*.py"` (~4 min). Só falham `test_autos` e `test_dashboard`
  (Playwright não roda no ambiente do Claude). `tests/test_painel.py` compara o HTML com `tests/fixtures/painel_instantaneo.json`:
  quando a tela muda de propósito, regrave com `PAINEL_GRAVAR=1 python -m unittest tests/test_painel.py`.
- Testes nunca fazem login real nem tocam em `projetos/`. Testes de coleta usam navegador/coletor falsos.
- Ambiente isolado para experimentar com dados reais: aponte `RELATORIO_DATA`, `RELATORIO_CARTEIRA`, `RELATORIO_CLIENTES` e
  `RELATORIO_PROJETOS` para uma pasta temporária (nunca grave em `projetos/` real), rode com `.venv/bin/python` do projeto e apague
  a pasta quando o Davi autorizar (pode conter PDFs reais).
- O painel do Davi roda em `http://127.0.0.1:5072` (`src/abrir_painel.py`; reinicia sozinho se a versão mudar e não houver coleta).
- Telas novas: use `ajuda("texto")` (botão (i)) em cada botão/campo, classes e tokens de `docs/identidade-visual.md`, sem recursos
  externos. Use subagentes (worktrees) para trabalhos grandes e independentes; cada um num conjunto de arquivos diferente.

## Mapa do código (src/)

| Área | Arquivos |
| --- | --- |
| Coleta | `coletor.py` (jus.br, certificado), `trt.py` (consulta pública TRT), `pje_trt.py` (PJe do advogado: 1º grau, 2º grau, TST), `pdpj.py` (login), `fila.py` (`ColetorReal`), `djen.py`, `capa.py` |
| Ficha e consolidação | `ficha.py` (campos e origem), `consolidar.py`, `carteira.py`, `clientes.py`, `julgamento.py`, `taxonomia.py` (vocabulários) |
| Migração de modelo | `leitores/` (`grade.py`, `tabela_livre.py`, `xlsx_b.py`, `docx_a.py`), `painel/migracao.py` |
| IA | `ia.py` (provedores: local, API, Claude Code, OpenAI-compatível), `resumir.py` (prompt e conferência), `sintese.py`, `ia_local.py` |
| Entregas | `escritores/` (`docx_a.py`, `xlsx_b.py`, `dashboard.py`), `modelos/`, `relatorio.py`, `planilha.py` |
| Fluxos e telas | `fluxos.py` (4 fluxos), `painel/*.py` (uma tela por arquivo; `base.py` = casco, tema e `ajuda()`) |

Documentos: `docs/pje-trt-login-proprio.md` (como o PJe/PDPJ funciona), `docs/confidencialidade-ia.md`, `docs/identidade-visual.md`,
`docs/PLANO-PROXIMA-SESSAO-CLAUDE.md`, `docs/claude-no-projeto.md` (modelos e esforço do Claude por tarefa).

## Claude (modelos e esforço) neste projeto

Resumo; detalhes, números do teste e como configurar em `docs/claude-no-projeto.md`.

- Padrão para **resumir documentos de processo** e **extrair campos de textos livres**: ver a recomendação em `docs/claude-no-projeto.md`.
- Mapeamento de colunas, normalização de valores (R$, %, sim/não, datas, CNPJ) e extração curta são tarefas fáceis: modelo pequeno
  em esforço baixo basta, e as regras determinísticas (`leitores/grade.py`) vêm primeiro; a IA entra no que as regras não resolvem.
- Quando o erro custa caro (sentença, acórdão, prazo, valor), preferir o modelo maior ou revisão humana; nunca aceitar valor, prazo
  ou data que não apareça no texto (a ferramenta já confere em `resumir.conferir`).
