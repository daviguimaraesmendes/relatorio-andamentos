"""Acesso e escritório (vale para todos os relatórios): senha do certificado, segredo do
autenticador, identificadores do escritório e teste de acesso (/acesso)."""
import html
import re
from pathlib import Path

from flask import request

import comum
from painel.base import TAREFA, _ir, _msg, _tarefa_rodando


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
                f"<form class='caixa' method='post'>{oculto}"
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
                f"<form class='caixa' method='post' action='/tarefa'>{oculto}<input type='hidden' name='tipo' value='teste_acesso'>"
                "<b>Testar acesso</b><p class='dica'>Abre o navegador minimizado, entra no jus.br com o certificado e o "
                "autenticador e fecha. O PJe Office precisa estar aberto.</p>"
                f"<button {'disabled' if _tarefa_rodando() else ''}>Testar acesso</button>{log_teste}</form>")
