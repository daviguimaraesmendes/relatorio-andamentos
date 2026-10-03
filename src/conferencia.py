"""Conferência semanal (rede de segurança, sem IA): entra no jus.br, lê os
andamentos e documentos dos últimos N dias de cada processo da carteira e
separa tudo o que ainda NÃO entrou num relatório aprovado.

Saída, para revisão manual do responsável:

    data/conferencia/AAAA-MM-DD/<responsavel>/<cliente>/<processo>/
        movimentos.png          print da aba Movimentos
        <documento>.pdf|.html   teor baixado pelo visualizador
        <documento>-print.png   print do documento aberto
    data/conferencia/AAAA-MM-DD/<responsavel>/PENDENCIAS.csv
    data/conferencia/AAAA-MM-DD/indice.html   (todas as pendências, por responsável)

Uso:
    python conferencia.py              # últimos 7 dias
    python conferencia.py --dias 14
"""
import csv
import os
import datetime
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

if "--projeto" in sys.argv:  # antes de importar comum: define o relatório ativo
    os.environ["RELATORIO_PROJETO"] = sys.argv[sys.argv.index("--projeto") + 1]

import coletor  # noqa: E402
import janela  # noqa: E402
import comum
from comum import carteira, eventos, load_json, save_json, slug
from carteira import clientes

DATA_NUM = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def responsavel(proc):
    if proc.get("responsavel"):
        return proc["responsavel"]
    for c in clientes():
        if c["nome"] == proc.get("cliente") and c.get("responsavel"):
            return c["responsavel"]
    return "sem-responsavel"


def _data(texto):
    if not texto:
        return None
    m = DATA_NUM.search(texto)
    if m:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    extenso = coletor.data_por_extenso(texto)
    return _data(extenso) if extenso else None


def ja_relatados(lista, numero):
    """Chaves de andamento e nomes de documento deste processo que já saíram
    em relatório aprovado (ou foram descartados de propósito na revisão).
    Andamento é comparado pela chave (data + texto + ordem no dia), porque o
    mesmo texto ('Conclusos para despacho') se repete em datas diferentes."""
    fechados = {"relatado", "aprovado", "descartado"}
    return {e.get("chave") or e["titulo"] for e in lista if e["numero"] == numero and e["status"] in fechados}


def pendencias(movimentos, documentos, relatados, desde):
    """Parte pura (testável): o que, desde a data, ainda não foi relatado.
    movimentos: [(chave, 'dd/mm/aaaa', texto)]; documentos: [(nome, data_ou_None)].
    Documento sem data entra se não foi relatado: na dúvida, mostra."""
    movs = [(d, t) for chave, d, t in movimentos if (_data(d) or datetime.date.min) >= desde and chave not in relatados]
    docs = [(n, d) for n, d in documentos if n not in relatados and (d is None or d >= desde)]
    return movs, docs


def conferir_processo(context, proc, estado, lista, desde, base):
    if re.search(r"\d{7}-\d{2}\.\d{4}\.5\.", proc["numero"]):
        raise RuntimeError("Conferência da Justiça do Trabalho ainda não automatizada: conferir no PJe do TRT.")
    salvas = coletor._tramitacoes_salvas(estado.get(proc["numero"], {}))
    tramitacoes = coletor.abrir_tramitacoes(context, proc["numero"], {k: v for k, v in salvas.items() if v.get("url_autos")})
    linhas = []
    for i, (autos, url, rotulo) in enumerate(tramitacoes):
        sufixo = coletor.grau(rotulo) if len(tramitacoes) > 1 else None
        linhas += _conferir_tramitacao(autos, proc, lista, desde, base, sufixo)
    return linhas


def _conferir_tramitacao(autos, proc, lista, desde, base, sufixo):
    numero = proc["numero"]
    relatados = ja_relatados(lista, numero)
    try:
        coletor.abrir_aba(autos, "Movimentos")
        movimentos = coletor.ler_movimentos(autos)
        coletor.abrir_aba(autos, "Documentos")
        links = coletor.listar_documentos(autos)
        documentos = [(nome, _data(data)) for nome, _, data in links]
        movs, docs = pendencias(movimentos, documentos, relatados, desde)
        if not movs and not docs:
            return []
        pasta = base / slug(responsavel(proc)) / slug(proc.get("cliente") or "sem-cliente") / slug(numero + (f" {sufixo}" if sufixo else ""))
        pasta.mkdir(parents=True, exist_ok=True)
        coletor.abrir_aba(autos, "Movimentos")
        coletor.print_elemento(autos, ".movimentos", pasta / "movimentos.png")
        coletor.abrir_aba(autos, "Documentos")
        linhas = [{"processo": numero, "cliente": proc.get("cliente", ""), "tipo": "andamento", "data": d,
                   "descricao": t, "arquivo": "movimentos.png"} for d, t in movs]
        por_nome = {nome: link for nome, link, _ in links}
        for nome, d in docs:
            arquivo, foto = coletor.abrir_documento(autos, por_nome[nome], nome, pasta / slug(nome)[:80])
            linhas.append({"processo": numero, "cliente": proc.get("cliente", ""), "tipo": "documento",
                           "data": d.strftime("%d/%m/%Y") if d else "sem data na tela", "descricao": nome,
                           "arquivo": (arquivo or foto).name})
            coletor.pausa(coletor.config()["coleta"]["pausa_entre_documentos_s"])
        print(f"  {len(movs)} andamento(s) e {len(docs)} documento(s) pendente(s)")
        return [{**l, "responsavel": responsavel(proc), "pasta": str(pasta.relative_to(base))} for l in linhas]
    finally:
        autos.close()


def escrever_indices(base, todas):
    por_resp = defaultdict(list)
    for l in todas:
        por_resp[l["responsavel"]].append(l)
    campos = ["processo", "cliente", "tipo", "data", "descricao", "arquivo"]
    for resp, linhas in por_resp.items():
        destino = base / slug(resp) / "PENDENCIAS.csv"
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore", delimiter=";")
            w.writeheader()
            w.writerows(linhas)
    partes = ["<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Conferência semanal</title>",
              "<style>body{font-family:-apple-system,system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1f2a2e}"
              "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #d9dfe1;padding:6px;text-align:left;font-size:14px}"
              "h2{margin-top:28px}</style><body>",
              f"<h1>Conferência semanal – {base.name}</h1>",
              f"<p>{len(todas)} pendência(s): andamentos e documentos dos autos que ainda não entraram em relatório aprovado.</p>"]
    for resp, linhas in sorted(por_resp.items()):
        partes.append(f"<h2>{html.escape(resp)} ({len(linhas)})</h2><table><tr><th>Processo</th><th>Cliente</th>"
                      "<th>Data</th><th>Tipo</th><th>Descrição</th><th>Arquivo</th></tr>")
        for l in linhas:
            link = f"{l['pasta']}/{l['arquivo']}"
            partes.append(f"<tr><td>{html.escape(l['processo'])}</td><td>{html.escape(l['cliente'])}</td>"
                          f"<td>{html.escape(l['data'] or '')}</td><td>{l['tipo']}</td><td>{html.escape(l['descricao'])}</td>"
                          f"<td><a href='{html.escape(link)}'>{html.escape(l['arquivo'])}</a></td></tr>")
        partes.append("</table>")
    (base / "indice.html").write_text("".join(partes) + "</body></html>", encoding="utf-8")


def rodar(dias=7):
    from playwright.sync_api import sync_playwright

    cart = carteira()
    if not cart:
        print("Carteira vazia: importe a lista de processos (carteira.py importar).")
        return
    desde = datetime.date.today() - datetime.timedelta(days=dias)
    base = comum.DATA / "conferencia" / f"{datetime.date.today():%Y-%m-%d}"
    estado = load_json(comum.ESTADO_FILE, {})
    lista = eventos()
    todas, falhas = [], []
    with sync_playwright() as p:
        browser, context = janela.abrir_navegador(p)
        coletor.logar(context)
        for proc in cart.values():
            print(f"{proc['numero']} ({proc.get('cliente', '')})")
            try:
                todas += conferir_processo(context, proc, estado, lista, desde, base)
            except Exception as e:
                print(f"  falhou: {e}")
                falhas.append(proc["numero"])
            save_json(comum.ESTADO_FILE, estado)
            coletor.pausa(coletor.config()["coleta"]["pausa_entre_processos_s"])
        browser.close()
    if falhas:
        todas += [{"processo": n, "cliente": cart[n].get("cliente", ""), "tipo": "FALHA", "data": "",
                   "descricao": "Não foi possível abrir os autos: conferir manualmente.", "arquivo": "",
                   "responsavel": responsavel(cart[n]), "pasta": ""} for n in falhas]
    base.mkdir(parents=True, exist_ok=True)
    escrever_indices(base, todas)
    print(f"\n{len(todas)} pendência(s). Índice: {base / 'indice.html'}")


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:  # só a ajuda, sem rodar nada
        print(__doc__)
        sys.exit(0)
    a = sys.argv[1:]
    rodar(int(a[a.index("--dias") + 1]) if "--dias" in a else 7)
    if "--sem-abrir" not in a:
        import webbrowser
        indice = comum.DATA / "conferencia" / f"{datetime.date.today():%Y-%m-%d}" / "indice.html"
        if indice.exists():
            webbrowser.open(indice.as_uri())
