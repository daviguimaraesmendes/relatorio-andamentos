"""Duas decisões do dono para a revisão:

A) RESUMIR MAIS TARDE: documentos que ficaram só com a frase automática (rodada sem IA, IA não configurada ou fora do ar) podem
   ser resumidos depois (`fluxos.resumir_pendentes`), sem coletar nada, sem tocar no que já foi aprovado e respeitando o
   consentimento para IA externa; a tela Revisar mostra o contador e o botão.
B) APROVAR TODAS AS ATUALIZAÇÕES em lote (`triagem.aplicar_lote_total`, POST /triagem/lote-todas): inclui amarelas e vermelhas
   depois de "li os alertas", mas nunca o que as travas da revisão recusam.

Dados fictícios, sem rede, sem IA real, sem login e sem o cofre real.

    python3 -m unittest tests.test_resumir_depois -v
"""
import copy
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import comum  # noqa: E402
import ficticio  # noqa: E402
import ficha as fch  # noqa: E402
import fluxos  # noqa: E402
import triagem  # noqa: E402
from flask import Flask  # noqa: E402
from test_fluxos import Base, ProvedorFalso  # noqa: E402
from test_triagem import gerar_eventos  # noqa: E402

TOKEN = "token-de-teste"
REVISOR = "Revisora Teste"


class ProvedorQueFalha:
    def __init__(self):
        self.chamadas = 0

    def gerar(self, *a, **k):
        self.chamadas += 1
        raise RuntimeError("fora do ar")


def proibido(*_a, **_k):
    raise AssertionError("a IA não podia ser chamada aqui")


def documentos(lista, status="rascunho"):
    return [e for e in lista if e["tipo_evento"] == "documento" and e["status"] == status]


# ================================================================ A) motor

class ResumirDepois(Base):
    N, CLIENTES = 10, 2

    def preparar_sem_ia(self):
        """Uma rodada com os resumos por IA desligados: os documentos vão à revisão só com a frase automática."""
        self.abrir_projeto()
        self.ia = ProvedorFalso()
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil, cliente: self.ia
        self.addCleanup(setattr, fluxos, "FABRICA_DE_PROVEDOR", None)
        r = self.inicial(resumos_ia=False)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(self.ia.chamadas, 0)
        self.docs = documentos(self.eventos())
        self.assertTrue(self.docs, "o simulado deveria trazer documentos")

    def com_texto(self):
        return [e for e in self.docs if (e.get("texto_arquivo") and Path(e["texto_arquivo"]).exists())]

    def test_rodada_sem_ia_marca_o_sinal_e_o_contador_conta(self):
        self.preparar_sem_ia()
        marcados = [e for e in self.docs if e.get("resumo_pendente_ia")]
        self.assertEqual(len(marcados), len(self.com_texto()))
        self.assertTrue(marcados)
        for e in marcados:
            self.assertFalse(e.get("conteudo"))
            self.assertTrue(any("Sem resumo por IA" in a for a in e["alertas"]))
        self.assertEqual(fluxos.contar_sem_resumo_ia(self.slug), len(marcados))

    def test_resumir_pendentes_resume_limpa_o_sinal_e_nao_chama_o_tribunal(self):
        self.preparar_sem_ia()
        n = fluxos.contar_sem_resumo_ia(self.slug)
        estimativa = fluxos.estimar_resumir_pendentes(self.slug)
        self.assertEqual((estimativa["pendentes"], estimativa["chamadas_min"], estimativa["chamadas_max"]), (n, n, 2 * n))
        self.assertTrue(estimativa["pode_rodar"])
        self.assertIn(f"{n} documento(s)", estimativa["frase"])
        self.assertEqual(self.ia.chamadas, 0)                       # estimar não chama a IA
        movimentos_antes = [e for e in self.eventos() if e["tipo_evento"] == "movimento"]
        coletados = len(self.coletor.completos)
        avisos_de_progresso = []
        r = fluxos.resumir_pendentes(self.slug, ao_progresso=avisos_de_progresso.append)
        self.assertTrue(r["ok"], r["resumo"])
        self.assertEqual((r["resumidos"], r["falhas"], r["sem_consentimento"]), (n, 0, 0))
        self.assertEqual(self.ia.chamadas, n)
        self.assertTrue(avisos_de_progresso)
        self.assertEqual(len(self.coletor.completos), coletados)    # nada foi coletado
        depois = self.eventos()
        self.assertEqual([e for e in depois if e["tipo_evento"] == "movimento"], movimentos_antes)
        for e in documentos(depois):
            if e["id"] in {d["id"] for d in self.com_texto()}:
                self.assertTrue(e["conteudo"])
                self.assertEqual(e["status"], "rascunho")           # continua sendo rascunho: ainda falta a aprovação
                self.assertEqual(e["motor"], "local:falso")
                self.assertNotIn("resumo_pendente_ia", e)
                self.assertFalse(any(a.startswith("Sem resumo por IA") for a in e["alertas"]), e["alertas"])
        self.assertEqual(fluxos.contar_sem_resumo_ia(self.slug), 0)
        r2 = fluxos.resumir_pendentes(self.slug)                    # idempotente: nada a fazer, nenhuma chamada nova
        self.assertEqual((r2["resumidos"], r2["pendentes"]), (0, 0))
        self.assertEqual(self.ia.chamadas, n)
        self.assertIn("Nenhum documento", r2["resumo"])

    def test_nao_toca_em_aprovado_relatado_descartado_nem_na_frase_corrigida(self):
        self.preparar_sem_ia()
        alvo = [e for e in self.com_texto()]
        self.assertGreaterEqual(len(alvo), 4)
        lista = comum.eventos() if False else None
        with fluxos._em(self.slug):
            lista = comum.eventos()
            ids = [e["id"] for e in alvo]
            por_id = {e["id"]: e for e in lista}
            por_id[ids[0]]["status"] = "aprovado"
            por_id[ids[1]]["status"] = "relatado"
            por_id[ids[2]]["status"] = "descartado"
            por_id[ids[3]]["frase"] = "Frase que a advogada corrigiu à mão."
            por_id[ids[3]]["prazo"] = "5 dias, anotado à mão"
            comum.salvar_eventos(lista)
        antes = {i: copy.deepcopy(por_id[i]) for i in ids[:3]}
        r = fluxos.resumir_pendentes(self.slug)
        self.assertEqual(r["resumidos"], len(alvo) - 3)
        depois = {e["id"]: e for e in self.eventos()}
        for i in ids[:3]:
            self.assertEqual(depois[i], antes[i])                   # intocados, inclusive o sinal
        self.assertEqual(depois[ids[3]]["frase"], "Frase que a advogada corrigiu à mão.")
        self.assertEqual(depois[ids[3]]["prazo"], "5 dias, anotado à mão")
        self.assertTrue(depois[ids[3]]["conteudo"])

    def test_filtra_por_processo(self):
        self.preparar_sem_ia()
        numero = self.com_texto()[0]["numero"]
        esperado = sum(1 for e in self.com_texto() if e["numero"] == numero)
        r = fluxos.resumir_pendentes(self.slug, numeros=[numero])
        self.assertEqual(r["resumidos"], esperado)
        self.assertEqual(fluxos.contar_sem_resumo_ia(self.slug), len(self.com_texto()) - esperado)

    def test_falha_da_ia_conta_e_deixa_o_documento_como_estava(self):
        self.preparar_sem_ia()
        falho = ProvedorQueFalha()
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil, cliente: falho
        n = fluxos.contar_sem_resumo_ia(self.slug)
        antes = {e["id"]: copy.deepcopy(e) for e in self.eventos()}
        r = fluxos.resumir_pendentes(self.slug)
        self.assertFalse(r["ok"])
        self.assertEqual((r["resumidos"], r["falhas"]), (0, n))
        self.assertIn("ia_sem_resposta", {a["codigo"] for a in r["avisos"]})
        self.assertEqual({e["id"]: e for e in self.eventos()}, antes)
        self.assertEqual(fluxos.contar_sem_resumo_ia(self.slug), n)   # dá para tentar de novo
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil, cliente: self.ia
        self.assertEqual(fluxos.resumir_pendentes(self.slug)["resumidos"], n)

    def test_ia_que_nao_respondeu_na_rodada_tambem_vira_pendente(self):
        self.abrir_projeto()
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil, cliente: ProvedorQueFalha()
        self.addCleanup(setattr, fluxos, "FABRICA_DE_PROVEDOR", None)
        self.inicial()
        docs = documentos(self.eventos())
        com = [e for e in docs if e.get("resumo_pendente_ia")]
        self.assertTrue(com)
        for e in com:
            self.assertTrue(any(a.startswith(fluxos.PREFIXO_ALERTA_IA_FALHOU) for a in e["alertas"]))
        self.ia = ProvedorFalso()
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil, cliente: self.ia
        r = fluxos.resumir_pendentes(self.slug)
        self.assertEqual(r["resumidos"], len(com))

    def test_evento_antigo_sem_o_sinal_e_reconhecido_pelo_alerta(self):
        self.preparar_sem_ia()
        with fluxos._em(self.slug):
            lista = comum.eventos()
            for e in lista:
                e.pop("resumo_pendente_ia", None)
            comum.salvar_eventos(lista)
        self.assertEqual(fluxos.contar_sem_resumo_ia(self.slug), len(self.com_texto()))

    def test_documento_sem_texto_nao_entra_na_conta_e_nao_e_inventado(self):
        self.preparar_sem_ia()
        com = self.com_texto()
        with fluxos._em(self.slug):
            lista = comum.eventos()
            alvo = next(e for e in lista if e["id"] == com[0]["id"])
            Path(alvo["texto_arquivo"]).unlink()                    # o texto sumiu depois da rodada
            comum.salvar_eventos(lista)
        e = fluxos.estimar_resumir_pendentes(self.slug)
        self.assertEqual((e["pendentes"], e["sem_texto"]), (len(com) - 1, 1))
        r = fluxos.resumir_pendentes(self.slug)
        self.assertEqual((r["resumidos"], r["sem_texto"]), (len(com) - 1, 1))
        self.assertIn("documento_sem_texto", {a["codigo"] for a in r["avisos"]})
        sobrou = next(x for x in self.eventos() if x["id"] == com[0]["id"])
        self.assertFalse(sobrou.get("conteudo"))

    def test_ia_externa_sem_consentimento_nao_roda_e_explica(self):
        self.preparar_sem_ia()
        fluxos.FABRICA_DE_PROVEDOR = proibido
        perfil = {"ia": {"provedor": "provedor-externo", "consentimento_externo": False, "pseudonimizar": True}}
        n = fluxos.contar_sem_resumo_ia(self.slug)
        with mock.patch.object(fluxos, "_perfil", lambda slug: perfil):
            e = fluxos.estimar_resumir_pendentes(self.slug)
            self.assertEqual((e["pendentes"], e["sem_consentimento"], e["pode_rodar"], e["externa"]), (0, n, False, True))
            self.assertIn("consentimento", e["frase"])
            antes = {x["id"]: copy.deepcopy(x) for x in self.eventos()}
            r = fluxos.resumir_pendentes(self.slug)
        self.assertEqual((r["resumidos"], r["sem_consentimento"]), (0, n))
        self.assertFalse(r["ok"])
        self.assertIn("ia_externa_sem_consentimento", {a["codigo"] for a in r["avisos"]})
        self.assertIn("Nada saiu do computador", " ".join(a["mensagem"] for a in r["avisos"]))
        self.assertEqual({x["id"]: x for x in self.eventos()}, antes)

    def test_ia_externa_com_consentimento_do_cliente_usa_o_provedor(self):
        self.preparar_sem_ia()
        clientes = {e["cliente"] for e in self.com_texto()}
        perfil = {"ia": {"provedor": "provedor-externo", "consentimento_externo": False, "pseudonimizar": True,
                         "por_cliente": {c: True for c in clientes}}}
        n = fluxos.contar_sem_resumo_ia(self.slug)
        with mock.patch.object(fluxos, "_perfil", lambda slug: perfil):
            r = fluxos.resumir_pendentes(self.slug)
        self.assertEqual(r["resumidos"], n)
        self.assertEqual(self.ia.chamadas, n)

    def test_sem_relatorio_ativo_pede_o_projeto(self):
        with self.assertRaises(ValueError):
            with mock.patch.object(comum, "PROJETO", None):
                fluxos.resumir_pendentes()


# ================================================================ telas

def montar_app():
    from painel import base, revisao_eventos, revisao_lote, revisao_resumir
    app = Flask(__name__)
    app.config["TESTING"] = True
    token_ok = base.criar_token_ok(TOKEN)
    for tela in (base, revisao_eventos, revisao_lote, revisao_resumir):
        tela.registrar(app, TOKEN, base.cabecalho, token_ok)
    return app


class TelaResumir(Base):
    N, CLIENTES = 6, 2

    def setUp(self):
        self.abrir_projeto()
        from painel import revisao_resumir
        self.rr = revisao_resumir
        self.ia = ProvedorFalso()
        fluxos.FABRICA_DE_PROVEDOR = lambda perfil, cliente: self.ia
        self.addCleanup(setattr, fluxos, "FABRICA_DE_PROVEDOR", None)
        self.c = montar_app().test_client()
        self.addCleanup(self.rr.ESTADO.update, rodando=False, slug=None, resultado=None, mensagem="")
        self.rr.ESTADO.update(rodando=False, slug=None, resultado=None, mensagem="")

    def get(self, caminho):
        r = self.c.get(caminho)
        return r, r.get_data(as_text=True)

    def com_documentos_sem_ia(self):
        r = self.inicial(resumos_ia=False)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        return fluxos.contar_sem_resumo_ia(self.slug)

    def test_revisar_sem_pendentes_nao_mostra_a_caixa(self):
        _, h = self.get("/")
        self.assertNotIn("sem resumo de IA", h)
        self.assertNotIn("Resumir os que ficaram sem IA", h)

    def test_revisar_mostra_contador_botao_e_ajuda(self):
        n = self.com_documentos_sem_ia()
        self.assertGreater(n, 0)
        r, h = self.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"<b>{n} documento(s) sem resumo de IA</b>", h)
        self.assertIn("Resumir os que ficaram sem IA", h)
        self.assertIn("action='/resumir-pendentes'", h)
        trecho = h.split("id='sem-ia'", 1)[1].split("</form>", 1)[0]
        self.assertGreaterEqual(trecho.count("class='ajuda'"), 2)           # contador e botão, os dois com (i)
        self.assertNotRegex(h, r"https?://(?!127\.0\.0\.1|localhost)")
        _, t = self.get("/triagem")
        self.assertIn(f"{n} documento(s) sem resumo de IA", t)               # também na triagem

    def test_confirmacao_mostra_estimativa_antes_de_chamar_a_ia(self):
        n = self.com_documentos_sem_ia()
        r, h = self.get("/resumir-pendentes")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"{n} documento(s) serão resumidos: de {n} a {2 * n} chamada(s) à IA", h)
        self.assertIn("A IA roda neste computador", h)
        self.assertIn(f"Confirmar e resumir {n} documento(s)", h)
        self.assertGreaterEqual(h.count("class='ajuda'"), 3)
        self.assertEqual(self.ia.chamadas, 0)

    def test_confirmar_resume_em_segundo_plano_e_mostra_o_resultado(self):
        n = self.com_documentos_sem_ia()
        r = self.c.post("/resumir-pendentes", data={"token": TOKEN})
        self.assertEqual(r.status_code, 302)
        self.rr.ESTADO["thread"].join(60)
        self.assertFalse(self.rr.ESTADO["rodando"])
        self.assertEqual(self.ia.chamadas, n)
        _, h = self.get("/resumir-pendentes")
        self.assertIn(f"{n} documento(s) resumido(s) de {n}", h)
        self.assertIn("Nenhum documento ficou sem resumo de IA", h)
        self.assertIn("disabled", h)                                          # nada mais a fazer
        _, rev = self.get("/")
        self.assertNotIn("sem resumo de IA</b>", rev)

    def test_post_sem_token_e_sem_pendentes(self):
        self.assertEqual(self.c.post("/resumir-pendentes", data={}).status_code, 403)
        r = self.c.post("/resumir-pendentes", data={"token": TOKEN})
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self.rr.ESTADO["thread"] if not self.rr.ESTADO["rodando"] and self.rr.ESTADO["resultado"] else None)
        self.assertEqual(self.ia.chamadas, 0)

    def test_externa_sem_consentimento_explica_na_tela_e_nao_roda(self):
        self.com_documentos_sem_ia()
        perfil = {"ia": {"provedor": "provedor-externo", "consentimento_externo": False}}
        fluxos.FABRICA_DE_PROVEDOR = proibido
        with mock.patch.object(fluxos, "_perfil", lambda slug: perfil):
            _, h = self.get("/resumir-pendentes")
            self.assertIn("não há consentimento", h)
            self.assertIn("disabled", h)
            r = self.c.post("/resumir-pendentes", data={"token": TOKEN})
            self.assertEqual(r.status_code, 302)
        self.assertFalse(self.rr.ESTADO["rodando"])


# ================================================================ B) aprovar todas as atualizações

class Dados(unittest.TestCase):
    """Rascunhos fictícios de todos os níveis, mais os casos que as travas recusam."""

    @classmethod
    def setUpClass(cls):
        shutil.rmtree(TMP / "projetos-de-teste", ignore_errors=True)
        cls.fichas = ficticio.gerar_carteira(20, clientes=3, semente=3)
        cls.eventos0, _, cls.gabarito = gerar_eventos(120, fichas=cls.fichas, pasta=TMP / "triagem-docs-lote-todas")
        cls.projeto = ficticio.criar_projeto_de_teste(cls.fichas, nome="Lote de Todas")
        import acesso
        cofre = {}
        cls.patches = [mock.patch.object(acesso, "obter", lambda chave: cofre.get(chave))]
        for nome, mod in list(sys.modules.items()):
            if mod is not None and (nome in ("comum",) or nome.startswith("painel.")) and hasattr(mod, "config"):
                cls.patches.append(mock.patch.object(mod, "config", lambda: {"revisor": REVISOR}))
        for p in cls.patches:
            p.start()
        cls.c = montar_app().test_client()

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        ficticio.restaurar_comum()

    def setUp(self):
        self.eventos = copy.deepcopy(self.eventos0)
        numero = self.eventos[0]["numero"]
        cliente = self.eventos[0]["cliente"]
        base = dict(numero=numero, cliente=cliente, status="rascunho", data="01/09/2026", detectado_em="2026-09-01T19:00:00")
        # casos que as travas recusam, em qualquer nível
        self.sem_frase = {**base, "id": "b:sem-frase", "tipo_evento": "movimento", "titulo": "X", "frase": "", "conteudo": ""}
        self.doc_sem_texto = {**base, "id": "b:sem-texto", "tipo_evento": "documento", "titulo": "9 - Petição", "tipo": "Petição",
                              "frase": "A parte contrária apresentou petição", "conteudo": "", "autoria": "contraria",
                              "polo_cliente": "passivo", "alertas": ["Sem resumo automático: o documento não tem texto legível; "
                                                                     "abrir nos autos e resumir manualmente."]}
        self.doc_sem_ia = {**self.doc_sem_texto, "id": "b:sem-ia", "texto_arquivo": str(TMP / "triagem-docs-lote-todas" / "doc0002.txt"),
                           "resumo_pendente_ia": True, "alertas": [fluxos.ALERTA_SEM_IA_DESLIGADA]}
        self.amostra = {**self.eventos[2], "id": "b:amostra", "amostra_lote": "lote-anterior"}
        self.eventos += [self.sem_frase, self.doc_sem_texto, self.doc_sem_ia, self.amostra]
        self.bloqueados = {"b:sem-frase", "b:sem-texto", "b:sem-ia", "b:amostra"}
        comum.salvar_eventos(self.eventos)
        fch.salvar(copy.deepcopy(self.fichas))
        (comum.DATA / "lotes.json").unlink(missing_ok=True)

    def post(self, dados=None, token=True):
        corpo = dict(dados or {})
        if token:
            corpo["token"] = TOKEN
        return self.c.post("/triagem/lote-todas", data=corpo)

    def em_disco(self):
        return {e["id"]: e for e in comum.eventos()}

    def niveis(self):
        return {i["ev"]["id"]: i["nivel"] for i in triagem.classificar_lista(comum.eventos(), fch.carregar(todas=True), status=None)}


class TriagemTotal(Dados):
    def test_plano_inclui_todos_os_niveis_e_separa_os_bloqueios(self):
        plano = triagem.preparar_lote_total(comum.eventos(), fch.carregar(todas=True))
        ids = {i["ev"]["id"] for i in plano["aprovar"]}
        self.assertFalse(ids & self.bloqueados)
        self.assertEqual(len(ids) + plano["total_bloqueados"], len(self.eventos))
        self.assertTrue(plano["por_nivel"]["amarelo"] and plano["por_nivel"]["vermelho"] and plano["por_nivel"]["verde"])
        self.assertEqual(plano["com_alerta"], plano["por_nivel"]["amarelo"] + plano["por_nivel"]["vermelho"])
        self.assertEqual(plano["bloqueados"]["sem_frase"], 1)
        self.assertEqual(plano["bloqueados"]["sem_texto"], 1)
        self.assertEqual(plano["bloqueados"]["resumo_pendente_ia"], 1)
        self.assertEqual(plano["bloqueados"]["amostra_anterior"], 1)

    def test_aplicar_registra_como_lote_de_todas(self):
        lista, fichas = comum.eventos(), fch.carregar(todas=True)
        r = triagem.aplicar_lote_total(lista, fichas, REVISOR, {"cliente": ""})
        self.assertEqual((r["tipo"], r["aprovado_por"], r["amostra"]), ("todas", REVISOR, []))
        self.assertTrue(r["id"].startswith("lote-todas-"))
        aprovados = [e for e in lista if e["status"] == "aprovado"]
        self.assertEqual(sorted(e["id"] for e in aprovados), sorted(r["aprovados"]))
        for e in aprovados:
            self.assertEqual((e["aprovado_por"], e["lote"], e["lote_tipo"]), (REVISOR, r["id"], "todas"))
            self.assertIn(e["triagem"]["nivel"], triagem.NIVEIS)
        with self.assertRaises(ValueError):
            triagem.aplicar_lote_total(lista, fichas, " ")


class TelaLoteTodas(Dados):
    def test_tela_mostra_numeros_alerta_confirmacao_e_ajuda(self):
        r = self.c.get("/triagem")
        h = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        plano = triagem.preparar_lote_total(comum.eventos(), fch.carregar(todas=True))
        pn = plano["por_nivel"]
        corpo = h.split("id='lote-todas'", 1)[1].split("</form>", 1)[0]
        self.assertIn("Aprovar todas as atualizações", corpo)
        self.assertIn(f"seriam aprovadas <b>{len(plano['aprovar'])}</b> linha(s): <b>{pn['verde']}</b> verde(s), "
                      f"<b>{pn['amarelo']}</b> amarela(s) e <b>{pn['vermelho']}</b> vermelha(s)", corpo)
        self.assertIn(f"{plano['com_alerta']} linha(s) têm alerta", corpo)
        self.assertIn("serão aprovadas mesmo assim", corpo)
        self.assertIn("name='li_alertas' value='1' required", corpo)
        self.assertIn(f"name='esperado' value='{len(plano['aprovar'])}'", corpo)
        self.assertIn("confirm(", corpo)
        self.assertGreaterEqual(corpo.count("class='ajuda'"), 3)
        for texto in ("sem a frase do relatório", "documento sem texto legível", "ainda pode ser resumido pela IA", "amostra de um lote anterior"):
            self.assertIn(texto, corpo)
        self.assertNotRegex(h, r"https?://(?!127\.0\.0\.1)")
        # a aprovação só dos verdes continua ali, igual
        self.assertIn("Aprovação em lote (só verdes)", h)

    def test_sem_token_sem_confirmacao_e_sem_li_alertas_nada_muda(self):
        self.assertEqual(self.post({"confirmar": "1"}, token=False).status_code, 403)
        self.assertEqual(self.post({}).status_code, 400)
        n = len(triagem.preparar_lote_total(comum.eventos(), fch.carregar(todas=True))["aprovar"])
        r = self.post({"confirmar": "1", "esperado": str(n)})                      # há alertas e faltou "li os alertas"
        self.assertEqual(r.status_code, 400)
        self.assertTrue(all(e["status"] == "rascunho" for e in comum.eventos()))
        self.assertFalse((comum.DATA / "lotes.json").exists())

    def test_numero_esperado_diferente_nao_aprova(self):
        r = self.post({"confirmar": "1", "li_alertas": "1", "esperado": "3"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("mudou", r.headers["Location"])
        self.assertTrue(all(e["status"] == "rascunho" for e in comum.eventos()))

    def test_aprova_todas_menos_as_travadas_e_registra_o_lote(self):
        antes = self.niveis()
        plano = triagem.preparar_lote_total(comum.eventos(), fch.carregar(todas=True))
        r = self.post({"confirmar": "1", "li_alertas": "1", "esperado": str(len(plano["aprovar"]))})
        self.assertEqual(r.status_code, 302)
        em_disco = self.em_disco()
        aprovados = {i for i, e in em_disco.items() if e["status"] == "aprovado"}
        self.assertEqual(aprovados, {i["ev"]["id"] for i in plano["aprovar"]})
        self.assertTrue({antes[i] for i in aprovados} >= {"verde", "amarelo", "vermelho"})   # não só os verdes
        for i in self.bloqueados:
            self.assertEqual(em_disco[i]["status"], "rascunho", i)
        lotes = comum.load_json(comum.DATA / "lotes.json", [])
        self.assertEqual(len(lotes), 1)
        self.assertEqual((lotes[0]["tipo"], lotes[0]["aprovado_por"], sorted(lotes[0]["aprovados"])),
                         ("todas", REVISOR, sorted(aprovados)))
        self.assertTrue(all(em_disco[i]["aprovado_em"] and em_disco[i]["lote"] == lotes[0]["id"] for i in aprovados))
        h = self.c.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Aprovadas todas as atualizações", h)
        self.assertIn("todas as atualizações:", h)                                   # nos últimos lotes
        # repetir não aprova mais nada
        r2 = self.post({"confirmar": "1", "li_alertas": "1", "esperado": "0"})
        self.assertIn("Nenhuma+linha+liberada", r2.headers["Location"].replace("%20", "+"))
        self.assertEqual(len(comum.load_json(comum.DATA / "lotes.json", [])), 1)

    def test_respeita_filtros_de_cliente_e_de_nivel(self):
        cliente = self.eventos[0]["cliente"]
        plano = triagem.preparar_lote_total(comum.eventos(), fch.carregar(todas=True), {"cliente": cliente, "nivel": "amarelo"})
        self.assertTrue(plano["aprovar"])
        self.assertEqual(plano["por_nivel"]["verde"] + plano["por_nivel"]["vermelho"], 0)
        r = self.post({"confirmar": "1", "li_alertas": "1", "esperado": str(len(plano["aprovar"])), "cliente": cliente, "nivel": "amarelo"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("cliente=", r.headers["Location"])
        self.assertIn("nivel=amarelo", r.headers["Location"])
        niveis = self.niveis()
        for i, e in self.em_disco().items():
            if e["status"] == "aprovado":
                self.assertEqual((e["cliente"], niveis[i]), (cliente, "amarelo"))

    def test_so_verdes_sem_alerta_dispensa_o_li_alertas(self):
        verdes = [e for e in self.eventos0 if self.gabarito[e["id"]][1] == "verde"]
        comum.salvar_eventos(verdes)
        plano = triagem.preparar_lote_total(comum.eventos(), fch.carregar(todas=True))
        self.assertEqual(plano["com_alerta"], 0)
        h = self.c.get("/triagem").get_data(as_text=True).split("id='lote-todas'", 1)[1].split("</form>", 1)[0]
        self.assertNotIn("li_alertas", h)
        r = self.post({"confirmar": "1", "esperado": str(len(plano["aprovar"]))})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(all(e["status"] == "aprovado" for e in comum.eventos()))

    def test_lote_so_dos_verdes_continua_como_era(self):
        antes = self.niveis()
        r = self.c.post("/triagem/lote", data={"token": TOKEN, "confirmar": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(all(antes[i] == "verde" for i, e in self.em_disco().items() if e["status"] == "aprovado"))


if __name__ == "__main__":
    unittest.main()
