"""IA local (Ollama): vê o que falta e instala. É o que o botão "Instalar IA local" do painel roda.

    python ia.py --status     mostra o que já está pronto
    python ia.py --instalar   instala o Ollama (Windows) e baixa o modelo, com progresso
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import comum

WINDOWS = sys.platform.startswith("win")
URL_INSTALADOR_OLLAMA = "https://ollama.com/download/OllamaSetup.exe"
TAMANHO_MINIMO_INSTALADOR = 50 * 2**20  # o instalador tem centenas de MB; menos que isto é página de erro


def _url():
    return comum.config().get("ollama_url", "http://127.0.0.1:11434")


def ollama_exe():
    """Caminho do ollama, ou None. Procura também nos lugares onde o instalador o coloca,
    porque o PATH deste processo não enxerga uma instalação feita depois que ele abriu."""
    achado = shutil.which("ollama")
    if achado:
        return achado
    candidatos = []
    if WINDOWS:
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles")):
            if base:
                candidatos.append(Path(base) / "Programs" / "Ollama" / "ollama.exe")
                candidatos.append(Path(base) / "Ollama" / "ollama.exe")
    else:
        candidatos.append(Path("/Applications/Ollama.app/Contents/Resources/ollama"))
    return next((str(c) for c in candidatos if c.exists()), None)


def servidor_no_ar():
    try:
        urllib.request.urlopen(_url() + "/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _tem_o_nome(modelo, nomes):
    return modelo in nomes or f"{modelo}:latest" in nomes


def modelo_baixado(modelo):
    """Pergunta ao servidor; se ele estiver desligado, olha o manifesto na pasta de modelos."""
    try:
        with urllib.request.urlopen(_url() + "/api/tags", timeout=2) as r:
            return _tem_o_nome(modelo, {m["name"] for m in json.loads(r.read()).get("models", [])})
    except (urllib.error.URLError, OSError, ValueError):
        pass
    nome, _, etiqueta = modelo.partition(":")
    pasta = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    return (pasta / "manifests" / "registry.ollama.ai" / "library" / nome / (etiqueta or "latest")).exists()


def situacao(modelo):
    return {"instalado": ollama_exe() is not None, "modelo": modelo, "modelo_baixado": modelo_baixado(modelo)}


def pronto(modelo):
    s = situacao(modelo)
    return s["instalado"] and s["modelo_baixado"]


# --- instalação (Windows) ---

def _baixar(url, destino):
    """Baixa mostrando o andamento de 10 em 10 por cento."""
    ultimo = -10
    with urllib.request.urlopen(url, timeout=60) as r, open(destino, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        feito = 0
        while bloco := r.read(1 << 20):
            f.write(bloco)
            feito += len(bloco)
            if total and (feito * 100 // total) >= ultimo + 10:
                ultimo = feito * 100 // total
                print(f"  {ultimo}% ({feito >> 20} de {total >> 20} MB)", flush=True)


def _assinatura_valida(arquivo):
    """O instalador só roda se tiver assinatura digital válida da Ollama."""
    ps = (f"$s = Get-AuthenticodeSignature -LiteralPath '{arquivo}'; "
          "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'Ollama') { 'ok' } else { $s.Status }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
    return r.stdout.strip() == "ok"


def instalar_ollama():
    if ollama_exe():
        print("Ollama já instalado.", flush=True)
        return True
    if not WINDOWS:
        print("Instale o Ollama por https://ollama.com/download (no Mac: brew install ollama) e clique de novo.", flush=True)
        return False
    with tempfile.TemporaryDirectory() as tmp:
        arquivo = Path(tmp) / "OllamaSetup.exe"
        print("Baixando o instalador do Ollama (ollama.com)...", flush=True)
        _baixar(URL_INSTALADOR_OLLAMA, arquivo)
        if arquivo.stat().st_size < TAMANHO_MINIMO_INSTALADOR:
            print("O arquivo baixado é pequeno demais para ser o instalador. Tente de novo mais tarde.", flush=True)
            return False
        print("Conferindo a assinatura digital do instalador...", flush=True)
        if not _assinatura_valida(arquivo):
            print("A assinatura do instalador não é válida. Por segurança, nada foi instalado.", flush=True)
            return False
        print("Instalando o Ollama (pode demorar alguns minutos)...", flush=True)
        subprocess.run([str(arquivo), "/SILENT", "/NORESTART"], check=False)
    for _ in range(30):
        if ollama_exe():
            print("Ollama instalado.", flush=True)
            return True
        time.sleep(2)
    print("A instalação do Ollama não terminou. Tente de novo ou instale por ollama.com/download.", flush=True)
    return False


def ligar_servidor():
    """Liga o servidor se estiver desligado. Devolve o processo que ligamos (para desligar depois) ou None."""
    if servidor_no_ar():
        return None
    exe = ollama_exe()
    if not exe:
        return None
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
    proc = subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
    for _ in range(30):
        if servidor_no_ar():
            break
        time.sleep(1)
    return proc


def baixar_modelo(modelo):
    """Baixa pela API do servidor, mostrando o andamento de 5 em 5 por cento de cada parte."""
    corpo = json.dumps({"model": modelo, "stream": True}).encode()
    req = urllib.request.Request(_url() + "/api/pull", data=corpo, headers={"Content-Type": "application/json"})
    marca = {}
    with urllib.request.urlopen(req, timeout=600) as r:
        for linha in r:
            if not linha.strip():
                continue
            info = json.loads(linha)
            if info.get("error"):
                raise RuntimeError(info["error"])
            total, feito, parte = info.get("total"), info.get("completed"), info.get("digest", "")
            if total and feito is not None:
                pct = feito * 100 // total
                if pct >= marca.get(parte, -5) + 5:
                    marca[parte] = pct
                    print(f"  baixando {parte[7:19] or 'modelo'}: {pct}% ({feito >> 20} de {total >> 20} MB)", flush=True)
            elif info.get("status") and info["status"] != marca.get("_status"):
                marca["_status"] = info["status"]
                print(f"  {info['status']}", flush=True)
    return True


def instalar(modelo):
    if not instalar_ollama():
        return 1
    ligado = None
    try:
        ligado = ligar_servidor()
        if not servidor_no_ar():
            print("Não consegui ligar o servidor do Ollama. Abra o Ollama pelo Menu Iniciar e clique de novo.", flush=True)
            return 1
        if modelo_baixado(modelo):
            print(f"O modelo {modelo} já está baixado.", flush=True)
        else:
            print(f"Baixando o modelo {modelo} (2 a 3,5 GB; pode levar vários minutos)...", flush=True)
            baixar_modelo(modelo)
    except (urllib.error.URLError, OSError, RuntimeError) as e:
        print(f"Falha ao baixar o modelo: {e}. Verifique a internet e clique de novo; o que já veio não se perde.", flush=True)
        return 1
    finally:
        if ligado:
            ligado.terminate()
    print("Pronto: a IA local está instalada. Os próximos resumos já usam o modelo.", flush=True)
    return 0


if __name__ == "__main__":
    import resumir

    m = resumir.modelo_escolhido()
    if "--status" in sys.argv:
        print(json.dumps(situacao(m), ensure_ascii=False))
    elif "--instalar" in sys.argv:
        sys.exit(instalar(m))
    else:
        print(__doc__)
