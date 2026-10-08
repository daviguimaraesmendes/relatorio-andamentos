"""Tela IA (/ia): provedores de IA, consentimento por relatório e por cliente e registro de envios.

- Cadastro de provedores externos (Claude pela API da Anthropic, Claude pelo Claude Code deste
  computador ou serviço compatível com OpenAI): nome, endereço, modelo e chave. A chave vai direto
  para o cofre do sistema e **nunca** volta para a tela (o campo fica sempre vazio; em branco, mantém
  a guardada). O Claude pelo Claude Code não usa chave: vale o login da assinatura já feito nele.
- Botão Testar: manda uma frase fixa, sem dado de cliente, e mostra o resultado.
- Consentimento: o motor padrão é o local. Para usar provedor externo é preciso escolhê-lo,
  marcar o consentimento (do relatório e/ou de cada cliente) e confirmar que entendeu o que sai
  do computador. Grava só a seção `ia` de `perfil.json` do relatório (o resto do perfil é de outra tela).
- Registro de envios: o que já saiu do computador, quando e para quem (sem o texto).

Rotas: GET /ia, GET /ia/registro, POST /ia/provedor, /ia/remover, /ia/testar, /ia/consentimento.
A lógica está em ia.py; aqui só há a tela. Para os testes, `TRANSPORTE`, `FABRICA_CLIENTE` e
`EXECUTAR` substituem a rede e o Claude Code (padrão: None = real).
"""
import html

from flask import request

import comum
import ia
from painel.base import _ir, _msg

TRANSPORTE = None
FABRICA_CLIENTE = None
EXECUTAR = None
_e = html.escape
CHAVE_OK = "<b style='color:var(--ok)'>guardada ✓</b>"
CHAVE_FALTA = "<b style='color:var(--alerta)'>sem chave</b>"
CHAVE_LOGIN = "<b style='color:var(--ok)'>login do Claude Code</b>"

ESTILO_LOCAL = ("<style>table.ia{border-collapse:collapse;width:100%}table.ia td,table.ia th{border:1px solid var(--linha);"
                "padding:4px 8px;font-size:14px;text-align:left;vertical-align:top}.selo{display:inline-block;padding:1px 8px;"
                "border-radius:10px;font-size:12px;background:var(--ok-fundo);color:var(--ok)}"
                ".selo.externa{background:var(--alerta-fundo);color:var(--alerta)}</style>")


def _selo(texto):
    return f"<span class='selo{' externa' if texto != 'local' else ''}'>{_e(texto)}</span>"


def _clientes():
    dados = comum.load_json(comum.CLIENTES_FILE, {"clientes": []})
    return [c["nome"] for c in dados.get("clientes", []) if isinstance(c, dict) and c.get("nome")]


def _tabela_registro(envios):
    if not envios:
        return "<p class='dica'>Nada saiu do computador neste relatório.</p>"
    linhas = "".join(
        f"<tr><td>{_e(e.get('quando', ''))}</td><td>{_e(e.get('provedor', ''))}</td><td>{_e(e.get('modelo', ''))}</td>"
        f"<td>{_e(e.get('cliente', ''))}</td><td>{_e(str(e.get('caracteres', '')))}</td>"
        f"<td>{'sim' if e.get('pseudonimizado') else 'não'}</td><td><code>{_e(str(e.get('sha256', ''))[:12])}</code></td>"
        f"<td>{_e(e.get('resultado', ''))}</td></tr>" for e in reversed(envios))
    return ("<table class='ia'><tr><th>Quando</th><th>Provedor</th><th>Modelo</th><th>Cliente</th><th>Caracteres</th>"
            f"<th>Pseudônimos</th><th>Impressão do texto</th><th>Resultado</th></tr>{linhas}</table>")


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def _formulario_provedor(editando):
        atual = ia.provedores().get(editando, {}) if editando else {}
        tipo = atual.get("tipo", "anthropic")
        opcoes = "".join(f"<option value='{t}' {'selected' if t == tipo else ''}>{_e(r)}</option>" for t, r in ia.TIPOS.items())
        fallback = atual.get("fallback_servidor", True)
        return (f"<form class='caixa' method='post' action='/ia/provedor'>{oculto}"
                f"<b>{'Atualizar' if atual else 'Cadastrar'} provedor</b>"
                f"<p><label>Nome (como aparecerá nas telas)<br><input type='text' name='nome' size='30' required "
                f"value='{_e(atual.get('nome', ''))}'></label></p>"
                f"<p><label>Tipo<br><select name='tipo'>{opcoes}</select></label></p>"
                f"<p><label>Modelo<br><input type='text' name='modelo' size='40' "
                f"value='{_e(atual.get('modelo', ia.MODELO_ANTHROPIC_PADRAO if tipo == 'anthropic' else ''))}'></label>"
                f"<br><span class='dica'>Claude (API): o padrão é <code>{_e(ia.MODELO_ANTHROPIC_PADRAO)}</code>. "
                "Claude Code: um apelido (<code>opus</code>, <code>sonnet</code>...) ou, em branco, o padrão da sua conta. "
                "Outro serviço: o nome do modelo como o serviço o chama.</span></p>"
                f"<p><label>Endereço da API<br><input type='text' name='endereco' size='60' "
                f"value='{_e(atual.get('endereco', ''))}'></label>"
                "<br><span class='dica'>Obrigatório para serviço compatível com OpenAI (o endereço da API do serviço). "
                "Para o Claude, deixe em branco. O endereço precisa começar com https.</span></p>"
                "<p><label>Chave da API<br><input type='password' name='chave' autocomplete='off' size='50'></label>"
                "<br><span class='dica'>Vai para o cofre do sistema e não volta a aparecer na tela. "
                "Não se aplica ao Claude pelo Claude Code (usa o login dele). "
                f"{'Já há uma chave guardada: em branco, mantém.' if atual and ia.chave_configurada(editando) else ''}</span></p>"
                "<p><label>Caminho do Claude Code (só para o tipo \"Claude pelo Claude Code\")<br>"
                f"<input type='text' name='executavel' size='60' value='{_e(atual.get('executavel', ''))}'></label>"
                "<br><span class='dica'>Em branco, a ferramenta procura sozinha. Vale a conta em que o Claude Code já está "
                "conectado (<code>/login</code>); o consumo entra no limite da sua assinatura. <b>O texto continua indo à "
                "Anthropic</b>, só que pela assinatura e não pela API: confira os termos da sua conta antes de autorizar "
                "dados de clientes.</span></p>"
                f"<p><label><input type='checkbox' name='fallback_servidor' value='1' {'checked' if fallback else ''}> "
                "Claude: se o modelo recusar o pedido, deixar a Anthropic tentar outro modelo dela (na mesma chamada)</label></p>"
                "<button class='principal'>Salvar provedor</button></form>")

    @app.get("/ia")
    def pagina_ia():
        perfil = ia.carregar_perfil()
        cfg_ia = perfil.get("ia") if isinstance(perfil.get("ia"), dict) else {}
        catalogo = ia.provedores()
        clientes = _clientes()
        escolhido = comum.slug(cfg_ia.get("provedor", "local")) if isinstance(cfg_ia.get("provedor"), str) else "local"
        escolhido = escolhido if escolhido in catalogo else "local"
        por_cliente = cfg_ia.get("por_cliente") if isinstance(cfg_ia.get("por_cliente"), dict) else {}
        h = [cabecalho("ia", "Provedores de IA"), ESTILO_LOCAL, "<h1>Inteligência artificial</h1>", _msg(),
             "<p>Por padrão, o resumo dos documentos é feito <b>no seu computador</b> (IA local) e nada sai dele. "
             "Aqui você pode, <b>cliente por cliente</b>, autorizar o envio do <b>texto</b> dos documentos a um serviço de IA "
             f"externo. Selo atual deste relatório: {_selo(ia.selo_para(perfil, ''))}</p>"]

        # 1. provedores cadastrados
        h.append("<h2>1. Provedores cadastrados</h2>")
        if catalogo:
            linhas = []
            for chave_id, p in sorted(catalogo.items()):
                linhas.append(
                    f"<tr><td>{_e(p.get('nome', chave_id))}</td><td>{_e(ia.TIPOS.get(p['tipo'], p['tipo']))}</td>"
                    f"<td>{_e(p.get('modelo', ''))}</td><td>{_e(p.get('endereco') or '(padrão do serviço)')}</td>"
                    f"<td>{CHAVE_LOGIN if p['tipo'] == 'claude_cli' else CHAVE_OK if ia.chave_configurada(chave_id) else CHAVE_FALTA}</td>"
                    f"<td><form method='post' action='/ia/testar' style='display:inline'>{oculto}"
                    f"<input type='hidden' name='nome' value='{_e(chave_id)}'><button>Testar</button></form> "
                    f"<a href='/ia?editar={_e(chave_id)}'>editar</a> "
                    f"<form method='post' action='/ia/remover' style='display:inline'>{oculto}"
                    f"<input type='hidden' name='nome' value='{_e(chave_id)}'><button>Remover</button></form></td></tr>")
            h.append("<table class='ia'><tr><th>Nome</th><th>Tipo</th><th>Modelo</th><th>Endereço</th><th>Chave</th><th></th></tr>"
                     + "".join(linhas) + "</table>"
                     "<p class='dica'>Testar envia só a frase \"Teste de conexão.\" (nenhum dado de cliente) e fica no registro de envios.</p>")
        else:
            h.append("<p class='dica'>Nenhum provedor externo cadastrado: tudo roda na IA local.</p>")
        h.append(_formulario_provedor(request.args.get("editar", "")))

        # 2. consentimento
        opcoes = "".join(f"<option value='{_e(k)}' {'selected' if k == escolhido else ''}>{_e(v.get('nome', k))}</option>"
                         for k, v in sorted(catalogo.items()))
        linhas_cli = "".join(
            f"<tr><td><input type='hidden' name='cliente_{i}' value='{_e(n)}'>{_e(n)}</td>"
            f"<td><input type='checkbox' name='cons_{i}' value='1' "
            f"{'checked' if any(comum.normalizar(str(k)) == comum.normalizar(n) and v is True for k, v in por_cliente.items()) else ''}></td>"
            f"<td>{_selo(ia.selo_para(perfil, n))}</td></tr>" for i, n in enumerate(clientes))
        h.append(
            "<h2>2. O que este relatório usa</h2>"
            f"<form class='caixa' method='post' action='/ia/consentimento'>{oculto}"
            f"<p><label>Provedor<br><select name='provedor'><option value='local' {'selected' if escolhido == 'local' else ''}>"
            f"Local (no meu computador)</option>{opcoes}</select></label></p>"
            "<div class='alerta'><b>O que sai do computador</b> se você autorizar: o <b>texto extraído</b> dos documentos do processo "
            "(trechos de até cerca de 9.000 caracteres por documento), mais o tipo do documento, quem o apresentou e o lado do cliente. "
            "<b>Não sai</b>: print de tela, certificado digital, senha, segredo do autenticador, caminhos de arquivo, planilhas e a "
            "carteira. Com \"pseudônimos\" ligado, nomes das partes, CPF, CNPJ, e-mail e número de processo são trocados por "
            "marcadores antes do envio (e devolvidos no resultado, só aqui). Isso reduz o risco, <b>não o elimina</b>: um nome escrito "
            "de forma diferente da cadastrada pode passar. Cada envio fica no registro abaixo (sem o texto).</div>"
            f"<p><label><input type='checkbox' name='pseudonimizar' value='1' "
            f"{'' if cfg_ia.get('pseudonimizar') is False else 'checked'}> Trocar nomes e números por pseudônimos antes de enviar</label></p>"
            f"<p><label><input type='checkbox' name='consentimento_externo' value='1' "
            f"{'checked' if cfg_ia.get('consentimento_externo') is True else ''}> Autorizo o envio, <b>para os clientes sem marcação "
            "própria abaixo</b>, ao provedor escolhido</label></p>"
            + (("<table class='ia'><tr><th>Cliente</th><th>Autorizo o envio</th><th>Vale agora</th></tr>" + linhas_cli +
                "</table><p class='dica'>A marcação de cada cliente vale para ele e prevalece sobre a do relatório. "
                "Cliente desmarcado fica sem envio; cliente cadastrado depois segue a marcação do relatório.</p>") if clientes else
               "<p class='dica'>Cadastre clientes em \"Clientes e processos\" para autorizar um a um.</p>")
            + "<p><label><input type='checkbox' name='entendi' value='1'> Entendi que, para os clientes autorizados, o texto dos "
              "documentos será enviado ao provedor escolhido (só necessário para ativar o envio).</label></p>"
              "<button class='principal'>Salvar</button></form>")

        # 3. registro
        envios = ia.registro_de_envios()
        h.append("<h2>3. Registro de envios</h2>"
                 "<p class='dica'>Tudo o que saiu do computador neste relatório. Guarda quando, para quem, quantos caracteres e uma "
                 "impressão digital do texto, nunca o texto.</p>" + _tabela_registro(envios[-10:])
                 + ("<p><a href='/ia/registro'>Ver o registro completo</a></p>" if len(envios) > 10 else ""))
        return "".join(h)

    @app.get("/ia/registro")
    def registro_completo():
        return (cabecalho("ia", "Registro de envios de IA") + ESTILO_LOCAL + "<h1>Registro de envios à IA externa</h1>"
                "<p><a href='/ia'>Voltar</a></p>" + _tabela_registro(ia.registro_de_envios()))

    @app.post("/ia/provedor")
    def salvar_provedor():
        token_ok()
        f = request.form
        avisos = ia.cadastrar(f.get("nome", ""), f.get("tipo", ""), f.get("modelo", ""), f.get("endereco", ""),
                              chave=f.get("chave", ""), fallback_servidor=bool(f.get("fallback_servidor")),
                              executavel=f.get("executavel", "").strip())
        return _ir("/ia", " ".join(a["mensagem"] for a in avisos) or f"Provedor \"{f.get('nome', '').strip()}\" salvo.")

    @app.post("/ia/remover")
    def remover_provedor():
        token_ok()
        ok = ia.remover(request.form.get("nome", ""))
        return _ir("/ia", "Provedor removido (a chave foi esvaziada no cofre)." if ok else "Provedor não encontrado.")

    @app.post("/ia/testar")
    def testar_provedor():
        token_ok()
        r = ia.testar(request.form.get("nome", ""), transporte=TRANSPORTE, fabrica_cliente=FABRICA_CLIENTE,
                     executar=EXECUTAR)
        if r["ok"]:
            return _ir("/ia", f"Teste concluído: o provedor respondeu \"{r['resposta']}\" (motor {r['motor']}).")
        return _ir("/ia", "O teste falhou: " + " ".join(a["mensagem"] for a in r["avisos"]))

    @app.post("/ia/consentimento")
    def salvar_consentimento():
        token_ok()
        f = request.form
        catalogo = ia.provedores()
        escolhido = comum.slug(f.get("provedor", "local"))
        escolhido = escolhido if escolhido in catalogo else "local"
        por_cliente = {}
        i = 0
        while f"cliente_{i}" in f:
            por_cliente[f[f"cliente_{i}"]] = bool(f.get(f"cons_{i}"))
            i += 1
        relatorio = bool(f.get("consentimento_externo"))
        if escolhido != "local" and (relatorio or any(por_cliente.values())) and not f.get("entendi"):
            return _ir("/ia", "Nada foi salvo: marque a confirmação de que entendeu o que será enviado.")
        ia.salvar_ia_no_perfil({"provedor": escolhido, "consentimento_externo": relatorio, "por_cliente": por_cliente,
                                "pseudonimizar": bool(f.get("pseudonimizar"))})
        if escolhido == "local":
            return _ir("/ia", "Salvo: este relatório usa a IA local.")
        return _ir("/ia", f"Salvo: provedor \"{catalogo[escolhido].get('nome', escolhido)}\" escolhido; só envia para quem "
                          "estiver autorizado.")
