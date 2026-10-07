"""Coletor simulado: determinismo, filtro `desde`, taxa de falha, profundidade, contagem de chamadas e
documentos legíveis pelo extrair.py.

    python3 -m unittest tests/test_simulado.py -v
"""
import hashlib
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import ficha  # noqa: E402
import ficticio  # noqa: E402
import extrair  # noqa: E402
import simulado  # noqa: E402
from simulado import ColetorSimulado  # noqa: E402

FICHAS = ficticio.gerar_carteira(200)
CHAVES = {"capa", "movimentos", "documentos", "erro"}


def novo(**kw):
    kw.setdefault("pasta", tempfile.mkdtemp(prefix="simulado-teste-", dir=isolamento.TMP))
    kw.setdefault("taxa_falha", 0.0)
    return ColetorSimulado(FICHAS, **kw)


def impressao(resultado):
    """O resultado sem os caminhos (a pasta muda), mas com o conteúdo dos arquivos."""
    docs = [{**d, "caminho": hashlib.sha1(Path(d["caminho"]).read_bytes()).hexdigest()} for d in resultado["documentos"]]
    return {**resultado, "documentos": docs}


class TestContrato(unittest.TestCase):
    def test_forma_do_resultado(self):
        r = novo().coletar({"numero": FICHAS[0]["numero"]}, "completo", None)
        self.assertEqual(set(r), CHAVES)
        self.assertIsNone(r["erro"])
        for m in r["movimentos"]:
            self.assertEqual(set(m), {"data", "texto", "grau", "chave"})
            self.assertTrue(ficha.data(m["data"]) and m["texto"] and m["chave"])
        for d in r["documentos"]:
            self.assertEqual(set(d), {"nome", "tipo", "data", "caminho"})
            self.assertTrue(Path(d["caminho"]).is_file() and ficha.data(d["data"]))
        self.assertTrue(set(r["capa"]) <= set(ficha.CAMPOS), "capa só com campos de ficha.CAMPOS")
        for grupo in {ficha.CAMPOS[c][1] for c in r["capa"]}:
            self.assertIn(grupo, ("capa", "partes", "situacao"))

    def test_capa_coerente_com_a_ficha(self):
        c = novo()
        for f in FICHAS[:40]:
            r = c.coletar(f, "rapido", None)
            for campo, valor in r["capa"].items():
                self.assertEqual(valor, ficha.obter(f, campo), campo)
            self.assertEqual(r["capa"]["momento_atual"], ficha.obter(f, "momento_atual"))
            self.assertEqual(r["movimentos"][-1]["data"], ficha.obter(f, "ultimo_andamento"), "último movimento = último andamento")
            self.assertEqual(r["movimentos"][0]["data"], ficha.obter(f, "data_ajuizamento"))

    def test_movimentos_em_ordem_e_chaves_unicas(self):
        c = novo()
        for f in FICHAS[:60]:
            r = c.coletar(f, "rapido", None)
            datas = [m["data"] for m in r["movimentos"]]
            self.assertEqual(datas, sorted(datas))
            chaves = [m["chave"] for m in r["movimentos"]]
            self.assertEqual(len(chaves), len(set(chaves)))

    def test_movimentos_no_texto_do_tribunal_sao_traduzidos_pelas_regras(self):
        import traduzir
        c, traduzidos, total = novo(), 0, 0
        for f in FICHAS[:60]:
            for m in c.coletar(f, "rapido", None)["movimentos"]:
                frase, _, _ = traduzir.traduzir_movimento(m["texto"])
                total += 1
                traduzidos += frase is not None
        self.assertGreater(traduzidos / total, 0.85, "a maioria dos movimentos casa com movimentos.json")
        self.assertLess(traduzidos, total, "alguns ficam sem regra (caminho do alerta na revisão)")

    def test_numero_desconhecido_nao_encontrado(self):
        r = novo().coletar({"numero": ficticio.numero_ficticio(999_000)}, "padrao", None)
        self.assertEqual(r["erro"]["codigo"], "nao_encontrado")
        self.assertEqual((r["capa"], r["movimentos"], r["documentos"]), ({}, [], []))

    def test_processo_vinculado_tem_coleta_propria(self):
        c = novo()
        f = next(x for x in FICHAS if x["vinculados"])
        v = f["vinculados"][0]
        r = c.coletar({"numero": v["numero"]}, "completo", None)
        self.assertIsNone(r["erro"])
        self.assertEqual(len(r["movimentos"]) > 0 and r["capa"]["fase"], "Recurso")
        self.assertTrue(r["documentos"])

    def test_profundidade_invalida_e_erro_de_programacao(self):
        with self.assertRaises(ValueError):
            novo().coletar({"numero": FICHAS[0]["numero"]}, "profundo", None)


class TestDeterminismo(unittest.TestCase):
    def test_mesma_semente_mesmo_resultado_em_qualquer_ordem(self):
        a, b = novo(semente=7, taxa_falha=0.2), novo(semente=7, taxa_falha=0.2)
        amostra = FICHAS[:50]
        ra = {f["numero"]: impressao(a.coletar(f, "completo", "2025-06-01")) for f in amostra}
        rb = {f["numero"]: impressao(b.coletar(f, "completo", "2025-06-01")) for f in reversed(amostra)}
        self.assertEqual(ra, rb)

    def test_semente_diferente_muda_acaso_mas_nao_o_roteiro(self):
        a, b = novo(semente=1, taxa_falha=0.3), novo(semente=2, taxa_falha=0.3)
        falhas_a = {f["numero"] for f in FICHAS if a.coletar(f, "rapido", None)["erro"]}
        falhas_b = {f["numero"] for f in FICHAS if b.coletar(f, "rapido", None)["erro"]}
        self.assertNotEqual(falhas_a, falhas_b)

    def test_repetir_a_chamada_devolve_o_mesmo(self):
        c = novo()
        f = FICHAS[3]
        self.assertEqual(impressao(c.coletar(f, "completo", None)), impressao(c.coletar(f, "completo", None)))


class TestDesde(unittest.TestCase):
    def test_filtra_movimentos_e_documentos_anteriores(self):
        c = novo()
        f = next(x for x in FICHAS if ficha.obter(x, "momento_atual") == "TRÂNSITO EM JULGADO")
        tudo = c.coletar(f, "completo", None)
        meio = tudo["movimentos"][len(tudo["movimentos"]) // 2]["data"]
        r = c.coletar(f, "completo", meio)
        self.assertTrue(r["movimentos"] and len(r["movimentos"]) < len(tudo["movimentos"]))
        self.assertTrue(all(m["data"] > meio for m in r["movimentos"]))
        self.assertTrue(all(d["data"] > meio for d in r["documentos"]))
        self.assertEqual(r["movimentos"], [m for m in tudo["movimentos"] if m["data"] > meio], "chaves estáveis")
        self.assertEqual(r["capa"], tudo["capa"], "a capa vem sempre")
        self.assertLess(len(r["documentos"]), len(tudo["documentos"]))

    def test_desde_no_futuro_nao_devolve_nada_novo(self):
        r = novo().coletar(FICHAS[0], "completo", "2099-01-01")
        self.assertEqual((r["movimentos"], r["documentos"]), ([], []))
        self.assertTrue(r["capa"])

    def test_aceita_data_br_e_iso(self):
        c = novo()
        self.assertEqual(c.coletar(FICHAS[1], "rapido", "01/01/2026"), c.coletar(FICHAS[1], "rapido", "2026-01-01"))


class TestFalhas(unittest.TestCase):
    def test_proporcao_e_codigos(self):
        c = novo(taxa_falha=0.1)
        codigos = Counter((c.coletar(f, "rapido", None)["erro"] or {}).get("codigo") for f in FICHAS)
        falhas = 200 - codigos[None]
        self.assertTrue(8 <= falhas <= 36, codigos)
        self.assertTrue(set(codigos) - {None} <= set(simulado.CODIGOS))
        self.assertGreaterEqual(len(set(codigos) - {None}), 3, "vários códigos de erro aparecem")

    def test_extremos(self):
        self.assertTrue(all(novo(taxa_falha=0).coletar(f, "rapido", None)["erro"] is None for f in FICHAS[:30]))
        r = [novo(taxa_falha=1.0).coletar(f, "rapido", None) for f in FICHAS[:30]]
        self.assertTrue(all(x["erro"] and x["erro"]["mensagem"] for x in r))
        self.assertTrue(all(x["movimentos"] == [] and x["documentos"] == [] for x in r))

    def test_erros_permanentes_e_transitorios(self):
        c = novo(taxa_falha=0.5)
        permanentes = transitorios = 0
        for f in FICHAS:
            n = f["numero"]
            primeiro = c.coletar(f, "rapido", None)["erro"]
            if not primeiro:
                continue
            segundo = c.coletar(f, "rapido", None)["erro"]
            if primeiro["codigo"] in simulado.PERMANENTES:
                permanentes += 1
                self.assertEqual(segundo["codigo"], primeiro["codigo"], "captcha/segredo/não encontrado persistem")
            else:
                transitorios += 1
                self.assertIsNone(segundo, f"{primeiro['codigo']} passa na repetição ({n})")
        self.assertTrue(permanentes and transitorios)

    def test_falhar_em(self):
        a, b = FICHAS[0]["numero"], FICHAS[1]["numero"]
        c = novo(falhar_em={a: "captcha", b: ("timeout", 2)})
        self.assertEqual([c.coletar(a, "rapido", None)["erro"]["codigo"] for _ in range(3)], ["captcha"] * 3)
        self.assertEqual([bool(c.coletar(b, "rapido", None)["erro"]) for _ in range(4)], [True, True, False, False])
        self.assertIsNone(c.coletar(FICHAS[2], "rapido", None)["erro"])

    def test_previsao_de_falha_nao_conta_chamada(self):
        c = novo(taxa_falha=0.3)
        previstos = {f["numero"]: c.codigo_de_falha_previsto(f["numero"]) for f in FICHAS[:40]}
        self.assertEqual(c.chamadas, 0)
        for f in FICHAS[:40]:
            erro = c.coletar(f, "rapido", None)["erro"]
            self.assertEqual(erro and erro["codigo"], previstos[f["numero"]])

    def test_atraso(self):
        with mock.patch("simulado.time.sleep") as dormir:
            novo(atraso_s=0.25).coletar(FICHAS[0], "rapido", None)
        dormir.assert_called_once_with(0.25)


class TestChamadas(unittest.TestCase):
    def test_contagem(self):
        c = novo()
        for f in FICHAS[:10]:
            c.coletar(f, "rapido", None)
        c.coletar(FICHAS[0], "padrao", "2026-01-01")
        self.assertEqual(c.chamadas, 11)
        self.assertEqual(c.chamadas_por_numero[FICHAS[0]["numero"]], 2)
        self.assertEqual(c.chamadas_por_numero[FICHAS[1]["numero"]], 1)
        self.assertEqual(c.registro[-1], (FICHAS[0]["numero"], "padrao", "2026-01-01"))
        self.assertEqual(len(c.registro), 11)


class TestProfundidade(unittest.TestCase):
    def test_rapido_padrao_completo(self):
        c = novo()
        for f in FICHAS[:60]:
            rapido = c.coletar(f, "rapido", None)
            padrao = c.coletar(f, "padrao", None)
            completo = c.coletar(f, "completo", None)
            self.assertEqual(rapido["documentos"], [])
            self.assertEqual(rapido["movimentos"], padrao["movimentos"])
            self.assertTrue(all(d["tipo"] in simulado.TIPOS_CHAVE for d in padrao["documentos"]))
            nomes_padrao = {d["nome"] for d in padrao["documentos"]}
            self.assertTrue(nomes_padrao <= {d["nome"] for d in completo["documentos"]})
            self.assertGreaterEqual(len(completo["documentos"]), len(padrao["documentos"]))
        f = next(x for x in FICHAS if ficha.obter(x, "momento_atual") == "TRÂNSITO EM JULGADO")
        self.assertGreater(len(c.coletar(f, "completo", None)["documentos"]), len(c.coletar(f, "padrao", None)["documentos"]))
        self.assertTrue(c.coletar(f, "padrao", None)["documentos"], "padrão traz os documentos-chave")


class TestDocumentos(unittest.TestCase):
    def test_pdf_minimo_legivel_por_pypdf_e_pelo_extrair(self):
        from pypdf import PdfReader
        texto = "Sentença: JULGO PROCEDENTE o pedido, condenação ao pagamento de R$ 1.234,56 (ação nº 1).\n" * 8
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "x.pdf"
            arq.write_bytes(simulado.pdf_minimo(texto, linhas_por_pagina=10, largura=50))
            leitor = PdfReader(str(arq))
            self.assertGreater(len(leitor.pages), 1)
            lido = " ".join(" ".join(p.extract_text().split()) for p in leitor.pages)
            self.assertIn("Sentença: JULGO PROCEDENTE", lido)
            self.assertIn("R$ 1.234,56", lido)
            self.assertIn("ação", extrair._texto_pdf_python(arq))
            self.assertIn("JULGO PROCEDENTE", extrair.extrair_arquivo(arq)[0])

    def test_documentos_gerados_sao_lidos_pelo_extrair(self):
        c = novo()
        formatos, lidos = Counter(), 0
        for f in FICHAS[:40]:
            for d in c.coletar(f, "completo", None)["documentos"]:
                texto, origem = extrair.extrair_arquivo(d["caminho"])
                formatos[Path(d["caminho"]).suffix] += 1
                self.assertIn(origem, ("html", "pdf"), f"PDF digitalizado? {d['nome']}")
                self.assertIn(f["numero"], texto)
                self.assertGreater(len(texto), 200)
                self.assertIn(d["tipo"].upper(), texto.upper())
                self.assertRegex(d["nome"], r"^\d+ - .+ - .+\.(pdf|html)$")
                lidos += 1
        self.assertEqual(set(formatos), {".pdf", ".html"})
        self.assertGreater(lidos, 100)

    def test_nome_do_documento_e_reconhecido_pelo_traduzir(self):
        import traduzir
        for d in novo().coletar(FICHAS[2], "completo", None)["documentos"]:
            partes = traduzir.separar_nome_documento(d["nome"])
            self.assertEqual(partes["tipo"], d["tipo"])
            self.assertEqual(partes["ext"], Path(d["nome"]).suffix[1:])

    def test_cenarios_de_decisao_aparecem_com_o_texto_certo(self):
        """Sentença de procedência, parcial, improcedência, acordo, extinção, decisão desfavorável com prazo e
        decisão que designa audiência: cada uma sai de pelo menos uma ficha da carteira de 200."""
        c = novo()
        esperado = {"procedência": "JULGO PROCEDENTE o pedido", "parcial": "JULGO PARCIALMENTE PROCEDENTES",
                    "improcedência": "JULGO IMPROCEDENTE", "acordo": "HOMOLOGO o acordo",
                    "extinção": "JULGO EXTINTO o processo, sem resolução do mérito", "prazo": "no prazo de",
                    "audiência": "DESIGNO audiência de conciliação"}
        achados = Counter()
        for f in FICHAS:
            for d in c.coletar(f, "padrao", None)["documentos"]:
                texto = extrair.extrair_arquivo(d["caminho"])[0]
                for nome, trecho in esperado.items():
                    if trecho in texto:
                        achados[nome] += 1
                if "no prazo de" in texto and d["tipo"] == "Decisão" and ("DEFIRO" in texto or "INDEFIRO" in texto):
                    achados["prazo_desfavoravel"] += 1
        self.assertEqual(set(esperado) - set(achados), set(), achados)
        self.assertTrue(achados["prazo_desfavoravel"])

    def test_acordo_sem_valor_no_documento_acompanha_a_ficha(self):
        fichas = ficticio.gerar_carteira(200, com_defeitos=True)
        sem_valor = fichas.defeitos["acordo_sem_valor"][0]
        com_valor = next(f for f in fichas if ficha.obter(f, "resultado") == "Acordo" and f["numero"] not in fichas.defeitos["acordo_sem_valor"])
        c = ColetorSimulado(fichas, taxa_falha=0, pasta=tempfile.mkdtemp(dir=isolamento.TMP))

        def acordo(numero):
            docs = c.coletar({"numero": numero}, "padrao", None)["documentos"]
            return next(extrair.extrair_arquivo(d["caminho"])[0] for d in docs if "HOMOLOGO o acordo" in extrair.extrair_arquivo(d["caminho"])[0])

        self.assertNotIn("R$", acordo(sem_valor).split("As partes noticiaram")[1].split("HOMOLOGO")[0])
        self.assertIn("R$", acordo(com_valor["numero"]).split("As partes noticiaram")[1].split("HOMOLOGO")[0])

    def test_documento_nao_traz_nada_alem_de_texto_ficticio(self):
        c = novo()
        for d in c.coletar(FICHAS[5], "completo", None)["documentos"]:
            texto = extrair.extrair_arquivo(d["caminho"])[0]
            self.assertIn("fictício", texto.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
