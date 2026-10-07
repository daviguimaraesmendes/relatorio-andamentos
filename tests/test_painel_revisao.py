"""Testes das telas de revisão em escala (painel/revisao_lote.py = /triagem, painel/processo.py = /processo)
e da fatia de revisão que já existia (painel/revisao_eventos.py), com `app.test_client()`, 600 eventos
fictícios e um relatório temporário. Sem rede, sem tocar em projetos/ real.

O módulo de sugestão de julgamento (julgamento.py, WS-17) é construído em paralelo: aqui ele é um STUB
que segue a interface do CONTRATOS §10 (`sugerir(ficha, eventos) -> {campo: {valor, regra, evidencia,
ressalvas}}`), injetado pelo teste; nenhum teste depende de o módulo real existir.

    python3 -m unittest tests/test_painel_revisao.py -v
"""
import copy
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import comum  # noqa: E402
import ficticio  # noqa: E402
import ficha as fch  # noqa: E402
import triagem  # noqa: E402
from test_triagem import gerar_eventos, sem_polo  # noqa: E402

REVISOR = "Revisora Teste"


def sugestoes_falsas(**campos):
    """Stub de julgamento.sugerir: devolve sempre as `campos` dadas (valor, regra, ressalvas)."""
    def sugerir(ficha, eventos):
        return {c: {"valor": v[0], "regra": v[1], "evidencia": {"documento": "Sentença", "trecho": "trecho fictício da decisão"},
                    "ressalvas": list(v[2:])} for c, v in campos.items()}
    return sugerir


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        eventos, fichas, cls.gabarito = gerar_eventos(600)
        cls.eventos0, cls.fichas0 = eventos, sem_polo(fichas)
        cls.projeto = ficticio.criar_projeto_de_teste(cls.fichas0, nome="Revisão em Escala")
        import acesso
        cls.cofre = {}
        cls.patches = [mock.patch.object(acesso, "obter", lambda chave: cls.cofre.get(chave)),
                       mock.patch.object(acesso, "guardar", lambda chave, valor: cls.cofre.__setitem__(chave, valor))]
        import revisao
        cfg = lambda: {"revisor": REVISOR}
        for nome, mod in list(sys.modules.items()):     # test_pipeline troca comum.config e não desfaz
            if mod is not None and (nome in ("comum", "revisao") or nome.startswith("painel.")) and hasattr(mod, "config"):
                cls.patches.append(mock.patch.object(mod, "config", cfg))
        for p in cls.patches:
            p.start()
        cls.TOKEN = revisao.TOKEN
        revisao.app.config["TESTING"] = True
        cls.c = revisao.app.test_client()
        cls.c.set_cookie("projeto", cls.projeto["slug"])

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        ficticio.restaurar_comum()

    def setUp(self):
        # cada teste parte de 600 rascunhos novos, das fichas originais e sem lotes
        self.eventos = copy.deepcopy(self.eventos0)
        comum.salvar_eventos(self.eventos)
        fch.salvar(copy.deepcopy(self.fichas0))
        (comum.DATA / "lotes.json").unlink(missing_ok=True)

    def get(self, caminho, **kw):
        r = self.c.get(caminho, **kw)
        return r, r.get_data(as_text=True)

    def post(self, caminho, dados=None, token=True):
        corpo = dict(dados or {})
        if token:
            corpo["token"] = self.TOKEN
        return self.c.post(caminho, data=corpo)

    def eventos_em_disco(self):
        return {e["id"]: e for e in comum.eventos()}

    def niveis(self):
        return {i["ev"]["id"]: i["nivel"] for i in triagem.classificar_lista(comum.eventos(), fch.carregar(todas=True), status=None)}


class Triagem(Base):
    def test_contadores_lista_ordenada_e_paginada(self):
        r, h = self.get("/triagem")
        self.assertEqual(r.status_code, 200)
        c = triagem.contar(triagem.classificar_lista(comum.eventos(), fch.carregar(todas=True)))
        for n, rotulo in (("vermelho", "vermelhas"), ("amarelo", "amarelas"), ("verde", "verdes")):
            self.assertIn(f"<b>{c[n]}</b>{rotulo}", h.replace(" (sempre revisar)", ""))
        self.assertIn("600 linha(s) para revisar", h)
        self.assertIn("página 1 de 6", h)
        self.assertEqual(h.count("<tr data-href="), 100)
        corpo = h.split("<table class='lista'", 1)[1]
        primeiro = re.search(r"<span class='nivel (\w+)'>", corpo).group(1)
        self.assertEqual(primeiro, "vermelho")                      # mais arriscado primeiro
        _, h2 = self.get("/triagem?pagina=6")
        self.assertEqual(h2.count("<tr data-href="), 100)
        _, h9 = self.get("/triagem?pagina=99")                      # passou do fim: última página
        self.assertIn("página 6 de 6", h9)
        _, hx = self.get("/triagem?pagina=abc")
        self.assertIn("página 1 de 6", hx)

    def test_filtros_na_tela(self):
        n_verde = triagem.contar(triagem.classificar_lista(comum.eventos(), fch.carregar(todas=True)))["verde"]
        _, h = self.get("/triagem?nivel=verde")
        self.assertIn(f"{n_verde} linha(s) para revisar", h)
        self.assertNotIn("<span class='nivel vermelho'>Vermelho</span></td>", h.split("<table class='lista'", 1)[1])
        cliente = fch.obter(self.fichas0[0], "cliente")
        _, h = self.get(f"/triagem?cliente={quote(cliente)}")
        self.assertRegex(h, r"(\d+) linha\(s\) para revisar")
        n = int(re.search(r"(\d+) linha\(s\) para revisar", h).group(1))
        esperado = sum(1 for e in comum.eventos() if e["cliente"] == cliente)
        self.assertEqual(n, esperado)
        _, h = self.get("/triagem?processo=0000000-00")
        self.assertIn("0 linha(s) para revisar", h)
        self.assertIn("Nada com esses filtros", h)
        _, h = self.get("/triagem?nivel=lixo&ordem=lixo")           # valores inválidos viram o padrão
        self.assertIn("600 linha(s) para revisar", h)
        for ordem in ("data", "processo", "risco"):
            r, h = self.get(f"/triagem?ordem={ordem}")
            self.assertEqual(r.status_code, 200)
        responsavel = fch.obter(self.fichas0[0], "responsavel")
        _, h = self.get(f"/triagem?responsavel={quote(responsavel)}")
        self.assertIn("linha(s) para revisar", h)
        _, h = self.get(f"/triagem?tribunal={self.fichas0[0]['tribunal']}")
        self.assertIn("linha(s) para revisar", h)

    def test_tela_mostra_resumo_do_lote_e_atalhos(self):
        _, h = self.get("/triagem")
        plano = triagem.preparar_lote(comum.eventos(), fch.carregar(todas=True))
        self.assertIn(f"Seriam aprovadas agora: <b>{len(plano['aprovar'])}</b>", h)
        self.assertIn("<b>10%</b>", h)
        self.assertIn("amostra", h)
        self.assertIn("Atalhos: J/K", h)
        self.assertIn(f"em nome de <b>{REVISOR}</b>", h)
        self.assertNotRegex(h, r"https?://(?!127\.0\.0\.1)")        # nada de endereço externo
        self.assertNotIn("<script src", h)

    def test_lote_sem_token_e_sem_confirmacao(self):
        self.assertEqual(self.post("/triagem/lote", {"confirmar": "1"}, token=False).status_code, 403)
        self.assertEqual(self.post("/triagem/lote").status_code, 400)
        self.assertEqual(self.post("/triagem/lote", {"confirmar": "0"}).status_code, 400)
        self.assertTrue(all(e["status"] == "rascunho" for e in comum.eventos()))

    def test_lote_aprova_so_verdes_fora_da_amostra_e_registra(self):
        antes = self.niveis()
        plano = triagem.preparar_lote(comum.eventos(), fch.carregar(todas=True))
        r = self.post("/triagem/lote", {"confirmar": "1"})
        self.assertEqual(r.status_code, 302)
        em_disco = self.eventos_em_disco()
        aprovados = {i for i, e in em_disco.items() if e["status"] == "aprovado"}
        self.assertEqual(aprovados, {i["ev"]["id"] for i in plano["aprovar"]})
        self.assertTrue(aprovados and all(antes[i] == "verde" for i in aprovados))       # nunca amarelo/vermelho
        amostra = {i for i, e in em_disco.items() if e.get("amostra_lote")}
        self.assertEqual(amostra, {i["ev"]["id"] for i in plano["amostra"]})
        self.assertTrue(all(em_disco[i]["status"] == "rascunho" for i in amostra))
        lotes = comum.load_json(comum.DATA / "lotes.json", [])
        self.assertEqual(len(lotes), 1)
        lote = lotes[0]
        self.assertEqual((lote["aprovado_por"], sorted(lote["aprovados"])), (REVISOR, sorted(aprovados)))
        for i in aprovados:
            self.assertEqual((em_disco[i]["aprovado_por"], em_disco[i]["lote"]), (REVISOR, lote["id"]))
            self.assertTrue(em_disco[i]["aprovado_em"])
        # nenhum amarelo/vermelho mudou
        self.assertTrue(all(e["status"] == "rascunho" for i, e in em_disco.items() if antes[i] != "verde"))
        # a mensagem aparece na tela seguinte
        _, h = self.get(r.headers["Location"])
        self.assertIn(f"Lote aprovado: {len(aprovados)} linha(s) verde(s), em nome de {REVISOR}", h)
        self.assertIn("amostra", h)
        # segundo lote: o que sobrou de verde é só a amostra, que exige olho humano
        r2 = self.post("/triagem/lote", {"confirmar": "1"})
        _, h2 = self.get(r2.headers["Location"])
        self.assertIn("Nenhuma linha verde para aprovar em lote", h2)
        self.assertEqual(len(comum.load_json(comum.DATA / "lotes.json", [])), 1)

    def test_lote_ignora_tentativa_de_forcar_nivel_ou_ids(self):
        r = self.post("/triagem/lote", {"confirmar": "1", "nivel": "vermelho", "ids": "t:0000,t:0001", "id": "t:0002", "todos": "1"})
        self.assertEqual(r.status_code, 302)
        antes = self.niveis()
        em_disco = self.eventos_em_disco()
        self.assertTrue(all(antes[i] == "verde" for i, e in em_disco.items() if e["status"] == "aprovado"))

    def test_lote_respeita_filtro_de_cliente(self):
        cliente = fch.obter(self.fichas0[0], "cliente")
        r = self.post("/triagem/lote", {"confirmar": "1", "cliente": cliente})
        em_disco = self.eventos_em_disco()
        aprovados = [e for e in em_disco.values() if e["status"] == "aprovado"]
        self.assertTrue(aprovados and all(e["cliente"] == cliente for e in aprovados))
        self.assertIn("cliente=", r.headers["Location"])             # volta para a tela com o mesmo filtro

    def test_amostragem_configuravel_pelo_config(self):
        def cfg():
            return {"revisor": REVISOR, "triagem": {"amostragem_pct": 50, "semente": "outra"}}
        with mock.patch.object(comum, "config", cfg):
            plano = triagem.preparar_lote(comum.eventos(), fch.carregar(todas=True))
        self.assertEqual(len(plano["amostra"]), -(-len(plano["elegiveis"]) // 2))

    def test_lote_com_poucos_verdes_pode_nao_aprovar_nada(self):
        verdes = [e for e in self.eventos if self.gabarito[e["id"]][1] == "verde"]
        comum.salvar_eventos(verdes[:1])                              # um verde só: a amostra mínima (1) é ele mesmo
        r = self.post("/triagem/lote", {"confirmar": "1"})
        _, h = self.get(r.headers["Location"])
        self.assertIn("Nenhuma linha verde para aprovar em lote", h)
        self.assertEqual(comum.eventos()[0]["status"], "rascunho")
        self.assertFalse(comum.eventos()[0].get("amostra_lote"))      # sem aprovar nada, nada é marcado

    def test_sem_eventos(self):
        comum.salvar_eventos([])
        r, h = self.get("/triagem")
        self.assertEqual(r.status_code, 200)
        self.assertIn("0 linha(s) para revisar", h)
        self.assertIn("disabled", h)                                  # botão do lote desligado

    def test_sugestao_da_triagem_na_pagina_de_revisao_so_com_muitos_rascunhos(self):
        _, h = self.get("/")
        self.assertIn("<a href='/triagem'>triagem</a>", h)            # 600 rascunhos: sugere
        comum.salvar_eventos(self.eventos[:5])
        _, h = self.get("/")
        self.assertNotIn("/triagem", h)                               # poucos: a página fica como era


class VisaoPorProcesso(Base):
    def setUp(self):
        super().setUp()
        self.ficha = self.fichas0[0]
        self.numero = self.ficha["numero"]
        self.proprios = [e for e in self.eventos if e["numero"] == self.numero]
        self.assertGreaterEqual(len(self.proprios), 8)

    def test_linha_do_tempo_com_print_e_trecho_lado_a_lado(self):
        alvo = next(e for e in self.proprios if e.get("trecho_origem"))
        impr = comum.PRINTS_DIR
        impr.mkdir(parents=True, exist_ok=True)
        (impr / "p.png").write_bytes(b"\x89PNG-fake")
        alvo["print"] = str(impr / "p.png")
        docs = comum.DOCS_DIR / "t"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "d.html").write_text("<p>documento fictício</p>", encoding="utf-8")
        alvo["arquivo"] = str(docs / "d.html")
        comum.salvar_eventos(self.eventos)
        r, h = self.get(f"/processo?numero={self.numero}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(h.count("class='cartao-ev"), len(self.proprios))
        self.assertIn(f"<h1>Processo {self.numero}</h1>", h)
        self.assertIn(f"/print?id={quote(alvo['id'])}", h)
        self.assertIn(f"/documento?id={quote(alvo['id'])}", h)
        self.assertIn("Trecho do documento", h)
        self.assertIn("class='lado'", h)
        self.assertIn("Sem print.", h)
        for ev in self.proprios:                                       # texto e nível de cada evento
            self.assertIn(ev["id"], h)
            n = triagem.classificar(ev, self.ficha)["nivel"]
            self.assertIn(f"<span class='nivel {n}'>", h)
        # a imagem e o documento abrem pelas rotas existentes
        for rota in ("print", "documento"):
            with self.c.get(f"/{rota}?id={alvo['id']}") as resp:
                self.assertEqual(resp.status_code, 200)

    def test_atalhos_e_botoes(self):
        _, h = self.get(f"/processo?numero={self.numero}")
        for trecho in ("name='acao' value='aprovar'", "name='acao' value='descartar'", "name='acao' value='salvar'",
                       "name='token'", "action='/processo/evento'", "Atalhos: J/K", "k==='j'", "k==='a'", "k==='d'", "k==='e'",
                       "confirm("):
            self.assertIn(trecho, h)
        self.assertNotIn("<script src", h)

    def test_numero_de_vinculado_abre_o_processo_principal(self):
        com_vinculo = next(f for f in self.fichas0 if f["vinculados"])
        vinc = com_vinculo["vinculados"][0]["numero"]
        _, h = self.get(f"/processo?numero={vinc}")
        self.assertIn(f"<h1>Processo {com_vinculo['numero']}</h1>", h)
        self.assertIn("Vinculados:", h)

    def test_processo_desconhecido(self):
        self.assertEqual(self.get("/processo?numero=0000000-00.0000.0.00.0000")[0].status_code, 404)
        self.assertEqual(self.get("/processo")[0].status_code, 404)

    def test_aprovar_corrigir_descartar_por_linha(self):
        verdes = [e for e in self.proprios if self.gabarito[e["id"]][1] == "verde"]
        outro = [e for e in self.proprios if e not in verdes]
        a, b, c = verdes[0], outro[0], outro[1]
        r = self.post("/processo/evento", {"id": a["id"], "numero": self.numero, "acao": "aprovar", "frase": a["frase"],
                                           "conteudo": a.get("conteudo", ""), "prazo": "", "audiencia": ""})
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"/processo?numero={self.numero}", r.headers["Location"])
        self.assertRegex(r.headers["Location"], r"#ev-[0-9a-f]{8}$")      # já no próximo rascunho
        em_disco = self.eventos_em_disco()
        self.assertEqual((em_disco[a["id"]]["status"], em_disco[a["id"]]["aprovado_por"]), ("aprovado", REVISOR))
        self.assertNotIn("lote", em_disco[a["id"]])                       # aprovação individual não é lote
        r = self.post("/processo/evento", {"id": b["id"], "numero": self.numero, "acao": "salvar", "frase": "Frase corrigida.",
                                           "conteudo": "", "prazo": "", "audiencia": ""})
        self.assertEqual(self.eventos_em_disco()[b["id"]]["status"], "rascunho")
        self.assertEqual(self.eventos_em_disco()[b["id"]]["frase"], "Frase corrigida.")
        r = self.post("/processo/evento", {"id": c["id"], "numero": self.numero, "acao": "descartar"})
        self.assertEqual(self.eventos_em_disco()[c["id"]]["status"], "descartado")
        _, h = self.get(r.headers["Location"])
        self.assertIn("Linha descartada.", h)
        # linha já aprovada: não aceita nova ação; sem frase não aprova; sem token, 403
        self.assertEqual(self.post("/processo/evento", {"id": a["id"], "numero": self.numero, "acao": "descartar"}).status_code, 404)
        self.assertEqual(self.post("/processo/evento", {"id": verdes[1]["id"], "numero": self.numero, "acao": "aprovar", "frase": " "}).status_code, 400)
        self.assertEqual(self.post("/processo/evento", {"id": verdes[1]["id"], "acao": "aprovar", "frase": "x"}, token=False).status_code, 403)

    def test_mesma_acao_do_evento_antigo(self):
        """/evento (revisão antiga) e /processo/evento gravam do mesmo jeito."""
        x, y = [e for e in self.eventos if self.gabarito[e["id"]][1] == "verde"][:2]
        dados = {"acao": "aprovar", "frase": "Foi feito algo.", "conteudo": "", "prazo": "", "audiencia": ""}
        self.post("/evento", {**dados, "id": x["id"]})
        self.post("/processo/evento", {**dados, "id": y["id"], "numero": y["numero"]})
        em_disco = self.eventos_em_disco()
        pega = lambda e: {k: e.get(k) for k in ("status", "frase", "conteudo", "prazo", "audiencia", "aprovado_por")}
        self.assertEqual(pega(em_disco[x["id"]]), pega(em_disco[y["id"]]))

    def test_aprovado_em_lote_aparece_na_linha_do_tempo(self):
        self.post("/triagem/lote", {"confirmar": "1"})
        em_disco = self.eventos_em_disco()
        achou = next(e for e in em_disco.values() if e.get("lote"))
        _, h = self.get(f"/processo?numero={achou['numero']}")
        self.assertIn("em lote", h)
        self.assertIn(f"aprovado por {REVISOR}", h)


class CamposDerivados(Base):
    def setUp(self):
        super().setUp()
        self.fichas = copy.deepcopy(self.fichas0)
        self.f = self.fichas[0]
        self.numero = self.f["numero"]
        for campo in ("situacao", "momento_atual", "fase", "resultado", "probabilidade", "valor_arbitrado", "valor_acordo",
                      "valor_estimado", "valor_economizado"):
            fch.limpar(self.f, campo)               # parte sem nenhum campo derivado
        fch.salvar(self.fichas)

    def _com(self, sugerir, fn=None):
        if fn:
            fn(self.f)
            fch.salvar(self.fichas)
        return mock.patch.object(sys.modules["painel.processo"], "_sugerir_padrao", lambda: sugerir)

    def _ficha(self):
        return next(f for f in fch.carregar(todas=True) if f["numero"] == self.numero)

    def test_bloco_antes_depois_com_regra_evidencia_e_ressalva(self):
        stub = sugestoes_falsas(resultado=("Improcedente", "R-mérito", "Sujeita a recurso."),
                                valor_estimado=("1500.00", "R-valor"))
        with self._com(stub, lambda f: fch.definir(f, "valor_estimado", "1000.00", "migrado")):
            _, h = self.get(f"/processo?numero={self.numero}")
        self.assertIn("Campos derivados: antes → depois", h)
        self.assertIn("Resultado", h)
        self.assertIn("Improcedente", h)
        self.assertIn("(vazio)", h)                                   # antes do resultado
        self.assertIn("R$ 1.000,00", h)                               # antes do valor estimado
        self.assertIn("R$ 1.500,00", h)                               # depois
        self.assertIn("R-mérito", h)
        self.assertIn("Sujeita a recurso.", h)
        self.assertIn("trecho fictício da decisão", h)
        self.assertIn("name='acao' value='corrigir'", h)

    def test_aprovar_grava_como_humano(self):
        stub = sugestoes_falsas(resultado=("Improcedente", "R-mérito"))
        with self._com(stub):
            r = self.post("/processo/campo", {"numero": self.numero, "campo": "resultado", "acao": "aprovar"})
            self.assertEqual(r.status_code, 302)
            f = self._ficha()
            self.assertEqual((fch.obter(f, "resultado"), fch.origem(f, "resultado")), ("Improcedente", "humano"))
            _, h = self.get(r.headers["Location"])
            self.assertIn("Resultado: (vazio) → Improcedente (aprovado por você).", h)
            _, h = self.get(f"/processo?numero={self.numero}")
            self.assertNotIn("Campos derivados", h)                   # decidido: some do bloco

    def test_corrigir_grava_o_que_a_pessoa_digitou_como_humano(self):
        stub = sugestoes_falsas(valor_estimado=("1500.00", "R-valor"))
        with self._com(stub):
            self.post("/processo/campo", {"numero": self.numero, "campo": "valor_estimado", "acao": "corrigir", "valor": "R$ 2.500,50"})
        f = self._ficha()
        self.assertEqual((fch.obter(f, "valor_estimado"), fch.origem(f, "valor_estimado")), ("2500.50", "humano"))

    def test_corrigir_com_valor_ruim_nao_grava(self):
        stub = sugestoes_falsas(resultado=("Improcedente", "R"), valor_estimado=("1500.00", "R"))
        with self._com(stub):
            r = self.post("/processo/campo", {"numero": self.numero, "campo": "resultado", "acao": "corrigir", "valor": "Vencemos feio"})
            _, h = self.get(r.headers["Location"])
            self.assertIn("valor não aceito", h)
            r = self.post("/processo/campo", {"numero": self.numero, "campo": "valor_estimado", "acao": "corrigir", "valor": " "})
            _, h = self.get(r.headers["Location"])
            self.assertIn("informe o valor corrigido", h)
        f = self._ficha()
        self.assertIsNone(fch.obter(f, "resultado"))
        self.assertIsNone(fch.obter(f, "valor_estimado"))

    def test_recusar_nao_pergunta_de_novo(self):
        stub = sugestoes_falsas(probabilidade=("Provável", "R-prob"))
        with self._com(stub):
            self.post("/processo/campo", {"numero": self.numero, "campo": "probabilidade", "acao": "recusar"})
            _, h = self.get(f"/processo?numero={self.numero}")
            self.assertNotIn("Campos derivados", h)
        f = self._ficha()
        self.assertIsNone(fch.obter(f, "probabilidade"))
        self.assertEqual(f["sugestoes_recusadas"], {"probabilidade": "Provável"})
        # sugestão DIFERENTE da recusada volta a aparecer
        with self._com(sugestoes_falsas(probabilidade=("Remota", "R-prob"))):
            _, h = self.get(f"/processo?numero={self.numero}")
            self.assertIn("Remota", h)

    def test_campo_humano_nunca_e_proposta_nem_e_sobrescrito(self):
        stub = sugestoes_falsas(resultado=("Improcedente", "R"), valor_economizado=("100.00", "R"))
        with self._com(stub, lambda f: fch.definir(f, "resultado", "Procedente", "humano")):
            _, h = self.get(f"/processo?numero={self.numero}")
            self.assertNotIn("Improcedente", h)
            self.assertIn("Valor economizado", h)
            # mesmo forçando o POST, o campo humano não muda
            r = self.post("/processo/campo", {"numero": self.numero, "campo": "resultado", "acao": "aprovar"})
            _, h2 = self.get(r.headers["Location"])
            self.assertIn("Essa proposta não existe mais", h2)
        self.assertEqual(fch.obter(self._ficha(), "resultado"), "Procedente")

    def test_proposta_pendente_na_ficha_aprovar_e_recusar(self):
        def pendentes(f):
            fch.definir(f, "momento_atual", "AGUARDANDO SENTENÇA", "derivado", evidencia="regra: conclusos para sentença")
            fch.definir(f, "situacao", "Encerrado", "sugerido")
        with self._com(None, pendentes):
            _, h = self.get(f"/processo?numero={self.numero}")
            self.assertIn("Momento atual do processo", h)
            self.assertIn("AGUARDANDO SENTENÇA", h)
            self.assertIn("regra: conclusos para sentença", h)
            self.post("/processo/campo", {"numero": self.numero, "campo": "momento_atual", "acao": "aprovar"})
            self.post("/processo/campo", {"numero": self.numero, "campo": "situacao", "acao": "recusar"})
        f = self._ficha()
        self.assertEqual((fch.obter(f, "momento_atual"), fch.origem(f, "momento_atual")), ("AGUARDANDO SENTENÇA", "humano"))
        self.assertIsNone(fch.obter(f, "situacao"))                   # recusada: a proposta sai da ficha

    def test_sugestao_com_defeito_vira_aviso_e_nao_derruba_a_tela(self):
        def quebrado(ficha, eventos):
            raise RuntimeError("falha de teste")
        with self._com(quebrado):
            r, h = self.get(f"/processo?numero={self.numero}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Não foi possível calcular as sugestões de julgamento (RuntimeError).", h)

    def test_sem_modulo_de_julgamento_a_tela_funciona(self):
        with self._com(None):
            r, h = self.get(f"/processo?numero={self.numero}")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Campos derivados", h)

    def test_resolucao_do_modulo_de_julgamento(self):
        from painel import processo
        falso = types.ModuleType("julgamento")
        falso.sugerir = lambda ficha, eventos: {}
        with mock.patch.dict(sys.modules, {"julgamento": falso}):
            self.assertIs(processo._sugerir_padrao(), falso.sugerir)
        with mock.patch.dict(sys.modules, {"julgamento": None}):      # None em sys.modules = ImportError
            self.assertIsNone(processo._sugerir_padrao())

    def test_so_eventos_aprovados_alimentam_a_sugestao(self):
        vistos = {}

        def espiao(ficha, eventos):
            vistos["status"] = {e["status"] for e in eventos}
            return {}
        proprios = [e for e in self.eventos if e["numero"] == self.numero]
        proprios[0]["status"], proprios[1]["status"] = "aprovado", "relatado"
        comum.salvar_eventos(self.eventos)
        with self._com(espiao):
            self.get(f"/processo?numero={self.numero}")
        self.assertEqual(vistos["status"], {"aprovado", "relatado"})

    def test_campo_sem_token_e_inexistente(self):
        self.assertEqual(self.post("/processo/campo", {"numero": self.numero, "campo": "resultado", "acao": "aprovar"}, token=False).status_code, 403)
        self.assertEqual(self.post("/processo/campo", {"numero": self.numero, "campo": "xyz", "acao": "aprovar"}).status_code, 404)
        self.assertEqual(self.post("/processo/campo", {"numero": "nao-existe", "campo": "resultado", "acao": "aprovar"}).status_code, 404)

    def test_propostas_de_campos_direto(self):
        from painel import processo
        f = copy.deepcopy(self.f)
        fch.definir(f, "valor_estimado", "900.00", "migrado")
        fch.definir(f, "probabilidade", "Possível", "humano")
        stub = sugestoes_falsas(valor_estimado=("900.00", "igual"), probabilidade=("Remota", "x"), resultado=("Acordo", "y"),
                                campo_que_nao_existe=("1", "z"))
        propostas, avisos = processo.propostas_de_campos(f, [], sugerir=stub)
        self.assertEqual([p["campo"] for p in propostas], ["resultado"])   # igual ao atual: nada muda; humano: nunca; desconhecido: ignora
        self.assertEqual(avisos, [])


if __name__ == "__main__":
    unittest.main()
