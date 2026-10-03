"""Caminhos, leitura/gravação de JSON e o arquivo de eventos.

Um "evento" é tudo o que pode virar uma linha do relatório ao cliente: um
documento novo nos autos ou uma movimentação sem documento. Todos ficam em
data/eventos.json, com um status que anda nesta ordem:

    coletado -> extraido -> rascunho -> aprovado -> relatado
                                    \\-> descartado

Os caminhos dependem do relatório (projeto) ativo; ver usar_projeto().
"""
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_FILE = RAIZ / "config.json"
MOVIMENTOS_FILE = RAIZ / "movimentos.json"
PROJETOS_DIR = Path(os.environ.get("RELATORIO_PROJETOS", RAIZ / "projetos"))
ATUAL_FILE = PROJETOS_DIR / ".projeto_atual"

# Cada relatório é um projeto autônomo em projetos/<slug>/:
#   projeto.json   nome, planilha modelo, data do último relatório
#   clientes.json  carteira.json
#   data/          eventos, estado da coleta, documentos, prints, relatórios
# Os caminhos abaixo apontam para o projeto ativo (usar_projeto). Nos testes,
# RELATORIO_DATA / RELATORIO_CARTEIRA / RELATORIO_CLIENTES fixam tudo numa pasta temporária.
PROJETO = None
PROJETO_DIR = PROJETO_FILE = None
DATA = CARTEIRA_FILE = CLIENTES_FILE = EVENTOS_FILE = ESTADO_FILE = None
DOCS_DIR = TEXTOS_DIR = RELATORIOS_DIR = DIAG_DIR = PRINTS_DIR = None


def _apontar(data, carteira_file, clientes_file):
    global DATA, CARTEIRA_FILE, CLIENTES_FILE, EVENTOS_FILE, ESTADO_FILE
    global DOCS_DIR, TEXTOS_DIR, RELATORIOS_DIR, DIAG_DIR, PRINTS_DIR
    DATA, CARTEIRA_FILE, CLIENTES_FILE = Path(data), Path(carteira_file), Path(clientes_file)
    EVENTOS_FILE = DATA / "eventos.json"
    ESTADO_FILE = DATA / "estado_coleta.json"
    DOCS_DIR = DATA / "documentos"
    TEXTOS_DIR = DATA / "textos"
    RELATORIOS_DIR = DATA / "relatorios"
    DIAG_DIR = DATA / "diagnosticos"
    PRINTS_DIR = DATA / "prints"


def projetos():
    """[(slug, dados do projeto.json)] em ordem de nome."""
    if not PROJETOS_DIR.exists():
        return []
    achados = [(d.name, load_json(d / "projeto.json", {})) for d in PROJETOS_DIR.iterdir()
               if d.is_dir() and (d / "projeto.json").exists()]
    return sorted(achados, key=lambda x: x[1].get("nome", x[0]).lower())


def usar_projeto(slug):
    global PROJETO, PROJETO_DIR, PROJETO_FILE
    pasta = PROJETOS_DIR / slug
    if not (pasta / "projeto.json").exists():
        raise ValueError(f"Relatório não encontrado: {slug}")
    PROJETO, PROJETO_DIR, PROJETO_FILE = slug, pasta, pasta / "projeto.json"
    _apontar(pasta / "data", pasta / "carteira.json", pasta / "clientes.json")
    try:
        ATUAL_FILE.write_text(slug, encoding="utf-8")
    except OSError:
        pass


def projeto():
    """Dados do projeto ativo (projeto.json)."""
    return load_json(PROJETO_FILE, {}) if PROJETO_FILE else {}


def salvar_projeto(dados):
    save_json(PROJETO_FILE, dados)


def criar_projeto(nome):
    base = slug(nome)
    destino, n = PROJETOS_DIR / base, 2
    while destino.exists():
        destino, n = PROJETOS_DIR / f"{base}-{n}", n + 1
    (destino / "data").mkdir(parents=True)
    save_json(destino / "projeto.json", {"nome": nome.strip(), "planilha_modelo": "", "ultimo_relatorio": ""})
    save_json(destino / "clientes.json", {"clientes": []})
    save_json(destino / "carteira.json", [])
    return destino.name


def _inicial():
    if "RELATORIO_DATA" in os.environ:  # testes e ensaios: pasta fixa
        d = Path(os.environ["RELATORIO_DATA"])
        _apontar(d, os.environ.get("RELATORIO_CARTEIRA", d / "carteira.json"),
                 os.environ.get("RELATORIO_CLIENTES", d / "clientes.json"))
        return
    escolhido = os.environ.get("RELATORIO_PROJETO")
    if not escolhido and ATUAL_FILE.exists():
        escolhido = ATUAL_FILE.read_text(encoding="utf-8").strip()
    disponiveis = [s for s, _ in projetos()]
    if escolhido not in disponiveis:
        escolhido = disponiveis[0] if disponiveis else None
    if escolhido:
        usar_projeto(escolhido)
    else:  # nenhum relatório ainda: caminhos provisórios, nada é gravado até criar um
        _apontar(PROJETOS_DIR / "_vazio" / "data", PROJETOS_DIR / "_vazio" / "carteira.json",
                 PROJETOS_DIR / "_vazio" / "clientes.json")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    """Grava num arquivo temporário e troca no fim: uma queda no meio da
    gravação nunca deixa o JSON pela metade."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def config():
    """config.json é pessoal (fora do repositório); sem ele, vale o config.exemplo.json."""
    if CONFIG_FILE.exists():
        return load_json(CONFIG_FILE, {})
    return load_json(RAIZ / "config.exemplo.json", {})


def carteira():
    """Processos ativos da carteira, indexados pelo número."""
    return {p["numero"]: p for p in load_json(CARTEIRA_FILE, []) if p.get("ativo", True)}


def eventos():
    return load_json(EVENTOS_FILE, [])


def salvar_eventos(lista):
    save_json(EVENTOS_FILE, lista)


def slug(texto):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", texto).strip("-").lower() or "sem-nome"


def normalizar(texto):
    """Minúsculas, sem acento e com espaços colapsados -- para comparar trechos
    de texto vindos do PDF (quebras de linha e hifenização variam)."""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    texto = re.sub(r"-\s*\n\s*", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


_inicial()
