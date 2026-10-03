"""Monta um relatório por cliente só com eventos APROVADOS na revisão.
Evento relatado não volta a aparecer no próximo relatório."""
import datetime
import html
import re
from collections import defaultdict

import comum
from comum import carteira, eventos, salvar_eventos, slug
ESTILO = """
:root { --tinta:#1f2a2e; --suave:#5b6b70; --linha:#d9dfe1; --fundo:#ffffff; --realce:#f3f6f7; }
body { font-family: Georgia, 'Times New Roman', serif; color: var(--tinta); background: var(--fundo);
       max-width: 760px; margin: 40px auto; padding: 0 16px; line-height: 1.55; }
h1 { font-size: 22px; margin-bottom: 4px; }
.sub { color: var(--suave); margin-top: 0; }
h2 { font-size: 17px; border-bottom: 1px solid var(--linha); padding-bottom: 4px; margin-top: 32px; }
.proc { color: var(--suave); font-size: 13px; margin-top: -6px; }
ol { padding-left: 0; list-style: none; }
li { padding: 10px 0; border-bottom: 1px solid var(--realce); }
.data { color: var(--suave); font-size: 13px; display: block; }
.prazo { background: var(--realce); padding: 4px 8px; display: inline-block; margin-top: 6px; font-size: 14px; }
footer { margin-top: 40px; color: var(--suave); font-size: 13px; }
"""


def _data_evento(ev):
    if ev.get("data"):
        try:
            return datetime.datetime.strptime(ev["data"], "%d/%m/%Y")
        except ValueError:
            pass
    return datetime.datetime.fromisoformat(ev["detectado_em"])


def ordem(ev):
    """Data do evento e, no mesmo dia, a hora exata quando o tribunal informa
    (a chave dos andamentos do TRT começa com data e hora ISO)."""
    chave = ev.get("chave") or ""
    hora = chave.split("|")[0] if re.match(r"\d{4}-\d{2}-\d{2}T", chave) else ""
    return (_data_evento(ev), hora)


def linha(ev):
    frase = (ev.get("frase") or "").strip()
    conteudo = (ev.get("conteudo") or "").strip()
    if conteudo:
        conteudo = conteudo[0].lower() + conteudo[1:]
        juncao = " " if conteudo.split()[0].endswith("ndo") else ", "  # "decisão determinando..."
        frase = f"{frase.rstrip('.')}{juncao}{conteudo.rstrip('.')}."
    extras = []
    if ev.get("audiencia"):
        extras.append(f"Audiência: {ev['audiencia'].rstrip('.')}")
    if ev.get("prazo"):
        extras.append(f"Prazo: {ev['prazo'].rstrip('.')}")
    return frase, extras


def gerar_html(cliente, evs, hoje):
    cart = carteira()
    por_processo = defaultdict(list)
    for ev in evs:
        por_processo[ev["numero"]].append(ev)
    partes = [f"<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
              f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
              f"<title>Relatório – {html.escape(cliente)}</title><style>{ESTILO}</style><body>",
              f"<h1>Relatório de andamento processual</h1>",
              f"<p class='sub'>{html.escape(cliente)} · {hoje:%d/%m/%Y}</p>"]
    for numero, lista in por_processo.items():
        proc = cart.get(numero, {})
        contraria = (proc.get("parte_contraria") or "").split(";")[0].strip()
        apelido = proc.get("apelido") or (f"{cliente} x {contraria}" if contraria else cliente)
        partes.append(f"<h2>{html.escape(apelido)}</h2><p class='proc'>Processo nº {html.escape(numero)}</p><ol>")
        for ev in sorted(lista, key=ordem):
            frase, extras = linha(ev)
            partes.append(f"<li><span class='data'>{_data_evento(ev):%d/%m/%Y}</span>{html.escape(frase)}"
                          + "".join(f"<br><span class='prazo'>{html.escape(x)}</span>" for x in extras) + "</li>")
        partes.append("</ol>")
    partes.append("<footer>Relatório revisado pelo advogado responsável. Em caso de dúvida, fale com o escritório.</footer></body></html>")
    return "".join(partes)


def gerar():
    lista = eventos()
    hoje = datetime.datetime.now()
    por_cliente = defaultdict(list)
    for ev in lista:
        if ev["status"] == "aprovado":
            por_cliente[ev["cliente"]].append(ev)
    gerados = []
    for cliente, evs in por_cliente.items():
        destino = comum.RELATORIOS_DIR / slug(cliente) / f"{hoje:%Y-%m-%d-%H%M}-relatorio.html"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(gerar_html(cliente, evs, hoje), encoding="utf-8")
        for ev in evs:
            ev.update(status="relatado", relatorio=str(destino), relatado_em=hoje.isoformat(timespec="seconds"))
        gerados.append(destino)
    salvar_eventos(lista)
    return gerados


if __name__ == "__main__":
    for g in gerar():
        print(g)
