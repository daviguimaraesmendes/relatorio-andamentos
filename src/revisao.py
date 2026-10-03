"""Painel local do Relatório de Andamentos: uma aba por relatório (projeto
autônomo, com clientes, processos, andamentos e planilha próprios) e, dentro
de cada uma: Atualizar, Revisar, Planilha, Clientes e processos, Configuração.

Roda só em 127.0.0.1, sem modo debug, um pedido por vez (o relatório ativo é
estado global). Cada formulário leva um token gerado na inicialização, para
que outra página aberta no navegador não consiga agir por conta própria."""
import datetime
import getpass
import html
import os
import re
import secrets
import signal
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from flask import Flask, abort, make_response, redirect, request, send_file

import cadastro
import comum
import relatorio
from comum import config, eventos, salvar_eventos

app = Flask(__name__)
TOKEN = secrets.token_urlsafe(24)
OCULTO = f"<input type='hidden' name='token' value='{TOKEN}'>"
TAREFA = {}  # tarefa em execução (uma por vez: o login usa o certificado)
WINDOWS = sys.platform.startswith("win")

ESTILO = """<style>
:root{--tinta:#1f2a2e;--suave:#5b6b70;--linha:#d9dfe1;--fundo:#ffffff;--fundo2:#f4f6f7;--acento:#1d5c63;
--alerta:#9a3412;--alerta-fundo:#fff4ed;--ok:#14532d;--ok-fundo:#eef6ee}
body{font-family:-apple-system,system-ui,sans-serif;color:var(--tinta);background:var(--fundo);margin:0}
.barra{background:var(--fundo2);border-bottom:1px solid var(--linha);padding:10px 16px 0}
.barra .marca{font-weight:700;font-size:15px;margin-bottom:8px}
.abas{display:flex;flex-wrap:wrap;gap:4px}
.abas a{padding:8px 14px;border:1px solid var(--linha);border-bottom:none;border-radius:6px 6px 0 0;
  text-decoration:none;color:var(--tinta);background:#e9eef0;font-size:14px}
.abas a.ativa{background:var(--fundo);font-weight:600;position:relative;top:1px}
.abas a.novo{background:none;border:1px dashed var(--linha);border-bottom:none;color:var(--suave)}
.sub{display:flex;flex-wrap:wrap;gap:18px;padding:12px 16px;border-bottom:1px solid var(--linha);font-size:14px}
.sub a{text-decoration:none;color:var(--acento)}.sub a.ativa{font-weight:700;color:var(--tinta)}
main{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0 12px}h2{margin-top:28px;border-bottom:1px solid var(--linha);padding-bottom:4px;font-size:18px}
.ev,.caixa{border:1px solid var(--linha);border-radius:6px;padding:12px;margin:12px 0}
.meta,.dica{color:var(--suave);font-size:13px}
.alerta{background:var(--alerta-fundo);color:var(--alerta);padding:6px 8px;border-radius:4px;font-size:14px;margin:6px 0}
.msg{background:var(--ok-fundo);color:var(--ok);padding:8px 10px;border-radius:4px;margin:12px 0;white-space:pre-line}
textarea{width:100%;box-sizing:border-box;font:inherit;padding:6px}
input[type=text],input[type=date],select{font:inherit;padding:4px}
blockquote{color:var(--suave);border-left:3px solid var(--linha);margin:6px 0;padding-left:8px;font-size:14px}
button{padding:6px 12px;margin-right:6px;cursor:pointer}
button.principal{background:var(--acento);color:#fff;border:1px solid var(--acento);border-radius:4px}
pre.log{background:#111;color:#ddd;padding:12px;border-radius:6px;font-size:12px;max-height:420px;overflow:auto;white-space:pre-wrap}
.cartoes{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.cartao{background:var(--fundo2);border-radius:6px;padding:10px}.cartao b{font-size:22px;display:block}
</style>"""

SUBABAS = [("atualizar", "/atualizar", "Atualizar"), ("revisar", "/", "Revisar"),
           ("planilha", "/planilha", "Planilha"), ("cadastro", "/cadastro", "Clientes e processos"),
           ("config", "/config", "Configuração")]


def cabecalho(ativa, titulo="Relatório de Andamentos"):
    abas = "".join(f"<a href='/p/{s}' class='{'ativa' if s == comum.PROJETO else ''}'>{html.escape(d.get('nome', s))}</a>"
                   for s, d in comum.projetos())
    sub = "".join(f"<a href='{url}' class='{'ativa' if chave == ativa else ''}'>{rotulo}</a>"
                  for chave, url, rotulo in SUBABAS) if comum.PROJETO else ""
    rodando = (f" · <a href='/atualizar'>tarefa em andamento: {html.escape(TAREFA['descricao'])}</a>"
               if _tarefa_rodando() else "")
    import acesso
    pronto = all(acesso.situacao().values())
    aviso = ("" if pronto or ativa == "acesso" else
             "<div class='alerta' style='margin:12px 16px'>Falta configurar o acesso (senha do certificado e "
             "código do autenticador). <a href='/acesso'>Configurar agora</a></div>")
    return (f"<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'><title>{html.escape(titulo)}</title>{ESTILO}<body>"
            f"<div class='barra'><div class='marca'>Relatório de Andamentos<span class='meta'>{rodando}</span>"
            f"<a href='/acesso' style='float:right;font-weight:normal;font-size:14px' "
            f"class='{'ativa' if ativa == 'acesso' else ''}'>Acesso e escritório {'✓' if pronto else '(configurar)'}</a></div>"
            f"<div class='abas'>{abas}<a href='/novo' class='novo'>+ Novo relatório</a></div></div>"
            f"<div class='sub'>{sub}</div>{aviso}<main>")


def _msg():
    return f"<div class='msg'>{html.escape(request.args['msg'])}</div>" if request.args.get("msg") else ""


def _ir(caminho, msg=""):
    from urllib.parse import quote
    return redirect(caminho + (("&" if "?" in caminho else "?") + "msg=" + quote(msg) if msg else ""))


def _token_ok():
    if request.form.get("token") != TOKEN:
        abort(403)


def _dentro(base, caminho):
    try:
        Path(caminho).resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


@app.before_request
def escolher_projeto():
    """O relatório ativo vem do cookie; sem relatório nenhum, só a tela de criar."""
    slug = request.cookies.get("projeto")
    disponiveis = [s for s, _ in comum.projetos()]
    if slug in disponiveis and slug != comum.PROJETO:
        comum.usar_projeto(slug)
    if not disponiveis and request.path not in ("/novo", "/acesso", "/tarefa", "/atualizar", "/interromper"):
        return redirect("/novo")


@app.get("/p/<slug>")
def trocar(slug):
    if slug not in [s for s, _ in comum.projetos()]:
        abort(404)
    comum.usar_projeto(slug)
    r = make_response(redirect("/"))
    r.set_cookie("projeto", slug, samesite="Strict", max_age=3600 * 24 * 365)
    return r


@app.route("/novo", methods=["GET", "POST"])
def novo():
    if request.method == "POST":
        _token_ok()
        nome = request.form.get("nome", "").strip()
        if not nome:
            return _ir("/novo", "Dê um nome ao relatório.")
        slug = comum.criar_projeto(nome)
        comum.usar_projeto(slug)
        r = make_response(_ir("/cadastro", f"Relatório criado: {nome}. Cadastre os clientes e os processos."))
        r.set_cookie("projeto", slug, samesite="Strict", max_age=3600 * 24 * 365)
        return r
    return (cabecalho("novo") + "<h1>Novo relatório</h1>" + _msg() +
            f"<form class='caixa' method='post'>{OCULTO}<p class='dica'>Cada relatório é independente: clientes, processos, "
            "andamentos e planilha próprios (ex.: um por grupo econômico ou por cliente).</p>"
            "<label>Nome <input type='text' name='nome' placeholder='Ex.: Grupo Exemplo' required></label> "
            "<button class='principal'>Criar</button></form>")


# --- Revisar ---

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
            h.append(f"<form class='ev' method='post' action='/evento'>{OCULTO}<input type='hidden' name='id' value='{esc('id')}'>"
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
    _token_ok()
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


# --- Atualizar (tarefas em segundo plano) ---

def _tarefa_rodando():
    return bool(TAREFA) and TAREFA["proc"].poll() is None


@app.get("/atualizar")
def atualizar():
    proj = comum.projeto()
    ultimo = proj.get("ultimo_relatorio", "")
    primeira = not comum.load_json(comum.ESTADO_FILE, {})
    h = [cabecalho("atualizar"), "<h1>Atualizar andamentos</h1>", _msg()]
    if TAREFA:
        rodando = _tarefa_rodando()
        log = Path(TAREFA["log"]).read_text(encoding="utf-8", errors="replace")[-12000:] if Path(TAREFA["log"]).exists() else ""
        estado = "em andamento" if rodando else f"concluída (código {TAREFA['proc'].returncode})"
        h.append(f"<div class='caixa'><b>{html.escape(TAREFA['descricao'])}</b> · relatório "
                 f"{html.escape(TAREFA['nome'])} · {estado} · início {TAREFA['inicio']}"
                 f"<pre class='log' id='log'>{html.escape(log)}</pre>")
        if rodando:
            h.append(f"<form method='post' action='/interromper'>{OCULTO}<button>Interromper</button></form>"
                     "<script>setTimeout(()=>location.reload(),3000);"
                     "const l=document.getElementById('log');l.scrollTop=l.scrollHeight;</script>")
        else:
            h.append("<script>const l=document.getElementById('log');l.scrollTop=l.scrollHeight;</script>"
                     "<a href='/'>Ir para a revisão</a>")
        h.append("</div>")
    bloqueado = "disabled" if _tarefa_rodando() else ""
    h.append(f"<form class='caixa' method='post' action='/tarefa'>{OCULTO}<input type='hidden' name='tipo' value='rodada'>"
             "<b>Buscar andamentos no jus.br</b><p class='dica'>Entra com o certificado (janela minimizada no canto), "
             "lê andamentos e documentos novos de cada processo, tira print e resume com a IA local. "
             "Ao terminar, os rascunhos aparecem em Revisar.</p>"
             + (f"<p>Primeira atualização deste relatório: considerar como novo o que veio depois de "
                f"<input type='date' name='desde' value='{html.escape(ultimo)}'> (data do último relatório enviado). "
                "Sem data, só registra o que já existe e começa a acompanhar daqui para frente.</p>" if primeira else "")
             + f"<button class='principal' {bloqueado}>Atualizar</button></form>")
    h.append(f"<form class='caixa' method='post' action='/tarefa'>{OCULTO}<input type='hidden' name='tipo' value='conferencia'>"
             "<b>Conferência</b><p class='dica'>Sem IA. Separa, por responsável, os andamentos e documentos dos últimos "
             "<input type='text' name='dias' value='7' size='3'> dias que ainda não entraram em relatório aprovado, "
             "com PDFs e prints, para revisão manual.</p>"
             f"<button {bloqueado}>Conferir</button></form>")
    return "".join(h)


@app.post("/tarefa")
def tarefa():
    _token_ok()
    if _tarefa_rodando():
        return _ir("/atualizar", "Já há uma tarefa em andamento. Aguarde ou interrompa.")
    tipo = request.form.get("tipo")
    raiz = comum.RAIZ
    py = [sys.executable, "-u"]
    if tipo == "rodada":
        args = py + [str(raiz / "src" / "rodar.py"), "--projeto", comum.PROJETO]
        if request.form.get("desde"):
            a, m, d = request.form["desde"].split("-")
            args += ["--desde", f"{d}/{m}/{a}"]
        descricao = "Atualização no jus.br"
    elif tipo == "teste_acesso":
        args, descricao = py + [str(raiz / "src" / "coletor.py"), "--testar-login"], "Teste de acesso ao jus.br"
    elif tipo == "conferencia":
        dias = re.sub(r"\D", "", request.form.get("dias", "7")) or "7"
        args = py + [str(raiz / "src" / "conferencia.py"), "--projeto", comum.PROJETO, "--dias", dias, "--sem-abrir"]
        descricao = f"Conferência ({dias} dias)"
    else:
        abort(400)
    logs = (comum.DATA if comum.PROJETO else comum.PROJETOS_DIR) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{tipo}.log"
    ambiente = {k: v for k, v in os.environ.items() if not k.startswith("RELATORIO_")}
    ambiente.update(PYTHONUNBUFFERED="1")
    if comum.PROJETO:
        ambiente["RELATORIO_PROJETO"] = comum.PROJETO
    separado = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True})
    proc = subprocess.Popen(args, cwd=raiz / "src", env=ambiente, stdout=log.open("w", encoding="utf-8"),
                            stderr=subprocess.STDOUT, **separado)
    TAREFA.clear()
    TAREFA.update(proc=proc, log=str(log), descricao=descricao, nome=comum.projeto().get("nome", comum.PROJETO or "-"),
                  inicio=f"{datetime.datetime.now():%H:%M}")
    return redirect("/acesso" if tipo == "teste_acesso" else "/atualizar")


@app.post("/interromper")
def interromper():
    _token_ok()
    if _tarefa_rodando():
        if WINDOWS:  # encerra o processo e os filhos (navegador)
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(TAREFA["proc"].pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(TAREFA["proc"].pid), signal.SIGTERM)
    return _ir("/atualizar", "Tarefa interrompida. O que já foi coletado fica salvo.")


# --- Planilha ---

@app.route("/planilha", methods=["GET", "POST"])
def planilha_mes():
    import planilha
    import tempfile
    proj = comum.projeto()
    aprovados = sum(e["status"] == "aprovado" for e in eventos())
    if request.method == "POST":
        _token_ok()
        arquivo = request.files.get("modelo")
        with tempfile.TemporaryDirectory() as tmp:
            if arquivo and arquivo.filename:
                if not arquivo.filename.lower().endswith(".xlsx"):
                    return _ir("/planilha", "Envie uma planilha .xlsx.")
                modelo = Path(tmp) / "modelo.xlsx"
                arquivo.save(modelo)
                nome_base = Path(arquivo.filename).stem
            elif proj.get("planilha_modelo") and Path(proj["planilha_modelo"]).exists():
                modelo = Path(proj["planilha_modelo"])
                nome_base = modelo.stem
            else:
                return _ir("/planilha", "Envie a planilha do relatório anterior (ou indique-a em Configuração).")
            nome_base = re.sub(r"\s*-\s*atualizada$", "", re.sub(r"^\d{4}-\d{2}-\d{2} - ", "", nome_base))
            nome = re.sub(r"[^\w .-]", "", nome_base)[:80] or "relatorio"
            destino = comum.RELATORIOS_DIR / "planilhas" / f"{datetime.date.today():%Y-%m-%d} - {nome}.xlsx"
            feitos, fora = planilha.gerar(modelo, destino, sem_novidade=bool(request.form.get("sem_novidade")))
        proj.update(planilha_modelo=str(destino), ultimo_relatorio=datetime.date.today().isoformat())
        comum.salvar_projeto(proj)
        msg = f"Planilha gerada: {len(feitos)} processo(s) atualizado(s). Ela passa a ser a referência do próximo mês."
        if fora:
            msg += f"\nAprovados sem linha na planilha (continuam aprovados): {', '.join(fora)}"
        return _ir("/planilha", msg)
    arquivos = sorted((comum.RELATORIOS_DIR / "planilhas").glob("*.xlsx"), reverse=True) \
        if (comum.RELATORIOS_DIR / "planilhas").exists() else []
    modelo = proj.get("planilha_modelo", "")
    h = [cabecalho("planilha"), "<h1>Planilha do mês</h1>", _msg(),
         f"<form class='caixa' method='post' enctype='multipart/form-data'>{OCULTO}"
         f"<p><b>{aprovados}</b> andamento(s) aprovado(s) para entrar na planilha.</p>"
         f"<p class='dica'>Referência atual: {html.escape(Path(modelo).name) if modelo else 'nenhuma'}"
         f"{'' if not modelo or Path(modelo).exists() else ' (arquivo não encontrado)'}. "
         "A planilha nova é uma cópia dela com os andamentos aprovados acrescentados na coluna Andamentos da aba "
         "Processos; gráficos, tabelas dinâmicas e o resto ficam iguais.</p>"
         "<p>Usar outra planilha como referência: <input type='file' name='modelo' accept='.xlsx'></p>"
         "<p><label><input type='checkbox' name='sem_novidade' value='1' checked> renovar \"Até DD/MM/AAAA sem atualizações\" "
         "nos processos sem andamento aprovado</label></p><button class='principal'>Gerar planilha</button></form>",
         "<h2>Planilhas geradas</h2><ul>"]
    for a in arquivos:
        rel = html.escape(str(a.relative_to(comum.RELATORIOS_DIR)))
        h.append(f"<li><a href='/relatorio?p={rel}'>{html.escape(a.name)}</a> "
                 f"<form style='display:inline' method='post' action='/mostrar'>{OCULTO}<input type='hidden' name='p' value='{rel}'>"
                 "<button>Mostrar no Finder</button></form></li>")
    h.append("</ul>" if arquivos else "<li class='dica'>Nenhuma ainda.</li></ul>")
    return "".join(h)


@app.post("/mostrar")
def mostrar():
    _token_ok()
    caminho = comum.RELATORIOS_DIR / request.form.get("p", "")
    if not _dentro(comum.RELATORIOS_DIR, caminho) or not caminho.is_file():
        abort(404)
    if WINDOWS:
        subprocess.run(["explorer", f"/select,{caminho}"], check=False)
    else:
        subprocess.run(["open", "-R", str(caminho)], check=False)
    return redirect("/planilha")


@app.get("/relatorio")
def ver_relatorio():
    caminho = comum.RELATORIOS_DIR / request.args.get("p", "")
    if not _dentro(comum.RELATORIOS_DIR, caminho) or not caminho.is_file():
        abort(404)
    return send_file(caminho, as_attachment=caminho.suffix == ".xlsx")


# --- Configuração ---

@app.route("/config", methods=["GET", "POST"])
def configuracao():
    proj = comum.projeto()
    if request.method == "POST":
        _token_ok()
        proj["nome"] = request.form.get("nome", "").strip() or proj.get("nome", comum.PROJETO)
        caminho = request.form.get("planilha_modelo", "").strip()
        if caminho and not Path(caminho).expanduser().exists():
            return _ir("/config", f"Planilha não encontrada: {caminho}")
        proj["planilha_modelo"] = str(Path(caminho).expanduser()) if caminho else ""
        proj["ultimo_relatorio"] = request.form.get("ultimo_relatorio", "")
        comum.salvar_projeto(proj)
        return _ir("/config", "Configuração salva.")
    return (cabecalho("config") + "<h1>Configuração do relatório</h1>" + _msg() +
            f"<form class='caixa' method='post'>{OCULTO}"
            f"<p><label>Nome do relatório<br><input type='text' name='nome' size='50' value='{html.escape(proj.get('nome', ''))}'></label></p>"
            f"<p><label>Planilha de referência (caminho completo do .xlsx do último relatório)<br>"
            f"<input type='text' name='planilha_modelo' size='90' value='{html.escape(proj.get('planilha_modelo', ''))}'></label><br>"
            "<span class='dica'>Dica: no Finder, clique no arquivo com a tecla Option e escolha \"Copiar como nome de caminho\".</span></p>"
            f"<p><label>Data do último relatório enviado<br><input type='date' name='ultimo_relatorio' "
            f"value='{html.escape(proj.get('ultimo_relatorio', ''))}'></label></p>"
            "<button class='principal'>Salvar</button></form>"
            f"<p class='dica'>Pasta deste relatório: {html.escape(str(comum.PROJETO_DIR))}</p>")


# --- arquivos dos eventos ---

@app.get("/documento")
def documento():
    ev = next((e for e in eventos() if e["id"] == request.args.get("id")), None)
    if not ev or not ev.get("arquivo") or not _dentro(comum.DOCS_DIR, ev["arquivo"]):
        abort(404)
    return send_file(ev["arquivo"])


@app.get("/print")
def ver_print():
    ev = next((e for e in eventos() if e["id"] == request.args.get("id")), None)
    if not ev or not ev.get("print") or not _dentro(comum.PRINTS_DIR, ev["print"]):
        abort(404)
    return send_file(ev["print"])


# --- Acesso e escritório (vale para todos os relatórios) ---

@app.route("/acesso", methods=["GET", "POST"])
def pagina_acesso():
    import acesso
    cfg = comum.config()  # config.json ou, na primeira vez, o exemplo
    if request.method == "POST":
        _token_ok()
        msgs = []
        senha = request.form.get("cert_senha", "")
        segredo = re.sub(r"\s", "", request.form.get("totp_secret", "")).upper()
        if senha:
            acesso.guardar("cert_senha", senha)
            msgs.append("Senha do certificado guardada no cofre do sistema.")
        if segredo:
            if not acesso.segredo_totp_valido(segredo):
                return _ir("/acesso", "O segredo do autenticador não é válido (letras A-Z e números 2-7). Nada foi salvo.")
            acesso.guardar("totp_secret", segredo)
            msgs.append("Segredo do autenticador guardado no cofre do sistema.")
        nomes = [l.strip() for l in request.form.get("identificadores", "").splitlines() if l.strip()]
        cfg["identificadores_escritorio"] = nomes
        cfg["revisor"] = request.form.get("revisor", "").strip()
        comum.save_json(comum.CONFIG_FILE, cfg)
        msgs.append("Dados do escritório salvos.")
        return _ir("/acesso", " ".join(msgs))
    st = acesso.situacao()
    codigo = acesso.codigo_totp_atual() if st["totp_secret"] else None
    log_teste = ""
    if TAREFA and TAREFA.get("descricao", "").startswith("Teste de acesso"):
        texto = Path(TAREFA["log"]).read_text(encoding="utf-8", errors="replace")[-3000:] if Path(TAREFA["log"]).exists() else ""
        rodando = _tarefa_rodando()
        log_teste = (f"<pre class='log'>{html.escape(texto)}</pre>"
                     + ("<script>setTimeout(()=>location.reload(),3000)</script>" if rodando else ""))
    ok = lambda b: "<b style='color:var(--ok)'>configurada ✓</b>" if b else "<b style='color:var(--alerta)'>não configurada</b>"
    return (cabecalho("acesso", "Acesso e escritório") + "<h1>Acesso e escritório</h1>" + _msg() +
            f"<form class='caixa' method='post'>{OCULTO}"
            "<p class='dica'>Os dois segredos abaixo vão direto para o cofre do sistema (Keychain no Mac, Gerenciador "
            "de Credenciais no Windows). Não ficam em arquivo e não voltam a aparecer na tela. Para trocar, digite de novo; "
            "em branco, mantém o que está guardado.</p>"
            f"<p><label>Senha (PIN) do certificado digital, a mesma que você digita no PJe Office: {ok(st['cert_senha'])}<br>"
            "<input type='password' name='cert_senha' autocomplete='off' size='30'></label></p>"
            f"<p><label>Segredo do autenticador do jus.br (código de 16 a 32 letras e números): {ok(st['totp_secret'])}<br>"
            "<input type='password' name='totp_secret' autocomplete='off' size='40'></label>"
            + (f"<br><span class='dica'>Código de agora, gerado com o segredo guardado: <b>{codigo}</b>. "
               "Confira se é o mesmo do app autenticador do seu celular.</span>" if codigo else "") + "</p>"
            "<p><label>Quem assina pelo escritório: um por linha, nome completo e número da OAB "
            "(ex.: <i>Fulano de Tal</i> e <i>12.345</i>)<br>"
            f"<textarea name='identificadores' rows='5'>{html.escape(chr(10).join(cfg.get('identificadores_escritorio', [])))}</textarea>"
            "</label><span class='dica'>Serve para escrever \"apresentamos\" nas petições do escritório e \"a parte contrária "
            "apresentou\" nas demais.</span></p>"
            f"<p><label>Seu nome (fica registrado nas aprovações) <input type='text' name='revisor' size='30' "
            f"value='{html.escape(cfg.get('revisor', ''))}'></label></p>"
            "<button class='principal'>Salvar</button></form>"
            f"<form class='caixa' method='post' action='/tarefa'>{OCULTO}<input type='hidden' name='tipo' value='teste_acesso'>"
            "<b>Testar acesso</b><p class='dica'>Abre o navegador minimizado, entra no jus.br com o certificado e o "
            "autenticador e fecha. O PJe Office precisa estar aberto.</p>"
            f"<button {'disabled' if _tarefa_rodando() else ''}>Testar acesso</button>{log_teste}</form>")


cadastro.registrar(app, TOKEN, cabecalho, _token_ok)


if __name__ == "__main__":
    porta = config().get("porta_revisao", 5072)
    print(f"Painel em http://127.0.0.1:{porta}  (feche esta janela para encerrar)")
    if "--abrir" in sys.argv:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{porta}/")).start()
    app.run(host="127.0.0.1", port=porta, debug=False, threaded=False)
