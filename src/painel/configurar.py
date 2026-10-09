"""Configurar tudo (/configurar): uma tela guiada, em passos, para quem não é técnico informar num só lugar tudo de que a
ferramenta precisa. Uma única página rolável, com a lista dos passos no alto e um selo "pronto ✓ / falta" em cada um.

    1. Seus dados                          seu nome (revisor) e quem assina pelo escritório      -> config.json
    2. Justiça do Trabalho (PDPJ)          CPF, senha e segredo do autenticador do PDPJ          -> cofre do sistema
    3. Justiça Estadual e Federal (jus.br) senha do certificado e segredo do autenticador        -> cofre do sistema
    4. IA que resume os documentos         situação da IA local e botão de instalar (tarefa `ia`)
    5. Testar                              login do PDPJ (UMA tentativa, com trava) e acesso do jus.br

O salvar dos passos 1 a 3 é o mesmo da tela Acesso (`acesso_tela.salvar_acesso`): confere tudo antes, não salva nada se
algo for inválido, campo em branco mantém o que está guardado. Senhas, CPF e segredos NUNCA voltam para a tela, arquivo,
log ou endereço (só o código de 6 dígitos de conferência do autenticador, como na tela Acesso). Os botões de teste e de
instalar usam a tarefa `/tarefa` de sempre (campo `volta` faz a tarefa retornar para cá). O login do PDPJ nunca se repete
sozinho: um clique é uma tentativa, e com a trava ativa o botão fica desligado.

Funciona sem relatório criado (como /acesso). Rotas: GET e POST /configurar."""
import html
from pathlib import Path
from urllib.parse import quote

from flask import redirect, request

import comum
from painel import acesso_tela
from painel.base import TAREFA, _msg, _tarefa_rodando, ajuda

_e = html.escape

ESTILO = """<style>
.cfg-resumo ol{list-style:none;margin:10px 0 0;padding:0;display:grid;gap:6px}
.cfg-resumo li{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;padding:8px 0;border-bottom:1px solid var(--linha)}
.cfg-resumo li:last-child{border-bottom:0}
.cfg-resumo a{font-weight:600;text-decoration:none;flex:1 1 220px}
.cfg-resumo a:hover{text-decoration:underline}
.cfg-passo{scroll-margin-top:80px}
.cfg-passo h2{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;margin:0 0 6px;font-size:19px}
.cfg-num{flex:none;display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;
  background:var(--botao);color:#fff;font-weight:700;font-size:15px}
.cfg-passo.feito .cfg-num{background:var(--verde);color:#fff}
.cfg-campo{margin:14px 0}
.cfg-campo label{display:block;font-weight:600}
.cfg-campo input[type=text],.cfg-campo input[type=password]{width:100%;max-width:460px;margin-top:4px}
.cfg-campo .dica{display:block;margin-top:4px}
.cfg-estado{font-weight:500}
.cfg-passo .sub{margin:14px 0;padding:14px 16px;border:1px solid var(--linha);border-radius:12px;background:var(--sutil)}
.cfg-acoes{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:16px}
.cfg-acoes form{display:inline}
.cfg-linha{margin:6px 0}
</style>"""

# Enquanto uma tarefa roda (instalar a IA, testar o acesso), só os blocos de andamento são atualizados: a página inteira
# não recarrega para não apagar o que a pessoa já digitou. Quando termina, recarrega se não houver nada digitado.
SCRIPT_VIVO = """<script>
(function(){if(!document.querySelector('[data-rodando]'))return;
function sujo(){return [].some.call(document.querySelectorAll('form.dados input,form.dados textarea'),
function(e){return e.type!=='hidden'&&e.value!==e.defaultValue})}
var t=setInterval(function(){fetch('/configurar',{cache:'no-store'}).then(function(r){return r.text()}).then(function(h){
var d=new DOMParser().parseFromString(h,'text/html');
[].forEach.call(document.querySelectorAll('[data-vivo]'),function(el){
var n=d.querySelector('[data-vivo="'+el.getAttribute('data-vivo')+'"]');if(n)el.innerHTML=n.innerHTML});
if(!d.querySelector('[data-rodando]')){clearInterval(t);
if(!sujo())location.reload();else{var a=document.getElementById('cfg-terminou');if(a)a.hidden=false}}
}).catch(function(){})},3000)})();
</script>"""


def _selo(pronto, falta="falta"):
    return ("<span class='selo ok'>pronto ✓</span>" if pronto else f"<span class='selo atencao'>{_e(falta)}</span>")


def _estado_ia():
    """Situação da IA local (o mesmo cálculo da tela IA); qualquer erro vale 'não pronta': nunca derruba a tela."""
    modelo, completo, instalado, baixado = "", False, False, False
    try:
        import ia_local
        import resumir
        modelo = resumir.modelo_escolhido()
        st = ia_local.situacao(modelo)
        instalado, baixado = bool(st["instalado"]), bool(st["modelo_baixado"])
        completo = instalado and baixado
    except Exception:  # noqa: BLE001
        pass
    externa = ""
    if comum.PROJETO:
        try:
            import ia
            selo = ia.selo_para(ia.carregar_perfil(), "")
            externa = selo if selo != "local" else ""
        except Exception:  # noqa: BLE001
            pass
    return {"modelo": modelo, "instalado": instalado, "baixado": baixado, "completo": completo, "externa": externa}


def _codigo(segredo_cofre):
    """Código de 6 dígitos do momento para conferir com o app do celular (None se não houver segredo ou ele for ruim)."""
    import acesso
    if not segredo_cofre:
        return None
    try:
        return acesso.codigo_totp_atual(segredo_cofre)
    except Exception:  # noqa: BLE001
        return None


def _log_vivo(chave, prefixos):
    """O final do log da tarefa atual, se for uma das desta etapa (atualiza sozinho enquanto a tarefa roda)."""
    desc = TAREFA.get("descricao", "") if TAREFA else ""
    if not desc.startswith(prefixos):
        return f"<div data-vivo='{chave}'></div>"
    arquivo = Path(TAREFA["log"])
    texto = arquivo.read_text(encoding="utf-8", errors="replace")[-3000:] if arquivo.exists() else ""
    return f"<div data-vivo='{chave}'><pre class='log'>{_e(texto)}</pre></div>"


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"
    oculto_volta = oculto + "<input type='hidden' name='volta' value='/configurar'>"

    def passo(n, titulo, pronto, ajuda_txt, corpo, falta="falta"):
        return (f"<section class='caixa cfg-passo{' feito' if pronto else ''}' id='passo-{n}' aria-labelledby='titulo-{n}'>"
                f"<h2 id='titulo-{n}'><span class='cfg-num' aria-hidden='true'>{n}</span>{_e(titulo)}{ajuda(ajuda_txt)} {_selo(pronto, falta)}</h2>"
                f"{corpo}</section>")

    def botao_salvar(n):
        return (f"<div class='cfg-acoes'><button class='principal' name='passo' value='{n}'>Salvar e continuar</button>"
                + ajuda("Guarda tudo o que está preenchido nos passos 1, 2 e 3 desta página e leva você ao passo seguinte. "
                        "Campos de senha em branco mantêm o que já estava guardado. Nada é enviado a lugar nenhum agora.")
                + "</div>")

    def pagina(erro=None, form=None):
        import acesso
        import pdpj
        form = form if form is not None else {}
        cfg = comum.config()
        st, pd = acesso.situacao(), acesso.situacao_pdpj()
        revisor = (form.get("revisor") if "revisor" in form else cfg.get("revisor", "")) or ""
        nomes = (form.get("identificadores") if "identificadores" in form
                 else "\n".join(str(x) for x in cfg.get("identificadores_escritorio", []))) or ""
        pronto1 = bool(str(cfg.get("revisor", "")).strip() and any(str(x).strip() for x in cfg.get("identificadores_escritorio", [])))
        pronto2 = all(pd.values())
        pronto3 = all(st.values())
        ia_st = _estado_ia()
        pronto4 = ia_st["completo"] or bool(ia_st["externa"])
        pode_testar_pdpj = pronto2
        prontos = [pronto1, pronto2, pronto3, pronto4]
        rodando = _tarefa_rodando()

        nomes_passos = (("Seus dados", pronto1), ("Justiça do Trabalho (PJe dos TRTs, conta do PDPJ)", pronto2),
                        ("Justiça Estadual e Federal (jus.br, com certificado digital)", pronto3),
                        ("IA que resume os documentos", pronto4))
        lista = "".join(f"<li><a href='#passo-{i}'>{i}. {_e(nome)}</a>{_selo(p)}</li>" for i, (nome, p) in enumerate(nomes_passos, 1))
        lista += (f"<li><a href='#passo-5'>5. Testar</a>"
                  f"{_selo(pode_testar_pdpj or pronto3, 'salve os dados antes')}</li>")
        feitos = sum(prontos)
        resumo = (f"<section class='caixa cfg-resumo' aria-label='Resumo dos passos'><b>{feitos} de 4 passos prontos</b>"
                  + ajuda("Cada passo tem um selo: \"pronto ✓\" quer dizer que os dados já estão guardados neste computador; \"falta\" "
                          "quer dizer que ainda falta preencher. Você pode fazer só os passos de que precisa e voltar quando quiser.")
                  + "<p class='dica'>Preencha na ordem, no seu ritmo. As senhas e códigos vão direto para o cofre do seu computador "
                    "(Chaveiro no Mac, Gerenciador de Credenciais no Windows): não ficam em arquivo e <b>não voltam a aparecer na tela</b>. "
                    "Para trocar um deles, digite de novo; campo em branco mantém o que já está guardado.</p>"
                    f"<ol>{lista}</ol></section>")

        # 1. Seus dados
        p1 = passo(1, "Seus dados", pronto1,
                   "O seu nome aparece em cada aprovação que você faz, para saber quem conferiu. Os nomes do escritório servem para o "
                   "texto dizer \"apresentamos\" nas petições do escritório. Ficam só no arquivo de configuração deste computador.",
                   "<p>Diga quem é você e quem assina pelo escritório. Isso deixa os resumos mais corretos.</p>"
                   "<div class='cfg-campo'><label for='revisor'>Seu nome (fica registrado nas aprovações)</label>"
                   f"<input type='text' id='revisor' name='revisor' autocomplete='off' placeholder='Ex.: Maria Silva' value='{_e(revisor, quote=True)}'></div>"
                   "<div class='cfg-campo'><label for='identificadores'>Quem assina pelo escritório (um por linha: nome completo e número da OAB)"
                   + ajuda("A ferramenta usa estes nomes para escrever \"apresentamos\" quando a petição é do escritório e \"a parte contrária "
                           "apresentou\" nas demais.")
                   + f"</label><textarea id='identificadores' name='identificadores' rows='4' placeholder='Fulano de Tal, OAB 12.345'>{_e(nomes)}</textarea></div>"
                   + botao_salvar(1))

        # 2. PDPJ
        codigo_pdpj = _codigo(acesso.obter("pdpj_totp")) if pd["pdpj_totp"] else None
        p2 = passo(2, "Justiça do Trabalho (PJe dos TRTs, conta do PDPJ)", pronto2,
                   "O programa entra no PJe dos TRTs com a sua conta do PDPJ. Os dados ficam só no cofre deste computador e só são "
                   "digitados no login do PDPJ. A ferramenta apenas lê: nunca protocola nem assina.",
                   "<p>Para acompanhar processos da <b>Justiça do Trabalho</b>, informe a sua conta do PDPJ: CPF, senha e o segredo do "
                   "aplicativo autenticador. A Justiça do Trabalho <b>não usa o certificado digital</b>.</p>"
                   "<p class='dica'>O autenticador do PDPJ é próprio desta conta e <b>não é</b> o do jus.br (passo 3): podem ser de pessoas "
                   "diferentes, cada um com o seu.</p>"
                   f"<div class='cfg-campo'><label for='pdpj_cpf'>CPF da conta do PDPJ <span class='cfg-estado'>{_selo(pd['pdpj_cpf'])}</span></label>"
                   "<input type='password' id='pdpj_cpf' name='pdpj_cpf' autocomplete='off' inputmode='numeric' placeholder='somente números; em branco mantém o guardado'>"
                   "</div>"
                   f"<div class='cfg-campo'><label for='pdpj_senha'>Senha da conta do PDPJ <span class='cfg-estado'>{_selo(pd['pdpj_senha'])}</span></label>"
                   "<input type='password' id='pdpj_senha' name='pdpj_senha' autocomplete='off' placeholder='em branco mantém a guardada'></div>"
                   f"<div class='cfg-campo'><label for='pdpj_totp'>Segredo do autenticador do PDPJ <span class='cfg-estado'>{_selo(pd['pdpj_totp'])}</span>"
                   + ajuda("É o código em texto (16 a 32 letras e números) que o PDPJ mostra quando você cadastra o aplicativo autenticador "
                           "da conta, na opção para digitar o código em vez de ler o QR Code. Com ele a ferramenta gera sozinha o código de "
                           "6 dígitos do login. Trate como senha: vai para o cofre do sistema e nunca é mostrado de volta.")
                   + "</label><input type='password' id='pdpj_totp' name='pdpj_totp' autocomplete='off' placeholder='em branco mantém o guardado'>"
                   "<span class='dica'>Ao cadastrar o autenticador no PDPJ, escolha a opção de não ler o QR Code e copie o código em texto.</span>"
                   + (f"<span class='dica'>Código de agora, gerado com o segredo do PDPJ guardado: <b>{_e(codigo_pdpj)}</b>. "
                      "Confira se é o mesmo do aplicativo autenticador do PDPJ no seu celular."
                      + ajuda("Se o número for igual ao do aplicativo, o segredo está certo. Se for diferente, digite o segredo de novo "
                              "(ou confira se a hora do computador está certa).") + "</span>" if codigo_pdpj else "")
                   + "</div>" + botao_salvar(2))

        # 3. jus.br
        codigo_jus = _codigo(acesso.obter("totp_secret")) if st["totp_secret"] else None
        p3 = passo(3, "Justiça Estadual e Federal (jus.br, com certificado digital)", pronto3,
                   "Serve para a ferramenta entrar no jus.br sozinha, com o seu certificado digital e o código do autenticador. Só é "
                   "preciso para processos fora da Justiça do Trabalho. A senha e o segredo ficam no cofre do sistema.",
                   "<p><b>Só preencha este passo se você acompanha processos fora da Justiça do Trabalho</b> (Justiça Estadual e Federal, "
                   "pelo jus.br). Se acompanha apenas processos trabalhistas, pode pular: a Justiça do Trabalho <b>não usa o certificado</b>.</p>"
                   "<p class='dica'>Para entrar, o PJe Office (o programa do certificado) precisa estar aberto no computador.</p>"
                   f"<div class='cfg-campo'><label for='cert_senha'>Senha (PIN) do certificado digital, a mesma que você digita no PJe Office "
                   f"<span class='cfg-estado'>{_selo(st['cert_senha'])}</span></label>"
                   "<input type='password' id='cert_senha' name='cert_senha' autocomplete='off' placeholder='em branco mantém a guardada'></div>"
                   f"<div class='cfg-campo'><label for='totp_secret'>Segredo do autenticador do jus.br <span class='cfg-estado'>{_selo(st['totp_secret'])}</span>"
                   + ajuda("É o código em texto que o jus.br mostra quando você cadastra o aplicativo autenticador (opção \"Não foi possível "
                           "ler o QR Code?\"). Trate como senha: vai para o cofre do sistema e nunca é mostrado de volta.")
                   + "</label><input type='password' id='totp_secret' name='totp_secret' autocomplete='off' placeholder='em branco mantém o guardado'>"
                   "<span class='dica'>No jus.br, ao cadastrar o autenticador, use \"Não foi possível ler o QR Code?\" e copie o código em texto.</span>"
                   + (f"<span class='dica'>Código de agora, gerado com o segredo do jus.br guardado: <b>{_e(codigo_jus)}</b>. "
                      "Confira se é o mesmo do aplicativo autenticador do jus.br."
                      + ajuda("Se o número for igual ao do aplicativo, o segredo está certo. Se for diferente, digite o segredo de novo "
                              "(ou confira se a hora do computador está certa).") + "</span>" if codigo_jus else "")
                   + "</div>" + botao_salvar(3))

        # 4. IA
        sit = lambda b: "<b style='color:var(--ok)'>pronto ✓</b>" if b else "<b style='color:var(--alerta)'>falta</b>"
        if ia_st["completo"]:
            ia_corpo_botao = "<p><b>A IA local está pronta.</b> Os próximos resumos já usam esta IA, sem tirar documento do computador.</p>"
        else:
            ia_corpo_botao = (f"<form method='post' action='/tarefa' class='cfg-linha'>{oculto_volta}<input type='hidden' name='tipo' value='ia'>"
                              f"<button class='principal' {'disabled' if rodando else ''}>Instalar IA local</button>"
                              + ajuda("Baixa da internet o Ollama (se faltar) e o modelo de resumo, de 2 a 3,5 GB. Só baixa programas: nenhum "
                                      "documento seu sai do computador. Pode levar vários minutos; se a conexão cair, clique de novo e ele continua.")
                              + "</form><p class='dica'>Pode levar vários minutos. No Mac, se o Ollama ainda não estiver instalado, o andamento "
                                "avisa como instalá-lo e você clica de novo.</p>")
        externo = (f"<p class='cfg-linha'>Este relatório usa o provedor externo <b>{_e(ia_st['externa'])}</b>.</p>" if ia_st["externa"] else "")
        ia_link = ("<p><a href='/ia'>Escolher outro provedor de IA</a> (Claude pela API, Claude pelo Claude Code ou um serviço compatível "
                   "com OpenAI)." if comum.PROJETO else
                   "<p class='dica'>Depois de criar um relatório, a tela <b>IA</b> deixa escolher um provedor externo (Claude pela API, "
                   "Claude pelo Claude Code ou um serviço compatível com OpenAI).")
        p4 = passo(4, "IA que resume os documentos", pronto4,
                   "A IA lê o texto dos documentos dos processos e escreve o resumo para você revisar. A IA local roda neste computador. "
                   "Esta etapa é opcional: sem IA, os andamentos são coletados e entram na revisão sem resumo.",
                   "<p>A IA <b>local</b> resume os documentos <b>neste computador</b>: nenhum documento é enviado para a internet. "
                   "Ela ocupa de 2 a 3,5 GB e é instalada só se você clicar.</p>"
                   f"<p class='cfg-linha'>Motor (Ollama): {sit(ia_st['instalado'])}<br>Modelo <b>{_e(ia_st['modelo'] or '?')}</b>: {sit(ia_st['baixado'])}</p>"
                   + externo + _log_vivo("ia", "Instalação da IA") + ia_corpo_botao + ia_link
                   + " <b>Atenção:</b> um provedor externo envia o texto dos documentos autorizados à empresa que mantém o serviço. "
                     "Só acontece se você escolher o provedor e autorizar, cliente por cliente, na tela IA.</p>")

        # 5. Testar
        trava = pdpj.trava()
        bloco_pdpj = acesso_tela._bloco_pdpj(oculto_volta, pdpj, _log_vivo("pdpj", ("Teste de login no PDPJ", "Tela de login do PDPJ")),
                                             embutido=True, pronto=pode_testar_pdpj)
        jus_ok = pronto3
        bloco_jus = (f"<div class='sub'><b>Testar acesso do jus.br</b>"
                     + ajuda("Abre um navegador minimizado, entra no jus.br com o certificado e o autenticador e fecha. É só um login de teste: "
                             "nenhum processo é consultado. O login e o código do autenticador saem do computador direto para o jus.br.")
                     + "<p class='dica'>Só para quem preencheu o passo 3. Entra no jus.br com o certificado e o autenticador. "
                       "O PJe Office precisa estar aberto. Deve terminar com \"ACESSO OK\".</p>"
                     f"<form method='post' action='/tarefa'>{oculto_volta}<input type='hidden' name='tipo' value='teste_acesso'>"
                     f"<button {'disabled' if rodando or not jus_ok else ''}>Testar acesso do jus.br</button></form>"
                     + ("" if jus_ok else "<p class='dica'><b>Teste desligado:</b> falta salvar o passo 3.</p>")
                     + _log_vivo("jus", ("Teste de acesso",)) + "</div>")
        p5 = passo(5, "Testar", pode_testar_pdpj or pronto3,
                   "Confere se os dados salvos entram de verdade. Cada teste de login do PDPJ faz UMA tentativa só e nunca se repete "
                   "sozinho, para não bloquear a sua conta.",
                   "<p>Depois de salvar os passos acima, confira se o login funciona. O teste do PDPJ faz <b>uma única tentativa</b> por "
                   "clique; se falhar, o programa bloqueia novas tentativas até você liberar.</p>" + bloco_pdpj + bloco_jus,
                   falta="salve os dados antes")

        topo_erro = (f"<div class='erro' id='cfg-erro' role='alert' tabindex='-1' style='white-space:pre-line'>{_e(erro)}</div>"
                     "<script>(function(){var e=document.getElementById('cfg-erro');if(e){e.scrollIntoView({block:'center'});e.focus()}})();</script>"
                     if erro else "")
        aviso_trava = ("<div class='alerta'>O login do PDPJ está bloqueado contra novas tentativas (veja o passo 5).</div>" if trava else "")
        formulario = (f"<form class='dados' method='post' action='/configurar'>{oculto}{p1}{p2}{p3}</form>")
        return (cabecalho("configurar", "Configurar tudo") + ESTILO
                + "<div class='cabeca-pagina'><h1>Configurar tudo</h1></div>"
                + _msg() + topo_erro
                + "<p>Um só lugar para informar tudo de que a ferramenta precisa, em passos simples. Você não precisa fazer todos hoje.</p>"
                + "<div id='cfg-terminou' class='info' role='status' hidden>A tarefa terminou. Salve o que digitou e atualize a página "
                  "para ver o resultado.</div>"
                + ("<span data-rodando hidden></span>" if rodando else "")
                + resumo + aviso_trava + formulario + p4 + p5
                + "<p class='dica'>Precisa de um ajuste avançado? A tela <a href='/acesso'>Acesso e escritório</a> continua disponível.</p>"
                + SCRIPT_VIVO)

    @app.get("/configurar")
    def configurar_tela():
        return pagina()

    @app.post("/configurar")
    def configurar_salvar():
        token_ok()
        msgs, erro = acesso_tela.salvar_acesso(request.form)
        if erro:
            return pagina(erro=erro, form=request.form), 400
        atual = request.form.get("passo", "")
        proximo = f"#passo-{int(atual) + 1}" if atual in ("1", "2", "3") else ""
        return redirect("/configurar?msg=" + quote(" ".join(msgs)) + proximo)
