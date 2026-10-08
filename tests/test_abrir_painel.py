"""Lançador do painel (src/abrir_painel.py): só abre o que está atual, reinicia o que está velho, nunca mata coleta."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import abrir_painel as ap  # noqa: E402


def servidor(versao_json=None, sem_servidor=False):
    """Troca ap._get por um servidor falso."""
    def get(url, timeout=3):
        if sem_servidor:
            raise OSError("recusou")
        if url.endswith("/versao.json"):
            if versao_json is None:
                raise OSError("404")
            return 200, json.dumps(versao_json)
        return 200, "{}"
    return mock.patch.object(ap, "_get", side_effect=get)


class TestEstado(unittest.TestCase):
    def test_estados(self):
        casos = [
            (dict(sem_servidor=True), "parado"),
            (dict(versao_json=None), "velho"),                                                            # sem /versao.json
            (dict(versao_json={"carregada": "b5", "arquivo": "b5", "coleta": False, "tarefa": False}), "atual"),
            (dict(versao_json={"carregada": "b4", "arquivo": "b5", "coleta": False, "tarefa": False}), "velho"),
            (dict(versao_json={"carregada": "b4", "arquivo": "b5", "coleta": True, "tarefa": False}), "ocupado_velho"),
            (dict(versao_json={"carregada": "b5", "arquivo": "b5", "coleta": False, "tarefa": True}), "ocupado"),
        ]
        for args, esperado in casos:
            with servidor(**args):
                self.assertEqual(ap.estado_do_painel(5072), esperado, args)


class TestServidorSemVersaoJson(unittest.TestCase):
    def _get(self, estado_coleta, pagina="<html></html>"):
        def get(url, timeout=3):
            if url.endswith("/versao.json"):
                raise OSError("404")
            if url.endswith("/fluxo/progresso.json"):
                return 200, json.dumps({"estado": estado_coleta})
            if url.endswith("/atualizar"):
                return 200, pagina
            return 200, "{}"
        return mock.patch.object(ap, "_get", side_effect=get)

    def test_sem_versao_json_e_coletando_nao_reinicia(self):
        with self._get("rodando"):
            self.assertEqual(ap.estado_do_painel(5072), "ocupado_velho")
        with self._get("parado", "<b>tarefa em andamento</b>"):
            self.assertEqual(ap.estado_do_painel(5072), "ocupado_velho")

    def test_sem_versao_json_e_parado_reinicia(self):
        with self._get("parado"):
            self.assertEqual(ap.estado_do_painel(5072), "velho")


class TestPrincipal(unittest.TestCase):
    def rodar(self, estado, encerra=True):
        with mock.patch.object(ap, "porta", return_value=5072), mock.patch.object(ap, "estado_do_painel", return_value=estado), \
                mock.patch.object(ap.webbrowser, "open") as abrir, mock.patch.object(ap, "encerrar_servidor", return_value=encerra) as enc, \
                mock.patch.object(ap.os, "execv") as execv, mock.patch.object(ap.os, "chdir"), \
                mock.patch.object(ap, "WINDOWS", False):
            codigo = ap.principal(["cadastro"])
        return codigo, abrir, enc, execv

    def test_atual_so_abre_o_navegador(self):
        codigo, abrir, enc, execv = self.rodar("atual")
        abrir.assert_called_once_with("http://127.0.0.1:5072/cadastro")
        enc.assert_not_called()
        execv.assert_not_called()

    def test_ocupado_nunca_reinicia(self):
        for estado in ("ocupado", "ocupado_velho"):
            _, abrir, enc, execv = self.rodar(estado)
            abrir.assert_called_once()
            enc.assert_not_called()
            execv.assert_not_called()

    def test_velho_encerra_e_sobe_o_novo(self):
        _, abrir, enc, execv = self.rodar("velho")
        enc.assert_called_once_with(5072)
        execv.assert_called_once()
        self.assertEqual(execv.call_args[0][1][1:], ["revisao.py", "--abrir"])

    def test_velho_que_nao_encerra_nao_sobe_outro_por_cima(self):
        codigo, _, _, execv = self.rodar("velho", encerra=False)
        self.assertEqual(codigo, 1)
        execv.assert_not_called()

    def test_parado_sobe_o_servidor(self):
        _, abrir, enc, execv = self.rodar("parado")
        enc.assert_not_called()
        execv.assert_called_once()


class TestPids(unittest.TestCase):
    def test_lsof_no_mac(self):
        class R:
            stdout = "123\n123\n456\n"
        with mock.patch.object(ap, "WINDOWS", False), mock.patch.object(ap.subprocess, "run", return_value=R()):
            self.assertEqual(ap.pids_na_porta(5072), [123, 456])

    def test_netstat_no_windows(self):
        class R:
            stdout = ("  TCP    127.0.0.1:5072    0.0.0.0:0    LISTENING    4321\n"
                      "  TCP    127.0.0.1:50720   0.0.0.0:0    LISTENING    999\n"
                      "  TCP    127.0.0.1:5072    127.0.0.1:60000    ESTABLISHED    4321\n")
        with mock.patch.object(ap, "WINDOWS", True), mock.patch.object(ap.subprocess, "run", return_value=R()):
            self.assertEqual(ap.pids_na_porta(5072), [4321])


if __name__ == "__main__":
    unittest.main()
