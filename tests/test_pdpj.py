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

    def test_erro_inesperado_depois_do_envio_tambem_trava(self):
        class Quebra(NavFalso):
            def esperar(self, ms):
                if self.digitado:
                    raise RuntimeError("janela fechada")
        nav = Quebra([tela(LOGIN), tela("https://sso.exemplo.invalid/auth", usuario=True, senha=True), tela("https://sso.exemplo.invalid/x")])
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        self.assertEqual((ctx.exception.etapa, ctx.exception.trava), ("erro", True))
        self.assertIsNotNone(pdpj.trava())
        self.assertEqual(nav.digitado, ["usuario", "senha"])

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


def _cpf_de_teste(base="987654321"):
    """CPF com dígitos verificadores corretos, calculado aqui (nenhum CPF escrito no arquivo)."""
    d = [int(c) for c in base]
    for n in (9, 10):
        d.append((sum(d[i] * (n + 1 - i) for i in range(n)) * 10 % 11) % 10)
    return "".join(map(str, d))


CPF_FICTICIO = _cpf_de_teste()
SENHA_FICTICIA = "senha-ficticia-" + "9x"
SSO = "https://sso.exemplo.invalid/auth"
SSO_OTP = "https://sso.exemplo.invalid/otp"


class NavComGancho(NavFalso):
    """Chama `gancho(nav, chave)` quando alguém digita, ANTES de registrar o valor (para espiar o que existe nesse instante)."""

    def __init__(self, *a, gancho=None, **kw):
        super().__init__(*a, **kw)
        self.gancho = gancho

    def digitar(self, seletores, valor):
        chave = {ALVO_CPF: "usuario", ALVO_SENHA: "senha", ALVO_OTP: "otp"}[seletores]
        if self.gancho:
            self.gancho(self, chave)
        return super().digitar(seletores, valor)


def telas_sso():
    return [tela(LOGIN), tela(SSO, usuario=True, senha=True), tela(SSO_OTP, otp=True), tela(PAINEL)]


class TravaAntesDoEnvio(Base):
    """A trava nasce ANTES da primeira credencial, de forma atômica: morrer no meio não deixa nova tentativa livre."""

    def test_trava_ja_existe_quando_a_primeira_credencial_e_digitada(self):
        vista = []
        nav = NavComGancho(telas_sso(), gancho=lambda n, c: vista.append((c, pdpj.trava() and pdpj.trava()["etapa"])))
        pdpj.entrar(nav, consulta=False)
        self.assertEqual(vista[0], ("usuario", "em_andamento"))
        self.assertIsNone(pdpj.trava())                              # login concluído: a própria trava foi removida

    def test_ctrl_c_no_meio_do_login_deixa_a_trava_de_pe(self):
        def gancho(n, chave):
            if chave == "senha":
                raise KeyboardInterrupt
        nav = NavComGancho(telas_sso(), gancho=gancho)
        with self.assertRaises(KeyboardInterrupt):
            pdpj.entrar(nav, consulta=False)
        self.assertEqual(pdpj.trava()["etapa"], "em_andamento")
        nav2 = NavFalso(telas_sso())                                 # a execução seguinte não digita nada
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav2, consulta=False)
        self.assertEqual(ctx.exception.etapa, "travado")
        self.assertEqual((nav2.aberturas, nav2.digitado), ([], []))

    def test_programa_morto_depois_de_enviar_a_senha_tambem_trava(self):
        class Morre(NavFalso):
            def esperar(self, ms):
                if self.digitado:
                    raise SystemExit(1)                              # kill / sys.exit: não passa por nenhum `except Exception`
        with self.assertRaises(SystemExit):
            pdpj.entrar(Morre(telas_sso()), consulta=False)
        self.assertIsNotNone(pdpj.trava())

    def test_interrupcao_antes_de_qualquer_envio_nao_trava(self):
        class Morre(NavFalso):
            def clicar_texto(self, *t):
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            pdpj.entrar(Morre(telas_sso()), consulta=False)
        self.assertIsNone(pdpj.trava())

    def test_duas_execucoes_ao_mesmo_tempo_nao_enviam_duas_vezes(self):
        """B leu a trava quando estava livre e só então A criou a sua: B desiste sem digitar nada."""
        b = NavFalso(telas_sso())
        resultado = {}

        def gancho_a(n, chave):
            if chave == "usuario" and "b" not in resultado:
                with mock.patch.object(pdpj, "trava", lambda: None):    # a leitura de B aconteceu antes da gravação de A
                    try:
                        pdpj.entrar(b, consulta=False)
                    except pdpj.PdpjErro as e:
                        resultado["b"] = e
        a = NavComGancho(telas_sso(), gancho=gancho_a)
        self.assertTrue(pdpj.entrar(a, consulta=False)["ok"])
        self.assertEqual(resultado["b"].etapa, "travado")
        self.assertFalse(resultado["b"].trava)
        self.assertEqual(b.digitado, [])
        self.assertEqual(a.digitado, ["usuario", "senha", "otp"])

    def test_sucesso_nao_destrava_trava_criada_por_outra_execucao(self):
        def gancho(n, chave):
            if chave == "otp":                                        # outra execução falhou e travou enquanto esta ainda andava
                pdpj.travar("recusado", "falha de outra execução", token="outra")
        nav = NavComGancho(telas_sso(), gancho=gancho)
        self.assertTrue(pdpj.entrar(nav, consulta=False)["ok"])
        self.assertEqual(pdpj.trava()["etapa"], "recusado")

    def test_falha_reescreve_a_propria_trava_e_nao_deixa_arquivos_temporarios(self):
        nav = NavFalso([tela(LOGIN), tela(SSO, usuario=True, senha=True), tela(SSO, usuario=True, senha=True, erro="Credenciais inválidas")])
        with self.assertRaises(pdpj.PdpjErro):
            pdpj.entrar(nav, consulta=False)
        self.assertEqual(pdpj.trava()["etapa"], "recusado")
        self.assertEqual([p.name for p in comum.PROJETOS_DIR.glob(".pdpj_trava*")], [".pdpj_trava.json"])

    def test_trava_ilegivel_bloqueia(self):
        pdpj.arquivo_trava().write_text("{nao e json", encoding="utf-8")
        nav = NavFalso(telas_sso())
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        self.assertEqual(ctx.exception.etapa, "travado")
        self.assertEqual((nav.aberturas, nav.digitado), ([], []))

    def test_pagina_sem_https_nao_recebe_credencial(self):
        nav = NavFalso([tela(LOGIN), tela("http://sso.exemplo.invalid/auth", usuario=True, senha=True)])
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        self.assertEqual((ctx.exception.etapa, ctx.exception.trava), ("inseguro", False))
        self.assertEqual(nav.digitado, [])
        self.assertIsNone(pdpj.trava())


class ErroNaTela(Base):
    def test_aviso_que_ja_estava_na_pagina_nao_derruba_um_login_bom(self):
        banner = "Sistema com instabilidade. Pode haver lentidão."
        nav = NavFalso([tela(LOGIN, erro=banner), tela(SSO, usuario=True, senha=True, erro=banner),
                        tela(SSO_OTP, otp=True, erro=banner), tela(PAINEL)])
        self.assertTrue(pdpj.entrar(nav, consulta=False)["ok"])
        self.assertEqual(nav.digitado, ["usuario", "senha", "otp"])

    def test_seletores_de_erro_nao_incluem_classes_genericas(self):
        partes = [x.strip() for x in pdpj.ERRO_SELETORES.split(",")]
        self.assertNotIn(".alert", partes)
        self.assertNotIn(".error", partes)

    def test_erro_nao_detectado_espera_o_tempo_e_nunca_reenvia(self):
        """A tela de erro voltou com o formulário, mas nenhum seletor a reconheceu: espera o limite e trava, sem digitar de novo."""
        nav = NavFalso([tela(LOGIN), tela(SSO, usuario=True, senha=True)] + [tela(SSO, usuario=True, senha=True)] * 3)
        relogio = iter(range(0, 10000, 5))
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False, relogio=lambda: next(relogio))
        self.assertEqual((ctx.exception.etapa, ctx.exception.trava), ("tempo", True))
        self.assertEqual(nav.digitado, ["usuario", "senha"])
        self.assertEqual(nav.enters, 1)

    def test_codigo_recusado_nao_reenvia_o_codigo(self):
        nav = NavFalso([tela(LOGIN), tela(SSO, usuario=True, senha=True), tela(SSO_OTP, otp=True),
                        tela(SSO_OTP, otp=True, erro="Código inválido")])
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        self.assertEqual(ctx.exception.etapa, "recusado")
        self.assertEqual(nav.digitado, ["usuario", "senha", "otp"])

    def test_cpf_depois_senha_e_formulario_voltando_nao_reenvia(self):
        nav = NavFalso([tela(LOGIN), tela("https://sso.exemplo.invalid/cpf", usuario=True),
                        tela("https://sso.exemplo.invalid/senha", senha=True),
                        tela("https://sso.exemplo.invalid/cpf", usuario=True, erro="Usuário ou senha inválidos")])
        with self.assertRaises(pdpj.PdpjErro):
            pdpj.entrar(nav, consulta=False)
        self.assertEqual(nav.digitado, ["usuario", "senha"])


class Vazamento(Base):
    def setUp(self):
        super().setUp()
        self.cofre.update(pdpj_cpf=CPF_FICTICIO, pdpj_senha=SENHA_FICTICIA)

    def guardado(self):
        arquivos = list(comum.DIAG_DIR.glob("pdpj_*")) + [pdpj.arquivo_trava()]
        return "\n".join(p.read_text(encoding="utf-8") for p in arquivos if p.exists())

    def test_mensagem_de_erro_da_pagina_com_os_valores_digitados_e_limpa(self):
        mascara = f"{CPF_FICTICIO[:3]}.{CPF_FICTICIO[3:6]}.{CPF_FICTICIO[6:9]}-{CPF_FICTICIO[9:]}"
        eco = f"CPF {mascara} ou senha {SENHA_FICTICIA} incorretos"
        nav = NavFalso([tela(LOGIN), tela(SSO, usuario=True, senha=True), tela(SSO, usuario=True, senha=True, erro=eco)])
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        tudo = self.guardado() + ctx.exception.mensagem + str(ctx.exception)
        for valor in (CPF_FICTICIO, SENHA_FICTICIA, mascara, mascara[:7]):
            self.assertNotIn(valor, tudo)

    def test_codigo_do_autenticador_digitado_nao_vai_para_mensagem_nem_trava(self):
        codigo = "".join(["48", "1516"])
        with mock.patch.object(acesso, "codigo_totp_atual", lambda segredo=None: codigo):
            nav = NavFalso([tela(LOGIN), tela(SSO, usuario=True, senha=True), tela(SSO_OTP, otp=True),
                            tela(SSO_OTP, otp=True, erro=f"O código {codigo} é inválido")])
            with self.assertRaises(pdpj.PdpjErro) as ctx:
                pdpj.entrar(nav, consulta=False)
        self.assertNotIn(codigo, self.guardado() + ctx.exception.mensagem)

    def test_endereco_sem_parametros_nem_fragmento(self):
        nav = NavFalso([tela(LOGIN), tela(SSO + "?session_code=abc&execution=def#state=ghi", usuario=True, senha=True),
                        tela(SSO + "?session_code=abc#state=ghi", usuario=True, senha=True, erro="Credenciais inválidas")])
        with self.assertRaises(pdpj.PdpjErro):
            pdpj.entrar(nav, consulta=False)
        guardado = self.guardado()
        for trecho in ("session_code", "execution", "state=", "abc", "ghi"):
            self.assertNotIn(trecho, guardado)

    def test_inspecionar_devolve_endereco_sem_parametros(self):
        nav = NavFalso([tela(LOGIN), tela(SSO + "?code=abc#frag")])
        r = pdpj.inspecionar(nav)
        self.assertNotIn("abc", r["url"])
        self.assertNotIn("frag", r["url"])

    def test_entrar_nao_imprime_nada(self):
        import contextlib
        import io
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
            pdpj.entrar(self.fluxo_ok(), consulta=False)
            nav2 = NavFalso([tela(LOGIN), tela(SSO, usuario=True, senha=True), tela(SSO, usuario=True, senha=True, erro="x")])
            with self.assertRaises(pdpj.PdpjErro):
                pdpj.entrar(nav2, consulta=False)
        self.assertEqual(saida.getvalue(), "")


class Totp(Base):
    def test_o_codigo_e_gerado_depois_da_pausa_da_janela(self):
        ordem = []
        with mock.patch.object(pdpj, "pausa_para_janela_do_totp", lambda **kw: ordem.append("pausa")), \
                mock.patch.object(acesso, "codigo_totp_atual", lambda segredo=None: ordem.append("codigo") or "123456"):
            pdpj.entrar(self.fluxo_ok(), consulta=False)
        self.assertEqual(ordem, ["pausa", "codigo"])

    def test_segredo_invalido_nao_digita_codigo_algum(self):
        self.cofre["pdpj_totp"] = "isto nao e base32 !!"
        nav = self.fluxo_ok()
        with self.assertRaises(pdpj.PdpjErro) as ctx:
            pdpj.entrar(nav, consulta=False)
        self.assertEqual(ctx.exception.etapa, "erro")
        self.assertEqual(nav.digitado, ["usuario", "senha"])         # o código nunca foi digitado
        self.assertTrue(ctx.exception.trava)                         # mas a senha foi: trava

    def test_pausa_no_limite_da_janela(self):
        dormiu = []
        self.assertFalse(PAUSA_REAL(agora=lambda: 90 + 24.0, dormir=dormiu.append))   # sobram 6 s: vale
        self.assertTrue(PAUSA_REAL(agora=lambda: 90 + 24.1, dormir=dormiu.append))    # sobram 5,9 s: espera
        self.assertEqual(len(dormiu), 1)


if __name__ == "__main__":
    unittest.main()
