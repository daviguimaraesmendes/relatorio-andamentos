"""Tela Acesso: CPF e senha do PDPJ (login no PJe dos TRTs). Cofre falso, config temporário, dados fictícios, sem rede.

    python3 -m unittest tests/test_acesso_pdpj.py -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import acesso  # noqa: E402
import comum  # noqa: E402

GLOBAIS = ("PROJETOS_DIR", "ATUAL_FILE", "CONFIG_FILE", "PROJETO", "PROJETO_DIR", "PROJETO_FILE", "DATA",
           "CARTEIRA_FILE", "CLIENTES_FILE", "EVENTOS_FILE", "ESTADO_FILE", "DOCS_DIR", "TEXTOS_DIR",
           "RELATORIOS_DIR", "DIAG_DIR", "PRINTS_DIR")


def _cpf_de_teste(base="987654321"):
    """CPF com dígitos verificadores corretos, calculado aqui (nenhum CPF escrito no arquivo)."""
    d = [int(c) for c in base]
    for n in (9, 10):
        d.append((sum(d[i] * (n + 1 - i) for i in range(n)) * 10 % 11) % 10)
    t = "".join(map(str, d))
    return f"{t[:3]}.{t[3:6]}.{t[6:9]}-{t[9:]}", t


CPF_OK, CPF_DIGITOS = _cpf_de_teste()
VALOR_A = "valor-ficticio-a-77"
VALOR_B = "".join(["JBSWY3DP", "EHPK3PXP"])


class CpfValido(unittest.TestCase):
    def test_validos_e_invalidos(self):
        self.assertTrue(acesso.cpf_valido(CPF_OK))
        self.assertTrue(acesso.cpf_valido(CPF_DIGITOS))
        errado = CPF_DIGITOS[:-1] + str((int(CPF_DIGITOS[-1]) + 1) % 10)          # último dígito trocado
        for ruim in ("", None, "123", "1" * 11, errado, "abc", CPF_DIGITOS + "5"):
            self.assertFalse(acesso.cpf_valido(ruim), ruim)


class Tela(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from painel import acesso_tela, base
        cls.salvo = {n: getattr(comum, n) for n in GLOBAIS}
        cls.app = Flask(__name__)
        cls.app.config["TESTING"] = True
        cls.token = "token-de-teste"
        for tela in (acesso_tela, base):
            tela.registrar(cls.app, cls.token, base.cabecalho, base.criar_token_ok(cls.token))
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for n, v in cls.salvo.items():
            setattr(comum, n, v)

    def setUp(self):
        nome = self._testMethodName
        raiz = TMP / "projetos-acesso-pdpj" / nome
        raiz.mkdir(parents=True, exist_ok=True)
        comum.PROJETOS_DIR, comum.ATUAL_FILE = raiz, raiz / ".projeto_atual"
        comum.CONFIG_FILE = TMP / f"config-acesso-{nome}.json"
        comum.CONFIG_FILE.unlink(missing_ok=True)
        comum._apontar(raiz / "_v" / "data", raiz / "_v" / "carteira.json", raiz / "_v" / "clientes.json")
        comum.PROJETO = comum.PROJETO_DIR = comum.PROJETO_FILE = None
        self.cofre = {}
        for alvo in (mock.patch.object(acesso, "obter", lambda c: self.cofre.get(c)),
                     mock.patch.object(acesso, "guardar", lambda c, v: self.cofre.__setitem__(c, v))):
            alvo.start()
            self.addCleanup(alvo.stop)

    def post(self, dados):
        return self.c.post("/acesso", data={"token": self.token, **dados})

    def pagina(self):
        return self.c.get("/acesso").get_data(as_text=True)

    def test_pagina_mostra_os_campos_sem_nada_configurado(self):
        p = self.pagina()
        for texto in ("CPF da conta do PDPJ", "Senha da conta do PDPJ", "name='pdpj_cpf'", "name='pdpj_senha'", "name='pdpj_totp'", "name='totp_secret'"):
            self.assertIn(texto, p)
        self.assertEqual(p.count("não configurada"), 5)       # certificado, autenticador do jus.br, CPF, senha e autenticador do PDPJ
        self.assertEqual(acesso.situacao_pdpj(), {"pdpj_cpf": False, "pdpj_senha": False, "pdpj_totp": False})

    def test_guarda_no_cofre_e_nunca_devolve_o_valor(self):
        r = self.post({"pdpj_cpf": CPF_OK, "pdpj_senha": VALOR_A, "pdpj_totp": VALOR_B})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.cofre["pdpj_cpf"], CPF_DIGITOS)          # só os dígitos
        self.assertEqual(self.cofre["pdpj_senha"], VALOR_A)
        self.assertEqual(self.cofre["pdpj_totp"], VALOR_B)
        self.assertNotIn("totp_secret", self.cofre)            # o do jus.br é outro e não é tocado
        self.assertEqual(acesso.situacao_pdpj(), {"pdpj_cpf": True, "pdpj_senha": True, "pdpj_totp": True})
        pagina = self.pagina()
        for segredo in (CPF_DIGITOS, CPF_OK, VALOR_A, VALOR_B):
            self.assertNotIn(segredo, pagina)
        self.assertNotIn(CPF_DIGITOS, comum.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertNotIn(VALOR_A, comum.CONFIG_FILE.read_text(encoding="utf-8"))

    def test_os_dois_autenticadores_sao_independentes(self):
        outro = "".join(["KRSXG5DS", "NFXGOZLS"])
        self.post({"totp_secret": VALOR_B})
        self.assertEqual(acesso.situacao_pdpj()["pdpj_totp"], False)       # o do jus.br não vale para o PDPJ
        self.post({"pdpj_totp": outro})
        self.assertEqual((self.cofre["totp_secret"], self.cofre["pdpj_totp"]), (VALOR_B, outro))
        p = self.pagina()
        self.assertEqual(p.count("Código de agora"), 2)                    # cada um com o seu código de conferência
        self.assertNotIn("o mesmo do jus.br e do PDPJ", p)

    def test_segredo_do_pdpj_invalido_nao_salva(self):
        r = self.post({"pdpj_totp": "isto não é base32 !!"})
        self.assertIn("PDPJ não é válido", self.c.get(r.headers["Location"]).get_data(as_text=True))
        self.assertEqual(self.cofre, {})

    def test_cpf_invalido_nao_salva_nada(self):
        r = self.post({"pdpj_cpf": CPF_DIGITOS[:-1] + str((int(CPF_DIGITOS[-1]) + 1) % 10), "pdpj_senha": VALOR_A})
        self.assertIn("CPF", self.c.get(r.headers["Location"]).get_data(as_text=True))
        self.assertEqual(self.cofre, {})

    def test_em_branco_mantem_o_que_esta_guardado(self):
        self.cofre.update(pdpj_cpf=CPF_DIGITOS, pdpj_senha=VALOR_A)
        self.post({"pdpj_cpf": "", "pdpj_senha": ""})
        self.assertEqual((self.cofre["pdpj_cpf"], self.cofre["pdpj_senha"]), (CPF_DIGITOS, VALOR_A))

    def test_exige_token(self):
        self.assertEqual(self.c.post("/acesso", data={"pdpj_cpf": CPF_OK}).status_code, 403)
        self.assertEqual(self.cofre, {})


if __name__ == "__main__":
    unittest.main()
