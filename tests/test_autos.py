"""Seletores do coletor contra a tela de autos digitais do PDPJ (bloco de
andamentos copiado da página real), num Chromium de verdade, sem login.

    ../.venv/bin/python -m unittest tests/test_autos.py -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402,F401  (antes de tudo)

import coletor  # noqa: E402
import extrair  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "autos_pdpj.html"


class TelaDosAutos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.page = cls.browser.new_page(viewport={"width": 1200, "height": 900})
        cls.page.set_content(FIXTURE.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_1_dialogo_guiado_nao_bloqueia(self):
        self.assertEqual(self.page.get_by_role("tab").count(), 0, "o diálogo esconde a página da acessibilidade")
        self.assertTrue(coletor._autos_carregados(self.page, "0000000-00.0000.0.00.0000"))
        self.assertEqual(self.page.locator("#guia").count(), 0, "o diálogo foi fechado com 'Pular'")

    def test_1b_menu_lateral(self):
        coletor.fechar_popups(self.page, tentativas=1)
        self.assertEqual(self.page.locator(".mat-drawer-opened").count(), 0,
                         "fechar avisos não pode clicar em 'Abrir/fechar menu de navegação'")
        self.page.evaluate("menu(true)")  # o portal às vezes abre o menu sozinho
        coletor.abrir_aba(self.page, "Movimentos")
        self.assertEqual(self.page.locator(".mat-drawer-opened").count(), 0)

    def test_2_movimentos_so_da_aba_ativa(self):
        coletor.abrir_aba(self.page, "Movimentos")
        itens = coletor.ler_movimentos(self.page)
        self.assertEqual(len(itens), 6, "documentos da outra aba não podem virar andamentos")
        self.assertEqual(itens[0][1:], ("06/08/2026", "Juntada de documento comprobatório"))
        self.assertEqual(itens[-1][1:], ("30/07/2026", "Distribuído por sorteio"))
        self.assertEqual(len({c for c, _, _ in itens}), 6, "chaves únicas")

    def test_3_documentos_com_data(self):
        coletor.abrir_aba(self.page, "Documentos")
        docs = coletor.listar_documentos(self.page)
        self.assertEqual([(n, d) for n, _, d in docs], [
            ("201 - Decisão - Decisão.html", "01/10/2026"),
            ("200 - Ata de Audiência de Conciliação - C06.pdf", "03/09/2026"),
            ("199 - Petição (outras) - Manifestação.pdf", "03/09/2026"),
        ])
        coletor.abrir_aba(self.page, "Movimentos")

    def test_print_e_ocr(self):
        destino = Path(os.environ["RELATORIO_DATA"]) / "print-teste.png"
        coletor.print_elemento(self.page, ".conteudo", destino)
        texto = extrair.texto_print(destino)
        self.assertIn("INDEFIRO", texto.upper())


if __name__ == "__main__":
    unittest.main(verbosity=2)
