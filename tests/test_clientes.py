"""Identificação de clientes em lote (clientes.py), a conferência da importação e a tela de cadastro.
Só dados fictícios."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: F401,E402

import carteira as cart  # noqa: E402
import clientes  # noqa: E402
import comum  # noqa: E402
import ficha  # noqa: E402
from ficticio import numero_ficticio, restaurar_comum  # noqa: E402


def limpar_estado():
    """Os testes de arquivo compartilham a pasta temporária: devolve tudo ao estado vazio."""
    for caminho in (comum.CARTEIRA_FILE, comum.CLIENTES_FILE):
        Path(caminho).unlink(missing_ok=True)
    restaurar_comum()
    if comum.PROJETO:       # `fluxos.migrar` ativou o relatório que criou: volta ao apontamento de teste
        comum.PROJETO = comum.PROJETO_DIR = comum.PROJETO_FILE = None
        comum._inicial()

GRUPO = ["Chácara Exemplo Comércio Ltda", "CHACARA EXEMPLO DISTRIBUIDORA LTDA.", "Chácara Exemplo Serviços S.A."]


def mk(i, autores, reus, **campos):
    f = ficha.nova_ficha(numero_ficticio(i))
    ficha.definir(f, "autores", autores, "migrado")
    ficha.definir(f, "reus", reus, "migrado")
    for k, v in campos.items():
        ficha.definir(f, k, v, "migrado")
    return f


def carteira_de_92():
    """92 processos: 80 contra empresas do mesmo grupo (réu), 8 em que o grupo é autor, 4 sem relação."""
    fs = []
    for i in range(80):
        fs.append(mk(i, f"Pessoa Fictícia {i:04d}", GRUPO[i % 3] + (" e Empresa Fictícia 099 Ltda" if i % 7 == 0 else "")))
    for i in range(80, 88):
        fs.append(mk(i, GRUPO[i % 3], f"Pessoa Fictícia {i:04d}"))
    for i in range(88, 92):
        fs.append(mk(i, f"Pessoa Fictícia {i:04d}", f"Empresa Fictícia {i:03d} Ltda"))
    return fs


class TestCandidatos(unittest.TestCase):
    def test_o_grupo_aparece_como_candidato_com_a_cobertura(self):
        cands = clientes.candidatos(carteira_de_92())
        topo = cands[0]
        self.assertEqual(topo["tipo"], "grupo")
        self.assertEqual(topo["nome"], "Chácara Exemplo")
        self.assertEqual(topo["processos"], 88)
        self.assertEqual((topo["autor"], topo["reu"]), (8, 80))

    def test_grafias_do_mesmo_nome_se_agrupam(self):
        fs = [mk(1, "A Ltda", "Cliente Exemplo Alfa Ltda"), mk(2, "B", "CLIENTE EXEMPLO ALFA LTDA."), mk(3, "C", "Cliente Exemplo Alfa")]
        c = next(x for x in clientes.candidatos(fs) if x["tipo"] == "nome" and "Alfa" in x["nome"])
        self.assertEqual(c["processos"], 3)

    def test_escolha_automatica_so_quando_e_obvia(self):
        self.assertEqual(clientes.escolher_automatico(clientes.candidatos(carteira_de_92()))["nome"], "Chácara Exemplo")
        varias = [mk(i, f"Pessoa Fictícia {i:04d}", f"Empresa Fictícia {i % 5:03d} Ltda") for i in range(20)]
        self.assertIsNone(clientes.escolher_automatico(clientes.candidatos(varias)))


class TestIdentificar(unittest.TestCase):
    def test_92_processos_de_uma_vez_com_polo_e_parte_contraria(self):
        fs = carteira_de_92()
        rel = clientes.identificar(fs, [{"nome": "Grupo Chácara Exemplo", "variacoes": ["Chácara Exemplo"]}], padrao=None)
        self.assertEqual(rel["aplicados"], {"Grupo Chácara Exemplo": 88})
        self.assertEqual(len(rel["sem_correspondencia"]), 4)
        passivos = [f for f in fs[:80]]
        self.assertTrue(all(ficha.obter(f, "polo_cliente") == "passivo" for f in passivos))
        self.assertTrue(all(ficha.obter(f, "polo_cliente") == "ativo" for f in fs[80:88]))
        self.assertTrue(ficha.obter(fs[0], "parte_contraria").startswith("Pessoa Fictícia 0000"))
        self.assertIsNone(ficha.obter(fs[90], "cliente"))

    def test_padrao_cobre_o_que_sobrar(self):
        fs = carteira_de_92()
        rel = clientes.identificar(fs, [{"nome": "Grupo Chácara Exemplo", "variacoes": ["Chácara Exemplo"]}], padrao="Outro Cliente")
        self.assertEqual(rel["padrao"], 4)
        self.assertEqual(ficha.obter(fs[91], "cliente"), "Outro Cliente")

    def test_humano_nunca_e_trocado_e_dois_lados_vira_ambiguo(self):
        fs = [mk(1, "Chácara Exemplo Comércio Ltda", "Chácara Exemplo Serviços S.A."), mk(2, "X", "Chácara Exemplo Comércio Ltda")]
        ficha.definir(fs[1], "cliente", "Escolhido Por Pessoa", "humano")
        rel = clientes.identificar(fs, [{"nome": "Grupo", "variacoes": ["Chácara Exemplo"]}])
        self.assertEqual(rel["ambiguos"], [fs[0]["numero"]])
        self.assertIsNone(ficha.obter(fs[0], "polo_cliente"))
        self.assertEqual(ficha.obter(fs[1], "cliente"), "Escolhido Por Pessoa")

    def test_aplicar_em_lote(self):
        fs = carteira_de_92()
        self.assertEqual(clientes.aplicar_em_lote(fs, "Cliente Exemplo 01"), 92)
        self.assertEqual(clientes.aplicar_em_lote(fs, "Cliente Exemplo 02"), 0)   # já têm cliente
        self.assertEqual(clientes.aplicar_em_lote(fs, "Cliente Exemplo 02", so_sem_cliente=False), 92)


class TestMigrarEmLote(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest import mock
        comum.save_json(comum.CLIENTES_FILE, {"clientes": []})
        # o relatório criado pelo `migrar` vai para uma pasta própria: não pode aparecer nas abas dos outros testes
        pasta = Path(tempfile.mkdtemp(prefix="projetos-clientes-"))
        self._patches = [mock.patch.object(comum, "PROJETOS_DIR", pasta), mock.patch.object(comum, "ATUAL_FILE", pasta / ".projeto_atual")]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        limpar_estado()

    def test_migrar_xlsx_sem_coluna_de_cliente_identifica_sozinho(self):
        import fluxos
        import tempfile
        from openpyxl import Workbook
        pasta = Path(tempfile.mkdtemp(prefix="clientes-"))
        wb = Workbook()
        ws = wb.active
        ws.title = "Processos"
        ws.append(["Número do Processo", "Autor(es)", "Réu(s)", "Vara", "Município", "Tribunal", "Data do Ajuizamento",
                   "Área do Direito", "Matéria Principal", "Objeto", "Valor da Causa", "Andamentos", "Situação", "Ativo"])
        for f in carteira_de_92():
            ws.append([f["numero"], ficha.obter(f, "autores"), ficha.obter(f, "reus"), "1ª Vara", "Fortaleza", "TJCE", "01/02/2024",
                       "Cível", "Dano moral", "x", 1000, "Em 01/03/2024 foi proferido despacho.", "Ativo", "Sim"])
        arq = pasta / "relatorio-exemplo.xlsx"
        wb.save(arq)
        r = fluxos.migrar([arq], projeto=None, nome="Relatório Exemplo")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["processos"], 92)
        self.assertEqual(r["clientes"], ["Chácara Exemplo"])
        self.assertFalse([a for a in r["avisos"] if a["codigo"] == "processo_sem_cliente" and "88" in a["mensagem"]])
        self.assertTrue(any(a["codigo"] == "clientes_identificados" for a in r["avisos"]))


class TestCadastroEmLote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        import cadastro
        cls.app = Flask(__name__)
        cls.app.config["TESTING"] = True
        cadastro.registrar(cls.app, "tok", lambda ativa, t="": "<main>", lambda: None)

    def tearDown(self):
        limpar_estado()

    def setUp(self):
        fs = carteira_de_92()
        comum.save_json(comum.CARTEIRA_FILE, fs)
        comum.save_json(comum.CLIENTES_FILE, {"clientes": [{"nome": "Grupo Chácara Exemplo", "variacoes": ["Chácara Exemplo"]}]})

    def test_identificar_pelas_partes_no_cadastro(self):
        r = self.app.test_client().post("/cadastro/lote", data={"token": "tok", "acao": "identificar"})
        self.assertIn(r.status_code, (200, 302))
        fs = ficha.carregar(todas=True)
        self.assertEqual(sum(1 for f in fs if ficha.obter(f, "cliente") == "Grupo Chácara Exemplo"), 88)

    def test_mesmo_cliente_para_todos_os_sem_cliente(self):
        self.app.test_client().post("/cadastro/lote", data={"token": "tok", "acao": "todos_sem_cliente", "cliente": "Cliente Exemplo 07"})
        fs = ficha.carregar(todas=True)
        self.assertTrue(all(ficha.obter(f, "cliente") == "Cliente Exemplo 07" for f in fs))
        self.assertIn("Cliente Exemplo 07", [c["nome"] for c in comum.load_json(comum.CLIENTES_FILE, {})["clientes"]])

    def test_edicao_na_tela_vale_para_a_ficha(self):
        # regressão: a edição plana do cadastro ficava escondida atrás do valor antigo de `campos`
        fs = ficha.carregar(todas=True)
        ficha.definir(fs[0], "cliente", "Antigo", "migrado")
        ficha.salvar(fs)
        self.app.test_client().post("/cadastro/processo", data={"token": "tok", "acao": "salvar", "numero": fs[0]["numero"],
                                    "cliente": "Novo Escolhido", "polo": "ativo", "parte_contraria": "", "responsavel": "", "ativo": "1"})
        self.assertEqual(ficha.obter(next(f for f in ficha.carregar(todas=True) if f["numero"] == fs[0]["numero"]), "cliente"), "Novo Escolhido")


class TestConferenciaDaImportacao(unittest.TestCase):
    def tearDown(self):
        limpar_estado()

    def test_a_tela_sugere_o_cliente_ja_marcado_e_o_confirmar_aplica_em_lote(self):
        from painel import assistente

        class Form:     # o suficiente do request.form do Flask
            def __init__(self, itens):
                self.itens = itens

            def getlist(self, k):
                return [v for kk, v in self.itens if kk == k]

            def get(self, k, padrao=None):
                return next((v for kk, v in self.itens if kk == k), padrao)
        comum.save_json(comum.CLIENTES_FILE, {"clientes": []})
        fs = carteira_de_92()
        corpo = assistente.html_da_conferencia([], [], fs, [], "", "lote-x", "Relatório Exemplo", False)
        self.assertIn("Quem é o cliente?", corpo)
        self.assertIn("92 processo(s) sem cliente", corpo)
        self.assertIn("name='cli' value='0' checked", corpo)        # o candidato óbvio já vem marcado
        resumo = assistente.identificar_clientes_do_formulario(fs, Form([("cli", "0"), ("cliente_padrao", "Cliente Exemplo 09")]))
        self.assertIn("Clientes definidos em lote", resumo)
        self.assertEqual(sum(1 for f in fs if ficha.obter(f, "cliente") == "Chácara Exemplo"), 88)
        self.assertEqual(sum(1 for f in fs if ficha.obter(f, "cliente") == "Cliente Exemplo 09"), 4)
        self.assertIn("Chácara Exemplo", [c["nome"] for c in comum.load_json(comum.CLIENTES_FILE, {})["clientes"]])

    def test_sem_processo_sem_cliente_o_bloco_nao_aparece(self):
        from painel import assistente
        fs = carteira_de_92()
        clientes.aplicar_em_lote(fs, "Cliente Exemplo 01")
        self.assertEqual(assistente.bloco_de_clientes(fs, "x"), "")


if __name__ == "__main__":
    unittest.main()
