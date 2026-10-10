"""Visão por processo (/processo?numero=...): tudo o que mudou num processo numa só página, para revisar
sem pular de lista em lista.

    GET  /processo?numero=N     linha do tempo dos eventos (data, texto, nível de risco), cada um com o
                                print e o trecho de origem lado a lado e os botões aprovar / salvar
                                correção / descartar; mais o bloco "campos derivados" (antes -> depois)
    POST /processo/evento       a mesma ação de /evento (painel.revisao_eventos.aplicar_acao), voltando
                                para o processo, já no próximo rascunho
    POST /processo/campo        aprovar | corrigir | recusar um campo derivado

Campos derivados (situação, momento atual, fase, resultado, probabilidade e os valores):
    - o que já está na ficha com origem `sugerido` ou `derivado` aparece como proposta (antes = vazio);
    - o que o módulo de sugestão de julgamento (julgamento.py, interface do CONTRATOS §10:
      `sugerir(ficha, eventos) -> {campo: {"valor", "regra", "evidencia": {"documento", "trecho"},
      "ressalvas": [..]}}`) propõe de diferente do que a ficha tem (antes = valor atual);
    - campo com origem `humano` nunca é proposta. Se julgamento.py não existir ainda, só aparece o
      primeiro tipo. Falha da sugestão vira aviso na página, nunca erro.
    - Aprovar grava com origem `humano` (ficha.definir com forcar=True); corrigir grava o que a
      pessoa digitou, também como `humano`; recusar apaga a proposta pendente da ficha e guarda o
      valor em ficha["sugestoes_recusadas"] para não perguntar de novo. Monetário só muda por pessoa.

Atalhos de teclado (sem biblioteca): J/K trocam de linha, A aprova, D descarta (pede confirmação),
E vai para a frase da linha. Funcionam só fora de campos de texto.
"""
import hashlib
import html
from urllib.parse import quote

from flask import abort, redirect, request

import ficha as fch
import triagem
from comum import eventos, salvar_eventos
from painel import revisao_eventos
from painel.base import _msg, ajuda
from painel.revisao_eventos import CONFIRMA_DESCARTE, DICAS, DICAS_ACOES
from painel.revisao_lote import ESTILO_TRIAGEM, data_do_evento, legenda_dos_niveis, selo

CAMPOS_DERIVADOS = ("situacao", "momento_atual", "fase", "resultado", "probabilidade", "valor_arbitrado",
                    "valor_acordo", "valor_estimado", "valor_economizado")
ORIGENS_PENDENTES = ("sugerido", "derivado")
STATUS_LEGIVEL = {"rascunho": "para revisar", "aprovado": "aprovado", "relatado": "já relatado",
                  "descartado": "descartado", "coletado": "ainda sem resumo", "extraido": "ainda sem resumo",
                  "sem_arquivo": "documento não baixado"}
ESTILO_PROCESSO = """<style>
.cartao-ev{border:1px solid var(--linha);border-radius:6px;padding:12px;margin:12px 0}
.cartao-ev.foco{outline:3px solid var(--acento)}
.cartao-ev.fechado{background:var(--fundo2)}
.lado{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:8px 0}
.lado>div{border:1px solid var(--linha);border-radius:4px;padding:8px;min-height:60px;overflow:auto}
.lado img{max-width:100%;max-height:340px}
@media(max-width:700px){.lado{grid-template-columns:1fr}}
table.derivados{width:100%;border-collapse:collapse;font-size:14px}
table.derivados th,table.derivados td{border-bottom:1px solid var(--linha);padding:6px 8px;text-align:left;vertical-align:top}
.antes{color:var(--suave)}.depois{font-weight:700}
</style>"""


# ------------------------------------------------------------------ campos derivados (lógica, sem Flask)

def _sugerir_padrao():
    """julgamento.sugerir, se o módulo (WS-17) já existir; senão None."""
    try:
        import julgamento
    except ImportError:
        return None
    return getattr(julgamento, "sugerir", None)


def eventos_do_processo(lista, ficha):
    """Eventos do processo (principal e vinculados), do mais antigo ao mais recente."""
    import relatorio
    numeros = set(fch.todos_os_numeros(ficha))
    proprios = [e for e in lista if e.get("numero") in numeros]

    def chave(e):
        try:
            return (relatorio.ordem(e)[0].timestamp(), relatorio.ordem(e)[1], e.get("id") or "")
        except Exception:
            return (0, "", e.get("id") or "")
    return sorted(proprios, key=chave)


def formatar_valor(campo, valor):
    """Valor de campo para a tela (dinheiro e data no padrão brasileiro)."""
    if valor in (None, ""):
        return "(vazio)"
    tipo = fch.CAMPOS[campo][2]
    if tipo == "dinheiro":
        return fch.dinheiro_br(valor) or str(valor)
    if tipo == "data":
        return fch.data_br(valor) or str(valor)
    if campo in fch.PERCENTUAIS:
        try:
            return f"{float(valor) * 100:.0f}%".replace(".", ",")
        except (TypeError, ValueError):
            return str(valor)
    return str(valor)


def _normalizado(campo, valor):
    """O valor como a ficha o guardaria (para comparar antes e depois); None se não for válido."""
    _, _, tipo, vocab = fch.CAMPOS[campo]
    return fch._normalizar_valor(tipo, vocab, valor)


def _evidencia_texto(sug):
    ev = sug.get("evidencia") or {}
    partes = [sug.get("regra") or "", ev.get("documento") or "", ev.get("trecho") or ""]
    return " | ".join(p for p in partes if p)[:400]


def propostas_de_campos(ficha, lista_eventos, sugerir=None):
    """(propostas, avisos): [{"campo", "rotulo", "antes", "depois", "origem_atual", "regra", "evidencia",
    "ressalvas"}] dos campos derivados que esperam decisão de uma pessoa. `sugerir` (opcional) substitui o
    julgamento.sugerir real (testes); só eventos aprovados ou já relatados alimentam a sugestão."""
    propostas, avisos = {}, []
    recusadas = ficha.get("sugestoes_recusadas") or {}
    for campo in CAMPOS_DERIVADOS:
        if fch.origem(ficha, campo) in ORIGENS_PENDENTES:
            depois = fch.obter(ficha, campo)
            registro = ficha["campos"][campo]
            propostas[campo] = {"campo": campo, "antes": None, "depois": depois, "origem_atual": registro["origem"],
                                "regra": "", "evidencia": registro.get("evidencia") or "", "ressalvas": []}
    sugerir = sugerir or _sugerir_padrao()
    if sugerir is not None:
        base = [e for e in lista_eventos if e.get("status") in ("aprovado", "relatado")]
        try:
            sugestoes = sugerir(ficha, base) or {}
        except Exception as e:                       # sugestão com defeito não pode derrubar a revisão
            sugestoes = {}
            avisos.append(f"Não foi possível calcular as sugestões de julgamento ({type(e).__name__}).")
        for campo, sug in sugestoes.items():
            if campo not in CAMPOS_DERIVADOS and campo not in fch.CAMPOS_DE_JULGAMENTO:
                continue
            if campo in propostas or fch.origem(ficha, campo) == "humano":
                continue                             # humano nunca é proposta
            depois = _normalizado(campo, sug.get("valor"))
            if depois in (None, ""):
                continue
            atual = fch.obter(ficha, campo)
            if atual not in (None, "") and _normalizado(campo, atual) == depois:
                continue                             # nada muda
            propostas[campo] = {"campo": campo, "antes": atual, "depois": depois, "origem_atual": fch.origem(ficha, campo),
                                "regra": sug.get("regra") or "", "evidencia": _evidencia_texto(sug),
                                "ressalvas": list(sug.get("ressalvas") or [])}
    saida = []
    for campo in CAMPOS_DERIVADOS + tuple(c for c in propostas if c not in CAMPOS_DERIVADOS):
        p = propostas.get(campo)
        if p and str(recusadas.get(campo)) != str(p["depois"]):
            p["rotulo"] = fch.CAMPOS[campo][0]
            saida.append(p)
    return saida, avisos


def decidir_campo(ficha, proposta, acao, valor_corrigido=None):
    """Aplica a decisão da pessoa a UM campo derivado, na ficha (quem chama salva). Devolve a mensagem.
    Levanta ValueError (mensagem em português) se o valor não for aceito."""
    campo, rotulo = proposta["campo"], proposta["rotulo"]
    if acao == "recusar":
        if fch.origem(ficha, campo) in ORIGENS_PENDENTES:
            fch.limpar(ficha, campo)
        ficha.setdefault("sugestoes_recusadas", {})[campo] = str(proposta["depois"])
        return f"{rotulo}: sugestão recusada."
    if acao == "aprovar":
        valor = proposta["depois"]
    elif acao == "corrigir":
        valor = (valor_corrigido or "").strip()
        if not valor:
            raise ValueError(f"{rotulo}: informe o valor corrigido.")
    else:
        raise ValueError("Ação desconhecida.")
    antes = fch.obter(ficha, campo)
    if not fch.definir(ficha, campo, valor, "humano", evidencia=proposta.get("evidencia") or None, forcar=True):
        if _normalizado(campo, valor) not in (None, "") and fch.origem(ficha, campo) == "humano" \
                and _normalizado(campo, valor) == fch.obter(ficha, campo):
            return f"{rotulo}: já estava aprovado."
        raise ValueError(f"{rotulo}: valor não aceito ({valor}). Confira o formato ou o vocabulário.")
    ficha.get("sugestoes_recusadas", {}).pop(campo, None)
    return f"{rotulo}: {formatar_valor(campo, antes)} → {formatar_valor(campo, fch.obter(ficha, campo))} (aprovado por você)."


# ------------------------------------------------------------------ tela

def _ancora(ev):
    return "ev-" + hashlib.sha1((ev.get("id") or "").encode("utf-8")).hexdigest()[:8]


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def _ficha_de(numero):
        fichas = fch.carregar(todas=True)
        return fichas, triagem.indice_de_fichas(fichas).get(numero)

    @app.get("/processo")
    def processo_tela():
        numero = (request.args.get("numero") or "").strip()
        lista = eventos()
        fichas, f = _ficha_de(numero)
        if f is None and not any(e.get("numero") == numero for e in lista):
            abort(404)
        propostas, avisos = ([], [])
        if f is not None:
            propostas, avisos = propostas_de_campos(f, eventos_do_processo(lista, f))
            evs = eventos_do_processo(lista, f)
        else:
            evs = [e for e in lista if e.get("numero") == numero]
        principal = f["numero"] if f else numero
        h = [cabecalho("revisar"), ESTILO_TRIAGEM, ESTILO_PROCESSO, f"<h1>Processo {html.escape(principal)}</h1>", _msg()]
        if f:
            vinc = ", ".join(f"{html.escape(v['numero'])} ({html.escape(v['tipo'])})" for v in f.get("vinculados", []))
            momento = fch.obter(f, "momento_atual")
            polo = {"ativo": "autor", "passivo": "réu"}.get(fch.obter(f, "polo_cliente") or "", "polo não informado")
            h.append(f"<p class='meta'>{html.escape(fch.obter(f, 'cliente') or 'sem cliente')} ({polo}) · "
                     f"{html.escape(f.get('tribunal') or 'tribunal não informado')}"
                     + (f" · momento atual: <b>{html.escape(momento)}</b>" if momento else "")
                     + (f"<br>Vinculados: {vinc}" if vinc else "") + "</p>")
        h.append("<p><a href='/triagem'>← Triagem</a> · <a href='/'>Revisar linha a linha</a></p>")
        h.append("<div class='caixa'><b>O que fazer agora</b><p>Decida primeiro os <b>campos derivados</b> (se houver), depois "
                 "percorra a <b>linha do tempo</b>: para cada andamento em revisão, compare o resumo com o print e o trecho do documento "
                 "e clique em <b>Aprovar</b>. Nada vale para os relatórios antes da sua decisão.</p>"
                 "<p class='dica'>Atalhos (fora dos campos de texto): J e K trocam de andamento, A aprova, D descarta, E edita a frase.</p></div>"
                 + legenda_dos_niveis())

        # ---- campos derivados
        for a in avisos:
            h.append(f"<div class='alerta'>{html.escape(a)}</div>")
        if propostas:
            h.append("<h2>Campos derivados: antes → depois"
                     + ajuda("Campos da ficha do processo (fase, resultado, probabilidade, valores...) que o programa propõe preencher "
                             "ou mudar a partir dos andamentos aprovados. É só uma proposta: nada vale até você aprovar, corrigir "
                             "ou recusar. Valores em dinheiro só mudam por decisão sua.")
                     + "</h2><p class='dica'>Nada aqui vale até você aprovar. "
                     "Aprovar grava como lançado por você.</p><table class='derivados'><tr><th>Campo</th><th>Antes</th>"
                     "<th>Depois (proposta)</th><th>Por quê" + ajuda("A regra ou a evidência (trecho de documento) em que a proposta se "
                     "apoia, e ressalvas quando houver. Confira antes de aprovar.") + "</th><th>Decisão</th></tr>")
            for p in propostas:
                pc = html.escape(p["campo"])
                h.append(
                    f"<tr><td>{html.escape(p['rotulo'])}</td><td class='antes'>{html.escape(formatar_valor(p['campo'], p['antes']))}</td>"
                    f"<td class='depois'>{html.escape(formatar_valor(p['campo'], p['depois']))}"
                    f"<div class='dica'>origem: {html.escape(p['origem_atual'] or 'regra')}</div></td>"
                    f"<td>{html.escape(p['regra'])}"
                    + (f"<div class='dica'>{html.escape(p['evidencia'])}</div>" if p["evidencia"] else "")
                    + "".join(f"<div class='alerta'>{html.escape(r)}</div>" for r in p["ressalvas"]) + "</td>"
                    f"<td><form method='post' action='/processo/campo'>{oculto}"
                    f"<input type='hidden' name='numero' value='{html.escape(principal)}'><input type='hidden' name='campo' value='{pc}'>"
                    "<button name='acao' value='aprovar' class='principal'>Aprovar</button>"
                    + ajuda("Aceita o valor proposto e o grava na ficha do processo como lançado por você. Passa a valer nos relatórios e "
                            "o programa não o muda mais sozinho.")
                    + "<button name='acao' value='recusar'>Recusar</button>"
                    + ajuda("Rejeita a proposta: nada muda na ficha e o programa não volta a propor o mesmo valor. Se surgir "
                            "um valor diferente, ele aparece de novo.")
                    + "<br><input type='text' name='valor' size='16' placeholder='valor corrigido'> "
                    "<button name='acao' value='corrigir'>Corrigir</button>"
                    + ajuda("Grava na ficha o valor que você digitou no campo ao lado, como lançado por você. Datas como 31/12/2026, "
                            "dinheiro como R$ 1.500,00; nos campos de lista, uma das opções que o programa conhece. Se o formato "
                            "não for aceito, nada muda e a tela diz o porquê.")
                    + "</form></td></tr>")
            h.append("</table>")

        # ---- linha do tempo
        h.append(f"<h2>Linha do tempo ({len(evs)})"
                 + ajuda("Todos os andamentos deste processo (e dos vinculados a ele) que o programa já coletou, do mais recente ao "
                         "mais antigo. Os que esperam revisão têm botões; os já decididos aparecem apagados, só para consulta.")
                 + "</h2>")
        if not evs:
            h.append("<div class='vazio'>Nenhum andamento coletado deste processo ainda. Use <a href='/atualizar'>Atualizar</a>.</div>")
        indice = triagem.indice_de_fichas(fichas)
        for ev in reversed(evs):                      # mais recente primeiro
            n = triagem.classificar_detalhado(ev, indice.get(ev.get("numero")), exigir_ficha=True)
            aberto = ev.get("status") == "rascunho"
            esc = lambda c: html.escape(ev.get(c) or "")
            h.append(f"<div class='cartao-ev{'' if aberto else ' fechado'}' id='{_ancora(ev)}' data-rascunho='{int(aberto)}'>"
                     f"<div class='meta'>{selo(n['nivel'])} {html.escape(data_do_evento(ev))} · {esc('numero')}"
                     f"{(' · ' + esc('grau')) if ev.get('grau') else ''} · {esc('titulo')} · "
                     f"<b>{html.escape(STATUS_LEGIVEL.get(ev.get('status'), ev.get('status') or ''))}</b>"
                     + (f" · aprovado por {esc('aprovado_por')}" if ev.get("aprovado_por") else "")
                     + (" · em lote" if ev.get("lote") else "")
                     + (" <span class='nivel amostra'>amostra de lote</span>" if ev.get("amostra_lote") and aberto else "")
                     + "</div>")
            if n["motivos"]:
                h.append("<ul class='motivos'>" + "".join(f"<li>{html.escape(m)}</li>" for m in n["motivos"]) + "</ul>")
            origem = ""
            if ev.get("trecho_origem"):
                origem += f"<blockquote>Trecho do documento: “{esc('trecho_origem')}”</blockquote>"
            if ev.get("arquivo"):
                origem += f"<a href='/documento?id={quote(ev['id'])}' target='_blank'>abrir documento</a>"
            tela = (f"<img src='/print?id={quote(ev['id'])}' alt='Print do andamento nos autos'>" if ev.get("print")
                    else "<span class='dica'>Sem print.</span>")
            h.append("<div class='lado'><div><b>Print</b>"
                     + ajuda("Foto da tela do tribunal no momento da coleta, guardada só neste computador. Serve para você conferir "
                             "o andamento com os próprios olhos.")
                     + f"<br>{tela}</div>"
                     "<div><b>Trecho de origem</b>"
                     + ajuda("O pedaço do documento de onde o resumo foi tirado, e o link para abrir o documento inteiro. "
                             "Se o trecho não estiver mesmo no documento, desconfie do resumo.")
                     + f"<br>{origem or '<span class=dica>Sem trecho de origem.</span>'}</div></div>")
            if aberto:
                h.append(f"<form class='acoes' method='post' action='/processo/evento'>{oculto}"
                         f"<input type='hidden' name='id' value='{esc('id')}'><input type='hidden' name='numero' value='{html.escape(principal)}'>"
                         f"<label>O que aconteceu{ajuda(DICAS['frase'])}<textarea name='frase' rows='2' required "
                         "oninvalid=\"this.setCustomValidity('Escreva a frase do relatório antes de aprovar, ou use Salvar correção.')\" "
                         f"oninput=\"this.setCustomValidity('')\">{esc('frase')}</textarea></label>"
                         f"<label>Conteúdo (opcional){ajuda(DICAS['conteudo'])}<textarea name='conteudo' rows='2'>{esc('conteudo')}</textarea></label>"
                         f"<label>Prazo{ajuda(DICAS['prazo'])}<textarea name='prazo' rows='1'>{esc('prazo')}</textarea></label>"
                         f"<label>Audiência{ajuda(DICAS['audiencia'])}<textarea name='audiencia' rows='1'>{esc('audiencia')}</textarea></label>"
                         "<button name='acao' value='aprovar' class='principal'>Aprovar (A)</button>"
                         + ajuda(DICAS_ACOES["aprovar"].replace("e some desta lista", "e passa a aparecer aqui só para consulta"))
                         + "<button name='acao' value='salvar' formnovalidate>Salvar correção</button>"
                         + ajuda(DICAS_ACOES["salvar"])
                         + f"<button name='acao' value='descartar' formnovalidate onclick=\"return confirm('{CONFIRMA_DESCARTE}')\">Descartar (D)</button>"
                         + ajuda(DICAS_ACOES["descartar"]) + "</form>")
            else:
                h.append(f"<p>{esc('frase')} {esc('conteudo')}</p>")
            h.append("</div>")
        h.append("<p class='dica'>Atalhos: J/K trocam de linha, A aprova, D descarta, E edita a frase.</p>"
                 "<script>(function(){var c=[].slice.call(document.querySelectorAll('.cartao-ev')),i=-1;"
                 "function f(n){if(!c.length)return;i=Math.max(0,Math.min(c.length-1,n));c.forEach(function(x){x.classList.remove('foco')});"
                 "c[i].classList.add('foco');c[i].scrollIntoView({block:'nearest'})}"
                 "var h=(location.hash||'').slice(1),ini=c.findIndex(function(x){return x.id===h});"
                 "if(ini<0)ini=c.findIndex(function(x){return x.dataset.rascunho==='1'});if(ini>=0)f(ini);"
                 "document.addEventListener('keydown',function(e){if(e.ctrlKey||e.metaKey||e.altKey)return;"
                 "var t=e.target||{};if(/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName||'')){if(e.key==='Escape')t.blur();return}"
                 "var k=e.key.toLowerCase();if(k==='j')f(i+1);else if(k==='k')f(i-1);else if(i>=0){"
                 "var fm=c[i].querySelector('form.acoes');if(!fm)return;"
                 "if(k==='a'){fm.querySelector('button[value=aprovar]').click()}"
                 "else if(k==='d'){fm.querySelector('button[value=descartar]').click()}"
                 "else if(k==='e'){e.preventDefault();fm.querySelector('textarea[name=frase]').focus()}}})})();</script>")
        return "".join(h)

    @app.post("/processo/evento")
    def processo_evento():
        token_ok()
        lista = eventos()
        ev = revisao_eventos.aplicar_acao(lista, request.form)
        salvar_eventos(lista)
        numero = request.form.get("numero") or ev.get("numero") or ""
        _, f = _ficha_de(numero)
        evs = eventos_do_processo(lista, f) if f else [e for e in lista if e.get("numero") == numero]
        evs = list(reversed(evs))                     # a ordem da tela
        pos = next((k for k, e in enumerate(evs) if e["id"] == ev["id"]), -1)
        seguintes = evs[pos + 1:] + evs[:pos] if pos >= 0 else evs
        proximo = next((e for e in seguintes if e.get("status") == "rascunho"), None)
        msg = {"aprovar": "Linha aprovada.", "descartar": "Linha descartada."}.get(request.form["acao"], "Correção salva.")
        destino = f"/processo?numero={quote(numero)}&msg={quote(msg)}"
        return redirect(destino + (f"#{_ancora(proximo)}" if proximo else ""))

    @app.post("/processo/campo")
    def processo_campo():
        token_ok()
        numero = (request.form.get("numero") or "").strip()
        campo, acao = request.form.get("campo", ""), request.form.get("acao", "")
        fichas, f = _ficha_de(numero)
        if f is None or campo not in fch.CAMPOS:
            abort(404)
        propostas, _ = propostas_de_campos(f, eventos_do_processo(eventos(), f))
        proposta = next((p for p in propostas if p["campo"] == campo), None)
        if proposta is None:
            msg = "Essa proposta não existe mais (já foi decidida ou mudou)."
        else:
            try:
                msg = decidir_campo(f, proposta, acao, request.form.get("valor"))
                fch.salvar(fichas)
            except ValueError as e:
                msg = str(e)
        return redirect(f"/processo?numero={quote(f['numero'])}&msg={quote(msg)}")
