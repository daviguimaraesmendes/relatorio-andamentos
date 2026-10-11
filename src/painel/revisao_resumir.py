"""Resumir mais tarde (tela Revisar): "Resumir os que ficaram sem IA".

Quando uma rodada roda sem IA (modo rápido, resumos por IA desligados, IA não configurada ou fora do ar), o documento vai à
revisão só com a frase automática. Aqui a pessoa manda resumir esses documentos depois, sem coletar nada de novo:

    GET  /resumir-pendentes   quantos documentos, a estimativa de chamadas e onde a IA roda; botão de confirmar
    POST /resumir-pendentes   começa a resumir (em segundo plano, um trabalho por vez); a mesma página mostra o andamento

O trabalho está em fluxos.resumir_pendentes (IA externa só com consentimento, com pseudonimização; evento aprovado,
descartado ou relatado nunca é tocado). Os resumos continuam sendo rascunho: nada vale antes da aprovação.
"""
import html
import threading
from urllib.parse import quote

from flask import abort, redirect

import comum
from painel.base import _msg, ajuda

ESTADO = {"rodando": False, "slug": None, "mensagem": "", "resultado": None, "thread": None}
_BLOQUEIO = threading.Lock()
AJUDA_BOTAO = ("Manda a IA resumir os documentos que ficaram só com a frase automática (porque a rodada foi sem IA, a IA não "
               "estava configurada ou não respondeu). Antes de começar, você vê quantos são e quantas chamadas à IA isso custa. "
               "Não busca nada nos tribunais e não mexe no que você já aprovou. Os resumos voltam como rascunho, para você revisar.")


def contador(projeto=None):
    """Quantos documentos abertos estão sem resumo de IA (0 se não der para contar: a tela nunca cai por isso)."""
    try:
        import fluxos
        return fluxos.contar_sem_resumo_ia(projeto)
    except Exception:  # noqa: BLE001 - o contador é um auxílio da tela Revisar
        return 0


def bloco_revisar():
    """Caixa da tela Revisar: o contador e o botão. Vazio quando não há documento sem resumo de IA."""
    n = contador()
    if not n:
        return ""
    return ("<div class='caixa' id='sem-ia'>"
            f"<b>{n} documento(s) sem resumo de IA</b>"
            + ajuda("Documentos que estão em revisão só com a frase automática, porque foram processados sem IA (modo rápido, "
                    "resumos por IA desligados, IA não configurada ou fora do ar). Você pode revisá-los assim, à mão, ou mandar "
                    "resumir agora.")
            + "<p class='dica'>Estes documentos ficaram só com a frase automática. Você pode mandar a IA resumi-los agora, sem "
              "buscar nada de novo nos tribunais.</p>"
              "<form method='get' action='/resumir-pendentes'>"
              "<button class='principal'>Resumir os que ficaram sem IA</button>" + ajuda(AJUDA_BOTAO) + "</form></div>")


def _trabalhar(slug):
    import fluxos

    def andamento(info):
        ESTADO["mensagem"] = info.get("mensagem", "")
    try:
        ESTADO["resultado"] = fluxos.resumir_pendentes(slug, ao_progresso=andamento)
    except Exception as erro:  # noqa: BLE001 - erro inesperado vira mensagem, nunca página quebrada
        ESTADO["resultado"] = {"ok": False, "resumo": f"Não consegui resumir agora ({type(erro).__name__}). Nada foi alterado.",
                               "avisos": []}
    finally:
        ESTADO["rodando"] = False


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def pagina(*partes, atualizar=False):
        topo = "<meta http-equiv='refresh' content='4'>" if atualizar else ""
        return "".join([cabecalho("revisar"), topo, "<h1>Resumir os que ficaram sem IA</h1>", _msg(), *partes])

    @app.get("/resumir-pendentes")
    def resumir_pendentes_tela():
        if not comum.PROJETO:
            return pagina("<p class='vazio'>Esta tela precisa de um relatório aberto.</p>")
        if ESTADO["rodando"] and ESTADO["slug"] == comum.PROJETO:
            return pagina("<div class='caixa'><b>Resumindo...</b>" + ajuda("A IA está resumindo os documentos, um por vez. Você pode "
                          "deixar esta página aberta ou voltar à revisão: o trabalho continua. Mantenha o programa aberto.")
                          + f"<p>{html.escape(ESTADO['mensagem'] or 'Começando')}</p></div>"
                          "<p><a href='/'>Voltar para Revisar</a></p>", atualizar=True)
        import fluxos
        e = fluxos.estimar_resumir_pendentes(comum.PROJETO)
        h = []
        r = ESTADO["resultado"] if ESTADO["slug"] == comum.PROJETO else None
        if r:
            h.append(f"<div class='{'msg' if r.get('ok') else 'alerta'}'><b>Último resumo:</b> {html.escape(r['resumo'])}</div>")
            h.extend(f"<div class='alerta'>{html.escape(a['mensagem'])}</div>" for a in r.get("avisos", []))
        onde = ("A IA é externa (" + html.escape(str(e["provedor"])) + "): os textos saem deste computador, só para clientes com "
                "consentimento, com os nomes trocados por códigos (pseudonimização)." if e["externa"]
                else "A IA roda neste computador: nenhum texto sai dele.")
        h.append(f"<div class='caixa'><p><b>{html.escape(e['frase'])}</b>"
                 + ajuda("A conta é pelos documentos que estão em revisão só com a frase automática e têm texto legível. Cada um gera "
                         "uma chamada à IA, ou duas se a primeira resposta vier fora do formato. Documentos sem texto legível "
                         "precisam ser resumidos à mão.") + "</p>"
                 f"<p class='dica'>{onde}</p>"
                 "<p class='dica'>Isto não busca nada nos tribunais. O que você já aprovou ou descartou não é tocado, e a frase que "
                 "você tiver corrigido é mantida. Os resumos voltam como rascunho: você ainda precisa aprová-los.</p>"
                 f"<form method='post' action='/resumir-pendentes'>{oculto}"
                 f"<button class='principal' {'disabled' if not e['pode_rodar'] else ''}>Confirmar e resumir {e['pendentes']} documento(s)</button>"
                 + ajuda("Começa a resumir agora, um documento por vez, com a IA configurada para este relatório. Você pode continuar "
                         "usando o programa enquanto isso. O botão fica apagado quando não há nada que a IA possa resumir.")
                 + " <a href='/'>Agora não</a>"
                 + ajuda("Volta para a revisão sem fazer nada. Os documentos continuam como estão.") + "</form></div>")
        return pagina(*h)

    @app.post("/resumir-pendentes")
    def resumir_pendentes_iniciar():
        token_ok()
        if not comum.PROJETO:
            abort(400, "Não há relatório aberto.")
        import fluxos
        e = fluxos.estimar_resumir_pendentes(comum.PROJETO)
        if not e["pode_rodar"]:
            return redirect("/resumir-pendentes?msg=" + quote("Nada para resumir agora."))
        with _BLOQUEIO:
            if ESTADO["rodando"]:
                return redirect("/resumir-pendentes?msg=" + quote("Já há um resumo em andamento."))
            ESTADO.update(rodando=True, slug=comum.PROJETO, mensagem="Começando", resultado=None)
            t = threading.Thread(target=_trabalhar, args=(comum.PROJETO,), daemon=True)
            ESTADO["thread"] = t
            t.start()
        return redirect("/resumir-pendentes")
