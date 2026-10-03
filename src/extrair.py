"""Texto de cada documento baixado: pdftotext para PDF com texto, OCR local
(ocrmypdf + Tesseract em português) para digitalização, e limpeza de tags
para os documentos que o PJe entrega em HTML. Nada sai da máquina."""
import html
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import comum
from comum import eventos, salvar_eventos
MIN_CARACTERES_POR_PAGINA = 200  # abaixo disso o PDF é tratado como digitalizado


class _SoTexto(HTMLParser):
    BLOCOS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__()
        self.partes, self._ignorar = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._ignorar += 1
        elif tag in self.BLOCOS:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._ignorar -= 1

    def handle_data(self, data):
        if not self._ignorar:
            self.partes.append(data)


def texto_html(caminho):
    p = _SoTexto()
    p.feed(Path(caminho).read_text(encoding="utf-8", errors="replace"))
    return html.unescape("".join(p.partes))


def _tem(programa):
    return shutil.which(programa) is not None


def paginas_pdf(caminho):
    if _tem("pdfinfo"):
        saida = subprocess.run(["pdfinfo", str(caminho)], capture_output=True, text=True).stdout
        m = re.search(r"^Pages:\s+(\d+)", saida, re.M)
        if m:
            return int(m.group(1))
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(caminho)).pages)
    except Exception:
        return 1


def _texto_pdf_python(caminho):
    """Leitura sem programas externos (Windows ou Mac sem o poppler)."""
    try:
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(caminho)).pages)
    except Exception:
        return ""


def texto_pdf(caminho):
    if _tem("pdftotext"):
        texto = subprocess.run(["pdftotext", "-enc", "UTF-8", str(caminho), "-"],
                               capture_output=True, text=True).stdout
    else:
        texto = _texto_pdf_python(caminho)
    if len(texto.strip()) >= MIN_CARACTERES_POR_PAGINA * paginas_pdf(caminho):
        return texto, "pdf"
    if not _tem("ocrmypdf"):  # sem OCR instalado: segue com o que deu para ler (alerta na revisão)
        return texto, "pdf-sem-ocr"
    with tempfile.TemporaryDirectory() as tmp:
        sidecar = Path(tmp) / "ocr.txt"
        r = subprocess.run(["ocrmypdf", "-l", "por", "--force-ocr", "--sidecar", str(sidecar),
                            "--output-type", "none", str(caminho), "-"],
                           capture_output=True, text=True)
        if r.returncode == 0 and sidecar.exists():
            return sidecar.read_text(encoding="utf-8"), "ocr"
    return texto, "pdf-sem-texto"


def limpar(texto):
    texto = texto.replace("\f", "\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n\n", texto).strip()


def extrair_arquivo(caminho):
    caminho = Path(caminho)
    if caminho.suffix.lower() in (".html", ".htm"):
        return limpar(texto_html(caminho)), "html"
    texto, origem = texto_pdf(caminho)
    return limpar(texto), origem


def texto_print(caminho):
    """OCR local do print do visualizador (só o que estava visível na tela)."""
    if not _tem("tesseract"):
        return ""
    r = subprocess.run(["tesseract", str(caminho), "-", "-l", "por"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def rodar():
    lista = eventos()
    feitos = 0
    for ev in lista:
        if ev["tipo_evento"] != "documento" or ev["status"] != "coletado":
            continue
        alertas = ev.setdefault("alertas", [])
        if ev.get("arquivo"):
            texto, origem = extrair_arquivo(ev["arquivo"])
        elif ev.get("print"):
            texto, origem = limpar(texto_print(ev["print"])), "ocr-print"
            alertas.append("Documento não baixado: texto lido do print (só a parte visível na tela). Conferir nos autos.")
        else:
            ev["status"] = "sem_arquivo"
            continue
        destino = comum.TEXTOS_DIR / f"{ev['id'].replace(':', '_')}.txt"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        ev.update(texto_arquivo=str(destino), origem_texto=origem, status="extraido")
        if len(texto) < 100:
            alertas.append("Documento sem texto legível: conferir o original.")
        feitos += 1
    salvar_eventos(lista)
    print(f"{feitos} documento(s) com texto extraído.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for arq in sys.argv[1:]:
            t, o = extrair_arquivo(arq)
            print(f"== {arq} [{o}, {len(t)} caracteres]\n{t[:600]}\n")
    else:
        rodar()
