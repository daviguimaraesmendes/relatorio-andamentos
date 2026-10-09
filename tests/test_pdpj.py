"""Login do PDPJ (src/pdpj.py): uma tentativa só, trava depois de falha com credencial enviada.
Navegador de mentira, cofre falso, sem rede. Dados fictícios.

    python3 -m unittest tests/test_pdpj.py -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import acesso  # noqa: E402
import comum  # noqa: E402
import pdpj  # noqa: E402

PAUSA_REAL = pdpj.pausa_para_janela_do_totp
ALVO_CPF, ALVO_SENHA, ALVO_OTP = pdpj.USUARIO_SELETORES, pdpj.SENHA_SELETORES, pdpj.OTP_SELETORES
LOGIN = "https://pje.trt7.jus.br/primeirograu/login.seam"
PAINEL = "https://pje.trt7.jus.br/pjekz/painel/usuario-externo"


def tela(url, **campos):
    return {"url": url, **campos}


class NavFalso:
    """Telas em sequência. `enter()` passa para a próxima; clicar no botão do PDPJ também."""

    def __init__(self, telas, botao=True, texto_inicial="", consulta=None):
        self.telas, self.i, self.botao, self.texto_inicial = telas, 0, botao, texto_inicial
        self.digitado, self.enters, self.cliques, self.aberturas = [], 0, [], []
        self._consulta = consulta

    @property
    def atual(self):
        return self.telas[min(self.i, len(self.telas) - 1)]

    def abrir(self, url):
        self.aberturas.append(url)

    def url(self):
        return self.atual["url"]

    def texto(self):
        return self.texto_inicial if self.i == 0 else self.atual.get("texto", "")

    def esperar(self, ms):
        pass

    def clicar_texto(self, *textos):
        self.cliques.append(textos)
        if not self.botao:
            return False
        self.i += 1
        return True

    def campo(self, seletores):
        chave = {ALVO_CPF: "usuario", ALVO_SENHA: "senha", ALVO_OTP: "otp"}[seletores]
        return object() if self.atual.get(chave) else None

    def digitar(self, seletores, valor):
        chave = {ALVO_CPF: "usuario", ALVO_SENHA: "senha", ALVO_OTP: "otp"}[seletores]
        if not self.atual.get(chave):
            return False
        self.digitado.append(chave)
        return True

    def enter(self):
        self.enters += 1
        self.i += 1

    def erro_visivel(self):
        return self.atual.get("erro", "")

    def campos(self):
        return ["input|password||senha|"]

    def nomes_de_cookies(self):
        return {"captchaToken"}

    def menu_consulta_processual(self):
        return self._consulta


class Base(unittest.TestCase):
    def setUp(self):
        nome = f"{type(self).__name__}-{self._testMethodName}"
        raiz = TMP / "projetos-pdpj" / nome
        raiz.mkdir(parents=True, exist_ok=True)
        self.salvo = (comum.PROJETOS_DIR, comum.DIAG_DIR)
        comum.PROJETOS_DIR, comum.DIAG_DIR = raiz, raiz / "diag"
        pdpj.liberar()
        self.addCleanup(lambda: setattr(comum, "PROJETOS_DIR", self.salvo[0]))
        self.addCleanup(lambda: setattr(comum, "DIAG_DIR", self.salvo[1]))
        self.cofre = {"pdpj_cpf": "00000000000", "pdpj_senha": "valor-a", "pdpj_totp": "JBSWY3DPEHPK3PXP"}
        for alvo in (mock.patch.object(acesso, "obter", lambda c: self.cofre.get(c)),
                     mock.patch.object(pdpj, "pausa_para_janela_do_totp", lambda **kw: False)):
            alvo.start()
            self.addCleanup(alvo.stop)

    def fluxo_ok(self, **kw):
        """login -> SSO com CPF e senha -> código -> painel."""
        return NavFalso([tela(LOGIN), tela("https://sso.exemplo.invalid/auth", usuario=True, senha=True),
                         tela("https://sso.exemplo.invalid/otp", otp=True), tela(PAINEL)], **kw)


class UmaTentativa(Base):
    def test_login_completo_envia_cada_campo_uma_vez(self):
        nav = self.fluxo_ok()
        r = pdpj.entrar(nav, consulta=False)
        self.assertTrue(r["ok"])
        self.assertEqual(nav.digitado, ["usuario", "senha", "otp"])
        self.assertEqual(nav.enters, 2)
        self.assertIsNone(pdpj.trava())

    def test_senha_errada_trava_e_nunca_reenvia(self):
        nav = NavFalso([tela(LOGIN), tela("https://sso.exemplo.invalid/auth", usuario=True, senha=True),
                        tela("https://sso.exemplo.invalid/auth", usuario=True, senha=True, erro="Credenciais inválidas")])
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        self.assertTrue(ctx.exception.trava)
        self.assertEqual(nav.digitado, ["usuario", "senha"])         # uma vez cada, o campo continuou na tela e não foi reenviado
        self.assertEqual(pdpj.trava()["etapa"], "recusado")

    def test_segunda_chamada_nao_toca_no_navegador(self):
        pdpj.travar("recusado", "Credenciais inválidas")
        nav = self.fluxo_ok()
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        self.assertEqual(ctx.exception.etapa, "travado")
        self.assertEqual((nav.aberturas, nav.cliques, nav.digitado, nav.enters), ([], [], [], 0))

    def test_liberar_permite_tentar_de_novo(self):
        pdpj.travar("recusado", "x")
        pdpj.liberar()
        self.assertTrue(pdpj.entrar(self.fluxo_ok(), consulta=False)["ok"])

    def test_tela_que_nunca_muda_para_depois_do_tempo_e_trava(self):
        nav = NavFalso([tela(LOGIN), tela("https://sso.exemplo.invalid/auth", usuario=True, senha=True)] + [tela("https://sso.exemplo.invalid/x")])
        relogio = iter(range(0, 1000, 20))                            # cada consulta ao relógio avança 20 s
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False, relogio=lambda: next(relogio))
        self.assertEqual(ctx.exception.etapa, "tempo")
        self.assertEqual(nav.digitado, ["usuario", "senha"])
        self.assertIsNotNone(pdpj.trava())

    def test_cpf_primeiro_e_depois_senha(self):
        nav = NavFalso([tela(LOGIN), tela("https://sso.exemplo.invalid/cpf", usuario=True),
                        tela("https://sso.exemplo.invalid/senha", senha=True), tela(PAINEL)])
        self.assertTrue(pdpj.entrar(nav, consulta=False)["ok"])
        self.assertEqual(nav.digitado, ["usuario", "senha"])


class FalhaAntesDeEnviarNaoTrava(Base):
    def test_sem_credencial_nem_abre_o_navegador(self):
        self.cofre.pop("pdpj_senha")
        nav = self.fluxo_ok()
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav)
        self.assertEqual(ctx.exception.etapa, "credenciais")
        self.assertIn("senha", ctx.exception.mensagem)
        self.assertEqual(nav.aberturas, [])
        self.assertIsNone(pdpj.trava())

    def test_botao_do_pdpj_nao_encontrado(self):
        nav = self.fluxo_ok(botao=False)
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav)
        self.assertEqual((ctx.exception.etapa, ctx.exception.trava), ("botao", False))
        self.assertEqual(nav.digitado, [])
        self.assertIsNone(pdpj.trava())

    def test_site_bloqueou_403(self):
        nav = self.fluxo_ok(texto_inicial="403 ERROR The request could not be satisfied. Request blocked.")
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav)
        self.assertEqual(ctx.exception.etapa, "site")
        self.assertEqual((nav.cliques, nav.digitado), ([], []))
        self.assertIsNone(pdpj.trava())

    def test_ja_logado_nao_envia_nada(self):
        nav = NavFalso([tela(PAINEL)])
        self.assertTrue(pdpj.entrar(nav, consulta=False)["ok"])
        self.assertEqual((nav.cliques, nav.digitado, nav.enters), ([], [], 0))


class Consulta(Base):
    def test_consulta_sem_captcha(self):
        aba = NavFalso([tela("https://pje.trt7.jus.br/consultaprocessual/")], texto_inicial="Consulta Processual Número do processo")
        r = pdpj.entrar(self.fluxo_ok(consulta=aba))
        self.assertEqual((r["ok"], r["captcha"], r["etapa"]), (True, False, "consulta"))

    def test_consulta_que_pede_captcha_nao_trava_o_login(self):
        aba = NavFalso([tela("https://pje.trt7.jus.br/consultaprocessual/captcha/detalhe")], texto_inicial="Digite os caracteres exibidos na imagem")
        r = pdpj.entrar(self.fluxo_ok(consulta=aba))
        self.assertEqual((r["ok"], r["captcha"]), (False, True))
        self.assertIsNone(pdpj.trava())

    def test_menu_sem_a_consulta_processual(self):
        r = pdpj.entrar(self.fluxo_ok(consulta=None))
        self.assertFalse(r["ok"])
        self.assertEqual(r["etapa"], "consulta")
        self.assertIsNone(pdpj.trava())


class Inspecionar(Base):
    def test_so_abre_a_tela_e_nao_digita(self):
        nav = self.fluxo_ok()
        r = pdpj.inspecionar(nav)
        self.assertTrue(r["ok"])
        self.assertEqual((nav.digitado, nav.enters), ([], 0))
        self.assertIsNone(pdpj.trava())


class TotpEDiagnostico(Base):
    def test_espera_a_proxima_janela_quando_falta_pouco(self):
        dormiu = []
        self.assertTrue(PAUSA_REAL(agora=lambda: 90 + 27.5, dormir=dormiu.append))     # faltam 2,5 s da janela de 30 s
        self.assertEqual(dormiu, [3.5])
        self.assertFalse(PAUSA_REAL(agora=lambda: 90 + 5, dormir=dormiu.append))

    def test_diagnostico_nunca_guarda_valores_digitados(self):
        nav = NavFalso([tela(LOGIN), tela("https://sso.exemplo.invalid/auth?cpf=segredo", usuario=True, senha=True),
                        tela("https://sso.exemplo.invalid/auth", usuario=True, senha=True, erro="Credenciais inválidas")])
        with self.assertRaises(pdpj.PdpjErro):
            pdpj.entrar(nav, consulta=False)
        guardado = "\n".join(p.read_text(encoding="utf-8") for p in comum.DIAG_DIR.glob("pdpj_*.json"))
        for valor in ("00000000000", "valor-a", "JBSWY3DPEHPK3PXP", "segredo"):
            self.assertNotIn(valor, guardado)
        self.assertNotIn("valor-a", pdpj.arquivo_trava().read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
