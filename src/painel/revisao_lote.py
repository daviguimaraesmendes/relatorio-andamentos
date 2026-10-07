"""Triagem da revisão (/triagem): contadores por nível de risco, filtros (cliente, responsável, tribunal,
nível, processo), ordenação por risco e aprovação em lote SÓ dos verdes, com amostragem obrigatória.

As regras de nível e do lote estão em triagem.py (sem tela, testável sozinha); aqui só a página:

    GET  /triagem         lista dos rascunhos por risco + resumo do que o lote faria agora
    POST /triagem/lote    aprova os verdes fora da amostra, em nome de quem revisa, e registra o lote

Amarelos e vermelhos nunca entram no lote (o servidor reclassifica no momento de aprovar). Uma parte
dos verdes (10%, configurável em config.json, "triagem") fica de fora de propósito: é a amostra que
vai para a revisão manual. Atalhos de teclado na lista: J/K trocam de linha, Enter abre o processo.
Cada linha leva à visão por processo (painel/processo.py).
"""
import getpass
import html
from urllib.parse import quote, urlencode

from flask import abort, redirect, request

import ficha as fch
import triagem
from comum import config, eventos, salvar_eventos
from painel.base import _msg

POR_PAGINA = 100
ROTULO_NIVEL = {"vermelho": "Vermelho", "amarelo": "Amarelo", "verde": "Verde"}

ESTILO_TRIAGEM = """<style>
.nivel{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;border:1px solid}
.nivel.vermelho{background:#fdecec;color:#9b1c1c;border-color:#e9b3b3}
.nivel.amarelo{background:#fff7db;color:#7a5b00;border-color:#ecd68a}
.nivel.verde{background:#eaf6ec;color:#14532d;border-color:#b7dcbd}
.nivel.amostra{background:#eef0fb;color:#2f3a8f;border-color:#bcc3ee}
table.lista{width:100%;border-collapse:collapse;font-size:14px}
table.lista th,table.lista td{border-bottom:1px solid var(--linha);padding:6px 8px;text-align:left;vertical-align:top}
table.lista tr.sel{outline:2px solid var(--acento);outline-offset:-2px;background:var(--fundo2)}
.filtros{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:12px 0}
.filtros label{font-size:13px;color:var(--suave);display:flex;flex-direction:column}
.cartoes .cartao.vermelho{border-left:4px solid #c53030}.cartoes .cartao.amarelo{border-left:4px solid #d69e2e}
.cartoes .cartao.verde{border-left:4px solid #2f855a}
.lote{background:var(--fundo2);border:1px solid var(--linha);border-radius:6px;padding:12px;margin:14px 0}
.motivos{color:var(--suave);font-size:13px;margin:0;padding-left:16px}
</style>"""


def selo(nivel, extra=""):
    return f"<span class='nivel {nivel}'>{ROTULO_NIVEL.get(nivel, nivel)}{extra}</span>"


def data_do_evento(ev):
    """DD/MM/AAAA do evento (campo `data` ou, sem ele, o dia em que foi detectado)."""
    if ev.get("data"):
        return ev["data"]
    return fch.data_br((ev.get("detectado_em") or "")[:10])


def revisor():
    return (config().get("revisor") or getpass.getuser()).strip()


def _filtros(args):
    return {k: (args.get(k) or "").strip() for k in ("cliente", "responsavel", "tribunal", "processo")}


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def _opcoes(nome, valores, atual):
        ops = "".join(f"<option value='{html.escape(v)}'{' selected' if v == atual else ''}>{html.escape(v)}</option>"
                      for v in sorted({v for v in valores if v}))
        return f"<select name='{nome}'><option value=''>todos</option>{ops}</select>"

    @app.get("/triagem")
    def triagem_tela():
        lista, fichas = eventos(), fch.carregar(todas=True)
        todos = triagem.classificar_lista(lista, fichas)
        filtros = _filtros(request.args)
        nivel = request.args.get("nivel") if request.args.get("nivel") in triagem.NIVEIS else ""
        ordem = request.args.get("ordem") if request.args.get("ordem") in ("risco", "data", "processo") else "risco"
        base = triagem.filtrar(todos, **filtros)
        c = triagem.contar(base)
        vistos = triagem.ordenar_por_risco(triagem.filtrar(base, nivel=nivel))
        if ordem == "processo":
            vistos.sort(key=lambda i: (i["ev"].get("numero") or "", triagem.RISCO[i["nivel"]]))
        elif ordem == "data":
            vistos.sort(key=lambda i: (fch.parse_data(data_do_evento(i["ev"])) or "", i["ev"].get("id") or ""), reverse=True)
        plano = triagem.preparar_lote(lista, fichas, filtros)
        na_amostra = {i["ev"]["id"] for i in plano["amostra"]}
        cfg = triagem.configuracao()
        aprovados = sum(e["status"] == "aprovado" for e in lista)

        h = [cabecalho("revisar"), ESTILO_TRIAGEM, "<h1>Triagem da revisão</h1>", _msg(),
             "<p class='dica'>Cada linha ganha um nível de risco por regras simples. Vermelho: efeito desfavorável, prazo, "
             "audiência, valor em dinheiro, mudança de resultado ou trecho que não confere. Amarelo: algum alerta. "
             "Verde: o resto. <a href='/'>Voltar à revisão linha a linha</a>.</p>",
             "<div class='cartoes'>"
             f"<div class='cartao vermelho'><b>{c['vermelho']}</b>vermelhas (sempre revisar)</div>"
             f"<div class='cartao amarelo'><b>{c['amarelo']}</b>amarelas</div>"
             f"<div class='cartao verde'><b>{c['verde']}</b>verdes</div>"
             f"<div class='cartao'><b>{aprovados}</b>aprovadas, aguardando a planilha</div></div>",
             "<form class='filtros' method='get' action='/triagem'>"
             f"<label>Cliente{_opcoes('cliente', [triagem.cliente_de(i) for i in todos], filtros['cliente'])}</label>"
             f"<label>Responsável{_opcoes('responsavel', [triagem.responsavel_de(i) for i in todos], filtros['responsavel'])}</label>"
             f"<label>Tribunal{_opcoes('tribunal', [triagem.tribunal_de(i) for i in todos], filtros['tribunal'])}</label>"
             "<label>Nível<select name='nivel'><option value=''>todos</option>"
             + "".join(f"<option value='{n}'{' selected' if n == nivel else ''}>{ROTULO_NIVEL[n]}</option>"
                       for n in ("vermelho", "amarelo", "verde")) + "</select></label>"
             f"<label>Processo<input type='text' name='processo' value='{html.escape(filtros['processo'])}' size='22' "
             "placeholder='parte do número'></label>"
             "<label>Ordenar por<select name='ordem'>"
             + "".join(f"<option value='{v}'{' selected' if v == ordem else ''}>{t}</option>"
                       for v, t in (("risco", "risco"), ("data", "data"), ("processo", "processo"))) + "</select></label>"
             "<button>Filtrar</button> <a href='/triagem'>limpar</a></form>"]

        # ---- aprovação em lote
        n_aprovar, n_amostra = len(plano["aprovar"]), len(plano["amostra"])
        barrados = plano["barrados"]
        h.append("<div class='lote'><b>Aprovação em lote (só verdes)</b>"
                 f"<p>Com os filtros acima há <b>{len(plano['elegiveis'])}</b> linha(s) verde(s) elegível(is). "
                 f"Por regra, <b>{cfg['amostragem_pct']:g}%</b> delas (<b>{n_amostra}</b>) ficam de fora para você conferir à mão "
                 f"(marcadas <span class='nivel amostra'>amostra</span> na lista). "
                 f"Seriam aprovadas agora: <b>{n_aprovar}</b>.</p>"
                 f"<p class='dica'>Amarelas ({barrados['amarelo']}) e vermelhas ({barrados['vermelho']}) nunca entram no lote"
                 + (f"; {barrados['amostra_anterior']} verde(s) já sorteada(s) para a amostra de lote anterior esperam conferência"
                    if barrados["amostra_anterior"] else "") + ".</p>"
                 f"<form method='post' action='/triagem/lote'>{oculto}<input type='hidden' name='confirmar' value='1'>"
                 + "".join(f"<input type='hidden' name='{k}' value='{html.escape(v)}'>" for k, v in filtros.items())
                 + f"<p class='dica'>O lote fica registrado em nome de <b>{html.escape(revisor())}</b> (nome em Acesso e escritório), "
                   "com data e hora.</p>"
                 f"<button class='principal' {'disabled' if not n_aprovar else ''}>Aprovar {n_aprovar} verde(s) em lote</button></form>")
        recentes = triagem.lotes()[-3:]
        if recentes:
            h.append("<p class='dica'>Últimos lotes: " + "; ".join(
                f"{html.escape(l['em'].replace('T', ' '))} por {html.escape(l['aprovado_por'])} ({len(l['aprovados'])} aprovada(s), "
                f"{len(l['amostra'])} na amostra)" for l in reversed(recentes)) + ".</p>")
        h.append("</div>")

        # ---- lista
        pagina = max(1, int(request.args["pagina"])) if (request.args.get("pagina") or "").isdigit() else 1
        total_pag = max(1, -(-len(vistos) // POR_PAGINA))
        pagina = min(pagina, total_pag)
        fatia = vistos[(pagina - 1) * POR_PAGINA:pagina * POR_PAGINA]
        h.append(f"<h2>{len(vistos)} linha(s) para revisar</h2>")
        if not fatia:
            h.append("<p>Nada com esses filtros. Use <a href='/atualizar'>Atualizar</a> para buscar andamentos novos.</p>")
        else:
            h.append("<table class='lista' id='lista'><tr><th>Nível</th><th>Data</th><th>Processo</th><th>Cliente</th>"
                     "<th>O que aconteceu</th><th>Por quê</th></tr>")
            for i in fatia:
                ev = i["ev"]
                extra = ""
                if ev["id"] in na_amostra or ev.get("amostra_lote"):
                    extra = " <span class='nivel amostra'>amostra</span>"
                h.append(f"<tr data-href='/processo?numero={quote(ev.get('numero') or '')}'>"
                         f"<td>{selo(i['nivel'])}{extra}</td><td>{html.escape(data_do_evento(ev))}</td>"
                         f"<td><a href='/processo?numero={quote(ev.get('numero') or '')}'>{html.escape(ev.get('numero') or '')}</a></td>"
                         f"<td>{html.escape(triagem.cliente_de(i))}</td>"
                         f"<td>{html.escape(((ev.get('frase') or '') + ' ' + (ev.get('conteudo') or '')).strip())}</td>"
                         "<td>" + (("<ul class='motivos'>" + "".join(f"<li>{html.escape(m)}</li>" for m in i["motivos"]) + "</ul>")
                                   if i["motivos"] else "<span class='dica'>sem alertas</span>") + "</td></tr>")
            h.append("</table>")
            if total_pag > 1:
                def _pg(n):
                    q = {k: v for k, v in request.args.items() if k != "pagina"}
                    return f"/triagem?{urlencode({**q, 'pagina': n})}"
                h.append("<p>" + (f"<a href='{_pg(pagina - 1)}'>anterior</a> · " if pagina > 1 else "")
                         + f"página {pagina} de {total_pag}"
                         + (f" · <a href='{_pg(pagina + 1)}'>próxima</a>" if pagina < total_pag else "") + "</p>")
            h.append("<p class='dica'>Atalhos: J/K trocam de linha, Enter abre o processo.</p>"
                     "<script>(function(){var l=[].slice.call(document.querySelectorAll('#lista tr[data-href]')),i=-1;"
                     "function f(n){if(!l.length)return;i=Math.max(0,Math.min(l.length-1,n));l.forEach(function(r){r.classList.remove('sel')});"
                     "l[i].classList.add('sel');l[i].scrollIntoView({block:'nearest'})}"
                     "document.addEventListener('keydown',function(e){if(e.ctrlKey||e.metaKey||e.altKey)return;"
                     "if(/^(INPUT|TEXTAREA|SELECT)$/.test((e.target||{}).tagName||''))return;var k=e.key.toLowerCase();"
                     "if(k==='j')f(i+1);else if(k==='k')f(i-1);else if(e.key==='Enter'&&i>=0)location.href=l[i].dataset.href})})();</script>")
        return "".join(h)

    @app.post("/triagem/lote")
    def triagem_lote():
        token_ok()
        if request.form.get("confirmar") != "1":
            abort(400, "Falta a confirmação do lote.")
        filtros = _filtros(request.form)
        lista, fichas = eventos(), fch.carregar(todas=True)
        plano = triagem.preparar_lote(lista, fichas, filtros)
        if not plano["aprovar"]:
            return redirect("/triagem?msg=" + quote("Nenhuma linha verde para aprovar em lote com esses filtros."))
        registro = triagem.aplicar_lote(lista, fichas, revisor(), filtros)
        salvar_eventos(lista)
        triagem.registrar_lote(registro)
        msg = (f"Lote aprovado: {len(registro['aprovados'])} linha(s) verde(s), em nome de {registro['aprovado_por']}. "
               f"{len(registro['amostra'])} ficaram para conferência manual (amostra).")
        return redirect(f"/triagem?{urlencode({k: v for k, v in filtros.items() if v})}{'&' if any(filtros.values()) else ''}msg={quote(msg)}")
