# Fixtures sintéticas e coletor simulado (item 0.3)

Tudo vive em `tests/ficticio.py` (geradores) e `src/simulado.py` (coletor). Nada usa rede, certificado ou dado
real; tudo é **gerado em tempo de execução** e **determinístico por semente** (nenhum número de processo vira
literal no repositório; `tests/test_ficticio.py` confere com o mesmo padrão do `empacotar.sh`).

Todo teste começa assim (o `isolamento` precisa vir antes de qualquer módulo da ferramenta):

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: F401
import ficticio, simulado           # ficticio já põe src/ no sys.path
```

## Receitas

**1. Carteira fictícia e número avulso**
```python
fichas = ficticio.gerar_carteira(200, clientes=5, semente=1)   # fichas v2, vocabulários canônicos, ~55% ativas
numero = ficticio.numero_ficticio(7)                           # 1234574-..., DV correto (ano/j/tr/origem opcionais)
assert all(ficha.validar(f) == [] for f in fichas)
```

**2. Carteira com defeitos para o verificador de qualidade (WS-11)**
```python
sujas = ficticio.gerar_carteira(200, com_defeitos=True)        # mesmo tamanho; trazem .defeitos
sujas.defeitos["acordo_sem_valor"]                             # números afetados, por tipo de defeito
ficticio.detectar_defeitos(sujas)                              # referência simples do que deve ser achado
```
Tipos: `numero_duplicado`, `materia_dois_rotulos` (pares principal/vinculado "mesma_acao"), `acordo_sem_valor`,
`encerrado_sem_resultado`, `ativo_em_conflito`, `dv_errado` (a ficha fica com número inválido), `grafias_cliente`.

**3. Listas brutas para os leitores (WS-2) e para a importação**
```python
arquivos = ficticio.gerar_lista_bruta(pasta, fichas)           # txt (e-mail), csv (;), xlsx, xlsx_bagunca (cabeçalho na linha 3)
esperado = arquivos["csv"]                                     # {"arquivo": Path, "validos": [...], "invalidos": [...]}
registros, invalidos = carteira.ler_lista(str(esperado["arquivo"]))
```

**4. Histórico em texto corrido e linha de base (migração)**
```python
ficticio.gerar_historico(f)                                    # "Em 18/06/2026 foi proferida sentença julgando ... Em ..."
ficticio.gerar_textos_de_andamento(f, ate="2026-06-30")        # lista de frases, cortada na data-base
ficticio.anexar_linha_de_base(f, data_base="2026-09-18")       # preenche f["linha_de_base"] no formato do contrato
```
O texto sai dos mesmos fatos que o coletor simulado usa: resultado, momento atual e datas batem com a ficha.

**5. Projeto temporário e coletor simulado (fila, revisão, relatórios)**
```python
with ficticio.projeto_de_teste(fichas) as proj:                # comum.criar_projeto numa pasta temporária; restaura ao sair
    coletor = simulado.ColetorSimulado(fichas, semente=1, taxa_falha=0.1)
    r = coletor.coletar({"numero": fichas[0]["numero"]}, "padrao", desde="2026-01-01")
    # r = {"capa": {...}, "movimentos": [...], "documentos": [...], "erro": None | {"codigo", "mensagem"}}
    assert coletor.chamadas == 1                               # e coletor.chamadas_por_numero[numero]
```

## Coletor simulado, em resumo

| Parâmetro | Efeito |
| --- | --- |
| `semente`, `taxa_falha` | Quem falha e com que código é decidido por (semente, número); reproduzível em qualquer ordem. |
| `profundidade` | `rapido`: capa + movimentos; `padrao`: + documentos-chave (sentença, acórdão, decisão); `completo`: todos. |
| `desde` | Só movimentos e documentos **posteriores** à data (ISO ou DD/MM/AAAA); a capa vem sempre. |
| `falhar_em={numero: codigo}` | Força o erro (sempre). `{numero: ("timeout", 2)}` falha só nas 2 primeiras chamadas. |
| `tentativas_transitorias` | `timeout`, `sessao_expirada` e `outro` falham só nas N primeiras chamadas (padrão 1); `captcha`, `segredo` e `nao_encontrado` falham sempre (a fila os manda para `manual`). |
| `pasta` | Onde gerar os documentos (padrão: `comum.DOCS_DIR/simulado`, que nos testes é temporária). |
| `atraso_s` | Dorme esse tempo por chamada (para testar janela de horário e estimativa, ou deixe 0). |

Documentos: HTML ou PDF de texto (gerado à mão por `simulado.pdf_minimo`, sem dependências), com nome no padrão do
PJe (`190123456 - Sentença - Sentença.pdf`), lidos por `extrair.extrair_arquivo`. Há sentença de procedência,
parcial, improcedência, acordo (com ou sem valor, conforme a ficha), extinção, decisão desfavorável com prazo e
decisão que designa audiência. Número que não está nas fichas (nem entre os vinculados) volta `nao_encontrado`;
processo vinculado (agravo, apenso, recurso) tem coleta própria, enxuta. Movimentos usam o texto do tribunal
(`movimentos.json` traduz a maioria; alguns ficam sem regra de propósito, para exercitar o alerta).

Para testes do pipeline, dá para transformar o resultado em evento com `comum`/`coletor`-style
(`status: "coletado"`, `arquivo: caminho`) e seguir com `extrair.rodar()`.
