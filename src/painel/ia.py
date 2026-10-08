"""Tela IA (/ia): provedores de IA, consentimento por relatório e por cliente e registro de envios.

- Cadastro de provedores externos (Claude pela API da Anthropic, Claude pelo Claude Code deste
  computador ou serviço compatível com OpenAI): nome, endereço, modelo e chave. A chave vai direto
  para o cofre do sistema e **nunca** volta para a tela (o campo fica sempre vazio; em branco, mantém
  a guardada). O Claude pelo Claude Code não usa chave: vale o login da assinatura já feito nele.
  O formulário esconde e mostra os campos conforme o tipo escolhido (pequeno script na própria página,
  sem recurso externo; sem script, todos os campos aparecem).
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
from painel.base import _ir, _msg, ajuda

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
                ".selo.externa{background:var(--alerta-fundo);color:var(--alerta)}"
                "[data-tipos][hidden]{display:none}details.avancado{margin:8px 0}details.avancado>summary{cursor:pointer;font-weight:600}</style>")

# Mostra só os campos que valem para o tipo escolhido. Os campos escondidos continuam no formulário (o servidor
# ignora o que não se aplica ao tipo). Sem JavaScript, tudo aparece e as dicas dizem a que tipo cada campo se refere.
SCRIPT_TIPOS = """<script>
(function(){var f=document.getElementById('form-provedor');if(!f)return;var tipo=f.querySelector('[name=tipo]');
var modelo=f.querySelector('[name=modelo]'),padrao=modelo.getAttribute('data-padrao-anthropic');
function atualizar(){var t=tipo.value;f.querySelectorAll('[data-tipos]').forEach(function(el){
el.hidden=el.getAttribute('data-tipos').split(' ').indexOf(t)<0});
var det=f.querySelector('details.avancado');if(det){var visivel=det.querySelectorAll('[data-tipos]:not([hidden])').length>0;det.hidden=!visivel}
if(t==='anthropic'&&!modelo.value)modelo.value=padrao;
if(t!=='anthropic'&&modelo.value===padrao)modelo.value=''}
tipo.addEventListener('change',atualizar);atualizar()})();
</script>"""


def _selo(texto):
    return f"<span class='selo{' externa' if texto != 'local' else ''}'>{_e(texto)}</span>"


def _clientes():
    dados = comum.load_json(comum.CLIENTES_FILE, {"clientes": []})
    return [c["nome"] for c in dados.get("clientes", []) if isinstance(c, dict) and c.get("nome")]


def _tabela_registro(envios):
    if not envios:
        return "<div class='vazio'>Nada saiu do computador neste relatório.</div>"
    linhas = "".join(
        f"<tr><td>{_e(e.get('quando', ''))}</td><td>{_e(e.get('provedor', ''))}</td><td>{_e(e.get('modelo', ''))}</td>"
        f"<td>{_e(e.get('cliente', ''))}</td><td>{_e(str(e.get('caracteres', '')))}</td>"
        f"<td>{'sim' if e.get('pseudonimizado') else 'não'}</td><td><code>{_e(str(e.get('sha256', ''))[:12])}</code></td>"
        f"<td>{_e(e.get('resultado', ''))}</td></tr>" for e in reversed(envios))
    return ("<table class='ia'><tr><th>Quando</th><th>Provedor</th><th>Modelo</th><th>Cliente</th><th>Caracteres"
            + ajuda("Tamanho do texto enviado, contado em letras e espaços.") + "</th>"
            "<th>Pseudônimos" + ajuda("\"sim\" quer dizer que nomes das partes, CPF, CNPJ, e-mail e número de processo foram trocados "
                                      "por marcadores antes do envio.") + "</th>"
            "<th>Impressão do texto" + ajuda("Um código (SHA-256, só os 12 primeiros caracteres) que identifica o texto enviado sem "
                                             "guardar o texto. Serve para comprovar depois o que saiu.") + "</th>"
            f"<th>Resultado</th></tr>{linhas}</table>")


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def _formulario_provedor(editando):
        atual = ia.provedores().get(editando, {}) if editando else {}
        tipo = atual.get("tipo", "anthropic")
        opcoes = "".join(f"<option value='{t}' {'selected' if t == tipo else ''}>{_e(r)}</option>" for t, r in ia.TIPOS.items())
        fallback = atual.get("fallback_servidor", True)
        padrao = _e(ia.MODELO_ANTHROPIC_PADRAO)
        return (f"<form class='caixa' id='form-provedor' method='post' action='/ia/provedor'>{oculto}"
                f"<b>{'Atualizar' if atual else 'Cadastrar'} provedor</b>"
                + ajuda("Um provedor é um serviço de IA fora do seu computador que pode resumir documentos no lugar da IA local. "
                        "Cadastrar não envia nada: só guarda os dados. O envio só acontece depois que você escolhe o provedor e "
                        "autoriza, na seção 2 abaixo.")
                + "<p class='dica'>Não precisa cadastrar nada para usar a ferramenta: sem provedor, o resumo é feito no seu computador.</p>"
                f"<p><label>Tipo de provedor"
                + ajuda("“Claude (API)”: manda o texto à Anthropic pela API, com uma chave sua (cobrança conforme o uso). "
                        "“Claude pelo Claude Code”: usa o Claude Code já instalado e conectado neste computador, com o login da sua "
                        "assinatura, sem chave de API; o texto TAMBÉM vai à Anthropic, então NÃO é IA local. "
                        "“API compatível com OpenAI”: qualquer serviço que fale o mesmo protocolo (por exemplo, um gateway do "
                        "escritório); precisa de endereço https, modelo e chave.")
                + f"<br><select name='tipo'>{opcoes}</select></label></p>"
                "<div class='alerta' data-tipos='claude_cli'><b>Atenção: o Claude Code NÃO é IA local.</b> Ele roda neste computador, mas "
                "o texto dos documentos autorizados é enviado à Anthropic, só que pela sua assinatura em vez da API. Os termos de uso e "
                "de retenção de dados de uma assinatura podem ser diferentes dos da API: confira antes de autorizar dados de clientes.</div>"
                f"<p><label>Nome (como aparecerá nas telas)"
                + ajuda("Um nome seu para reconhecer este provedor (por exemplo, \"Claude do escritório\"). Escolher o mesmo nome de um "
                        "provedor já cadastrado atualiza aquele. \"local\" é reservado.")
                + f"<br><input type='text' name='nome' size='30' required placeholder='ex.: Claude do escritório' "
                f"value='{_e(atual.get('nome', ''))}'></label></p>"
                f"<p><label>Modelo"
                + ajuda("O modelo de IA que fará os resumos. Claude (API): o padrão sugerido serve. Claude Code: pode deixar em branco "
                        "(usa o padrão da sua conta) ou usar um apelido como opus ou sonnet. Outro serviço: o nome do modelo como "
                        "o próprio serviço o chama.")
                + f"<br><input type='text' name='modelo' size='40' data-padrao-anthropic='{padrao}' "
                f"value='{_e(atual.get('modelo', ia.MODELO_ANTHROPIC_PADRAO if tipo == 'anthropic' else ''))}'></label>"
                f"<br><span class='dica' data-tipos='anthropic'>Claude (API): o padrão é <code>{padrao}</code>.</span>"
                "<span class='dica' data-tipos='claude_cli'>Claude Code: um apelido (<code>opus</code>, <code>sonnet</code>...) ou, em branco, "
                "o padrão da sua conta.</span>"
                "<span class='dica' data-tipos='openai_compativel'>Outro serviço: o nome do modelo como o serviço o chama.</span></p>"
                f"<p data-tipos='openai_compativel'><label>Endereço da API"
                + ajuda("O endereço (URL) em que o serviço recebe os pedidos, sempre começando com https. É o endereço do serviço "
                        "para onde o texto autorizado seria enviado: use só um que você conheça e em que confie.")
                + f"<br><input type='text' name='endereco' size='60' placeholder='endereço do serviço, começando com https' "
                f"value='{_e(atual.get('endereco', ''))}'></label>"
                "<br><span class='dica'>Obrigatório para serviço compatível com OpenAI (o endereço da API do serviço). "
                "Para o Claude, deixe em branco. O endereço precisa começar com https.</span></p>"
                f"<p data-tipos='anthropic openai_compativel'><label>Chave da API"
                + ajuda("Sua senha de acesso ao serviço. Vai direto para o cofre do sistema (Keychain no Mac, Gerenciador de Credenciais no Windows) e nunca mais "
                        "aparece na tela nem fica em arquivo do programa. Deixar em branco mantém a chave já guardada.")
                + "<br><input type='password' name='chave' autocomplete='off' size='50'></label>"
                "<br><span class='dica'>Vai para o cofre do sistema e não volta a aparecer na tela. "
                "Não se aplica ao Claude pelo Claude Code (usa o login dele). "
                f"{'Já há uma chave guardada: em branco, mantém.' if atual and ia.chave_configurada(editando) else ''}</span></p>"
                "<details class='avancado'><summary>Opções avançadas</summary>"
                "<p data-tipos='claude_cli'><label>Caminho do Claude Code (só para o tipo \"Claude pelo Claude Code\")"
                + ajuda("Onde o programa Claude Code está instalado neste computador. Em branco, a ferramenta procura sozinha. "
                        "Ele roda sem ferramentas, numa pasta temporária vazia, e não lê os seus arquivos. Vale a conta em que o Claude "
                        "Code já está conectado (/login); o consumo entra no limite da sua assinatura.")
                + f"<br><input type='text' name='executavel' size='60' placeholder='deixe em branco para procurar sozinho' "
                f"value='{_e(atual.get('executavel', ''))}'></label>"
                "<br><span class='dica'>Em branco, a ferramenta procura sozinha. Vale a conta em que o Claude Code já está "
                "conectado (<code>/login</code>); o consumo entra no limite da sua assinatura. <b>O texto continua indo à "
                "Anthropic</b>, só que pela assinatura e não pela API: confira os termos da sua conta antes de autorizar "
                "dados de clientes.</span></p>"
                f"<p data-tipos='anthropic'><label><input type='checkbox' name='fallback_servidor' value='1' {'checked' if fallback else ''}> "
                "Claude: se o modelo recusar o pedido, deixar a Anthropic tentar outro modelo dela (na mesma chamada)</label>"
                + ajuda("Se o modelo escolhido se recusar a responder, a própria Anthropic tenta outro modelo dela dentro da mesma "
                        "chamada. O texto continua indo só à Anthropic; ninguém mais o recebe.")
                + "</p></details>"
                "<button class='principal'>Salvar provedor</button>"
                + ajuda("Guarda o cadastro (e a chave, no cofre do sistema). Não envia nenhum documento; para testar a conexão use "
                        "o botão Testar na tabela acima.")
                + "</form>" + SCRIPT_TIPOS)

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
             f"externo. Selo atual deste relatório: {_selo(ia.selo_para(perfil, ''))}"
             + ajuda("O selo diz qual motor de IA este relatório usaria agora: \"local\" (no seu computador) ou \"externa: nome do "
                     "provedor\". Cada cliente pode ter um selo diferente; veja a coluna \"Vale agora\" na seção 2.") + "</p>",
             "<div class='caixa'><b>O que fazer agora</b><p>Se você quer manter tudo no seu computador, <b>não precisa fazer nada aqui</b>. "
             "Para usar um serviço externo: (1) cadastre o provedor, (2) na seção 2 escolha-o e autorize os clientes e (3) confirme que "
             "entendeu o que será enviado. Sem os três passos, nada sai do computador.</p>"
             "<p class='dica'>O Claude Code é um serviço externo, <b>não</b> uma IA local: o texto autorizado vai à Anthropic pela sua "
             "assinatura, em vez da API.</p></div>"]

        # 1. provedores cadastrados
        h.append("<h2>1. Provedores cadastrados"
                 + ajuda("Os serviços de IA externos que você já cadastrou. Ter um provedor cadastrado não envia nada: o envio só "
                         "acontece se ele for escolhido na seção 2 e o cliente estiver autorizado.") + "</h2>")
        if catalogo:
            linhas = []
            for chave_id, p in sorted(catalogo.items()):
                linhas.append(
                    f"<tr><td>{_e(p.get('nome', chave_id))}</td><td>{_e(ia.TIPOS.get(p['tipo'], p['tipo']))}</td>"
                    f"<td>{_e(p.get('modelo', ''))}</td><td>{_e(p.get('endereco') or '(padrão do serviço)')}</td>"
                    f"<td>{CHAVE_LOGIN if p['tipo'] == 'claude_cli' else CHAVE_OK if ia.chave_configurada(chave_id) else CHAVE_FALTA}</td>"
                    f"<td><form method='post' action='/ia/testar' style='display:inline'>{oculto}"
                    f"<input type='hidden' name='nome' value='{_e(chave_id)}'><button>Testar</button>"
                    + ajuda("Manda ao provedor uma frase fixa (\"Teste de conexão.\"), sem nenhum dado de cliente, para ver se a chave ou "
                            "o login funciona. Essa frase sai do computador e fica no registro de envios. No Claude Code pode levar alguns "
                            "segundos e usa um pouco da sua assinatura.")
                    + f"</form> <a href='/ia?editar={_e(chave_id)}'>editar</a>"
                    + ajuda("Abre os dados deste provedor no formulário abaixo para você mudar. A chave guardada nunca aparece; "
                            "deixá-la em branco mantém a atual.")
                    + f" <form method='post' action='/ia/remover' style='display:inline' "
                    "onsubmit=\"return confirm('Remover este provedor? A chave guardada no cofre será apagada e não há como desfazer.')\">"
                    f"{oculto}<input type='hidden' name='nome' value='{_e(chave_id)}'><button>Remover</button>"
                    + ajuda("Tira o provedor da lista e esvazia a chave dele no cofre do sistema. Se este relatório usava esse provedor, "
                            "volta a usar a IA local. Não há como desfazer; para usá-lo de novo, cadastre outra vez.")
                    + "</form></td></tr>")
            h.append("<table class='ia'><tr><th>Nome</th><th>Tipo</th><th>Modelo</th><th>Endereço</th><th>Chave"
                     + ajuda("\"guardada ✓\": há uma chave no cofre do sistema. \"sem chave\": falta cadastrar a chave. \"login do Claude "
                             "Code\": este tipo não usa chave, vale a conta em que o Claude Code já está conectado.")
                     + "</th><th></th></tr>"
                     + "".join(linhas) + "</table>"
                     "<p class='dica'>Testar envia só a frase \"Teste de conexão.\" (nenhum dado de cliente) e fica no registro de envios.</p>")
        else:
            h.append("<div class='vazio'>Nenhum provedor externo cadastrado: tudo roda na IA local.</div>")
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
            "<h2>2. O que este relatório usa"
            + ajuda("Aqui você escolhe qual motor faz os resumos deste relatório e quais clientes autorizam o envio de texto a um "
                    "provedor externo. Cada relatório decide sozinho; nada vale para os outros relatórios.") + "</h2>"
            f"<form class='caixa' method='post' action='/ia/consentimento'>{oculto}"
            f"<p><label>Provedor"
            + ajuda("\"Local\" é a IA no seu computador: nada sai. Escolher um provedor externo só vale para os clientes autorizados "
                    "abaixo; para os demais, o programa continua usando a IA local. Se o provedor falhar, também volta sozinho "
                    "para a IA local.")
            + f"<br><select name='provedor'><option value='local' {'selected' if escolhido == 'local' else ''}>"
            f"Local (no meu computador)</option>{opcoes}</select></label></p>"
            "<div class='alerta'><b>O que sai do computador</b> se você autorizar: o <b>texto extraído</b> dos documentos do processo "
            "(trechos de até cerca de 9.000 caracteres por documento), mais o tipo do documento, quem o apresentou e o lado do cliente. "
            "<b>Não sai</b>: print de tela, certificado digital, senha, segredo do autenticador, caminhos de arquivo, planilhas e a "
            "carteira. Com \"pseudônimos\" ligado, nomes das partes, CPF, CNPJ, e-mail e número de processo são trocados por "
            "marcadores antes do envio (e devolvidos no resultado, só aqui). Isso reduz o risco, <b>não o elimina</b>: um nome escrito "
            "de forma diferente da cadastrada pode passar. Cada envio fica no registro abaixo (sem o texto).</div>"
            f"<p><label><input type='checkbox' name='pseudonimizar' value='1' "
            f"{'' if cfg_ia.get('pseudonimizar') is False else 'checked'}> Trocar nomes e números por pseudônimos antes de enviar</label>"
            + ajuda("Antes do envio, nomes das partes e dos clientes cadastrados, CPF, CNPJ, e-mail e número de processo viram "
                    "marcadores como [PARTE_1]; a resposta volta com os nomes de volta e o mapa fica só neste computador. "
                    "Reduz o risco, mas não o elimina: um nome escrito de outro jeito pode passar. Recomendado deixar ligado.") + "</p>"
            f"<p><label><input type='checkbox' name='consentimento_externo' value='1' "
            f"{'checked' if cfg_ia.get('consentimento_externo') is True else ''}> Autorizo o envio, <b>para os clientes sem marcação "
            "própria abaixo</b>, ao provedor escolhido</label>"
            + ajuda("Vale como regra geral do relatório: todo cliente que não tiver marcação própria na tabela abaixo passa a ter o "
                    "texto dos documentos enviado ao provedor escolhido, inclusive clientes cadastrados no futuro. Deixe desmarcado "
                    "se prefere autorizar cliente por cliente.") + "</p>"
            + (("<table class='ia'><tr><th>Cliente</th><th>Autorizo o envio"
                + ajuda("Marque só os clientes cujo texto de documentos você aceita enviar ao provedor. A marcação do cliente vale mais "
                        "do que a regra geral do relatório: desmarcado aqui = sem envio, mesmo que a regra geral esteja marcada.")
                + "</th><th>Vale agora"
                + ajuda("O motor que seria usado hoje para este cliente, considerando o que está salvo (não o que você acabou de marcar, "
                        "até clicar em Salvar).") + "</th></tr>" + linhas_cli +
                "</table><p class='dica'>A marcação de cada cliente vale para ele e prevalece sobre a do relatório. "
                "Cliente desmarcado fica sem envio; cliente cadastrado depois segue a marcação do relatório.</p>") if clientes else
               "<p class='dica'>Cadastre clientes em \"Clientes e processos\" para autorizar um a um.</p>")
            + "<p><label><input type='checkbox' name='entendi' value='1'> Entendi que, para os clientes autorizados, o texto dos "
              "documentos será enviado ao provedor escolhido (só necessário para ativar o envio).</label>"
            + ajuda("Confirmação de que você leu o quadro \"O que sai do computador\" e aceita o envio. Sem ela, o programa não salva "
                    "nenhuma autorização para provedor externo. Voltar para a IA local não precisa dela.") + "</p>"
              "<button class='principal'>Salvar</button>"
            + ajuda("Grava a escolha de provedor e as autorizações no perfil deste relatório. Nada é enviado agora: o envio só "
                    "acontece quando os documentos forem resumidos, e apenas para quem estiver autorizado.")
            + "</form>")

        # 3. registro
        envios = ia.registro_de_envios()
        h.append("<h2>3. Registro de envios"
                 + ajuda("O diário de tudo o que já saiu deste computador para um provedor de IA neste relatório (inclusive os testes). "
                         "Guarda o quê e quando, nunca o texto. Fica só aqui e não pode ser apagado por esta tela.") + "</h2>"
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
