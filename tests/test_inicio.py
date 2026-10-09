"""Testes da tela Início (/inicio) e da busca (/busca): relatório temporário, dados fictícios, sem rede.

    python3 -m unittest tests/test_inicio.py -v
"""
import datetime
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import comum  # noqa: E402
import ficha as fch  # noqa: E402
from ficticio import numero_ficticio  # noqa: E402

GLOBAIS = ("PROJETOS_DIR", "ATUAL_FILE", "CONFIG_FILE", "PROJETO", "PROJETO_DIR", "PROJETO_FILE", "DATA",
           "CARTEIRA_FILE", "CLIENTES_FILE", "EVENTOS_FILE", "ESTADO_FILE", "DOCS_DIR", "TEXTOS_DIR",
           "RELATORIOS_DIR", "DIAG_DIR", "PRINTS_DIR")
N1, N2, N3 = numero_ficticio(1), numero_ficticio(2), numero_ficticio(3)
CLIENTE = "Cliente Exemplo 01 Ltda"
CLIENTE_XSS = "Cliente Exemplo 09 <script>alert(1)</script> & Cia Ltda"
VALOR_SIGILOSO = "valor-sigiloso-do-cofre-123"
AGORA = datetime.datetime(2026, 10, 8, 21, 30)      # quinta-feira, à noite


def evento(i, numero, status="rascunho", **kw):
    base = {"id": f"t:{i}", "numero": numero, "cliente": CLIENTE, "tipo_evento": "documento", "status": status,
            "detectado_em": "2026-10-06T10:00:00", "data": "06/10/2026", "titulo": f"Documento {i}",
            "frase": f"Foi proferida a decisão número {i}.", "polo_cliente": "passivo", "efeito": "neutro"}
    base.update(kw)
    return base


class Tela(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from painel import base, inicio
        cls.inicio = inicio
        cls.salvo = {n: getattr(comum, n) for n in GLOBAIS}
        cls.app = Flask(__name__)
        cls.app.config["TESTING"] = True
        token = "token-de-teste"
        for tela in (inicio, base):       # a mesma ordem de revisao.py
            tela.registrar(cls.app, token, base.cabecalho, base.criar_token_ok(token))
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for n, v in cls.salvo.items():
            setattr(comum, n, v)

    def setUp(self):
        import acesso
        nome = f"{type(self).__name__}-{self._testMethodName}"
        self.raiz = TMP / "projetos-inicio" / nome
        self.raiz.mkdir(parents=True, exist_ok=True)
        comum.PROJETOS_DIR = self.raiz
        comum.ATUAL_FILE = self.raiz / ".projeto_atual"
        comum.CONFIG_FILE = TMP / f"config-inicio-{nome}.json"
        comum.CONFIG_FILE.unlink(missing_ok=True)
        comum._apontar(self.raiz / "_vazio" / "data", self.raiz / "_vazio" / "carteira.json",
                       self.raiz / "_vazio" / "clientes.json")
        comum.PROJETO = comum.PROJETO_DIR = comum.PROJETO_FILE = None
        self.cofre = {"cert_senha": VALOR_SIGILOSO, "totp_secret": "JBSWY3DPEHPK3PXP"}
        for alvo in (mock.patch.object(acesso, "obter", lambda chave: self.cofre.get(chave)),
                     mock.patch.object(self.inicio, "_agora", lambda: AGORA),
                     mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede usada")),
                     mock.patch.object(socket.socket, "connect", side_effect=AssertionError("rede usada"))):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.c.delete_cookie("projeto")

    def criar_relatorio(self, nome="Grupo Exemplo", fichas=(), eventos=(), clientes=()):
        slug = comum.criar_projeto(nome)
        comum.usar_projeto(slug)
        fch.salvar(list(fichas))
        if clientes:
            comum.save_json(comum.CLIENTES_FILE, {"clientes": [{"nome": c} for c in clientes]})
        comum.salvar_eventos(list(eventos))
        self.c.set_cookie("projeto", slug)
        return slug

    def ficha(self, numero, cliente=CLIENTE, **campos):
        return fch.nova_ficha(numero, cliente=cliente, **campos)

    def pagina(self, caminho, status=200):
        r = self.c.get(caminho)
        self.assertEqual(r.status_code, status, caminho)
        return r.get_data(as_text=True)

    def texto(self, caminho):
        """A página sem as marcas de destaque (a palavra achada vem entre <mark>)."""
        return self.pagina(caminho).replace("<mark>", "").replace("</mark>", "")

    # --- Início ---

    def test_sem_relatorio_mostra_primeiros_passos(self):
        t = self.pagina("/inicio")
        for trecho in ("BOA NOITE · QUINTA-FEIRA, 08 DE OUTUBRO", "<h1>Olá!</h1>", "RADAR IMEDIATO", "Primeiros passos",
                       "Configurar tudo", "Criar o relatório", "Cadastrar clientes e processos", "Rodar o Assistente",
                       "href='/configurar'", "href='/novo'", "href='/cadastro'", "href='/fluxo'", "class='ajuda'"):
            self.assertIn(trecho, t)
        self.assertNotIn("Demandam ação agora", t)

    def test_sem_relatorio_o_resto_continua_indo_para_novo(self):
        r = self.c.get("/planilha")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/novo"))

    def test_relatorio_vazio(self):
        self.criar_relatorio()
        t = self.pagina("/inicio")
        for trecho in ("Primeiros passos", "Este relatório ainda não tem processos", "Demandam ação agora",
                       "Nada pede a sua atenção agora", "Nenhuma coleta foi feita", "Próximas ações",
                       "Cadastrar clientes e processos", "Atualizar andamentos", "Gerar planilha",
                       "<b>0</b><span class='rot'>para revisar"):
            self.assertIn(trecho, t)

    def test_com_dados(self):
        self.criar_relatorio(
            fichas=[self.ficha(N1), self.ficha(N2, cliente="Outro Cliente S.A.")],
            eventos=[evento(1, N1, efeito="desfavoravel", prazo="15 dias"), evento(2, N1), evento(3, N2),
                     evento(4, N2, "aprovado"), evento(5, N2, "relatado", detectado_em="2026-01-02T10:00:00"),
                     evento(6, N2, "coletado")])
        t = self.pagina("/inicio")
        self.assertIn("<h1>Olá!</h1>", t)
        self.assertIn("<b>3</b><span class='rot'>para revisar", t)
        self.assertIn("<b>5</b><span class='rot'>novos na semana", t)     # 6 eventos menos o de janeiro
        self.assertIn("<b>1</b><span class='rot'>aprovados", t)
        self.assertIn("3 resumos esperam a sua revisão, em 2 processos.", t)
        self.assertIn("2 processos acompanhados", t)
        self.assertIn(f"/processo?numero={N1}", t)
        self.assertIn("olhar com atenção", t)                            # N1 tem prazo e efeito desfavorável
        self.assertIn("Revisar 3 resumos", t)
        self.assertIn("Gerar a planilha (1 aprovado)", t)
        self.assertIn("1 documento coletado sem resumo", t)
        self.assertNotIn("Primeiros passos", t)

    def test_nome_do_usuario_e_hora_do_dia(self):
        self.criar_relatorio()
        comum.save_json(comum.CONFIG_FILE, {"revisor": "Davi Mendes"})
        self.assertIn("<h1>Olá, Davi!</h1>", self.pagina("/inicio"))
        for hora, saudacao in ((6, "BOM DIA"), (14, "BOA TARDE"), (23, "BOA NOITE"), (2, "BOA NOITE")):
            quando = datetime.datetime(2026, 10, 8, hora, 0)
            self.assertTrue(self.inicio.rotulo_do_dia(quando).startswith(saudacao + " · QUINTA-FEIRA, 08 DE OUTUBRO"))
        self.assertEqual(self.inicio.rotulo_do_dia(datetime.datetime(2026, 3, 3, 9, 0)), "BOM DIA · TERÇA-FEIRA, 03 DE MARÇO")

    def test_ultima_coleta_pela_fila_com_falha(self):
        import fila
        self.criar_relatorio(fichas=[self.ficha(N1), self.ficha(N2)], eventos=[evento(1, N1)])
        f = fila.Fila()
        f.enfileirar([N1, N2])
        f.proximo()
        f.marcar(N1, "coletado")
        f.proximo()
        f.marcar(N2, "manual", {"codigo": "captcha", "mensagem": "captcha do TRT"})
        t = self.pagina("/inicio")
        self.assertIn("Última coleta", t)
        self.assertIn("<b>1</b>de 2 processos coletados", t)
        self.assertIn("<b>1</b>com captcha", t)
        self.assertIn("conferir manualmente", t)

    def test_escapa_html_dos_nomes(self):
        self.criar_relatorio(fichas=[self.ficha(N1, cliente=CLIENTE_XSS)],
                             eventos=[evento(1, N1, cliente=CLIENTE_XSS, frase="<img src=x onerror=alert(1)>")])
        for caminho in ("/inicio", "/busca?q=cia", "/busca?q=img", f"/busca?q={CLIENTE_XSS}"):
            t = self.pagina(caminho)
            self.assertNotIn("<script>alert(1)", t, caminho)
            self.assertNotIn("<img src=x", t, caminho)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", self.pagina("/busca?q=cia"))

    def test_nada_sensivel_aparece(self):
        self.criar_relatorio(fichas=[self.ficha(N1)], eventos=[evento(1, N1, arquivo=str(TMP / "doc-secreto.html"))])
        for caminho in ("/inicio", "/busca?q=decisão", f"/busca?q={N1}"):
            t = self.pagina(caminho)
            for proibido in (VALOR_SIGILOSO, "JBSWY3DPEHPK3PXP", "doc-secreto", str(TMP)):
                self.assertNotIn(proibido, t, caminho)

    # --- Busca ---

    def dados_de_busca(self):
        self.criar_relatorio(
            fichas=[self.ficha(N1, autores="Maria da Silva Fictícia", reus=CLIENTE, apelido="Caso do galpão"),
                    self.ficha(N2, cliente="Outro Cliente S.A.", reus="Outro Cliente S.A.")],
            clientes=[CLIENTE, "Outro Cliente S.A.", "Cliente Exemplo 03 Ltda"],
            eventos=[evento(1, N1, frase="Deferida a penhora online sobre contas.", conteudo="Valor bloqueado"),
                     evento(2, N2, status="aprovado", cliente="Outro Cliente S.A.", frase="Audiência designada.")])

    def test_busca_sem_consulta_ou_curta(self):
        self.dados_de_busca()
        t = self.pagina("/busca")
        self.assertIn("Buscar clientes, processos e documentos", t)
        self.assertIn("Como buscar", t)
        self.assertIn("Digite pelo menos 2", self.pagina("/busca?q=a"))
        self.assertIn("Como buscar", self.pagina("/busca?q=%20%20"))

    def test_busca_por_cliente_parte_e_apelido(self):
        self.dados_de_busca()
        t = self.pagina("/busca?q=cliente+exemplo")
        self.assertIn("Clientes", t)
        self.assertIn(f"/processo?numero={N1}", t)
        self.assertNotIn(f"/processo?numero={N2}", t)
        self.assertIn("Cliente Exemplo 03 Ltda", self.texto("/busca?q=exemplo+03"))
        self.assertIn(f"/processo?numero={N1}", self.pagina("/busca?q=FICTICIA"))        # sem acento, sem caixa
        self.assertIn(f"/processo?numero={N1}", self.pagina("/busca?q=galpao"))

    def test_busca_por_numero_com_e_sem_pontuacao(self):
        self.dados_de_busca()
        so_digitos = "".join(c for c in N1 if c.isdigit())
        for consulta in (N1, so_digitos, so_digitos[:9], N1.split(".")[0]):
            self.assertIn(f"/processo?numero={N1}", self.pagina(f"/busca?q={consulta}"), consulta)
        self.assertNotIn(f"/processo?numero={N2}", self.pagina(f"/busca?q={N1}"))

    def test_busca_por_texto_do_andamento(self):
        self.dados_de_busca()
        t = self.pagina("/busca?q=penhora")
        self.assertIn("Andamentos e resumos", t)
        self.assertIn("<mark>penhora</mark>", t)
        self.assertIn("para revisar", t)
        self.assertIn(f"/processo?numero={N1}", t)
        self.assertNotIn("Audiência designada", t)
        self.assertIn("Audiência designada", self.texto("/busca?q=audiencia"))

    def test_busca_sem_resultado(self):
        self.dados_de_busca()
        t = self.pagina("/busca?q=zzzxyz")
        self.assertIn("Nenhum resultado", t)
        self.assertIn("zzzxyz", t)
        self.assertNotIn("/processo?numero=", t)

    def test_busca_limita_resultados(self):
        eventos = [evento(i, N1, frase=f"Petição repetida {i}") for i in range(60)]
        self.criar_relatorio(fichas=[self.ficha(N1)], eventos=eventos)
        t = self.pagina("/busca?q=repetida")
        self.assertEqual(t.count("class='ini-trecho'"), self.inicio.MAX_ANDAMENTOS)
        self.assertIn(f"Mostrando {self.inicio.MAX_ANDAMENTOS} de 60", t)
        r = self.inicio.buscar("x" * 5000)       # consulta enorme é cortada, não derruba nada
        self.assertLessEqual(len("".join(r["termos"])), self.inicio.MAX_CONSULTA)

    def test_busca_sem_relatorio(self):
        t = self.pagina("/busca?q=teste")
        self.assertIn("Nenhum resultado", t)


if __name__ == "__main__":
    unittest.main()
