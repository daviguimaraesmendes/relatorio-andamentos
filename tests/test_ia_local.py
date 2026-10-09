"""Testa o botão "Instalar IA local" com um Ollama falso: sem rede e sem instalar nada.

    python3 -m unittest tests.test_ia_local -v
"""
import io
import json
import sys
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402,F401  (antes de tudo)
import comum  # noqa: E402
import ia_local as ia  # noqa: E402

BAIXADOS = []


class OllamaFalso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self._enviar(json.dumps({"models": [{"name": n} for n in BAIXADOS]}).encode())

    def do_POST(self):
        pedido = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        linhas = [{"status": "pulling manifest"}]
        for feito in (0, 30, 60, 100):
            linhas.append({"status": "downloading", "digest": "sha256:abcdef1234567890", "total": 100 << 20, "completed": feito << 20})
        if pedido["model"] == "inexistente:1b":
            linhas = [{"error": "file does not exist"}]
        else:
            BAIXADOS.append(pedido["model"])
        self._enviar(b"".join(json.dumps(l).encode() + b"\n" for l in linhas))

    def _enviar(self, corpo):
        self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


class IA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), OllamaFalso)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cfg = dict(comum.config(), ollama_url=f"http://127.0.0.1:{cls.srv.server_port}")
        cls.patch = mock.patch.object(comum, "config", lambda: cfg)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.srv.shutdown()

    def setUp(self):
        BAIXADOS.clear()

    def test_baixa_o_modelo_mostrando_o_andamento(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            ia.baixar_modelo("teste:3b")
        texto = saida.getvalue()
        self.assertIn("30%", texto)
        self.assertIn("100%", texto)
        self.assertIn("teste:3b", BAIXADOS)
        self.assertTrue(ia.modelo_baixado("teste:3b"))

    def test_erro_do_servidor_vira_excecao(self):
        with self.assertRaises(RuntimeError):
            ia.baixar_modelo("inexistente:1b")

    def test_instalar_pula_o_que_ja_esta_pronto(self):
        BAIXADOS.append("teste:3b")
        saida = io.StringIO()
        with mock.patch.object(ia, "ollama_exe", lambda: "/usr/bin/ollama"), redirect_stdout(saida):
            self.assertEqual(ia.instalar("teste:3b"), 0)
        self.assertIn("já está baixado", saida.getvalue())

    def test_instalar_baixa_quando_falta_so_o_modelo(self):
        with mock.patch.object(ia, "ollama_exe", lambda: "/usr/bin/ollama"), redirect_stdout(io.StringIO()):
            self.assertEqual(ia.instalar("teste:3b"), 0)
        self.assertEqual(BAIXADOS, ["teste:3b"])

    def test_situacao(self):
        with mock.patch.object(ia, "ollama_exe", lambda: None):
            self.assertEqual(ia.situacao("teste:3b"), {"instalado": False, "modelo": "teste:3b", "modelo_baixado": False})
            self.assertFalse(ia.pronto("teste:3b"))
        BAIXADOS.append("teste:3b")
        with mock.patch.object(ia, "ollama_exe", lambda: "x"):
            self.assertTrue(ia.pronto("teste:3b"))

    def test_sem_ollama_fora_do_windows_so_orienta(self):
        saida = io.StringIO()
        with mock.patch.object(ia, "ollama_exe", lambda: None), mock.patch.object(ia, "WINDOWS", False), redirect_stdout(saida):
            self.assertEqual(ia.instalar("teste:3b"), 1)
        self.assertIn("ollama.com/download", saida.getvalue())

    def test_pagina_do_painel(self):
        import revisao
        cliente = revisao.app.test_client()
        with mock.patch.object(ia, "ollama_exe", lambda: None):
            html = cliente.get("/ia").get_data(as_text=True)
        self.assertIn("Instalar IA local", html)
        self.assertIn("falta", html)
        BAIXADOS.append(__import__("resumir").modelo_escolhido())
        with mock.patch.object(ia, "ollama_exe", lambda: "x"):
            html = cliente.get("/ia").get_data(as_text=True)
        self.assertIn("Tudo pronto", html)
        self.assertNotIn("name='tipo' value='ia'", html, "pronto: sem o botão de instalar")


if __name__ == "__main__":
    unittest.main()
