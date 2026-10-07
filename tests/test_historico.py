"""Retrato mensal da carteira (src/historico.py, WS-11).

    python3 -m unittest tests/test_historico.py -v

Os totais são conferidos contra um cálculo independente, feito direto nos dicionários das fichas (sem usar
`ficha.obter` nem as regras de qualidade.py).
"""
import copy
import json
import random
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import ficha  # noqa: E402
import ficticio  # noqa: E402
import historico  # noqa: E402

NUM = ficticio.numero_ficticio


def valor(f, campo):
    return (f.get("campos", {}).get(campo) or {}).get("valor")


def soma(fichas, campo, quando=lambda f: True):
    return sum((Decimal(valor(f, campo)) for f in fichas if valor(f, campo) not in (None, "") and quando(f)), Decimal(0))


def lido_de(fichas, data_base, arquivo="mes.xlsx", cliente=None):
    """RelatorioLido (CONTRATOS §4) montado das fichas, como um leitor entregaria."""
    return {"formato": "xlsx_b", "arquivo": arquivo, "cliente": cliente, "data_base": data_base,
            "processos": [{"numero": f["numero"], "vinculados": f.get("vinculados", []),
                           "campos": {k: {"valor": c["valor"], "origem": "migrado"} for k, c in f["campos"].items()},
                           "andamentos_texto": "", "ultimo_andamento": None, "origem_no_arquivo": f"linha {i + 2}"}
                          for i, f in enumerate(fichas)],
            "parametros": {}, "colunas_sem_destino": [], "avisos": []}


class TestRetrato(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = ficticio.gerar_carteira(200)
        cls.r = historico.retrato(cls.fichas, "2026-09-18")

    def test_estrutura_do_contrato(self):
        self.assertEqual(set(self.r), {"versao", "data_base", "totais", "por_processo"})
        self.assertEqual(self.r["data_base"], "2026-09-18")
        self.assertEqual(set(self.r["totais"]), {"processos", "ativos", "encerrados", "valor_causa", "valor_estimado",
                                                 "valor_economizado", "valor_economizado_confiavel"})
        self.assertEqual(set(self.r["por_processo"][0]), {"numero", "cliente", "situacao", "momento_atual", "valor_causa",
                                                           "valor_estimado", "resultado", "probabilidade"})
        json.dumps(self.r)

    def test_totais_contra_calculo_independente(self):
        t = self.r["totais"]
        self.assertEqual(t["processos"], 200)
        self.assertEqual(t["ativos"], sum(1 for f in self.fichas if f["ativo"]))
        self.assertEqual(t["encerrados"], sum(1 for f in self.fichas if not f["ativo"]))
        self.assertEqual(t["ativos"] + t["encerrados"], t["processos"])
        self.assertEqual(Decimal(t["valor_causa"]), soma(self.fichas, "valor_causa"))
        self.assertEqual(Decimal(t["valor_estimado"]), soma(self.fichas, "valor_estimado"))
        self.assertEqual(Decimal(t["valor_economizado"]), soma(self.fichas, "valor_economizado"))
        self.assertTrue(all(len(v.split(".")[1]) == 2 for k, v in t.items() if k.startswith("valor")))

    def test_economizado_confiavel_exclui_as_ressalvas(self):
        def confiavel(f):
            autor = valor(f, "polo_cliente") == "ativo"
            obs = (valor(f, "observacoes") or "").lower()
            terceiro, exclusao = "terceiro" in obs, "exclusão da lide" in obs
            res = valor(f, "resultado")
            definido = ((res == "Acordo" and bool(valor(f, "valor_acordo")))
                        or (res in ("Procedente", "Parcialmente procedente") and valor(f, "valor_arbitrado") is not None)
                        or res == "Improcedente")
            return not f["ativo"] and not autor and not terceiro and not exclusao and definido
        esperado = soma(self.fichas, "valor_economizado", confiavel)
        self.assertEqual(Decimal(self.r["totais"]["valor_economizado_confiavel"]), esperado)
        self.assertGreater(esperado, 0)
        self.assertLess(esperado, Decimal(self.r["totais"]["valor_economizado"]), "o geral é maior: tem ressalva dentro")

    def test_linha_por_processo(self):
        por = {p["numero"]: p for p in self.r["por_processo"]}
        self.assertEqual(list(por), sorted(por), "ordenado por número")
        for f in self.fichas:
            p = por[f["numero"]]
            self.assertEqual(p["cliente"], valor(f, "cliente"))
            self.assertEqual(p["momento_atual"], valor(f, "momento_atual"))
            self.assertEqual(p["situacao"], valor(f, "situacao"))
            self.assertEqual(p["valor_causa"], valor(f, "valor_causa"))
            self.assertEqual(p["resultado"], valor(f, "resultado") or "")
            self.assertEqual(p["valor_estimado"], valor(f, "valor_estimado") or "")

    def test_data_base_em_formato_br_e_invalida(self):
        self.assertEqual(historico.retrato(self.fichas[:3], "18/09/2026")["data_base"], "2026-09-18")
        with self.assertRaises(ValueError):
            historico.retrato(self.fichas[:3], "ontem")

    def test_marcador_e_numero_repetido_nao_entram(self):
        lixo = ficha.nova_ficha("0000000-00.0000.0.00.0000")
        r = historico.retrato([*self.fichas[:5], lixo, copy.deepcopy(self.fichas[0])], "2026-09-18")
        self.assertEqual(r["totais"]["processos"], 5)
        self.assertEqual(r, historico.retrato(self.fichas[:5], "2026-09-18"))

    def test_carteira_vazia(self):
        r = historico.retrato([], "2026-09-18")
        self.assertEqual(r["totais"], {"processos": 0, "ativos": 0, "encerrados": 0, "valor_causa": "0.00", "valor_estimado": "0.00",
                                       "valor_economizado": "0.00", "valor_economizado_confiavel": "0.00"})

    def test_item_da_fase_1(self):
        antigo = {"numero": NUM(1), "cliente": "Cliente Exemplo 01 Ltda", "polo_cliente": "passivo", "ativo": True}
        p, = historico.retrato([antigo], "2026-09-18")["por_processo"]
        self.assertEqual((p["cliente"], p["situacao"], p["valor_causa"]), ("Cliente Exemplo 01 Ltda", "Ativo", ""))


class TestGravarECarregar(unittest.TestCase):
    def test_ida_e_volta_no_projeto(self):
        fichas = ficticio.gerar_carteira(40)
        with ficticio.projeto_de_teste(fichas) as proj:
            caminho = historico.gravar_retrato(fichas, "2026-09-18", None)
            self.assertEqual(caminho, proj["data"] / "historico" / "2026-09-18.json")
            serie = historico.carregar(proj["slug"])
            self.assertEqual(list(serie), [historico.retrato(fichas, "2026-09-18")])
            self.assertEqual(serie.avisos, [])
            # as quatro formas de apontar o projeto dão a mesma série
            for destino in (None, proj["slug"], proj["pasta"], proj["data"] / "historico"):
                self.assertEqual(list(historico.carregar(destino)), list(serie), destino)

    def test_mesmo_estado_mesmo_arquivo_byte_a_byte(self):
        fichas = ficticio.gerar_carteira(60, com_defeitos=True)
        with ficticio.projeto_de_teste(fichas) as proj:
            a = historico.gravar_retrato(fichas, "2026-09-18", proj["slug"]).read_bytes()
            embaralhadas = list(fichas)
            random.Random(7).shuffle(embaralhadas)
            b = historico.gravar_retrato(embaralhadas, "18/09/2026", proj["slug"]).read_bytes()
            c = historico.gravar_retrato(copy.deepcopy(list(fichas)), "2026-09-18", proj["slug"]).read_bytes()
            self.assertEqual(a, b)
            self.assertEqual(a, c)
            self.assertEqual(len(list((proj["data"] / "historico").glob("*.json"))), 1, "regravar substitui, não duplica")

    def test_destino_arquivo_e_pasta_avulsa(self):
        fichas = ficticio.gerar_carteira(10)
        pasta = isolamento.TMP / "avulso"
        arq = historico.gravar_retrato(fichas, "2026-01-31", pasta / "meu.json")
        self.assertEqual(arq, pasta / "meu.json")
        self.assertTrue(arq.exists())
        arq2 = historico.gravar_retrato(fichas, "2026-02-28", pasta / "serie")
        self.assertEqual(arq2, pasta / "serie" / "2026-02-28.json")
        self.assertEqual([r["data_base"] for r in historico.carregar(pasta / "serie")], ["2026-02-28"])

    def test_carregar_ordena_por_data_e_pula_arquivo_ruim(self):
        fichas = ficticio.gerar_carteira(10)
        with ficticio.projeto_de_teste(fichas) as proj:
            for d in ("2026-09-18", "2026-07-31", "2026-08-31"):
                historico.gravar_retrato(fichas, d, proj["slug"])
            pasta = proj["data"] / "historico"
            (pasta / "2026-10-31.json").write_text("{ isto não é json", encoding="utf-8")
            (pasta / "2026-11-30.json").write_text('{"data_base": "2026-11-30"}', encoding="utf-8")
            (pasta / "anotacoes.json").write_text("{}", encoding="utf-8")
            serie = historico.carregar(proj["slug"])
            self.assertEqual([r["data_base"] for r in serie], ["2026-07-31", "2026-08-31", "2026-09-18"])
            self.assertEqual(sorted(a["onde"] for a in serie.avisos), ["2026-10-31.json", "2026-11-30.json"])
            self.assertTrue(all(a["codigo"] == "retrato_ilegivel" and a["nivel"] == "atencao" for a in serie.avisos))

    def test_sem_historico_devolve_serie_vazia(self):
        with ficticio.projeto_de_teste([]) as proj:
            serie = historico.carregar(proj["slug"])
            self.assertEqual((list(serie), serie.avisos), ([], []))

    def test_evolucao(self):
        fichas = ficticio.gerar_carteira(10)
        serie = historico.Serie([historico.retrato(fichas, "2026-07-31"), historico.retrato(fichas[:5], "2026-08-31")])
        e = historico.evolucao(serie)
        self.assertEqual([x["data_base"] for x in e], ["2026-07-31", "2026-08-31"])
        self.assertEqual([x["processos"] for x in e], [10, 5])


class TestReconstruir(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = ficticio.gerar_carteira(60)

    def test_um_relatorio_igual_ao_retrato_das_fichas(self):
        serie = historico.reconstruir([lido_de(self.fichas, "2026-09-18")])
        self.assertEqual(list(serie), [historico.retrato(self.fichas, "2026-09-18")])
        self.assertEqual(serie.avisos, [])

    def test_varios_meses_viram_a_serie_em_ordem(self):
        # três relatórios (fora de ordem): a carteira cresce e um processo é encerrado no último mês
        jul = self.fichas[:40]
        ago = self.fichas[:50]
        set_ = copy.deepcopy(self.fichas[:60])
        ativo = next(f for f in set_ if f["ativo"])
        ficha.definir(ativo, "momento_atual", "TRÂNSITO EM JULGADO", "humano", forcar=True)
        ficha.definir(ativo, "situacao", "Encerrado", "humano", forcar=True)
        serie = historico.reconstruir([lido_de(set_, "2026-09-30", "set.xlsx"), lido_de(jul, "2026-07-31", "jul.xlsx"),
                                       lido_de(ago, "2026-08-31", "ago.xlsx")])
        self.assertEqual([r["data_base"] for r in serie], ["2026-07-31", "2026-08-31", "2026-09-30"])
        self.assertEqual([r["totais"]["processos"] for r in serie], [40, 50, 60])
        self.assertEqual(serie[2]["totais"]["encerrados"], sum(1 for f in self.fichas if not f["ativo"]) + 1)
        self.assertEqual(Decimal(serie[0]["totais"]["valor_causa"]), soma(jul, "valor_causa"))
        self.assertEqual(Decimal(serie[2]["totais"]["valor_causa"]), soma(set_, "valor_causa"))
        self.assertEqual(serie.avisos, [])
        e = historico.evolucao(serie)
        self.assertEqual([x["processos"] for x in e], [40, 50, 60])

    def test_ativo_vem_da_situacao_ou_do_momento(self):
        f = copy.deepcopy(self.fichas[0])
        f["campos"].pop("situacao", None)
        f["campos"]["momento_atual"] = {"valor": "PROCESSO ARQUIVADO", "origem": "migrado", "em": "x"}
        r, = historico.reconstruir([lido_de([f], "2026-09-18")])
        self.assertEqual((r["totais"]["ativos"], r["totais"]["encerrados"]), (0, 1))
        self.assertEqual(r["por_processo"][0]["situacao"], "Encerrado")

    def test_relatorio_sem_data_base_e_pulado_com_aviso(self):
        serie = historico.reconstruir([lido_de(self.fichas[:5], None, "sem-data.docx"), lido_de(self.fichas[:5], "2026-09-18")])
        self.assertEqual(len(serie), 1)
        a, = serie.avisos
        self.assertEqual((a["codigo"], a["nivel"], a["onde"]), ("retrato_sem_data_base", "atencao", "sem-data.docx"))

    def test_mesma_data_une_relatorios_e_repetido_vale_o_ultimo(self):
        a, b = self.fichas[:10], self.fichas[10:20]
        serie = historico.reconstruir([lido_de(a, "2026-09-18", "cliente1.docx"), lido_de(b, "2026-09-18", "cliente2.docx")])
        self.assertEqual([r["totais"]["processos"] for r in serie], [20])
        self.assertEqual(serie.avisos, [])
        repetido = copy.deepcopy(a[0])
        ficha.definir(repetido, "valor_causa", "1.00", "humano", forcar=True)
        serie = historico.reconstruir([lido_de(a, "2026-09-18", "um.xlsx"), lido_de([repetido], "2026-09-18", "dois.xlsx")])
        self.assertEqual(serie[0]["totais"]["processos"], 10)
        self.assertEqual(next(p for p in serie[0]["por_processo"] if p["numero"] == a[0]["numero"])["valor_causa"], "1.00")
        self.assertEqual([x["codigo"] for x in serie.avisos], ["numero_repetido_no_mes"])

    def test_cliente_do_relatorio_vale_quando_o_processo_nao_traz(self):
        f = copy.deepcopy(self.fichas[0])
        f["campos"].pop("cliente")
        r, = historico.reconstruir([lido_de([f], "2026-09-18", cliente="Cliente Exemplo 09 Ltda")])
        self.assertEqual(r["por_processo"][0]["cliente"], "Cliente Exemplo 09 Ltda")

    def test_campo_desconhecido_vira_aviso_e_nao_derruba(self):
        lido = lido_de(self.fichas[:3], "2026-09-18")
        lido["processos"][0]["campos"]["coluna_inventada"] = {"valor": "x", "origem": "migrado"}
        serie = historico.reconstruir([lido])
        self.assertEqual(serie[0]["totais"]["processos"], 3)
        self.assertEqual([a["codigo"] for a in serie.avisos], ["campo_desconhecido"])

    def test_entrada_vazia(self):
        self.assertEqual(list(historico.reconstruir([])), [])
        self.assertEqual(list(historico.reconstruir(None)), [])

    def test_vinculados_e_valores_normalizados_na_leitura(self):
        f = ficha.nova_ficha(NUM(5))
        ficha.definir(f, "cliente", "Cliente Exemplo 01 Ltda", "migrado")
        lido = lido_de([f], "2026-09-18")
        lido["processos"][0]["campos"]["valor_causa"] = {"valor": "R$ 1.234,56", "origem": "migrado"}
        lido["processos"][0]["vinculados"] = [{"numero": NUM(900), "tipo": "agravo"}]
        r, = historico.reconstruir([lido])
        self.assertEqual(r["totais"]["valor_causa"], "1234.56")
        self.assertEqual(r["totais"]["processos"], 1, "vinculado não conta à parte")


if __name__ == "__main__":
    unittest.main()
