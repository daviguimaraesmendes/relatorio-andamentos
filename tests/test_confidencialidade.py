"""Confidencialidade (teste transversal do WS-13): nada de cliente, de segredo ou de domínio externo no que é
versionado, empacotado ou gerado. As regras vivem em `confidencialidade_regras.py` (a mesma varredura que o
`empacotar.sh` aplica ao pacote).

Grupos de testes:
1. O detector detecta (casos plantados, montados em tempo de execução: nenhum número real vira literal aqui).
2. Arquivos versionados: número de processo, nomes, documentos pessoais, segredos, arquivos proibidos, inclusive o
   texto dentro de .docx/.xlsx dos modelos (`src/modelos/`).
3. `config.exemplo.json` sem identificadores do escritório nem do revisor.
4. HTML gerado sem domínio externo: telas do painel (as novas são puladas até existirem), relatório HTML da Fase 1,
   templates e saídas do dashboard (puladas até o WS-8 existir).
5. Saída dos escritores (puladas até WS-6/WS-7 existirem): só os números das fichas, nada vindo do modelo padrão.
6. Nomes cadastrados NESTE computador (só tem efeito no Mac do escritório; sem dados reais, é pulado).

    python3 -m unittest tests/test_confidencialidade.py -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transversal as T  # noqa: E402  (isolamento antes de tudo)
import confidencialidade_regras as R  # noqa: E402
import ficticio  # noqa: E402

TIPOS_GRAVES = ("numero_de_processo", "documento_pessoal", "segredo", "arquivo_proibido")


def formatar(achados, limite=15):
    linhas = [f"{a.arquivo}:{a.linha} [{a.tipo}] {a.trecho}" for a in achados[:limite]]
    if len(achados) > limite:
        linhas.append(f"... e mais {len(achados) - limite}")
    return "\n  " + "\n  ".join(linhas)


# ------------------------------------------------------------------ 1. o detector detecta

class Detector(unittest.TestCase):
    def tipos(self, texto, **kw):
        return {a.tipo for a in R.varrer_texto(texto, "x.txt", **kw)}

    def test_numero_real_e_barrado_e_os_permitidos_passam(self):
        fora = ficticio.numero_ficticio(7)                       # 1234574-...: fora da faixa permitida
        self.assertIn("numero_de_processo", self.tipos(f"Processo {fora}."))
        self.assertIn("numero_de_processo", self.tipos(f"sem máscara {fora.replace('-', '').replace('.', '')}"))
        for ok in (ficticio.numero_ficticio(0), ficticio.numero_ficticio(3), "0000000-00.0000.0.00.0000",
                   "9999999-99.9999.9.99.9999"):
            self.assertNotIn("numero_de_processo", self.tipos(f"Processo {ok}."), ok)

    def test_documentos_pessoais(self):
        self.assertIn("documento_pessoal", self.tipos("CPF " + "529.982." + "247-25"))
        self.assertIn("documento_pessoal", self.tipos("CNPJ " + "11.222." + "333/0001-81"))
        self.assertIn("documento_pessoal", self.tipos("escreva para fulano@" + "empresa-real.com.br"))
        self.assertIn("documento_pessoal", self.tipos("ligue (85) " + "98765-4321"))
        self.assertEqual(self.tipos("a@exemplo.test, b@example.org, 111.111.111-11, python@3.12"), set())

    def test_segredos(self):
        chave = "sk-ant-" + "Qz9" * 12
        self.assertIn("segredo", self.tipos(f'ANTHROPIC = "{chave}"'))
        self.assertIn("segredo", self.tipos('{"senha": "' + "Tr0ub" + '4dor&3xyz"}'))
        self.assertIn("segredo", self.tipos("-----BEGIN RSA PRIV" + "ATE KEY-----"))
        self.assertEqual(self.tipos('chave = "sk-ant-chave-falsa-de-teste-123456"; senha = "teste-12345678"'), set())
        self.assertEqual(self.tipos("senha = digitar(senha)  # sem valor literal"), set())

    def test_empresa_suspeita_e_fictícia(self):
        estranha = "Zephyr" + "ion Miner" + "ação Ltda"        # montada em tempo de execução: o repositório não a contém
        self.assertIn("empresa_suspeita", self.tipos(f"Contrato com {estranha}."))
        self.assertEqual(self.tipos("Cliente Exemplo 01 Ltda; EMPRESA TESTE COMERCIO LTDA; Banco Modelo S.A."), set())
        self.assertNotIn("empresa_suspeita", self.tipos(f"Contrato com {estranha}.", heuristica=False))

    def test_nome_cadastrado_neste_computador(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "projetos" / "p1").mkdir(parents=True)
            cliente = "Quixote" + "lândia Partici" + "pações Ltda"
            (raiz / "projetos" / "p1" / "clientes.json").write_text(json.dumps(
                {"clientes": [{"nome": cliente, "variacoes": ["Quixote Part."]}]}), encoding="utf-8")
            (raiz / "config.json").write_text(json.dumps({"revisor": "Doutor Zacarias Nunes"}), encoding="utf-8")
            nomes = R.nomes_cadastrados(raiz)
            self.assertIn(R.sem_acento(cliente), nomes)
            self.assertIn("doutor zacarias nunes", nomes)
            self.assertIn("nome_cadastrado", self.tipos(f"Reunião com a {cliente.upper()} hoje", nomes=nomes))
            self.assertIn("nome_cadastrado", self.tipos("quem revisa: Doutor Zacarias Nunes", nomes=nomes))
            self.assertNotIn("nome_cadastrado", self.tipos("Cliente Exemplo 01 Ltda", nomes=nomes))

    def test_arquivos_proibidos(self):
        for caminho in ("config.json", "projetos/x/carteira.json", "data/eventos.json", "certificado.pfx", ".env",
                        "src/chave.pem", "dist/pacote.zip"):
            self.assertIsNotNone(R.arquivo_proibido(caminho), caminho)
        for caminho in ("config.exemplo.json", "src/modelos/xlsx_b/modelo.xlsx", "tests/fixtures/carteira.json",
                        "docs/guia-fase2.md", "projetos/.gitkeep"):
            self.assertIsNone(R.arquivo_proibido(caminho), caminho)

    def test_varredura_entra_nos_arquivos_office(self):
        import zipfile
        fora = ficticio.numero_ficticio(9)
        with tempfile.TemporaryDirectory() as d:
            alvo = Path(d) / "modelo.docx"
            with zipfile.ZipFile(alvo, "w") as z:
                z.writestr("word/document.xml", f"<w:p><w:r><w:t>Processo {fora}</w:t></w:r></w:p>")
            self.assertIn("numero_de_processo", {a.tipo for a in R.varrer(Path(d), [Path("modelo.docx")], nomes=set())})

    def test_varredura_percorre_todos_os_arquivos_da_pasta(self):
        """Regressão: o primeiro rascunho só varria o primeiro arquivo de cada pasta."""
        fora = ficticio.numero_ficticio(12)
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d) / "src"
            pasta.mkdir()
            for nome in ("a.txt", "b.txt", "c.txt"):
                (pasta / nome).write_text("nada aqui\n", encoding="utf-8")
            (pasta / "d.txt").write_text(f"processo {fora}\n", encoding="utf-8")
            achados = R.varrer(Path(d), nomes=set())
            self.assertEqual([a.arquivo for a in achados if a.tipo == "numero_de_processo"], ["src/d.txt"])

    def test_referencias_externas(self):
        r = R.referencias_externas
        self.assertEqual(r("<html><body><a href='/x'>a</a><img src='data:image/png;base64,AAAA'>"
                           "<link rel=stylesheet href='estilo.css'><script>var u='http://www.w3.org/2000/svg';</script>"
                           "<form action='/tarefa' method=post></form> http://127.0.0.1:5072/ </body></html>"), [])
        for html in ("<script src='https://cdn.exemplo.test/lib.js'></script>",
                     "<link rel=stylesheet href='https://fonts.exemplo.test/css'>",
                     "<style>@import url(https://x.exemplo.test/a.css);</style>",
                     "<style>@font-face{src:url(//x.exemplo.test/f.woff2)}</style>",
                     "<script>fetch('https://api.exemplo.test/dados')</script>",
                     "<img src=//x.exemplo.test/i.png>",
                     "<p>veja https://www.exemplo.test/pagina</p>"):
            self.assertTrue(r(html), html)
        self.assertEqual(r("<a href='https://www.exemplo.test/'>x</a>", incluir_links=False, procurar_no_texto=False), [])


# ------------------------------------------------------------------ 2 e 3. o que está versionado

class ArquivosVersionados(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arquivos = T.arquivos_do_projeto()
        cls.achados = R.varrer(T.RAIZ, cls.arquivos, nomes=set(), heuristica=True)

    def por_tipo(self, *tipos):
        return [a for a in self.achados if a.tipo in tipos]

    def test_ha_o_que_varrer(self):
        self.assertGreater(len(self.arquivos), 30, "a lista de arquivos versionados veio quase vazia")

    def test_nenhum_numero_de_processo_fora_do_permitido(self):
        achados = self.por_tipo("numero_de_processo")
        self.assertEqual(achados, [], "número de processo fora de 0000000/9999999/1234567-1234570:" + formatar(achados))

    def test_nenhum_nome_de_empresa_que_pareca_real(self):
        achados = self.por_tipo("empresa_suspeita")
        self.assertEqual(achados, [], "nome de empresa que não parece fictício (troque por um fictício como "
                                      "'Cliente Exemplo 01' ou, se for genérico, acrescente a palavra a GENERICAS):" + formatar(achados))

    def test_nenhum_documento_pessoal(self):
        achados = self.por_tipo("documento_pessoal")
        self.assertEqual(achados, [], "CPF/CNPJ/e-mail/telefone em formato real:" + formatar(achados))

    def test_nenhum_segredo(self):
        achados = self.por_tipo("segredo")
        self.assertEqual(achados, [], "possível segredo versionado:" + formatar(achados))

    def test_nenhum_arquivo_proibido(self):
        achados = self.por_tipo("arquivo_proibido")
        self.assertEqual(achados, [], "arquivo que não pode ser versionado:" + formatar(achados))

    def test_ativos_dos_modelos_sao_sanitizados(self):
        """docx/xlsx de src/modelos/ são lidos por dentro (XML): sem número, nome ou segredo. Pulado até existirem."""
        ativos = [p for p in self.arquivos if p.parts[:2] == ("src", "modelos") and p.suffix.lower() in R.EXTENSOES_OFFICE]
        if not ativos:
            self.skipTest("src/modelos/ ainda não tem .docx/.xlsx (WS-6/WS-7/WS-8); reativar na integração")
        achados = R.varrer(T.RAIZ, ativos, nomes=set(), heuristica=True)
        self.assertEqual(achados, [], "modelo padrão com dado que não é fictício:" + formatar(achados))

    def test_config_exemplo_sem_identificadores(self):
        cfg = json.loads((T.RAIZ / "config.exemplo.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("identificadores_escritorio"), [], "config.exemplo.json com quem assina preenchido")
        self.assertEqual(cfg.get("revisor", ""), "")
        self.assertNotIn("jusbr_autologin", cfg)


# ------------------------------------------------------------------ 4. HTML gerado sem domínio externo

class PainelOffline(unittest.TestCase):
    """GET nas telas do painel (num relatório fictício, sem rede, sem subir processo) e confere que nenhuma carrega
    nada de fora. As telas novas (WS-9, WS-16, WS-18) entram sozinhas quando forem registradas."""
    ROTAS_ANTIGAS = ("/", "/atualizar", "/planilha", "/cadastro", "/config", "/acesso", "/novo")
    ROTAS_NOVAS = {"/fluxo": "WS-9", "/migracao": "WS-9", "/entregas": "WS-9", "/perfil": "WS-9",
                   "/pedidos": "WS-16", "/ia": "WS-18"}

    @classmethod
    def setUpClass(cls):
        cls.fichas = ficticio.gerar_carteira(6, clientes=2)
        cls.ctx = ficticio.projeto_de_teste(cls.fichas)
        cls.proj = cls.ctx.__enter__()
        cls.cofre = {}
        import acesso
        cls.patches = [mock.patch.object(acesso, "obter", lambda chave: cls.cofre.get(chave)),
                       mock.patch.object(acesso, "guardar", lambda chave, valor: cls.cofre.__setitem__(chave, valor)),
                       mock.patch("subprocess.Popen", side_effect=AssertionError("GET não pode subir processo"))]
        for p in cls.patches:
            p.start()
        import revisao
        cls.app = revisao.app
        cls.app.config["TESTING"] = True
        cls.c = cls.app.test_client()
        cls.c.set_cookie("projeto", cls.proj["slug"])

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        cls.ctx.__exit__(None, None, None)

    def pagina(self, rota):
        resp = self.c.get(rota, follow_redirects=True)
        try:
            return resp.status_code, resp.get_data(as_text=True), resp.headers.get("Content-Type", "")
        finally:
            resp.close()

    def conferir(self, rota):
        status, corpo, tipo = self.pagina(rota)
        self.assertLess(status, 500, f"{rota} devolveu erro {status}")
        if status == 200 and "html" in tipo:
            externas = R.referencias_externas(corpo)
            self.assertEqual(externas, [], f"{rota} referencia domínio externo: {externas}")
        return status

    def test_telas_da_fase1_sem_dominio_externo(self):
        for rota in self.ROTAS_ANTIGAS:
            with self.subTest(rota=rota):
                self.assertEqual(self.conferir(rota), 200)

    def test_telas_novas_sem_dominio_externo(self):
        for rota, ws in self.ROTAS_NOVAS.items():
            with self.subTest(rota=rota):
                status, _corpo, _tipo = self.pagina(rota)
                if status == 404:
                    self.skipTest(f"{rota} ainda não está registrada ({ws}); reativar na integração")
                self.conferir(rota)

    def test_relatorio_html_da_fase1_sem_dominio_externo(self):
        import datetime
        import relatorio
        eventos = T.eventos_aprovados(self.fichas, por_ficha=2)
        for e in eventos:
            e.update(frase="foi proferido despacho.", cliente="Cliente Exemplo 01 Ltda")
        html = relatorio.gerar_html("Cliente Exemplo 01 Ltda", eventos, datetime.datetime(2026, 10, 7))
        self.assertEqual(R.referencias_externas(html), [])


class DashboardOffline(unittest.TestCase):
    """Templates e saídas do dashboard (WS-8). Pulado até `escritores.dashboard` existir."""

    def test_templates_no_repositorio(self):
        htmls = sorted((T.RAIZ / "src" / "modelos").glob("**/*.html"))
        if not htmls:
            self.skipTest("src/modelos/ ainda não tem templates .html (WS-8); reativar na integração")
        for p in htmls:
            with self.subTest(arquivo=p.name):
                self.assertEqual(R.referencias_externas(p.read_text(encoding="utf-8")), [], f"{p.name} não é offline")

    def test_saidas_nos_dois_modos(self):
        dash = T.exigir("escritores.dashboard", "gerador de dashboards")
        with tempfile.TemporaryDirectory() as d:
            xlsx = T.xlsx_de_entrada(Path(d) / "entrada.xlsx", 20)
            for modo in ("modelo", "embutido"):
                with self.subTest(modo=modo):
                    destino = Path(d) / f"painel-{modo}.html"
                    dash.gravar(xlsx, destino, T.perfil_padrao(), modo=modo)
                    html = destino.read_text(encoding="utf-8")
                    self.assertEqual(R.referencias_externas(html), [], f"dashboard {modo} referencia domínio externo")
                    self.assertNotIn("fonts.googleapis", html)
                    achados = [a for a in R.varrer_texto(html, destino.name, heuristica=True)
                               if a.tipo in ("documento_pessoal", "segredo")]
                    self.assertEqual(achados, [], formatar(achados))


# ------------------------------------------------------------------ 5. saída dos escritores

class SaidaDosEscritores(unittest.TestCase):
    """O modelo padrão não pode vazar nada: no arquivo gerado só aparecem os números das fichas dadas."""

    def conferir(self, destino, fichas):
        texto = T.texto_do_arquivo(destino)
        esperados = {n for f in fichas for n in ([f["numero"]] + [v["numero"] for v in f.get("vinculados", [])])}
        no_arquivo = set(R.CNJ_MASCARA.findall(texto))
        estranhos = sorted(n for n in no_arquivo - esperados if not R.numero_permitido(n))
        self.assertEqual(estranhos, [], f"número que não é de nenhuma ficha em {destino.name}")
        outros = [a for a in R.varrer_texto(texto, destino.name, heuristica=True)
                  if a.tipo in ("documento_pessoal", "segredo", "empresa_suspeita")]
        self.assertEqual(outros, [], formatar(outros))
        self.assertTrue(no_arquivo & esperados, "o arquivo gerado não contém nenhum dos processos (teste inútil)")

    def test_docx_a_do_modelo_padrao(self):
        escritor = T.exigir("escritores.docx_a", "escritor .docx")
        fichas = ficticio.gerar_carteira(5, clientes=1)
        with tempfile.TemporaryDirectory() as d:
            destino = Path(d) / "saida.docx"
            escritor.gravar(None, T.estado_de_teste(fichas, eventos=T.eventos_aprovados(fichas, 1)), destino)
            self.conferir(destino, fichas)

    def test_xlsx_b_do_modelo_padrao(self):
        escritor = T.exigir("escritores.xlsx_b", "escritor .xlsx")
        fichas = ficticio.gerar_carteira(5, clientes=1)
        with tempfile.TemporaryDirectory() as d:
            destino = Path(d) / "saida.xlsx"
            escritor.gravar(None, T.estado_de_teste(fichas, eventos=T.eventos_aprovados(fichas, 1)), destino)
            self.conferir(destino, fichas)


# ------------------------------------------------------------------ 6. nomes cadastrados neste computador

class NomesDestaMaquina(unittest.TestCase):
    def test_nenhum_nome_cadastrado_em_arquivo_versionado(self):
        nomes = R.nomes_cadastrados(T.RAIZ)
        if not nomes:
            self.skipTest("nenhum projetos/*/clientes.json (nem config.json preenchido) neste computador: "
                          "este teste só tem efeito no computador do escritório")
        achados = R.varrer(T.RAIZ, T.arquivos_do_projeto(), nomes=nomes, heuristica=False)
        achados = [a for a in achados if a.tipo == "nome_cadastrado"]
        self.assertEqual(achados, [], "nome de cliente/parte cadastrado aparece em arquivo versionado:" + formatar(achados))


if __name__ == "__main__":
    unittest.main()
