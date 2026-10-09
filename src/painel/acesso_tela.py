"""Acesso e escritório (vale para todos os relatórios): senha do certificado, segredo do
autenticador, identificadores do escritório e teste de acesso (/acesso)."""
import html
import re
from pathlib import Path

from flask import request

import comum
from painel.base import TAREFA, _ir, _msg, _tarefa_rodando, ajuda, volta_para


def salvar_acesso(form):
    """Salva o que veio do formulário de acesso (usada por /acesso e por /configurar). Devolve `(mensagens, erro)`.

    Primeiro confere TUDO; se algo for inválido, não grava nada e devolve `([], texto do que fazer)`. Campo de segredo em
    branco mantém o que já está no cofre. Senhas e segredos vão só para o cofre do sistema (nunca para arquivo, log ou
    mensagem); os nomes do escritório e o do revisor vão para o config.json."""
    import acesso
    senha = form.get("cert_senha", "")
    segredo = re.sub(r"\s", "", form.get("totp_secret", "")).upper()
    cpf = form.get("pdpj_cpf", "").strip()
    senha_pdpj = form.get("pdpj_senha", "")
    segredo_pdpj = re.sub(r"\s", "", form.get("pdpj_totp", "")).upper()
    if cpf and not acesso.cpf_valido(cpf):
        return [], "O CPF não é válido (11 dígitos). Nada foi salvo."
    if segredo_pdpj and not acesso.segredo_totp_valido(segredo_pdpj):
        return [], ("O segredo do autenticador do PDPJ não é válido (letras A-Z e números 2-7). Nada foi salvo.\n"
                    "Copie de novo o código em texto que o PDPJ mostra ao cadastrar o autenticador e cole inteiro.")
    if segredo and not acesso.segredo_totp_valido(segredo):
        return [], ("O segredo do autenticador não é válido (letras A-Z e números 2-7). Nada foi salvo.\n"
                    "Copie de novo o código que o jus.br mostra em \"Não foi possível ler o QR Code?\" e cole inteiro, sem o QR Code.")
    msgs = []
    if senha:
        acesso.guardar("cert_senha", senha)
        msgs.append("Senha do certificado guardada no cofre do sistema.")
    if cpf:
        acesso.guardar("pdpj_cpf", re.sub(r"\D", "", cpf))
        msgs.append("CPF do PDPJ guardado no cofre do sistema.")
    if senha_pdpj:
        acesso.guardar("pdpj_senha", senha_pdpj)
        msgs.append("Senha do PDPJ guardada no cofre do sistema.")
    if segredo_pdpj:
        acesso.guardar("pdpj_totp", segredo_pdpj)
        msgs.append("Segredo do autenticador do PDPJ guardado no cofre do sistema.")
    if segredo:
        acesso.guardar("totp_secret", segredo)
        msgs.append("Segredo do autenticador guardado no cofre do sistema.")
    cfg = comum.config()  # config.json ou, na primeira vez, o exemplo
    cfg["identificadores_escritorio"] = [l.strip() for l in form.get("identificadores", "").splitlines() if l.strip()]
    cfg["revisor"] = form.get("revisor", "").strip()
    comum.save_json(comum.CONFIG_FILE, cfg)
    msgs.append("Dados do escritório salvos.")
    return msgs, None


def _bloco_pdpj(oculto, pdpj, log_html, embutido=False, pronto=True):
    """Testes do login no PDPJ: sempre UMA tentativa, e nenhuma nova depois de falha com credencial enviada.
    `embutido`: sem moldura própria (para dentro de outra caixa); `pronto=False`: faltam dados, o teste fica desligado."""
    t = pdpj.trava()
    bloqueado = "disabled" if _tarefa_rodando() or t or not pronto else ""
    faltam = ("" if pronto else "<p class='dica'><b>Teste desligado:</b> falta salvar o CPF, a senha e o segredo do autenticador "
                                "do PDPJ (passo 2).</p>")
    aviso = ""
    if t:
        aviso = (f"<div class='alerta'><b>Nova tentativa bloqueada.</b> A última falhou em {html.escape(str(t.get('quando', '?')))} "
                 f"({html.escape(str(t.get('etapa', '?')))}: {html.escape(str(t.get('mensagem', '')))}). Para não bloquear a conta do "
                 "PDPJ, nada será tentado sozinho. Confira CPF, senha e autenticador acima, salve, e só então libere.</div>"
                 f"<form method='post' action='/acesso/pdpj/liberar' style='display:inline'>{oculto}"
                 "<button>Liberar nova tentativa</button>"
                 + ajuda("Remove o bloqueio de segurança. Faça isso só depois de conferir os dados do PDPJ: uma senha errada repetida "
                         "pode bloquear a sua conta.") + "</form>")
    return (f"<div class='{'sub' if embutido else 'caixa'}'><b>Testar o login no PDPJ (PJe do TRT7)</b>"
            + ajuda("Abre o navegador do programa, entra no PJe do TRT7 com o CPF, a senha e o autenticador do PDPJ e abre a Consulta "
                    "Processual pelo menu. Só lê: não consulta processo, não protocola, não assina. Os dados vão só ao PDPJ.")
            + "<p class='dica'>O teste faz <b>uma única tentativa</b>. Se falhar depois de enviar as credenciais, o programa para e "
              "bloqueia novas tentativas até você liberar, para não bloquear a sua conta.</p>"
            f"<form method='post' action='/tarefa' style='display:inline'>{oculto}<input type='hidden' name='tipo' value='ver_login_pdpj'>"
            f"<button {'disabled' if _tarefa_rodando() else ''}>Só ver a tela de login (não digita nada)</button>"
            + ajuda("Abre a página de login do PDPJ e anota quais campos ela tem, sem digitar nada. Serve para conferir que a página "
                    "abre neste computador, antes de testar com as suas credenciais. Não há risco de bloqueio.")
            + "</form> "
            f"<form method='post' action='/tarefa' style='display:inline' onsubmit=\"return confirm('Testar o login agora? "
            "Será feita UMA tentativa com o CPF, a senha e o autenticador salvos. Se falhar, nada será repetido.')\">"
            f"{oculto}<input type='hidden' name='tipo' value='teste_pdpj'>"
            f"<button class='principal' {bloqueado}>Testar login (uma tentativa)</button>"
            + ajuda("Faz o login de verdade, uma vez. Se der certo, termina com \"ACESSO PDPJ OK\". Se falhar, para e bloqueia novas "
                    "tentativas até você liberar. Acompanhe pela janela do navegador que abre.")
            + f"</form>{faltam}{aviso}{log_html}</div>")


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.post("/acesso/pdpj/liberar")
    def liberar_pdpj():
        token_ok()
        import pdpj
        pdpj.liberar()
        return _ir(volta_para("/acesso"), "Nova tentativa de login no PDPJ liberada. Confira os dados antes de testar de novo.")

    @app.route("/acesso", methods=["GET", "POST"])
    def pagina_acesso():
        import acesso
        cfg = comum.config()  # config.json ou, na primeira vez, o exemplo
        if request.method == "POST":
            token_ok()
            msgs, erro = salvar_acesso(request.form)
            return _ir("/acesso", erro or " ".join(msgs))
        st = acesso.situacao()
        pdpj = acesso.situacao_pdpj()
        codigo = acesso.codigo_totp_atual() if st["totp_secret"] else None
        codigo_pdpj = acesso.codigo_totp_atual(acesso.obter("pdpj_totp")) if pdpj["pdpj_totp"] else None
        import pdpj as pdpj_login
        log_teste = log_teste_pdpj = ""
        desc = TAREFA.get("descricao", "") if TAREFA else ""
        if desc.startswith(("Teste de acesso", "Teste de login no PDPJ", "Tela de login do PDPJ")):
            texto = Path(TAREFA["log"]).read_text(encoding="utf-8", errors="replace")[-3000:] if Path(TAREFA["log"]).exists() else ""
            rodando = _tarefa_rodando()
            log = (f"<pre class='log'>{html.escape(texto)}</pre>"
                   + ("<script>setTimeout(()=>location.reload(),3000)</script>" if rodando else ""))
            if desc.startswith("Teste de acesso"):
                log_teste = log
            else:
                log_teste_pdpj = log
        ok = lambda b: "<b style='color:var(--ok)'>configurada ✓</b>" if b else "<b style='color:var(--alerta)'>não configurada</b>"
        if all(st.values()):
            agora = ("Tudo configurado. Confira o código abaixo e clique em <b>Testar acesso</b> uma vez (com o PJe Office aberto) "
                     "para ter certeza de que o login funciona.")
        else:
            agora = ("Faltam dados para a ferramenta entrar no jus.br sozinha. Preencha a senha do certificado e o segredo do "
                     "autenticador, clique em <b>Salvar</b> e depois em <b>Testar acesso</b>.")
        return (cabecalho("acesso", "Acesso e escritório") + "<h1>Acesso e escritório</h1>" + _msg() +
                f"<div class='caixa'><b>O que fazer agora</b>"
                + ajuda("Esta tela vale para todos os relatórios. Só você mexe nela. As senhas ficam no cofre do seu computador e "
                        "só são usadas para entrar no jus.br e nos TRTs; a ferramenta apenas lê, nunca protocola nem assina.")
                + f"<p>{agora}</p>"
                "<p class='dica'>Prefere ser guiado, passo a passo? Use a tela <a class='pilula' href='/configurar'>Configurar tudo</a>. "
                "Esta tela é para ajustes avançados.</p></div>"
                f"<form class='caixa' method='post'>{oculto}"
                "<p class='dica'>Os dois segredos abaixo vão direto para o cofre do sistema (Keychain no Mac, Gerenciador "
                "de Credenciais no Windows). Não ficam em arquivo e não voltam a aparecer na tela. Para trocar, digite de novo; "
                "em branco, mantém o que está guardado.</p>"
                f"<p><label>Senha (PIN) do certificado digital, a mesma que você digita no PJe Office: {ok(st['cert_senha'])}"
                + ajuda("Serve para a ferramenta digitar a senha do certificado no PJe Office quando entra no jus.br. Fica no cofre do "
                        "sistema, não em arquivo, e nunca é mostrada de volta. Só sai do computador pelo próprio login no jus.br.")
                + "<br><input type='password' name='cert_senha' autocomplete='off' size='30' placeholder='deixe em branco para manter'></label></p>"
                f"<p><label>Segredo do autenticador do <b>jus.br</b> (código de 16 a 32 letras e números): {ok(st['totp_secret'])}"
                + ajuda("É o código em texto que o jus.br mostra quando você cadastra o aplicativo autenticador (opção \"Não foi possível "
                        "ler o QR Code?\"). Com ele a ferramenta gera sozinha o código de 6 dígitos do login. Trate como senha: fica no cofre "
                        "do sistema e nunca é mostrado de volta.")
                + "<br><input type='password' name='totp_secret' autocomplete='off' size='40' placeholder='deixe em branco para manter'></label>"
                + (f"<br><span class='dica'>Código de agora, gerado com o segredo guardado: <b>{codigo}</b>. "
                   "Confira se é o mesmo do app autenticador do seu celular."
                   + ajuda("Se o número for igual ao do app do celular, o segredo está certo. Se for diferente, digite o segredo de novo "
                           "(ou confira se a hora do computador está certa).") + "</span>" if codigo else "") + "</p>"
                "<p class='dica'><b>Login no PJe dos TRTs (conta do PDPJ)</b>: CPF, senha e segredo do autenticador da conta do PDPJ. "
                "É uma conta própria, <b>independente da do jus.br acima</b> (podem ser de pessoas diferentes, com autenticadores diferentes). "
                "Cada pessoa cadastra os seus, só neste computador.</p>"
                f"<p><label>CPF da conta do PDPJ: {ok(pdpj['pdpj_cpf'])}"
                + ajuda("O CPF que você usa para entrar no PJe com \"Entrar com PDPJ\". Fica só no cofre deste computador (não vai para "
                        "arquivo, log nem para o pacote do programa) e não volta a aparecer na tela. Só é digitado no login do PDPJ.")
                + "<br><input type='password' name='pdpj_cpf' autocomplete='off' inputmode='numeric' size='20' "
                  "placeholder='somente números, deixe em branco para manter'></label></p>"
                f"<p><label>Senha da conta do PDPJ: {ok(pdpj['pdpj_senha'])}"
                + ajuda("A senha da conta do PDPJ (a mesma do login com CPF no PJe). Fica no cofre do sistema, nunca em arquivo, e não "
                        "volta a aparecer na tela. Só sai do computador pelo próprio login no PDPJ.")
                + "<br><input type='password' name='pdpj_senha' autocomplete='off' size='30' "
                  "placeholder='deixe em branco para manter'></label></p>"
                f"<p><label>Segredo do autenticador (TOTP) da conta do <b>PDPJ</b> (código de 16 a 32 letras e números): {ok(pdpj['pdpj_totp'])}"
                + ajuda("É o código em texto que o PDPJ mostra quando você cadastra o aplicativo autenticador da conta do PDPJ (opção para "
                        "digitar o código em vez de ler o QR Code). Não é necessariamente o mesmo do jus.br. Com ele a ferramenta gera sozinha "
                        "o código de 6 dígitos do login. Trate como senha: fica no cofre do sistema e nunca é mostrado de volta.")
                + "<br><input type='password' name='pdpj_totp' autocomplete='off' size='40' placeholder='deixe em branco para manter'></label>"
                + (f"<br><span class='dica'>Código de agora, gerado com o segredo do PDPJ guardado: <b>{codigo_pdpj}</b>. "
                   "Confira se é o mesmo do app autenticador do PDPJ no seu celular."
                   + ajuda("Se o número for igual ao do app, o segredo está certo. Se for diferente, digite o segredo de novo "
                           "(ou confira se a hora do computador está certa).") + "</span>" if codigo_pdpj else "") + "</p>"
                "<p><label>Quem assina pelo escritório: um por linha, nome completo e número da OAB "
                "(ex.: <i>Fulano de Tal</i> e <i>12.345</i>)"
                + ajuda("A ferramenta usa estes nomes para escrever \"apresentamos\" quando a petição é do escritório e \"a parte contrária "
                        "apresentou\" nas demais. Fica só no arquivo de configuração deste computador.")
                + "<br>"
                f"<textarea name='identificadores' rows='5' placeholder='Fulano de Tal, OAB 12.345'>"
                f"{html.escape(chr(10).join(cfg.get('identificadores_escritorio', [])))}</textarea>"
                "</label><span class='dica'>Serve para escrever \"apresentamos\" nas petições do escritório e \"a parte contrária "
                "apresentou\" nas demais.</span></p>"
                "<p><label>Seu nome (fica registrado nas aprovações)"
                + ajuda("Aparece em cada andamento que você aprova em Revisar, para saber quem conferiu. Não é usado para mais nada.")
                + f" <input type='text' name='revisor' size='30' placeholder='Ex.: Maria Silva' "
                f"value='{html.escape(cfg.get('revisor', ''))}'></label></p>"
                "<button class='principal'>Salvar</button>"
                + ajuda("Guarda o que você digitou: senha e segredo no cofre do sistema, e os nomes do escritório no arquivo de configuração. "
                        "O que está vazio nas duas primeiras caixas continua como estava; os nomes e o seu nome são sempre trocados pelo que "
                        "estiver nas caixas.")
                + "</form>"
                + _bloco_pdpj(oculto, pdpj_login, log_teste_pdpj) +
                f"<form class='caixa' method='post' action='/tarefa'>{oculto}<input type='hidden' name='tipo' value='teste_acesso'>"
                "<b>Testar acesso</b>"
                + ajuda("Abre um navegador minimizado, entra no jus.br com o certificado e o autenticador e fecha. É só um login de teste: "
                        "nenhum processo é consultado. Por isso o login e o código do autenticador saem do computador, direto para o jus.br.")
                + "<p class='dica'>Abre o navegador minimizado, entra no jus.br com o certificado e o "
                "autenticador e fecha. O PJe Office precisa estar aberto. Deve terminar com \"ACESSO OK\".</p>"
                f"<button {'disabled' if _tarefa_rodando() else ''}>Testar acesso</button>"
                + ajuda("Começa o teste agora. Se aparecer uma janela pedindo ação (captcha ou confirmação), conclua nela. "
                        "O resultado aparece logo abaixo; o teste termina com \"ACESSO OK\" quando deu certo.")
                + f"{log_teste}</form>")
