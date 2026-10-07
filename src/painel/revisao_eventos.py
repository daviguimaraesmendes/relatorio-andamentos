"""Revisar andamentos (página inicial, /): lista os rascunhos por cliente e grava a aprovação,
o descarte ou a edição (/evento)."""
import datetime
import getpass
import html
from collections import defaultdict

from flask import abort, redirect, request

import comum
import relatorio
from comum import config, eventos, salvar_eventos
from painel.base import _msg


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.get("/")
    def inicio():
        lista = eventos()
        rascunhos = [e for e in lista if e["status"] == "rascunho"]
        aprovados = sum(e["status"] == "aprovado" for e in lista)
        por_cliente = defaultdict(list)
        for ev in rascunhos:
            por_cliente[ev["cliente"]].append(ev)
        h = [cabecalho("revisar"), "<h1>Revisar andamentos</h1>", _msg(),
             f"<div class='cartoes'><div class='cartao'><b>{len(rascunhos)}</b>para revisar</div>"
             f"<div class='cartao'><b>{aprovados}</b>aprovados, aguardando a planilha</div>"
             f"<div class='cartao'><b>{len(comum.carteira())}</b>processos acompanhados</div></div>"]
        for cliente, evs in sorted(por_cliente.items()):
            h.append(f"<h2>{html.escape(cliente or 'sem cliente')}</h2>")
            for ev in sorted(evs, key=lambda e: (e["numero"], relatorio.ordem(e))):
                esc = lambda c: html.escape(ev.get(c) or "")
                h.append(f"<form class='ev' method='post' action='/evento'>{oculto}<input type='hidden' name='id' value='{esc('id')}'>"
                         f"<div class='meta'>{esc('data')} · {esc('numero')}{(' · ' + esc('grau')) if ev.get('grau') else ''} · {esc('titulo')}"
                         + (f" · <a href='/documento?id={html.escape(ev['id'])}' target='_blank'>abrir documento</a>" if ev.get("arquivo") else "")
                         + (f" · <a href='/print?id={html.escape(ev['id'])}' target='_blank'>ver print</a>" if ev.get("print") else "")
                         + (f" · modelo {esc('modelo')}" if ev.get("modelo") else "") + "</div>")
                polo = {"ativo": "autor", "passivo": "réu"}.get(ev.get("polo_cliente") or "", "polo não informado")
                efeito = {"favoravel": "favorável", "desfavoravel": "desfavorável", "neutro": "neutro",
                          "incerto": "incerto"}.get(ev.get("efeito") or "", "")
                h.append(f"<div class='meta'>Cliente {esc('cliente')} ({polo})"
                         + (f" · efeito para o cliente: <b>{efeito}</b>" if efeito else "") + "</div>")
                for a in ev.get("alertas", []):
                    h.append(f"<div class='alerta'>{html.escape(a)}</div>")
                h.append(f"<label>O que aconteceu<textarea name='frase' rows='2'>{esc('frase')}</textarea></label>"
                         f"<label>Conteúdo (opcional)<textarea name='conteudo' rows='2'>{esc('conteudo')}</textarea></label>")
                if ev.get("trecho_origem"):
                    h.append(f"<blockquote>Trecho do documento: “{esc('trecho_origem')}”</blockquote>")
                for campo, rotulo in (("prazo", "Prazo"), ("audiencia", "Audiência")):
                    h.append(f"<label>{rotulo}<textarea name='{campo}' rows='1'>{esc(campo)}</textarea></label>")
                h.append("<button name='acao' value='aprovar' class='principal'>Aprovar</button>"
                         "<button name='acao' value='salvar'>Salvar sem aprovar</button>"
                         "<button name='acao' value='descartar'>Descartar</button></form>")
        if not rascunhos:
            h.append("<p>Nada para revisar. Use <a href='/atualizar'>Atualizar</a> para buscar andamentos novos.</p>")
        return "".join(h)

    @app.post("/evento")
    def evento():
        token_ok()
        lista = eventos()
        ev = next((e for e in lista if e["id"] == request.form["id"]), None)
        if ev is None or ev["status"] != "rascunho":
            abort(404)
        for campo in ("frase", "conteudo", "prazo", "audiencia"):
            ev[campo] = request.form.get(campo, "").strip() or None
        acao = request.form["acao"]
        if acao == "aprovar":
            if not ev.get("frase"):
                abort(400, "Frase vazia.")
            ev.update(status="aprovado", aprovado_por=config().get("revisor") or getpass.getuser(),
                      aprovado_em=datetime.datetime.now().isoformat(timespec="seconds"))
        elif acao == "descartar":
            ev.update(status="descartado", motivo="Descartado na revisão.")
        salvar_eventos(lista)
        return redirect("/")
