"""Acesso e escritório (vale para todos os relatórios): senha do certificado, segredo do
autenticador, identificadores do escritório e teste de acesso (/acesso)."""
import html
import re
from pathlib import Path

from flask import request

import comum
from painel.base import TAREFA, _ir, _msg, _tarefa_rodando, ajuda


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.route("/acesso", methods=["GET", "POST"])
    def pagina_acesso():
        import acesso
        cfg = comum.config()  # config.json ou, na primeira vez, o exemplo
        if request.method == "POST":
            token_ok()
            msgs = []
            senha = request.form.get("cert_senha", "")
            segredo = re.sub(r"\s", "", request.form.get("totp_secret", "")).upper()
            if senha:
                acesso.guardar("cert_senha", senha)
                msgs.append("Senha do certificado guardada no cofre do sistema.")
            if segredo:
                if not acesso.segredo_totp_valido(segredo):
                    return _ir("/acesso", "O segredo do autenticador não é válido (letras A-Z e números 2-7). Nada foi salvo.\n"
                                          "Copie de novo o código que o jus.br mostra em \"Não foi possível ler o QR Code?\" e cole inteiro, sem o QR Code.")
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
                + f"<p>{agora}</p></div>"
                f"<form class='caixa' method='post'>{oculto}"
                "<p class='dica'>Os dois segredos abaixo vão direto para o cofre do sistema (Keychain no Mac, Gerenciador "
                "de Credenciais no Windows). Não ficam em arquivo e não voltam a aparecer na tela. Para trocar, digite de novo; "
                "em branco, mantém o que está guardado.</p>"
                f"<p><label>Senha (PIN) do certificado digital, a mesma que você digita no PJe Office: {ok(st['cert_senha'])}"
                + ajuda("Serve para a ferramenta digitar a senha do certificado no PJe Office quando entra no jus.br. Fica no cofre do "
                        "sistema, não em arquivo, e nunca é mostrada de volta. Só sai do computador pelo próprio login no jus.br.")
                + "<br><input type='password' name='cert_senha' autocomplete='off' size='30' placeholder='deixe em branco para manter'></label></p>"
                f"<p><label>Segredo do autenticador do jus.br (código de 16 a 32 letras e números): {ok(st['totp_secret'])}"
                + ajuda("É o código em texto que o jus.br mostra quando você cadastra o aplicativo autenticador (opção \"Não foi possível "
                        "ler o QR Code?\"). Com ele a ferramenta gera sozinha o código de 6 dígitos do login. Trate como senha: fica no cofre "
                        "do sistema e nunca é mostrado de volta.")
                + "<br><input type='password' name='totp_secret' autocomplete='off' size='40' placeholder='deixe em branco para manter'></label>"
                + (f"<br><span class='dica'>Código de agora, gerado com o segredo guardado: <b>{codigo}</b>. "
                   "Confira se é o mesmo do app autenticador do seu celular."
                   + ajuda("Se o número for igual ao do app do celular, o segredo está certo. Se for diferente, digite o segredo de novo "
                           "(ou confira se a hora do computador está certa).") + "</span>" if codigo else "") + "</p>"
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
