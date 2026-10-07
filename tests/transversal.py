"""Apoio dos testes transversais da Fase 2 (WS-13): `test_confidencialidade.py`, `test_desempenho.py`,
`test_contratos.py` e `test_empacotamento.py`.

Os módulos dos outros workstreams chegam em momentos diferentes. Os testes transversais usam o que já existe
e **pulam com mensagem clara** o que ainda não existe (o coordenador reativa na integração: basta o módulo
passar a existir; nenhum teste precisa ser editado). Este arquivo concentra:

- `MODULOS`: a tabela módulo -> workstream -> o que o contrato promete (fonte da matriz de `docs/fase2/STATUS.md`).
  Para ver o estado atual:  python3 tests/test_contratos.py --matriz
- `modulo(nome)` / `exigir(nome)`: importa o módulo; `exigir` pula o teste (SkipTest) quando ele ainda não existe.
  Módulo que existe mas quebra ao importar NÃO é pulado: o erro aparece.
- `arquivos_do_projeto()` / `texto_do_arquivo()`: arquivos versionados (git) e leitura segura de texto, inclusive
  por dentro de .docx/.xlsx.
- `estado_de_teste()`, `perfil_padrao()`, `eventos_aprovados()`: dados fictícios no formato dos contratos.

Tudo aqui usa dados fictícios (tests/ficticio.py) e nenhuma rede.
"""
import importlib
import inspect
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de qualquer módulo da ferramenta)

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "src"
sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------- tabela de módulos (matriz do STATUS.md)
# (workstream, módulo importável, arquivo esperado, contrato que o teste confere)
# "contrato" é uma lista de (nome, posicionais, nomeados): nome dentro do módulo ("Fila.enfileirar" = método),
# `posicionais` = primeiros parâmetros, na ordem; `nomeados` = parâmetros que precisam existir (ou **kwargs).
MODULOS = [
    ("WS-1", "taxonomia", "src/taxonomia.py",
     [("carregar", ("projeto",), ()), ("adicionar_sinonimo", ("vocab", "canonico", "sinonimo"), ()),
      ("momento_por_regras", ("movimentos",), ()), ("normalizar_momento", ("texto",), ())]),
    ("WS-1", "consolidar", "src/consolidar.py",
     [("consolidar", ("fichas",), ()), ("migrar_projeto", ("slug",), ())]),
    ("WS-2", "leitores", "src/leitores/__init__.py",
     [("detectar", ("caminho",), ()), ("ler", ("caminho",), ("formato",))]),
    ("WS-3", "fila", "src/fila.py",
     [("Fila.enfileirar", ("numeros",), ("modo", "profundidade", "prioridade", "desde")),
      ("Fila.proximo", (), ()), ("Fila.marcar", ("numero", "estado"), ("erro",)), ("Fila.resumo", (), ()),
      ("Fila.pausar", (), ()), ("Fila.retomar", (), ()), ("Fila.parar_com_seguranca", (), ()),
      ("Fila.estimativa", (), ()), ("cobertura", ("projeto",), ()), ("rodar_fila", ("fila", "coletor"), ("ao_progresso",))]),
    ("WS-4", "capa", "src/capa.py",
     [("extrair", ("fonte", "dados"), ()), ("aplicar", ("ficha", "capa"), ())]),
    ("WS-5", "sintese", "src/sintese.py",
     [("momento_atual", ("ficha", "eventos", "movimentos", "provedor"), ()),
      ("ultimo_andamento", ("eventos", "movimentos"), ()),
      ("narrativa_inicial", ("ficha", "eventos", "profundidade", "provedor"), ()),
      ("narrativa_incremental", ("ficha", "eventos_novos"), ())]),
    ("WS-6", "escritores.docx_a", "src/escritores/docx_a.py", [("gravar", ("molde", "estado", "destino"), ())]),
    ("WS-7", "escritores.xlsx_b", "src/escritores/xlsx_b.py", [("gravar", ("molde", "estado", "destino"), ())]),
    ("WS-8", "escritores.dashboard", "src/escritores/dashboard.py", [("gravar", ("xlsx", "destino", "perfil"), ())]),
    ("WS-9", "painel.assistente", "src/painel/assistente.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
    ("WS-9", "painel.migracao", "src/painel/migracao.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
    ("WS-9", "painel.entregas", "src/painel/entregas.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
    ("WS-9", "painel.perfil", "src/painel/perfil.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
    ("WS-10", "triagem", "src/triagem.py", [("classificar", ("evento", "ficha"), ())]),
    ("WS-10", "painel.revisao_lote", "src/painel/revisao_lote.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
    ("WS-10", "painel.processo", "src/painel/processo.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
    ("WS-11", "qualidade", "src/qualidade.py",
     [("verificar", ("fichas", "perfil"), ()), ("o_que_mudou", ("estado_antes", "estado_depois"), ())]),
    ("WS-11", "historico", "src/historico.py",
     [("gravar_retrato", ("fichas", "data_base", "destino"), ()), ("carregar", ("projeto",), ()),
      ("reconstruir", ("relatorios_lidos",), ())]),
    ("WS-11", "quadros", "src/quadros.py", []),
    ("WS-16", "pedidos", "src/pedidos.py",
     [("pacote", ("projeto",), ()), ("validar", ("texto_colado",), ()), ("gravar", ("projeto", "dados"), ())]),
    ("WS-16", "painel.pedidos", "src/painel/pedidos.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
    ("WS-17", "julgamento", "src/julgamento.py",
     [("sugerir", ("ficha", "eventos"), ()), ("aplicar", ("ficha", "sugestoes"), ()),
      ("concordancia", ("fichas_migradas",), ())]),
    ("WS-18", "ia", "src/ia.py",
     [("provedor", ("perfil", "cliente"), ()), ("registro_de_envios", ("projeto",), ()), ("selo", ("motor",), ()),
      ("pseudonimizar", ("texto", "partes"), ())]),
    ("WS-18", "painel.ia", "src/painel/ia.py", [("registrar", ("app", "TOKEN", "cabecalho", "token_ok"), ())]),
]

# Rota que cada tela precisa ter registrado em `revisao.app` (a tupla de `revisao.py` é do coordenador).
PREFIXO_DE_ROTA = {"painel.assistente": "/fluxo", "painel.migracao": "/migracao", "painel.entregas": "/entregas",
                   "painel.perfil": "/perfil", "painel.pedidos": "/pedidos", "painel.ia": "/ia"}


# ---------------------------------------------------------------- importação tolerante

def modulo(nome):
    """O módulo importado, ou None se ele (ainda) não existe. Erro DENTRO de um módulo que existe é propagado."""
    try:
        return importlib.import_module(nome)
    except ModuleNotFoundError as e:
        ausente = e.name or ""
        if ausente == nome or nome.startswith(ausente + "."):    # o próprio módulo (ou seu pacote) não existe
            return None
        raise


def ws_do_modulo(nome):
    return next((ws for ws, m, _a, _c in MODULOS if m == nome), "?")


def exigir(nome, para=""):
    """Importa o módulo ou pula o teste com a mensagem padrão (quem reativa na integração sabe o quê procurar)."""
    mod = modulo(nome)
    if mod is None:
        raise unittest.SkipTest(f"{nome} ainda não existe ({ws_do_modulo(nome)}, Onda 1); reativar na integração"
                                + (f" ({para})" if para else ""))
    return mod


def resolver(mod, nome):
    """'Fila.resumo' -> função/método dentro do módulo (ou None)."""
    atual = mod
    for parte in nome.split("."):
        atual = getattr(atual, parte, None)
        if atual is None:
            return None
    return atual


def assinatura_compativel(func, posicionais=(), nomeados=()):
    """None se a assinatura atende ao contrato; senão, o motivo em texto."""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return "assinatura ilegível"
    params = [p for p in sig.parameters.values() if p.name not in ("self", "cls")]
    tem_kwargs = any(p.kind is p.VAR_KEYWORD for p in params)
    tem_args = any(p.kind is p.VAR_POSITIONAL for p in params)
    posicionais_reais = [p.name for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    # nome com '_' no fim (capa_) existe para não sobrepor o nome de um módulo: vale como o nome sem ele
    if not tem_args and [n.rstrip('_') for n in posicionais_reais[:len(posicionais)]] != list(posicionais):
        return f"parâmetros {posicionais_reais} não começam por {list(posicionais)}"
    nomes = {p.name for p in params}
    faltam = [n for n in nomeados if n not in nomes and not tem_kwargs]
    return f"faltam parâmetros {faltam}" if faltam else None


# ---------------------------------------------------------------- arquivos do projeto

PASTAS_IGNORADAS = {".git", ".venv", "venv", "__pycache__", "projetos", "ensaio", "data", "dist", "hub", ".claude",
                    "node_modules", ".pytest_cache"}


def arquivos_do_projeto(raiz=RAIZ):
    """Caminhos (relativos à raiz) dos arquivos versionados. Com git: tudo que está no índice ou ainda não foi
    adicionado, exceto o que o .gitignore barra (assim o teste vale durante o trabalho, antes do commit).
    Sem git (pacote descompactado): percorre a pasta, sem as pastas de dados e de ambiente."""
    try:
        saida = subprocess.run(["git", "-C", str(raiz), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                               capture_output=True, check=True, timeout=60).stdout.decode("utf-8")
        achados = [Path(p) for p in saida.split("\0") if p]
        return sorted(p for p in achados if (raiz / p).is_file())
    except (OSError, subprocess.SubprocessError):
        achados = []
        for pasta, subpastas, nomes in os.walk(raiz):
            subpastas[:] = [d for d in subpastas if d not in PASTAS_IGNORADAS]
            achados += [(Path(pasta) / n).relative_to(raiz) for n in nomes]
        return sorted(achados)


# a mesma varredura de texto do empacotar.sh (inclui o texto por dentro de .docx/.xlsx)
from confidencialidade_regras import texto_do_arquivo  # noqa: E402,F401


# ---------------------------------------------------------------- dados fictícios no formato dos contratos

def perfil_padrao(**extra):
    """Perfil do relatório (CONTRATOS §7) com os valores padrão."""
    perfil = {"versao": 1, "entregas": ["docx_a", "xlsx_b", "dashboard"], "molde_planilha": "padrao",
              "colunas_ativas": [], "estilo_texto": "a", "profundidade": "padrao", "modo_coleta": "imediato",
              "ia": {"provedor": "local", "consentimento_externo": False, "pseudonimizar": True},
              "parametros": {"headcount": None, "empresas_do_grupo": []}}
    perfil.update(extra)
    return perfil


def eventos_aprovados(fichas, por_ficha=2, a_partir="2026-09-19", motor="local:teste"):
    """Eventos aprovados fictícios (formato de comum.py): `por_ficha` por processo, datas depois de `a_partir`."""
    import datetime
    import ficha as fch
    inicio = datetime.date.fromisoformat(a_partir)
    frases = ("foi proferido despacho determinando a juntada de documentos.",
              "a parte ré apresentou manifestação nos autos.",
              "foi designada audiência de instrução.")
    lista = []
    for i, f in enumerate(fichas):
        for k in range(por_ficha):
            dia = inicio + datetime.timedelta(days=(i + 3 * k) % 25)
            lista.append({"id": f"ev-{i:04d}-{k}", "numero": f["numero"], "cliente": fch.obter(f, "cliente") or "",
                          "status": "aprovado", "data": dia.strftime("%d/%m/%Y"), "frase": frases[(i + k) % len(frases)],
                          "conteudo": "", "grau": "1º grau", "motor": motor, "profundidade": "padrao"})
    return lista


def estado_de_teste(fichas, data_base="2026-09-18", cliente="Cliente Exemplo 01 Ltda", eventos=None, perfil=None):
    """EstadoRelatorio (CONTRATOS §5) a partir de fichas fictícias."""
    return {"cliente": cliente, "data_base": data_base, "fichas": list(fichas),
            "eventos": list(eventos if eventos is not None else []), "perfil": perfil or perfil_padrao(),
            "parametros": {"headcount": 250, "empresas_do_grupo": []}}


# ---------------------------------------------------------------- arquivos de entrada fictícios para os leitores

def _carregar_por_caminho(nome_unico, caminho):
    import importlib.util
    spec = importlib.util.spec_from_file_location(nome_unico, caminho)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome_unico] = mod
    spec.loader.exec_module(mod)
    return mod


def _spike(nome_unico, subpasta, arquivo):
    caminho = RAIZ / "spikes" / subpasta / arquivo
    if not caminho.exists():            # spikes/ não vai no pacote
        return None
    if nome_unico in sys.modules:
        return sys.modules[nome_unico]
    sys.path.insert(0, str(caminho.parent))
    try:
        return _carregar_por_caminho(nome_unico, caminho)
    finally:
        sys.path.remove(str(caminho.parent))


def docx_de_entrada(destino, fichas, eventos=None, data_base="2026-09-18"):
    """.docx do modelo A com as fichas dadas. Prefere o protótipo do spike S2 (independente do leitor e do escritor de
    produção); sem ele (pacote), usa `escritores.docx_a`; sem nenhum dos dois, pula o teste. Devolve o Path."""
    estado = estado_de_teste(fichas, data_base, eventos=eventos)
    proto = _spike("spike_s2_docx_atualizador", "s2_docx", "docx_atualizador.py")
    escritor = proto or modulo("escritores.docx_a")
    if escritor is None:
        raise unittest.SkipTest("sem gerador de .docx de entrada (spikes/s2_docx ausente e escritores.docx_a ainda não existe)")
    escritor.gravar(None, estado, Path(destino))
    return Path(destino)


def xlsx_de_entrada(destino, n=200, fichas=None):
    """.xlsx do modelo B com `n` linhas. Prefere o gerador do spike S1 (independente); sem ele usa
    `escritores.xlsx_b`; sem nenhum dos dois, pula o teste. Devolve o Path."""
    gerador = _spike("spike_s1_gerar_modelo", "s1_xlsx", "gerar_modelo.py")
    if gerador is not None:
        gerador.gerar(Path(destino), "completo", n_linhas=n)
        return Path(destino)
    escritor = modulo("escritores.xlsx_b")
    if escritor is None:
        raise unittest.SkipTest("sem gerador de .xlsx de entrada (spikes/s1_xlsx ausente e escritores.xlsx_b ainda não existe)")
    if fichas is None:
        import ficticio
        fichas = ficticio.gerar_carteira(n)
    escritor.gravar(None, estado_de_teste(fichas), Path(destino))
    return Path(destino)
