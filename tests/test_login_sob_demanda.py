"""O login do jus.br (certificado) só acontece quando um processo precisa dele. Navegador de mentira, sem rede.

    python3 -m unittest tests/test_login_sob_demanda.py -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import coletor  # noqa: E402
import pje_trt  # noqa: E402
import trt  # noqa: E402
from ficticio import numero_ficticio  # noqa: E402

N_TRT = numero_ficticio(1, j=5, tr=7)
N_TJ = numero_ficticio(2)


class Parou(Exception):
    pass


class LoginSobDemanda(unittest.TestCase):
    def setUp(self):
        coletor._LOGADOS.clear()
        pje_trt.zerar_rodada()
        self.logins = []
        for alvo in (mock.patch.object(coletor, "logar", lambda ctx: (self.logins.append(ctx), coletor._LOGADOS.add(id(ctx)))),):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.ctx = mock.MagicMock()

    def test_garantir_login_faz_uma_vez_por_navegador(self):
        coletor.garantir_login(self.ctx)
        coletor.garantir_login(self.ctx)
        self.assertEqual(len(self.logins), 1)
        outro = mock.MagicMock()
        coletor.garantir_login(outro)
        self.assertEqual(len(self.logins), 2)

    def test_esquecer_login_permite_novo_login_no_navegador_reaberto(self):
        coletor.garantir_login(self.ctx)
        coletor.esquecer_login(self.ctx)
        coletor.garantir_login(self.ctx)
        self.assertEqual(len(self.logins), 2)

    def test_processo_fora_da_justica_do_trabalho_exige_o_login(self):
        with mock.patch.object(coletor, "abrir_tramitacoes", side_effect=Parou):
            with self.assertRaises(Parou):
                coletor.coletar_processo(self.ctx, {"numero": N_TJ}, {}, [], 5, 5)
        self.assertEqual(len(self.logins), 1)

    def test_trabalhista_pelo_pje_proprio_nao_usa_o_certificado(self):
        sessao = object()
        with mock.patch.object(pje_trt, "sessao_da_rodada", lambda ctx, numero: sessao), \
                mock.patch.object(pje_trt, "coletar_processo", return_value=3) as lido:
            n = trt.coletar_processo(self.ctx, {"numero": N_TRT}, {}, [], 5, 5)
        self.assertEqual(n, 3)
        lido.assert_called_once()
        self.assertEqual(self.logins, [])

    def test_trabalhista_sem_pje_proprio_cai_na_consulta_publica_com_login(self):
        with mock.patch.object(pje_trt, "sessao_da_rodada", lambda ctx, numero: None), \
                mock.patch.object(trt, "pagina_da_consulta", side_effect=Parou):
            with self.assertRaises(Parou):
                trt.coletar_processo(self.ctx, {"numero": N_TRT}, {}, [], 5, 5)
        self.assertEqual(len(self.logins), 1)

    def test_processo_fora_do_acervo_cai_na_consulta_publica_com_login(self):
        with mock.patch.object(pje_trt, "sessao_da_rodada", lambda ctx, numero: object()), \
                mock.patch.object(pje_trt, "coletar_processo", side_effect=pje_trt.NaoNoAcervo("fora")), \
                mock.patch.object(trt, "pagina_da_consulta", side_effect=Parou):
            with self.assertRaises(Parou):
                trt.coletar_processo(self.ctx, {"numero": N_TRT}, {}, [], 5, 5)
        self.assertEqual(len(self.logins), 1)

    def test_sessao_do_pje_que_cai_vai_para_a_consulta_publica(self):
        with mock.patch.object(pje_trt, "sessao_da_rodada", lambda ctx, numero: object()), \
                mock.patch.object(pje_trt, "coletar_processo", side_effect=pje_trt.SessaoExpirada("caiu")), \
                mock.patch.object(trt, "pagina_da_consulta", side_effect=Parou):
            with self.assertRaises(Parou):
                trt.coletar_processo(self.ctx, {"numero": N_TRT}, {}, [], 5, 5)
        self.assertEqual(len(self.logins), 1)


class PdpjUmaVezPorRodada(unittest.TestCase):
    """Do `trt.coletar_processo` até o login do PDPJ: navegador reaberto no meio da rodada não manda as credenciais de novo."""

    def setUp(self):
        import acesso
        import janela
        import pdpj
        pje_trt.zerar_rodada()
        self.entradas = []
        cofre = {"pdpj_cpf": "x", "pdpj_senha": "y", "pdpj_totp": "z"}
        for alvo in (mock.patch.object(acesso, "obter", lambda c: cofre.get(c)),
                     mock.patch.object(pdpj, "trava", lambda: None),
                     mock.patch.object(pdpj, "entrar", lambda nav, trt_, consulta=True: self.entradas.append(trt_)),
                     mock.patch.object(janela, "nova_pagina", lambda ctx: mock.MagicMock()),
                     mock.patch.object(coletor, "garantir_login", lambda ctx: None),
                     mock.patch.object(trt, "pagina_da_consulta", side_effect=Parou)):
            alvo.start()
            self.addCleanup(alvo.stop)

    def coletar(self, ctx):
        with self.assertRaises(Parou):
            trt.coletar_processo(ctx, {"numero": N_TRT}, {}, [], 5, 5)

    def test_navegador_reaberto_nao_refaz_o_login_do_pdpj(self):
        antigo, novo = mock.MagicMock(), mock.MagicMock()
        with mock.patch.object(pje_trt, "coletar_processo", side_effect=pje_trt.SessaoExpirada("caiu")):
            self.coletar(antigo)                    # entrou, a sessão caiu: o resto vai pela consulta pública
            self.coletar(novo)                      # o ColetorReal fechou e reabriu o navegador (outro contexto)
        self.assertEqual(self.entradas, [7])

    def test_nova_rodada_pode_entrar_de_novo(self):
        with mock.patch.object(pje_trt, "coletar_processo", side_effect=pje_trt.SessaoExpirada("caiu")):
            self.coletar(mock.MagicMock())
            trt.zerar_rodada()                      # o que o ColetorReal faz ao nascer
            self.coletar(mock.MagicMock())
        self.assertEqual(self.entradas, [7, 7])


if __name__ == "__main__":
    unittest.main()
