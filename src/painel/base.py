"""Peças comuns do painel: estilo, barra de abas, mensagens, redirecionamento,
verificação do token, proteção de caminhos e a escolha do relatório ativo.
Cada tela (os outros módulos de painel/) recebe `cabecalho` e `token_ok` daqui
pelo `registrar(app, TOKEN, cabecalho, token_ok)`, como em cadastro.py."""
import html
import os
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
#atencao{position:sticky;top:0;z-index:50;background:#b91c1c;color:#fff;padding:10px 16px;font-weight:700;font-size:15px}
#atencao small{display:block;font-weight:400;opacity:.9}
</style>"""

# Faixa vermelha fixa quando a coleta espera uma pessoa (captcha do TRT, login do jus.br). Atualiza sozinha.
SCRIPT_ATENCAO = """<script>
(function(){var f=document.getElementById('atencao');if(!f)return;
function ler(){fetch('/atencao.json',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
if(d&&d.texto){f.textContent=d.texto;f.style.display='block'}else{f.style.display='none'}}).catch(function(){})}
setInterval(ler,5000)})();
</script>"""


def faixa_de_atencao():
    """A faixa vermelha (escondida quando não há pedido). O texto inicial vem do servidor; o script a mantém em dia."""
    import atencao
    registro = atencao.atual()
    texto = html.escape(atencao.texto_da_faixa(registro)) if registro else ""
    return (f"<div id='atencao' role='alert' style='display:{'block' if registro else 'none'}'>{texto}</div>"
            + SCRIPT_ATENCAO)

SUBABAS = [("fluxo", "/fluxo", "Assistente"), ("atualizar", "/atualizar", "Atualizar"), ("revisar", "/", "Revisar"),
           ("planilha", "/planilha", "Planilha"), ("migracao", "/migracao", "Migrar de modelo"),
           ("entregas", "/entregas", "Entregas"),
           ("pedidos", "/pedidos", "Pedidos"), ("cadastro", "/cadastro", "Clientes e processos"),
           ("perfil", "/perfil", "Perfil"), ("ia", "/ia", "IA"), ("config", "/config", "Configuração")]


def _ia_local_pronta():
    """O motor local (Ollama) está instalado? Verificação barata (sem rede nem subprocesso), usada em todo cabeçalho; o
    detalhe (modelo baixado) fica na tela /ia. Qualquer erro vale 'não': o cabeçalho nunca quebra a tela."""
    try:
        import ia_local
        return ia_local.ollama_exe() is not None
    except Exception:
        return False


def cabecalho(ativa, titulo="Relatório de Andamentos"):
    abas = "".join(f"<a href='/p/{s}' class='{'ativa' if s == comum.PROJETO else ''}'>{html.escape(d.get('nome', s))}</a>"
                   for s, d in comum.projetos())
    sub = "".join(f"<a href='{url}' class='{'ativa' if chave == ativa else ''}'>{rotulo}</a>"
                  for chave, url, rotulo in SUBABAS) if comum.PROJETO else ""
    rodando = (f" · <a href='/atualizar'>tarefa em andamento: {html.escape(TAREFA['descricao'])}</a>"
               if _tarefa_rodando() else "")
    import acesso
    pronto = all(acesso.situacao().values())
    ia_pronta = _ia_local_pronta()
    aviso = ("" if pronto or ativa == "acesso" else
             "<div class='alerta' style='margin:12px 16px'>Falta configurar o acesso (senha do certificado e "
             "código do autenticador). <a href='/acesso'>Configurar agora</a></div>")
    return (f"<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'><title>{html.escape(titulo)}</title>{ESTILO}<body>"
            f"{faixa_de_atencao()}{aviso_de_painel_desatualizado()}"
            f"<div class='barra'><div class='marca'>Relatório de Andamentos<span class='meta'>{(' · versão ' + html.escape(versao())) if versao() else ''}{rodando}</span>"
            f"<a href='/acesso' style='float:right;font-weight:normal;font-size:14px' "
            f"class='{'ativa' if ativa == 'acesso' else ''}'>Acesso e escritório {'✓' if pronto else '(configurar)'}</a>"
            f"<a href='/ia' style='float:right;font-weight:normal;font-size:14px;margin-right:18px' "
            f"class='{'ativa' if ativa == 'ia' else ''}'>IA local {'(instalada)' if ia_pronta else '(instalar)'}</a></div>"
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


def versao():
    """Texto do arquivo VERSAO (ex.: '2.0.0-beta2'); vazio se não existir. A variável RELATORIO_VERSAO a sobrepõe
    (os testes fixam um valor para o cabeçalho não mudar a cada versão)."""
    if "RELATORIO_VERSAO" in os.environ:
        return os.environ["RELATORIO_VERSAO"]
    try:
        return (comum.RAIZ / "VERSAO").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


VERSAO_CARREGADA = versao()     # a versão do programa que ESTE painel carregou ao abrir


def aviso_de_painel_desatualizado():
    """Se o arquivo VERSAO mudou depois que o painel abriu (pacote novo copiado por cima com o painel ainda aberto), o
    painel segue rodando o código ANTIGO e o número da versão no topo mente. Devolve o aviso, ou ''."""
    atual = versao()
    if atual == VERSAO_CARREGADA:
        return ""
    return ("<div class='alerta' style='margin:12px 16px;background:#b91c1c;color:#fff;font-weight:700'>Reinicie o painel: o programa "
            f"foi atualizado para a versão {html.escape(atual or '?')}, mas este painel ainda está rodando a versão "
            f"{html.escape(VERSAO_CARREGADA or '?')}. Feche a janela do Terminal do painel e abra o <b>Abrir painel.command</b> de novo.</div>")


def _tarefa_rodando():
    return bool(TAREFA) and TAREFA["proc"].poll() is None


def coleta_em_andamento_em():
    """Slug do relatório em que a coleta do Assistente está rodando agora, ou None. A coleta roda numa thread deste
    processo e usa o relatório "ativo" (`comum.PROJETO`, global): trocar de relatório no meio gravaria andamentos no
    relatório errado. Por isso a troca fica bloqueada enquanto a coleta roda."""
    try:
        from painel import assistente
        return assistente.EXEC.get("slug") if assistente.execucao_rodando() else None
    except Exception:
        return None


def registrar(app, TOKEN, cabecalho, token_ok):
    """Registra o que vale para todas as telas: a escolha do relatório ativo."""
    @app.before_request
    def escolher_projeto():
        """O relatório ativo vem do cookie; sem relatório nenhum, só a tela de criar."""
        slug = request.cookies.get("projeto")
        disponiveis = [s for s, _ in comum.projetos()]
        rodando = coleta_em_andamento_em()
        if rodando and rodando in disponiveis:
            slug = rodando                  # coleta em andamento: o relatório não muda até terminar
        if slug in disponiveis and slug != comum.PROJETO:
            comum.usar_projeto(slug)
        primeiro_uso = ("/novo", "/acesso", "/tarefa", "/atualizar", "/interromper", "/atencao.json", "/versao.json", "/ia")
        # o assistente e a migração de modelo criam o primeiro relatório: ficam liberados sem relatório
        if not disponiveis and request.path not in primeiro_uso and not request.path.startswith(("/fluxo", "/migracao")):
            return redirect("/novo")

    @app.get("/versao.json")
    def versao_json():
        """Para o lançador (abrir_painel.py): qual versão ESTE servidor carregou, qual está no disco e se há trabalho
        em andamento (nesse caso o lançador não reinicia o servidor)."""
        return {"carregada": VERSAO_CARREGADA, "arquivo": versao(), "coleta": bool(coleta_em_andamento_em()),
                "tarefa": _tarefa_rodando()}

    @app.get("/atencao.json")
    def atencao_json():
        """O que a faixa vermelha mostra agora ({} quando ninguém é esperado)."""
        import atencao
        from flask import jsonify
        registro = atencao.atual()
        resposta = jsonify({**registro, "texto": atencao.texto_da_faixa(registro)} if registro else {})
        resposta.headers["Cache-Control"] = "no-store"
        return resposta
