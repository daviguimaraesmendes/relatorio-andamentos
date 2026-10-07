"""Testes da triagem (src/triagem.py): nível de risco por regras, filtros, amostragem reprodutível e
aprovação em lote só de verdes. Tudo com eventos FICTÍCIOS gerados aqui (600 por padrão), sem rede e
sem tocar em projetos/ real.

    python3 -m unittest tests/test_triagem.py -v

`gerar_eventos` também serve ao teste do painel (tests/test_painel_revisao.py): cada evento nasce de
um "tipo" com nível e código esperados, de modo que o gabarito vem da CONSTRUÇÃO e não de rodar as
mesmas regras duas vezes.
"""
import copy
import datetime
import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import ficticio  # noqa: E402
import comum  # noqa: E402
import ficha as fch  # noqa: E402
import triagem  # noqa: E402

TEXTO_DO_DOCUMENTO = ("A parte ré apresentou contestação e juntou documentos aos autos. O pedido de juntada foi recebido "
                      "pelo cartório e os autos seguem conclusos para análise da secretaria.")
TRECHO_BOM = "apresentou contestação e juntou documentos aos autos"
TRECHO_RUIM = "o juiz determinou o pagamento imediato de tudo à parte contrária"


# ---- os tipos de evento: (nome, nível esperado, código que tem de aparecer, ajustes no evento)

def _mov(frase, titulo=None):
    return {"tipo_evento": "movimento", "titulo": titulo or frase + " (original)", "frase": frase, "conteudo": ""}


def _doc(**extra):
    base = {"tipo_evento": "documento", "titulo": "1 - Petição", "tipo": "Petição", "frase": "A parte contrária apresentou petição",
            "conteudo": "juntando documentos", "trecho_origem": TRECHO_BOM, "efeito": "neutro", "autoria": "contraria",
            "polo_cliente": "passivo", "arquivo_texto": True, "alertas": []}
    base.update(extra)
    return base


TIPOS = [
    # verdes
    ("verde_movimento_peticao", "verde", None, lambda: _mov("Foi apresentada petição (Contestação).")),
    ("verde_movimento_despacho", "verde", None, lambda: _mov("O processo foi encaminhado ao juiz para despacho.")),
    ("verde_documento_conferido", "verde", None, lambda: _doc()),
    ("verde_documento_do_nosso_lado", "verde", None, lambda: _doc(autoria="nos", polo_cliente="ativo", frase="Nós apresentamos petição")),
    # amarelos
    ("amarelo_alerta_de_regra", "amarelo", "alerta", lambda: _doc(alertas=["A IA citou dispositivo legal: conferir."])),
    ("amarelo_sem_traducao", "amarelo", "alerta", lambda: {**_mov("Movimento esquisito do tribunal"),
                                                           "alertas": ["Movimentação sem tradução cadastrada: reescrever."]}),
    ("amarelo_sem_traducao_so_pelo_texto", "amarelo", "sem_traducao", lambda: {**_mov("Movimento esquisito 2"), "titulo": "Movimento esquisito 2"}),
    ("amarelo_autoria", "amarelo", "autoria_nao_identificada", lambda: _doc(autoria="outro")),
    ("amarelo_efeito_incerto", "amarelo", "efeito_incerto", lambda: _doc(efeito="incerto")),
    ("amarelo_sem_trecho", "amarelo", "sem_trecho", lambda: _doc(trecho_origem="", arquivo_texto=False)),
    ("amarelo_sem_polo", "amarelo", "polo_nao_informado", lambda: _doc(polo_cliente=None, ficha_sem_polo=True)),
    # vermelhos
    ("vermelho_desfavoravel", "vermelho", "desfavoravel", lambda: _doc(efeito="desfavoravel", conteudo="negando o pedido da nossa parte")),
    ("vermelho_prazo_no_campo", "vermelho", "prazo", lambda: _doc(prazo="15 dias para o autor se manifestar")),
    ("vermelho_prazo_no_texto", "vermelho", "prazo", lambda: _mov("Terminou o prazo de manifestação do réu.")),
    ("vermelho_audiencia_no_campo", "vermelho", "audiencia", lambda: _doc(audiencia="12/11/2026, às 9h")),
    ("vermelho_audiencia_no_texto", "vermelho", "audiencia", lambda: _mov("Foi marcada audiência de instrução para a data fixada.")),
    ("vermelho_valor_rs", "vermelho", "valor", lambda: _doc(conteudo="pedindo o pagamento de R$ 1.500,00")),
    ("vermelho_valor_por_extenso", "vermelho", "valor", lambda: _doc(conteudo="fixando multa de 10 mil reais")),
    ("vermelho_valor_no_trecho", "vermelho", "valor", lambda: _doc(trecho_origem="juntou comprovante de 350,00 aos autos", texto_extra="juntou comprovante de 350,00 aos autos")),
    ("vermelho_resultado_procedente", "vermelho", "mudanca_resultado", lambda: _doc(conteudo="julgando procedente o pedido")),
    ("vermelho_resultado_movimento", "vermelho", "mudanca_resultado", lambda: _mov("O pedido foi julgado improcedente.")),
    ("vermelho_transito", "vermelho", "mudanca_resultado", lambda: _mov("A decisão se tornou definitiva (trânsito em julgado).")),
    ("vermelho_sentenca", "vermelho", "decisao_de_merito", lambda: _doc(tipo="Sentença", titulo="2 - Sentença", conteudo="encaminhando as partes")),
    ("vermelho_acordao_publicado", "vermelho", "decisao_de_merito", lambda: _mov("Foi publicada a Acórdão no Diário de Justiça.")),
    ("vermelho_trecho_nao_confere_pelo_alerta", "vermelho", "trecho_nao_confere", lambda: _doc(
        alertas=["O trecho citado pela IA não foi encontrado no documento: conferir o resumo."], arquivo_texto=False)),
    ("vermelho_trecho_nao_confere_pelo_disco", "vermelho", "trecho_nao_confere", lambda: _doc(trecho_origem=TRECHO_RUIM)),
]
ESPERADO = {nome: (nivel, codigo) for nome, nivel, codigo, _ in TIPOS}


def gerar_eventos(n=600, fichas=None, pasta=None, semente=7):
    """(eventos, fichas, gabarito): `n` eventos fictícios em rascunho, ciclando pelos TIPOS (embaralhados de
    modo reprodutível). `gabarito` = {id: (nome do tipo, nível esperado, código esperado)}."""
    fichas = fichas if fichas is not None else ficticio.gerar_carteira(60, clientes=3, semente=1)
    pasta = Path(pasta or (TMP / "triagem-docs"))
    pasta.mkdir(parents=True, exist_ok=True)
    rng = random.Random(semente)
    ordem = list(range(len(TIPOS)))
    eventos, gabarito = [], {}
    for i in range(n):
        if i % len(TIPOS) == 0:
            rng.shuffle(ordem)
        nome, nivel, codigo, construir = TIPOS[ordem[i % len(TIPOS)]]
        f = fichas[i % len(fichas)]
        ev = construir()
        extra = ev.pop("texto_extra", "")
        com_arquivo = ev.pop("arquivo_texto", False)
        ev.pop("ficha_sem_polo", None)
        dia = datetime.date(2026, 9, 1) + datetime.timedelta(days=i % 30)
        ev.update(id=f"t:{i:04d}", numero=f["numero"], cliente=fch.obter(f, "cliente"), status="rascunho",
                  data=dia.strftime("%d/%m/%Y"), detectado_em=f"{dia.isoformat()}T19:00:00")
        if "polo_cliente" not in ev:
            ev["polo_cliente"] = fch.obter(f, "polo_cliente")
        if com_arquivo:
            caminho = pasta / f"doc{i:04d}.txt"
            caminho.write_text(TEXTO_DO_DOCUMENTO + " " + extra, encoding="utf-8")
            ev["texto_arquivo"] = str(caminho)
        eventos.append(ev)
        gabarito[ev["id"]] = (nome, nivel, codigo)
    return eventos, fichas, gabarito


def sem_polo(fichas):
    """Cópia das fichas sem polo do cliente (para o tipo 'amarelo_sem_polo')."""
    saida = copy.deepcopy(fichas)
    for f in saida:
        f["campos"].pop("polo_cliente", None)
        f.pop("polo_cliente", None)
    return saida


class Classificacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eventos, cls.fichas, cls.gabarito = gerar_eventos(600)
        # o tipo "sem polo" precisa de ficha sem polo: usa as fichas sem polo para classificar todos
        cls.fichas_sem_polo = sem_polo(cls.fichas)
        cls.indice = triagem.indice_de_fichas(cls.fichas_sem_polo)

    def test_600_eventos_separados_por_nivel_conforme_as_regras(self):
        contagem = Counter()
        for ev in self.eventos:
            nome, nivel, codigo = self.gabarito[ev["id"]]
            r = triagem.classificar_detalhado(ev, self.indice[ev["numero"]])
            with self.subTest(tipo=nome, id=ev["id"]):
                self.assertEqual(r["nivel"], nivel, r)
                if codigo:
                    self.assertIn(codigo, r["codigos"], r)
                if nivel == "verde":
                    self.assertEqual(r["motivos"], [])
                else:
                    self.assertTrue(r["motivos"])
            contagem[r["nivel"]] += 1
        esperado = Counter(self.gabarito[e["id"]][1] for e in self.eventos)
        self.assertEqual(contagem, esperado)
        self.assertEqual(sum(contagem.values()), 600)
        self.assertTrue(all(contagem[n] > 0 for n in triagem.NIVEIS))

    def test_classificar_devolve_so_nivel_e_motivos(self):
        r = triagem.classificar(self.eventos[0], self.indice[self.eventos[0]["numero"]])
        self.assertEqual(sorted(r), ["motivos", "nivel"])
        self.assertIn(r["nivel"], triagem.NIVEIS)

    def test_vermelho_vem_antes_do_amarelo_nos_motivos(self):
        ev = _doc(id="x", numero="n", cliente="C", status="rascunho", prazo="5 dias", autoria="outro", alertas=["Um alerta qualquer."])
        r = triagem.classificar_detalhado(ev, None)
        self.assertEqual(r["nivel"], "vermelho")
        self.assertEqual(r["codigos"][0], "prazo")
        self.assertIn("alerta", r["codigos"])
        self.assertIn("Um alerta qualquer.", r["motivos"])

    def test_resultado_diferente_do_da_ficha_e_vermelho(self):
        f = fch.nova_ficha(ficticio.numero_ficticio(900))
        fch.definir(f, "resultado", "Procedente", "humano")
        fch.definir(f, "cliente", "Cliente Exemplo 01 Ltda", "humano")
        fch.definir(f, "polo_cliente", "passivo", "humano")
        ev = {**_mov("Andamento sem texto de julgamento."), "id": "r", "numero": f["numero"], "cliente": "x", "status": "rascunho"}
        self.assertEqual(triagem.classificar(ev, f)["nivel"], "verde")
        self.assertEqual(triagem.classificar({**ev, "resultado": "Procedente"}, f)["nivel"], "verde")   # igual: nada muda
        r = triagem.classificar({**ev, "resultado": "Improcedente"}, f)
        self.assertEqual(r["nivel"], "vermelho")

    def test_sem_ficha_so_e_amarelo_na_lista(self):
        ev = {**_mov("O processo foi distribuído."), "id": "z", "numero": ficticio.numero_ficticio(901), "cliente": "C", "status": "rascunho"}
        self.assertEqual(triagem.classificar(ev)["nivel"], "verde")                # sem ficha, a função avulsa não opina
        item = triagem.classificar_lista([ev], [])[0]
        self.assertEqual((item["nivel"], item["codigos"]), ("amarelo", ["fora_da_carteira"]))

    def test_movimento_sem_polo_nao_vira_amarelo(self):
        ev = {**_mov("O processo foi distribuído."), "id": "m", "numero": "n", "cliente": "C", "status": "rascunho"}
        self.assertEqual(triagem.classificar(ev)["nivel"], "verde")

    def test_frase_vazia_e_amarelo(self):
        ev = {**_mov(""), "id": "v", "numero": "n", "cliente": "C", "status": "rascunho", "titulo": "x"}
        self.assertEqual(triagem.classificar_detalhado(ev)["codigos"], ["sem_frase"])

    def test_datas_e_numeros_de_processo_nao_sao_valor(self):
        ev = {**_mov("O processo foi distribuído em 12/11/2026 sob o número 1234567-06.2026.8.06.0001."), "id": "d",
              "numero": "n", "cliente": "C", "status": "rascunho"}
        self.assertEqual(triagem.classificar(ev)["nivel"], "verde")

    def test_sempre_humano_lista_so_os_motivos_de_olho_humano(self):
        ev = _doc(id="x", numero="n", cliente="C", status="rascunho", prazo="5 dias", alertas=["Um alerta."], arquivo_texto=False)
        ev.pop("arquivo_texto", None)
        motivos = triagem.exige_humano(ev, None)
        self.assertEqual(motivos, ["Há prazo."])
        self.assertEqual(triagem.exige_humano(_doc(id="y", numero="n", cliente="C", status="rascunho", alertas=["Só alerta."]), None), [])


class ListaEFiltros(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eventos, cls.fichas, cls.gabarito = gerar_eventos(600)
        cls.itens = triagem.classificar_lista(cls.eventos, sem_polo(cls.fichas))

    def test_so_rascunho_entra_na_lista(self):
        eventos = copy.deepcopy(self.eventos[:10])
        eventos[0]["status"], eventos[1]["status"] = "aprovado", "descartado"
        self.assertEqual(len(triagem.classificar_lista(eventos, self.fichas)), 8)
        self.assertEqual(len(triagem.classificar_lista(eventos, self.fichas, status=None)), 10)

    def test_ordenacao_por_risco(self):
        ordenados = triagem.ordenar_por_risco(self.itens)
        niveis = [triagem.RISCO[i["nivel"]] for i in ordenados]
        self.assertEqual(niveis, sorted(niveis))
        self.assertEqual(len(ordenados), 600)
        # dentro do nível, o mais recente primeiro
        for nivel in triagem.NIVEIS:
            datas = [datetime.datetime.strptime(i["ev"]["data"], "%d/%m/%Y") for i in ordenados if i["nivel"] == nivel]
            self.assertEqual(datas, sorted(datas, reverse=True))

    def test_filtros(self):
        cliente = triagem.cliente_de(self.itens[0])
        so_cliente = triagem.filtrar(self.itens, cliente=cliente)
        self.assertTrue(so_cliente and all(triagem.cliente_de(i) == cliente for i in so_cliente))
        self.assertLess(len(so_cliente), 600)
        resp = triagem.responsavel_de(self.itens[0])
        self.assertTrue(all(triagem.responsavel_de(i) == resp for i in triagem.filtrar(self.itens, responsavel=resp)))
        trib = triagem.tribunal_de(self.itens[0])
        self.assertTrue(all(triagem.tribunal_de(i) == trib for i in triagem.filtrar(self.itens, tribunal=trib)))
        so_verde = triagem.filtrar(self.itens, nivel="verde")
        self.assertTrue(so_verde and all(i["nivel"] == "verde" for i in so_verde))
        numero = self.itens[0]["ev"]["numero"]
        achados = triagem.filtrar(self.itens, processo=numero[:9])      # trecho do número, sem pontuação
        self.assertTrue(achados and all(numero[:7] in i["ev"]["numero"] for i in achados))
        self.assertEqual(triagem.filtrar(self.itens, processo="0000000-00"), [])
        self.assertEqual(len(triagem.filtrar(self.itens)), 600)

    def test_contagem(self):
        c = triagem.contar(self.itens)
        self.assertEqual(c["total"], 600)
        self.assertEqual(c["verde"] + c["amarelo"] + c["vermelho"], 600)


class Lote(unittest.TestCase):
    def setUp(self):
        self.eventos, self.fichas, self.gabarito = gerar_eventos(600)
        self.fichas = sem_polo(self.fichas)

    def _verdes(self):
        return {i["ev"]["id"] for i in triagem.classificar_lista(self.eventos, self.fichas) if i["nivel"] == "verde"}

    def test_lote_nunca_inclui_amarelo_nem_vermelho(self):
        plano = triagem.preparar_lote(self.eventos, self.fichas, pct=10, semente="s")
        niveis = {self.gabarito[i["ev"]["id"]][1] for i in plano["aprovar"] + plano["amostra"]}
        self.assertEqual(niveis, {"verde"})
        verdes = self._verdes()
        self.assertEqual({i["ev"]["id"] for i in plano["elegiveis"]}, verdes)
        ids = [i["ev"]["id"] for i in plano["aprovar"]]
        self.assertTrue(set(ids) <= verdes and not set(ids) & {i["ev"]["id"] for i in plano["amostra"]})
        c = triagem.contar(triagem.classificar_lista(self.eventos, self.fichas))
        self.assertEqual(plano["barrados"]["amarelo"], c["amarelo"])
        self.assertEqual(plano["barrados"]["vermelho"], c["vermelho"])

    def test_amostra_e_dez_por_cento_arredondando_para_cima(self):
        plano = triagem.preparar_lote(self.eventos, self.fichas, semente="s")           # padrão: 10%
        n = len(plano["elegiveis"])
        self.assertEqual(len(plano["amostra"]), -(-n // 10))
        self.assertEqual(len(plano["amostra"]) + len(plano["aprovar"]), n)
        self.assertGreater(len(plano["aprovar"]), 0)

    def test_amostragem_reprodutivel_e_independe_da_ordem(self):
        a = triagem.preparar_lote(self.eventos, self.fichas, semente="s")
        b = triagem.preparar_lote(self.eventos, self.fichas, semente="s")
        embaralhado = list(self.eventos)
        random.Random(3).shuffle(embaralhado)
        c = triagem.preparar_lote(embaralhado, self.fichas, semente="s")
        ids = lambda p: sorted(i["ev"]["id"] for i in p["amostra"])
        self.assertEqual(ids(a), ids(b))
        self.assertEqual(ids(a), ids(c))
        outra = triagem.preparar_lote(self.eventos, self.fichas, semente="outra")
        self.assertNotEqual(ids(a), ids(outra))
        self.assertEqual(len(ids(a)), len(ids(outra)))

    def test_amostra_obrigatoria_casos_de_borda(self):
        ids = [f"e{i}" for i in range(50)]
        self.assertEqual(triagem.amostra_obrigatoria(ids, pct=0, semente="s"), set())
        self.assertEqual(triagem.amostra_obrigatoria([], pct=10, semente="s"), set())
        self.assertEqual(len(triagem.amostra_obrigatoria(ids, pct=100, semente="s")), 50)
        self.assertEqual(len(triagem.amostra_obrigatoria(ids, pct=250, semente="s")), 50)       # limitado a 100%
        self.assertEqual(len(triagem.amostra_obrigatoria(["so um"], pct=10, semente="s")), 1)   # mínimo 1
        self.assertEqual(len(triagem.amostra_obrigatoria(ids, pct=10, semente="s")), 5)
        self.assertEqual(triagem.amostra_obrigatoria(ids, 10, "s"), triagem.amostra_obrigatoria(list(reversed(ids)), 10, "s"))

    def test_aplicar_lote_registra_quem_e_quando(self):
        agora = datetime.datetime(2026, 10, 7, 10, 30, 5)
        verdes_antes = self._verdes()
        registro = triagem.aplicar_lote(self.eventos, self.fichas, "  Revisora Teste ", pct=10, semente="s", agora=agora)
        self.assertEqual(registro["aprovado_por"], "Revisora Teste")
        self.assertTrue(registro["id"].startswith("lote-20261007-103005-"))
        self.assertEqual(registro["em"], "2026-10-07T10:30:05")
        por_id = {e["id"]: e for e in self.eventos}
        for i in registro["aprovados"]:
            ev = por_id[i]
            self.assertEqual((ev["status"], ev["aprovado_por"], ev["aprovado_em"], ev["lote"]),
                             ("aprovado", "Revisora Teste", "2026-10-07T10:30:05", registro["id"]))
            self.assertEqual(ev["triagem"], {"nivel": "verde", "motivos": []})
            self.assertEqual(self.gabarito[i][1], "verde")
        for i in registro["amostra"]:
            self.assertEqual(por_id[i]["status"], "rascunho")
            self.assertEqual(por_id[i]["amostra_lote"], registro["id"])
            self.assertNotIn("aprovado_por", por_id[i])
        # ninguém além dos aprovados mudou de status
        mudaram = {e["id"] for e in self.eventos if e["status"] != "rascunho"}
        self.assertEqual(mudaram, set(registro["aprovados"]))
        self.assertEqual(set(registro["aprovados"]) | set(registro["amostra"]), verdes_antes)

    def test_sorteado_para_amostra_nunca_mais_entra_em_lote(self):
        r1 = triagem.aplicar_lote(self.eventos, self.fichas, "A", pct=10, semente="s")
        r2 = triagem.aplicar_lote(self.eventos, self.fichas, "A", pct=10, semente="s")
        self.assertEqual(r2["aprovados"], [])            # os verdes que sobraram são justamente a amostra do lote 1
        self.assertEqual(r2["amostra"], [])
        self.assertEqual(r2["barrados"]["amostra_anterior"], len(r1["amostra"]))

    def test_lote_pede_aprovador(self):
        for vazio in ("", "   ", None):
            with self.assertRaises(ValueError):
                triagem.aplicar_lote(self.eventos, self.fichas, vazio)
        self.assertTrue(all(e["status"] == "rascunho" for e in self.eventos))

    def test_segunda_trava_sempre_humano_mesmo_se_o_nivel_vier_errado(self):
        """Se um dia a classificação deixar passar um verde que exige olho humano, o lote ainda o barra."""
        falso = {"nivel": "verde", "motivos": ["Há prazo."], "codigos": ["prazo"]}
        with mock.patch.object(triagem, "classificar_detalhado", return_value=falso):
            plano = triagem.preparar_lote(self.eventos, self.fichas, pct=0)
        self.assertEqual(plano["aprovar"], [])
        self.assertEqual(plano["barrados"]["vermelho"], 600)

    def test_filtro_do_lote_restringe_o_que_e_aprovado(self):
        cliente = fch.obter(self.fichas[0], "cliente")
        plano = triagem.preparar_lote(self.eventos, self.fichas, filtros={"cliente": cliente, "nivel": "vermelho"}, pct=10, semente="s")
        self.assertTrue(plano["aprovar"])
        self.assertTrue(all(i["nivel"] == "verde" and triagem.cliente_de(i) == cliente for i in plano["aprovar"]))   # nível do filtro é ignorado
        todos = triagem.preparar_lote(self.eventos, self.fichas, pct=10, semente="s")
        self.assertLess(len(plano["elegiveis"]), len(todos["elegiveis"]))

    def test_registro_de_lotes_em_disco(self):
        with ficticio.projeto_de_teste(self.fichas):
            self.assertEqual(triagem.lotes(), [])
            reg = triagem.aplicar_lote(self.eventos, self.fichas, "A", pct=10, semente="s")
            triagem.registrar_lote(reg)
            triagem.registrar_lote({**reg, "id": "outro"})
            self.assertEqual([l["id"] for l in triagem.lotes()], [reg["id"], "outro"])
            self.assertTrue((comum.DATA / "lotes.json").exists())


class Configuracao(unittest.TestCase):
    def test_padroes_e_sobreposicao(self):
        with mock.patch.object(comum, "config", lambda: {}):
            self.assertEqual(triagem.configuracao(), {"amostragem_pct": 10.0, "semente": "triagem-v1", "sugerir_a_partir_de": 20})
        with mock.patch.object(comum, "config", lambda: {"triagem": {"amostragem_pct": 25, "semente": "x", "sugerir_a_partir_de": 5}}):
            self.assertEqual(triagem.configuracao(), {"amostragem_pct": 25.0, "semente": "x", "sugerir_a_partir_de": 5})
        with mock.patch.object(comum, "config", lambda: {"triagem": {"amostragem_pct": "lixo", "sugerir_a_partir_de": None}}):
            self.assertEqual(triagem.configuracao()["amostragem_pct"], 10.0)
        with mock.patch.object(comum, "config", lambda: {"triagem": {"amostragem_pct": 500}}):
            self.assertEqual(triagem.configuracao()["amostragem_pct"], 100.0)

    def test_amostragem_vem_do_config(self):
        ids = [f"e{i}" for i in range(100)]
        with mock.patch.object(comum, "config", lambda: {"triagem": {"amostragem_pct": 30, "semente": "q"}}):
            self.assertEqual(len(triagem.amostra_obrigatoria(ids)), 30)


if __name__ == "__main__":
    unittest.main()
