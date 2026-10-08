"""Lançador do painel (usado por "Abrir painel.command" e "Abrir painel.bat").

    python abrir_painel.py [caminho-da-tela]

- Painel fechado: sobe o servidor (revisao.py --abrir) e abre o navegador.
- Painel aberto e na versão do disco: só abre o navegador.
- Painel aberto numa versão ANTIGA (pacote novo copiado por cima, ou atualização do GitHub): encerra o servidor
  antigo e sobe o novo, para que o código novo realmente rode. Se houver coleta ou tarefa em andamento, não encerra
  nada: avisa e deixa para depois (reiniciar mataria a coleta).
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
WINDOWS = sys.platform.startswith("win")


def porta():
    sys.path.insert(0, str(AQUI))
    import comum
    return int(comum.config().get("porta_revisao", 5072))


def _get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def estado_do_painel(porta_):
    """'parado' | 'atual' | 'velho' | 'ocupado_velho' | 'ocupado' (ocupado = coleta ou tarefa em andamento)."""
    base = f"http://127.0.0.1:{porta_}"
    try:
        _get(base + "/atencao.json", 2)
    except Exception:
        try:
            _get(base + "/", 2)
        except urllib.error.HTTPError:
            pass                       # respondeu (mesmo com erro): há um servidor
        except Exception:
            return "parado"
    try:
        _, corpo = _get(base + "/versao.json")
        d = json.loads(corpo)
    except Exception:
        # servidor tão antigo que nem tem /versao.json: vale ver se está coletando antes de decidir reiniciar
        try:
            _, corpo = _get(base + "/fluxo/progresso.json")
            if json.loads(corpo).get("estado") in ("rodando", "pausada", "pausado"):
                return "ocupado_velho"
            _, pagina = _get(base + "/atualizar")
            if "tarefa em andamento" in pagina or "Interromper" in pagina:
                return "ocupado_velho"
        except Exception:
            pass
        return "velho"
    velho = d.get("carregada") != d.get("arquivo")
    if d.get("coleta") or d.get("tarefa"):
        return "ocupado_velho" if velho else "ocupado"
    return "velho" if velho else "atual"


def pids_na_porta(porta_):
    """PIDs que escutam a porta (vazio se não souber)."""
    try:
        if WINDOWS:
            saida = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15).stdout
            return sorted({int(m.group(1)) for linha in saida.splitlines() if "LISTENING" in linha and f":{porta_} " in linha
                           for m in [re.search(r"(\d+)\s*$", linha.strip())] if m})
        saida = subprocess.run(["lsof", "-nP", f"-iTCP:{porta_}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=15).stdout
        return sorted({int(x) for x in saida.split()})
    except Exception:
        return []


def encerrar_servidor(porta_):
    """Encerra o servidor antigo e espera a porta ser liberada. True se liberou."""
    for pid in pids_na_porta(porta_):
        try:
            if WINDOWS:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=15)
            else:
                os.kill(pid, 15)
        except Exception:
            pass
    for _ in range(10):
        if not pids_na_porta(porta_):
            return True
        time.sleep(1)
    return False


def principal(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    tela = argv[0] if argv else ""
    p = porta()
    url = f"http://127.0.0.1:{p}/{tela}"
    estado = estado_do_painel(p)
    if estado == "atual" or estado == "ocupado":
        webbrowser.open(url)
        return 0
    if estado == "ocupado_velho":
        print("Há uma coleta ou tarefa em andamento num painel de versão ANTIGA. Não vou reiniciar agora para não perdê-la.\n"
              "Quando terminar, feche a janela do painel e abra de novo.", flush=True)
        webbrowser.open(url)
        return 0
    if estado == "velho":
        print("O painel aberto é de uma versão antiga; reiniciando para carregar a nova...", flush=True)
        if not encerrar_servidor(p):
            print(f"Não consegui encerrar o painel antigo (porta {p}). Feche a janela dele e abra de novo.", flush=True)
            return 1
    os.chdir(AQUI)
    comando = [sys.executable, "revisao.py", "--abrir"]
    if WINDOWS:
        return subprocess.call(comando)
    os.execv(sys.executable, comando)


if __name__ == "__main__":
    sys.exit(principal())
