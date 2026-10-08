"""Beta 3: login do jus.br com diagnóstico, captcha do TRT (uma página de consulta por rodada, aviso que chama a
atenção, processo adiado), processo físico e graus (1º, 2º e TST). Tudo com doubles e dados fictícios: nada de rede,
certificado, navegador, osascript ou tribunal. O que depende do tribunal e do Mac reais se valida no piloto.

    python3 -m unittest tests/test_beta3.py -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import acesso  # noqa: E402
import atencao  # noqa: E402
import capa  # noqa: E402
import comum  # noqa: E402
import coletor  # noqa: E402
import ficticio  # noqa: E402
import fila  # noqa: E402
import janela  # noqa: E402
import taxonomia  # noqa: E402
import trt  # noqa: E402
from test_fila import FICHAS, Relogio, nova_fila, numeros_do  # noqa: E402

TRT7 = "1234569-95.2026.5.07.0001"        # números fictícios (dígito verificador correto)
TRT7_B = "1234570-71.2025.5.07.0001"


# ================================================================== atenção (faixa, notificação, lembrete)

class TestAtencao(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS[:2])
        self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def test_pedir_ler_e_limpar(self):
        self.assertIsNone(atencao.atual())
        atencao.pedir("captcha", "x", tribunal="7")
        r = atencao.atual()
        self.assertEqual((r["tipo"], r["tribunal"]), ("captcha", "7"))
        self.assertIn("captcha do TRT 7 aguardando", atencao.texto_da_faixa(r))
        atencao.limpar("login")                 # outro tipo: não limpa
        self.assertIsNotNone(atencao.atual())
        atencao.limpar("captcha", "9")          # outro TRT: não limpa
        self.assertIsNotNone(atencao.atual())
        atencao.limpar("captcha", "7")
        self.assertIsNone(atencao.atual())

    def test_pedido_de_programa_que_nao_existe_mais_some(self):
        atencao.pedir("login", "x")
        registro = comum.load_json(atencao._arquivo(), {})
        registro["pid"] = 2 ** 22 + 12345        # pid inexistente
        comum.save_json(atencao._arquivo(), registro)
        self.assertIsNone(atencao.atual())

    def test_pedido_muito_velho_some(self):
        atencao.pedir("login", "x")
        registro = comum.load_json(atencao._arquivo(), {})
        registro["desde"] = "2020-01-01T00:00:00"
        comum.save_json(atencao._arquivo(), registro)
        self.assertIsNone(atencao.atual())

    def test_lembrete_repete_a_cada_60_s(self):
        agora, avisos = [1000.0], []
        l = atencao.Lembrete("oi", relogio=lambda: agora[0], notificador=avisos.append)
        self.assertFalse(l.tick())
        agora[0] += 59
        self.assertFalse(l.tick())
        agora[0] += 2
        self.assertTrue(l.tick())
        agora[0] += 30
        self.assertFalse(l.tick())
        agora[0] += 31
        self.assertTrue(l.tick())
        self.assertEqual((len(avisos), l.vezes), (2, 2))

    def test_no_mac_notifica_e_traz_o_navegador_para_a_frente(self):
        chamadas = []

        class Ok:
            returncode = 0

        with mock.patch.object(atencao, "MAC", True), \
                mock.patch.object(atencao, "_executar", side_effect=lambda a, timeout=5: chamadas.append(a) or Ok()):
            self.assertTrue(atencao.notificar('Captcha "do" TRT 7'))
            self.assertTrue(atencao.trazer_navegador_para_frente())
            pagina = mock.Mock()
            with mock.patch.object(janela, "mostrar") as mostrar:
                atencao.chamar(pagina, "captcha", "msg", tribunal="7")
            mostrar.assert_called_once_with(pagina, maximizar=True)        # tela cheia
        scripts = [a[2] for a in chamadas]
        self.assertTrue(any("display notification" in x and 'sound name "Ping"' in x for x in scripts))
        self.assertTrue(any("frontmost" in x and "Chrom" in x for x in scripts))
        self.assertTrue(all(a[0] == "osascript" for a in chamadas))
        self.assertIn('\\"do\\"', scripts[0], "aspas do texto são escapadas")
        self.assertEqual(atencao.atual()["tipo"], "captcha")

    def test_fora_do_mac_nao_chama_osascript(self):
        with mock.patch.object(atencao, "MAC", False), mock.patch.object(atencao, "_executar") as ex:
            self.assertFalse(atencao.trazer_navegador_para_frente())
            atencao.notificar("x")
        ex.assert_not_called()

    def test_faixa_vermelha_no_painel_e_rota_json(self):
        from revisao import app
        cliente = app.test_client()
        self.assertEqual(cliente.get("/atencao.json").get_json(), {})
        pagina = cliente.get("/fluxo").get_data(as_text=True)
        self.assertIn("id='atencao'", pagina)
        self.assertIn("display:none", pagina.split("id='atencao'")[1][:80])
        atencao.pedir("captcha", "x", tribunal="7")
        dados = cliente.get("/atencao.json").get_json()
        self.assertIn("Precisa de você: captcha do TRT 7 aguardando", dados["texto"])
        pagina = cliente.get("/fluxo").get_data(as_text=True)
        self.assertIn("display:block", pagina.split("id='atencao'")[1][:80])
        self.assertIn("Precisa de você: captcha do TRT 7 aguardando", pagina)


# ================================================================== login do jus.br

class PaginaDeLogin:
    """Página falsa do jus.br: mostra "Sair do portal" depois de `entra_apos` esperas (None = nunca)."""

    def __init__(self, entra_apos=None):
        self.esperas, self.entra_apos, self.fechada = 0, entra_apos, False

    def goto(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        self.esperas += 1

    def inner_text(self, sel):
        return "Sair do portal" if self.entra_apos is not None and self.esperas >= self.entra_apos else "Entrar"

    def close(self):
        self.fechada = True


class TestLogin(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS[:2])
        self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.avisos = []
        p = [mock.patch.object(atencao, "notificar", side_effect=lambda t, titulo=None: self.avisos.append(t)),
             mock.patch.object(atencao, "trazer_navegador_para_frente", return_value=True),
             mock.patch.object(janela, "mostrar"), mock.patch.object(janela, "minimizar")]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def _diagnostico_falso(self):
        def salvar(page, motivo):
            base = comum.DIAG_DIR / f"{motivo}_x"
            comum.DIAG_DIR.mkdir(parents=True, exist_ok=True)
            base.with_suffix(".txt").write_text("tela", encoding="utf-8")
            return base
        return mock.patch.object(coletor, "salvar_diagnostico", side_effect=salvar)

    def test_login_automatico_registra_o_passo_que_falhou(self):
        page = mock.Mock()
        page.inner_text.return_value = ""
        with mock.patch.object(acesso, "obter", return_value=None):
            self.assertFalse(acesso.login_automatico(page))
        self.assertEqual(acesso.ULTIMO["passo"], "senha")
        self.assertIn("Acesso e escritório", acesso.ULTIMO["o_que_fazer"])
        with mock.patch.object(acesso, "obter", return_value="x"), mock.patch.object(acesso, "_clicar_certificado", return_value=False):
            self.assertFalse(acesso.login_automatico(page))
        self.assertEqual(acesso.ULTIMO["passo"], "botao")
        with mock.patch.object(acesso, "obter", return_value="x"), mock.patch.object(acesso, "_clicar_certificado", return_value=True), \
                mock.patch.object(acesso, "_dialogo_aberto", return_value=False), mock.patch.object(acesso.time, "sleep"), \
                mock.patch.object(acesso, "pje_office_aberto", return_value=False):
            self.assertFalse(acesso.login_automatico(page, limite_dialogo=0))
        self.assertEqual((acesso.ULTIMO["passo"], acesso.ULTIMO["pje_office_aberto"]), ("dialogo", False))
        self.assertIn("PJe Office", acesso.ULTIMO["o_que_fazer"])

    def test_pje_office_aberto_consulta_o_sistema(self):
        class R:
            returncode = 0
        with mock.patch.object(acesso, "MAC", True), mock.patch.object(acesso.subprocess, "run", return_value=R()):
            self.assertTrue(acesso.pje_office_aberto())
        R.returncode = 1
        with mock.patch.object(acesso, "MAC", True), mock.patch.object(acesso.subprocess, "run", return_value=R()):
            self.assertFalse(acesso.pje_office_aberto())
        with mock.patch.object(acesso, "MAC", False), mock.patch.object(acesso, "WINDOWS", False):
            self.assertIsNone(acesso.pje_office_aberto())

    def test_login_que_falha_e_a_pessoa_conclui(self):
        page = PaginaDeLogin(entra_apos=3)
        contexto = mock.Mock()

        def falha(_p):
            acesso.registrar_falha("dialogo", "O diálogo não apareceu.")
            return False
        with mock.patch.object(janela, "nova_pagina", return_value=page), mock.patch.object(acesso, "login_automatico", side_effect=falha), \
                mock.patch.object(acesso, "pje_office_aberto", return_value=False), self._diagnostico_falso():
            coletor.logar(contexto)
        self.assertTrue(page.fechada)
        diagnosticos = sorted(p.name for p in comum.DIAG_DIR.iterdir())
        self.assertEqual(len([d for d in diagnosticos if d.startswith("login_jusbr_t")]), 4, diagnosticos)   # 2 tentativas: .txt e .json
        motivo = json.loads(next(p for p in comum.DIAG_DIR.iterdir() if p.suffix == ".json").read_text(encoding="utf-8"))
        self.assertEqual(motivo["passo"], "dialogo")
        self.assertLessEqual(set(motivo), {"passo", "mensagem", "o_que_fazer", "pje_office_aberto", "acessibilidade", "tentativa",
                                           "plataforma", "quando"}, "o diagnóstico guarda só o motivo, nunca segredo")
        self.assertIsNone(atencao.atual(), "concluído: a faixa vermelha sai")
        janela.mostrar.assert_called()           # a janela apareceu para a pessoa

    def test_login_nao_concluido_levanta_e_deixa_a_faixa_com_a_orientacao(self):
        page = PaginaDeLogin(entra_apos=None)

        def falha(_p):
            acesso.registrar_falha("dialogo", "O diálogo não apareceu.")
            return False
        with mock.patch.object(janela, "nova_pagina", return_value=page), mock.patch.object(acesso, "login_automatico", side_effect=falha), \
                mock.patch.object(acesso, "pje_office_aberto", return_value=False), mock.patch.object(coletor, "LOGIN_TIMEOUT_S", -1), \
                self._diagnostico_falso():
            with self.assertRaises(coletor.LoginFalhou) as ctx:
                coletor.logar(mock.Mock())
        self.assertIn("PJe Office", str(ctx.exception))
        registro = atencao.atual()
        self.assertEqual(registro["tipo"], "login")
        self.assertIn("Retomar", registro["mensagem"])

    def test_fila_para_na_falha_de_login_e_nao_gasta_tentativa(self):
        """O ColetorReal devolve erro `fatal`: a fila pausa, o processo volta a pendente sem gastar tentativa e os
        demais NÃO tentam novo login (antes, cada processo repetia o login)."""
        class SemLogin:
            chamadas = 0

            def coletar(self, processo, profundidade, desde):
                SemLogin.chamadas += 1
                return {"capa": {}, "movimentos": [], "documentos": [], "erro": {
                    "codigo": "sessao_expirada", "mensagem": "Login no jus.br não concluído a tempo.", "fatal": True}}
        with ficticio.projeto_de_teste(FICHAS):
            rel = Relogio()
            f = nova_fila({"slug": comum.PROJETO}, rel)
            f.enfileirar([x["numero"] for x in FICHAS[:5]], modo="imediato", profundidade="rapido")
            eventos = []
            rodar = fila.rodar_fila(f, SemLogin(), ao_progresso=eventos.append, esperar=False)
            self.assertEqual(SemLogin.chamadas, 1)
            self.assertTrue(f.controle()["pausada"])
            primeiro = f.item(FICHAS[0]["numero"])
            self.assertEqual((primeiro["estado"], primeiro["tentativas"]), ("pendente", 0))
            login = [e for e in eventos if e["evento"] == "login"]
            self.assertEqual(len(login), 1)
            self.assertIn("Login", login[0]["mensagem"])
            self.assertEqual(rodar["pendente"], 5)

    def test_painel_oferece_retomar_depois_da_falha_de_login(self):
        from painel import assistente
        antes = dict(assistente.EXEC)
        self.addCleanup(lambda: (assistente.EXEC.clear(), assistente.EXEC.update(antes)))
        assistente.EXEC["log"].clear()
        assistente._progresso({"evento": "login", "mensagem": "O diálogo não apareceu.", "total": 1})
        self.assertEqual(assistente.EXEC["estado"], "pausada")
        self.assertIn("PRECISA DE VOCÊ", assistente.EXEC["log"][0])
        self.assertIn("Retomar", assistente.EXEC["log"][0])

    def test_assistente_fecha_o_navegador_no_fim_da_coleta(self):
        from painel import assistente
        fechados = []

        class Coletor:
            def coletar(self, processo, profundidade, desde):
                return {"capa": {}, "movimentos": [], "documentos": [], "erro": None}

            def fechar(self):
                fechados.append(1)
        antes = dict(assistente.EXEC)
        self.addCleanup(lambda: (assistente.EXEC.clear(), assistente.EXEC.update(antes)))
        f = nova_fila({"slug": comum.PROJETO}, Relogio())
        f.enfileirar([FICHAS[0]["numero"]], modo="imediato", profundidade="rapido")
        assistente.EXEC.update(modo="imediato", pedido=None, erro=None)
        assistente._trabalho(fila, f, Coletor(), comum.PROJETO)
        self.assertEqual(fechados, [1])

    def test_coletor_real_devolve_erro_fatal_quando_abrir_falha(self):
        real = fila.ColetorReal()
        with mock.patch.object(fila.ColetorReal, "abrir", side_effect=coletor.LoginFalhou("Login no jus.br não concluído a tempo. x")):
            r = real.coletar({"numero": TRT7, "cliente": "x"}, "rapido", None)
        self.assertEqual((r["erro"]["codigo"], r["erro"]["fatal"]), ("sessao_expirada", True))

    def test_os_dois_caminhos_usam_o_mesmo_login(self):
        """A aba Atualizar (coletor.rodar) e a fila (ColetorReal.abrir) logam por coletor.logar."""
        chamadas = []
        fake_pw = mock.MagicMock()
        with mock.patch.object(coletor, "logar", side_effect=lambda ctx: chamadas.append("logar")), \
                mock.patch.object(janela, "abrir_navegador", return_value=(mock.Mock(), mock.Mock())), \
                mock.patch("playwright.sync_api.sync_playwright", return_value=fake_pw):
            real = fila.ColetorReal()
            real.abrir()
            real.fechar()
            with ficticio.projeto_de_teste(FICHAS[:1]), \
                    mock.patch.object(coletor, "carteira", return_value={"1": {"numero": "1", "cliente": "x"}}), \
                    mock.patch.object(coletor, "coletar_processo", return_value=0), mock.patch.object(coletor, "pausa"):
                coletor.rodar(["1"])
        self.assertEqual(chamadas, ["logar", "logar"])


# ================================================================== TRT: uma página de consulta por rodada

class RespostaFalsa:
    def __init__(self, url, corpo=None, pdf=None):
        self.url, self._corpo, self._pdf = url, corpo, pdf
        self.headers = {"content-type": "application/pdf" if pdf is not None else "application/json"}

    def json(self):
        return self._corpo

    def body(self):
        return self._pdf


def autos_falsos(numero, id_, movimentos, documentos=()):
    itens = [{"id": i, "data": f"2026-09-{10 + i:02d}T10:00:00.1", "titulo": t, "documento": False} for i, t in enumerate(movimentos, 1)]
    for d in documentos:
        itens.append({"id": d, "documento": True, "idUnicoDocumento": f"u{d}", "tipo": "Sentença", "titulo": "Sentença",
                      "data": "2026-09-20T10:00:00.1", "publico": True})
    return {"id": id_, "numero": numero, "itensProcesso": itens}


class PortalFalso:
    """Simula o PJe do TRT: um contexto com páginas. A consulta é uma página só (SPA): pesquisar leva ao detalhe do
    processo; voltar leva à consulta sem recarregar; o captcha, se pedido, trava o detalhe até alguém resolver."""

    def __init__(self, autos, captcha_na_primeira=0, captcha_nunca_resolvido=False, falha_grau2=False):
        self.autos = autos                      # {(numero, grau): corpo}
        self.paginas, self.ouvintes = [], []
        self.captcha_pendente = captcha_na_primeira       # nº de esperas até a pessoa resolver; 0 = sem captcha
        self.captcha_nunca = captcha_nunca_resolvido
        self.falha_grau2 = falha_grau2
        self.gotos, self.pesquisas, self.graus_pedidos = [], [], []
        self.pdfs = {}

    # contexto
    def new_page(self):
        p = PaginaFalsa(self)
        self.paginas.append(p)
        return p

    def on(self, evento, fn):
        self.ouvintes.append(fn)

    def remove_listener(self, evento, fn):
        self.ouvintes.remove(fn)

    def emitir(self, resp):
        for fn in list(self.ouvintes):
            fn(resp)

    def consultas_abertas(self):
        return [p for p in self.paginas if p.aberta_na_consulta]


class FakeLocator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    @property
    def first(self):
        return self

    def count(self):
        s, p = self.sel, self.page
        if "captcha" in s.lower():
            return 1 if p.captcha else 0
        if s in ("#nrProcessoInput", "#btnPesquisar") or "processo" in s.lower() or s == "input[type='text']":
            return 1 if p.estado == "consulta" and not p.captcha else 0
        return 0

    def is_visible(self):
        return self.count() > 0

    def click(self, **k):
        if self.sel == "#btnPesquisar":
            self.page.pesquisar()

    def fill(self, v):
        self.page.digitado = ""

    def press_sequentially(self, texto, delay=0):
        self.page.digitado += texto

    def press(self, *a):
        self.page.pesquisar()


class PaginaFalsa:
    def __init__(self, portal):
        self.portal, self.url, self.estado, self.captcha = portal, "about:blank", "vazia", False
        self.digitado, self.fechada, self.aberta_na_consulta = "", False, False
        self.historico = []
        self.fragmento_pdf = None
        self.context = portal

    # navegação
    def goto(self, url, **k):
        self.portal.gotos.append(url)
        if url.endswith("/consultaprocessual/login"):
            self.estado = "login"
        elif url.rstrip("/").endswith("/consultaprocessual"):
            self.estado, self.url = "consulta", url
            self.aberta_na_consulta = True
        elif "/detalhe-processo/" in url:
            base = url.split("#")[0]
            numero, grau = base.split("/detalhe-processo/")[1].split("/")[:2]
            if grau == "2" and self.portal.falha_grau2:
                raise RuntimeError("Timeout 45000ms exceeded")
            self.url, self.estado = base, "detalhe"
            if "#" in url:                                        # visualizador de documento: entrega o PDF
                unico = url.split("#")[1]
                self.portal.emitir(RespostaFalsa(f"https://pje.trt7.jus.br/pje-consulta-api/api/processos/{numero}/documentos/{unico[1:]}",
                                                 pdf=b"%PDF-1.4 ficticio"))
            else:
                self.abrir_detalhe(numero, grau)

    def reload(self, **k):
        if self.estado == "login":
            self.estado, self.url = "consulta", "https://pje.trt7.jus.br/consultaprocessual/"
            self.aberta_na_consulta = True

    def go_back(self, **k):
        if self.estado == "detalhe":
            self.estado, self.url = "consulta", "https://pje.trt7.jus.br/consultaprocessual/"

    def pesquisar(self):
        self.portal.pesquisas.append(self.digitado)
        numero = next(n for n, _ in self.portal.autos if "".join(c for c in n if c.isdigit()) == self.digitado)
        self.estado, self.url = "detalhe", f"https://pje.trt7.jus.br/consultaprocessual/detalhe-processo/{numero}/1"
        self.abrir_detalhe(numero, "1")

    def abrir_detalhe(self, numero, grau):
        self.portal.graus_pedidos.append((numero, grau))
        if self.portal.captcha_pendente or self.portal.captcha_nunca:
            self.captcha, self.espera_do_detalhe = True, (numero, grau)
            return
        self.portal.emitir(RespostaFalsa(f"https://pje.trt7.jus.br/pje-consulta-api/api/processos/{self.portal.autos[(numero, grau)]['id']}",
                                         self.portal.autos[(numero, grau)]))

    def evaluate(self, js, rota=None):
        if self.portal.falha_grau2 and rota and rota.endswith("/2"):
            raise RuntimeError("sem rota")
        if rota and "/detalhe-processo/" in rota:
            numero, grau = rota.split("/detalhe-processo/")[1].split("/")[:2]
            self.url, self.estado = f"https://pje.trt7.jus.br{rota}", "detalhe"
            if (numero, grau) in self.portal.autos:
                self.abrir_detalhe(numero, grau)

    # conteúdo
    def locator(self, sel):
        return FakeLocator(self, sel)

    def get_by_role(self, *a, **k):
        return FakeLocator(self, "__nada__")

    def inner_text(self, sel):
        return "digite os caracteres da imagem" if self.captcha else "Consulta processual"

    def wait_for_timeout(self, ms):
        import time as _t
        _t.sleep(0.0005)
        if self.captcha and not self.portal.captcha_nunca:
            self.portal.captcha_pendente -= 1
            if self.portal.captcha_pendente <= 0:
                self.portal.captcha_pendente, self.captcha = 0, False
                self.abrir_detalhe(*self.espera_do_detalhe)

    def is_closed(self):
        return self.fechada

    def close(self):
        self.fechada = True

    def bring_to_front(self):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS[:2])
        self.proj = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        trt.zerar_rodada()
        self.addCleanup(trt.zerar_rodada)
        self.notificacoes = []
        for alvo in (mock.patch.object(atencao, "notificar", side_effect=lambda t, titulo=None: self.notificacoes.append(t)),
                     mock.patch.object(atencao, "trazer_navegador_para_frente", return_value=True),
                     mock.patch.object(janela, "mostrar"), mock.patch.object(janela, "minimizar"),
                     mock.patch.object(janela, "print_da_pagina", side_effect=RuntimeError("sem tela")),
                     mock.patch.object(coletor, "pausa")):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.config = {"coleta": {"pausa_entre_documentos_s": [0, 0], "captcha_espera_min": 1}}

    def coletar(self, portal, numero, estado=None, proc_extra=None, historico=5, cota=5, relato=None):
        proc = {"numero": numero, "cliente": "Cliente X", **(proc_extra or {})}
        lista = comum.eventos()
        estado = {} if estado is None else estado
        with mock.patch.object(comum, "config", return_value=self.config):
            baixados = trt.coletar_processo(portal, proc, estado, lista, historico, cota, None, relato)
        return baixados, estado, lista


def portal_de(*numeros, movimentos=("Distribuição", "Audiência realizada"), com_segundo_grau=None, **kw):
    autos = {}
    for k, n in enumerate(numeros, 1):
        autos[(n, "1")] = autos_falsos(n, 100 + k, movimentos, documentos=[f"{900 + k}"])
        if com_segundo_grau and n in com_segundo_grau:
            autos[(n, "2")] = autos_falsos(n, 200 + k, ["Distribuído ao relator", "Pauta de julgamento"])
    return PortalFalso(autos, **kw)


class TestUmaPaginaPorTRT(Base):
    def test_tres_processos_do_mesmo_trt_usam_a_mesma_pagina_sem_recarregar(self):
        a, b, c = TRT7, TRT7_B, "1234568-72.2024.5.07.0001"
        portal = portal_de(a, b, c, captcha_na_primeira=2)
        with mock.patch.object(trt, "tem_captcha", wraps=trt.tem_captcha):
            for numero in (a, b, c):
                self.coletar(portal, numero)
        consultas = portal.consultas_abertas()
        self.assertEqual(len(consultas), 1, "uma página de consulta só, durante toda a rodada")
        self.assertEqual(portal.pesquisas, ["".join(ch for ch in n if ch.isdigit()) for n in (a, b, c)],
                         "cada processo foi pesquisado pelo formulário")
        self.assertEqual([g for g in portal.gotos if g.rstrip("/").endswith("/consultaprocessual")], [],
                         "nenhum goto da consulta por processo (só o acesso restrito, via /login)")
        self.assertEqual(trt.CAPTCHAS, {"7": 1}, "um captcha para três processos")
        self.assertEqual(trt.RECARGAS, {})
        self.assertIn("captchas pedidos nesta rodada: 1 no TRT 7", trt.resumo_dos_captchas())
        abertas = [p for p in portal.paginas if not p.fechada]
        self.assertEqual(abertas, consultas, "as abas de documento foram fechadas; a de consulta continua aberta")

    def test_documento_abre_em_outra_aba_e_a_consulta_nao_e_tocada(self):
        portal = portal_de(TRT7)
        baixados, estado, lista = self.coletar(portal, TRT7)
        self.assertEqual(baixados, 1)
        consulta = portal.consultas_abertas()[0]
        self.assertEqual(consulta.url, f"https://pje.trt7.jus.br/consultaprocessual/detalhe-processo/{TRT7}/1")
        com_hash = [g for g in portal.gotos if "#" in g]
        self.assertEqual(len(com_hash), 1)
        self.assertEqual(len(portal.paginas), 2, "consulta + uma aba de documento (fechada)")
        self.assertTrue(portal.paginas[1].fechada)
        pdfs = list((comum.DOCS_DIR / "cliente-x" / trt.slug(TRT7)).glob("*.pdf"))
        self.assertEqual(len(pdfs), 1)

    def test_recarrega_so_quando_o_campo_do_numero_nao_volta(self):
        portal = portal_de(TRT7, TRT7_B)
        self.coletar(portal, TRT7)
        pagina = portal.consultas_abertas()[0]
        pagina.go_back = lambda **k: None                    # o histórico não leva de volta à consulta
        self.coletar(portal, TRT7_B)
        self.assertEqual(trt.RECARGAS, {"7": 1})
        self.assertTrue(any(g.rstrip("/").endswith("/consultaprocessual") for g in portal.gotos))
        self.assertIn("consulta recarregada do zero: 1x no TRT 7", trt.resumo_dos_captchas())

    def test_pagina_fechada_e_reaberta(self):
        portal = portal_de(TRT7, TRT7_B)
        self.coletar(portal, TRT7)
        portal.consultas_abertas()[0].fechada = True
        self.coletar(portal, TRT7_B)
        self.assertEqual(len([p for p in portal.paginas if p.aberta_na_consulta]), 2)

    def test_fechar_consultas_no_fim_da_rodada(self):
        portal = portal_de(TRT7)
        self.coletar(portal, TRT7)
        trt.fechar_consultas(portal)
        self.assertEqual(portal.consultas_abertas()[0].fechada, True)
        self.assertEqual(trt.CONSULTAS, {})


# ================================================================== TRT: captcha que chama a atenção

class TestCaptcha(Base):
    def test_captcha_chama_a_atencao_e_some_quando_resolvido(self):
        portal = portal_de(TRT7, captcha_na_primeira=2)
        self.coletar(portal, TRT7)
        self.assertEqual(trt.CAPTCHAS, {"7": 1})
        self.assertIsNone(atencao.atual(), "resolvido: faixa vermelha limpa")
        janela.mostrar.assert_called()
        self.assertEqual(janela.mostrar.call_args.kwargs.get("maximizar"), True)
        self.assertTrue(any("captcha do TRT 7" in n for n in self.notificacoes))
        janela.minimizar.assert_called()           # voltou a minimizar

    def test_nao_resolvido_no_prazo_levanta_captcha_adiavel(self):
        portal = portal_de(TRT7, captcha_nunca_resolvido=True)
        self.config["coleta"]["captcha_espera_min"] = 0.001         # 0,06 s
        with self.assertRaises(trt.CaptchaNaoResolvido) as ctx:
            self.coletar(portal, TRT7)
        self.assertTrue(ctx.exception.adiavel)
        self.assertIsNone(atencao.atual(), "pulado: a faixa não fica vermelha à toa")
        erro = fila.classificar_erro(ctx.exception)
        self.assertEqual((erro["codigo"], erro.get("adiavel")), ("captcha", True))
        self.assertIsNone(fila.classificar_erro(RuntimeError("Captcha do TRT não resolvido a tempo.")).get("adiavel"))

    def test_espera_configuravel(self):
        with mock.patch.object(comum, "config", return_value={"coleta": {"captcha_espera_min": 3}}):
            self.assertEqual(trt.espera_do_captcha_s(), 180)
        with mock.patch.object(comum, "config", return_value={"coleta": {}}):
            self.assertEqual(trt.espera_do_captcha_s(), 600)

    def test_lembrete_a_cada_60_s_durante_a_espera(self):
        portal = portal_de(TRT7, captcha_na_primeira=10 ** 6)
        pagina = portal.new_page()
        pagina.captcha, pagina.estado, pagina.url = True, "detalhe", "https://pje.trt7.jus.br/x"
        pagina.espera_do_detalhe = (TRT7, "1")
        relogio = {"t": 0.0}

        def tempo():
            return relogio["t"]

        def esperar(ms):
            relogio["t"] += 1.5
        pagina.wait_for_timeout = esperar
        with mock.patch.object(trt.time, "time", tempo), mock.patch.object(atencao.time, "time", tempo):
            self.assertFalse(trt.esperar_captcha_humano(pagina, limite_s=200, tribunal="7"))
        lembretes = [n for n in self.notificacoes if "precisa de você" in n]
        self.assertGreaterEqual(len(lembretes), 3, self.notificacoes)    # ~ 60, 120, 180 s (além do aviso inicial)


# ================================================================== fila: captcha adiado para o fim da rodada

class Coletor:
    """Captcha de TRT adiável até `resolve_apos` chamadas a outros tribunais; depois, tudo coleta."""

    def __init__(self, resolve_apos=None):
        self.resolve_apos, self.outros, self.ordem = resolve_apos, 0, []

    def coletar(self, processo, profundidade, desde):
        self.ordem.append(processo["numero"])
        trabalhista = processo["tribunal"].startswith("TRT")
        if not trabalhista:
            self.outros += 1
        if trabalhista and (self.resolve_apos is None or self.outros < self.resolve_apos):
            return {"capa": {}, "movimentos": [], "documentos": [], "erro": {
                "codigo": "captcha", "mensagem": "Captcha do TRT não resolvido a tempo.", "adiavel": True}}
        return {"capa": {}, "movimentos": [], "documentos": [], "erro": None}


class TestCaptchaAdiado(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS)
        self.proj = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def test_pula_o_trt_segue_com_os_outros_e_volta_no_fim(self):
        trt3, outros = numeros_do("TRT3", 3), numeros_do("TJSP", 3)
        f = nova_fila(self.proj, Relogio(), captcha_limite=3)
        f.enfileirar(trt3 + outros, modo="imediato", profundidade="rapido")
        c = Coletor(resolve_apos=3)
        avisos = []
        rodar = fila.rodar_fila(f, c, ao_progresso=lambda r: avisos.append(r["evento"]))
        self.assertEqual(c.ordem, [trt3[0]] + outros + trt3, "um captcha, os demais tribunais e, no fim, o TRT adiado")
        self.assertEqual(rodar["coletado"], 6)
        self.assertEqual(rodar["manual"], 0)
        self.assertEqual(avisos.count("captcha"), 1)

    def test_segunda_falha_do_captcha_vai_para_manual_sem_travar_os_outros(self):
        trt3, outros = numeros_do("TRT3", 3), numeros_do("TJSP", 2)
        f = nova_fila(self.proj, Relogio(), captcha_limite=3)
        f.enfileirar(trt3 + outros, modo="imediato", profundidade="rapido")
        c = Coletor(resolve_apos=None)
        rodar = fila.rodar_fila(f, c)
        self.assertEqual(c.ordem[0], trt3[0])
        self.assertEqual(rodar["coletado"], 2)
        # a segunda tentativa (fim da rodada) também falhou: o primeiro vai para manual e conta no limite do TRT
        self.assertEqual(f.item(trt3[0])["estado"], "manual")
        self.assertEqual(f.item(trt3[0])["erro"]["codigo"], "captcha")
        self.assertEqual(f.item(trt3[0])["tentativas"], 1)
        for n in trt3[1:]:
            self.assertEqual(f.item(n)["estado"], "manual", "sem sucesso no meio: o resto do TRT vai para manual")

    def test_sem_a_marca_adiavel_o_comportamento_antigo_continua(self):
        trt3 = numeros_do("TRT3", 2)
        f = nova_fila(self.proj, Relogio(), captcha_limite=5)
        f.enfileirar(trt3, modo="imediato", profundidade="rapido")
        from simulado import ColetorSimulado
        c = ColetorSimulado(FICHAS, semente=1, taxa_falha=0.0, falhar_em={trt3[0]: "captcha"},
                            pasta=tempfile.mkdtemp(dir=isolamento.TMP))
        fila.rodar_fila(f, c)
        self.assertEqual(f.item(trt3[0])["estado"], "manual")
        self.assertNotIn("adiado", f.item(trt3[1]))


# ================================================================== processo físico

class TestFisico(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS)
        self.proj = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.n = FICHAS[0]["numero"]

    def test_so_e_fisico_quando_djen_e_datajud_respondem_vazios(self):
        vazio_dj = lambda n: ({"hits": {"hits": []}}, [])      # noqa: E731
        com_dj = lambda n: ({"hits": {"hits": [{"_source": {"numeroProcesso": "".join(c for c in self.n if c.isdigit()), "grau": "G1"}}]}}, [])  # noqa: E731
        sem_pub, com_pub = (lambda n: []), (lambda n: [{"id": 1}])
        with mock.patch.object(capa, "_config_datajud", return_value=(True, "chave")):
            self.assertTrue(fila.parece_fisico(self.n, buscar_djen=sem_pub, consultar_datajud=vazio_dj))
            self.assertFalse(fila.parece_fisico(self.n, buscar_djen=com_pub, consultar_datajud=vazio_dj), "tem publicação")
            self.assertFalse(fila.parece_fisico(self.n, buscar_djen=sem_pub, consultar_datajud=com_dj), "DataJud conhece")
            self.assertFalse(fila.parece_fisico(self.n, buscar_djen=sem_pub, consultar_datajud=lambda n: (None, [])),
                             "DataJud fora do ar: na dúvida, manual")

            def cai(n):
                raise OSError("sem rede")
            self.assertFalse(fila.parece_fisico(self.n, buscar_djen=cai, consultar_datajud=vazio_dj), "DJEN fora do ar")
        with mock.patch.object(capa, "_config_datajud", return_value=(False, None)):
            self.assertFalse(fila.parece_fisico(self.n, buscar_djen=sem_pub), "DataJud desligado: não dá para afirmar")

    def test_coletor_real_so_converte_nao_encontrado(self):
        real = fila.ColetorReal()
        real._contexto = object()
        for texto, fisico, esperado in (("Processo não encontrado na consulta do jus.br (conferir manualmente).", True, "fisico"),
                                        ("Processo não encontrado na consulta do jus.br (conferir manualmente).", False, "nao_encontrado"),
                                        ("Os autos não chegaram (diagnóstico salvo).", True, "outro"),
                                        ("Timeout 30000ms exceeded", True, "timeout")):
            with mock.patch.object(coletor, "coletar_processo", side_effect=RuntimeError(texto)), \
                    mock.patch.object(fila, "parece_fisico", return_value=fisico):
                r = real.coletar({"numero": self.n, "cliente": "x"}, "rapido", None)
            self.assertEqual(r["erro"]["codigo"], esperado, texto)

    def test_fila_taxa_cobertura_e_conferir(self):
        trt3, tj = numeros_do("TRT3", 4), numeros_do("TJSP", 3)
        f = nova_fila(self.proj, Relogio())
        f.enfileirar(trt3 + tj, modo="imediato", profundidade="rapido")
        from simulado import ColetorSimulado
        c = ColetorSimulado(FICHAS, semente=1, taxa_falha=0.0, pasta=tempfile.mkdtemp(dir=isolamento.TMP),
                            falhar_em={trt3[0]: "fisico", trt3[1]: "fisico", tj[0]: "segredo", trt3[2]: "nao_encontrado"})
        rodar = fila.rodar_fila(f, c)
        self.assertEqual((rodar["coletado"], rodar["manual"], rodar["fisico"]), (3, 4, 2))
        for n in trt3[:2]:
            item = f.item(n)
            self.assertEqual((item["estado"], item["erro"]["codigo"], item["tentativas"]), ("manual", "fisico", 1))
            self.assertIn("físico", item["motivo"])
        taxa = fila.taxa_de_sucesso(self.proj["slug"])
        self.assertEqual((taxa["coletados"], taxa["fisicos"], taxa["manuais"], taxa["eletronicos"]), (3, 2, 2, 5))
        self.assertEqual(taxa["taxa"], 0.6, "3 de 5 eletrônicos; os 2 físicos ficam fora da conta")
        cob = fila.cobertura(self.proj["slug"])
        self.assertEqual(sum(l.get("fisico", 0) for l in cob.values()), 2)
        self.assertEqual(sum(l["manual"] for l in cob.values()), 2, "físicos não entram em 'conferir à mão'")
        for l in cob.values():
            self.assertTrue({"coletado", "so_djen", "manual"} <= set(l))
        conferir = {x["numero"]: x for x in f.conferir_manualmente()}
        self.assertTrue(conferir[trt3[0]]["fisico"] and conferir[trt3[0]]["codigo"] == "fisico")
        self.assertFalse(conferir[tj[0]]["fisico"])

    def test_taxa_sem_eletronicos_e_none(self):
        f = nova_fila(self.proj, Relogio())
        f.enfileirar([self.n], modo="imediato", profundidade="rapido")
        self.assertIsNone(fila.taxa_de_sucesso(self.proj["slug"])["taxa"])

    def test_cobertura_sem_fisico_mantem_as_tres_chaves(self):
        f = nova_fila(self.proj, Relogio())
        f.enfileirar(numeros_do("TJSP", 2), modo="imediato", profundidade="rapido")
        fila.rodar_fila(f, Coletor(resolve_apos=0))
        for l in fila.cobertura(self.proj["slug"]).values():
            self.assertEqual(set(l), {"coletado", "so_djen", "manual"})

    def test_painel_mostra_os_fisicos_a_parte(self):
        from painel import entregas
        trt3 = numeros_do("TRT3", 2)
        f = nova_fila(self.proj, Relogio())
        f.enfileirar(trt3, modo="imediato", profundidade="rapido")
        from simulado import ColetorSimulado
        c = ColetorSimulado(FICHAS, semente=1, taxa_falha=0.0, pasta=tempfile.mkdtemp(dir=isolamento.TMP),
                            falhar_em={trt3[0]: "fisico", trt3[1]: "segredo"})
        fila.rodar_fila(f, c)
        itens = {i["numero"]: i for i in entregas.itens_para_conferir(f)}
        self.assertTrue(itens[trt3[0]]["fisico"])
        self.assertFalse(itens[trt3[1]]["fisico"])
        from revisao import app
        pagina = app.test_client().get("/entregas").get_data(as_text=True)
        self.assertIn("Processos físicos (1)", pagina)
        self.assertIn("processo em segredo de justiça", pagina)
        pagina = app.test_client().get("/fluxo/progresso").get_data(as_text=True)
        self.assertIn("Taxa de sucesso (só processos eletrônicos): 0 de 1", pagina)
        self.assertIn("físicos (sem autos eletrônicos)", pagina)


# ================================================================== graus: 1º, 2º e TST

class TestGraus(Base):
    def test_indicio_de_recurso(self):
        def movs(*t):
            return [("k", "01/01/2026", x) for x in t]
        self.assertIsNone(trt.indicio_de_recurso(movs("Distribuição", "Audiência realizada", "Juntada de petição")))
        for texto in ("Remetidos os autos ao Tribunal Regional do Trabalho", "Juntada de recurso ordinário",
                      "Distribuído ao relator", "Acórdão publicado", "Remessa dos autos ao 2º grau"):
            self.assertTrue(trt.indicio_de_recurso(movs("Distribuição", texto)), texto)
        self.assertIn("DataJud", trt.indicio_de_recurso(movs("Distribuição"), {"indicio_2grau": True}))
        self.assertIn("já tinha", trt.indicio_de_recurso(movs("Distribuição"), None, {"1": {}, "2": {}}))

    def test_sem_indicio_nao_tenta_o_segundo_grau(self):
        portal = portal_de(TRT7, com_segundo_grau={TRT7})
        relato = {}
        self.coletar(portal, TRT7, relato=relato)
        self.assertEqual([g for _, g in portal.graus_pedidos], ["1"])
        self.assertEqual((relato["graus_lidos"], relato["graus_falhos"]), (["1"], []))

    def test_com_indicio_le_o_segundo_grau_na_mesma_pagina(self):
        portal = portal_de(TRT7, movimentos=("Distribuição", "Remetidos os autos ao Tribunal"), com_segundo_grau={TRT7})
        relato = {}
        _, estado, lista = self.coletar(portal, TRT7, relato=relato)
        self.assertEqual(relato["graus_lidos"], ["1", "2"])
        self.assertEqual(len(portal.consultas_abertas()), 1)
        graus = {e.get("grau") for e in lista if e["tipo_evento"] == "movimento"}
        self.assertEqual(graus, {"1º grau", "2º grau"})
        self.assertEqual(set(estado[TRT7]["trt"]), {"1", "2"})
        self.assertFalse([g for g in portal.gotos if "/detalhe-processo/" in g and g.endswith("/2")], "pela rota da aplicação, sem recarregar")

    def test_indicio_do_datajud_basta(self):
        portal = portal_de(TRT7, com_segundo_grau={TRT7})
        relato = {}
        self.coletar(portal, TRT7, proc_extra={"indicio_2grau": True}, relato=relato)
        self.assertEqual(relato["graus_lidos"], ["1", "2"])

    def test_falha_no_segundo_grau_nao_e_engolida(self):
        portal = portal_de(TRT7, movimentos=("Distribuição", "Remetidos os autos ao Tribunal"), com_segundo_grau={TRT7}, falha_grau2=True)
        relato = {}
        baixados, estado, lista = self.coletar(portal, TRT7, relato=relato)
        self.assertEqual(relato["graus_lidos"], ["1"])
        self.assertEqual([f["grau"] for f in relato["graus_falhos"]], ["2"])
        aviso = relato["avisos"][0]
        self.assertEqual((aviso["codigo"], aviso["nivel"]), ("grau_nao_lido", "atencao"))
        self.assertIn("Remetidos", aviso["mensagem"])
        self.assertIn("Timeout", aviso["mensagem"])
        self.assertTrue([e for e in lista if e["tipo_evento"] == "movimento"], "o 1º grau lido segue valendo")

    def test_coletor_real_repassa_graus_e_avisos(self):
        real = fila.ColetorReal()
        real._contexto = object()

        def falso(contexto, proc, estado, lista, historico, cota, desde=None, relato=None):
            relato.update(graus_lidos=["1"], graus_falhos=[{"grau": "2", "motivo": "x"}],
                          avisos=[{"nivel": "atencao", "codigo": "grau_nao_lido", "onde": "trt", "mensagem": "m"}])
            return 0
        with mock.patch.object(coletor, "coletar_processo", side_effect=falso), \
                mock.patch.object(capa, "_config_datajud", return_value=(False, None)):
            r = real.coletar({"numero": TRT7, "cliente": "x"}, "rapido", None)
        self.assertEqual(r["graus"], {"lidos": ["1"], "falhos": [{"grau": "2", "motivo": "x"}]})
        self.assertEqual(r["avisos"][0]["codigo"], "grau_nao_lido")

    def test_resultado_com_aviso_e_graus_chega_ao_relatorio(self):
        import fluxos
        resultado = {"capa": {}, "movimentos": [], "documentos": [], "erro": None, "no_tst": True,
                     "graus": {"lidos": ["1"], "falhos": [{"grau": "2", "motivo": "x"}]},
                     "avisos": [{"nivel": "atencao", "codigo": "grau_nao_lido", "onde": f"trt/{FICHAS[0]['numero']}", "mensagem": "m"}]}
        fluxos.processar_resultado(self.proj["slug"], FICHAS[0]["numero"], resultado)
        ciclo = fluxos._estado()["ciclo"]
        self.assertEqual([a["codigo"] for a in ciclo["avisos"]], ["grau_nao_lido"])
        f0 = next(f for f in __import__("ficha").carregar(todas=True) if f["numero"] == FICHAS[0]["numero"])
        self.assertTrue(f0["ultima_coleta"]["no_tst"])
        self.assertEqual(f0["ultima_coleta"]["graus"]["lidos"], ["1"])


class TestTST(unittest.TestCase):
    NUMERO = TRT7
    DIGITOS = "".join(c for c in TRT7 if c.isdigit())

    def dados_tst(self):
        return {"hits": {"hits": [{"_source": {"numeroProcesso": self.DIGITOS, "grau": "SUP", "tribunal": "TST", "movimentos": [
            {"codigo": 26, "nome": "Distribuição", "dataHora": "2026-09-01T10:00:00.000Z",
             "complementosTabelados": [{"nome": "Ministro Fulano"}]},
            {"codigo": 123, "nome": "Recebimento", "dataHora": "2026-09-02T09:00:00.000Z"}]}}]}}

    def test_datajud_do_tst(self):
        dados = self.dados_tst()
        self.assertTrue(capa.no_tst(dados, self.NUMERO))
        self.assertFalse(capa.no_tst({"hits": {"hits": []}}, self.NUMERO))
        movs = capa.movimentos_do_tst(dados, self.NUMERO)
        self.assertEqual([(m["data"], m["grau"]) for m in movs], [("2026-09-01", "TST"), ("2026-09-02", "TST")])
        self.assertEqual(len({m["chave"] for m in movs}), 2)
        self.assertIn("Ministro Fulano", movs[0]["texto"])

    def test_so_trabalhista_consulta_o_tst(self):
        self.assertEqual(capa.consultar_tst("1234567-06.2026.8.06.0001"), (None, []))
        chamado = {}

        def transporte(url, cab, corpo):
            chamado["url"] = url
            return 200, json.dumps(self.dados_tst()).encode()
        dados, avisos = capa.consultar_tst(self.NUMERO, transporte=transporte, ativo=True, chave="k", dormir=lambda s: None)
        self.assertIn("api_publica_tst", chamado["url"])
        self.assertTrue(capa.no_tst(dados, self.NUMERO))

    def test_graus_do_datajud_e_indicio(self):
        dados = {"hits": {"hits": [{"_source": {"numeroProcesso": self.DIGITOS, "grau": "G1"}},
                                   {"_source": {"numeroProcesso": self.DIGITOS, "grau": "G2"}}]}}
        self.assertEqual(capa.graus_do_datajud(dados, self.NUMERO), ["G1", "G2"])
        self.assertTrue(capa.indica_segundo_grau(dados, self.NUMERO))
        self.assertFalse(capa.indica_segundo_grau({"hits": {"hits": [dados["hits"]["hits"][0]]}}, self.NUMERO))

    def test_coletor_real_acrescenta_os_movimentos_do_tst(self):
        resultado = {"capa": {}, "movimentos": [{"data": "2026-08-01", "texto": "x", "grau": "2º grau", "chave": "k"}],
                     "documentos": [], "erro": None}
        with mock.patch.object(capa, "_config_datajud", return_value=(True, "k")), \
                mock.patch.object(capa, "consultar_tst", return_value=(self.dados_tst(), [])):
            fila._acrescentar_tst(resultado, self.NUMERO)
        self.assertTrue(resultado["no_tst"])
        self.assertEqual([m["grau"] for m in resultado["movimentos"]], ["2º grau", "TST", "TST"])
        self.assertEqual(resultado["avisos"][0]["codigo"], "no_tst")
        # repetir não duplica
        with mock.patch.object(capa, "_config_datajud", return_value=(True, "k")), \
                mock.patch.object(capa, "consultar_tst", return_value=(self.dados_tst(), [])):
            fila._acrescentar_tst(resultado, self.NUMERO)
        self.assertEqual(len(resultado["movimentos"]), 3)

    def test_sem_datajud_nada_muda(self):
        resultado = {"capa": {}, "movimentos": [], "documentos": [], "erro": None}
        with mock.patch.object(capa, "_config_datajud", return_value=(False, None)):
            fila._acrescentar_tst(resultado, self.NUMERO)
        self.assertNotIn("no_tst", resultado)

    def test_vocabulario_e_momento_no_tst(self):
        self.assertIn("TST", taxonomia.GRAUS)
        movs = [{"data": "2026-08-01", "texto": "Juntada de recurso de revista", "grau": "2º grau"},
                {"data": "2026-09-01", "texto": "Distribuído ao Ministro Fulano", "grau": "TST"}]
        momento, _ = taxonomia.momento_por_regras(movs)
        self.assertEqual(momento, "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA")
        movs = [{"data": "2026-09-01", "texto": "Distribuído", "grau": "TST"}]
        momento, evidencia = taxonomia.momento_por_regras(movs)
        self.assertEqual(momento, "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA")
        self.assertIn("movimento do TST", evidencia)
        movs = [{"data": "2026-09-01", "texto": "Distribuído", "grau": "2º grau"}]
        self.assertNotEqual(taxonomia.momento_por_regras(movs)[0], "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA")

    def test_julgamento_trata_tst_como_grau_acima_do_segundo(self):
        import julgamento
        self.assertEqual(julgamento._grau_declarado({"grau": "TST"}), 3)
        self.assertEqual(julgamento._grau_declarado({"grau": "2º grau"}), 2)
        self.assertEqual(julgamento._grau_declarado({"grau": None}), 1)


# ================================================================== texto da IA local: explicar o andamento

class TestEstiloDaIA(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS[:1])
        self.proj = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def test_o_pedido_exige_motivo_efeito_e_dados_concretos(self):
        import resumir
        pedido = resumir.montar_pedido("texto", "Sentença", "juizo", "Foi proferida sentença", {"cliente": "X", "polo": "ativo"})
        self.assertIn(f"{resumir.LIMITE_PALAVRAS} palavras", pedido)
        self.assertNotIn("até 40 palavras", pedido)
        for exigencia in ("por quê", "o que muda na prática", "valores em reais", "prazos"):
            self.assertIn(exigencia, pedido)
        self.assertIn("gerúndio", pedido)
        self.assertIn("MOTIVO", resumir.SISTEMA_BASE.upper())
        self.assertIn("frases vagas", resumir.SISTEMA_BASE)

    def test_exemplos_do_escritorio_entram_no_sistema(self):
        import resumir
        self.assertEqual(resumir.sistema(), resumir.SISTEMA_BASE)
        arquivo = comum.PROJETO_DIR / "estilo.md"
        arquivo.write_text("Em 10/09/2026, foi proferida sentença, que acolheu o pedido por falta de prova do pagamento.", encoding="utf-8")
        self.assertIn("falta de prova do pagamento", resumir.sistema())
        self.assertIn("Modelo de redação do escritório", resumir.sistema())
        arquivo.unlink()
        with mock.patch.object(resumir, "config", return_value={"estilo_redacao": "Exemplo do config."}):
            self.assertIn("Exemplo do config.", resumir.sistema())

    def test_o_provedor_recebe_o_sistema_com_o_estilo(self):
        import resumir
        (comum.PROJETO_DIR / "estilo.md").write_text("Exemplo X de redação.", encoding="utf-8")
        recebidos = []

        class Prov:
            def gerar(self, sistema, usuario, *, esquema=None, cliente=""):
                recebidos.append(sistema)
                return {"json": {"conteudo": "julgando procedente o pedido da inicial por falta de defesa e condenando a ré a pagar R$ 1.000,00",
                                 "trecho_origem": "JULGO PROCEDENTE o pedido formulado na inicial", "prazo": None,
                                 "audiencia": None, "efeito": "neutro"}, "motor": "falso"}
        resumir.resumir_com_provedor(Prov(), "SENTENÇA\nJULGO PROCEDENTE o pedido formulado na inicial, condenando a ré.", "Sentença",
                                     "juizo", "Foi proferida sentença", {"cliente": "X", "polo": "ativo"})
        self.assertIn("Exemplo X de redação.", recebidos[0])

    def test_resumo_curto_demais_vai_para_a_revisao(self):
        import resumir
        texto = "DECISÃO\nDefiro o pedido de dilação de prazo formulado pela parte autora para juntada de documentos."
        curto = {"conteudo": "deferindo o pedido", "trecho_origem": "Defiro o pedido de dilação de prazo formulado pela parte autora",
                 "prazo": None, "audiencia": None, "efeito": "neutro"}
        self.assertTrue(any("curto demais" in a for a in resumir.conferir(curto, texto)))
        bom = {**curto, "conteudo": "deferindo o pedido de mais prazo feito pela parte autora para juntar documentos, o que adia a decisão"}
        self.assertFalse(any("curto demais" in a for a in resumir.conferir(bom, texto)))
        vazio = {**curto, "conteudo": "Não foi possível identificar o conteúdo."}
        self.assertFalse(any("curto demais" in a for a in resumir.conferir(vazio, texto)))


# ================================================================== diagnóstico anonimizado da rodada

class TestDiagnostico(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS[:1])
        self.proj = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def test_conta_sem_vazar_numero_nem_nome(self):
        import diagnostico_rodada as dr
        data = comum.DATA
        (data / "logs").mkdir(parents=True, exist_ok=True)
        (data / "logs" / "r1.log").write_text("\n".join([
            f"{TRT7} (Cliente Fulano)", "CAPTCHA na consulta do TRT: resolva na janela que apareceu.",
            "  tempo: busca 12.5 s", "  tempo: documentos 30.0 s",
            "1234568-72.2024.5.07.0001 (Cliente Fulano)", "CAPTCHA na consulta do TRT 7: resolva na janela",
            "1234567-06.2026.8.06.0001 (Cliente Fulano)", "  falhou: Processo em segredo de justiça: sem acesso a autos de MARIA DA SILVA SOUZA",
            "Login automático não concluiu (tentativa 1 de 2): O diálogo do PJe Office de /Users/fulano/x não apareceu.",
            "O diálogo do PJe Office não apareceu. Confira se o PJe Office está aberto.", "Termine o login no jus.br na janela que apareceu.",
            "Login concluído.", "  tramitação: 2º grau"]), encoding="utf-8")
        itens = {}
        for k, (n, trib, estado, codigo) in enumerate([(TRT7, "TRT7", "coletado", None), (TRT7_B, "TRT7", "manual", "captcha"),
                                                       ("1234568-72.2024.5.07.0001", "TRT7", "manual", "fisico"),
                                                       ("1234567-06.2026.8.06.0001", "TJCE", "manual", "nao_encontrado")]):
            itens[n] = {"numero": n, "tribunal": trib, "estado": estado, "erro": {"codigo": codigo} if codigo else None,
                        "duracao_s": 40.0 if estado == "coletado" else None, "proxima_tentativa": None}
        comum.save_json(data / "fila.json", {"itens": itens})
        comum.save_json(data / "eventos.json", [
            {"tipo_evento": "movimento", "numero": TRT7, "titulo": "Remetidos os autos ao Tribunal", "alertas": []},
            {"tipo_evento": "movimento", "numero": TRT7, "titulo": "Expedida notificação para JOAO DE TAL em 12/09/2026",
             "alertas": ["Movimentação sem tradução cadastrada: reescrever"]}])
        comum.save_json(data / "estado_coleta.json", {TRT7: {"trt": {"1": {}}}})
        texto = dr.montar()
        self.assertNotIn("1234567", texto)
        self.assertNotIn("MARIA", texto)
        self.assertNotIn("JOAO", texto)
        self.assertNotIn("/Users/fulano", texto)
        self.assertIn("<NOME>", texto)
        self.assertIn("| TRT 7 | 2 |", texto, "dois captchas do TRT 7")
        self.assertIn("1º processo do bloco", texto)
        self.assertIn("2º processo do bloco em diante", texto)
        self.assertIn("Físicos marcados (beta 3) | 1", texto)
        self.assertIn("1 de 3 (33%)", texto, "1 coletado de 3 eletrônicos: o físico fica fora da conta")
        self.assertIn("busca | 1 | 12.5 s", texto)
        self.assertIn("| concluidos | 1 |", texto)
        self.assertIn("Processos de TRT com andamento que indica recurso: 1; destes, sem o 2º grau lido: 1", texto)
        self.assertIn("Expedida notificação para <NOME>", texto)

    def test_mascara(self):
        import diagnostico_rodada as dr
        m = dr.mascarar(f"Juntada de petição de FULANO DE TAL no processo {TRT7} valor R$ 1.234,56 em 12/09/2026")
        self.assertEqual(m, "Juntada de petição de <NOME> no processo <proc> valor R$ # em ##/##/####")


if __name__ == "__main__":
    unittest.main()
