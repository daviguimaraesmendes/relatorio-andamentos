"""Login no PJe dos TRTs pela conta do PDPJ (CPF, senha e autenticador), em UMA tentativa.

Regra de ouro: contas do PDPJ bloqueiam com tentativas erradas. Por isso:

- Cada campo (CPF, senha, código do autenticador) é enviado no máximo UMA vez por tentativa; nada é reenviado.
- Se qualquer credencial foi enviada e o login não concluiu, grava uma TRAVA (`projetos/.pdpj_trava.json`) e
  se recusa a tentar de novo até a pessoa liberar na tela Acesso (ou `python pdpj.py --liberar`). Reiniciar o
  programa, o painel ou a coleta não destrava.
- Falha ANTES de enviar qualquer credencial (site fora do ar, tela diferente da esperada, campo não encontrado)
  não trava: nada foi enviado. Mesmo assim não há laço de repetição: uma tentativa e para.
- O código do autenticador é gerado só quando a janela de 30 s tem folga, para não ser enviado já vencido.
- O que fica em diagnóstico é só texto (endereço, mensagem de erro, nomes de campos): nunca valores digitados.

Depois do login, entra pelo MENU do PJe (Consulta -> Consulta Processual), que é o caminho que não pede captcha
(abrir a consulta direto pela URL pede). Só leitura: nada é protocolado nem assinado.

    python pdpj.py --testar [--trt 7]       login completo + entrada na Consulta Processual (uma tentativa)
    python pdpj.py --inspecionar [--trt 7]  só abre a tela de login do PDPJ e lista os campos (não digita nada)
    python pdpj.py --liberar                libera uma nova tentativa depois de uma falha
"""
import datetime
import json
import re
import sys
import time
from pathlib import Path

import acesso
import comum

URL_LOGIN = "https://pje.trt{n}.jus.br/primeirograu/login.seam"
OTP_SELETORES = "input[name='otp'], input#otp, input[autocomplete='one-time-code']"
USUARIO_SELETORES = ("input[name='username'], input#username, input[autocomplete='username'], "
                     "input[name='cpf'], input#cpf, input[name='login']")
SENHA_SELETORES = "input[type='password']"
ERRO_SELETORES = "[role='alert'], .alert-error, .alert, #input-error, .kc-feedback-text, .pf-m-danger, .error, .mat-error"
MARCAS_BLOQUEIO_DO_SITE = re.compile(r"403 ERROR|Request blocked|Access Denied", re.I)
ESPERA_MAX_S = 75


class PdpjErro(RuntimeError):
    """Falha do login do PDPJ. `trava` diz se alguma credencial já tinha sido enviada."""

    def __init__(self, etapa, mensagem, trava=False):
        super().__init__(mensagem)
        self.etapa, self.mensagem, self.trava = etapa, mensagem, trava


# --- trava contra nova tentativa ---------------------------------------------

def arquivo_trava():
    return comum.PROJETOS_DIR / ".pdpj_trava.json"


def trava():
    """{"quando", "etapa", "mensagem"} se uma tentativa falhou e ainda não foi liberada; senão None."""
    try:
        dados = json.loads(arquivo_trava().read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {"quando": "", "etapa": "?", "mensagem": "trava ilegível"}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"quando": "", "etapa": "?", "mensagem": "trava ilegível: libere para tentar de novo"}


def travar(etapa, mensagem):
    comum.PROJETOS_DIR.mkdir(parents=True, exist_ok=True)
    arquivo_trava().write_text(json.dumps(
        {"quando": datetime.datetime.now().isoformat(timespec="seconds"), "etapa": etapa, "mensagem": mensagem[:300]},
        ensure_ascii=False), encoding="utf-8")


def liberar():
    arquivo_trava().unlink(missing_ok=True)


def pausa_para_janela_do_totp(minimo_s=6, agora=time.time, dormir=time.sleep):
    """Espera a próxima janela de 30 s se o código atual vence em menos de `minimo_s` segundos."""
    restante = 30 - (agora() % 30)
    if restante < minimo_s:
        dormir(restante + 1)
        return True
    return False


# --- o navegador (Playwright) atrás de uma interface pequena, para os testes ---

class Navegador:
    def __init__(self, page):
        self.page = page

    def abrir(self, url):
        self.page.goto(url, timeout=45000, wait_until="load")

    def url(self):
        return self.page.url

    def texto(self):
        try:
            return self.page.inner_text("body")[:4000]
        except Exception:
            return ""

    def esperar(self, ms):
        self.page.wait_for_timeout(ms)

    def clicar_texto(self, *textos):
        for t in textos:
            for loc in (self.page.get_by_role("button", name=re.compile(re.escape(t), re.I)),
                        self.page.get_by_role("link", name=re.compile(re.escape(t), re.I)),
                        self.page.get_by_text(t, exact=False)):
                try:
                    alvo = loc.first
                    if alvo.is_visible():
                        alvo.click(timeout=8000)
                        return True
                except Exception:
                    continue
        return False

    def campo(self, seletores):
        try:
            alvo = self.page.locator(seletores).first
            return alvo if alvo.is_visible() else None
        except Exception:
            return None

    def digitar(self, seletores, valor):
        alvo = self.campo(seletores)
        if alvo is None:
            return False
        alvo.click()
        alvo.press_sequentially(valor, delay=45)
        return True

    def enter(self):
        self.page.keyboard.press("Enter")

    def erro_visivel(self):
        try:
            for el in self.page.locator(ERRO_SELETORES).all()[:5]:
                if el.is_visible():
                    t = " ".join(el.inner_text().split())
                    if t:
                        return t[:200]
        except Exception:
            pass
        return ""

    def campos(self):
        """Só nomes e tipos dos campos da página (nunca valores)."""
        try:
            return self.page.evaluate("""() => [...document.querySelectorAll('input,button,a[role=button]')].map(e =>
                [e.tagName.toLowerCase(), e.type || '', e.name || '', e.id || '',
                 (e.innerText || '').trim().slice(0, 30)].join('|')).slice(0, 25)""")
        except Exception:
            return []

    def nomes_de_cookies(self):
        try:
            return {c["name"] for c in self.page.context.cookies()}
        except Exception:
            return set()

    def menu_consulta_processual(self):
        """Menu do PJe: hambúrguer -> Consulta -> Consulta Processual (abre em outra aba). Devolve o Navegador dela.
        Os itens são os do próprio menu (pje-item-menu-sobreposto), com o texto EXATO: o painel tem outros botões com
        "Consulta" no nome (ex.: Consulta Processos de Terceiros) que não podem ser clicados por engano."""
        page = self.page
        page.locator("#botao-menu").first.click(timeout=10000)
        page.wait_for_timeout(1000)
        page.locator("pje-item-menu-sobreposto .item-center", has_text=re.compile(r"^\s*Consulta\s*$")).first.click(timeout=10000)
        page.wait_for_timeout(1000)
        with page.context.expect_page(timeout=20000) as nova:
            page.locator("pje-item-menu-sobreposto a", has_text=re.compile(r"^\s*Consulta Processual\s*$")).first.click(timeout=10000)
        aba = nova.value
        aba.wait_for_load_state("load", timeout=30000)
        aba.wait_for_timeout(2500)
        return Navegador(aba)


# --- login -------------------------------------------------------------------

def _diag(nav, etapa, mensagem, extra=None):
    """Só texto, sem valores digitados: endereço (sem query), mensagem e nomes dos campos."""
    try:
        pasta = comum.DIAG_DIR
        pasta.mkdir(parents=True, exist_ok=True)
        dados = {"quando": datetime.datetime.now().isoformat(timespec="seconds"), "etapa": etapa, "mensagem": mensagem,
                 "url": nav.url().split("?")[0], "campos": nav.campos(), **(extra or {})}
        (pasta / f"pdpj_{etapa}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _logado(nav):
    u = nav.url()
    return "/pjekz/" in u and "acesso-negado" not in u


def inspecionar(nav, trt=7):
    """Abre a tela de login do PDPJ e lista os campos. Não digita nada, não trava."""
    nav.abrir(URL_LOGIN.format(n=trt))
    nav.esperar(3000)
    if MARCAS_BLOQUEIO_DO_SITE.search(nav.texto()):
        raise PdpjErro("site", "O site do TRT bloqueou o acesso desta máquina (erro 403). Tente de outra rede ou mais tarde.")
    if _logado(nav):
        return {"ok": True, "etapa": "inspecionar", "mensagem": "Já havia uma sessão aberta; nada a inspecionar."}
    if not nav.clicar_texto("Entrar com PDPJ", "PDPJ"):
        _diag(nav, "inspecionar", "Botão \"Entrar com PDPJ\" não encontrado.")
        raise PdpjErro("botao", "Não achei o botão \"Entrar com PDPJ\" na página do TRT.")
    nav.esperar(5000)
    _diag(nav, "inspecionar", "Tela de login do PDPJ")
    return {"ok": True, "etapa": "inspecionar", "mensagem": "Tela de login do PDPJ aberta; campos gravados em diagnosticos/.",
            "campos": nav.campos(), "url": nav.url().split("?")[0]}


def _credenciais():
    cpf, senha, segredo = acesso.obter("pdpj_cpf"), acesso.obter("pdpj_senha"), acesso.obter("pdpj_totp")
    faltam = [n for n, v in (("CPF", cpf), ("senha", senha), ("segredo do autenticador", segredo)) if not v]
    if faltam:
        raise PdpjErro("credenciais", "Falta cadastrar na tela Acesso e escritório (bloco do PDPJ): " + ", ".join(faltam) + ".")
    return cpf, senha, segredo


def entrar(nav, trt=7, consulta=True, relogio=time.time, dormir=time.sleep):
    """Uma tentativa de login no PDPJ e, se `consulta`, a entrada pela Consulta Processual.
    Devolve {"ok", "etapa", "mensagem", "captcha"}; levanta PdpjErro quando falha (com `trava` se enviou credencial)."""
    t = trava()
    if t:
        raise PdpjErro("travado", f"Nova tentativa bloqueada: a última falhou em {t.get('quando', '?')} "
                                  f"({t.get('etapa', '?')}: {t.get('mensagem', '')}). Para não bloquear a conta, só tente de novo "
                                  "depois de conferir os dados e liberar na tela Acesso e escritório.")
    cpf, senha, segredo = _credenciais()
    enviou = []          # o que já foi enviado nesta tentativa

    def falhar(etapa, mensagem):
        if enviou:
            travar(etapa, mensagem)
        _diag(nav, etapa, mensagem, {"enviado": list(enviou)})
        raise PdpjErro(etapa, mensagem, trava=bool(enviou))

    try:
        nav.abrir(URL_LOGIN.format(n=trt))
        nav.esperar(2500)
    except Exception as e:
        falhar("abrir", f"Não consegui abrir a página do TRT ({type(e).__name__}).")
    if MARCAS_BLOQUEIO_DO_SITE.search(nav.texto()):
        falhar("site", "O site do TRT bloqueou o acesso desta máquina (erro 403). Tente de outra rede ou mais tarde.")
    if not _logado(nav):
        try:
            _fazer_login(nav, cpf, senha, segredo, enviou, falhar, relogio, dormir)
        except PdpjErro:
            raise
        except Exception as e:  # noqa: BLE001 - imprevisto (janela fechada, erro do navegador): trava se algo já foi enviado
            falhar("erro", f"Erro inesperado durante o login ({type(e).__name__}).")
    liberar()                                    # entrou: nada a travar
    if not consulta:
        return {"ok": True, "etapa": "login", "mensagem": "Login no PDPJ concluído.", "captcha": None}
    return _entrar_na_consulta(nav)


def _fazer_login(nav, cpf, senha, segredo, enviou, falhar, relogio, dormir):
    """O passo a passo da tela de login. Cada campo é enviado no máximo uma vez (`enviou`)."""
    if not nav.clicar_texto("Entrar com PDPJ", "PDPJ"):
        falhar("botao", "Não achei o botão \"Entrar com PDPJ\" na página do TRT.")
    inicio = relogio()
    while not _logado(nav):
        if relogio() - inicio > ESPERA_MAX_S:
            falhar("tempo", "O login não concluiu a tempo (a tela esperada não apareceu).")
        erro = nav.erro_visivel()
        if erro:
            falhar("recusado", f"O PDPJ recusou ou avisou: {erro}")
        if "otp" not in enviou and nav.campo(OTP_SELETORES) is not None:
            pausa_para_janela_do_totp(dormir=dormir)
            enviou.append("otp")             # marcado ANTES de digitar: nunca reenvia
            if not nav.digitar(OTP_SELETORES, acesso.codigo_totp_atual(segredo)):
                falhar("otp", "Não consegui preencher o código do autenticador.")
            nav.enter()
            nav.esperar(3000)
            continue
        if "senha" not in enviou and nav.campo(SENHA_SELETORES) is not None:
            if "cpf" not in enviou and nav.campo(USUARIO_SELETORES) is not None:
                enviou.append("cpf")
                if not nav.digitar(USUARIO_SELETORES, cpf):
                    falhar("cpf", "Não consegui preencher o CPF.")
            enviou.append("senha")
            if not nav.digitar(SENHA_SELETORES, senha):
                falhar("senha", "Não consegui preencher a senha.")
            nav.enter()
            nav.esperar(3000)
            continue
        if "cpf" not in enviou and nav.campo(SENHA_SELETORES) is None and nav.campo(USUARIO_SELETORES) is not None:
            enviou.append("cpf")
            if not nav.digitar(USUARIO_SELETORES, cpf):
                falhar("cpf", "Não consegui preencher o CPF.")
            nav.enter()
            nav.esperar(3000)
            continue
        nav.esperar(700)


def _entrar_na_consulta(nav):
    """Menu do PJe -> Consulta -> Consulta Processual. Falhar aqui NÃO trava (o login já deu certo)."""
    try:
        aba = nav.menu_consulta_processual()
    except Exception as e:
        aba = None
        motivo = type(e).__name__
    else:
        motivo = "o menu não mostrou Consulta > Consulta Processual"
    if aba is None:
        _diag(nav, "consulta", f"Não consegui abrir a Consulta Processual pelo menu ({motivo}).")
        return {"ok": False, "etapa": "consulta", "captcha": None,
                "mensagem": f"Login feito, mas não consegui abrir a Consulta Processual pelo menu ({motivo})."}
    captcha = "/captcha" in aba.url() or bool(re.search(r"caracteres exibidos na imagem|captcha", aba.texto()[:600], re.I))
    token = "captchaToken" in aba.nomes_de_cookies()
    if captcha:
        _diag(aba, "consulta", "A Consulta Processual pediu captcha mesmo pela entrada do menu.")
        return {"ok": False, "etapa": "consulta", "captcha": True,
                "mensagem": "Login feito, mas a Consulta Processual pediu captcha mesmo entrando pelo menu."}
    return {"ok": True, "etapa": "consulta", "captcha": False, "token_de_consulta": token,
            "mensagem": "Login feito e Consulta Processual aberta sem captcha."}


# --- linha de comando (o painel chama por aqui) ---------------------------------

def _argumento(args, nome, padrao):
    return int(args[args.index(nome) + 1]) if nome in args else padrao


def principal(args):
    if "--liberar" in args:
        liberar()
        print("Trava removida: uma nova tentativa é permitida.")
        return 0
    trt = _argumento(args, "--trt", 7)
    t = trava()
    if t and "--testar" in args:
        print(f"BLOQUEADO: a última tentativa falhou em {t.get('quando', '?')} ({t.get('etapa', '?')}: {t.get('mensagem', '')}). "
              "Nada foi tentado. Confira os dados, e libere na tela Acesso e escritório para tentar de novo.")
        return 2
    from playwright.sync_api import sync_playwright
    import janela
    with sync_playwright() as p:
        browser, context = janela.abrir_navegador(p)
        try:
            page = context.new_page()
            janela.mostrar(page)                 # a pessoa acompanha na tela
            nav = Navegador(page)
            if "--inspecionar" in args:
                r = inspecionar(nav, trt)
                print(r["mensagem"])
                for c in r.get("campos", []):
                    print("  campo:", c)
                return 0
            if "--testar" in args:
                r = entrar(nav, trt)
                print(("ACESSO PDPJ OK: " if r["ok"] else "ATENÇÃO: ") + r["mensagem"])
                return 0 if r["ok"] else 1
            print(__doc__)
            return 0
        except PdpjErro as e:
            print(f"FALHOU ({e.etapa}): {e.mensagem}")
            if e.trava:
                print("Credenciais já tinham sido enviadas, então NENHUMA nova tentativa será feita sozinha. "
                      "Confira os dados e libere na tela Acesso e escritório.")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
