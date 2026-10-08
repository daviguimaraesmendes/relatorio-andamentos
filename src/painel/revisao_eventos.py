"""Revisar andamentos (página inicial, /): lista os rascunhos por cliente e grava a aprovação,
o descarte ou a edição (/evento).

Esta continua sendo a revisão padrão, evento a evento. Para muitos rascunhos há a triagem por nível
(/triagem, painel/revisao_lote.py) e a visão por processo (/processo, painel/processo.py); a página
só sugere a triagem quando passa de `triagem.sugerir_a_partir_de` rascunhos (padrão 20). A regra de
gravar aprovar/salvar/descartar está em `aplicar_acao`, que a visão por processo reaproveita."""
import datetime
import getpass
import hashlib
import html
from collections import defaultdict
from urllib.parse import quote

from flask import abort, redirect, request

import comum
import relatorio
import triagem
from comum import config, eventos, salvar_eventos
from painel.base import _msg, ajuda
from painel.revisao_lote import ESTILO_TRIAGEM, legenda_dos_niveis, selo


def aplicar_acao(lista, form):
    """Aplica aprovar | salvar | descartar ao rascunho `form["id"]` da `lista` de eventos (modifica a lista;
    quem chama grava com salvar_eventos). 404 se não houver rascunho com o id; 400 se aprovar sem frase."""
    ev = next((e for e in lista if e["id"] == form["id"]), None)
    if ev is None or ev["status"] != "rascunho":
        abort(404)
    for campo in ("frase", "conteudo", "prazo", "audiencia"):
        ev[campo] = form.get(campo, "").strip() or None
    acao = form["acao"]
    if acao == "aprovar":
        if not ev.get("frase"):
            abort(400, "Para aprovar, preencha o campo \"O que aconteceu\". Volte e escreva a frase, ou use \"Salvar sem aprovar\".")
        ev.update(status="aprovado", aprovado_por=config().get("revisor") or getpass.getuser(),
                  aprovado_em=datetime.datetime.now().isoformat(timespec="seconds"))
    elif acao == "descartar":
        ev.update(status="descartado", motivo="Descartado na revisão.")
    return ev


def ancora(ev):
    """Âncora do cartão do andamento (para a página voltar exatamente onde você estava)."""
    return "ev-" + hashlib.sha1((ev.get("id") or "").encode("utf-8")).hexdigest()[:8]


def _na_ordem_da_pagina(lista):
    """Os rascunhos na ordem em que a tela os mostra (cliente, processo, data)."""
    return sorted((e for e in lista if e["status"] == "rascunho"),
                  key=lambda e: (e.get("cliente") or "", e["numero"], relatorio.ordem(e)))


AVISOS_DA_ACAO = {"aprovar": "Andamento aprovado: já vale para a planilha e os relatórios.",
                  "salvar": "Correção salva. O andamento continua em revisão.",
                  "descartar": "Andamento descartado: não entra no relatório."}

DICAS = {
    "frase": "A frase que vai para o relatório do cliente, escrita pelo programa. Corrija o que estiver errado. "
             "É obrigatória para aprovar.",
    "conteudo": "Detalhe opcional que se junta à frase no relatório (por exemplo, \"determinando o pagamento\"). "
                "Pode ficar em branco.",
    "prazo": "Se houver prazo, escreva aqui. Sai no relatório em destaque (\"Prazo: ...\"). Deixe em branco se não houver.",
    "audiencia": "Se houver audiência, escreva data e hora. Sai no relatório em destaque (\"Audiência: ...\"). "
                 "Deixe em branco se não houver.",
}

DICAS_ACOES = {
    "aprovar": "Grava as correções que você fez e marca o andamento como aprovado, em seu nome e com data e hora. "
               "Ele passa a valer para a planilha e os relatórios e some desta lista. Nada sai do computador. "
               "Depois de aprovado, não dá para editar por esta tela.",
    "salvar": "Grava só o texto que você corrigiu e deixa o andamento em revisão, para você terminar depois.",
    "descartar": "Marca o andamento como sem interesse: ele não entra na planilha nem nos relatórios e não volta para a "
                 "revisão. O registro continua guardado no computador, mas não há botão para desfazer.",
}
CONFIRMA_DESCARTE = "Descartar este andamento? Ele não entrará no relatório e não há como desfazer por esta tela."

SCRIPT_REVISAO = """<script>
(function(){
var cartoes=[].slice.call(document.querySelectorAll('.ev')),i=-1;
var busca=document.getElementById('busca-rev'),nivel=document.getElementById('nivel-rev'),conta=document.getElementById('conta-rev');
function visiveis(){return cartoes.filter(function(c){return !c.hidden})}
function foco(n){var v=visiveis();if(!v.length)return;i=Math.max(0,Math.min(v.length-1,n));
cartoes.forEach(function(c){c.classList.remove('foco')});v[i].classList.add('foco');v[i].scrollIntoView({block:'nearest'})}
function filtrar(){var q=(busca.value||'').trim().toLowerCase(),nv=nivel.value,n=0;
cartoes.forEach(function(c){var ok=(!q||c.dataset.busca.indexOf(q)>=0)&&(!nv||(nv==='atencao'?c.dataset.nivel!=='verde':c.dataset.nivel===nv));
c.hidden=!ok;if(ok)n++;c.classList.remove('foco')});
[].slice.call(document.querySelectorAll('section.grupo')).forEach(function(g){g.hidden=!g.querySelector('.ev:not([hidden])')});
i=-1;conta.textContent=(q||nv)?('mostrando '+n+' de '+cartoes.length):''}
if(busca){busca.addEventListener('input',filtrar);nivel.addEventListener('change',filtrar)}
var h=(location.hash||'').slice(1),ini=cartoes.findIndex(function(c){return c.getAttribute('id')===h});if(ini>=0)foco(ini);
document.addEventListener('keydown',function(e){if(e.ctrlKey||e.metaKey||e.altKey)return;
var t=e.target||{};if(/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName||'')){if(e.key==='Escape')t.blur();return}
var k=e.key.toLowerCase();if(k==='j')foco(i+1);else if(k==='k')foco(i-1);else{var v=visiveis();if(i<0||!v[i])return;
var f=v[i];if(k==='a'){f.querySelector('button[value=aprovar]').click()}
else if(k==='d'){f.querySelector('button[value=descartar]').click()}
else if(k==='e'){e.preventDefault();f.querySelector('textarea[name=frase]').focus()}}})})();
</script>"""

ESTILO_REVISAO = """<style>
.ev.foco{outline:3px solid var(--teal,var(--acento))}
.barra-filtro{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin:12px 0}
.barra-filtro label{font-size:13px;color:var(--suave);display:flex;flex-direction:column}
.barra-filtro input[type=search]{min-width:280px}
.ev label{display:block;margin:6px 0;font-size:14px}
.ev[hidden],section.grupo[hidden]{display:none}
</style>"""


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.get("/")
    def inicio():
        lista = eventos()
        rascunhos = [e for e in lista if e["status"] == "rascunho"]
        aprovados = sum(e["status"] == "aprovado" for e in lista)
        por_cliente = defaultdict(list)
        for ev in rascunhos:
            por_cliente[ev.get("cliente") or ""].append(ev)
        niveis = {}
        try:        # a cor de risco é um auxílio: se a classificação falhar, a revisão funciona sem ela
            import ficha as fch
            niveis = {i["ev"]["id"]: i for i in triagem.classificar_lista(lista, fch.carregar(todas=True))}
        except Exception:
            niveis = {}
        h = [cabecalho("revisar"), ESTILO_REVISAO, ESTILO_TRIAGEM, "<h1>Revisar andamentos</h1>", _msg(),
             "<div class='caixa'><b>O que fazer agora</b>"
             "<p>Leia cada andamento, confira com o documento (o link \"abrir documento\" ou \"ver print\" está logo no alto do cartão) "
             "e, estando certo, clique em <b>Aprovar</b>. Se a frase estiver errada, corrija o texto e aprove, ou use "
             "<b>Salvar sem aprovar</b> para voltar depois. O que não interessa ao cliente, <b>Descartar</b>.</p>"
             "<p class='dica'>Nada vai para a planilha nem para os relatórios sem a sua aprovação: o programa só prepara o rascunho. "
             "Atalhos de teclado (fora dos campos de texto): J e K trocam de andamento, A aprova, D descarta, E edita a frase.</p></div>",
             f"<div class='cartoes'><div class='cartao'><b>{len(rascunhos)}</b>para revisar"
             + ajuda("Andamentos que o programa preparou (movimentações e resumos de documentos) e que ainda esperam a sua decisão.")
             + "</div>"
             f"<div class='cartao'><b>{aprovados}</b>aprovados, aguardando a planilha"
             + ajuda("Já aprovados por você. Entram na planilha e nos relatórios na próxima vez que você gerar as entregas.")
             + "</div>"
             f"<div class='cartao'><b>{len(comum.carteira())}</b>processos acompanhados"
             + ajuda("Quantos processos ativos estão na carteira deste relatório. Para cadastrar ou tirar processos, "
                     "use \"Clientes e processos\".") + "</div></div>"]
        sugestao = ("<p class='dica'>Muitos rascunhos? A <a href='/triagem'>triagem</a> separa por risco e "
                    "aprova os tranquilos em lote.</p>"
                    if len(rascunhos) >= triagem.configuracao()["sugerir_a_partir_de"] else "")
        h.append(sugestao)
        if rascunhos:
            h.append(legenda_dos_niveis())
            h.append("<div class='barra-filtro'><label>Buscar<input type='search' id='busca-rev' size='32' "
                     "placeholder='cliente, nº do processo ou palavra da frase'></label>"
                     "<label>Mostrar<select id='nivel-rev'><option value=''>todos</option>"
                     "<option value='atencao'>só vermelhos e amarelos</option><option value='vermelho'>só vermelhos</option>"
                     "<option value='amarelo'>só amarelos</option><option value='verde'>só verdes</option></select></label>"
                     "<span class='dica' id='conta-rev'></span>"
                     + ajuda("Esconde, aqui na tela, os andamentos que não combinam com a busca ou com a cor escolhida. "
                             "Não muda nada nos dados; recarregar a página mostra tudo de novo.") + "</div>")
        for cliente, evs in sorted(por_cliente.items()):
            h.append(f"<section class='grupo'><h2>{html.escape(cliente or 'sem cliente')}</h2>")
            if not cliente:
                h.append("<p class='dica'>Estes processos não têm cliente cadastrado: o resumo pode estar sem o ponto de vista certo. "
                         "Escolha o cliente em <a href='/cadastro'>Clientes e processos</a>.</p>")
            for ev in sorted(evs, key=lambda e: (e["numero"], relatorio.ordem(e))):
                esc = lambda c: html.escape(ev.get(c) or "")
                tri = niveis.get(ev["id"])
                nivel = tri["nivel"] if tri else ""
                busca = html.escape(" ".join(str(ev.get(c) or "") for c in ("cliente", "numero", "titulo", "frase", "conteudo")).lower(), quote=True)
                h.append(f"<form class='ev' id='{ancora(ev)}' data-nivel='{nivel}' data-busca='{busca}' method='post' action='/evento'>"
                         f"{oculto}<input type='hidden' name='id' value='{esc('id')}'>"
                         f"<div class='meta'>"
                         + (selo(nivel).replace("<span ", "<span title='" + html.escape("; ".join(tri["motivos"]) or "Nenhum alerta", quote=True) + "' ", 1)
                            + " · " if tri else "")
                         + f"{esc('data')} · {esc('numero')}{(' · ' + esc('grau')) if ev.get('grau') else ''} · {esc('titulo')}"
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
                h.append(f"<label>O que aconteceu{ajuda(DICAS['frase'])}<textarea name='frase' rows='2' required "
                         "oninvalid=\"this.setCustomValidity('Escreva a frase do relatório antes de aprovar, ou use Salvar sem aprovar.')\" "
                         f"oninput=\"this.setCustomValidity('')\">{esc('frase')}</textarea></label>"
                         f"<label>Conteúdo (opcional){ajuda(DICAS['conteudo'])}<textarea name='conteudo' rows='2'>{esc('conteudo')}</textarea></label>")
                if ev.get("trecho_origem"):
                    h.append(f"<blockquote>Trecho do documento: “{esc('trecho_origem')}”"
                             + ajuda("O pedaço do documento de onde o resumo foi tirado. Serve para você conferir; não vai para o relatório. "
                                     "Se o trecho não estiver mesmo no documento, desconfie do resumo.") + "</blockquote>")
                for campo, rotulo in (("prazo", "Prazo"), ("audiencia", "Audiência")):
                    h.append(f"<label>{rotulo}{ajuda(DICAS[campo])}<textarea name='{campo}' rows='1'>{esc(campo)}</textarea></label>")
                h.append("<button name='acao' value='aprovar' class='principal'>Aprovar</button>"
                         + ajuda(DICAS_ACOES["aprovar"])
                         + "<button name='acao' value='salvar' formnovalidate>Salvar sem aprovar</button>"
                         + ajuda(DICAS_ACOES["salvar"])
                         + "<button name='acao' value='descartar' formnovalidate "
                           f"onclick=\"return confirm('{CONFIRMA_DESCARTE}')\">Descartar</button>"
                         + ajuda(DICAS_ACOES["descartar"])
                         + "</form>")
            h.append("</section>")
        if not rascunhos:
            h.append("<div class='vazio'>Nada para revisar. Use <a href='/atualizar'>Atualizar</a> para buscar andamentos novos.</div>")
        else:
            h.append(SCRIPT_REVISAO)
        return "".join(h)

    @app.post("/evento")
    def evento():
        token_ok()
        lista = eventos()
        antes = _na_ordem_da_pagina(lista)                    # a ordem da tela, para voltar ao andamento seguinte
        ev = aplicar_acao(lista, request.form)
        salvar_eventos(lista)
        destino = "/?msg=" + quote(AVISOS_DA_ACAO.get(request.form.get("acao"), AVISOS_DA_ACAO["salvar"]))
        pos = next((k for k, e in enumerate(antes) if e["id"] == ev["id"]), -1)
        restantes = [e for e in antes[pos + 1:] + antes[:max(pos, 0)] if e["status"] == "rascunho" and e["id"] != ev["id"]]
        if ev["status"] == "rascunho":
            return redirect(destino + "#" + ancora(ev))      # "Salvar sem aprovar": fica no mesmo cartão
        return redirect(destino + (("#" + ancora(restantes[0])) if restantes else ""))
