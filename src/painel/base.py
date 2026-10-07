"""Peças comuns do painel: estilo, barra de abas, mensagens, redirecionamento,
verificação do token, proteção de caminhos e a escolha do relatório ativo.
Cada tela (os outros módulos de painel/) recebe `cabecalho` e `token_ok` daqui
pelo `registrar(app, TOKEN, cabecalho, token_ok)`, como em cadastro.py."""
import html
import sys
from pathlib import Path

from flask import abort, redirect, request

import comum

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

SUBABAS = [("fluxo", "/fluxo", "Assistente"), ("atualizar", "/atualizar", "Atualizar"), ("revisar", "/", "Revisar"),
           ("planilha", "/planilha", "Planilha"), ("entregas", "/entregas", "Entregas"),
           ("pedidos", "/pedidos", "Pedidos"), ("cadastro", "/cadastro", "Clientes e processos"),
           ("perfil", "/perfil", "Perfil"), ("ia", "/ia", "IA"), ("config", "/config", "Configuração")]


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


def criar_token_ok(TOKEN):
    """O `token_ok` que as telas chamam no início de cada POST."""
    def token_ok():
        if request.form.get("token") != TOKEN:
            abort(403)
    return token_ok


def _dentro(base, caminho):
    try:
        Path(caminho).resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _tarefa_rodando():
    return bool(TAREFA) and TAREFA["proc"].poll() is None


def registrar(app, TOKEN, cabecalho, token_ok):
    """Registra o que vale para todas as telas: a escolha do relatório ativo."""
    @app.before_request
    def escolher_projeto():
        """O relatório ativo vem do cookie; sem relatório nenhum, só a tela de criar."""
        slug = request.cookies.get("projeto")
        disponiveis = [s for s, _ in comum.projetos()]
        if slug in disponiveis and slug != comum.PROJETO:
            comum.usar_projeto(slug)
        primeiro_uso = ("/novo", "/acesso", "/tarefa", "/atualizar", "/interromper")
        # o assistente e a migração de modelo criam o primeiro relatório: ficam liberados sem relatório
        if not disponiveis and request.path not in primeiro_uso and not request.path.startswith(("/fluxo", "/migracao")):
            return redirect("/novo")
