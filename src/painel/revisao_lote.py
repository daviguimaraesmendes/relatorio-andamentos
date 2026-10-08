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
from painel.base import _msg, ajuda

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


# O que cada "motivo" da triagem quer dizer (as regras estão em triagem.py; aqui só a explicação em português simples).
MOTIVOS_VERMELHOS = (
    ("Efeito desfavorável ao cliente.", "A IA (ou quem revisou antes) marcou que o andamento é ruim para o cliente. "
     "Vale pensar em avisá-lo pessoalmente antes de mandar o relatório."),
    ("Há prazo.", "Existe um prazo no campo próprio ou o texto fala em \"prazo\" ou \"tantos dias\". Prazo perdido é o erro mais caro: confira a data."),
    ("Há audiência.", "Existe audiência marcada ou citada. Confira data e hora."),
    ("Há valor em dinheiro.", "O texto traz valor em reais. Confira o número no documento."),
    ("Pode mudar o resultado do processo.", "O texto usa palavras de julgamento (procedente, improcedente, homologação, extinção, "
     "trânsito em julgado, condenação, provimento...). Confira se o resumo diz o que a decisão decidiu."),
    ("Sentença ou acórdão: sempre conferir.", "Decisões que resolvem o rumo do processo nunca passam sem olho humano."),
    ("O trecho de origem não confere com o documento.", "A frase que a IA disse ter tirado do documento não aparece nele. "
     "Abra o documento e confira se o resumo é verdadeiro."),
)
MOTIVOS_AMARELOS = (
    ("Avisos já gravados no andamento", "Qualquer aviso laranja (por exemplo, \"A IA citou dispositivo legal: conferir\", "
     "\"resumo curto demais\", \"nome do cliente não aparece no documento\") deixa a linha amarela."),
    ("Autoria não identificada.", "O programa não conseguiu dizer quem apresentou o documento (autor, réu, juiz...)."),
    ("Sem frase para o relatório.", "A linha está sem o texto \"O que aconteceu\": escreva antes de aprovar."),
    ("Andamento sem tradução cadastrada.", "O programa não conhece este tipo de movimentação e repetiu o texto do tribunal. "
     "Reescreva em linguagem simples."),
    ("Processo sem cliente / Polo do cliente não informado.", "Falta cadastrar o cliente ou o lado dele (autor ou réu) em "
     "Clientes e processos; sem isso o resumo pode ter o ponto de vista errado."),
    ("A IA não soube dizer o efeito para o cliente / Resumo sem trecho de origem.", "O resumo não traz a prova de onde saiu."),
    ("O processo não está na carteira.", "O andamento é de um processo que não está (ou saiu) da lista de acompanhados."),
)


def legenda_dos_niveis():
    """Quadro recolhido que explica as cores e cada motivo que a triagem pode apontar (usado na triagem, no processo e na revisão)."""
    def lista(itens):
        return "<ul class='motivos'>" + "".join(f"<li><b>{html.escape(t)}</b> {html.escape(d)}</li>" for t, d in itens) + "</ul>"
    return ("<details class='caixa'><summary><b>O que significam as cores e os avisos?</b></summary>"
            "<p>O programa dá a cada linha uma cor por regras simples. <b>Não é a IA decidindo</b>: é uma lista de situações em que "
            "um erro custaria caro. As regras são propositalmente largas: é melhor você olhar uma linha tranquila "
            "do que deixar passar uma importante.</p>"
            f"<p>{selo('vermelho')} Sempre olhe com atenção. Nunca entra na aprovação em lote.</p>{lista(MOTIVOS_VERMELHOS)}"
            f"<p>{selo('amarelo')} Revisão normal, mas também nunca entra em lote.</p>{lista(MOTIVOS_AMARELOS)}"
            f"<p>{selo('verde')} Nenhum dos casos acima. Só estes podem ser aprovados em lote, e mesmo assim uma parte "
            "(a amostra) fica de fora para você conferir.</p></details>")


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
             "<div class='caixa'><b>O que fazer agora</b><ol>"
             "<li>Comece pelas linhas <b>vermelhas</b> e <b>amarelas</b>: clique no número do processo para ver tudo dele e "
             "aprovar uma a uma.</li>"
             "<li>Depois, se quiser ganhar tempo, aprove as <b>verdes</b> de uma vez no quadro \"Aprovação em lote\" "
             "(uma amostra fica de fora para você conferir).</li>"
             "<li>Nada vai para os relatórios antes de você aprovar.</li></ol></div>",
             "<p class='dica'>Cada linha ganha um nível de risco por regras simples. Vermelho: efeito desfavorável, prazo, "
             "audiência, valor em dinheiro, mudança de resultado ou trecho que não confere. Amarelo: algum alerta. "
             "Verde: o resto. <a href='/'>Voltar à revisão linha a linha</a>.</p>" + legenda_dos_niveis(),
             "<div class='cartoes'>"
             f"<div class='cartao vermelho'><b>{c['vermelho']}</b>vermelhas (sempre revisar)"
             + ajuda("Linhas com algo que pode custar caro: prazo, audiência, valor em dinheiro, efeito ruim para o cliente, "
                     "sentença ou acórdão, ou resumo que não confere com o documento. Nunca entram na aprovação em lote.") + "</div>"
             f"<div class='cartao amarelo'><b>{c['amarelo']}</b>amarelas"
             + ajuda("Linhas com algum aviso, como autoria não identificada, falta de cliente ou de lado (autor/réu) ou andamento "
                     "sem tradução. Você revisa uma a uma; também não entram em lote.") + "</div>"
             f"<div class='cartao verde'><b>{c['verde']}</b>verdes"
             + ajuda("Linhas sem nenhum dos alertas acima. Só estas podem ser aprovadas em lote, mantida sempre uma amostra "
                     "para você conferir.") + "</div>"
             f"<div class='cartao'><b>{aprovados}</b>aprovadas, aguardando a planilha"
             + ajuda("Linhas que você já aprovou. Entram nos relatórios na próxima vez que você gerar as entregas.") + "</div></div>",
             "<form class='filtros' method='get' action='/triagem'>"
             f"<label>Cliente{_opcoes('cliente', [triagem.cliente_de(i) for i in todos], filtros['cliente'])}</label>"
             f"<label>Responsável{_opcoes('responsavel', [triagem.responsavel_de(i) for i in todos], filtros['responsavel'])}</label>"
             f"<label>Tribunal{_opcoes('tribunal', [triagem.tribunal_de(i) for i in todos], filtros['tribunal'])}</label>"
             "<label>Nível<select name='nivel'><option value=''>todos</option>"
             + "".join(f"<option value='{n}'{' selected' if n == nivel else ''}>{ROTULO_NIVEL[n]}</option>"
                       for n in ("vermelho", "amarelo", "verde")) + "</select></label>"
             f"<label>Processo<input type='text' name='processo' value='{html.escape(filtros['processo'])}' size='22' "
             "placeholder='parte do número, ex.: 0001234'></label>"
             "<label>Ordenar por<select name='ordem'>"
             + "".join(f"<option value='{v}'{' selected' if v == ordem else ''}>{t}</option>"
                       for v, t in (("risco", "risco"), ("data", "data"), ("processo", "processo"))) + "</select></label>"
             "<span><button>Filtrar</button>"
             + ajuda("Mostra só as linhas que combinam com o que você escolheu (cliente, responsável, tribunal, nível, parte do "
                     "número do processo). Os filtros também valem para a aprovação em lote logo abaixo: filtrar por um cliente "
                     "aprova só os verdes dele. Não muda nada nos dados.")
             + " <a href='/triagem'>limpar</a></span></form>"]

        # ---- aprovação em lote
        n_aprovar, n_amostra = len(plano["aprovar"]), len(plano["amostra"])
        barrados = plano["barrados"]
        h.append("<div class='lote'><b>Aprovação em lote (só verdes)</b>"
                 + ajuda("Aprova de uma vez as linhas verdes dos filtros atuais, em seu nome e com data e hora, e registra o lote. "
                         "Uma parte delas (a amostra) fica de fora para você conferir à mão. Amarelas e vermelhas nunca entram. "
                         "Não existe botão para desfazer: depois de aprovada, a linha não volta para revisão por esta tela.") +
                 f"<p>Com os filtros acima há <b>{len(plano['elegiveis'])}</b> linha(s) verde(s) elegível(is). "
                 f"Por regra, <b>{cfg['amostragem_pct']:g}%</b> delas (<b>{n_amostra}</b>) ficam de fora para você conferir à mão "
                 f"(marcadas <span class='nivel amostra'>amostra</span> na lista). "
                 f"Seriam aprovadas agora: <b>{n_aprovar}</b>.</p>"
                 f"<p class='dica'>Amarelas ({barrados['amarelo']}) e vermelhas ({barrados['vermelho']}) nunca entram no lote"
                 + (f"; {barrados['amostra_anterior']} verde(s) já sorteada(s) para a amostra de lote anterior esperam conferência"
                    if barrados["amostra_anterior"] else "") + ".</p>"
                 f"<form method='post' action='/triagem/lote' onsubmit=\"return confirm('Aprovar {n_aprovar} linha(s) verde(s) em "
                 f"lote? Isso não pode ser desfeito por esta tela.')\">"
                 f"{oculto}<input type='hidden' name='confirmar' value='1'>"
                 + "".join(f"<input type='hidden' name='{k}' value='{html.escape(v)}'>" for k, v in filtros.items())
                 + f"<p class='dica'>O lote fica registrado em nome de <b>{html.escape(revisor())}</b> (nome em Acesso e escritório), "
                   "com data e hora.</p>"
                 f"<button class='principal' {'disabled' if not n_aprovar else ''}>Aprovar {n_aprovar} verde(s) em lote</button>"
                 + ajuda("Grava a aprovação das linhas verdes que seriam aprovadas agora, em nome de quem está cadastrado como revisor. "
                         "Nada sai do computador. Pede uma confirmação antes. O botão fica apagado quando não há verde para aprovar.")
                 + "</form>")
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
            h.append("<div class='vazio'>Nada com esses filtros. Tire algum filtro ou use <a href='/atualizar'>Atualizar</a> "
                     "para buscar andamentos novos.</div>")
        else:
            h.append("<p><label>Buscar nesta página <input type='search' id='busca-lista' size='30' "
                     "placeholder='parte do número, cliente ou palavra'></label>"
                     + ajuda("Esconde, aqui na tela, as linhas que não contêm o que você digitou. Serve só para achar rápido; "
                             "não muda nada nos dados nem na aprovação em lote (para isso use os filtros acima).")
                     + " <span class='dica' id='conta-lista'></span></p>")
            h.append("<table class='lista' id='lista'><tr><th>Nível" + ajuda("Cor de risco da linha, calculada por regras fixas "
                     "(não pela IA). Veja \"O que significam as cores e os avisos?\" no alto da página.")
                     + "</th><th>Data</th><th>Processo</th><th>Cliente</th>"
                     "<th>O que aconteceu</th><th>Por quê" + ajuda("Os motivos pelos quais a linha não é verde. Sem motivo nenhum, "
                     "a linha é verde e pode entrar na aprovação em lote.") + "</th></tr>")
            for i in fatia:
                ev = i["ev"]
                extra = ""
                if ev["id"] in na_amostra or ev.get("amostra_lote"):
                    extra = (" <span class='nivel amostra' title='Linha verde que ficou de fora do lote de propósito, '"
                             "para você conferir à mão.'>amostra</span>")
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
                     "<script>(function(){var tab=document.getElementById('lista'),i=-1;"
                     "function vis(){return [].slice.call(tab.querySelectorAll('tr[data-href]')).filter(function(r){return !r.hidden})}"
                     "function f(n){var l=vis();if(!l.length)return;i=Math.max(0,Math.min(l.length-1,n));"
                     "tab.querySelectorAll('tr.sel').forEach(function(r){r.classList.remove('sel')});"
                     "l[i].classList.add('sel');l[i].scrollIntoView({block:'nearest'})}"
                     "document.addEventListener('keydown',function(e){if(e.ctrlKey||e.metaKey||e.altKey)return;"
                     "if(/^(INPUT|TEXTAREA|SELECT)$/.test((e.target||{}).tagName||''))return;var k=e.key.toLowerCase();"
                     "if(k==='j')f(i+1);else if(k==='k')f(i-1);else if(e.key==='Enter'&&i>=0){var l=vis();if(l[i])location.href=l[i].dataset.href}});"
                     "var b=document.getElementById('busca-lista'),c=document.getElementById('conta-lista');"
                     "if(b)b.addEventListener('input',function(){var q=b.value.trim().toLowerCase(),n=0,t=0;"
                     "tab.querySelectorAll('tr[data-href]').forEach(function(r){t++;var ok=!q||r.textContent.toLowerCase().indexOf(q)>=0;"
                     "r.hidden=!ok;if(ok)n++;r.classList.remove('sel')});i=-1;c.textContent=q?('mostrando '+n+' de '+t):''})})();</script>")
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
