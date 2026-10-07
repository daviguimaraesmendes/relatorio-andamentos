"""Quadros analíticos (src/quadros.py, WS-11), conferidos contra cálculo independente em Python.

    python3 -m unittest tests/test_quadros.py -v

Duas frentes: (1) cenários montados à mão, com o resultado calculado no papel; (2) a carteira fictícia de 200
processos, em que o cálculo é refeito aqui direto nos dicionários das fichas, sem usar as regras de
qualidade.py nem `ficha.obter`.
"""
import copy
import json
import sys
import unittest
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import ficha  # noqa: E402
import ficticio  # noqa: E402
import quadros  # noqa: E402

NUM = ficticio.numero_ficticio


def mk(n, ativo=True, **campos):
    padrao = {"cliente": "Cliente Exemplo 01 Ltda", "polo_cliente": "passivo", "momento_atual": "AGUARDANDO SENTENÇA",
              "situacao": "Ativo", "valor_causa": "10000.00", "materia_principal": "Horas extras e reflexos"}
    f = ficha.nova_ficha(NUM(n))
    for campo, valor in {**padrao, **campos}.items():
        if valor is not None:
            assert ficha.definir(f, campo, valor, "humano", forcar=True), (campo, valor)
    f["ativo"] = ativo
    return f


def encerrada(n, resultado, **campos):
    momento = {"Acordo": "ACORDO HOMOLOGADO", "Extinto sem resolução de mérito": "EXTINTO SEM RESOLUÇÃO DE MÉRITO"}.get(resultado, "TRÂNSITO EM JULGADO")
    return mk(n, ativo=False, momento_atual=momento, situacao="Encerrado", resultado=resultado, **campos)


def linha(q, chave, valor, campo="chave"):
    return next(l for l in q["linhas"] if l[campo] == valor)


def tem_json(teste, q):
    teste.assertEqual(json.loads(json.dumps(q)), q)


# ================================================================== cenários no papel

class TestAcordosXEconomia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = [
            encerrada(1, "Acordo", valor_causa="10000.00", valor_acordo="4000.00", valor_estimado="4000.00", valor_economizado="6000.00"),
            encerrada(2, "Acordo", valor_causa="20000.00", valor_acordo="5000.00", valor_estimado="5000.00", valor_economizado="15000.00",
                      observacoes="[acordo pago por terceiro]"),
            encerrada(3, "Extinto sem resolução de mérito", valor_causa="8000.00", valor_estimado="0.00", valor_economizado="8000.00",
                      observacoes="[exclusão da lide]"),
            encerrada(4, "Procedente", polo_cliente="ativo", valor_causa="3000.00", valor_arbitrado="2500.00", valor_estimado="2500.00",
                      valor_economizado="500.00"),
            encerrada(5, "Acordo", valor_causa="12000.00", valor_economizado="12000.00"),          # acordo sem valor lançado
            encerrada(6, "Improcedente", valor_causa="50000.00", valor_estimado="0.00", valor_economizado="50000.00"),
            encerrada(7, "Extinto sem resolução de mérito", valor_causa="7000.00", valor_estimado="0.00", valor_economizado="7000.00"),
            encerrada(8, "Procedente", valor_causa="40000.00", valor_arbitrado="30000.00", valor_estimado="30000.00"),   # economia calculada
            encerrada(9, "Improcedente", valor_causa="9000.00"),                                      # sem economia nenhuma
            mk(10, valor_causa="1000.00", valor_economizado="999.00"),                                # ativo: nunca entra
        ]
        cls.q = quadros.acordos_x_economia(cls.fichas)

    def camada(self, chave):
        return linha(self.q, "chave", chave)

    def test_total_geral(self):
        c = self.camada("total_geral")
        self.assertEqual((c["processos"], c["valor_causa"], c["economia"], c["valor_desfecho"]), (8, "150000.00", "108500.00", "41500.00"))
        self.assertEqual((c["acordos"], c["valor_acordos"]), (3, "9000.00"))
        self.assertEqual(c["percentual_economia"], round(108500 / 150000 * 100, 2))

    def test_apenas_com_desembolso_do_cliente(self):
        c = self.camada("desembolso_do_cliente")
        self.assertEqual((c["processos"], c["valor_causa"], c["economia"]), (5, "119000.00", "85000.00"))
        self.assertEqual((c["acordos"], c["valor_acordos"]), (2, "4000.00"))

    def test_desfecho_pecuniario_definido_e_o_indicador_recomendado(self):
        c = self.camada("desfecho_pecuniario_definido")
        self.assertEqual((c["processos"], c["valor_causa"], c["economia"], c["percentual_economia"]), (3, "100000.00", "66000.00", 66.0))
        self.assertEqual((c["acordos"], c["valor_acordos"]), (1, "4000.00"))
        self.assertEqual(self.q["resumo"]["indicador_recomendado"], "desfecho_pecuniario_definido")
        self.assertIn("recomendado", c["camada"])

    def test_resumo_dos_excluidos(self):
        r = self.q["resumo"]
        self.assertEqual((r["encerrados"], r["com_economia"], r["sem_economia"]), (9, 8, 1))
        self.assertEqual(r["excluidos"], {"acordo_sem_valor": 1, "acordo_terceiro": 1, "exclusao_lide": 1, "cliente_autor": 1,
                                         "sem_desfecho_pecuniario_definido": 1})

    def test_detalhe_por_processo_com_a_camada_em_que_parou(self):
        d = {x["numero"]: x for x in self.q["detalhe"]}
        self.assertEqual(len(d), 8)
        self.assertEqual(d[NUM(1)]["camada"], "desfecho_pecuniario_definido")
        self.assertEqual(d[NUM(2)]["camada"], "total_geral")
        self.assertEqual(d[NUM(2)]["ressalvas"], ["acordo pago por terceiro"])
        self.assertEqual(d[NUM(5)]["camada"], "desembolso_do_cliente")
        self.assertEqual(d[NUM(5)]["ressalvas"], ["acordo sem valor lançado"])
        self.assertEqual(d[NUM(8)]["economia"], "10000.00", "calculada: causa menos estimado")
        self.assertEqual(d[NUM(7)]["camada"], "desembolso_do_cliente")
        self.assertNotIn(NUM(10), d)
        self.assertNotIn(NUM(9), d)

    def test_notas_tem_os_numeros_do_caso(self):
        texto = "\n".join(self.q["notas"])
        for trecho in ("8 processo(s), economia de R$ 108.500,00", "cliente autor: 1", "acordo pago por terceiro: 1",
                       "exclusão da lide: 1", "acordo sem valor lançado: 1", "R$ 66.000,00", "indicador recomendado",
                       "1 processo(s) encerrado(s) não têm valor", "[acordo pago por terceiro]"):
            self.assertIn(trecho, texto)

    def test_sugerido_fica_de_fora_por_padrao(self):
        f = encerrada(1, "Improcedente", valor_causa="1000.00")
        ficha.definir(f, "valor_estimado", "0.00", "sugerido")
        ficha.definir(f, "valor_economizado", "1000.00", "sugerido")
        q = quadros.acordos_x_economia([f])
        self.assertEqual(linha(q, "chave", "total_geral")["processos"], 0)
        self.assertIn("2 valor(es) apenas sugerido(s)", "\n".join(q["notas"]))
        q = quadros.acordos_x_economia([f], apenas_confirmados=False)
        self.assertEqual(linha(q, "chave", "total_geral")["economia"], "1000.00")
        self.assertNotIn("apenas sugerido", "\n".join(q["notas"]))

    def test_estrutura_e_json(self):
        self.assertEqual(set(self.q), {"titulo", "colunas", "linhas", "resumo", "detalhe", "notas", "avisos"})
        for l in self.q["linhas"]:
            self.assertTrue({c["chave"] for c in self.q["colunas"]} <= set(l))
        self.assertEqual({c["tipo"] for c in self.q["colunas"]}, {"texto", "inteiro", "dinheiro", "percentual"})
        tem_json(self, self.q)

    def test_carteira_vazia_e_sem_encerrados(self):
        for entrada in ([], [mk(1)]):
            q = quadros.acordos_x_economia(entrada)
            self.assertEqual([l["processos"] for l in q["linhas"]], [0, 0, 0])
            self.assertEqual([l["percentual_economia"] for l in q["linhas"]], [None, None, None])


class TestMaioresExposicoes(unittest.TestCase):
    def test_maior_valor_e_origem_com_desempate(self):
        fichas = [mk(1, valor_causa="500.00", valor_estimado="100.00"),                       # causa 500
                  mk(2, valor_causa="400.00", valor_estimado="700.00", valor_arbitrado="700.00"),  # empate estimado/arbitrado: estimado
                  mk(3, valor_causa="100.00", valor_execucao="900.00"),                       # execução
                  mk(4, valor_causa="1000.00", valor_arbitrado="800.00"),                     # causa vence
                  mk(5, valor_causa="9999.00", polo_cliente="ativo"),                         # autor: fora
                  encerrada(6, "Procedente", valor_causa="8888.00"),                          # encerrado: fora
                  mk(7, valor_causa=None),                                                    # sem valor nenhum: fora
                  mk(8, valor_causa="0.00")]
        q = quadros.maiores_exposicoes(fichas)
        self.assertEqual([(l["numero"], l["exposicao"], l["base"]) for l in q["linhas"]],
                         [(NUM(4), "1000.00", "causa"), (NUM(3), "900.00", "execução"), (NUM(2), "700.00", "estimado"),
                          (NUM(1), "500.00", "causa")])
        self.assertEqual([l["posicao"] for l in q["linhas"]], [1, 2, 3, 4])
        self.assertEqual(q["resumo"], {"processos_considerados": 4, "exposicao_total": "3100.00", "exposicao_top": "3100.00",
                                       "concentracao_top": 100.0})

    def test_top_empate_de_ranking_e_opcoes(self):
        fichas = [mk(n, valor_causa="1000.00") for n in (5, 3, 4)] + [mk(1, valor_causa="10.00")]
        q = quadros.maiores_exposicoes(fichas, top=2)
        self.assertEqual([l["numero"] for l in q["linhas"]], [NUM(3), NUM(4)], "empate: número do processo")
        self.assertEqual((q["resumo"]["processos_considerados"], q["resumo"]["exposicao_top"], q["resumo"]["exposicao_total"]),
                         (4, "2000.00", "3010.00"))
        self.assertEqual(q["resumo"]["concentracao_top"], round(2000 / 3010 * 100, 2))
        extra = [mk(20, polo_cliente="ativo", valor_causa="5000.00"), encerrada(21, "Improcedente", valor_causa="6000.00")]
        self.assertEqual(len(quadros.maiores_exposicoes(extra)["linhas"]), 0)
        self.assertEqual([l["numero"] for l in quadros.maiores_exposicoes(extra, incluir_encerrados=True, incluir_cliente_autor=True)["linhas"]],
                         [NUM(21), NUM(20)])

    def test_notas_e_json(self):
        q = quadros.maiores_exposicoes([mk(1, valor_causa="500.00")])
        self.assertIn("R$ 500,00", "\n".join(q["notas"]))
        self.assertIn("cliente não é autor", "\n".join(q["notas"]))
        tem_json(self, q)
        self.assertEqual(quadros.maiores_exposicoes([])["linhas"], [])


class TestCondenacaoXCausa(unittest.TestCase):
    def test_no_papel(self):
        fichas = [encerrada(1, "Procedente", valor_causa="1000.00", valor_arbitrado="800.00"),
                  encerrada(2, "Parcialmente procedente", valor_causa="2000.00", valor_arbitrado="500.00"),
                  encerrada(3, "Procedente", valor_causa="100.00", valor_arbitrado="150.00"),
                  encerrada(4, "Procedente", valor_causa="777.00"),                       # sem arbitrado: conta como falta
                  encerrada(5, "Improcedente", valor_causa="5000.00", valor_arbitrado="1.00")]   # não é condenação
        q = quadros.condenacao_x_causa(fichas)
        proc, parc, total = q["linhas"]
        self.assertEqual((proc["processos"], proc["valor_causa"], proc["condenacao"], proc["percentual"]), (2, "1100.00", "950.00", round(950 / 1100 * 100, 2)))
        self.assertEqual((parc["processos"], parc["valor_causa"], parc["condenacao"], parc["percentual"]), (1, "2000.00", "500.00", 25.0))
        self.assertEqual((total["resultado"], total["processos"], total["valor_causa"], total["condenacao"], total["percentual"]),
                         ("Total", 3, "3100.00", "1450.00", round(1450 / 3100 * 100, 2)))
        self.assertEqual(q["resumo"], {"sem_valor_arbitrado": 1, "acima_da_causa": 1})
        self.assertEqual([d["numero"] for d in q["detalhe"]], [NUM(1), NUM(2), NUM(3)])
        self.assertEqual(next(d for d in q["detalhe"] if d["numero"] == NUM(3))["diferenca"], "-50.00")
        texto = "\n".join(q["notas"])
        self.assertIn("1 processo(s) procedente(s) ou parcialmente procedente(s) não têm valor arbitrado", texto)
        self.assertIn("1 processo(s) têm condenação acima do valor da causa", texto)
        tem_json(self, q)

    def test_vazio(self):
        q = quadros.condenacao_x_causa([])
        self.assertEqual([l["processos"] for l in q["linhas"]], [0, 0, 0])
        self.assertIsNone(q["linhas"][-1]["percentual"])


class TestComposicaoPorTese(unittest.TestCase):
    def test_no_papel(self):
        fichas = [mk(1, materia_principal="Horas extras e reflexos", valor_causa="1000.00"),
                  mk(2, materia_principal="horas extras", valor_causa="3000.00"),                      # sinônimo: junta
                  encerrada(3, "Improcedente", materia_principal="Horas extras e reflexos", valor_causa="2000.00"),
                  mk(4, materia_principal="Dano moral", valor_causa="4000.00"),
                  mk(5, materia_principal="Honorários advocatícios", valor_causa="1000.00"),
                  mk(6, materia_principal="Matéria Inventada Exemplo", valor_causa="500.00"),             # fora do vocabulário
                  mk(7, materia_principal=None, valor_causa="500.00")]
        q = quadros.composicao_por_tese(fichas)
        por = {l["tese"]: l for l in q["linhas"]}
        he = por["Horas extras e reflexos"]
        self.assertEqual((he["processos"], he["ativos"], he["valor_causa"], he["tema"], he["conta_nos_rankings"]), (3, 2, "6000.00", "Jornada", "Sim"))
        self.assertEqual(he["percentual_processos"], round(3 / 7 * 100, 2))
        self.assertEqual(he["percentual_valor"], round(6000 / 12000 * 100, 2))
        self.assertEqual(por["Honorários advocatícios"]["conta_nos_rankings"], "Não")
        self.assertEqual((por["Matéria Inventada Exemplo"]["tema"], por["Matéria Inventada Exemplo"]["conta_nos_rankings"]), (None, None))
        self.assertIn(quadros.SEM_MATERIA, por)
        self.assertEqual(q["linhas"][0]["tese"], "Horas extras e reflexos", "ordenado por quantidade")
        self.assertEqual(sum(l["processos"] for l in q["linhas"]), 7)
        self.assertAlmostEqual(sum(l["percentual_processos"] for l in q["linhas"]), 100, delta=0.1)
        self.assertEqual(q["resumo"]["processos"], 7)
        self.assertEqual(Decimal(q["resumo"]["valor_causa"]), Decimal("12000.00"))
        jornada = next(t for t in q["resumo"]["por_tema"] if t["tema"] == "Jornada")
        self.assertEqual((jornada["processos"], jornada["valor_causa"]), (3, "6000.00"))
        texto = "\n".join(q["notas"])
        self.assertIn("1 processo(s) sem matéria principal", texto)
        self.assertIn("Matéria Inventada Exemplo", texto)
        tem_json(self, q)


class TestDesfechoPorTese(unittest.TestCase):
    def test_no_papel(self):
        fichas = [encerrada(1, "Improcedente", polo_cliente="passivo"),                       # favorável
                  encerrada(2, "Procedente", polo_cliente="ativo"),                           # favorável
                  encerrada(3, "Procedente", polo_cliente="passivo"),                         # desfavorável
                  encerrada(4, "Parcialmente procedente", polo_cliente="passivo"),            # parcial: nunca favorável
                  encerrada(5, "Improcedente", polo_cliente=None),                            # sem polo
                  encerrada(6, "Acordo", valor_acordo="1.00"),                                # fora do mérito
                  encerrada(7, "Extinto sem resolução de mérito"),
                  mk(8),                                                                       # sem resultado
                  encerrada(9, "Improcedente", materia_principal="Dano moral")]
        q = quadros.desfecho_por_tese(fichas)
        t = linha(q, "tese", "Horas extras e reflexos", "tese")
        self.assertEqual((t["julgados"], t["procedentes"], t["parciais"], t["improcedentes"]), (5, 2, 1, 2))
        self.assertEqual((t["favoraveis"], t["sem_polo"], t["percentual_favoravel"]), (2, 1, 50.0))
        dm = linha(q, "tese", "Dano moral", "tese")
        self.assertEqual((dm["julgados"], dm["favoraveis"]), (1, 1))
        self.assertEqual(q["resumo"]["total"]["julgados"], 6)
        self.assertEqual(q["resumo"]["fora_do_merito"], {"Acordo": 1, "Extinto sem resolução de mérito": 1})
        texto = "\n".join(q["notas"])
        self.assertIn("Só entram processos julgados no mérito", texto)
        self.assertIn("Acordo: 1", texto)
        self.assertIn("não inverte por polo", texto)
        tem_json(self, q)

    def test_sem_polo_nenhum_nao_divide_por_zero(self):
        q = quadros.desfecho_por_tese([encerrada(1, "Procedente", polo_cliente=None)])
        self.assertIsNone(q["linhas"][0]["percentual_favoravel"])


class TestGerarEBase(unittest.TestCase):
    def test_gerar_junta_tudo_com_notas(self):
        fichas = [encerrada(1, "Acordo", valor_causa="10000.00", valor_acordo="4000.00", valor_estimado="4000.00"),
                  mk(2, valor_causa="5000.00")]
        q = quadros.gerar(fichas, top=5)
        self.assertEqual(set(q), {"acordos_x_economia", "maiores_exposicoes", "condenacao_x_causa", "composicao_por_tese",
                                  "desfecho_por_tese", "notas", "avisos"})
        self.assertIn("Maiores exposições (top 5)", q["maiores_exposicoes"]["titulo"])
        notas = "\n".join(q["notas"])
        for q_ in ("Acordos x economia", "Maiores exposições", "Condenação x valor da causa", "Composição da carteira", "Desfecho por tese"):
            self.assertIn(q_, notas)
        self.assertIn("R$ 6.000,00", notas)
        self.assertTrue(all(isinstance(n, str) for n in q["notas"]))
        tem_json(self, q)

    def test_gerar_com_carteira_vazia(self):
        q = quadros.gerar([])
        self.assertEqual(q["avisos"], [])
        self.assertEqual(q["composicao_por_tese"]["linhas"], [])
        tem_json(self, q)

    def test_ficha_repetida_marcador_e_sugerido(self):
        f = encerrada(1, "Improcedente", valor_causa="1000.00", valor_estimado="0.00")
        outra = copy.deepcopy(f)
        ficha.definir(outra, "valor_causa", "9.00", "humano", forcar=True)
        marcador = ficha.nova_ficha("0000000-00.0000.0.00.0000")
        q = quadros.gerar([f, outra, marcador])
        self.assertEqual([a["codigo"] for a in q["avisos"]], ["ficha_repetida_ignorada"])
        self.assertEqual(q["composicao_por_tese"]["resumo"]["processos"], 1)
        self.assertEqual(q["composicao_por_tese"]["resumo"]["valor_causa"], "1000.00", "valeu a primeira ficha")
        g = mk(2)
        ficha.definir(g, "valor_estimado", "123.00", "sugerido")
        self.assertIn("1 valor(es) apenas sugerido(s)", "\n".join(quadros.gerar([g])["notas"]))

    def test_item_da_fase_1_e_nao_altera_as_fichas(self):
        fichas = ficticio.gerar_carteira(30)
        antes = copy.deepcopy(list(fichas))
        quadros.gerar(fichas)
        self.assertEqual(antes, list(fichas))
        antigo = {"numero": NUM(3), "cliente": "Cliente Exemplo 01 Ltda", "polo_cliente": "passivo", "ativo": True}
        self.assertEqual(quadros.composicao_por_tese([antigo])["linhas"][0]["tese"], quadros.SEM_MATERIA)


# ================================================================== carteira fictícia, cálculo independente

ENCERRADOS = {"TRÂNSITO EM JULGADO", "PROCESSO ARQUIVADO", "ACORDO HOMOLOGADO", "EXTINTO SEM RESOLUÇÃO DE MÉRITO"}
MERITO = ("Procedente", "Parcialmente procedente", "Improcedente")


def v(f, campo):
    return (f.get("campos", {}).get(campo) or {}).get("valor")


def d(f, campo):
    x = v(f, campo)
    return Decimal(x) if x not in (None, "") else None


def acabou(f):
    return (not f["ativo"]) or v(f, "situacao") == "Encerrado" or v(f, "momento_atual") in ENCERRADOS


def ressalvas(f):
    obs = (v(f, "observacoes") or "").lower()
    r = set()
    if v(f, "resultado") == "Acordo" and not v(f, "valor_acordo"):
        r.add("sem_valor")
    if "pago por terceiro" in obs:
        r.add("terceiro")
    if "exclusão da lide" in obs:
        r.add("exclusao")
    if v(f, "polo_cliente") == "ativo":
        r.add("autor")
    return r


class TestCarteiraFicticia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ficticio.gerar_carteira(200, semente=3)
        cls.fichas = copy.deepcopy(list(base))
        # injeta ressalvas para as camadas diferirem de verdade: acordos pagos por terceiro e exclusões da lide
        acordos = [f for f in cls.fichas if v(f, "resultado") == "Acordo"]
        extintos = [f for f in cls.fichas if v(f, "resultado") == "Extinto sem resolução de mérito"]
        for f in acordos[::2]:
            ficha.definir(f, "observacoes", "[acordo pago por terceiro]", "humano", forcar=True)
        for f in extintos[::2]:
            ficha.definir(f, "observacoes", "[exclusão da lide]", "humano", forcar=True)
        for f in cls.fichas:   # deixa quase todo encerrado com economia lançada, para as camadas terem corpo
            if acabou(f) and d(f, "valor_economizado") is None and d(f, "valor_causa"):
                est = d(f, "valor_estimado")
                if est is None and v(f, "resultado") in ("Improcedente", "Extinto sem resolução de mérito", "Arquivado / desistência"):
                    ficha.definir(f, "valor_estimado", "0.00", "humano")
        cls.q = quadros.gerar(cls.fichas)

    def economia(self, f):
        e = d(f, "valor_economizado")
        if e is not None:
            return e
        c, est = d(f, "valor_causa"), d(f, "valor_estimado")
        return c - est if c is not None and est is not None else None

    def test_acordos_x_economia(self):
        universo = [(f, self.economia(f)) for f in self.fichas if acabou(f)]
        universo = [(f, e) for f, e in universo if e is not None]
        c2 = [(f, e) for f, e in universo if not ressalvas(f) & {"terceiro", "exclusao", "autor"}]

        def definido(f):
            r = v(f, "resultado")
            return (r == "Acordo" and bool(v(f, "valor_acordo"))) or (r in ("Procedente", "Parcialmente procedente") and v(f, "valor_arbitrado") is not None) or r == "Improcedente"
        c3 = [(f, e) for f, e in c2 if "sem_valor" not in ressalvas(f) and definido(f)]
        q = self.q["acordos_x_economia"]
        for chave, membros in (("total_geral", universo), ("desembolso_do_cliente", c2), ("desfecho_pecuniario_definido", c3)):
            l = linha(q, "chave", chave)
            causa = sum((d(f, "valor_causa") or Decimal(0) for f, _ in membros), Decimal(0))
            eco = sum((e for _, e in membros), Decimal(0))
            self.assertEqual(l["processos"], len(membros), chave)
            self.assertEqual(Decimal(l["valor_causa"]), causa, chave)
            self.assertEqual(Decimal(l["economia"]), eco, chave)
            self.assertEqual(l["percentual_economia"], round(float(eco / causa * 100), 2) if causa else None, chave)
            self.assertEqual(l["acordos"], sum(1 for f, _ in membros if v(f, "resultado") == "Acordo"), chave)
        t, c2_, c3_ = (linha(q, "chave", k)["processos"] for k in ("total_geral", "desembolso_do_cliente", "desfecho_pecuniario_definido"))
        self.assertTrue(t > c2_ > c3_ > 0, (t, c2_, c3_))
        self.assertGreater(Decimal(linha(q, "chave", "total_geral")["economia"]), Decimal(linha(q, "chave", "desfecho_pecuniario_definido")["economia"]))

    def test_maiores_exposicoes(self):
        candidatos = []
        for f in self.fichas:
            if acabou(f) or v(f, "polo_cliente") == "ativo":
                continue
            valores = [(d(f, c), nome) for c, nome in (("valor_estimado", "estimado"), ("valor_arbitrado", "arbitrado"),
                                                       ("valor_execucao", "execução"), ("valor_causa", "causa")) if d(f, c) is not None]
            valores = [x for x in valores if x[0] > 0]
            if valores:
                melhor = max(valores, key=lambda x: x[0])   # max devolve o primeiro dos empatados: mesma ordem de preferência
                candidatos.append((-melhor[0], f["numero"], melhor[1]))
        candidatos.sort()
        q = self.q["maiores_exposicoes"]
        self.assertEqual([(l["numero"], Decimal(l["exposicao"]), l["base"]) for l in q["linhas"]],
                         [(n, -v_, b) for v_, n, b in candidatos[:10]])
        self.assertEqual(q["resumo"]["processos_considerados"], len(candidatos))
        self.assertEqual(Decimal(q["resumo"]["exposicao_total"]), -sum(c[0] for c in candidatos))
        self.assertEqual(len(q["linhas"]), 10)

    def test_condenacao_x_causa(self):
        com = [f for f in self.fichas if v(f, "resultado") in ("Procedente", "Parcialmente procedente")
               and d(f, "valor_arbitrado") and d(f, "valor_causa")]
        q = self.q["condenacao_x_causa"]
        total = linha(q, "resultado", "Total", "resultado")
        self.assertGreater(len(com), 5)
        self.assertEqual(total["processos"], len(com))
        self.assertEqual(Decimal(total["valor_causa"]), sum(d(f, "valor_causa") for f in com))
        self.assertEqual(Decimal(total["condenacao"]), sum(d(f, "valor_arbitrado") for f in com))
        for r in ("Procedente", "Parcialmente procedente"):
            m = [f for f in com if v(f, "resultado") == r]
            l = linha(q, "resultado", r, "resultado")
            self.assertEqual((l["processos"], Decimal(l["condenacao"])), (len(m), sum((d(f, "valor_arbitrado") for f in m), Decimal(0))))
        self.assertEqual(q["resumo"]["sem_valor_arbitrado"],
                         sum(1 for f in self.fichas if v(f, "resultado") in ("Procedente", "Parcialmente procedente")) - len(com))

    def test_composicao_por_tese(self):
        contagem = Counter(v(f, "materia_principal") for f in self.fichas)
        valor = defaultdict(Decimal)
        for f in self.fichas:
            valor[v(f, "materia_principal")] += d(f, "valor_causa")
        q = self.q["composicao_por_tese"]
        self.assertEqual({l["tese"]: l["processos"] for l in q["linhas"]}, dict(contagem))
        self.assertEqual({l["tese"]: Decimal(l["valor_causa"]) for l in q["linhas"]}, dict(valor))
        self.assertEqual(sum(l["processos"] for l in q["linhas"]), 200)
        self.assertEqual(Decimal(q["resumo"]["valor_causa"]), sum(valor.values()))
        self.assertEqual({l["tese"]: l["ativos"] for l in q["linhas"]},
                         {m: sum(1 for f in self.fichas if v(f, "materia_principal") == m and not acabou(f)) for m in contagem})

    def test_desfecho_por_tese(self):
        julgados = [f for f in self.fichas if v(f, "resultado") in MERITO]
        q = self.q["desfecho_por_tese"]
        self.assertEqual(q["resumo"]["total"]["julgados"], len(julgados))
        for l in q["linhas"]:
            m = [f for f in julgados if v(f, "materia_principal") == l["tese"]]
            c = Counter(v(f, "resultado") for f in m)
            fav = sum(1 for f in m if (v(f, "polo_cliente") == "passivo" and v(f, "resultado") == "Improcedente")
                      or (v(f, "polo_cliente") == "ativo" and v(f, "resultado") == "Procedente"))
            self.assertEqual((l["julgados"], l["procedentes"], l["parciais"], l["improcedentes"], l["favoraveis"]),
                             (len(m), c["Procedente"], c["Parcialmente procedente"], c["Improcedente"], fav), l["tese"])
            self.assertEqual(l["percentual_favoravel"], round(fav / len(m) * 100, 2))
        self.assertEqual(sum(l["julgados"] for l in q["linhas"]), len(julgados))

    def test_estrutura_do_conjunto(self):
        tem_json(self, self.q)
        self.assertGreater(len(self.q["notas"]), 20)


if __name__ == "__main__":
    unittest.main()
