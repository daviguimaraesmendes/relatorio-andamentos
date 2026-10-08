"""Início (/inicio) e busca (/busca): a primeira tela do painel e a procura por clientes, processos e andamentos.

    GET /inicio       saudação do dia, "o que precisa de você agora" e o cartão RADAR IMEDIATO (para revisar,
                      novos na semana, aprovados), mais os cartões "Demandam ação agora", "Última coleta" e
                      "Próximas ações" e os atalhos das tarefas mais comuns. Sem relatório criado (ou com o
                      relatório ainda vazio) mostra os primeiros passos.
    GET /busca?q=     procura no relatório ativo por nome de cliente ou parte, número de processo (com ou sem
                      pontuação) e texto dos andamentos e resumos já gravados.

Só lê dados que já estão no computador (carteira, eventos, fila, acesso): não fala com tribunal, não chama IA
e não mostra segredo (do cofre só se pergunta se a senha e o código estão cadastrados, nunca o valor).

Os números do cartão vêm das mesmas fontes das outras telas:
  - para revisar    eventos com status `rascunho` (o mesmo número da tela Revisar);
  - novos (7 dias)  eventos cujo `detectado_em` caiu nos últimos 7 dias;
  - aprovados       eventos com status `aprovado` (aguardando entrar na planilha).
O risco de cada rascunho é o de `triagem.classificar_lista`; a última coleta, a de `fila.Fila` (e, sem fila, a
data do arquivo de estado do coletor ou do evento mais recente).

Registro: `inicio.registrar(app, TOKEN, cabecalho, token_ok)`. Como o painel, sem relatório, manda tudo para
/novo, esta tela se antecipa a esse desvio só para /inicio e /busca; por isso `inicio` fica ANTES de `base`
na lista de telas de revisao.py (a ordem dos before_request é a do registro).
"""
import datetime
import html
import re
import unicodedata
from urllib.parse import quote

from flask import request

import comum
from painel.base import ajuda

DIAS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")
STATUS_LEGIVEL = {"rascunho": "para revisar", "aprovado": "aprovado", "relatado": "já relatado",
                  "descartado": "descartado", "coletado": "ainda sem resumo", "extraido": "ainda sem resumo"}
ROTULO_NIVEL = {"vermelho": "olhar com atenção", "amarelo": "revisão normal", "verde": "tranquilo"}
DIAS_RECENTES = 7
MAX_ACAO = 6            # linhas em "Demandam ação agora"
MAX_CLIENTES, MAX_PROCESSOS, MAX_ANDAMENTOS = 10, 20, 20
MAX_CONSULTA = 100      # caracteres da consulta de busca

ESTILO = """<style>
.ini{--i-linha:var(--linha,#e2e7eb);--i-cartao:var(--cartao,#fff);--i-tinta:var(--tinta,#0e1620);--i-suave:var(--suave,#536773);
  --i-teal:var(--teal,#4fa598);--i-teal2:var(--teal-2,#3d8a7e)}
.ini *{box-sizing:border-box}
.ini-hero{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:24px;align-items:center;margin:8px 0 24px;
  padding:32px;border-radius:20px;border:1px solid var(--i-linha);
  background:linear-gradient(135deg,var(--hero-de,#e6f0fb),var(--hero-ate,#eef4fb))}
.ini-rotulo{font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--i-suave)}
.ini-hero h1{font-size:34px;line-height:1.15;font-weight:700;margin:8px 0 10px;color:var(--i-tinta);border:0;padding:0}
.ini-sub{font-size:16px;margin:0 0 8px;color:var(--i-tinta)}
.ini-nota{font-size:14px;font-style:italic;color:var(--i-suave);margin:0 0 14px}
.ini-pilula{display:inline-block;padding:5px 14px;border-radius:999px;font-size:13px;font-weight:600;
  border:1px solid var(--verde-borda,#b5e6cb);color:var(--verde,#15803d);background:transparent}
.ini-radar{background:var(--i-cartao);border:1px solid var(--i-linha);border-radius:16px;padding:18px 20px}
.ini-radar .ini-rotulo{margin-bottom:12px}
.ini-blocos{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.ini-bloco{border-radius:12px;padding:12px 10px;border:1px solid;text-align:center}
.ini-bloco b{display:block;font-size:30px;line-height:1.1;font-weight:700}
.ini-bloco .rot{display:block;margin-top:4px;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase}
.ini-bloco.ambar{background:var(--ambar-fundo,#fff8e1);border-color:var(--ambar-borda,#f1dfa0);color:var(--ambar,#b45309)}
.ini-bloco.azul{background:var(--azul-fundo,#eaf4fe);border-color:var(--azul-borda,#b9d8f5);color:var(--azul,#1d4f91)}
.ini-bloco.verde{background:var(--verde-fundo,#e8f8f0);border-color:var(--verde-borda,#b5e6cb);color:var(--verde,#15803d)}
.ini-grade{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;margin:0 0 24px}
.ini-cartao{background:var(--i-cartao);border:1px solid var(--i-linha);border-radius:14px;padding:20px 22px;
  box-shadow:0 1px 2px rgba(15,34,54,.04);min-width:0}
.ini-cartao.largo{grid-column:1 / -1}
.ini-topo{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;
  padding-bottom:12px;margin-bottom:8px;border-bottom:1px solid var(--i-linha)}
.ini-topo>div:first-child{flex:1 1 240px;min-width:0}
.ini-cartao.alto{grid-row:span 2}
.ini-topo h2{font-size:18px;font-weight:600;margin:0;border:0;padding:0;color:var(--i-tinta)}
.ini-topo p{margin:2px 0 0;font-size:14px;color:var(--i-suave)}
.ini-botao{display:inline-block;padding:8px 18px;border-radius:999px;border:1px solid var(--i-linha);background:transparent;
  color:var(--i-tinta);font-size:14px;font-weight:600;text-decoration:none;cursor:pointer;white-space:nowrap}
.ini-botao:hover{border-color:var(--i-teal);color:var(--i-teal2)}
.ini-botao.principal{background:var(--i-teal);border-color:var(--i-teal);color:#fff}
.ini-botao.principal:hover{background:var(--i-teal2);border-color:var(--i-teal2);color:#fff}
.ini-lista{list-style:none;margin:0;padding:0}
.ini-lista li{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
  padding:11px 0;border-bottom:1px solid var(--i-linha)}
.ini-lista li>span:first-child{flex:1 1 220px;min-width:0}
.ini-lista li:last-child{border-bottom:0}
.ini-lista .ini-tit{font-weight:600;color:var(--i-tinta);text-decoration:none;overflow-wrap:anywhere}
.ini-lista a.ini-tit:hover{color:var(--i-teal2)}
.ini-lista .ini-det{display:block;font-size:13px;color:var(--i-suave);font-weight:400}
.ini-vazio{grid-column:1 / -1;margin:14px 0 4px;color:var(--i-suave);font-size:15px}
.ini-nivel{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid;white-space:nowrap}
.ini-nivel.vermelho{background:rgba(185,28,28,.08);border-color:rgba(185,28,28,.35);color:var(--perigo,#b91c1c)}
.ini-nivel.amarelo{background:var(--ambar-fundo,#fff8e1);border-color:var(--ambar-borda,#f1dfa0);color:var(--ambar,#b45309)}
.ini-nivel.verde{background:var(--verde-fundo,#e8f8f0);border-color:var(--verde-borda,#b5e6cb);color:var(--verde,#15803d)}
.ini-urgente{border-left:4px solid var(--perigo,#b91c1c);padding-left:12px!important}
.ini-numeros{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:12px 0 4px}
.ini-numeros div{background:var(--fundo2,rgba(120,140,150,.1));border-radius:10px;padding:10px 12px;font-size:13px;color:var(--i-suave)}
.ini-numeros b{display:block;font-size:22px;color:var(--i-tinta)}
.ini-atalhos{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 24px}
.ini-atalhos .ini-botao{padding:14px 28px;font-size:16px}
.ini-passos{list-style:none;counter-reset:passo;margin:0;padding:0}
.ini-passos li{counter-increment:passo;display:flex;gap:14px;align-items:flex-start;padding:14px 0;border-bottom:1px solid var(--i-linha)}
.ini-passos li:last-child{border-bottom:0}
.ini-passos li::before{content:counter(passo);flex:none;width:30px;height:30px;border-radius:50%;background:var(--i-teal);color:#fff;
  font-weight:700;display:flex;align-items:center;justify-content:center}
.ini-passos li.feito::before{content:"\\2713";background:var(--verde,#15803d)}
.ini-passos .ini-corpo{flex:1;min-width:0}
.ini-passos .ini-tit{font-weight:600;color:var(--i-tinta)}
.ini-passos p{margin:2px 0 8px;font-size:14px;color:var(--i-suave)}
.ini-busca-form{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 20px}
.ini-busca-form input[type=search]{flex:1;min-width:200px;padding:10px 16px;border-radius:999px;border:1px solid var(--i-linha);
  font:inherit;background:var(--i-cartao);color:var(--i-tinta)}
.ini mark{background:var(--ambar-fundo,#fff8e1);color:inherit;border-radius:3px;padding:0 2px;box-shadow:0 0 0 1px var(--ambar-borda,#f1dfa0)}
.ini-trecho{font-size:14px;color:var(--i-suave);margin:4px 0 0;overflow-wrap:anywhere}
@media(max-width:860px){.ini-cartao.alto{grid-row:auto}.ini-hero{grid-template-columns:1fr;padding:22px}.ini-hero h1{font-size:28px}
  .ini-grade{grid-template-columns:1fr}.ini-cartao.largo{grid-column:auto}}
@media(max-width:420px){.ini-blocos{grid-template-columns:1fr}.ini-atalhos .ini-botao{width:100%;text-align:center}}
</style>"""


# ================================================================ utilidades

def _e(texto):
    return html.escape(str(texto if texto is not None else ""))


def _agora():
    """A hora do computador (os testes trocam esta função)."""
    return datetime.datetime.now()


def _plural(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def _tentar(funcao, padrao):
    """Uma fonte de dados com defeito (arquivo ilegível, módulo ausente) nunca derruba a tela."""
    try:
        return funcao()
    except Exception:
        return padrao


def rotulo_do_dia(agora):
    """"BOA NOITE · QUINTA-FEIRA, 08 DE OUTUBRO" (em português, sem depender do idioma do sistema)."""
    saudacao = "BOM DIA" if 5 <= agora.hour < 12 else "BOA TARDE" if 12 <= agora.hour < 18 else "BOA NOITE"
    return f"{saudacao} · {DIAS[agora.weekday()].upper()}, {agora.day:02d} DE {MESES[agora.month - 1].upper()}"


def _data_hora(texto):
    try:
        return datetime.datetime.fromisoformat(str(texto)[:19])
    except (ValueError, TypeError):
        return None


def _quando(momento, agora):
    """"08/10/2026 às 19:30 (há 2 dias)"."""
    dias = (agora.date() - momento.date()).days
    rel = "hoje" if dias <= 0 else "ontem" if dias == 1 else f"há {dias} dias"
    return f"{momento:%d/%m/%Y} às {momento:%H:%M} ({rel})"


def _primeiro_nome():
    nome = (_tentar(comum.config, {}).get("revisor") or "").strip()
    return nome.split()[0] if nome else ""


# ================================================================ o que o relatório tem hoje

def levantar(agora=None):
    """Tudo o que a tela Início mostra, em dados (sem HTML). Sem relatório devolve {"relatorio": False}."""
    agora = agora or _agora()
    if not comum.PROJETO or not comum.projetos():
        return {"relatorio": False, "acesso_pronto": _acesso_pronto()}
    import ficha as fch
    lista = _tentar(comum.eventos, [])
    fichas = _tentar(fch.carregar, [])
    por_status = {}
    for e in lista:
        por_status[e.get("status")] = por_status.get(e.get("status"), 0) + 1
    limite = agora - datetime.timedelta(days=DIAS_RECENTES)
    novos = sum(1 for e in lista if (_data_hora(e.get("detectado_em")) or datetime.datetime.min) >= limite)
    clientes = {(fch.obter(f, "cliente") or "").strip() for f in fichas} - {""}
    d = {"relatorio": True, "nome": comum.projeto().get("nome", comum.PROJETO), "acesso_pronto": _acesso_pronto(),
         "processos": len(fichas), "clientes": len(clientes), "eventos": len(lista),
         "rascunhos": por_status.get("rascunho", 0), "aprovados": por_status.get("aprovado", 0),
         "relatados": por_status.get("relatado", 0),
         "sem_resumo": por_status.get("coletado", 0) + por_status.get("extraido", 0), "novos": novos}
    d["acoes"] = _tentar(lambda: _processos_em_aberto(lista, fichas), [])
    d["atencao"] = _tentar(_texto_de_atencao, "")
    d["coleta"] = _coleta(lista, agora)
    d["em_andamento"] = _tentar(_tarefa_em_andamento, "")
    return d


def _acesso_pronto():
    import acesso
    return _tentar(lambda: all(acesso.situacao().values()), False)


def _texto_de_atencao():
    import atencao
    registro = atencao.atual()
    return atencao.texto_da_faixa(registro) if registro else ""


def _tarefa_em_andamento():
    """Descrição da coleta ou tarefa rodando agora, ou ''."""
    from painel import base
    if base._tarefa_rodando():
        return base.TAREFA.get("descricao", "Tarefa em andamento")
    if base.coleta_em_andamento_em():
        return "Coleta do Assistente"
    return ""


def _processos_em_aberto(lista, fichas):
    """Processos com rascunhos para revisar, os de maior risco primeiro: [{numero, cliente, qtd, nivel, motivo}]."""
    import ficha as fch
    import triagem
    itens = triagem.classificar_lista(lista, fichas)
    por_processo = {}
    for i in triagem.ordenar_por_risco(itens):
        numero = i["ev"].get("numero") or ""
        atual = por_processo.get(numero)
        if atual is None:
            por_processo[numero] = {"numero": numero, "cliente": triagem.cliente_de(i), "qtd": 1, "nivel": i["nivel"],
                                    "motivo": (i["motivos"] or [""])[0]}
        else:
            atual["qtd"] += 1
    ordem = {"vermelho": 0, "amarelo": 1, "verde": 2}
    return sorted(por_processo.values(), key=lambda p: (ordem.get(p["nivel"], 3), -p["qtd"], p["numero"]))


def _coleta(lista, agora):
    """{"quando": datetime|None, "origem", "total", "coletados", "pendentes", "falhas": [...], "captcha": n}."""
    saida = {"quando": None, "origem": "", "total": 0, "coletados": 0, "pendentes": 0, "falhas": [], "captcha": 0}

    def da_fila():
        import fila
        f = fila.Fila()
        itens = f.itens()
        if not itens:
            return
        saida["total"] = len(itens)
        saida["coletados"] = sum(i["estado"] == "coletado" for i in itens)
        saida["pendentes"] = sum(i["estado"] in ("pendente", "coletando") for i in itens)
        saida["falhas"] = f.conferir_manualmente()
        saida["captcha"] = sum(1 for x in saida["falhas"] if x.get("codigo") == "captcha")
        quando = max((_data_hora(i.get("coletado_em")) for i in itens if i.get("coletado_em")), default=None)
        if quando:
            saida["quando"], saida["origem"] = quando, "fila"
    _tentar(da_fila, None)
    if saida["quando"] is None:
        quando = max((_data_hora(e.get("detectado_em")) for e in lista if e.get("detectado_em")), default=None)
        arq = comum.ESTADO_FILE
        if arq and arq.exists():
            m = datetime.datetime.fromtimestamp(arq.stat().st_mtime)
            quando = max(quando, m) if quando else m
        if quando:
            saida["quando"], saida["origem"] = quando, "estado"
    return saida


def proximas_acoes(d):
    """Os passos sugeridos, o mais importante primeiro: [(título, explicação, link, botão, ajuda)]."""
    a = []
    if not d["acesso_pronto"]:
        a.append(("Configurar o acesso ao jus.br", "Falta a senha do certificado e/ou o código do autenticador.",
                  "/acesso", "Configurar", "Guarda a senha do certificado e o segredo do autenticador no cofre do seu "
                  "computador (Chaveiro/Gerenciador de Credenciais). Nada disso sai do computador nem aparece em tela."))
    if d["processos"] == 0:
        a.append(("Cadastrar clientes e processos", "O relatório ainda não tem processos para acompanhar.", "/cadastro",
                  "Cadastrar", "Abre a tela onde você digita ou importa a lista de clientes e de números de processo. "
                  "Nada é buscado nos tribunais nesta etapa."))
        return a
    sem_coleta = d["coleta"]["quando"] is None and d["eventos"] == 0
    if sem_coleta:
        a.append(("Buscar os andamentos pela primeira vez", "Nenhuma coleta foi feita neste relatório.", "/fluxo",
                  "Abrir o Assistente", "O Assistente guia a primeira coleta: lê os processos cadastrados, baixa os "
                  "andamentos no jus.br e nos TRTs e prepara os resumos para você revisar. Pode levar um tempo."))
    if d["rascunhos"]:
        import triagem
        muitos = d["rascunhos"] >= _tentar(lambda: triagem.configuracao()["sugerir_a_partir_de"], 20)
        a.append((f"Revisar {_plural(d['rascunhos'], 'resumo', 'resumos')}",
                  "Há muitos: a triagem separa por risco e aprova os tranquilos em lote." if muitos
                  else "Leia cada resumo, corrija se precisar e aprove ou descarte.",
                  "/triagem" if muitos else "/", "Revisar",
                  "Abre a lista dos resumos feitos pela IA. Nada entra no relatório sem a sua aprovação; "
                  "aprovar ou descartar grava a sua decisão e não pode ser desfeito por aqui."))
    if d["sem_resumo"]:
        a.append((f"{_plural(d['sem_resumo'], 'documento coletado', 'documentos coletados')} sem resumo",
                  "Rode a atualização para a IA resumir e gerar os rascunhos.", "/atualizar", "Atualizar",
                  "Lê o que já foi baixado e escreve os resumos para você revisar. Com IA local nada sai do "
                  "computador; com IA externa, só o que você autorizou na tela IA."))
    if d["aprovados"]:
        a.append((f"Gerar a planilha ({_plural(d['aprovados'], 'aprovado', 'aprovados')})",
                  "Os resumos aprovados ainda não entraram em relatório.", "/entregas", "Gerar",
                  "Monta os arquivos (relatório em texto, planilha e painel) só com o que você aprovou. Os arquivos "
                  "ficam na pasta de saída do relatório; nada é enviado."))
    if not sem_coleta and not d["rascunhos"] and not d["sem_resumo"] and not d["aprovados"]:
        a.append(("Atualizar os andamentos", "Tudo em dia. Busque de novo quando quiser ver o que mudou.", "/atualizar",
                  "Atualizar", "Entra no jus.br com o seu certificado, lê os andamentos novos e prepara os resumos."))
    return a[:4]


# ================================================================ a tela

def _cartao(titulo, subtitulo, corpo, ajuda_txt="", botao="", largo=False, alto=False):
    return (f"<section class='ini-cartao{' largo' if largo else ''}{' alto' if alto else ''}'><div class='ini-topo'><div>"
            f"<h2>{_e(titulo)}{ajuda(ajuda_txt) if ajuda_txt else ''}</h2>"
            f"{f'<p>{_e(subtitulo)}</p>' if subtitulo else ''}</div>{botao}</div>{corpo}</section>")


def _botao(rotulo, url, principal=False):
    return f"<a class='ini-botao{' principal' if principal else ''}' href='{_e(url)}'>{_e(rotulo)}</a>"


def _hero(d, agora):
    nome = _primeiro_nome()
    titulo = f"Olá, {_e(nome)}!" if nome else "Olá!"
    if not d["relatorio"]:
        frase, nota = "Vamos começar? Siga os passos abaixo para montar o seu primeiro relatório.", \
                      "Tudo fica guardado só neste computador."
        pilula = ""
    elif d["processos"] == 0:
        frase, nota = ("Este relatório ainda não tem processos. Cadastre-os para começar a acompanhar.",
                       "Você pode importar uma lista pronta ou digitar os números.")
        pilula = ""
    else:
        if d["atencao"]:
            frase = f"A coleta está esperando por você. {d['atencao']}"
        elif d["rascunhos"]:
            frase = (f"{_plural(d['rascunhos'], 'resumo espera', 'resumos esperam')} a sua revisão, em "
                     f"{_plural(len(d['acoes']), 'processo', 'processos')}.") if d["acoes"] else \
                f"{_plural(d['rascunhos'], 'resumo espera', 'resumos esperam')} a sua revisão."
        elif d["aprovados"]:
            frase = f"A revisão está em dia. Há {_plural(d['aprovados'], 'resumo aprovado', 'resumos aprovados')} " \
                    "esperando entrar na planilha."
        else:
            frase = "Nada espera por você agora."
        nota = "Os resumos só entram no relatório depois que você aprova."
        pilula = f"<span class='ini-pilula'>{_e(_plural(d['processos'], 'processo acompanhado', 'processos acompanhados'))}</span>"
    if d["relatorio"]:
        blocos = (
            ("ambar", d["rascunhos"], "para revisar", "Resumos feitos pela IA que esperam a sua leitura e aprovação. É o "
             "mesmo número da tela Revisar. Nada disso entra no relatório sem você."),
            ("azul", d["novos"], "novos na semana", f"Andamentos e documentos que o programa encontrou nos "
             f"últimos {DIAS_RECENTES} dias, contando desde o dia em que foram detectados."),
            ("verde", d["aprovados"], "aprovados", "Resumos que você já aprovou e que ainda vão entrar na planilha ou no "
             "relatório. Quando a planilha é gerada, eles passam para \"já relatados\"."))
        corpo_radar = "".join(f"<div class='ini-bloco {cor}'><b>{n}</b><span class='rot'>{_e(rot)}{ajuda(aj)}</span></div>"
                              for cor, n, rot, aj in blocos)
    else:
        corpo_radar = ("<p class='ini-vazio'>Quando você criar o relatório, aqui aparecem os resumos para revisar, os "
                       "andamentos novos e o que já está aprovado.</p>")
    return (f"<div class='ini-hero'><div><div class='ini-rotulo'>{_e(rotulo_do_dia(agora))}</div><h1>{titulo}</h1>"
            f"<p class='ini-sub'>{_e(frase)}</p><p class='ini-nota'>{_e(nota)}</p>{pilula}</div>"
            f"<div class='ini-radar'><div class='ini-rotulo'>RADAR IMEDIATO{ajuda('Um resumo do relatório ativo: o que espera por você, o que chegou de novo e o que já está aprovado. Os números são calculados com os dados que já estão no seu computador.')}</div>"
            f"<div class='ini-blocos'>{corpo_radar}</div></div></div>")


def _primeiros_passos(d):
    relatorio = d["relatorio"]
    passos = [
        ("Configurar o acesso", "Cadastre a senha do certificado digital e o código do autenticador, e o seu nome para as "
         "aprovações.", "/acesso", "Configurar acesso", d["acesso_pronto"],
         "Guarda os dados de entrada no jus.br no cofre do seu computador. Eles nunca aparecem em tela, arquivo ou log "
         "e não saem daqui."),
        ("Criar o relatório", "Cada relatório é independente: tem clientes, processos e andamentos próprios (por exemplo, "
         "um por grupo econômico).", "/novo", "Criar relatório", relatorio,
         "Cria uma pasta no seu computador para os dados deste relatório. Nada é enviado a lugar nenhum."),
        ("Cadastrar clientes e processos", "Digite os números dos processos ou importe uma lista (planilha, texto).",
         "/cadastro", "Cadastrar", bool(relatorio and d.get("processos")),
         "Os números são conferidos (dígito verificador) e o tribunal é deduzido do próprio número. Nenhum tribunal "
         "é consultado nesta etapa."),
        ("Rodar o Assistente", "Ele busca os andamentos, prepara os resumos e leva você à revisão. Também importa "
         "um relatório pronto.", "/fluxo", "Abrir o Assistente", False,
         "Guia a primeira coleta no jus.br e nos TRTs com o seu certificado. Pode levar um tempo e, às vezes, pede "
         "que você resolva um captcha na janela que abrir.")]
    itens = "".join(
        f"<li class='{'feito' if feito else ''}'><div class='ini-corpo'><div class='ini-tit'>{_e(tit)}{ajuda(aj)}</div>"
        f"<p>{_e(desc)}</p>{_botao(rot, url, principal=not feito)}</div></li>"
        for tit, desc, url, rot, feito, aj in passos)
    return _cartao("Primeiros passos", "Quatro passos e o painel está pronto para uso.", f"<ol class='ini-passos'>{itens}</ol>",
                   "Siga na ordem. Os passos já feitos aparecem com um visto; você pode voltar a eles quando quiser.",
                   largo=True)


def _cartao_acao(d):
    if d["atencao"]:
        pedido = (f"<ul class='ini-lista'><li class='ini-urgente'><span class='ini-tit'>{_e(d['atencao'])}"
                  f"<span class='ini-det'>A coleta fica parada até você resolver na janela do navegador.</span></span>"
                  f"{_botao('Ver andamento', '/fluxo/progresso')}</li></ul>")
    else:
        pedido = ""
    linhas = "".join(
        f"<li><span><a class='ini-tit' href='/processo?numero={quote(p['numero'])}'>{_e(p['numero'])}</a>"
        f"<span class='ini-det'>{_e(p['cliente'] or 'sem cliente')} · "
        f"{_e(_plural(p['qtd'], 'resumo para revisar', 'resumos para revisar'))}"
        f"{(' · ' + _e(p['motivo'])) if p['motivo'] else ''}</span></span>"
        f"<span class='ini-nivel {_e(p['nivel'])}'>{_e(ROTULO_NIVEL.get(p['nivel'], p['nivel']))}</span></li>"
        for p in d["acoes"][:MAX_ACAO])
    if linhas:
        resto = len(d["acoes"]) - MAX_ACAO
        corpo = pedido + f"<ul class='ini-lista'>{linhas}</ul>" + (
            f"<p class='ini-vazio'>E mais {_plural(resto, 'processo', 'processos')}. Veja todos na revisão.</p>" if resto > 0 else "")
    elif pedido:
        corpo = pedido
    else:
        corpo = ("<p class='ini-vazio'>Nada pede a sua atenção agora. Quando houver resumos para revisar, um captcha "
                 "ou um login esperando por você, eles aparecem aqui.</p>")
    return _cartao("Demandam ação agora", "Processos com resumos aguardando a sua revisão, do maior para o menor risco.",
                   corpo, "Lista os processos com resumos em rascunho. O nível vem de regras simples: vermelho para "
                   "prazo, audiência, valor, efeito desfavorável ou mudança de resultado; amarelo para alertas; "
                   "verde para o resto. Clique no número para abrir o processo.",
                   _botao("Ver todos", "/triagem"), alto=True)


def _cartao_coleta(d, agora):
    c = d["coleta"]
    if c["quando"] is None and not d["em_andamento"]:
        corpo = ("<p class='ini-vazio'>Nenhuma coleta foi feita neste relatório ainda. Use o Assistente ou a tela Atualizar "
                 "para buscar os andamentos.</p>")
    else:
        partes = []
        if d["em_andamento"]:
            partes.append(f"<p><b>Em andamento agora:</b> {_e(d['em_andamento'])}. <a href='/fluxo/progresso'>Acompanhar</a></p>")
        if c["quando"]:
            partes.append(f"<p>Última coleta: <b>{_e(_quando(c['quando'], agora))}</b></p>")
        if c["total"]:
            falhas = len(c["falhas"])
            partes.append(f"<div class='ini-numeros'><div><b>{c['coletados']}</b>de {c['total']} processos coletados</div>"
                          f"<div><b>{c['pendentes']}</b>na fila</div>"
                          f"<div><b>{falhas}</b>para conferir à mão</div>"
                          f"<div><b>{c['captcha']}</b>com captcha</div></div>")
            if falhas:
                partes.append("<p class='dica'>Processos que o programa não conseguiu coletar sozinho (captcha, segredo de "
                              "justiça, não localizado ou erro) estão em <a href='/entregas'>Entregas</a>, na lista "
                              "\"conferir manualmente\".</p>")
            else:
                partes.append("<p class='dica'>Nenhuma falha nem captcha pendente.</p>")
        else:
            partes.append("<p class='dica'>A data vem do último registro gravado pelo coletor neste relatório.</p>")
        corpo = "".join(partes)
    return _cartao("Última coleta", "Quando o programa buscou andamentos pela última vez.", corpo,
                   "Mostra a data da última coleta e quantos processos foram coletados, estão na fila ou precisam de "
                   "conferência manual. Só lê o que já foi gravado; não busca nada.",
                   _botao("Atualizar", "/atualizar"))


def _cartao_proximas(d):
    acoes = proximas_acoes(d)
    if not acoes:
        corpo = "<p class='ini-vazio'>Nada a fazer por enquanto.</p>"
    else:
        corpo = "<ul class='ini-lista'>" + "".join(
            f"<li><span class='ini-tit'>{_e(tit)}{ajuda(aj)}<span class='ini-det'>{_e(desc)}</span></span>"
            f"{_botao(rot, url, principal=(i == 0))}</li>" for i, (tit, desc, url, rot, aj) in enumerate(acoes)) + "</ul>"
    return _cartao("Próximas ações", "O que o Assistente sugere fazer, na ordem.", corpo,
                   "O programa olha o que já existe no relatório (acesso, processos, coleta, rascunhos, aprovados) e "
                   "sugere o próximo passo. É só uma sugestão; nada é feito sem você clicar.")


def _atalhos():
    return ("<div class='ini-atalhos'>"
            f"{_botao('Atualizar andamentos', '/atualizar', True)}"
            f"{_botao('Revisar', '/')}{_botao('Gerar planilha', '/entregas')}"
            f"{ajuda('Atualizar busca andamentos novos no jus.br com o seu certificado. Revisar abre os resumos para você aprovar. Gerar planilha monta os arquivos só com o que você aprovou.')}"
            "</div>")


def pagina_inicio(cabecalho, agora=None):
    agora = agora or _agora()
    d = levantar(agora)
    h = [cabecalho("inicio", "Início"), ESTILO, "<div class='ini'>", _hero(d, agora)]
    if not d["relatorio"]:
        h.append(_primeiros_passos(d))
    else:
        h.append(_atalhos())
        if d["processos"] == 0:
            h.append(f"<div class='ini-grade'>{_primeiros_passos(d)}</div>")
        h.append("<div class='ini-grade'>" + _cartao_acao(d) + _cartao_coleta(d, agora) + _cartao_proximas(d) + "</div>")
    h.append("</div>")
    return "".join(h)


# ================================================================ busca

def _sem_acento(texto):
    """Minúsculas e sem acento, caractere a caractere (o tamanho se mantém na maioria dos casos)."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def _normalizado_com_mapa(texto):
    """(texto normalizado, mapa) em que mapa[i] é a posição, no original, do caractere i do normalizado."""
    saida, mapa = [], []
    for pos, c in enumerate(texto):
        n = _sem_acento(c)
        n = " " if c.isspace() else n
        saida.append(n)
        mapa.extend([pos] * len(n))
    return "".join(saida), mapa


def termos_da_consulta(consulta):
    """Palavras da consulta, normalizadas (até 6). Vazio se a consulta for curta demais para procurar."""
    consulta = (consulta or "").strip()[:MAX_CONSULTA]
    termos = [t for t in _sem_acento(consulta).split() if t][:6]
    return termos if sum(len(t) for t in termos) >= 2 else []


def _casa(texto_norm, termos):
    return all(t in texto_norm for t in termos)


def _so_digitos(texto):
    return re.sub(r"\D", "", texto or "")


def _destaque(texto, termos, largura=170):
    """Trecho do `texto` em volta do primeiro termo achado, escapado, com os termos em <mark>."""
    texto = " ".join(str(texto or "").split())
    norm, mapa = _normalizado_com_mapa(texto)
    achados = []
    for t in termos:
        for m in re.finditer(re.escape(t), norm):
            achados.append((mapa[m.start()], mapa[m.end() - 1] + 1))
    if not achados:
        return _e(texto[:largura] + ("…" if len(texto) > largura else ""))
    achados.sort()
    ini = max(0, achados[0][0] - largura // 3)
    fim = min(len(texto), ini + largura)
    saida, pos = [], ini
    for a, b in achados:
        if a < pos or a >= fim:
            continue
        b = min(b, fim)
        saida.append(_e(texto[pos:a]) + f"<mark>{_e(texto[a:b])}</mark>")
        pos = b
    saida.append(_e(texto[pos:fim]))
    return ("…" if ini > 0 else "") + "".join(saida) + ("…" if fim < len(texto) else "")


def buscar(consulta):
    """Procura no relatório ativo. Devolve {"termos", "clientes", "processos", "andamentos", "total_*"} com listas já
    limitadas. Só lê arquivos locais e só olha campos de identificação e o texto dos andamentos; nunca segredos."""
    import ficha as fch
    termos = termos_da_consulta(consulta)
    saida = {"termos": termos, "clientes": [], "processos": [], "andamentos": [],
             "total_clientes": 0, "total_processos": 0, "total_andamentos": 0}
    if not termos:
        return saida
    digitos = _so_digitos(consulta) if re.fullmatch(r"[\d.\-/\s]+", (consulta or "").strip()) else ""
    digitos = digitos if len(digitos) >= 4 else ""
    fichas = _tentar(lambda: fch.carregar(todas=True), [])
    por_cliente = {}
    processos = []
    for f in fichas:
        cliente = (fch.obter(f, "cliente") or "").strip()
        numeros = [n for n in fch.todos_os_numeros(f) if n]
        campos = [fch.obter(f, c) or "" for c in ("cliente", "apelido", "autores", "reus", "parte_contraria",
                                                   "outras_partes", "objeto")]
        texto_norm = _sem_acento(" ".join(str(c) for c in campos + numeros))
        achou_numero = bool(digitos) and any(digitos in _so_digitos(n) for n in numeros)
        if cliente:
            por_cliente.setdefault(cliente, 0)
            por_cliente[cliente] += 1
        if achou_numero or _casa(texto_norm, termos):
            processos.append({"numero": f.get("numero") or (numeros[0] if numeros else ""), "cliente": cliente,
                              "partes": " x ".join(x for x in (str(fch.obter(f, "autores") or ""),
                                                               str(fch.obter(f, "reus") or "")) if x),
                              "apelido": fch.obter(f, "apelido") or "", "tribunal": f.get("tribunal") or ""})
    # clientes: os do cadastro (mesmo sem processo) e os que aparecem nas fichas
    cadastro = _tentar(lambda: comum.load_json(comum.CLIENTES_FILE, {}), {})
    lista_cad = cadastro.get("clientes", []) if isinstance(cadastro, dict) else cadastro
    for c in lista_cad if isinstance(lista_cad, list) else []:
        nome = (c.get("nome") if isinstance(c, dict) else str(c or "")).strip()
        if nome:
            por_cliente.setdefault(nome, 0)
    clientes = [{"nome": n, "processos": q} for n, q in sorted(por_cliente.items(), key=lambda x: x[0].lower())
                if _casa(_sem_acento(n), termos)]
    # andamentos e resumos já gravados
    achados = []
    for e in _tentar(comum.eventos, []):
        texto = " ".join(str(e.get(c) or "") for c in ("titulo", "frase", "conteudo", "trecho_origem", "prazo", "audiencia"))
        if _casa(_sem_acento(texto), termos):
            achados.append((e, texto))
    achados.sort(key=lambda x: (_data_hora(x[0].get("detectado_em")) or datetime.datetime.min, x[0].get("id") or ""),
                 reverse=True)
    saida.update(total_clientes=len(clientes), total_processos=len(processos), total_andamentos=len(achados),
                 clientes=clientes[:MAX_CLIENTES], processos=processos[:MAX_PROCESSOS],
                 andamentos=[{"ev": e, "texto": t} for e, t in achados[:MAX_ANDAMENTOS]])
    return saida


def _link_processo(numero):
    return f"/processo?numero={quote(numero or '')}"


def _mais(total, mostrados):
    return (f"<p class='ini-vazio'>Mostrando {mostrados} de {total}. Refine a busca para ver o resto.</p>"
            if total > mostrados else "")


def pagina_busca(cabecalho, consulta):
    consulta = (consulta or "").strip()[:MAX_CONSULTA]
    r = buscar(consulta)
    h = [cabecalho("busca", "Buscar"), ESTILO, "<div class='ini'>",
         f"<h1>Buscar clientes, processos e documentos{ajuda('Procura no relatório ativo, só nos dados que já estão no seu computador: nomes de clientes e partes, números de processo (com ou sem pontos e traço) e o texto dos andamentos e resumos já gravados. Nada é consultado na internet.')}</h1>",
         "<form class='ini-busca-form' method='get' action='/busca'>"
         f"<input type='search' name='q' value='{_e(consulta)}' maxlength='{MAX_CONSULTA}' "
         "placeholder='Nome do cliente, número do processo ou uma palavra do andamento' aria-label='Buscar' autofocus>"
         "<button class='ini-botao principal' type='submit'>Buscar</button></form>"]
    if not consulta:
        h.append(_cartao("Como buscar", "", "<p class='ini-vazio'>Digite o nome de um cliente ou de uma parte, um número de "
                         "processo (com ou sem pontuação) ou uma palavra que apareça nos andamentos.</p>"))
    elif not r["termos"]:
        h.append(_cartao("Consulta curta demais", "", "<p class='ini-vazio'>Digite pelo menos 2 letras ou números para "
                         "buscar.</p>"))
    elif not (r["total_clientes"] or r["total_processos"] or r["total_andamentos"]):
        h.append(_cartao("Nenhum resultado", "", f"<p class='ini-vazio'>Não encontrei nada para <b>{_e(consulta)}</b> neste "
                         "relatório. Confira a grafia, tente uma parte do nome ou do número, ou troque de relatório "
                         "pelas abas do topo.</p>"))
    else:
        if r["total_clientes"]:
            linhas = "".join(
                f"<li><span class='ini-tit'>{_destaque(c['nome'], r['termos'])}<span class='ini-det'>"
                f"{_e(_plural(c['processos'], 'processo', 'processos'))}</span></span>"
                f"{_botao('Ver revisão', '/triagem?cliente=' + quote(c['nome']))}</li>" for c in r["clientes"])
            h.append(_cartao("Clientes", f"{r['total_clientes']} encontrado(s)", f"<ul class='ini-lista'>{linhas}</ul>"
                             + _mais(r["total_clientes"], len(r["clientes"]))))
        if r["total_processos"]:
            linhas = "".join(
                f"<li><span><a class='ini-tit' href='{_e(_link_processo(p['numero']))}'>{_destaque(p['numero'], r['termos'])}</a>"
                f"<span class='ini-det'>{_e(p['cliente'] or 'sem cliente')}"
                f"{(' · ' + _e(p['tribunal'])) if p['tribunal'] else ''}"
                f"{(' · ' + _destaque(p['partes'], r['termos'])) if p['partes'] else ''}</span></span></li>"
                for p in r["processos"])
            h.append(_cartao("Processos", f"{r['total_processos']} encontrado(s)", f"<ul class='ini-lista'>{linhas}</ul>"
                             + _mais(r["total_processos"], len(r["processos"]))))
        if r["total_andamentos"]:
            linhas = []
            for a in r["andamentos"]:
                e = a["ev"]
                quando = e.get("data") or (e.get("detectado_em") or "")[:10]
                linhas.append(
                    f"<li><span style='min-width:0'><a class='ini-tit' href='{_e(_link_processo(e.get('numero')))}'>"
                    f"{_e(e.get('numero') or 'sem número')}</a>"
                    f"<span class='ini-det'>{_e(e.get('cliente') or 'sem cliente')} · {_e(quando)} · "
                    f"{_e(STATUS_LEGIVEL.get(e.get('status'), e.get('status') or ''))}</span>"
                    f"<span class='ini-trecho'>{_destaque(a['texto'], r['termos'])}</span></span></li>")
            h.append(_cartao("Andamentos e resumos", f"{r['total_andamentos']} encontrado(s), do mais recente ao mais antigo",
                             f"<ul class='ini-lista'>{''.join(linhas)}</ul>" + _mais(r["total_andamentos"], len(r["andamentos"]))))
    h.append("</div>")
    return "".join(h)


# ================================================================ registro

def registrar(app, TOKEN, cabecalho, token_ok):
    @app.before_request
    def inicio_sem_relatorio():
        """Sem relatório criado o painel manda tudo para /novo; /inicio e /busca ficam de fora para mostrar os
        primeiros passos. Com relatório, não faz nada (o `base` escolhe o relatório pelo cookie, depois)."""
        if request.path in ("/inicio", "/busca") and not comum.projetos():
            return pagina_inicio(cabecalho) if request.path == "/inicio" else pagina_busca(cabecalho, request.args.get("q"))
        return None

    @app.get("/inicio")
    def inicio_tela():
        return pagina_inicio(cabecalho)

    @app.get("/busca")
    def busca_tela():
        return pagina_busca(cabecalho, request.args.get("q"))
