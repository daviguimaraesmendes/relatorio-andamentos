"""Rodada completa, igual no Mac e no Windows: coleta nos autos (jus.br e TRTs),
extração do texto, resumo pela IA local. É o que o botão Atualizar do painel roda.

    python rodar.py --projeto <pasta> [--desde DD/MM/AAAA] [--historico N] [--processo N1,N2]
"""
import datetime
import os
import shutil
import subprocess
import sys
import time
import urllib.request

if "--projeto" in sys.argv:  # antes de importar comum: define o relatório ativo
    os.environ["RELATORIO_PROJETO"] = sys.argv[sys.argv.index("--projeto") + 1]

import comum  # noqa: E402


def _arg(nome):
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else None


def ollama_no_ar():
    try:
        urllib.request.urlopen(comum.config().get("ollama_url", "http://127.0.0.1:11434") + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


def main():
    import coletor
    import extrair
    import resumir

    desde = _arg("--desde")
    if desde:
        d, m, a = (int(x) for x in desde.split("/"))
        desde = datetime.date(a, m, d)
    numeros = [n.strip() for n in _arg("--processo").split(",")] if _arg("--processo") else None
    try:
        coletor.rodar(numeros, int(_arg("--historico") or 0), desde)
    except Exception as e:
        print(f"Coleta com falha ({e}); seguindo com o que já foi baixado.", flush=True)
    extrair.rodar()
    # o modelo local só roda durante o resumo: liga aqui e desliga no fim
    servidor = None
    if not ollama_no_ar() and shutil.which("ollama"):
        servidor = subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
    try:
        resumir.rodar()
    finally:
        if servidor:
            servidor.terminate()
    n = sum(e["status"] == "rascunho" for e in comum.eventos())
    print(f"{n} rascunho(s) aguardando revisão. Veja em Revisar, no painel.", flush=True)


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:  # só a ajuda, sem rodar nada
        print(__doc__)
        sys.exit(0)
    main()
