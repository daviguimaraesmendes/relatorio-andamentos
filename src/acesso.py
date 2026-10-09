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


# --- o que deu errado no login (lido por coletor.logar, gravado em diagnosticos/ e mostrado no painel) ---

ULTIMO = {}   # {"passo", "mensagem", "o_que_fazer", "pje_office_aberto", "acessibilidade"} da última falha

ORIENTACAO = {
    "senha": "Cadastre a senha do certificado e o segredo do autenticador em \"Acesso e escritório\".",
    "botao": "A página do jus.br não mostrou o botão \"Seu certificado digital\". Faça o login você mesmo na janela que "
             "apareceu (certificado e código) e a coleta continua.",
    "dialogo": "O PJe Office não abriu o diálogo da senha. Abra o PJe Office (o programa do certificado), deixe-o aberto "
               "e clique em \"Retomar\".",
    "preencher": "O Mac não deixou o programa preencher a senha no PJe Office. Em Ajustes do Sistema > Privacidade e "
                 "Segurança > Acessibilidade, permita o Terminal (ou o aplicativo que abre o painel) e tente de novo.",
    "totp": "O jus.br pediu o código do autenticador, mas ele não está cadastrado. Cadastre o segredo em \"Acesso e escritório\".",
    "confirmacao": "O jus.br não confirmou a entrada: o código do autenticador pode ter sido recusado (relógio do Mac "
                   "desajustado?) ou apareceu uma tela nova. Termine o login na janela que apareceu.",
}


def pje_office_aberto():
    """True/False se for possível saber se o PJe Office está rodando; None se não der para saber."""
    try:
        if MAC:
            return subprocess.run(["pgrep", "-fi", "pjeoffice"], capture_output=True, timeout=5).returncode == 0
        if WINDOWS:
            saida = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10).stdout.lower()
            return "pjeoffice" in saida or "pje office" in saida
    except Exception:
        pass
    return None


def registrar_falha(passo, mensagem, **extra):
    """Guarda por que o login automático não concluiu (sem senha, sem código, sem dado pessoal)."""
    ULTIMO.clear()
    ULTIMO.update(passo=passo, mensagem=mensagem, o_que_fazer=ORIENTACAO.get(passo, ""),
                  pje_office_aberto=pje_office_aberto(), **extra)
    return ULTIMO


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


CHAVES_PDPJ = ("pdpj_cpf", "pdpj_senha", "totp_secret")


def situacao_pdpj():
    """O que já está configurado para o login por CPF e senha no PDPJ/PJe (sem revelar nada). O código do
    autenticador (TOTP) é o mesmo da conta do jus.br: `totp_secret`."""
    return {c: bool(obter(c)) for c in CHAVES_PDPJ}


def cpf_valido(texto):
    """CPF com 11 dígitos e dígitos verificadores corretos (aceita pontos e traço)."""
    d = re.sub(r"\D", "", texto or "")
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if int(d[n]) != (soma * 10 % 11) % 10:
            return False
    return True


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

_PROCURA_JANELA = f'''repeat with w in windows
                    if (name of w) contains "{TITULO_DIALOGO.split()[-1]}" then {{RETORNO}}
                end repeat'''


def _osascript(script, timeout=15):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and re.search(r"assistive|1002|not allowed|n[ãa]o (est[áa] )?autorizad", r.stderr or "", re.I):
        ULTIMO["acessibilidade"] = False  # o Mac barrou o controle do System Events
    return r


def _dialogo_aberto():
    """O diálogo da senha do PJe Office (janela do processo `java` cujo título contém "senha"). Procura por parte do
    título, e não pelo título exato, para não depender de pequenas diferenças entre versões do PJe Office."""
    if MAC:
        script = f'''tell application "System Events"
            if exists process "java" then
                tell process "java"
                    {_PROCURA_JANELA.format(RETORNO="return true")}
                end tell
            end if
            return false
        end tell'''
        try:
            return _osascript(script).stdout.strip() == "true"
        except Exception:
            return False
    if WINDOWS:
        try:
            from pywinauto import Desktop
            return Desktop(backend="win32").window(title_re=f".*{TITULO_DIALOGO}.*").exists(timeout=0.5)
        except Exception:
            return False
    return False


def janelas_do_pje_office():
    """Títulos das janelas abertas do PJe Office (processo `java`), para o diagnóstico quando o diálogo não aparece:
    mostram se o título é outro ou se há outra janela (aviso, atualização) na frente. Só títulos, nada pessoal."""
    if not MAC:
        return []
    script = '''tell application "System Events"
        if not (exists process "java") then return ""
        set nomes to {}
        tell process "java"
            repeat with w in windows
                set end of nomes to (name of w)
            end repeat
        end tell
        set AppleScript's text item delimiters to "|"
        return nomes as text
    end tell'''
    try:
        return [t.strip() for t in _osascript(script).stdout.strip().split("|") if t.strip()][:10]
    except Exception:
        return []


def liberar_permissao_do_navegador():
    """O Chrome mostra, ao clicar em "Seu certificado digital", um aviso NATIVO ("Acessar outros apps e serviços neste
    dispositivo") com o botão "Permitir". Enquanto ele está aberto o PJe Office nunca é chamado e o diálogo da senha
    não aparece: foi a causa do login automático que "não funcionava" (a ferramenta antiga jusbr-autologin já clicava
    nele). Clica em Permitir nas janelas do navegador da automação (Chrome for Testing / Chromium), nunca no Chrome
    pessoal da pessoa. True se clicou."""
    if not MAC:
        return False
    script = '''tell application "System Events"
        repeat with proc in (every process whose name is "Google Chrome for Testing" or name is "Chromium")
            repeat with wIdx from 1 to (count of windows of proc)
                try
                    set todos to entire contents of window wIdx of proc
                    repeat with el in todos
                        try
                            if role of el is "AXButton" and (description of el is "Permitir" or description of el is "Allow") then
                                click el
                                return "OK"
                            end if
                        end try
                    end repeat
                end try
            end repeat
        end repeat
    end tell
    return "NAO"'''
    try:
        return _osascript(script, timeout=12).stdout.strip() == "OK"
    except Exception:
        return False


def _preencher_dialogo(senha):
    if MAC:
        script = f'''tell application "System Events"
            tell process "java"
                set frontmost to true
                delay 0.2
                set alvo to missing value
                repeat with w in windows
                    if (name of w) contains "{TITULO_DIALOGO.split()[-1]}" then
                        set alvo to w
                        exit repeat
                    end if
                end repeat
                if alvo is missing value then error "diálogo da senha não encontrado"
                click text field 1 of alvo
                keystroke (system attribute "PJE_CERT_SENHA")
                click button "OK" of alvo
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
    ULTIMO.clear()
    senha, segredo = obter("cert_senha"), obter("totp_secret")
    if not senha:
        print("Senha do certificado não configurada (painel > Acesso).", flush=True)
        registrar_falha("senha", "Senha do certificado não configurada.")
        return False
    if not _clicar_certificado(page):
        print("Não achei o botão 'Seu certificado digital'.", flush=True)
        registrar_falha("botao", "Não achei o botão \"Seu certificado digital\" na página do jus.br.")
        return False
    print(f"Aguardando o diálogo do PJe Office (até {limite_dialogo}s)...", flush=True)
    fim = time.time() + limite_dialogo
    rodada = 0
    while time.time() < fim and not _dialogo_aberto():
        if rodada % 2 == 0 and liberar_permissao_do_navegador():
            print("Permissão do navegador para abrir o PJe Office concedida.", flush=True)
        rodada += 1
        time.sleep(1)
    if not _dialogo_aberto():
        print("O diálogo do PJe Office não apareceu. Confira se o PJe Office está aberto.", flush=True)
        extra = {"acessibilidade": False} if ULTIMO.get("acessibilidade") is False else {}
        janelas = janelas_do_pje_office()
        if janelas:
            extra["janelas_do_pje"] = janelas
        registrar_falha("preencher" if extra else "dialogo",
                        "O Mac barrou o acesso ao PJe Office (Acessibilidade)." if extra
                        else f"O diálogo \"{TITULO_DIALOGO}\" do PJe Office não apareceu em {limite_dialogo} s.", **extra)
        return False
    if not _preencher_dialogo(senha):
        registrar_falha("preencher", "Não consegui preencher a senha no diálogo do PJe Office.")
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
                    registrar_falha("totp", "O jus.br pediu o código do autenticador, que não está cadastrado.")
                    return False
                campo.click()
                campo.press_sequentially(codigo_totp_atual(segredo), delay=50)
                page.keyboard.press("Enter")
                print("Código do autenticador preenchido.", flush=True)
                page.wait_for_timeout(2500)
                if LOGIN_MARKER in _texto(page):
                    return True
                registrar_falha("confirmacao", "O código do autenticador foi enviado, mas o jus.br não confirmou a entrada.")
                return False
        except Exception:
            pass
        page.wait_for_timeout(500)
    if LOGIN_MARKER in _texto(page):
        return True
    registrar_falha("confirmacao", "Depois da senha do certificado o jus.br não pediu o código nem confirmou a entrada em 30 s.")
    return False
