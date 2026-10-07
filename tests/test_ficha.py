"""Ficha v2 e vocabulários: origem dos campos, prioridade, conversões e normalização de rótulos.
Só dados fictícios (números sintéticos com dígito verificador correto)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: F401  (aponta comum.py para uma pasta temporária)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import comum  # noqa: E402
import ficha  # noqa: E402
import taxonomia  # noqa: E402
from ficticio import numero_ficticio  # noqa: E402


NUM, OUTRO = numero_ficticio(0), numero_ficticio(1)


class TestConversoes(unittest.TestCase):
    def test_dinheiro(self):
        casos = {"R$ 1.234,56": "1234.56", "1,234.56": "1234.56", 1234.5: "1234.50", "R$ 0,00": "0.00",
                 "R$ 10.788.082,61": "10788082.61", "15000": "15000.00", "-": None, "": None, None: None}
        for entrada, esperado in casos.items():
            self.assertEqual(ficha.parse_dinheiro(entrada), esperado, entrada)

    def test_data(self):
        self.assertEqual(ficha.parse_data("18/09/2026"), "2026-09-18")
        self.assertEqual(ficha.parse_data("2026-09-18"), "2026-09-18")
        self.assertIsNone(ficha.parse_data("31/02/2026"))
        self.assertEqual(ficha.data_br("2026-09-18"), "18/09/2026")

    def test_dinheiro_br(self):
        self.assertEqual(ficha.dinheiro_br("1234567.80"), "R$ 1.234.567,80")


class TestPrioridade(unittest.TestCase):
    def setUp(self):
        self.f = ficha.nova_ficha(NUM)

    def test_humano_nao_e_sobrescrito(self):
        self.assertTrue(ficha.definir(self.f, "probabilidade", "Provável", "humano"))
        self.assertFalse(ficha.definir(self.f, "probabilidade", "Remota", "sugerido"))
        self.assertFalse(ficha.definir(self.f, "probabilidade", "Remota", "coletado"))
        self.assertEqual(ficha.obter(self.f, "probabilidade"), "Provável")
        self.assertTrue(ficha.definir(self.f, "probabilidade", "Remota", "humano"))  # humano novo vale

    def test_coletado_vence_migrado_e_sugerido_nao_vence_nada(self):
        ficha.definir(self.f, "vara", "5ª Vara", "migrado")
        self.assertTrue(ficha.definir(self.f, "vara", "6ª Vara", "coletado"))
        self.assertFalse(ficha.definir(self.f, "vara", "7ª Vara", "migrado"))
        self.assertEqual(ficha.obter(self.f, "vara"), "6ª Vara")

    def test_valor_vazio_nao_apaga_e_rotulo_desconhecido_nao_grava(self):
        ficha.definir(self.f, "resultado", "Acordo", "humano")
        self.assertFalse(ficha.definir(self.f, "resultado", "", "humano"))
        self.assertFalse(ficha.definir(self.f, "resultado", "algo inventado", "humano"))
        self.assertEqual(ficha.obter(self.f, "resultado"), "Acordo")

    def test_normaliza_pelo_tipo(self):
        ficha.definir(self.f, "valor_causa", "R$ 1.000,00", "coletado")
        ficha.definir(self.f, "data_ajuizamento", "01/02/2024", "coletado")
        self.assertEqual(ficha.obter(self.f, "valor_causa"), "1000.00")
        self.assertEqual(ficha.obter(self.f, "data_ajuizamento"), "2024-02-01")
        self.assertEqual(ficha.validar(self.f), [])


class TestCompatibilidade(unittest.TestCase):
    def test_item_da_fase_1_vira_ficha_sem_perda(self):
        item = {"numero": NUM, "tribunal": "TJCE", "cliente": "CLIENTE EXEMPLO", "polo_cliente": "passivo",
                "parte_contraria": "FULANO", "responsavel": "Davi", "contato": "", "ativo": True,
                "origem": "lista", "incluido_em": "2026-10-01"}
        f = ficha.de_carteira_v1(item)
        self.assertEqual(f["v"], 2)
        self.assertEqual(f["cliente"], "CLIENTE EXEMPLO")  # chave plana continua
        self.assertEqual(ficha.obter(f, "cliente"), "CLIENTE EXEMPLO")
        self.assertEqual(ficha.obter(f, "polo_cliente"), "passivo")
        self.assertEqual(f["origem"], "lista")

    def test_campo_plano_espelhado(self):
        f = ficha.nova_ficha(NUM)
        ficha.definir(f, "cliente", "CLIENTE EXEMPLO", "humano")
        self.assertEqual(f["cliente"], "CLIENTE EXEMPLO")

    def test_ida_e_volta_no_arquivo(self):
        comum.save_json(comum.CARTEIRA_FILE, [{"numero": NUM, "tribunal": "TJCE", "cliente": "X", "ativo": True}])
        fichas = ficha.carregar()
        ficha.definir(fichas[0], "vara", "1ª Vara", "coletado")
        ficha.salvar(fichas)
        de_novo = ficha.carregar()
        self.assertEqual(ficha.obter(de_novo[0], "vara"), "1ª Vara")
        self.assertEqual(de_novo[0]["cliente"], "X")

    def test_vinculados(self):
        f = ficha.nova_ficha(NUM)
        ficha.vincular(f, NUM, "agravo")  # o próprio número não entra
        self.assertEqual(f["vinculados"], [])
        outro = OUTRO
        ficha.vincular(f, outro, "Agravo de instrumento")
        ficha.vincular(f, outro, "agravo")
        self.assertEqual(len(f["vinculados"]), 1)
        self.assertEqual(f["vinculados"][0]["tipo"], "agravo")


class TestTaxonomia(unittest.TestCase):
    def test_rotulos_soltos(self):
        n = taxonomia.normalizar
        self.assertEqual(n("resultado", "Parcialmente procedente."), "Parcialmente procedente")
        self.assertEqual(n("resultado", "PARCIAL PROCEDÊNCIA"), "Parcialmente procedente")
        self.assertEqual(n("resultado", "Improcedente"), "Improcedente")
        self.assertEqual(n("resultado", "Incompetência territorial declarada"), "Incompetência declarada")
        self.assertEqual(n("probabilidade", "provavel"), "Provável")
        self.assertEqual(n("area", "Trabalho"), "Trabalhista")
        self.assertEqual(n("materia", "Insalubridade"), "Adicional de insalubridade")
        self.assertEqual(n("materia", "horas extras"), "Horas extras e reflexos")

    def test_ambiguo_ou_desconhecido_vira_none(self):
        self.assertIsNone(taxonomia.normalizar("resultado", "qualquer coisa"))
        self.assertIsNone(taxonomia.normalizar("resultado", ""))

    def test_momento_atual(self):
        self.assertFalse(taxonomia.momento_ativo("PROCESSO ARQUIVADO"))
        self.assertTrue(taxonomia.momento_ativo("AGUARDANDO SENTENÇA"))
        self.assertIsNone(taxonomia.momento_ativo("INVENTADO"))
        f = ficha.nova_ficha(NUM)
        ficha.definir(f, "momento_atual", "aguardando sentença", "coletado")
        self.assertEqual(ficha.obter(f, "momento_atual"), "AGUARDANDO SENTENÇA")
        f["ativo"] = False
        self.assertTrue(any("conflita" in p for p in ficha.validar(f)))


class TestMomentoComQualificador(unittest.TestCase):
    def test_separa_momento_e_qualificador(self):
        f = ficha.nova_ficha(NUM)
        self.assertTrue(ficha.definir(f, "momento_atual", "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)", "migrado"))
        self.assertEqual(ficha.obter(f, "momento_atual"), "CUMPRIMENTO DE SENTENÇA")
        self.assertEqual(ficha.obter(f, "momento_qualificador"), "HONORÁRIOS SUSPENSOS")
        self.assertEqual(taxonomia.formatar_momento(ficha.obter(f, "momento_atual"), ficha.obter(f, "momento_qualificador")),
                         "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)")
        self.assertEqual(ficha.validar(f), [])

    def test_qualificador_antigo_sai_quando_o_momento_muda(self):
        f = ficha.nova_ficha(NUM)
        ficha.definir(f, "momento_atual", "PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)", "migrado")
        ficha.definir(f, "momento_atual", "CUMPRIMENTO DE SENTENÇA", "coletado")
        self.assertEqual(ficha.obter(f, "momento_atual"), "CUMPRIMENTO DE SENTENÇA")
        self.assertIsNone(ficha.obter(f, "momento_qualificador"))

    def test_mesmo_momento_mantem_o_qualificador(self):
        f = ficha.nova_ficha(NUM)
        ficha.definir(f, "momento_atual", "PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)", "migrado")
        ficha.definir(f, "momento_atual", "PROCESSO ARQUIVADO", "coletado")
        self.assertEqual(ficha.obter(f, "momento_qualificador"), "DECISÃO FAVORÁVEL")


if __name__ == "__main__":
    unittest.main()
