"""Relatório mensal em planilha: parte da planilha do mês anterior (o modelo
que o escritório já usa) e acrescenta, na coluna "Andamentos" da aba
"Processos", o que foi aprovado na revisão, no mesmo estilo:

    "... Em 01/10/2026, o juiz proferiu decisão, determinando ... "
    "... Até 03/10/2026 sem andamentos."   (processo sem novidade aprovada)

A gravação é cirúrgica: só as células "Andamentos" mudam; gráficos, tabelas
dinâmicas, imagens, fórmulas e as outras abas são copiados byte a byte.
(Bibliotecas comuns de Excel apagam gráficos e tabelas dinâmicas ao salvar.)

Uso:
    python planilha.py MODELO.xlsx DESTINO.xlsx [--sem-linha-vazia]
"""
import datetime
import html
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from comum import carteira, eventos, salvar_eventos

ABA = "Processos"
COL_NUMERO, COL_ANDAMENTOS = "A", "P"
CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
FECHO = re.compile(r"\s*Até\s+\d{2}/\d{2}/\d{4},?\s+sem\s+(atualizações|atualização|andamentos?)\.?\s*$", re.I)
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _caminho_da_aba(z, nome):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rid = next(s.get(f"{{{NS['r']}}}id") for s in wb.find("m:sheets", NS) if s.get("name") == nome)
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    alvo = next(r.get("Target") for r in rels if r.get("Id") == rid)
    return "xl/" + alvo.lstrip("/").removeprefix("xl/")


def _textos_compartilhados(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in sst.findall("m:si", NS)]


def _celula(xml, ref):
    """(início, fim, texto_da_tag) da célula ref no XML da aba, ou None."""
    m = re.search(rf'<c r="{ref}"(?:\s[^>]*)?(?:/>|>.*?</c>)', xml, re.S)
    return (m.start(), m.end(), m.group(0)) if m else None


def _valor(tag, compartilhados):
    if 't="s"' in tag:
        v = re.search(r"<v>(\d+)</v>", tag)
        return compartilhados[int(v.group(1))] if v else ""
    if 't="inlineStr"' in tag:
        return html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", tag, re.S)))
    v = re.search(r"<v>(.*?)</v>", tag, re.S)
    return html.unescape(v.group(1)) if v else ""


def _celula_texto(ref, estilo, texto):
    esc = html.escape(texto, quote=False)
    s = f' s="{estilo}"' if estilo else ""
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{esc}</t></is></c>'


def frase_planilha(ev):
    """'Em 01/10/2026, o juiz proferiu decisão, dizendo que...' (estilo do relatório mensal)."""
    import relatorio
    frase, extras = relatorio.linha(ev)
    data = relatorio._data_evento(ev).strftime("%d/%m/%Y")
    primeira = frase.split()[0]
    corpo = frase if (len(primeira) > 1 and primeira.isupper()) else frase[0].lower() + frase[1:]  # mantém siglas
    if ev.get("grau") and ev["grau"] != "1º grau":
        corpo = f"no {ev['grau']}, {corpo}"
    texto = f"Em {data} {corpo}"  # estilo da planilha: sem vírgula após a data
    for x in extras:
        texto += f" {x}."
    return texto


def linhas_da_aba(caminho_xlsx):
    """{numero: linha} dos processos na aba Processos."""
    with zipfile.ZipFile(caminho_xlsx) as z:
        xml = z.read(_caminho_da_aba(z, ABA)).decode("utf-8")
        compartilhados = _textos_compartilhados(z)
    linhas = {}
    for m in re.finditer(rf'<c r="{COL_NUMERO}(\d+)"(?:\s[^>]*)?(?:/>|>.*?</c>)', xml, re.S):
        achado = CNJ.search(_valor(m.group(0), compartilhados))
        if achado:
            linhas[achado.group(0)] = int(m.group(1))
    return linhas


def gerar(modelo, destino, sem_novidade=True, hoje=None):
    """Volta (processos atualizados, processos sem linha na planilha)."""
    hoje = hoje or datetime.date.today()
    lista = eventos()
    aprovados = [e for e in lista if e["status"] == "aprovado"]
    acompanhados = set(carteira())
    with zipfile.ZipFile(modelo) as z:
        aba = _caminho_da_aba(z, ABA)
        xml = z.read(aba).decode("utf-8")
        compartilhados = _textos_compartilhados(z)
        partes = {i.filename: (i, z.read(i.filename)) for i in z.infolist()}
    linhas = linhas_da_aba(modelo)

    por_processo = {}
    for ev in aprovados:
        por_processo.setdefault(ev["numero"], []).append(ev)
    fora = sorted(n for n in por_processo if n not in linhas)
    atualizados = []
    import relatorio
    for numero, linha in sorted(linhas.items(), key=lambda x: -x[1]):  # de baixo para cima: posições não mudam
        evs = sorted(por_processo.get(numero, []), key=relatorio.ordem)
        if not evs and not (sem_novidade and numero in acompanhados):
            continue
        ref = f"{COL_ANDAMENTOS}{linha}"
        achada = _celula(xml, ref)
        if achada:
            ini, fim, tag = achada
            atual = _valor(tag, compartilhados).rstrip()
            estilo = (re.search(r'\ss="(\d+)"', tag) or [None, None])[1]
        else:  # célula vazia que nem existe no XML: entra no fim da linha
            m = re.search(rf'<row r="{linha}"[^>]*>(.*?)</row>', xml, re.S)
            ini = fim = m.end(1)
            atual, estilo = "", None
        # o fecho "Até 29/09/2026 sem atualizações." do relatório anterior sai:
        # ou vira andamento novo, ou é renovado com a data de hoje
        fecho = FECHO.search(atual)
        expressao = fecho.group(1).lower() if fecho else "atualizações"
        if fecho:
            atual = atual[:fecho.start()].rstrip()
        if evs:
            acrescimo = " ".join(frase_planilha(e) for e in evs)
        else:
            acrescimo = f"Até {hoje:%d/%m/%Y} sem {expressao}."
        novo = f"{atual} {acrescimo}".strip()
        xml = xml[:ini] + _celula_texto(ref, estilo, novo) + xml[fim:]
        atualizados.append(numero)

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w") as out:
        for nome, (info, dados) in partes.items():
            out.writestr(info, xml.encode("utf-8") if nome == aba else dados)

    agora = datetime.datetime.now().isoformat(timespec="seconds")
    for ev in aprovados:
        if ev["numero"] in linhas:
            ev.update(status="relatado", relatorio=str(destino), relatado_em=agora)
    salvar_eventos(lista)
    return sorted(atualizados), fora


if __name__ == "__main__":
    a = sys.argv[1:]
    feitos, fora = gerar(a[0], a[1], sem_novidade="--sem-linha-vazia" not in a)
    print(f"{len(feitos)} processo(s) atualizado(s) em {a[1]}")
    if fora:
        print("Aprovados sem linha na planilha (continuam aprovados):", *fora, sep="\n  ")
