# Contratos da Fase 2 (congelados no marco M1)

Este documento é a fonte única das interfaces entre os workstreams (`PLANO.md`, seção 8).
**Mudança de contrato só pelo coordenador.** Quem precisar de mudança abre uma nota em
`docs/fase2/RFC-<assunto>.md` e avisa; não altera o contrato por conta própria.

Código de referência já existente: `src/ficha.py`, `src/taxonomia.py`, `src/comum.py`, `src/carteira.py`.

## 0. Convenções gerais

- Módulos planos em `src/`, nomes e comentários em português, no estilo do código atual.
- Datas em **ISO** (`AAAA-MM-DD`) dentro de ficha, perfil e retrato; `DD/MM/AAAA` só na tela e nos arquivos entregues. Dinheiro em **texto decimal** (`"1234.56"`); use `ficha.dinheiro()` para somar.
- Todo texto que sai para o cliente nasce de evento **aprovado** (regra da Fase 1 mantida).
- Todo teste usa **dados fictícios** e nunca toca em `projetos/` real (`tests/isolamento.py` é importado antes de tudo).
- Números de processo em arquivos **versionados** só podem ser os permitidos pelo `empacotar.sh` (`0000000-00.0000.0.00.0000`, `9999999-99...`, `1234567` a `1234570`). Fixtures maiores (ex.: 200 processos) são **geradas em tempo de execução**, nunca gravadas como literais no repositório. Use `numero_ficticio(n)` e os geradores de `tests/ficticio.py` e o coletor simulado de `src/simulado.py` (receitas em `docs/fase2/fixtures.md`).
- Nenhum teste faz chamada de rede nem usa o certificado, o jus.br ou provedor de IA real.
- Erros esperados (arquivo ilegível, formato desconhecido, campo fora do vocabulário) viram **avisos estruturados**, não exceções soltas; exceção só para erro de programação ou de ambiente.

## 1. Ficha v2 (`src/ficha.py`)

Registro por processo, armazenado em `carteira.json` (lista; itens da Fase 1 são lidos como v2 sem perda).

- **Campos**: tabela `ficha.CAMPOS` (nome → rótulo, grupo, tipo, vocabulário). Grupos: `gestao`, `partes`, `capa`, `situacao`, `julgamento`.
- **Origem de cada campo** (`humano 5 > coletado 4 > migrado 3 > derivado 2 > sugerido 1`): `ficha.definir(ficha, campo, valor, origem, evidencia=None, forcar=False)` respeita a prioridade; vazio nunca apaga; rótulo fora do vocabulário **não grava**.
- `ficha.obter`, `ficha.origem`, `ficha.limpar`, `ficha.vincular`, `ficha.todos_os_numeros`, `ficha.validar`, `ficha.carregar`, `ficha.salvar`, `ficha.nova_ficha`, `ficha.de_carteira_v1`.
- **Linha de base** (`ficha["linha_de_base"]`): `{"data_base": "AAAA-MM-DD", "andamentos_texto": "...", "arquivo": "nome.ext", "ultimo_andamento": "AAAA-MM-DD"|null}`. É o histórico lido de um relatório existente; **nunca é recoletado nem reescrito**.
- **Vínculos** (`ficha["vinculados"]`): `[{"numero": "...", "tipo": "recurso|agravo|apenso|reajuizamento|mesma_acao"}]`. O relatório trata principal + vinculados como **uma linha**.
- **Colunas de julgamento** (`CAMPOS_DE_JULGAMENTO`): lidas de relatório migrado entram com origem `humano`; `julgamento.py` só sugere (`sugerido`) onde estiver vazio.

## 2. Vocabulários (`src/taxonomia.py`)

`taxonomia.normalizar(vocabulario, texto) -> canônico | None` (nunca adivinha em caso de ambiguidade). Vocabulários: `polo`, `situacao`, `fase`, `resultado`, `probabilidade`, `area`, `tipo_vinculo`, `momento_atual`, `materia`. `momento_ativo()` e `categoria_do_momento()` dizem se o momento conta como ativo e em que fase está. WS-1 amplia os vocabulários e os sinônimos (editáveis no painel) **sem remover valor canônico existente**.

## 3. Evento

Mantém o formato de `src/comum.py` (status `coletado → extraido → rascunho → aprovado → relatado | descartado`). Campos novos permitidos (aditivos, nunca obrigatórios): `motor` (identificador do motor de IA que resumiu, ex. `local:gemma3:4b`, `externo:anthropic`), `profundidade` (`rapido|padrao|completo`), `grau`.

## 4. Leitores (`src/leitores/`)

```python
leitores.detectar(caminho) -> "docx_a" | "xlsx_b" | "lista" | "tabela_livre" | "desconhecido"
leitores.ler(caminho, formato=None) -> RelatorioLido            # dict
```

```python
RelatorioLido = {
  "formato": "docx_a|xlsx_b|lista|tabela_livre",
  "arquivo": "nome.ext",
  "cliente": str | None,                 # título do documento ou parâmetro da planilha
  "data_base": "AAAA-MM-DD" | None,
  "processos": [ProcessoLido, ...],
  "parametros": {...},                   # ex.: headcount, empresas do grupo (modelo B)
  "colunas_sem_destino": [{"coluna": str, "amostra": [..]}],   # nada se perde em silêncio
  "avisos": [Aviso, ...],
}
ProcessoLido = {
  "numero": "CNJ principal",
  "vinculados": [{"numero": ..., "tipo": ...}],
  "campos": {campo: {"valor": ..., "origem": "migrado|humano"}},   # só campos de ficha.CAMPOS
  "andamentos_texto": str,               # vira ficha["linha_de_base"]["andamentos_texto"]
  "ultimo_andamento": "AAAA-MM-DD" | None,
  "origem_no_arquivo": "linha 12" | "tabela 3",
}
Aviso = {"nivel": "info|atencao|erro", "onde": str, "mensagem": str, "candidatos": [..]}
```

Regras: ambiguidade (mesmo número duas vezes, rótulo fora do vocabulário, data inválida) gera `Aviso` e **não** vira dado silencioso; número com dígito errado é recusado e listado; um ler → escrever → ler preserva os campos.

## 5. Escritores (`src/escritores/`)

```python
escritores.docx_a.gravar(molde, estado, destino, **opcoes) -> Resultado
escritores.xlsx_b.gravar(molde, estado, destino, **opcoes) -> Resultado
escritores.dashboard.gravar(xlsx, destino, perfil, **opcoes) -> Resultado
```

- `molde`: `Path` do arquivo do cliente (atualização) ou `None` (cria do modelo padrão em `src/modelos/`).
- `EstadoRelatorio = {"cliente", "data_base" (ISO), "fichas": [ficha...], "eventos": [evento aprovado...], "perfil": Perfil, "parametros": {...}}`.
- `Resultado = {"destino": Path, "processos_atualizados": [numero], "processos_novos": [numero], "mudancas": [{"numero", "campo", "antes", "depois"}], "avisos": [Aviso]}`.
- **Só acrescenta** no texto de andamentos; nunca apaga o que um humano escreveu. Idempotente: gravar duas vezes o mesmo estado não duplica. O original nunca é sobrescrito (`destino != molde`).
- `.xlsx`: edição cirúrgica do pacote (partes não editadas idênticas byte a byte), recálculo forçado ao abrir; campos `humano` nunca sobrescritos. `.docx`: runs e tabelas preservados, datas em negrito nos trechos novos.
- `dashboard`: HTML **autônomo e offline** (bibliotecas embutidas); modos `modelo` (arrasta a planilha) e `embutido` (dados do retrato).

## 6. Coletor e fila (`src/fila.py`)

```python
class Coletor(Protocol):        # real: adaptador sobre coletor.py/trt.py; teste: coletor simulado
    def coletar(self, processo: dict, profundidade: str, desde: str | None) -> ResultadoColeta: ...

# `desde` é ESTRITO (só o que for posterior), como o `_depois` do coletor real; vale para movimentos e documentos; a capa vem sempre.
ResultadoColeta = {
  "capa": {campo: valor},        # só campos de ficha.CAMPOS (grupos capa/partes/situacao); polo_cliente e parte_contraria NUNCA vêm da coleta (o tribunal não os informa)
  "movimentos": [{"data": "AAAA-MM-DD", "texto": str, "grau": str|None, "chave": str}],   # chave: "DD/MM/AAAA|texto|n", como no coletor real
  "documentos": [{"nome": str, "tipo": str, "data": "AAAA-MM-DD", "caminho": str}],
  "erro": None | {"codigo": "captcha|segredo|nao_encontrado|timeout|sessao_expirada|outro", "mensagem": str},
}
```

```python
fila.Fila(projeto).enfileirar(numeros, *, modo="continuo|imediato", profundidade="rapido|padrao|completo",
                              prioridade=0, desde=None)
fila.Fila(...).proximo() -> item | None        # respeita janela de horário e pausa entre processos
fila.Fila(...).marcar(numero, estado, erro=None)
fila.Fila(...).resumo() -> {"total", "pendente", "coletando", "coletado", "erro", "manual", "estimativa_s"}
fila.Fila(...).pausar() / .retomar() / .parar_com_seguranca()
fila.cobertura(projeto) -> {tribunal: {"coletado": n, "so_djen": n, "manual": n}}
```

Estados por processo: `pendente → coletando → coletado | erro | manual`. Estado persistido em disco a cada transição (retomável após queda em qualquer ponto; nunca repete processo `coletado`). `erro` guarda contagem e código; `captcha`/`segredo` vão para `manual` sem travar o resto. **Sequencial contra jus.br e TRT**; modo `imediato` mostra estimativa de duração e exige confirmação antes de começar.

## 7. Perfil do relatório (`projetos/<slug>/perfil.json`)

```json
{
  "versao": 1,
  "entregas": ["docx_a", "xlsx_b", "dashboard"],
  "molde_planilha": "cliente | padrao",
  "colunas_ativas": ["numero", "autores", "reus", "..."],
  "estilo_texto": "a | b",
  "profundidade": "rapido | padrao | completo",
  "modo_coleta": "continuo | imediato",
  "ia": {"provedor": "local", "consentimento_externo": false, "pseudonimizar": true},
  "parametros": {"headcount": null, "empresas_do_grupo": []}
}
```

`ia.consentimento_externo` é **por relatório** e, quando houver mais de um cliente, por cliente (`ia.por_cliente`: `{nome: bool}`). Sem `true` explícito, nada sai do computador.

## 8. Provedor de IA (`src/ia.py`)

```python
ia.provedor(perfil, cliente) -> Provedor           # escolhe local ou externo conforme consentimento
Provedor.gerar(sistema: str, usuario: str, *, esquema: dict | None = None, cliente: str) -> {"texto": str, "json": dict | None, "motor": str}
ia.registro_de_envios(projeto) -> list             # tudo que saiu do computador (só externo)
```

Provedor externo: chave no cofre do sistema (`acesso.py`/keyring); só texto extraído; pseudonimização opcional; falha de rede cai no local e avisa. Stub local disponível desde o M1 para os demais workstreams.

## 9. Retrato mensal (`projetos/<slug>/data/historico/AAAA-MM-DD.json`)

```json
{
  "data_base": "AAAA-MM-DD",
  "totais": {"processos": 0, "ativos": 0, "encerrados": 0, "valor_causa": "0.00", "valor_estimado": "0.00",
             "valor_economizado": "0.00"},
  "por_processo": [{"numero": "...", "situacao": "...", "momento_atual": "...", "valor_causa": "...",
                    "valor_estimado": "...", "resultado": "...", "probabilidade": "..."}]
}
```

Gerado a cada atualização concluída; reconstruível a partir de vários `.xlsx` antigos na migração.

## 10. Sugestão de julgamento (`src/julgamento.py`)

```python
julgamento.sugerir(ficha, eventos) -> {campo: {"valor": ..., "regra": str, "evidencia": {"documento": str, "trecho": str}, "ressalvas": [str]}}
julgamento.concordancia(fichas_migradas) -> {campo: {"concordam": n, "total": n, "casos_divergentes": [numero]}}
```

Regras em `PLANO.md`, seção 7.2. Nunca grava `humano`; grava `sugerido`; campo já `humano` nunca é tocado.

## 11. Telas do painel (`src/painel/`)

Cada tela nova é um módulo com `registrar(app, TOKEN, cabecalho, token_ok)`; `src/revisao.py` só cria o app e chama os `registrar` (fatiamento do item 0.4). Rotas novas ficam sob prefixos próprios (`/fluxo/...`, `/migracao/...`, `/entregas/...`, `/pedidos/...`, `/ia/...`) para não colidir.

## 12. Propriedade de arquivos

| Workstream | Arquivos próprios |
| --- | --- |
| Coordenador | `ficha.py`, `docs/fase2/CONTRATOS.md`, `PLANO.md`, `fluxos.py` |
| WS-1 | `taxonomia.py`, `tests/test_ficha.py` (extensões em `tests/test_taxonomia.py`) |
| WS-2 | `leitores/*`, `tests/test_leitores.py`; `carteira.py` só para reaproveitar funções (sem alterar assinaturas) |
| WS-3 | `fila.py`, `tests/test_fila.py`, ajustes mínimos em `coletor.py`, `trt.py`, `rodar.py` |
| WS-4 | `capa.py`, `djen.py` (extensões), `tests/test_capa.py` |
| WS-5 | `sintese.py`, `resumir.py` (extensões), `tests/test_sintese.py` |
| WS-6 | `escritores/docx_a.py`, `modelos/docx_a/*`, `tests/test_docx_a.py` |
| WS-7 | `escritores/xlsx_b.py`, `planilha.py`, `modelos/xlsx_b/*`, `tests/test_xlsx_b.py` |
| WS-8 | `escritores/dashboard.py`, `modelos/dashboard/*`, `tests/test_dashboard.py` |
| WS-9 | `painel/assistente.py`, `painel/migracao.py`, `painel/entregas.py`, `painel/perfil.py` |
| WS-10 | `painel/revisao_lote.py`, `painel/processo.py`, `painel/revisao_eventos.py` (fatia de revisão) |
| WS-11 | `qualidade.py`, `tests/test_qualidade.py` |
| WS-13 | `tests/ficticio.py`, testes transversais, `README.md`, `docs/`, `empacotar.sh` |
| WS-16 | `pedidos.py`, `modelos/pedidos/*`, `docs/pedidos-iniciais.md`, `painel/pedidos.py` |
| WS-17 | `julgamento.py`, `tests/test_julgamento.py` |
| WS-18 | `ia.py`, `painel/ia.py`, `tests/test_ia.py` |

Arquivo **compartilhado** que dois workstreams precisem mudar: quem chega primeiro faz a mudança mínima e avisa o coordenador; o segundo rebaseia.
