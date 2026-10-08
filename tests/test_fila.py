"""Fila de coleta em massa (src/fila.py), toda com o ColetorSimulado, relógio injetável e dados fictícios.
Nada de rede, certificado, navegador ou tribunal; o `ColetorReal` só tem a importação e a tradução testadas
(a coleta de verdade se valida no piloto).

    python3 -m unittest tests/test_fila.py -v
"""
import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import comum  # noqa: E402
import ficticio  # noqa: E402
import fila  # noqa: E402
import ficha  # noqa: E402
from fila import Fila, rodar_fila  # noqa: E402
from simulado import ColetorSimulado  # noqa: E402

FICHAS = ficticio.gerar_carteira(200, clientes=5, semente=1)
NUMEROS = [f["numero"] for f in FICHAS]
INICIO = datetime.datetime(2026, 10, 7, 21, 0, 0)     # dentro da janela padrão (20:00-06:00)


class Queda(BaseException):
    """Simula a queda do programa (BaseException: nenhum `except Exception` da fila a engole)."""


class Relogio:
    """Relógio e cronômetro falsos: `dormir` só avança o tempo, ninguém espera de verdade."""

    def __init__(self, inicio=INICIO):
        self.t, self.mono = inicio, 0.0

    def agora(self):
        return self.t

    def cron(self):
        return self.mono

    def avancar(self, s):
        self.t += datetime.timedelta(seconds=s)
        self.mono += s

    def dormir(self, s):
        self.avancar(s)


class Embrulho:
    """Coletor que embrulha outro: gasta tempo falso por chamada e permite espiar/interromper cada uma."""

    def __init__(self, base, relogio=None, duracao=0, antes=None, depois=None):
        self.base, self.relogio, self.duracao, self.antes, self.depois = base, relogio, duracao, antes, depois
        self.chamadas = []

    def coletar(self, processo, profundidade, desde):
        self.chamadas.append(processo["numero"])
        if self.antes:
            self.antes(len(self.chamadas), processo)
        r = self.base.coletar(processo, profundidade, desde)
        if self.relogio:
            self.relogio.avancar(self.duracao(processo["numero"]) if callable(self.duracao) else self.duracao)
        if self.depois:
            self.depois(len(self.chamadas), processo, r)
        return r


def simulado(taxa=0.0, fichas=FICHAS, **kw):
    kw.setdefault("pasta", tempfile.mkdtemp(prefix="fila-teste-", dir=isolamento.TMP))
    return ColetorSimulado(fichas, semente=1, taxa_falha=taxa, **kw)


def nova_fila(proj, rel=None, **kw):
    rel = rel or Relogio()
    kw.setdefault("pausa_s", (0, 0))
    kw.setdefault("janelas", [])
    kw.setdefault("espera_base_s", 60)
    return Fila(proj["slug"], relogio=rel.agora, cronometro=rel.cron, dormir=rel.dormir, **kw)


def estados(f):
    return {i["numero"]: i["estado"] for i in f.itens()}


def numeros_do(tribunal, n=None, fichas=FICHAS):
    achados = [x["numero"] for x in fichas if x["tribunal"] == tribunal]
    return achados[:n] if n else achados


class Base(unittest.TestCase):
    def setUp(self):
        self._ctx = ficticio.projeto_de_teste(FICHAS)
        self.proj = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.rel = Relogio()

    def fila(self, **kw):
        return nova_fila(self.proj, self.rel, **kw)


# ------------------------------------------------------------------ enfileirar e estado

class TestEnfileirar(Base):
    def test_grava_em_data_fila_json_e_nova_instancia_ve_o_mesmo(self):
        f = self.fila()
        r = f.enfileirar(NUMEROS[:5], modo="imediato", profundidade="rapido", prioridade=2, desde="2026-09-18")
        self.assertEqual(r["enfileirados"], NUMEROS[:5])
        arquivo = Path(self.proj["data"]) / "fila.json"
        self.assertTrue(arquivo.is_file())
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        self.assertEqual(set(dados["itens"]), set(NUMEROS[:5]))
        outra = self.fila()
        i = outra.item(NUMEROS[0])
        self.assertEqual((i["estado"], i["modo"], i["profundidade"], i["prioridade"], i["desde"]),
                         ("pendente", "imediato", "rapido", 2, "2026-09-18"))
        self.assertEqual(outra.resumo()["total"], 5)

    def test_cliente_e_tribunal_vem_da_carteira_e_do_numero(self):
        f = self.fila()
        f.enfileirar([NUMEROS[0]])
        i = f.item(NUMEROS[0])
        self.assertEqual(i["cliente"], ficha.obter(FICHAS[0], "cliente"))
        self.assertEqual(i["tribunal"], FICHAS[0]["tribunal"])
        f.enfileirar([{"numero": NUMEROS[1], "cliente": "Outro Cliente"}])
        self.assertEqual(f.item(NUMEROS[1])["cliente"], "Outro Cliente")

    def test_entradas_invalidas(self):
        f = self.fila()
        with self.assertRaises(ValueError):
            f.enfileirar(NUMEROS[:1], modo="noturno")
        with self.assertRaises(ValueError):
            f.enfileirar(NUMEROS[:1], profundidade="tudo")
        with self.assertRaises(ValueError):
            f.enfileirar(NUMEROS[:1], desde="ontem")
        with self.assertRaises(ValueError):
            Fila("relatorio-que-nao-existe")
        with self.assertRaises(ValueError):
            f.marcar(ficticio.numero_ficticio(9999), "coletado")
        with self.assertRaises(ValueError):
            f.marcar(NUMEROS[0], "voando")

    def test_repetir_numero_nao_duplica_nem_recoleta(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:3], profundidade="rapido")
        r = f.enfileirar(NUMEROS[:3], profundidade="completo", prioridade=5)
        self.assertEqual((r["enfileirados"], r["ja_na_fila"]), ([], NUMEROS[:3]))
        self.assertEqual(f.resumo()["total"], 3)
        self.assertEqual(f.item(NUMEROS[0])["profundidade"], "completo")      # pendente: parâmetros atualizados
        rodar_fila(f, simulado(), esperar=False)
        self.assertEqual(f.resumo()["coletado"], 3)
        r = f.enfileirar(NUMEROS[:3])
        self.assertEqual(r["ja_coletados"], NUMEROS[:3])                      # nunca repete `coletado`
        r = f.enfileirar(NUMEROS[:2], recoletar=True)                         # só no ciclo seguinte
        self.assertEqual(r["enfileirados"], NUMEROS[:2])
        self.assertEqual(f.resumo()["pendente"], 2)

    def test_so_djen_entra_como_manual_sem_chamar_o_coletor(self):
        so = numeros_do("TJSP", 3)
        f = self.fila(tribunais_so_djen=["TJSP"])
        f.enfileirar(so + NUMEROS[:2])
        c = simulado()
        rodar_fila(f, c, esperar=False)
        for n in so:
            self.assertEqual(f.item(n)["estado"], "manual")
            self.assertTrue(f.item(n)["so_djen"])
            self.assertEqual(c.chamadas_por_numero[n], 0)
        self.assertEqual(f.resumo()["so_djen"], 3)


# ------------------------------------------------------------------ ordem de saída

class TestOrdem(Base):
    def test_prioridade_maior_primeiro_e_empate_por_ordem_de_entrada(self):
        f = self.fila()
        base = [n for n in numeros_do("TJSP") + numeros_do("TJBA") + numeros_do("TJRS")][:6]
        f.enfileirar(base[:3], prioridade=0)
        f.enfileirar(base[3:5], prioridade=5)
        f.enfileirar(base[5:], prioridade=1)
        saiu = []
        while (i := f.proximo()) is not None:
            saiu.append(i["numero"])
            f.marcar(i["numero"], "coletado")
        self.assertEqual(saiu, [base[3], base[4], base[5], base[0], base[1], base[2]])

    def test_mesmo_trt_sai_junto_na_posicao_do_primeiro(self):
        f = self.fila()
        a, c = numeros_do("TRT3", 2)
        b, e = numeros_do("TRT9", 2)
        d = numeros_do("TJSP", 1)[0]
        f.enfileirar([a, b, c, d, e])
        saiu = []
        while (i := f.proximo()) is not None:
            saiu.append(i["numero"])
            f.marcar(i["numero"], "coletado")
        self.assertEqual(saiu, [a, c, b, e, d])

    def test_prioridade_vence_o_agrupamento_de_trt(self):
        f = self.fila()
        a, c = numeros_do("TRT3", 2)
        f.enfileirar([a], prioridade=0)
        f.enfileirar([numeros_do("TJSP", 1)[0]], prioridade=9)
        f.enfileirar([c], prioridade=0)
        primeiro = f.proximo()
        self.assertEqual(primeiro["numero"], numeros_do("TJSP", 1)[0])

    def test_filtro_por_cliente_e_por_lista(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:40])
        cliente = ficha.obter(FICHAS[0], "cliente")
        esperados = [n for n in NUMEROS[:40] if f.item(n)["cliente"] == cliente]
        c = simulado()
        rodar_fila(f, c, cliente=cliente, esperar=False)
        self.assertEqual({n for n in NUMEROS[:40] if f.item(n)["estado"] == "coletado"}, set(esperados))
        self.assertEqual(f.resumo(cliente=cliente)["pendente"], 0)
        self.assertEqual(f.resumo()["pendente"], 40 - len(esperados))
        lista = [n for n in NUMEROS[:40] if n not in esperados][:4]
        rodar_fila(f, c, numeros=lista, esperar=False)
        self.assertEqual(f.resumo()["coletado"], len(esperados) + 4)
        self.assertEqual(c.chamadas, len(esperados) + 4)


# ------------------------------------------------------------------ sequencial e pausa

class TestSequencial(Base):
    def test_um_por_vez_e_pausa_entre_processos(self):
        f = self.fila(pausa_s=(5, 5))
        f.enfileirar(NUMEROS[:3], modo="imediato")
        primeiro = f.proximo()
        self.assertIsNotNone(primeiro)
        self.assertIsNone(f.proximo(), "enquanto um coleta, ninguém sai")
        f.marcar(primeiro["numero"], "coletado")
        self.assertIsNone(f.proximo(), "pausa entre processos ainda não passou")
        self.assertAlmostEqual(f.espera_s(), 5, delta=1)
        self.rel.avancar(2)
        self.assertIsNone(f.proximo())
        self.rel.avancar(4)
        self.assertEqual(f.proximo()["numero"], NUMEROS[1])

    def test_rodar_fila_respeita_a_pausa_com_relogio_falso(self):
        f = self.fila(pausa_s=(10, 10))
        f.enfileirar(NUMEROS[:4], modo="imediato")
        momentos = []
        c = Embrulho(simulado(), antes=lambda n, p: momentos.append(self.rel.agora()))
        rodar_fila(f, c)
        passos = [(b - a).total_seconds() for a, b in zip(momentos, momentos[1:])]
        self.assertEqual(len(momentos), 4)
        self.assertTrue(all(p >= 10 for p in passos), passos)

    def test_pausa_sorteada_dentro_do_intervalo(self):
        f = self.fila(pausa_s=(3, 5), sorteio=lambda a, b: 4.0)
        f.enfileirar(NUMEROS[:2], modo="imediato")
        i = f.proximo()
        f.marcar(i["numero"], "coletado")
        self.assertAlmostEqual(f.espera_s(), 4, delta=1)


# ------------------------------------------------------------------ política de erro

class TestErros(Base):
    def test_transitorio_repete_com_espera_crescente_e_esgota(self):
        f = self.fila(espera_base_s=60, tentativas_max=3)
        f.enfileirar(NUMEROS[:1], modo="imediato")
        esperas = []
        for _ in range(3):
            i = f.proximo()
            self.assertIsNotNone(i)
            marcado = f.marcar(i["numero"], "erro", {"codigo": "timeout", "mensagem": "demorou"})
            if marcado["proxima_tentativa"]:
                esperas.append((datetime.datetime.fromisoformat(marcado["proxima_tentativa"]) - self.rel.agora()).total_seconds())
                self.assertIsNone(f.proximo(), "ainda dentro da espera")
                self.rel.avancar(esperas[-1])
        self.assertEqual(esperas, [60, 120])
        final = f.item(NUMEROS[0])
        self.assertEqual((final["estado"], final["tentativas"], final["erro"]["codigo"]), ("erro", 3, "timeout"))
        self.assertIsNone(final["proxima_tentativa"])
        self.assertIsNone(f.proximo())
        self.assertIsNone(f.espera_s())
        self.assertEqual(f.resumo()["erro_definitivo"], 1)
        self.assertEqual([x["numero"] for x in f.conferir_manualmente()], NUMEROS[:1])

    def test_espera_tem_teto(self):
        f = self.fila(espera_base_s=1000, tentativas_max=10)
        f.enfileirar(NUMEROS[:1], modo="imediato")
        for _ in range(5):
            i = f.proximo()
            m = f.marcar(i["numero"], "erro", {"codigo": "outro", "mensagem": ""})
            espera = (datetime.datetime.fromisoformat(m["proxima_tentativa"]) - self.rel.agora()).total_seconds()
            self.rel.avancar(espera)
        self.assertLessEqual(espera, fila.TETO_ESPERA_S)

    def test_codigos_permanentes_vao_para_manual_sem_repetir(self):
        f = self.fila()
        for pos, codigo in enumerate(("captcha", "segredo", "nao_encontrado")):
            with self.subTest(codigo=codigo):
                n = NUMEROS[pos]
                f.enfileirar([n], modo="imediato")
                i = f.proximo()
                self.assertEqual(i["numero"], n)
                m = f.marcar(n, "erro", {"codigo": codigo, "mensagem": "x"})
                self.assertEqual((m["estado"], m["erro"]["codigo"]), ("manual", codigo))
                self.assertIsNone(f.proximo())
                self.assertIsNone(f.espera_s())
                self.assertTrue(m["motivo"])
        self.assertEqual(f.reabrir(NUMEROS[:1]), NUMEROS[:1])      # só por ação do usuário
        self.assertEqual(f.item(NUMEROS[0])["estado"], "pendente")
        self.assertEqual(f.item(NUMEROS[1])["estado"], "manual")

    def test_codigo_desconhecido_vira_outro(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:1], modo="imediato")
        i = f.proximo()
        m = f.marcar(i["numero"], "erro", {"codigo": "marte", "mensagem": ""})
        self.assertEqual(m["erro"]["codigo"], "outro")

    def test_coletado_e_final(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:1], modo="imediato")
        i = f.proximo()
        f.marcar(i["numero"], "coletado")
        f.marcar(i["numero"], "coletado")        # idempotente
        with self.assertRaises(ValueError):
            f.marcar(i["numero"], "erro", {"codigo": "timeout", "mensagem": ""})
        self.assertEqual(f.reabrir([i["numero"]]), [], "reabrir nunca mexe em coletado")

    def test_excecao_do_coletor_vira_erro_outro_e_a_fila_segue(self):
        class Quebrado:
            def coletar(self, processo, profundidade, desde):
                if processo["numero"] == NUMEROS[1]:
                    raise RuntimeError("bug no coletor")
                return {"capa": {}, "movimentos": [], "documentos": [], "erro": None}
        f = self.fila(tentativas_max=1)
        f.enfileirar(NUMEROS[:3], modo="imediato")
        rodar_fila(f, Quebrado())
        self.assertEqual(f.item(NUMEROS[1])["estado"], "erro")
        self.assertIn("bug no coletor", f.item(NUMEROS[1])["erro"]["mensagem"])
        self.assertEqual(f.resumo()["coletado"], 2)

    def test_falha_ao_gravar_o_resultado_nao_marca_coletado(self):
        chamadas = []

        def gravar(item, resultado):
            chamadas.append(item["numero"])
            if len(chamadas) == 1:
                raise OSError("disco cheio")
        f = self.fila(espera_base_s=1)
        f.enfileirar(NUMEROS[:2], modo="imediato", profundidade="rapido")
        c = simulado()
        rodar_fila(f, c, ao_resultado=gravar)
        self.assertEqual(f.resumo()["coletado"], 2)
        self.assertEqual(chamadas.count(NUMEROS[0]), 2, "o primeiro foi tentado de novo, porque não foi gravado")


# ------------------------------------------------------------------ 200 processos, falhas aleatórias

class TestEscala(Base):
    def esperado(self, c, tentativas_max):
        """Destino de cada número, calculado do coletor (independente da fila)."""
        manual, coletado = {}, []
        for n in NUMEROS:
            codigo = c.codigo_de_falha_previsto(n)
            if codigo in fila.PERMANENTES:
                manual[n] = codigo
            elif codigo is not None and c.tentativas_transitorias >= tentativas_max:
                manual[n] = "esgotou"
            else:
                coletado.append(n)
        return manual, coletado

    def test_200_com_falhas_aleatorias_terminam(self):
        c = simulado(taxa=0.3)
        f = self.fila(tentativas_max=3)
        f.enfileirar(NUMEROS, modo="imediato", profundidade="rapido")
        manual, coletado = self.esperado(c, 3)
        self.assertTrue(manual and any(c.codigo_de_falha_previsto(n) for n in coletado), "a fixture precisa ter os dois tipos de falha")
        resumo = rodar_fila(f, c)
        self.assertEqual((resumo["pendente"], resumo["coletando"]), (0, 0))
        self.assertEqual(resumo["coletado"], len(coletado))
        self.assertEqual(resumo["manual"], len(manual))
        self.assertEqual(resumo["total"], 200)
        for n in manual:
            self.assertEqual(f.item(n)["erro"]["codigo"], manual[n])
            self.assertEqual(c.chamadas_por_numero[n], 1)         # manual: nunca repetido
        for n in coletado:
            previsto = c.codigo_de_falha_previsto(n)
            self.assertEqual(c.chamadas_por_numero[n], 2 if previsto else 1, n)   # transitório: 1 repetição

    def test_transitorio_que_nunca_passa_esgota_as_tentativas(self):
        c = simulado(taxa=0.3, tentativas_transitorias=99)
        f = self.fila(tentativas_max=3)
        f.enfileirar(NUMEROS, modo="imediato", profundidade="rapido")
        resumo = rodar_fila(f, c)
        definitivos = [i for i in f.itens() if i["estado"] == "erro"]
        self.assertTrue(definitivos)
        for i in definitivos:
            self.assertEqual(i["tentativas"], 3)
            self.assertEqual(c.chamadas_por_numero[i["numero"]], 3)
            self.assertIn(i["erro"]["codigo"], fila.TRANSITORIOS)
        self.assertEqual(resumo["pendente"] + resumo["coletando"], 0)
        self.assertEqual(resumo["erro_definitivo"], len(definitivos))

    def test_captcha_e_segredo_nao_travam_o_resto(self):
        forcados = {NUMEROS[3]: "captcha", NUMEROS[10]: "segredo", NUMEROS[11]: "nao_encontrado", NUMEROS[50]: "captcha"}
        c = simulado(falhar_em=forcados)
        f = self.fila()
        f.enfileirar(NUMEROS, modo="imediato", profundidade="rapido")
        resumo = rodar_fila(f, c)
        self.assertEqual((resumo["manual"], resumo["coletado"]), (4, 196))
        for n, codigo in forcados.items():
            self.assertEqual((f.item(n)["estado"], f.item(n)["erro"]["codigo"]), ("manual", codigo))
            self.assertEqual(c.chamadas_por_numero[n], 1)

    def test_tempo_total_razoavel(self):
        import time
        c = simulado(taxa=0.2)
        f = Fila(self.proj["slug"], pausa_s=(0, 0), janelas=[], espera_base_s=0)    # relógio e sono reais
        f.enfileirar(NUMEROS, modo="imediato", profundidade="rapido")
        t0 = time.time()
        resumo = rodar_fila(f, c)
        self.assertEqual(resumo["pendente"] + resumo["coletando"], 0)
        self.assertLess(time.time() - t0, 60)


# ------------------------------------------------------------------ interrupção e retomada

class TestRetomada(Base):
    def rodar_ate_o_fim(self, c, **kw):
        f = self.fila(tentativas_max=3)
        resumo = rodar_fila(f, c, **kw)
        self.assertEqual((resumo["pendente"], resumo["coletando"]), (0, 0))
        return f, resumo

    def cenario(self, interromper, numeros=NUMEROS[:60]):
        """Roda com uma queda no ponto dado por `interromper(coletor) -> (kwargs de rodar_fila, coletor)`, retoma com
        OUTRA instância da fila e confere que nada `coletado` antes da queda foi coletado de novo."""
        c = simulado(taxa=0.15)
        f = self.fila(tentativas_max=3)
        f.enfileirar(numeros, modo="imediato", profundidade="rapido")
        kw, coletor = interromper(c)
        with self.assertRaises(Queda):
            rodar_fila(f, coletor, **kw)
        antes = {i["numero"] for i in self.fila().itens() if i["estado"] == "coletado"}
        chamadas_antes = {n: c.chamadas_por_numero[n] for n in antes}
        self.assertLess(len(antes), len(numeros))
        f2, resumo = self.rodar_ate_o_fim(c)
        self.assertEqual(resumo["total"], len(numeros))
        for n in antes:
            self.assertEqual(c.chamadas_por_numero[n], chamadas_antes[n], f"{n} foi coletado de novo")
            self.assertEqual(f2.item(n)["estado"], "coletado")
        # o desfecho final é o mesmo de uma rodada sem queda: coletado = sem falha permanente
        for n in numeros:
            permanente = c.codigo_de_falha_previsto(n) in fila.PERMANENTES
            self.assertEqual(f2.item(n)["estado"], "manual" if permanente else "coletado", n)
        return f2, antes

    def test_queda_antes_do_coletor_responder(self):
        def interromper(c):
            def antes(n, p):
                if n == 7:
                    raise Queda()
            return {}, Embrulho(c, antes=antes)
        f, antes = self.cenario(interromper)
        self.assertLess(len(antes), 7)

    def test_queda_depois_do_coletor_e_antes_de_gravar_o_estado(self):
        def interromper(c):
            def depois(n, p, r):
                if n == 20:
                    raise Queda()
            return {}, Embrulho(c, depois=depois)
        self.cenario(interromper)

    def test_queda_na_transicao_para_coletando(self):
        def interromper(c):
            def progresso(r):
                if r["evento"] == "coletando" and r["coletado"] == 12:
                    raise Queda()
            return {"ao_progresso": progresso}, c
        f, antes = self.cenario(interromper)
        self.assertGreaterEqual(len(antes), 12)

    def test_queda_logo_depois_de_coletado(self):
        def interromper(c):
            def progresso(r):
                if r["evento"] == "coletado" and r["coletado"] == 30:
                    raise Queda()
            return {"ao_progresso": progresso}, c
        f, antes = self.cenario(interromper)
        self.assertGreaterEqual(len(antes), 30)

    def test_queda_ao_gravar_o_resultado(self):
        def interromper(c):
            contador = []

            def gravar(item, resultado):
                contador.append(1)
                if len(contador) == 50:
                    raise Queda()
            return {"ao_resultado": gravar}, c
        self.cenario(interromper)

    def test_varias_quedas_seguidas_ate_terminar(self):
        numeros = NUMEROS[:60]
        c = simulado(taxa=0.15)
        f = self.fila(tentativas_max=3)
        f.enfileirar(numeros, modo="imediato", profundidade="rapido")
        quedas = 0
        while True:
            contador = []

            def antes(n, p):
                contador.append(1)
                if len(contador) == 9:
                    raise Queda()
            try:
                rodar_fila(self.fila(tentativas_max=3), Embrulho(c, antes=antes))
                break
            except Queda:
                quedas += 1
            self.assertLess(quedas, 40)
        self.assertGreaterEqual(quedas, 5)
        final = self.fila()
        self.assertEqual(final.resumo()["pendente"] + final.resumo()["coletando"], 0)
        for n in numeros:
            if final.item(n)["estado"] == "coletado":
                previsto = c.codigo_de_falha_previsto(n)
                # uma chamada, mais a repetição do erro transitório, mais no máximo a que a queda interrompeu
                self.assertLessEqual(c.chamadas_por_numero[n], 1 + (1 if previsto else 0) + 1, n)

    def test_estado_nunca_fica_pela_metade(self):
        """Se a troca atômica falhar, o arquivo continua íntegro e com o estado anterior."""
        f = self.fila()
        f.enfileirar(NUMEROS[:10], modo="imediato")
        i = f.proximo()
        f.marcar(i["numero"], "coletado")
        arquivo = Path(self.proj["data"]) / "fila.json"
        antes = arquivo.read_text(encoding="utf-8")
        with mock.patch("comum.os.replace", side_effect=OSError("queda")):
            with self.assertRaises(OSError):
                f.proximo()
        self.assertEqual(arquivo.read_text(encoding="utf-8"), antes)
        self.assertEqual(self.fila().resumo()["coletado"], 1)
        self.assertEqual(self.fila().resumo()["coletando"], 0)

    def test_recuperar_devolve_o_coletando_sem_gastar_tentativa(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:2], modo="imediato")
        i = f.proximo()
        self.assertEqual(f.item(i["numero"])["tentativas"], 1)
        self.assertEqual(f.recuperar_interrompidos(), [i["numero"]])
        self.assertEqual((f.item(i["numero"])["estado"], f.item(i["numero"])["tentativas"]), ("pendente", 0))

    def test_duas_rodadas_ao_mesmo_tempo_sao_recusadas(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:2], modo="imediato")
        with f._transacao() as d:
            d["executor"] = {"pid": os.getppid(), "desde": "2026-10-07T21:00:00"}    # outro processo vivo
        with self.assertRaises(RuntimeError):
            rodar_fila(f, simulado())
        with f._transacao() as d:
            d["executor"] = {"pid": 2 ** 22 + 12345, "desde": "2026-10-07T21:00:00"}  # processo morto: rodada travada de antes
        rodar_fila(f, simulado())
        self.assertEqual(f.resumo()["coletado"], 2)


# ------------------------------------------------------------------ pausar, retomar, parar

class TestControle(Base):
    def test_parar_com_seguranca_termina_o_corrente_e_grava(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:20], modo="imediato", profundidade="rapido")
        outra = self.fila()                    # como o painel: outra instância, mesmo arquivo

        def progresso(r):
            if r["evento"] == "coletando" and r["coletado"] == 4:
                outra.parar_com_seguranca()    # pedido no meio do 5º processo
        c = simulado()
        resumo = rodar_fila(f, c, ao_progresso=progresso)
        self.assertEqual((resumo["coletado"], resumo["pendente"], resumo["coletando"]), (5, 15, 0))
        self.assertEqual(c.chamadas, 5)
        retomada = rodar_fila(self.fila(), c)
        self.assertEqual(retomada["coletado"], 20)
        self.assertEqual(c.chamadas, 20, "a retomada não repete ninguém")

    def test_pausar_e_retomar(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:6], modo="imediato", profundidade="rapido")
        f.pausar()
        self.assertIsNone(f.proximo())
        self.assertTrue(f.resumo()["pausada"])
        resumo = rodar_fila(f, simulado(), esperar=False)
        self.assertEqual(resumo["coletado"], 0)
        f.retomar()
        c = simulado()

        def progresso(r):
            if r["evento"] == "coletado" and r["coletado"] == 2:
                f.pausar()
        resumo = rodar_fila(f, c, ao_progresso=progresso, esperar=False)
        self.assertEqual((resumo["coletado"], resumo["pausada"]), (2, True))
        f.retomar()
        self.assertEqual(rodar_fila(f, c)["coletado"], 6)

    def test_pausada_com_espera_aguarda_o_retomar(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:3], modo="imediato", profundidade="rapido")
        f.pausar()
        contagem = []

        def dormir(s):
            contagem.append(s)
            if len(contagem) == 3:
                f.retomar()
            self.rel.avancar(s)
        f.dormir = dormir
        self.assertEqual(rodar_fila(f, simulado())["coletado"], 3)
        self.assertGreaterEqual(len(contagem), 3)

    def test_max_processos(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:10], modo="imediato", profundidade="rapido")
        self.assertEqual(rodar_fila(f, simulado(), max_processos=4)["coletado"], 4)


# ------------------------------------------------------------------ modos e janelas

class TestJanelas(Base):
    def test_funcoes_de_janela(self):
        j = fila.parse_janelas(["20:00-06:00", ("12:00", "13:00")])
        dia = datetime.datetime(2026, 10, 7)
        for hora, dentro in ((20, True), (23, True), (3, True), (6, False), (9, False), (12, True), (13, False), (19, False)):
            self.assertEqual(fila.dentro_da_janela(j, dia.replace(hour=hora)), dentro, hora)
        self.assertEqual(fila.proxima_abertura(j, dia.replace(hour=15)), dia.replace(hour=20))
        self.assertEqual(fila.proxima_abertura(j, dia.replace(hour=9)), dia.replace(hour=12))
        self.assertEqual(fila.proxima_abertura(j, dia.replace(hour=22)), dia.replace(hour=22))
        self.assertEqual(fila.proxima_abertura(fila.parse_janelas(["20:00-06:00"]), dia.replace(hour=7)), dia.replace(hour=20))
        self.assertTrue(fila.dentro_da_janela([], dia.replace(hour=11)))
        for ruim in ("noite", "25:00-26:00", "20h-6h"):
            with self.assertRaises(ValueError):
                fila.parse_janelas([ruim])

    def test_continuo_so_roda_dentro_da_janela_e_retoma_no_dia_seguinte(self):
        self.rel = Relogio(datetime.datetime(2026, 10, 7, 15, 0, 0))     # tarde: janela fechada
        f = self.fila(janelas=["20:00-06:00"], pausa_s=(1800, 1800))     # 30 min entre processos: 20 por noite
        f.enfileirar(NUMEROS[:30], modo="continuo", profundidade="rapido")
        momentos = []
        c = Embrulho(simulado(), antes=lambda n, p: momentos.append(self.rel.agora()))
        sem_esperar = rodar_fila(f, c, esperar=False)
        self.assertEqual((sem_esperar["coletado"], len(momentos)), (0, 0), "fora da janela e sem esperar: nada roda")
        self.assertAlmostEqual(f.espera_s(), 5 * 3600, delta=2)
        resumo = rodar_fila(f, c)
        self.assertEqual(resumo["coletado"], 30)
        self.assertEqual(momentos[0], datetime.datetime(2026, 10, 7, 20, 0, 0))
        self.assertTrue(all(fila.dentro_da_janela(f.janelas, m) for m in momentos))
        primeira_noite = [m for m in momentos if m < datetime.datetime(2026, 10, 8, 12)]
        segunda_noite = [m for m in momentos if m >= datetime.datetime(2026, 10, 8, 12)]
        self.assertEqual((len(primeira_noite), len(segunda_noite)), (20, 10))
        self.assertEqual(segunda_noite[0], datetime.datetime(2026, 10, 8, 20, 0, 0))

    def test_imediato_ignora_a_janela(self):
        self.rel = Relogio(datetime.datetime(2026, 10, 7, 15, 0, 0))
        f = self.fila(janelas=["20:00-06:00"])
        f.enfileirar(NUMEROS[:3], modo="imediato", profundidade="rapido")
        f.enfileirar(NUMEROS[3:6], modo="continuo", profundidade="rapido")
        self.assertEqual(rodar_fila(f, simulado(), esperar=False)["coletado"], 3)
        self.assertEqual(f.resumo()["pendente"], 3)

    def test_janela_vem_do_config(self):
        cfg = {**comum.config(), "coleta": {**comum.config()["coleta"], "janelas_continuo": ["22:00-23:00"]}}
        with mock.patch.object(comum, "config", return_value=cfg):
            f = Fila(self.proj["slug"], relogio=self.rel.agora)
        self.assertEqual(f.janelas[0][0], datetime.time(22, 0))


# ------------------------------------------------------------------ estimativa

class TestEstimativa(Base):
    def test_padrao_conservador_sem_medida_e_converge_com_a_media_medida(self):
        f = self.fila(pausa_s=(3, 5), sorteio=lambda a, b: (a + b) / 2)
        f.enfileirar(NUMEROS[:40], modo="imediato", profundidade="rapido")
        self.assertFalse(f.resumo()["medido"])
        self.assertEqual(f.resumo()["estimativa_s"], 40 * (120 + 4))
        self.assertEqual(f.estimativa(), 40 * 124)
        self.assertEqual(f.estimativa(10), 10 * 124)
        c = Embrulho(simulado(), self.rel, duracao=30)
        rodar_fila(f, c, max_processos=5)
        self.assertTrue(f.medido())
        self.assertAlmostEqual(f.media_s(), 30)
        self.assertEqual(f.resumo()["estimativa_s"], 35 * (30 + 4))
        # o tempo real passa a ser outro: a média móvel acompanha (só as últimas 20 medições)
        c.duracao = lambda numero: 50
        rodar_fila(f, c, max_processos=20)
        self.assertAlmostEqual(f.media_s(), 50)
        c.duracao = lambda numero: 10
        rodar_fila(f, c, max_processos=10)
        esperadas = [50.0] * 10 + [10.0] * 10
        self.assertAlmostEqual(f.media_s(), sum(esperadas) / 20)
        self.assertEqual(f.resumo()["estimativa_s"], int(round(5 * (sum(esperadas) / 20 + 4))))

    def test_medida_so_conta_processos_coletados(self):
        f = self.fila(pausa_s=(0, 0))
        f.enfileirar(NUMEROS[:4], modo="imediato", profundidade="rapido")
        c = Embrulho(simulado(falhar_em={NUMEROS[0]: "captcha", NUMEROS[1]: "segredo"}), self.rel, duracao=7)
        rodar_fila(f, c)
        self.assertEqual(f.media_s(), 7)
        self.assertEqual(len(f._ler()["medicoes"]), 2)

    def test_estimativa_acompanha_o_que_falta(self):
        f = self.fila(pausa_s=(0, 0))
        f.enfileirar(NUMEROS[:10], modo="imediato", profundidade="rapido")
        rodar_fila(f, Embrulho(simulado(), self.rel, duracao=10), max_processos=4)
        self.assertEqual(f.resumo()["estimativa_s"], 60)
        rodar_fila(f, simulado())
        self.assertEqual(f.resumo()["estimativa_s"], 0)

    def test_estimativa_por_cliente(self):
        f = self.fila(pausa_s=(0, 0))
        f.enfileirar(NUMEROS[:40], modo="imediato")
        cliente = ficha.obter(FICHAS[0], "cliente")
        n = sum(1 for i in f.itens() if i["cliente"] == cliente)
        self.assertEqual(f.resumo(cliente=cliente)["estimativa_s"], n * 120)


# ------------------------------------------------------------------ captcha de TRT

class TestCaptchaTRT(Base):
    def test_aviso_de_captcha_uma_vez_por_trt_e_por_rodada(self):
        trt3, trt9 = numeros_do("TRT3", 4), numeros_do("TRT9", 3)
        forcados = {trt3[0]: "captcha", trt3[1]: "captcha", trt9[0]: "captcha"}
        f = self.fila(captcha_limite=10)
        f.enfileirar(trt3 + trt9, modo="imediato", profundidade="rapido")
        avisos = []
        rodar_fila(f, simulado(falhar_em=forcados), ao_progresso=lambda r: avisos.append(r) if r["evento"] == "captcha" else None)
        self.assertEqual(sorted(a["tribunal"] for a in avisos), ["TRT3", "TRT9"])
        self.assertEqual(f.resumo()["manual"], 3)
        self.assertEqual(f.resumo()["coletado"], 4)

    def test_captchas_seguidos_mandam_o_resto_do_trt_para_manual_sem_travar_os_outros(self):
        trt3, trt9, outros = numeros_do("TRT3", 8), numeros_do("TRT9", 3), numeros_do("TJSP", 3)
        forcados = {n: "captcha" for n in trt3[:3]}
        c = simulado(falhar_em=forcados)
        f = self.fila(captcha_limite=3)
        f.enfileirar(trt9[:1] + trt3 + trt9[1:] + outros, modo="imediato", profundidade="rapido")
        rodar_fila(f, c)
        for n in trt3:
            self.assertEqual(f.item(n)["estado"], "manual", n)
        for n in trt3[3:]:
            self.assertEqual(c.chamadas_por_numero[n], 0, "o resto do TRT nem foi tentado")
            self.assertIn("Captcha", f.item(n)["motivo"])
        for n in trt9 + outros:
            self.assertEqual(f.item(n)["estado"], "coletado")
        # na rodada seguinte o usuário reabre e, resolvido o captcha, coleta
        f.reabrir(trt3[3:])
        rodar_fila(f, c)
        self.assertEqual(f.resumo()["coletado"], len(trt9 + outros + trt3[3:]))

    def test_sucesso_no_meio_zera_a_contagem(self):
        trt3 = numeros_do("TRT3", 7)
        forcados = {trt3[0]: "captcha", trt3[1]: "captcha", trt3[3]: "captcha", trt3[4]: "captcha"}
        f = self.fila(captcha_limite=3)
        f.enfileirar(trt3, modo="imediato", profundidade="rapido")
        rodar_fila(f, simulado(falhar_em=forcados))
        self.assertEqual(f.resumo()["coletado"], 3)
        self.assertEqual(f.resumo()["manual"], 4)


# ------------------------------------------------------------------ cobertura

class TestCobertura(Base):
    def test_cobertura_por_tribunal(self):
        so = ["TJSP", "TJBA"]
        c = simulado(taxa=0.3, tentativas_transitorias=99)
        f = self.fila(tentativas_max=3, tribunais_so_djen=so)
        f.enfileirar(NUMEROS, modo="imediato", profundidade="rapido")
        rodar_fila(f, c)
        esperado = {}
        for ficha_ in FICHAS:
            t, n = ficha_["tribunal"], ficha_["numero"]
            chave = "so_djen" if t in so else ("manual" if c.codigo_de_falha_previsto(n) else "coletado")
            esperado.setdefault(t, {"coletado": 0, "so_djen": 0, "manual": 0})[chave] += 1
        self.assertEqual(fila.cobertura(self.proj["slug"]), dict(sorted(esperado.items())))
        self.assertEqual(sum(sum(v.values()) for v in fila.cobertura(self.proj["slug"]).values()), 200)
        self.assertTrue(any(v["so_djen"] for v in esperado.values()) and any(v["manual"] for v in esperado.values()))

    def test_sem_fila_e_pendentes_nao_contam(self):
        self.assertEqual(fila.cobertura(self.proj["slug"]), {})
        f = self.fila()
        f.enfileirar(NUMEROS[:5], modo="imediato")
        self.assertEqual(fila.cobertura(self.proj["slug"]), {})
        i = f.proximo()
        f.marcar(i["numero"], "coletado")
        self.assertEqual(sum(v["coletado"] for v in fila.cobertura(self.proj["slug"]).values()), 1)

    def test_aceita_o_dict_do_projeto_de_teste(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:3], modo="imediato")
        rodar_fila(f, simulado())
        self.assertEqual(fila.cobertura(self.proj), fila.cobertura(self.proj["slug"]))


# ------------------------------------------------------------------ progresso

class TestProgresso(Base):
    def test_ao_progresso_a_cada_transicao_com_resumo(self):
        f = self.fila()
        f.enfileirar(NUMEROS[:3], modo="imediato", profundidade="rapido")
        vistos = []
        rodar_fila(f, simulado(falhar_em={NUMEROS[1]: "segredo"}), ao_progresso=vistos.append)
        eventos = [(v["evento"], v.get("numero")) for v in vistos]
        self.assertEqual(eventos, [("coletando", NUMEROS[0]), ("coletado", NUMEROS[0]),
                                   ("coletando", NUMEROS[1]), ("manual", NUMEROS[1]),
                                   ("coletando", NUMEROS[2]), ("coletado", NUMEROS[2]), ("fim", None)])
        for v in vistos:
            self.assertTrue({"total", "pendente", "coletando", "coletado", "erro", "manual", "estimativa_s"} <= set(v))
        self.assertEqual((vistos[-1]["coletado"], vistos[-1]["manual"]), (2, 1))

    def test_aviso_de_espera_quando_a_janela_esta_fechada(self):
        self.rel = Relogio(datetime.datetime(2026, 10, 7, 12, 0, 0))
        f = self.fila(janelas=["20:00-06:00"])
        f.enfileirar(NUMEROS[:1], modo="continuo", profundidade="rapido")
        vistos = []
        rodar_fila(f, simulado(), ao_progresso=vistos.append)
        espera = [v for v in vistos if v["evento"] == "espera"]
        self.assertEqual(len(espera), 1)
        self.assertAlmostEqual(espera[0]["espera_s"], 8 * 3600, delta=2)

    def test_resultado_entregue_a_quem_grava(self):
        recebidos = {}
        f = self.fila()
        f.enfileirar(NUMEROS[:3], modo="imediato", profundidade="padrao", desde="2025-01-01")
        c = simulado()
        rodar_fila(f, c, ao_resultado=lambda item, r: recebidos.update({item["numero"]: (item["desde"], r)}))
        self.assertEqual(set(recebidos), set(NUMEROS[:3]))
        desde, r = recebidos[NUMEROS[0]]
        self.assertEqual(desde, "2025-01-01")
        self.assertTrue(r["movimentos"])
        self.assertEqual(c.registro[0][1:], ("padrao", "2025-01-01"))        # profundidade e `desde` chegam ao coletor


# ------------------------------------------------------------------ adaptador real (só o que dá para testar aqui)

class TestColetorReal(unittest.TestCase):
    def test_importacao(self):
        problemas = fila.verificar_importacao()
        if problemas:
            self.skipTest("ambiente sem dependências do coletor real: " + "; ".join(problemas))
        c = fila.ColetorReal()          # construir não abre navegador nem rede
        self.assertIsNone(c._contexto)
        self.assertTrue(callable(c.coletar))

    def test_classificar_erro_com_as_mensagens_do_coletor_e_do_trt(self):
        casos = {
            "Captcha do TRT não resolvido a tempo.": "captcha",
            "Processo em segredo de justiça: a consulta processual não mostra os autos.": "segredo",
            "Processo não encontrado na consulta do jus.br (conferir manualmente).": "nao_encontrado",
            "O TRT não reconheceu o número do processo.": "nao_encontrado",
            "Login no jus.br não concluído a tempo.": "sessao_expirada",
            "Os autos não chegaram (diagnóstico salvo).": "outro",
            "Nenhuma tramitação abriu (diagnóstico salvo).": "outro",
            "Acesso restrito do TRT não abriu a consulta.": "outro",
            "Target page, context or browser has been closed": "sessao_expirada",
        }
        for texto, codigo in casos.items():
            self.assertEqual(fila.classificar_erro(RuntimeError(texto))["codigo"], codigo, texto)

        class TimeoutError(Exception):    # o do Playwright tem este nome
            pass
        self.assertEqual(fila.classificar_erro(TimeoutError("Timeout 30000ms exceeded."))["codigo"], "timeout")
        self.assertEqual(fila.classificar_erro(ValueError(""))["codigo"], "outro")

    def test_eventos_para_resultado(self):
        eventos = [
            {"id": "a", "tipo_evento": "movimento", "data": "06/08/2026", "titulo": "Conclusos para sentença",
             "chave": "06/08/2026|Conclusos para sentença|0", "grau": None},
            {"id": "b", "tipo_evento": "documento", "data": "07/08/2026", "titulo": "123 - Sentença - Sentença",
             "tipo": "Sentença", "arquivo": "/tmp/x.pdf"},
            {"id": "c", "tipo_evento": "documento", "data": "07/08/2026", "titulo": "só print", "tipo": "Decisão", "arquivo": None},
            {"id": "d", "tipo_evento": "movimento", "data": "sem data", "titulo": "lixo"},
        ]
        movimentos, documentos = fila.eventos_para_resultado(eventos)
        self.assertEqual(movimentos, [{"data": "2026-08-06", "texto": "Conclusos para sentença", "grau": None,
                                       "chave": "06/08/2026|Conclusos para sentença|0"}])
        self.assertEqual(documentos, [{"nome": "123 - Sentença - Sentença", "tipo": "Sentença", "data": "2026-08-07", "caminho": "/tmp/x.pdf"}])

    def test_coletar_traduz_e_grava_com_o_coletor_substituido(self):
        """O adaptador com `coletor.coletar_processo` trocado por um falso (sem navegador, sem rede)."""
        import coletor
        n = NUMEROS[0]
        chamadas = []

        def falso(context, proc, estado, lista, historico, cota, desde=None, relato=None):
            chamadas.append((proc, historico, cota, desde))
            lista.append({"id": f"{n}:m1", "tipo_evento": "movimento", "numero": n, "data": "01/10/2026",
                          "titulo": "Juntada de petição", "chave": "01/10/2026|Juntada de petição|0", "grau": None,
                          "status": "coletado"})
            estado[n] = {"ultima_coleta": "x"}
            if proc["cliente"] == "falha":
                raise RuntimeError("Captcha do TRT não resolvido a tempo.")
            return 0
        with ficticio.projeto_de_teste(FICHAS[:2]):
            real = fila.ColetorReal(historico=2)
            real._contexto = object()          # finge navegador já aberto
            with mock.patch.object(coletor, "coletar_processo", side_effect=falso):
                r = real.coletar({"numero": n, "cliente": "Cliente X"}, "rapido", "2026-09-18")
                self.assertIsNone(r["erro"])
                self.assertEqual(r["movimentos"][0]["data"], "2026-10-01")
                self.assertEqual(chamadas[0][1:], (2, 0, datetime.date(2026, 9, 18)))     # rápido = cota 0; `desde` virou date
                self.assertEqual(r["capa"], {})
                self.assertEqual(len(comum.eventos()), 1)
                self.assertIn(n, comum.load_json(comum.ESTADO_FILE, {}))
                r = real.coletar({"numero": n, "cliente": "falha"}, "completo", None)
                self.assertEqual(r["erro"]["codigo"], "captcha")
                self.assertEqual(chamadas[1][2], fila.ColetorReal.COTA_COMPLETO)
                self.assertEqual(len(comum.eventos()), 2, "o que já tinha sido lido antes da falha foi guardado")


if __name__ == "__main__":
    unittest.main()
