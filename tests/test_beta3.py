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
        self.assertIn("beep 2", scripts, "bipe que não depende da permissão de notificações")
        self.assertFalse(any('contains "Chrom"' in x for x in scripts), "nunca traz o Chrome pessoal para a frente")
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

    def test_login_clica_em_permitir_do_navegador_enquanto_espera_o_dialogo(self):
        # sem esse clique o PJe Office nunca é chamado e o diálogo da senha não aparece (login manual, 08/10/2026)
        page = mock.Mock()
        page.inner_text.return_value = "Sair do portal"
        estados = iter([False, False, True, True])
        with mock.patch.object(acesso, "obter", return_value="x"), mock.patch.object(acesso, "_clicar_certificado", return_value=True), \
                mock.patch.object(acesso, "_dialogo_aberto", side_effect=lambda: next(estados)), mock.patch.object(acesso.time, "sleep"), \
                mock.patch.object(acesso, "liberar_permissao_do_navegador", return_value=True) as liberar, \
                mock.patch.object(acesso, "_preencher_dialogo", return_value=True):
            self.assertTrue(acesso.login_automatico(page))
        liberar.assert_called()

    def test_falha_do_dialogo_registra_os_titulos_das_janelas_do_pje(self):
        page = mock.Mock()
        with mock.patch.object(acesso, "obter", return_value="x"), mock.patch.object(acesso, "_clicar_certificado", return_value=True), \
                mock.patch.object(acesso, "_dialogo_aberto", return_value=False), mock.patch.object(acesso.time, "sleep"), \
                mock.patch.object(acesso, "liberar_permissao_do_navegador", return_value=False), \
                mock.patch.object(acesso, "janelas_do_pje_office", return_value=["Atualização disponível"]), \
                mock.patch.object(acesso, "pje_office_aberto", return_value=True):
            self.assertFalse(acesso.login_automatico(page, limite_dialogo=0))
        self.assertEqual(acesso.ULTIMO["janelas_do_pje"], ["Atualização disponível"])

    def test_permissao_do_navegador_so_toca_no_navegador_da_automacao(self):
        class R:
            returncode, stdout, stderr = 0, "OK\n", ""
        with mock.patch.object(acesso, "MAC", True), mock.patch.object(acesso.subprocess, "run", return_value=R()) as run:
            self.assertTrue(acesso.liberar_permissao_do_navegador())
        script = run.call_args[0][0][2]
        self.assertIn("Google Chrome for Testing", script)
        self.assertIn('"Permitir"', script)
        self.assertNotIn('contains "Chrom"', script, "nunca o Chrome pessoal")
        with mock.patch.object(acesso, "MAC", False):
            self.assertFalse(acesso.liberar_permissao_do_navegador())

    def test_dialogo_da_senha_e_achado_por_parte_do_titulo(self):
        class R:
            returncode, stdout, stderr = 0, "true\n", ""
        with mock.patch.object(acesso, "MAC", True), mock.patch.object(acesso.subprocess, "run", return_value=R()) as run:
            self.assertTrue(acesso._dialogo_aberto())
        self.assertIn('contains "senha"', run.call_args[0][0][2])

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
        self.assertLessEqual(set(motivo), {"passo", "mensagem", "o_que_fazer", "pje_office_aberto", "acessibilidade", "janelas_do_pje", "tentativa",
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
        """A aba Atualizar (coletor.rodar) loga por coletor.logar; a fila (ColetorReal) só loga quando um processo precisa
        (coletor.garantir_login, que também passa por coletor.logar): abrir o navegador sozinho não loga."""
        chamadas = []
        fake_pw = mock.MagicMock()
        with mock.patch.object(coletor, "logar", side_effect=lambda ctx: (chamadas.append("logar"), coletor._LOGADOS.add(id(ctx)))), \
                mock.patch.object(janela, "abrir_navegador", return_value=(mock.Mock(), mock.Mock())), \
                mock.patch("playwright.sync_api.sync_playwright", return_value=fake_pw):
            real = fila.ColetorReal()
            real.abrir()
            self.assertEqual(chamadas, [], "abrir o navegador não faz login no jus.br")
            real._contexto = object()
            coletor.garantir_login(real._contexto)
            coletor.garantir_login(real._contexto)                 # uma vez só por navegador
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

    def __init__(self, autos, captcha_na_primeira=0, captcha_nunca_resolvido=False, falha_grau2=False,
                 escolha_de_grau=False, com_tst=False, sem_pdf=()):
        self.autos = autos                      # {(numero, grau): corpo}
        self.escolha_de_grau = escolha_de_grau  # a pesquisa devolve a tela "N processos encontrados: 1° Grau / 2° Grau"
        self.com_tst = com_tst
        self.sem_pdf = set(sem_pdf)             # ids de documentos cujo PDF o portal não entrega
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


class BotaoDeGrau:
    def __init__(self, page, numero, grau):
        self.page, self.numero, self.grau = page, numero, grau

    def is_visible(self):
        return self.page.estado == "escolha"

    def inner_text(self):
        rotulo = "TST\nAIRR-" if self.grau == "tst" else f"{self.grau}° Grau\nATOrd-"
        return f" {rotulo}{self.numero} "

    def click(self, **k):
        if self.grau == "tst":
            return
        self.page.estado, self.page.url = "detalhe", f"https://pje.trt7.jus.br/consultaprocessual/detalhe-processo/{self.numero}/{self.grau}"
        self.page.abrir_detalhe(self.numero, self.grau)


class BotoesDeGrau:
    def __init__(self, page):
        self.page = page

    def lista(self):
        p = self.page
        if p.estado != "escolha" or p.captcha:
            return []
        graus = sorted(g for n, g in p.portal.autos if n == p.numero_escolha)
        return graus + (["tst"] if p.portal.com_tst else [])

    def count(self):
        return len(self.lista())

    def nth(self, i):
        return BotaoDeGrau(self.page, self.page.numero_escolha, self.lista()[i])


class PaginaFalsa:
    def __init__(self, portal):
        self.portal, self.url, self.estado, self.captcha = portal, "about:blank", "vazia", False
        self.digitado, self.fechada, self.aberta_na_consulta = "", False, False
        self.historico = []
        self.numero_escolha = None
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
                if unico[1:] in self.portal.sem_pdf:
                    return
                self.portal.emitir(RespostaFalsa(f"https://pje.trt7.jus.br/pje-consulta-api/api/processos/{numero}/documentos/{unico[1:]}",
                                                 pdf=b"%PDF-1.4 ficticio"))
            else:
                self.abrir_detalhe(numero, grau)

    def reload(self, **k):
        if self.estado == "login":
            self.estado, self.url = "consulta", "https://pje.trt7.jus.br/consultaprocessual/"
            self.aberta_na_consulta = True

    def go_back(self, **k):
        if self.estado == "detalhe" and self.portal.escolha_de_grau and self.numero_escolha:
            self.estado, self.url = "escolha", "https://pje.trt7.jus.br/consultaprocessual/lista-processo"
        elif self.estado in ("detalhe", "escolha"):
            self.estado, self.url = "consulta", "https://pje.trt7.jus.br/consultaprocessual/"

    def pesquisar(self):
        self.portal.pesquisas.append(self.digitado)
        numero = next(n for n, _ in self.portal.autos if "".join(c for c in n if c.isdigit()) == self.digitado)
        if self.portal.escolha_de_grau and sum(1 for n, _ in self.portal.autos if n == numero) + int(self.portal.com_tst) > 1:
            self.estado, self.numero_escolha = "escolha", numero
            self.url = "https://pje.trt7.jus.br/consultaprocessual/lista-processo"
            return
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
        if "selecao-processo" in sel:
            return BotoesDeGrau(self)
        return FakeLocator(self, sel)

    def get_by_role(self, *a, **k):
        return FakeLocator(self, "__nada__")

    def inner_text(self, sel):
        if self.estado == "escolha" and not self.captcha:
            return "2 processos encontrados: 1° Grau 2° Grau"
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
                     mock.patch.object(coletor, "pausa"),
                     mock.patch.object(coletor, "garantir_login")):          # o login do jus.br é de verdade: nunca nos testes
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

    def test_tela_de_escolha_de_grau_abre_o_primeiro_e_le_o_segundo_pela_lista(self):
        # TRT 7 / TRT 22 em 08/10/2026: a pesquisa devolve "N processos encontrados" e os autos só vêm ao clicar
        portal = portal_de(TRT7, com_segundo_grau={TRT7}, escolha_de_grau=True, com_tst=True)
        relato = {}
        _, estado, lista = self.coletar(portal, TRT7, relato=relato)
        self.assertEqual(relato["graus_lidos"], ["1", "2"])
        self.assertEqual(relato["graus_disponiveis"], ["1", "2", "tst"])
        self.assertEqual(len(portal.pesquisas), 2, "o 2º grau sai de nova pesquisa + clique no botão do 2º grau")
        self.assertFalse([g for g in portal.gotos if "/detalhe-processo/" in g and "#" not in g], "sem recarregar")
        self.assertEqual({e.get("grau") for e in lista if e["tipo_evento"] == "movimento"}, {"1º grau", "2º grau"})

    def test_tela_de_escolha_sem_segundo_grau_le_so_o_primeiro(self):
        portal = portal_de(TRT7, escolha_de_grau=True, com_tst=True)
        relato = {}
        self.coletar(portal, TRT7, relato=relato)
        self.assertEqual(relato["graus_lidos"], ["1"])
        self.assertEqual(len(portal.pesquisas), 1)

    def test_coletor_real_marca_no_tst_quando_a_consulta_lista_o_tst(self):
        real = fila.ColetorReal()
        real._contexto = object()

        def falso(contexto, proc, estado, lista, historico, cota, desde=None, relato=None):
            relato.update(graus_lidos=["1"], graus_disponiveis=["1", "tst"])
            return 0
        with mock.patch.object(coletor, "coletar_processo", side_effect=falso), \
                mock.patch.object(capa, "_config_datajud", return_value=(False, None)):
            r = real.coletar({"numero": TRT7, "cliente": "x"}, "rapido", None)
        self.assertTrue(r["no_tst"])

    def test_chave_do_grau(self):
        self.assertEqual([trt._chave_do_grau(t) for t in (" 1° Grau\n ATOrd-x", "2º Grau ROT-x", "TST\nAIRR-x", "outra")],
                         ["1", "2", "tst", "?"])

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


# ================================================================== estilo dos andamentos (parâmetros do relatório modelo)

class TestEstiloDosAndamentos(unittest.TestCase):
    PADRAO = ("Execução de cotas condominiais ajuizada contra o proprietário da unidade 000 pelo não pagamento de R$ 3.000,00 "
              "(janeiro a março/2026). Rejeitada a exceção de pré-executividade em 10/05/2026, com determinação de prosseguimento. "
              "O executado depositou R$ 1.000,00 como pagamento parcial, o que impugnamos por insuficiência, requerendo o "
              "prosseguimento pelo saldo de R$ 2.000,00; em 15/07/2026, o Juízo autorizou o levantamento do valor incontroverso. "
              "Em 02/09/2026, apresentamos nova memória de cálculo. Em 18/09/2026, sem atualizações.")

    def codigos(self, texto, base=None):
        import estilo_andamentos as ea
        return [a["codigo"] for a in ea.avaliar(texto, base)]

    def test_texto_no_padrao_nao_tem_aviso(self):
        self.assertEqual(self.codigos(self.PADRAO, "18/09/2026"), [])

    def test_metricas(self):
        import estilo_andamentos as ea
        m = ea.metricas(self.PADRAO)
        self.assertTrue(m["abertura_sem_data"])
        self.assertEqual((m["valores"], m["datas"]), (3, 3))
        self.assertGreaterEqual(m["primeira_pessoa_plural"], 2)
        self.assertEqual(m["atos_datados"], 1, "só os atos que abrem a oração com 'Em DD/MM/AAAA,' (o fecho não conta)")

    def test_cada_desvio_gera_o_seu_aviso(self):
        self.assertIn("estilo_curto", self.codigos("Deferida a tutela em 10/05/2026."))
        self.assertIn("estilo_longo", self.codigos(("Em 10/05/2026, deferida a tutela. " * 60)))
        self.assertIn("estilo_data_por_extenso", self.codigos(self.PADRAO.replace("10/05/2026", "10 de maio de 2026")))
        self.assertIn("estilo_sem_data", self.codigos("Ação de cobrança com tutela deferida e depósito parcial do valor devido pela parte contrária, "
                                                      "seguida de contestação, réplica e pedido de prova pericial, ainda sem decisão sobre o objeto da perícia."))
        self.assertIn("estilo_fora_de_ordem", self.codigos("Ação de cobrança ajuizada pelo condomínio contra o proprietário, com pedido de tutela "
                                                           "deferido em seguida pelo Juízo e depois contestado. Em 05/09/2026, requeremos prazo. "
                                                           "Em 02/03/2026, apresentamos réplica e documentos novos sobre os pagamentos alegados."))
        self.assertIn("estilo_voz_do_escritorio", self.codigos(self.PADRAO.replace("apresentamos", "o escritório apresentou")))
        self.assertIn("estilo_frase_vaga", self.codigos(self.PADRAO.replace("Rejeitada a exceção", "Analisando o pedido, rejeitada a exceção")))
        self.assertIn("estilo_fecho_data_base", self.codigos(self.PADRAO, "25/09/2026"))
        self.assertEqual(self.codigos(""), ["estilo_vazio"])

    def test_colher_agrega_sem_dado_identificavel(self):
        import estilo_andamentos as ea
        lido = {"processos": [{"andamentos_texto": self.PADRAO.replace(" Em 18/09/2026, sem atualizações.", ""), "fecho": "x"},
                              {"andamentos_texto": "Deferida a tutela em 10/05/2026.", "fecho": None}]}
        with mock.patch("leitores.ler", return_value=lido):
            r = ea.colher("qualquer.docx")
        self.assertEqual((r["textos"], r["com_fecho"], r["abertura_participial"]), (2, 1, 1))
        self.assertIn(("estilo_curto", 1), [tuple(x) for x in r["fora_do_padrao"]])
        self.assertNotIn("unidade 000", json.dumps(r, ensure_ascii=False))

    def test_momentos_do_relatorio_modelo_no_vocabulario(self):
        for momento in ("AGUARDANDO CITAÇÃO DO EXECUTADO", "AGUARDANDO PAGAMENTO DO SALDO DEVEDOR"):
            self.assertIn(momento, taxonomia.MOMENTO_ATUAL)
            self.assertEqual(taxonomia.normalizar_momento(momento)[0], momento)

    def test_pedido_a_ia_traz_o_padrao_do_escritorio(self):
        import resumir
        for trecho in ("DD/MM/AAAA", "primeira pessoa do plural", "R$ 1.979,91", "nunca cite jurisprudência"):
            self.assertIn(trecho, resumir.SISTEMA_BASE)
        self.assertNotIn("Não cite número de lei", resumir.SISTEMA_BASE)


# ================================================================== relatório de contingências (planilha fora do modelo)

def planilha_de_contingencias(caminho, com_data_base=False):
    """Planilha FICTÍCIA no formato 'contingências' do escritório: título nas 3 primeiras linhas, cabeçalho na linha 5,
    partes numa só coluna 'AUTOR/RECLAMANTE', histórico em 'OBSERVAÇÃO' e colunas próprias (passivo, provisão)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Relatório Cliente Teste"
    ws["A1"], ws["A2"], ws["A3"] = "CLIENTE TESTE", "Acompanhamento de Passivo", "Mês: Setembro- 2026"
    cab = ["AUTOR/RECLAMANTE", "RÉU/RECLAMADO", "PROCESSO Nº.", "NATUREZA DA AÇÃO", "PASSIVO POTENCIAL ", "POSSIBILIDADE DE PERDA ",
           "PROVISÃO CONSTITUÍDA", "BREVE RESUMO DO CASO", "OBSERVAÇÃO"]
    for j, c in enumerate(cab, 1):
        ws.cell(5, j, c)
    historico = ("Ação de cobrança ajuizada pelo autor contra a empresa, com pedido de tutela de urgência indeferido. Em 10/03/2026, "
                 "apresentamos contestação e documentos novos sobre os pagamentos alegados. Em 15/04/2026, o Juízo designou audiência "
                 "de conciliação, que restou sem acordo. Em 20/05/2026, requeremos o julgamento antecipado da lide. "
                 + ("Em 18/09/2026, sem atualizações." if com_data_base else "Em 12/06/2026, foi proferida sentença de improcedência."))
    for k, num in enumerate(["1234567-06.2026.8.06.0001", "1234568-72.2024.4.05.8100", "1234569-95.2026.5.07.0001"]):
        r = 6 + k
        ws.cell(r, 1, f"Autor Fictício {k}"); ws.cell(r, 2, "Empresa Ré Fictícia S.A."); ws.cell(r, 3, num)
        ws.cell(r, 4, "Cobrança"); ws.cell(r, 5, "R$ 10.000,00"); ws.cell(r, 6, "REMOTA - improcedência"); ws.cell(r, 7, "R$ 2.000,00")
        ws.cell(r, 8, "Resumo curto do caso fictício."); ws.cell(r, 9, historico)
    wb.save(caminho)


class TestPlanilhaDeContingencias(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=isolamento.TMP))
        self.arq = self.tmp / "contingencias.xlsx"

    def test_leitor_reconhece_partes_resumo_e_historico(self):
        import leitores
        planilha_de_contingencias(self.arq, com_data_base=True)
        rel = leitores.ler(self.arq)
        self.assertEqual((rel["formato"], len(rel["processos"])), ("tabela_livre", 3))
        mapa = {m["coluna"].strip(): (m["campo"], m["aplicado"]) for m in rel["mapeamento"]}
        self.assertEqual(mapa["AUTOR/RECLAMANTE"], ("autores", True))
        self.assertEqual(mapa["RÉU/RECLAMADO"], ("reus", True))
        self.assertEqual(mapa["BREVE RESUMO DO CASO"], ("objeto", True))
        self.assertEqual(mapa["OBSERVAÇÃO"], ("andamentos", True), "o histórico é reconhecido pelo conteúdo")
        p = rel["processos"][0]
        self.assertEqual(len(p["andamentos"]), 3)
        self.assertEqual(rel["data_base"], "2026-09-18", "sem data-base escrita, vale a data do fecho 'sem atualizações'")
        self.assertIn("data_base_deduzida", [a["codigo"] for a in rel["avisos"]])
        nao_lidas = {c["coluna"].strip() for c in rel["colunas_sem_destino"]}
        self.assertIn("PROVISÃO CONSTITUÍDA", nao_lidas, "coluna própria do cliente não se perde: vai para 'campos não migrados'")

    def test_observacao_comum_continua_observacao(self):
        import leitores
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        for j, c in enumerate(["Processo", "Autor", "Réu", "Observação"], 1):
            ws.cell(1, j, c)
        for k in range(4):
            ws.cell(2 + k, 1, ["1234567-06.2026.8.06.0001", "1234568-72.2024.4.05.8100", "1234569-95.2026.5.07.0001", "1234570-71.2025.8.06.0001"][k])
            ws.cell(2 + k, 2, "Autor"); ws.cell(2 + k, 3, "Réu"); ws.cell(2 + k, 4, "Ligar para o cliente")
        wb.save(self.tmp / "simples.xlsx")
        rel = leitores.ler(self.tmp / "simples.xlsx")
        mapa = {m["coluna"]: m["campo"] for m in rel["mapeamento"]}
        self.assertEqual(mapa["Observação"], "observacoes")

    def _painel(self):
        from revisao import app, TOKEN
        return app.test_client(), TOKEN

    def _enviar(self, c, token, rota, campo="arquivos"):
        r = c.post(rota, data={"token": token, campo: (open(self.arq, "rb"), "contingencias.xlsx")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        return r.headers["Location"]

    def test_importar_avisa_da_planilha_fora_do_modelo_e_deixa_mapear(self):
        planilha_de_contingencias(self.arq, com_data_base=True)
        with ficticio.projeto_de_teste(FICHAS[:1]):
            c, token = self._painel()
            loc = self._enviar(c, token, "/fluxo/importar/enviar")
            pagina = c.get(loc).get_data(as_text=True)
            self.assertIn("Planilha fora do modelo do programa", pagina)
            self.assertIn("/fluxo/mapear?lote=", pagina)
            self.assertIn("/fluxo/migrar?lote=", pagina)
            lote = loc.split("lote=")[1]
            mapa = c.get(f"/fluxo/mapear?lote={lote}").get_data(as_text=True)
            self.assertIn("PROVISÃO CONSTITUÍDA", mapa)
            # a pessoa manda a provisão para "custas" e tira o resumo do caso; o resto fica como o programa propôs
            import re as _re
            form = {"token": token, "lote": lote}
            for i, nome, bloco in _re.findall(r"name='col_(\d+)' value='([^']*)'.*?<select name='map_\d+'>(.*?)</select>", mapa, flags=_re.S):
                marcado = _re.search(r"<option value='([^']*)' selected>", bloco)
                form[f"col_{i}"] = nome.replace("&amp;", "&")
                form[f"map_{i}"] = {"PROVISÃO CONSTITUÍDA": "custas", "BREVE RESUMO DO CASO": ""}.get(nome.strip(), marcado.group(1) if marcado else "")
            sem_numero = {k: ("" if v == "numero" else v) for k, v in form.items()}
            r = c.post("/fluxo/mapear", data=sem_numero)
            self.assertIn("mapear?lote=", r.headers["Location"], "sem a coluna do número, volta com explicação")
            r = c.post("/fluxo/mapear", data=form)
            self.assertEqual(r.status_code, 302)
            self.assertIn("conferir?lote=", r.headers["Location"])
            pagina = c.get(r.headers["Location"]).get_data(as_text=True)
            self.assertIn("Mapeamento aplicado", pagina)
            fichas = comum.load_json(next(Path(isolamento.TMP).rglob(f"{lote}/fichas.json")), [])
            self.assertEqual(len(fichas), 3)
            f0 = next(f for f in fichas if f["numero"] == "1234567-06.2026.8.06.0001")
            import ficha as _ficha
            self.assertTrue(_ficha.obter(f0, "autores"))
            self.assertTrue(_ficha.obter(f0, "custas"), "a provisão foi mapeada para custas pela pessoa")
            self.assertFalse(_ficha.obter(f0, "objeto"), "o resumo do caso foi desmarcado")
            self.assertTrue(f0.get("linha_de_base"), "o histórico da coluna Observação virou a linha de base")

    def test_planilha_do_mes_com_planilha_fora_do_modelo_explica_em_vez_de_dar_erro_500(self):
        planilha_de_contingencias(self.arq, com_data_base=True)       # sem a aba "Processos"
        with ficticio.projeto_de_teste(FICHAS[:1]):
            c, token = self._painel()
            r = c.post("/planilha", data={"token": token, "modelo": (open(self.arq, "rb"), "contingencias.xlsx")},
                       content_type="multipart/form-data")
            self.assertEqual(r.status_code, 302)
            pagina = c.get(r.headers["Location"]).get_data(as_text=True)
            self.assertIn("Não consegui gerar a partir desta planilha", pagina)
            self.assertIn("/fluxo/atualizar", pagina)

    def test_aba_atualizar_oferece_o_fluxo_por_arquivo_e_o_historico_da_primeira_vez(self):
        with ficticio.projeto_de_teste(FICHAS[:1]):
            c, _ = self._painel()
            pagina = c.get("/atualizar").get_data(as_text=True)
            self.assertIn("/fluxo/atualizar", pagina)
            self.assertIn("/migracao", pagina)
            self.assertIn("name='historico' value='5'", pagina, "sem data, a 1ª atualização baixa os mais recentes, não só registra")

    def test_tarefa_de_atualizacao_passa_o_historico_para_o_coletor(self):
        with ficticio.projeto_de_teste(FICHAS[:1]):
            c, token = self._painel()
            with mock.patch("subprocess.Popen") as popen, mock.patch("painel.atualizar._tarefa_rodando", return_value=False):
                c.post("/tarefa", data={"token": token, "tipo": "rodada", "historico": "7"})
            args = popen.call_args[0][0]
            self.assertEqual(args[args.index("--historico") + 1], "7")
            with mock.patch("subprocess.Popen") as popen, mock.patch("painel.atualizar._tarefa_rodando", return_value=False):
                c.post("/tarefa", data={"token": token, "tipo": "rodada", "desde": "2026-09-01"})
            self.assertNotIn("--historico", popen.call_args[0][0])
            self.assertEqual(popen.call_args[0][0][popen.call_args[0][0].index("--desde") + 1], "01/09/2026")

    def test_converter_a_planilha_para_texto_planilha_e_painel(self):
        planilha_de_contingencias(self.arq, com_data_base=True)
        with ficticio.projeto_de_teste(FICHAS[:1]):
            c, token = self._painel()
            loc = self._enviar(c, token, "/fluxo/importar/enviar")
            lote = loc.split("lote=")[1]
            r = c.get(f"/fluxo/migrar?lote={lote}")
            self.assertEqual(r.status_code, 302)
            self.assertIn("/migracao/mapear?lote=", r.headers["Location"])
            mapa = c.get(r.headers["Location"]).get_data(as_text=True)
            self.assertIn("Painel com gráficos", mapa)
            novo_lote = r.headers["Location"].split("lote=")[1]
            r = c.post("/migracao/converter", data={"token": token, "lote": novo_lote, "acao": "converter", "nome": "Convertido",
                                                    "modelos": ["docx_a", "dashboard"], "estilo_texto": "a"})
            self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
            from painel import entregas
            gerados = {a["nome"].rsplit(".", 1)[-1] for rodada in entregas.listar_saida() for a in rodada["arquivos"]}
            self.assertTrue({"docx", "xlsx", "html"} <= gerados, f"a conversão gerou {sorted(gerados)}")

    def test_atualizar_pede_a_data_base_quando_o_arquivo_nao_traz(self):
        planilha_de_contingencias(self.arq, com_data_base=False)
        f = FICHAS[0]
        with ficticio.projeto_de_teste(FICHAS[:1]):
            c, token = self._painel()
            loc = self._enviar(c, token, "/fluxo/atualizar/enviar")
            pagina = c.get(loc).get_data(as_text=True)
            self.assertIn("Data-base do relatório", pagina)
            self.assertIn("name='data_base'", pagina)
            self.assertIn("<b>O arquivo não traz a data-base.</b>", pagina)
            self.assertIn("histórico completo", pagina)
        planilha_de_contingencias(self.arq, com_data_base=True)
        with ficticio.projeto_de_teste(FICHAS[:1]):
            c, token = self._painel()
            loc = self._enviar(c, token, "/fluxo/atualizar/enviar")
            pagina = c.get(loc).get_data(as_text=True)
            self.assertIn("value='18/09/2026'", pagina)
            self.assertNotIn("<b>O arquivo não traz a data-base.</b>", pagina)

    def test_conversao_aceita_o_painel_como_destino(self):
        from painel import migracao
        self.assertIn("dashboard", migracao.MODELOS_DE_DESTINO)
        self.assertIn("texto simplificado", migracao.MODELOS_DE_DESTINO["docx_a"])

    def test_coletor_real_sem_desde_traz_o_historico_completo(self):
        """Antes, processo visto pela primeira vez sem `desde` voltava vazio (virava 'linha de base')."""
        real = fila.ColetorReal()
        real._contexto = object()
        visto = {}

        def falso(contexto, proc, estado, lista, historico, cota, desde=None, relato=None):
            visto["historico"], visto["desde"] = historico, desde
            return 0
        with mock.patch.object(coletor, "coletar_processo", side_effect=falso), mock.patch.object(capa, "_config_datajud", return_value=(False, None)):
            real.coletar({"numero": TRT7, "cliente": "x"}, "padrao", None)
            self.assertEqual(visto["historico"], fila.ColetorReal.HISTORICO_TODO)
            real.coletar({"numero": TRT7, "cliente": "x"}, "padrao", "2026-09-18")
            self.assertEqual(visto["historico"], 0, "com data-base: só o que veio depois")


if __name__ == "__main__":
    unittest.main()


class TestErrosDoPortalJusBr(unittest.TestCase):
    """Falhas de 08/10/2026: erros passageiros do portal e processo que já está no STJ."""

    def test_reconhece_erro_passageiro_do_portal(self):
        for texto in ("Internal Server Error\nError id 20d0", "Erro inesperado ao manusear pedido de autenticação para provedor"):
            with mock.patch.object(coletor, "_texto", return_value=texto):
                self.assertTrue(coletor.erro_transitorio_do_portal(object()), texto)
        with mock.patch.object(coletor, "_texto", return_value="Consultar Processos"):
            self.assertFalse(coletor.erro_transitorio_do_portal(object()))

    def test_abrir_url_tenta_de_novo_depois_de_erro_passageiro(self):
        paginas = [mock.Mock(), mock.Mock()]
        with mock.patch.object(janela, "nova_pagina", side_effect=paginas), mock.patch.object(coletor, "fechar_popups"), \
                mock.patch.object(coletor, "_autos_carregados", side_effect=[False, True]), \
                mock.patch.object(coletor, "erro_transitorio_do_portal", return_value=True), mock.patch.object(coletor.time, "sleep"):
            self.assertIs(coletor._abrir_url(object(), "N", "http://x"), paginas[1])
        paginas[0].close.assert_called()

    def test_abrir_url_nao_insiste_em_erro_que_nao_e_passageiro(self):
        with mock.patch.object(janela, "nova_pagina", return_value=mock.Mock()) as nova, mock.patch.object(coletor, "fechar_popups"), \
                mock.patch.object(coletor, "_autos_carregados", return_value=False), \
                mock.patch.object(coletor, "erro_transitorio_do_portal", return_value=False), mock.patch.object(coletor.time, "sleep"):
            self.assertIsNone(coletor._abrir_url(object(), "N", "http://x"))
        self.assertEqual(nova.call_count, 1)

    def test_processo_no_stj_vai_para_conferencia_manual_sem_repetir(self):
        self.assertEqual(coletor.em_tribunal_superior("Recurso Especial (1032)\nSTJ - SECRETARIA JUDICIÁRIA - SJD"), "STJ")
        self.assertIsNone(coletor.em_tribunal_superior("1ª VARA CÍVEL DE FORTALEZA"))
        erro = fila.classificar_erro(RuntimeError("Processo no STJ (tribunal superior): o jus.br não abre estes autos."))
        self.assertEqual(erro["codigo"], "nao_encontrado")
        self.assertIn(erro["codigo"], fila.PERMANENTES)


class TestDocumentosPendentes(Base):
    def _portal(self, docs, **kw):
        autos = {(TRT7, "1"): autos_falsos(TRT7, 101, ("Distribuição",), documentos=docs)}
        return PortalFalso(autos, **kw)

    def test_o_que_passou_da_cota_na_primeira_leitura_e_baixado_na_proxima_rodada(self):
        portal = self._portal(["901", "902", "903"])
        estado = {}
        baixados, estado, _ = self.coletar(portal, TRT7, estado=estado, historico=10, cota=1)
        self.assertEqual(baixados, 1)
        self.assertEqual(len(estado[TRT7]["trt"]["1"]["documentos"]), 1, "só o baixado fica conhecido")
        baixados, estado, _ = self.coletar(portal, TRT7, estado=estado, historico=10, cota=5)
        self.assertEqual(baixados, 2)
        self.assertEqual(set(estado[TRT7]["trt"]["1"]["documentos"]), {"901", "902", "903"})

    def test_primeira_leitura_nao_marca_como_conhecido_o_que_ficou_fora_do_historico(self):
        # historico=0 = linha de base deliberada: nada é baixado e nada fica pendente
        portal = self._portal(["901", "902"])
        baixados, estado, _ = self.coletar(portal, TRT7, historico=0, cota=5)
        self.assertEqual(baixados, 0)
        self.assertEqual(set(estado[TRT7]["trt"]["1"]["documentos"]), {"901", "902"})

    def test_documento_sem_arquivo_e_tentado_de_novo_e_depois_desiste(self):
        portal = self._portal(["901"], sem_pdf={"901"})
        estado = {}
        for rodada in range(1, trt.DESISTE_DO_DOCUMENTO + 1):
            _, estado, lista = self.coletar(portal, TRT7, estado=estado, historico=10, cota=5)
            reg = estado[TRT7]["trt"]["1"]
            self.assertEqual(reg["falhas_documentos"]["901"], rodada)
            self.assertEqual("901" in reg["documentos"], rodada == trt.DESISTE_DO_DOCUMENTO)

    def test_documento_que_falhou_e_atualizado_no_mesmo_evento_quando_o_pdf_chega(self):
        portal = self._portal(["901"], sem_pdf={"901"})
        estado, lista = {}, comum.eventos()

        def rodada():
            with mock.patch.object(comum, "config", return_value=self.config):
                return trt.coletar_processo(portal, {"numero": TRT7, "cliente": "Cliente X"}, estado, lista, 10, 5, None, {})
        self.assertEqual(rodada(), 0)
        docs = [e for e in lista if e["tipo_evento"] == "documento"]
        self.assertEqual((len(docs), docs[0].get("arquivo")), (1, None))
        portal.sem_pdf.clear()
        self.assertEqual(rodada(), 1)
        docs = [e for e in lista if e["tipo_evento"] == "documento"]
        self.assertEqual(len(docs), 1, "o mesmo evento, sem duplicar")
        self.assertTrue(docs[0]["arquivo"])
        self.assertNotIn("901", estado[TRT7]["trt"]["1"]["falhas_documentos"])


class TestEntradaNoTRT(Base):
    def test_entrada_que_falha_na_primeira_tem_segunda_chance_e_guarda_a_tela(self):
        portal = portal_de(TRT7)
        with mock.patch.object(trt, "entrar_acesso_restrito", side_effect=[False, True]) as entrar, \
                mock.patch.object(coletor, "salvar_diagnostico") as diag:
            page = trt.pagina_da_consulta(portal, "pje.trt8.jus.br")
        self.assertIsNotNone(page)
        self.assertEqual(entrar.call_count, 2)
        self.assertIn("acesso_restrito_falhou_trt8_t1", diag.call_args[0][1])

    def test_entrada_que_falha_duas_vezes_levanta_o_erro_de_sempre(self):
        portal = portal_de(TRT7)
        with mock.patch.object(trt, "entrar_acesso_restrito", return_value=False), mock.patch.object(coletor, "salvar_diagnostico"):
            with self.assertRaisesRegex(RuntimeError, "Acesso restrito do TRT não abriu"):
                trt.pagina_da_consulta(portal, "pje.trt8.jus.br")


class TestTrocaDeRelatorioDuranteAColeta(unittest.TestCase):
    """Defeito conhecido do beta3: a thread de coleta usa o relatório "ativo" (global); trocar de aba no meio
    gravava andamentos no relatório errado. Agora a troca fica bloqueada enquanto a coleta roda."""

    def _painel(self):
        from revisao import app
        return app.test_client()

    def test_troca_bloqueada_com_coleta_em_andamento(self):
        from painel import assistente
        with ficticio.projeto_de_teste(FICHAS[:1]) as proj:
            outro = comum.criar_projeto("Outro relatório")
            comum.usar_projeto(proj["slug"])
            c = self._painel()
            with mock.patch.dict(assistente.EXEC, {"slug": proj["slug"]}), mock.patch.object(assistente, "execucao_rodando", return_value=True):
                r = c.get(f"/p/{outro}")
                self.assertEqual(r.status_code, 302)
                self.assertIn("coleta", r.headers["Location"])
                self.assertEqual(comum.PROJETO, proj["slug"], "continua no relatório da coleta")
                c.set_cookie("projeto", outro)
                c.get("/fluxo")
                self.assertEqual(comum.PROJETO, proj["slug"], "nem o cookie de outra aba troca o relatório")
                r = c.post("/novo", data={"token": __import__("revisao").TOKEN, "nome": "Mais um"})
                self.assertIn("coleta", r.headers["Location"])
            r = c.get(f"/p/{outro}")                      # coleta terminada: a troca volta a valer
            self.assertEqual(r.headers["Location"], "/")
            self.assertEqual(comum.PROJETO, outro)
