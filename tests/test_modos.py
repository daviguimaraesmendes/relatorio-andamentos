"""Os dois modos de trabalho do relatório: MONTAGEM COMPLETA ("pesada") e ATUALIZAÇÃO LEVE, a estimativa de resumos por IA
na confirmação e o atalho "Atualizar planilha e painéis agora (sem coletar)".

Duas camadas, como nos testes dos fluxos: o motor (`src/fluxos.py`, com o coletor simulado e um provedor de IA falso que conta
as chamadas) e as telas do Assistente e das Entregas (Flask test client). Dados fictícios, sem rede, sem login em tribunal e
sem o cofre real. O que NÃO é exercitado aqui: o ColetorReal e a IA de verdade.

    python3 -m unittest tests/test_modos.py -v
"""
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import ficticio  # noqa: E402
import simulado  # noqa: E402
import comum  # noqa: E402
import ficha  # noqa: E402
import fluxos  # noqa: E402
from flask import Flask  # noqa: E402
from test_fluxos import Base, ColetorAte, ProvedorFalso, aprovar_tudo, magra, DATA_1, DATA_2  # noqa: E402

TOKEN = "token-de-teste"
DATA_0 = "2026-03-31"          # o mês anterior ao DATA_1: a "montagem completa" acontece nele e a "atualização leve" vem depois


class Espiao(ColetorAte):
    """Coletor simulado que anota, a cada chamada, o que a fila pediu (processo, profundidade, desde)."""

    def __init__(self, base, ate):
        super().__init__(base, ate)
        self.pedidos = []

    def coletar(self, processo, profundidade, desde):
        self.pedidos.append({"numero": processo["numero"], "profundidade": profundidade, "desde": desde})
        return super().coletar(processo, profundidade, desde)


class ProvedorContador(ProvedorFalso):
    """Separa as chamadas que resumem documento das que pedem o momento atual do processo (síntese)."""

    def __init__(self):
        super().__init__()
        self.de_momento = 0

    def gerar(self, sistema, usuario, *, esquema=None, cliente="", partes=()):
        if esquema and "momento" in str(esquema.get("properties", {})):
            self.de_momento += 1
        return super().gerar(sistema, usuario, esquema=esquema, cliente=cliente, partes=partes)

    @property
    def de_resumo(self):
        return self.chamadas - self.de_momento


def proibido(*_args, **_kw):
    raise AssertionError("isto não podia ser chamado: o atalho 'sem coletar' não usa tribunal, login nem IA")


# ================================================================ os valores de cada modo

class ValoresDosModos(unittest.TestCase):
    def test_montagem_completa(self):
        o = fluxos.opcoes_do_preset("completa")
        self.assertEqual((o["profundidade"], o["historico"], o["resumos_ia"], o["sintese"]), ("completo", "todo", True, True))
        self.assertEqual(o["entregas"], ["docx_a", "xlsx_b", "dashboard"])
        self.assertEqual(o["ajustes"], [])

    def test_atualizacao_leve(self):
        o = fluxos.opcoes_do_preset("leve")
        self.assertEqual((o["profundidade"], o["historico"], o["resumos_ia"], o["sintese"]), ("padrao", "novo", True, True))
        self.assertIsNone(o["entregas"])                       # as que o Perfil já tem
        self.assertEqual(fluxos.opcoes_do_preset("leve", profundidade="rapido")["profundidade"], "rapido")

    def test_ajustes_ficam_registrados_e_valor_invalido_e_recusado(self):
        o = fluxos.opcoes_do_preset("completa", resumos_ia=False, historico="novo")
        self.assertEqual((o["resumos_ia"], o["historico"]), (False, "novo"))
        self.assertEqual(o["ajustes"], ["historico", "resumos_ia"])
        self.assertEqual(o["profundidade"], "completo")        # o que não foi ajustado continua o do modo
        for ruim in ({"profundidade": "enorme"}, {"historico": "metade"}, {"entregas": ["nada"]}):
            with self.assertRaises(ValueError):
                fluxos.opcoes_do_preset("leve", **ruim)
        with self.assertRaises(ValueError):
            fluxos.opcoes_do_preset("pesadissima")

    def test_sem_modo_os_valores_sao_os_de_sempre(self):
        self.assertEqual(fluxos.OPCOES_PADRAO, {"preset": None, "historico": None, "resumos_ia": True, "sintese": True})
        self.assertIsNone(fluxos._resolver_opcoes(None, "rapido", None, None, None, ["xlsx_b"]))


# ================================================================ o motor com cada modo

class MotorDosModos(Base):
    N, CLIENTES = 30, 2

    def preparar(self, **kw):
        self.abrir_projeto(**kw)
        self.ia = ProvedorContador()
        self.espiao = Espiao(self.simulado, DATA_0)
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil, cliente: self.ia
        self.addCleanup(setattr, fluxos, "FABRICA_DE_PROVEDOR", None)

    def ciclo(self, funcao, **kw):
        kw.setdefault("modo", "imediato")
        kw.setdefault("coletor", self.espiao)
        kw.setdefault("fila_opcoes", self.fila())
        return funcao(self.slug, **kw)

    def montar_primeiro_mes(self):
        """A montagem completa até a entrega (mês anterior). Devolve o resultado da entrega."""
        self.ciclo(fluxos.inicial, preset="completa", data_base=DATA_0)
        aprovar_tudo()
        r = self.ciclo(fluxos.inicial, preset="completa", data_base=DATA_0)
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        return r

    # --- montagem completa

    def test_completa_pede_tudo_e_gera_as_tres_entregas(self):
        self.preparar()
        r = self.ciclo(fluxos.inicial, preset="completa", data_base=DATA_0)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(r["modo_de_trabalho"], "completa")
        self.assertEqual(len(self.espiao.pedidos), self.N)
        self.assertEqual({p["profundidade"] for p in self.espiao.pedidos}, {"completo"})
        self.assertEqual({p["desde"] for p in self.espiao.pedidos}, {None})           # o histórico todo
        self.assertGreater(self.ia.de_resumo, 0)                                      # resumo por IA dos documentos
        with fluxos._em(self.slug):
            perfil = fluxos._perfil(self.slug)
        self.assertEqual((perfil["profundidade"], perfil["entregas"]), ("completo", ["docx_a", "xlsx_b", "dashboard"]))
        aprovar_tudo()
        r2 = self.ciclo(fluxos.inicial, preset="completa", data_base=DATA_0)
        self.assertEqual(r2["etapa"], "entregue", r2["resumo"])
        nomes = sorted(Path(a).name for a in r2["arquivos"])
        self.assertTrue(any(n.endswith(".docx") for n in nomes) and any(n.startswith("Planilha") for n in nomes)
                        and any(n.startswith("Painel") for n in nomes), nomes)

    def test_completa_numa_atualizacao_refaz_o_historico_sem_duplicar_nada(self):
        self.preparar()
        self.montar_primeiro_mes()
        antes = self.eventos()
        ids_antes, docs_antes = [e["id"] for e in antes], {e["id"]: e.get("conteudo") for e in antes}
        chamadas_antes = self.ia.de_resumo
        self.espiao.pedidos.clear()
        r = self.ciclo(fluxos.atualizar, preset="completa", data_base=DATA_0)
        self.assertIn(r["etapa"], ("revisao", "entregue"), r["resumo"])
        self.assertEqual({p["desde"] for p in self.espiao.pedidos}, {None}, "a montagem completa ignora a data-base")
        depois = self.eventos()
        self.assertEqual(sorted(e["id"] for e in depois), sorted(ids_antes), "nenhum evento duplicado")
        self.assertEqual(self.ia.de_resumo, chamadas_antes, "documento já resumido não é resumido de novo")
        for e in depois:
            self.assertEqual(e.get("conteudo"), docs_antes[e["id"]])

    # --- atualização leve

    def test_leve_so_pede_o_novo_e_nao_repete_resumos(self):
        self.preparar()
        self.montar_primeiro_mes()
        antes = {e["id"]: e for e in self.eventos()}
        resumos_antes = {i: e.get("conteudo") for i, e in antes.items()}
        chamadas_antes = self.ia.de_resumo
        self.espiao.pedidos.clear()
        self.espiao.ate = DATA_1
        r = self.ciclo(fluxos.atualizar, preset="leve", data_base=DATA_1)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(r["modo_de_trabalho"], "leve")
        # pediu só o posterior à data-base do relatório anterior, na leitura padrão
        self.assertEqual({p["desde"] for p in self.espiao.pedidos}, {DATA_0})
        self.assertEqual({p["profundidade"] for p in self.espiao.pedidos}, {"padrao"})
        depois = self.eventos()
        novos = [e for e in depois if e["id"] not in antes]
        self.assertTrue(novos, "o ciclo seguinte trouxe novidades")
        for e in novos:
            self.assertGreater(ficha.parse_data(e["data"]), DATA_0, "nenhum documento ou andamento antigo foi pedido de novo")
        # o que já existia não foi tocado e a IA só resumiu os documentos novos (um chamado por documento)
        for i, e in antes.items():
            self.assertEqual(next(x for x in depois if x["id"] == i).get("conteudo"), resumos_antes[i])
        docs_novos = [e for e in novos if e["tipo_evento"] == "documento" and e.get("conteudo")]
        self.assertGreater(len(docs_novos), 0)
        self.assertEqual(self.ia.de_resumo - chamadas_antes, len(docs_novos))

    def test_leve_rapido_nao_abre_documentos_nem_chama_a_ia(self):
        self.preparar()
        self.montar_primeiro_mes()
        chamadas_antes = self.ia.de_resumo
        self.espiao.pedidos.clear()
        self.espiao.ate = DATA_1
        r = self.ciclo(fluxos.atualizar, preset="leve", profundidade="rapido", data_base=DATA_1)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(self.ia.de_resumo, chamadas_antes)
        self.assertTrue(self.espiao.pedidos)
        self.assertEqual({p["profundidade"] for p in self.espiao.pedidos}, {"rapido"})
        self.assertEqual([e for e in self.eventos() if e["tipo_evento"] == "documento" and ficha.parse_data(e["data"]) > DATA_0], [])
        with fluxos._em(self.slug):
            self.assertEqual(fluxos._perfil(self.slug)["profundidade"], "rapido")

    # --- ajustes das opções avançadas

    def test_sem_ia_nao_chama_o_provedor_e_deixa_o_resumo_para_a_revisao(self):
        self.preparar()
        r = self.ciclo(fluxos.inicial, preset="leve", resumos_ia=False, data_base=DATA_0)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(self.ia.chamadas, 0)          # nem de resumo nem de momento atual
        docs = [e for e in self.eventos() if e["tipo_evento"] == "documento" and e["status"] == "rascunho"]
        self.assertTrue(docs)
        for e in docs:
            self.assertFalse(e.get("conteudo"))
            self.assertTrue(any("Sem resumo por IA" in a for a in e.get("alertas", [])), e.get("alertas"))
        self.assertTrue(any(ficha.obter(f, "momento_atual") for f in self.fichas()), "a consolidação por regra continua")

    def test_sem_consolidar_a_ficha_nao_calcula_o_momento_atual(self):
        self.preparar()
        r = self.ciclo(fluxos.inicial, preset="leve", sintese=False, data_base=DATA_0)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(r["sintese"].get("pulada"), True)
        self.assertFalse(any(ficha.obter(f, "momento_atual") for f in self.fichas()))

    # --- comportamento antigo

    def test_sem_modo_escolhido_tudo_corre_como_sempre(self):
        self.preparar()
        r = self.ciclo(fluxos.inicial, profundidade="padrao", data_base=DATA_0)
        self.assertIsNone(r["modo_de_trabalho"])
        self.assertEqual({p["profundidade"] for p in self.espiao.pedidos}, {"padrao"})
        self.assertEqual(fluxos.opcoes_da_coleta(self.slug), fluxos.OPCOES_PADRAO)
        with fluxos._em(self.slug):
            self.assertNotIn("opcoes_da_coleta", fluxos._estado())
        self.assertGreater(self.ia.de_resumo, 0)

    def test_opcoes_antigas_nao_vazam_para_o_ciclo_seguinte_sem_modo(self):
        self.preparar()
        fluxos.guardar_opcoes(fluxos.opcoes_do_preset("leve", resumos_ia=False), self.slug)        # sobrou de uma preparação da tela
        self.assertFalse(fluxos.opcoes_da_coleta(self.slug)["resumos_ia"])
        self.ciclo(fluxos.inicial, profundidade="padrao", data_base=DATA_0)                         # ciclo novo, sem modo
        self.assertTrue(fluxos.opcoes_da_coleta(self.slug)["resumos_ia"])
        self.assertGreater(self.ia.de_resumo, 0)

    # --- estimativa de resumos por IA

    def semear_documentos(self, n, status="extraido"):
        with fluxos._em(self.slug):
            lista = comum.eventos()
            for i in range(n):
                lista.append({"id": f"X:{i}", "tipo_evento": "documento", "numero": self.verdade[0]["numero"], "cliente": "",
                              "apelido": "", "titulo": f"{i} - Sentença", "detectado_em": "2026-10-07T10:00:00", "status": status,
                              "tipo": "Sentença", "descricao": "Sentença", "data": "01/10/2026"})
            comum.salvar_eventos(lista)

    def test_estimativa_conta_os_documentos_que_ainda_nao_tem_resumo(self):
        self.preparar()
        sem_nada = fluxos.estimar_resumos_ia(self.slug, "padrao")
        self.assertFalse(sem_nada["pode_estimar"])
        self.assertIn("não dá para estimar", sem_nada["frase"])
        self.semear_documentos(3)
        e = fluxos.estimar_resumos_ia(self.slug, "padrao")
        self.assertEqual((e["pendentes"], e["chamadas_min"], e["chamadas_max"]), (3, 3, 6))
        self.assertIn("cerca de 3 documento(s) novo(s)", e["frase"])
        self.assertFalse(e["externa"])
        self.assertIn("desligados", fluxos.estimar_resumos_ia(self.slug, "padrao", {"resumos_ia": False})["frase"])
        self.assertIn("nenhum", fluxos.estimar_resumos_ia(self.slug, "rapido")["frase"])
        self.semear_documentos(0)
        # documento já resumido (rascunho) não entra na conta
        with fluxos._em(self.slug):
            lista = comum.eventos()
            for ev in lista:
                ev["status"] = "rascunho"
            comum.salvar_eventos(lista)
        self.assertEqual(fluxos.estimar_resumos_ia(self.slug, "padrao")["pendentes"], 0)

    # --- atualizar sem coletar (motor)

    def test_atualizar_sem_coletar_regenera_planilha_e_paineis_sem_tribunal_e_sem_ia(self):
        self.preparar(reserva=1)
        self.montar_primeiro_mes()
        relatados = sorted(e["id"] for e in self.eventos() if e["status"] == "relatado")
        self.assertTrue(relatados)
        novo = self.reserva[0]["numero"]
        with fluxos._em(self.slug):                       # a pessoa cadastra um processo: o atalho precisa levá-lo à planilha
            fs = ficha.carregar(todas=True)
            fs.append(magra(self.reserva[0]))
            ficha.salvar(fs)
        import fila
        import ia
        fluxos.FABRICA_DE_PROVEDOR = proibido
        with mock.patch.object(fila, "ColetorReal", proibido), mock.patch.object(fila, "rodar_fila", proibido), \
                mock.patch.object(fluxos, "_coletor_real", proibido), mock.patch.object(ia, "provedor", proibido), \
                mock.patch.object(fluxos, "_coletar", proibido):
            r = fluxos.atualizar_sem_coletar(self.slug)
        self.assertTrue(r["ok"], r["resumo"])
        self.assertTrue(r["sem_coleta"])
        pasta = Path(r["pasta"])
        self.assertTrue(pasta.is_dir() and pasta.name.endswith("-atualizacao-rapida"), pasta)
        nomes = sorted(Path(a).name for a in r["arquivos"])
        self.assertTrue(any(n.startswith("Planilha") for n in nomes) and any(n.startswith("Painel") for n in nomes), nomes)
        self.assertFalse(any(n.endswith(".docx") for n in nomes), "o texto só sai se for pedido")
        import openpyxl
        planilha = next(Path(a) for a in r["arquivos"] if Path(a).suffix == ".xlsx")
        numeros = {str(c) for ws in openpyxl.load_workbook(planilha, data_only=False) for linha in ws.iter_rows(values_only=True)
                   for c in linha if c}
        self.assertTrue(novo in numeros, "o processo cadastrado depois da última entrega entrou na planilha")
        # não é a entrega ao cliente: nada muda de status e a data-base é a da última entrega
        self.assertEqual(sorted(e["id"] for e in self.eventos() if e["status"] == "relatado"), relatados)
        self.assertEqual(len(self.espiao.pedidos), self.N, "nenhuma coleta nova: só a da montagem do primeiro mês")

    def test_atualizar_sem_coletar_com_o_relatorio_vazio_explica(self):
        self.preparar(n=2)
        with fluxos._em(self.slug):
            ficha.salvar([])
        r = fluxos.atualizar_sem_coletar(self.slug)
        self.assertFalse(r["ok"])
        self.assertIn("ainda não tem processos", r["resumo"])
        self.assertIsNone(r["pasta"])
        r = fluxos.atualizar_sem_coletar(self.slug, [])           # nenhuma entrega marcada -> as padrão do atalho
        self.assertFalse(r["ok"])


# ================================================================ as telas

class TelasDosModos(unittest.TestCase):
    N = 30

    def setUp(self):
        from painel import assistente, base, entregas, migracao, perfil, revisao_eventos
        import acesso
        import fila
        self.ass, self.ent, self.fila_mod, self.perfil = assistente, entregas, fila, perfil
        shutil.rmtree(TMP / "projetos-de-teste", ignore_errors=True)
        self.addCleanup(ficticio.restaurar_comum)
        cofre = {"cert_senha": "x", "totp_secret": "y"}
        for p in (mock.patch.object(acesso, "obter", lambda chave: cofre.get(chave)),
                  mock.patch.object(assistente, "INTERVALO_DA_JANELA_S", 0.05),
                  mock.patch.object(entregas, "abrir_fila", self._abrir_fila)):
            p.start()
            self.addCleanup(p.stop)
        self.ia = ProvedorContador()
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil_, cliente: self.ia
        self.addCleanup(setattr, fluxos, "FABRICA_DE_PROVEDOR", None)
        self._zerar()
        self.addCleanup(self._parar)
        base.TAREFA.clear()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        token_ok = base.criar_token_ok(TOKEN)
        for tela in (base, revisao_eventos, assistente, migracao, entregas, perfil):
            tela.registrar(self.app, TOKEN, base.cabecalho, token_ok)
        self.c = self.app.test_client()

    def _abrir_fila(self):
        return self.fila_mod.Fila(comum.PROJETO, pausa_s=(0, 0))

    def _zerar(self):
        self.ass.EXEC.update(thread=None, slug=None, fila=None, estado="parado", pedido=None, resumo=None, erro=None,
                             inicio=None, modo="continuo")
        self.ass.EXEC["log"].clear()

    def _parar(self):
        t = self.ass.EXEC["thread"]
        if t is not None and t.is_alive():
            self.ass.EXEC["pedido"] = "parada"
            self.ass._ESPERA.set()
            t.join(10)
        self.ass.FABRICA_DE_COLETOR = None
        self._zerar()

    # --- apoio

    def abrir_projeto(self, n=None):
        todas = ficticio.gerar_carteira(n if n is not None else self.N, clientes=2, semente=5)
        self.verdade = list(todas)
        self.proj = ficticio.criar_projeto_de_teste([magra(f) for f in todas], nome="Relatório dos Modos")
        self.slug = self.proj["slug"]
        self.simulado = simulado.ColetorSimulado(todas, semente=1, taxa_falha=0.0, pasta=self.proj["pasta"] / "docs-sim")
        self.espiao = Espiao(self.simulado, DATA_0)
        self.ass.FABRICA_DE_COLETOR = lambda: self.espiao

    def get(self, caminho, seguir=True):
        r = self.c.get(caminho, follow_redirects=seguir)
        return r, r.get_data(as_text=True)

    def post(self, caminho, dados=None, seguir=True):
        r = self.c.post(caminho, data={**(dados or {}), "token": TOKEN}, follow_redirects=seguir)
        return r, r.get_data(as_text=True)

    def esperar_coleta(self, segundos=60):
        t = self.ass.EXEC["thread"]
        self.assertIsNotNone(t, "a coleta não foi iniciada")
        t.join(segundos)
        self.assertFalse(t.is_alive(), "a coleta não terminou a tempo")

    def fichas(self):
        return ficha.carregar(todas=True)

    def itens_da_fila(self):
        return {i["numero"]: i for i in self._abrir_fila().itens()}

    def ciclo_completo_pelo_motor(self):
        """Mês 1 já entregue (pelo motor, que é o que a tela usa por baixo): deixa `ultimo_texto_gravado` na data-base 1."""
        kw = dict(coletor=self.espiao, modo="imediato", fila_opcoes=opcoes_rapidas(), data_base=DATA_0)
        fluxos.inicial(self.slug, preset="completa", **kw)
        aprovar_tudo()
        r = fluxos.inicial(self.slug, preset="completa", **kw)
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        return r

    # --- as telas oferecem os dois modos, com quadro e ajuda

    def test_inicio_mostra_os_dois_modos_o_quadro_e_o_atalho(self):
        self.abrir_projeto()
        r, t = self.get("/fluxo")
        self.assertEqual(r.status_code, 200)
        for trecho in ("Montagem completa", "Atualização leve", "Montagem completa x Atualização leve", "Quanto costuma levar",
                       "Resumos por IA", "Consolidação da ficha", "Documentos que baixa", "/fluxo/inicial?modo=completa",
                       "/fluxo/atualizar?modo=leve", "Atualizar planilha e painéis agora (sem coletar)", "action='/entregas/atualizar-agora'"):
            self.assertIn(trecho, t)
        self.assertGreater(t.count("class='ajuda'"), 20)                     # tudo com (i)
        self.assertEqual(t.count("class='botao-grande'"), 4)                 # os quatro caminhos de sempre continuam
        self.assertNotIn("https://", t.replace("http://localhost", ""))     # nada externo

    def test_inicial_oferece_modos_opcoes_avancadas_e_entregas_do_modo(self):
        self.abrir_projeto()
        r, t = self.get("/fluxo/inicial")
        for trecho in ("name='preset' value='completa' checked", "name='preset' value='leve'", "Opções avançadas",
                       "<details class='avancado'>", "name='historico'", "name='resumos_ia'", "name='sintese'",
                       "name='profundidade' value=''", "name='profundidade' value='rapido'", "name='profundidade_leve'",
                       "Conforme o modo escolhido", "Montagem completa x Atualização leve"):
            self.assertIn(trecho, t)
        for entrega in ("docx_a", "xlsx_b", "dashboard"):                    # a completa já vem com as três marcadas
            self.assertIn(f"name='entregas' value='{entrega}' checked", t)
        r, t = self.get("/fluxo/inicial?modo=leve")
        self.assertIn("name='preset' value='leve' checked", t)

    def test_atualizar_oferece_o_modo_leve_e_leva_a_escolha_para_a_conferencia(self):
        self.abrir_projeto()
        r, t = self.get("/fluxo/atualizar")
        self.assertIn("name='preset' value='leve' checked", t)
        self.assertIn("Atualização leve", t)
        r, t = self.post("/fluxo/atualizar/enviar", {"preset": "completa"})
        self.assertEqual(r.request.path, "/fluxo/atualizar/conferir")
        self.assertIn("name='preset' value='completa' checked", t)
        self.assertIn("Opções avançadas", t)

    # --- montagem completa pela tela

    def test_tela_completa_define_os_parametros_estima_ia_e_resume_so_depois_de_confirmar(self):
        self.abrir_projeto()
        r, t = self.post("/fluxo/inicial/preparar", {"preset": "completa", "modo_coleta": "imediato", "so_novos": "1",
                                                     "com_entregas": "1", "entregas": ["docx_a", "xlsx_b", "dashboard"],
                                                     "profundidade": "", "historico": "", "resumos_ia": "", "sintese": ""})
        self.assertEqual(r.request.path, "/fluxo/confirmar")
        self.assertIn("Modo de trabalho:</b> Montagem completa", t)
        self.assertIn("Resumos por IA", t)                                           # a estimativa honesta
        self.assertIn("não dá para estimar", t)                                      # nada coletado ainda: diz que não dá
        perfil = self.perfil.carregar()
        self.assertEqual((perfil["profundidade"], perfil["entregas"]), ("completo", ["docx_a", "xlsx_b", "dashboard"]))
        self.assertEqual({i["desde"] for i in self.itens_da_fila().values()}, {None})
        self.assertEqual({i["profundidade"] for i in self.itens_da_fila().values()}, {"completo"})
        self.assertEqual(self.espiao.pedidos, [])                                    # nada foi coletado antes de confirmar
        self.post("/fluxo/comecar")
        self.esperar_coleta()
        self.assertEqual({p["profundidade"] for p in self.espiao.pedidos}, {"completo"})
        self.assertGreater(self.ia.de_resumo, 0)                                     # o gancho da tela resumiu com a IA
        self.assertTrue(any(ficha.obter(f, "momento_atual") for f in self.fichas()))
        self.assertTrue(any(e["tipo_evento"] == "documento" and e["status"] == "rascunho" for e in comum.eventos()))

    def test_tela_completa_sem_ia_nao_chama_a_ia(self):
        self.abrir_projeto()
        r, t = self.post("/fluxo/inicial/preparar", {"preset": "completa", "modo_coleta": "imediato", "so_novos": "1",
                                                     "com_entregas": "1", "entregas": ["xlsx_b"], "resumos_ia": "nao"})
        self.assertIn("desligados neste modo", t)
        self.post("/fluxo/comecar")
        self.esperar_coleta()
        self.assertEqual(self.ia.chamadas, 0)                                        # nem de resumo nem de momento atual
        self.assertEqual(self.perfil.carregar()["entregas"], ["xlsx_b"])             # a escolha explícita das caixas vale mais

    def test_opcao_avancada_muda_um_valor_do_modo(self):
        self.abrir_projeto()
        r, t = self.post("/fluxo/inicial/preparar", {"preset": "completa", "modo_coleta": "imediato", "so_novos": "1",
                                                     "com_entregas": "1", "entregas": ["xlsx_b"], "profundidade": "rapido",
                                                     "historico": "novo"})
        self.assertEqual(self.perfil.carregar()["profundidade"], "rapido")
        self.assertIn("nenhum", t)                                                   # rápido não abre documentos: sem IA
        self.assertEqual(fluxos.opcoes_da_coleta(self.slug)["historico"], "novo")

    def test_valor_invalido_do_modo_volta_com_mensagem(self):
        self.abrir_projeto()
        r, t = self.post("/fluxo/inicial/preparar", {"preset": "completa", "modo_coleta": "imediato", "profundidade": "enorme",
                                                     "com_entregas": "1", "entregas": ["xlsx_b"]})
        self.assertEqual(r.request.path, "/fluxo/inicial")
        self.assertIn("Profundidade desconhecida", t)

    # --- estimativa na confirmação

    def test_confirmacao_conta_os_documentos_sem_resumo(self):
        self.abrir_projeto()
        with fluxos._em(self.slug):
            lista = comum.eventos()
            for i in range(4):
                lista.append({"id": f"X:{i}", "tipo_evento": "documento", "numero": self.verdade[0]["numero"], "cliente": "",
                              "apelido": "", "titulo": f"{i} - Decisão", "detectado_em": "2026-10-07T10:00:00", "status": "extraido",
                              "tipo": "Decisão", "descricao": "Decisão", "data": "01/10/2026"})
            comum.salvar_eventos(lista)
        r, t = self.post("/fluxo/inicial/preparar", {"preset": "leve", "modo_coleta": "imediato", "so_novos": "1",
                                                     "com_entregas": "1", "entregas": ["xlsx_b"]})
        self.assertIn("Resumos por IA: cerca de 4 documento(s) novo(s)", t)
        self.assertIn("A IA roda neste computador", t)
        self.assertIn("Modo de trabalho:</b> Atualização leve", t)

    # --- atualização leve pela tela

    def test_tela_leve_so_pede_o_novo_e_so_resume_o_novo(self):
        self.abrir_projeto()
        self.ciclo_completo_pelo_motor()                       # mês 1 entregue; o relógio da fila é o de 07/10, ou seja, "outro dia"
        antes = {e["id"]: e.get("conteudo") for e in comum.eventos()}
        chamadas_antes = self.ia.de_resumo
        self.espiao.pedidos.clear()
        self.espiao.ate = DATA_1
        r, t = self.get("/fluxo/atualizar")
        r, t = self.post("/fluxo/atualizar/enviar", {"preset": "leve"})
        self.assertEqual(r.request.path, "/fluxo/atualizar/conferir")
        lote = __import__("re").search(r"name='lote' value='([^']+)'", t).group(1)
        r, t = self.post("/fluxo/atualizar/preparar", {"lote": lote, "preset": "leve", "profundidade_leve": "padrao",
                                                       "modo_coleta": "imediato", "data_base": "", "profundidade": "",
                                                       "historico": "", "resumos_ia": "", "sintese": ""})
        self.assertEqual(r.request.path, "/fluxo/confirmar")
        self.assertIn("Modo de trabalho:</b> Atualização leve", t)
        pendentes = [i for i in self.itens_da_fila().values() if i["estado"] == "pendente"]
        self.assertTrue(pendentes, "a fila trouxe de volta os processos coletados no mês anterior")
        self.assertEqual({i["desde"] for i in pendentes}, {DATA_0})                      # só depois da data-base anterior
        self.assertEqual({i["profundidade"] for i in pendentes}, {"padrao"})
        self.post("/fluxo/comecar")
        self.esperar_coleta()
        self.assertEqual(len(self.espiao.pedidos), len(pendentes))
        depois = comum.eventos()
        novos = [e for e in depois if e["id"] not in antes]
        self.assertTrue(novos)
        for e in novos:
            self.assertGreater(ficha.parse_data(e["data"]), DATA_0)
        for e in depois:
            if e["id"] in antes:
                self.assertEqual(e.get("conteudo"), antes[e["id"]], "resumo já feito não é refeito")
        docs_novos = [e for e in novos if e["tipo_evento"] == "documento" and e.get("conteudo")]
        self.assertGreater(len(docs_novos), 0)
        self.assertEqual(self.ia.de_resumo - chamadas_antes, len(docs_novos))

    # --- sem modo escolhido, como sempre

    def test_formulario_antigo_sem_modo_continua_igual(self):
        self.abrir_projeto()
        r, t = self.post("/fluxo/inicial/preparar", {"com_entregas": "1", "entregas": ["xlsx_b"], "profundidade": "padrao",
                                                     "modo_coleta": "imediato", "so_novos": "1"})
        self.assertEqual(r.request.path, "/fluxo/confirmar")
        self.assertNotIn("Modo de trabalho:", t)
        self.assertEqual(fluxos.opcoes_da_coleta(self.slug), fluxos.OPCOES_PADRAO)
        perfil = self.perfil.carregar()
        self.assertEqual((perfil["profundidade"], perfil["entregas"]), ("padrao", ["xlsx_b"]))
        self.post("/fluxo/comecar")
        self.esperar_coleta()
        self.assertGreater(self.ia.de_resumo, 0)

    # --- atualizar sem coletar (telas)

    def test_entregas_mostra_o_atalho_com_confirmacao_e_ajuda(self):
        self.abrir_projeto()
        r, t = self.get("/entregas")
        self.assertIn("Atualizar planilha e painéis agora (sem coletar)", t)
        self.assertIn("action='/entregas/atualizar-agora'", t)
        self.assertEqual(t.count("onsubmit=\"return confirm("), 2)                    # o atalho e o "Gerar entregas"
        self.assertIn("sem tribunal", t)

    def test_atalho_regenera_sem_chamar_coletor_nem_ia_e_diz_onde_gravou(self):
        self.abrir_projeto()
        self.ciclo_completo_pelo_motor()
        pasta_saida = self.ent.pasta_saida()
        rodadas_antes = sorted(p.name for p in pasta_saida.iterdir())
        relatados = sorted(e["id"] for e in comum.eventos() if e["status"] == "relatado")
        chamadas_antes, pedidos_antes = self.ia.chamadas, len(self.espiao.pedidos)
        self.assertGreater(pedidos_antes, 0)
        fluxos.FABRICA_DE_PROVEDOR = proibido
        self.ass.FABRICA_DE_COLETOR = proibido
        import ia
        with mock.patch.object(self.fila_mod, "ColetorReal", proibido), mock.patch.object(self.fila_mod, "rodar_fila", proibido), \
                mock.patch.object(self.ass, "iniciar_execucao", proibido), mock.patch.object(ia, "provedor", proibido):
            r, t = self.post("/entregas/atualizar-agora", {"entregas": ["xlsx_b", "dashboard"], "volta": "/entregas"})
        self.assertEqual(r.request.path, "/entregas")
        self.assertIn("Atualizado sem coletar nada (sem tribunal, sem IA).", t)
        self.assertIn("Os arquivos foram gravados na pasta:", t)
        self.assertIn(str(pasta_saida), t)
        self.assertIn("atualizacao-rapida", t)
        self.assertIn("Planilha - ", t)
        self.assertIn("Painel - ", t)
        novas = [p for p in pasta_saida.iterdir() if p.name not in rodadas_antes]
        self.assertEqual(len(novas), 1)
        nomes = sorted(a.name for a in novas[0].iterdir())
        self.assertTrue(any(n.startswith("Planilha") for n in nomes) and any(n.startswith("Painel") for n in nomes), nomes)
        self.assertFalse(any(n.endswith(".docx") for n in nomes))
        self.assertEqual((self.ia.chamadas, len(self.espiao.pedidos)), (chamadas_antes, pedidos_antes))
        self.assertEqual(sorted(e["id"] for e in comum.eventos() if e["status"] == "relatado"), relatados)
        self.assertIn(novas[0].name, self.get("/entregas")[1])                          # a lista de arquivos entregues mostra a pasta nova

    def test_atalho_do_fim_do_assistente_volta_para_onde_a_pessoa_estava(self):
        self.abrir_projeto()
        self.ciclo_completo_pelo_motor()
        r, t = self.get("/fluxo")
        self.assertIn("name='volta' value='/fluxo'", t)
        r, t = self.post("/entregas/atualizar-agora", {"entregas": ["xlsx_b"], "volta": "/fluxo"})
        self.assertEqual(r.request.path, "/fluxo")
        self.assertIn("Atualizado sem coletar nada", t)
        r, t = self.post("/entregas/atualizar-agora", {"entregas": ["xlsx_b"], "volta": "http://outro-site.exemplo/"})
        self.assertEqual(r.request.path, "/entregas")                                   # só endereços do próprio painel

    def test_atalho_mensagens_claras_e_token(self):
        self.abrir_projeto()
        r, t = self.post("/entregas/atualizar-agora", {"volta": "/entregas"})
        self.assertIn("Marque pelo menos uma entrega", t)
        r = self.c.post("/entregas/atualizar-agora", data={"entregas": ["xlsx_b"]})
        self.assertEqual(r.status_code, 403)

    def test_atalho_com_relatorio_vazio_e_sem_relatorio(self):
        self.abrir_projeto(n=0)
        r, t = self.post("/entregas/atualizar-agora", {"entregas": ["xlsx_b", "dashboard"]})
        self.assertIn("ainda não tem processos", t)
        shutil.rmtree(TMP / "projetos-de-teste", ignore_errors=True)         # nenhum relatório: o painel manda criar o primeiro
        comum.PROJETO = None
        r, t = self.post("/entregas/atualizar-agora", {"entregas": ["xlsx_b"]}, seguir=False)
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/novo"))
        r, t = self.get("/fluxo")                                            # o início do Assistente abre e explica
        self.assertIn("Quando houver um relatório", t)


def opcoes_rapidas():
    from test_fluxos import Relogio, opcoes_da_fila
    return opcoes_da_fila(Relogio())


if __name__ == "__main__":
    unittest.main()
