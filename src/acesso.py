"""Login no jus.br com certificado digital (PJe Office Pro) e código do
autenticador (TOTP), sem depender de outra ferramenta.

Segredos: a senha do certificado e o segredo TOTP ficam no cofre do sistema
(Keychain no Mac, Gerenciador de Credenciais no Windows), via `keyring`, sob o
serviço "jusbr-autologin" (o mesmo do jusbr-autologin: quem já usa aquela
ferramenta não precisa cadastrar de novo). São informados uma vez, na tela
Acesso do painel, e nunca aparecem em arquivo, log ou tela.

O diálogo "Informe a senha" do PJe Office é um programa Java fora do navegador:
no Mac é preenchido por AppleScript; no Windows, por pywinauto.
"""
import os
import platform
import re
import subprocess
import sys
import time

SERVICO = "jusbr-autologin"
MAC = sys.platform == "darwin"
WINDOWS = sys.platform.startswith("win")
TITULO_DIALOGO = "Informe a senha"
OTP_SELETORES = "input[name='otp'], input#otp, input[autocomplete='one-time-code']"
LOGIN_MARKER = "Sair do portal"


# --- cofre do sistema --------------------------------------------------------

def obter(chave):
    try:
        import keyring
        return keyring.get_password(SERVICO, chave)
    except Exception:
        return None


def guardar(chave, valor):
    import keyring
    keyring.set_password(SERVICO, chave, valor)


def situacao():
    """O que já está configurado (sem revelar nada)."""
    return {"cert_senha": bool(obter("cert_senha")), "totp_secret": bool(obter("totp_secret"))}


def codigo_totp_atual(segredo=None):
    """Código de 6 dígitos do momento, para a pessoa conferir com o app do celular."""
    import pyotp
    segredo = segredo or obter("totp_secret")
    return pyotp.TOTP(re.sub(r"\s", "", segredo).upper()).now() if segredo else None


def segredo_totp_valido(segredo):
    try:
        codigo_totp_atual(segredo)
        return True
    except Exception:
        return False


# --- diálogo do PJe Office ---------------------------------------------------

def _dialogo_aberto():
    if MAC:
        script = f'''tell application "System Events"
            if exists process "java" then
                tell process "java" to return exists window "{TITULO_DIALOGO}"
            end if
            return false
        end tell'''
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        return r.stdout.strip() == "true"
    if WINDOWS:
        try:
            from pywinauto import Desktop
            return Desktop(backend="win32").window(title_re=f".*{TITULO_DIALOGO}.*").exists(timeout=0.5)
        except Exception:
            return False
    return False


def _preencher_dialogo(senha):
    if MAC:
        script = f'''tell application "System Events"
            tell process "java"
                set frontmost to true
                delay 0.2
                set w to window "{TITULO_DIALOGO}"
                click text field 1 of w
                keystroke (system attribute "PJE_CERT_SENHA")
                click button "OK" of w
            end tell
        end tell'''
        env = dict(os.environ, PJE_CERT_SENHA=senha)  # a senha não aparece na linha de comando
        return subprocess.run(["osascript", "-e", script], env=env, capture_output=True).returncode == 0
    if WINDOWS:
        try:
            from pywinauto import Desktop
            from pywinauto.keyboard import send_keys
            janela = Desktop(backend="win32").window(title_re=f".*{TITULO_DIALOGO}.*")
            janela.set_focus()
            time.sleep(0.3)
            escapada = re.sub(r"([{}+^%~()\[\]])", r"{\1}", senha)  # caracteres especiais do send_keys
            send_keys(escapada, with_spaces=True, pause=0.02)
            send_keys("{ENTER}")
            return True
        except Exception as e:
            print(f"Não consegui preencher o diálogo do PJe Office ({e}).", flush=True)
            return False
    return False


def _clicar_certificado(page):
    for sel in ("text=Seu certificado digital", "text=certificado digital",
                "a:has-text('certificado digital')", "button:has-text('certificado digital')"):
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


def _texto(page):
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def login_automatico(page, limite_dialogo=90):
    """Certificado + TOTP. Volta True se terminou logado."""
    senha, segredo = obter("cert_senha"), obter("totp_secret")
    if not senha:
        print("Senha do certificado não configurada (painel > Acesso).", flush=True)
        return False
    if not _clicar_certificado(page):
        print("Não achei o botão 'Seu certificado digital'.", flush=True)
        return False
    print(f"Aguardando o diálogo do PJe Office (até {limite_dialogo}s)...", flush=True)
    fim = time.time() + limite_dialogo
    while time.time() < fim and not _dialogo_aberto():
        time.sleep(1)
    if not _dialogo_aberto():
        print("O diálogo do PJe Office não apareceu. Confira se o PJe Office está aberto.", flush=True)
        return False
    if not _preencher_dialogo(senha):
        return False
    print("Senha do certificado enviada ao PJe Office.", flush=True)
    # o campo do código do autenticador demora um tempo variável para aparecer
    for _ in range(60):
        if LOGIN_MARKER in _texto(page):
            return True
        try:
            campo = page.locator(OTP_SELETORES).first
            if campo.is_visible():
                if not segredo:
                    print("Segredo TOTP não configurado (painel > Acesso).", flush=True)
                    return False
                campo.click()
                campo.press_sequentially(codigo_totp_atual(segredo), delay=50)
                page.keyboard.press("Enter")
                print("Código do autenticador preenchido.", flush=True)
                page.wait_for_timeout(2500)
                return LOGIN_MARKER in _texto(page)
        except Exception:
            pass
        page.wait_for_timeout(500)
    return LOGIN_MARKER in _texto(page)
