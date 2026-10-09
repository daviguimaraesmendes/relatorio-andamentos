"""Tela "Configurar tudo" (/configurar): passos guiados, selos pronto/falta, salvar no cofre certo, segredos que não voltam,
trava do PDPJ e atalhos. Cofre falso, config temporário, dados fictícios, sem rede e sem abrir tarefa de verdade.

    python3 -m unittest tests/test_configurar.py -v
"""
import re
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import acesso  # noqa: E402
import comum  # noqa: E402
import pdpj  # noqa: E402

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
CPF_RUIM = CPF_DIGITOS[:-1] + str((int(CPF_DIGITOS[-1]) + 1) % 10)
VALOR_A = "valor-ficticio-a-77"
VALOR_B = "valor-ficticio-b-88"
TOTP_PDPJ = "".join(["JBSWY3DP", "EHPK3PXP"])
TOTP_JUS = "".join(["KRSXG5DS", "NFXGOZLS"])
SEM_IA = {"modelo": "modelo-ficticio", "instalado": False, "baixado": False, "completo": False, "externa": ""}
COM_IA = {**SEM_IA, "instalado": True, "baixado": True, "completo": True}


class FalsoProc:
    """Processo de mentira: está 'rodando' para sempre e nunca abre nada."""
    pid = 4242

    def poll(self):
        return None


class Configurar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from painel import acesso_tela, atualizar, base, configurar, inicio
        cls.base, cls.configurar = base, configurar
        cls.salvo = {n: getattr(comum, n) for n in GLOBAIS}
        cls.app = Flask(__name__)
        cls.app.config["TESTING"] = True
        cls.token = "token-de-teste"
        for tela in (inicio, base, atualizar, acesso_tela, configurar):       # a ordem de revisao.py (inicio antes de base)
            tela.registrar(cls.app, cls.token, base.cabecalho, base.criar_token_ok(cls.token))
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for n, v in cls.salvo.items():
            setattr(comum, n, v)

    def setUp(self):
        nome = self._testMethodName
        raiz = TMP / "projetos-configurar" / nome
        raiz.mkdir(parents=True, exist_ok=True)
        comum.PROJETOS_DIR, comum.ATUAL_FILE = raiz, raiz / ".projeto_atual"
        comum.CONFIG_FILE = TMP / f"config-configurar-{nome}.json"
        comum.CONFIG_FILE.unlink(missing_ok=True)
        comum._apontar(raiz / "_v" / "data", raiz / "_v" / "carteira.json", raiz / "_v" / "clientes.json")
        comum.PROJETO = comum.PROJETO_DIR = comum.PROJETO_FILE = None
        self.c.delete_cookie("projeto")
        self.cofre = {}
        self.base.TAREFA.clear()
        self.addCleanup(self.base.TAREFA.clear)
        self.addCleanup(pdpj.liberar)
        self.ia = dict(SEM_IA)
        for alvo in (mock.patch.object(acesso, "obter", lambda c: self.cofre.get(c)),
                     mock.patch.object(acesso, "guardar", lambda c, v: self.cofre.__setitem__(c, v)),
                     mock.patch.object(self.configurar, "_estado_ia", lambda: self.ia),
                     mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede usada")),
                     mock.patch.object(socket.socket, "connect", side_effect=AssertionError("rede usada"))):
            alvo.start()
            self.addCleanup(alvo.stop)
        pdpj.liberar()

    # --- ajudantes ---

    def pagina(self, caminho="/configurar"):
        return self.c.get(caminho).get_data(as_text=True)

    def post(self, dados, caminho="/configurar", token=True):
        return self.c.post(caminho, data=({"token": self.token} if token else {}) | dados)

    def selos(self, pagina):
        """{passo: 'pronto ✓' ou 'falta' ...} lido da lista de passos do alto da página."""
        return {int(n): t for n, t in re.findall(r"<a href='#passo-(\d)'>[^<]*</a><span class='selo [a-z]+'>([^<]*)</span>", pagina)}

    def preencher_tudo(self):
        self.cofre.update(pdpj_cpf=CPF_DIGITOS, pdpj_senha=VALOR_A, pdpj_totp=TOTP_PDPJ, cert_senha=VALOR_B, totp_secret=TOTP_JUS)
        comum.save_json(comum.CONFIG_FILE, {"revisor": "Maria Teste", "identificadores_escritorio": ["Fulano Teste, OAB 12.345"]})

    def botao_testar_pdpj(self, p):
        m = re.search(r"<button class='principal' ([^>]*)>Testar login \(uma tentativa\)</button>", p)
        self.assertIsNotNone(m, "botão de teste do PDPJ não encontrado")
        return m.group(1)

    # --- a tela abre ---

    def test_abre_sem_nada_configurado_e_sem_relatorio(self):
        r = self.c.get("/configurar")
        self.assertEqual(r.status_code, 200)             # sem relatório não desvia para /novo
        p = r.get_data(as_text=True)
        for texto in ("<h1>Configurar tudo</h1>", "0 de 4 passos prontos", "Seus dados",
                      "Justiça do Trabalho (PJe dos TRTs, conta do PDPJ)", "Justiça Estadual e Federal (jus.br, com certificado digital)",
                      "IA que resume os documentos", "Testar", "name='revisor'", "name='identificadores'", "name='pdpj_cpf'",
                      "name='pdpj_senha'", "name='pdpj_totp'", "name='cert_senha'", "name='totp_secret'", "Instalar IA local",
                      "Testar login (uma tentativa)", "Testar acesso do jus.br", "class='ajuda'",
                      "Só preencha este passo se você acompanha processos fora da Justiça do Trabalho",
                      "não usa o certificado digital", "<b>não é</b> o do jus.br"):
            self.assertIn(texto, p)
        self.assertEqual(self.selos(p), {1: "falta", 2: "falta", 3: "falta", 4: "falta", 5: "salve os dados antes"})
        self.assertNotIn("o mesmo do jus.br e do PDPJ", p)
        self.assertEqual(self.cofre, {})                 # só olhar não grava nada
        self.assertFalse(comum.CONFIG_FILE.exists())

    def test_abre_tambem_com_relatorio(self):
        comum.usar_projeto(comum.criar_projeto("Relatório fictício"))
        p = self.pagina()
        self.assertIn("<h1>Configurar tudo</h1>", p)
        self.assertIn("href='/ia'", p)                   # com relatório, o link para escolher o provedor externo

    def test_selos_acompanham_o_que_esta_guardado(self):
        self.cofre.update(pdpj_cpf=CPF_DIGITOS, pdpj_senha=VALOR_A, pdpj_totp=TOTP_PDPJ)
        comum.save_json(comum.CONFIG_FILE, {"revisor": "Maria Teste", "identificadores_escritorio": ["Fulano Teste, OAB 12.345"]})
        s = self.selos(self.pagina())
        self.assertEqual((s[1], s[2], s[3], s[4]), ("pronto ✓", "pronto ✓", "falta", "falta"))
        self.assertIn("2 de 4 passos prontos", self.pagina())
        self.cofre.update(cert_senha=VALOR_B)            # só um dos dois do jus.br: ainda falta
        self.assertEqual(self.selos(self.pagina())[3], "falta")
        self.cofre.update(totp_secret=TOTP_JUS)
        self.ia = dict(COM_IA)
        s = self.selos(self.pagina())
        self.assertEqual([s[i] for i in (1, 2, 3, 4)], ["pronto ✓"] * 4)
        self.assertIn("4 de 4 passos prontos", self.pagina())

    def test_passo_1_so_fica_pronto_com_nome_e_assinatura(self):
        comum.save_json(comum.CONFIG_FILE, {"revisor": "Maria Teste", "identificadores_escritorio": []})
        self.assertEqual(self.selos(self.pagina())[1], "falta")

    def test_ia_externa_escolhida_conta_como_pronta(self):
        self.ia = {**SEM_IA, "externa": "externa: provedor-ficticio"}
        p = self.pagina()
        self.assertEqual(self.selos(p)[4], "pronto ✓")
        self.assertIn("provedor-ficticio", p)

    # --- salvar ---

    def test_cada_grupo_vai_para_o_cofre_certo(self):
        r = self.post({"pdpj_cpf": CPF_OK, "pdpj_senha": VALOR_A, "pdpj_totp": TOTP_PDPJ, "passo": "2"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("#passo-3"))
        self.assertEqual(self.cofre, {"pdpj_cpf": CPF_DIGITOS, "pdpj_senha": VALOR_A, "pdpj_totp": TOTP_PDPJ})
        self.assertNotIn("totp_secret", self.cofre)       # o do jus.br é outro e não é tocado
        self.assertNotIn("cert_senha", self.cofre)
        self.post({"cert_senha": VALOR_B, "totp_secret": " krsx g5ds nfxg ozls ", "passo": "3"})
        self.assertEqual((self.cofre["cert_senha"], self.cofre["totp_secret"]), (VALOR_B, TOTP_JUS))
        self.assertEqual(self.cofre["pdpj_totp"], TOTP_PDPJ)   # o do PDPJ não foi sobrescrito pelo do jus.br
        self.assertNotEqual(self.cofre["pdpj_totp"], self.cofre["totp_secret"])

    def test_dados_do_escritorio_vao_para_o_config_e_nao_para_o_cofre(self):
        self.post({"revisor": " Maria Teste ", "identificadores": "Fulano Teste, OAB 12.345\n\n  Beltrano Teste  \n", "passo": "1"})
        cfg = comum.load_json(comum.CONFIG_FILE, {})
        self.assertEqual(cfg["revisor"], "Maria Teste")
        self.assertEqual(cfg["identificadores_escritorio"], ["Fulano Teste, OAB 12.345", "Beltrano Teste"])
        self.assertEqual(self.cofre, {})
        p = self.pagina()
        self.assertIn("Maria Teste", p)
        self.assertIn("Beltrano Teste", p)

    def test_mensagem_de_sucesso_na_pagina(self):
        r = self.post({"pdpj_senha": VALOR_A, "passo": "2"})
        p = self.pagina(r.headers["Location"].split("#")[0])
        self.assertIn("Senha do PDPJ guardada no cofre do sistema.", p)
        self.assertNotIn(VALOR_A, p)

    def test_em_branco_mantem_o_que_esta_guardado(self):
        self.preencher_tudo()
        antes = dict(self.cofre)
        self.post({"pdpj_cpf": "", "pdpj_senha": "", "pdpj_totp": "", "cert_senha": "", "totp_secret": "", "passo": "2"})
        self.assertEqual(self.cofre, antes)

    def test_cpf_invalido_nao_salva_nada(self):
        r = self.post({"pdpj_cpf": CPF_RUIM, "pdpj_senha": VALOR_A, "cert_senha": VALOR_B, "revisor": "Maria Teste", "passo": "2"})
        self.assertEqual(r.status_code, 400)
        p = r.get_data(as_text=True)
        self.assertIn("O CPF não é válido", p)
        self.assertIn("Nada foi salvo", p)
        self.assertEqual(self.cofre, {})                  # nem a senha do PDPJ nem a do certificado
        self.assertFalse(comum.CONFIG_FILE.exists())      # nem os nomes
        self.assertIn("value='Maria Teste'", p)           # mas o que não é segredo continua na tela, para não digitar tudo de novo
        for segredo in (CPF_RUIM, CPF_DIGITOS, VALOR_A, VALOR_B):
            self.assertNotIn(segredo, p)

    def test_segredo_do_autenticador_invalido_nao_salva_nada(self):
        for campo, trecho in (("pdpj_totp", "autenticador do PDPJ não é válido"), ("totp_secret", "O segredo do autenticador não é válido")):
            r = self.post({campo: "isto não é base32 !!", "pdpj_senha": VALOR_A, "cert_senha": VALOR_B, "passo": "2"})
            self.assertEqual(r.status_code, 400, campo)
            self.assertIn(trecho, r.get_data(as_text=True))
            self.assertEqual(self.cofre, {}, campo)
            self.assertFalse(comum.CONFIG_FILE.exists(), campo)

    def test_exige_token(self):
        self.assertEqual(self.post({"pdpj_cpf": CPF_OK, "pdpj_senha": VALOR_A}, token=False).status_code, 403)
        self.assertEqual(self.post({"tipo": "ia", "volta": "/configurar"}, caminho="/tarefa", token=False).status_code, 403)
        self.assertEqual(self.post({"volta": "/configurar"}, caminho="/acesso/pdpj/liberar", token=False).status_code, 403)
        self.assertEqual(self.cofre, {})

    def test_a_tela_acesso_e_a_configurar_salvam_do_mesmo_jeito(self):
        dados = {"pdpj_cpf": CPF_OK, "pdpj_senha": VALOR_A, "pdpj_totp": TOTP_PDPJ, "cert_senha": VALOR_B, "totp_secret": TOTP_JUS,
                 "revisor": "Maria Teste", "identificadores": "Fulano Teste, OAB 12.345"}
        self.post(dados, caminho="/acesso")
        pelo_acesso, cfg_acesso = dict(self.cofre), comum.load_json(comum.CONFIG_FILE, {})
        self.cofre.clear()
        comum.CONFIG_FILE.unlink()
        self.post(dados)
        self.assertEqual(self.cofre, pelo_acesso)
        self.assertEqual(comum.load_json(comum.CONFIG_FILE, {}), cfg_acesso)

    # --- segredos nunca voltam ---

    def test_nenhum_segredo_volta_para_a_pagina(self):
        self.preencher_tudo()
        p = self.pagina()
        for segredo in (CPF_DIGITOS, CPF_OK, VALOR_A, VALOR_B, TOTP_PDPJ, TOTP_JUS):
            self.assertNotIn(segredo, p)
        for campo in ("pdpj_cpf", "pdpj_senha", "pdpj_totp", "cert_senha", "totp_secret"):
            m = re.search(rf"<input [^>]*name='{campo}'[^>]*>", p)
            self.assertIsNotNone(m, campo)
            self.assertIn("type='password'", m.group(0))
            self.assertNotIn("value=", m.group(0))
        cfg = comum.CONFIG_FILE.read_text(encoding="utf-8")
        for segredo in (CPF_DIGITOS, VALOR_A, VALOR_B, TOTP_PDPJ, TOTP_JUS):
            self.assertNotIn(segredo, cfg)

    def test_nem_no_endereco_do_redirecionamento(self):
        r = self.post({"pdpj_cpf": CPF_OK, "pdpj_senha": VALOR_A, "pdpj_totp": TOTP_PDPJ, "cert_senha": VALOR_B, "passo": "2"})
        for segredo in (CPF_DIGITOS, CPF_OK, VALOR_A, VALOR_B, TOTP_PDPJ):
            self.assertNotIn(segredo, r.headers["Location"])

    def test_codigo_de_conferencia_de_cada_autenticador(self):
        self.preencher_tudo()
        p = self.pagina()
        self.assertIn("Código de agora, gerado com o segredo do PDPJ guardado", p)
        self.assertIn("Código de agora, gerado com o segredo do jus.br guardado", p)
        self.assertEqual(p.count("Código de agora"), 2)
        self.assertIn(f"<b>{acesso.codigo_totp_atual(TOTP_PDPJ)}</b>", p)
        self.assertIn(f"<b>{acesso.codigo_totp_atual(TOTP_JUS)}</b>", p)

    def test_sem_segredo_nao_mostra_codigo(self):
        self.assertNotIn("Código de agora", self.pagina())

    # --- testes de login e trava ---

    def test_teste_desligado_enquanto_faltam_os_dados(self):
        p = self.pagina()
        self.assertIn("disabled", self.botao_testar_pdpj(p))
        self.assertIn("Teste desligado", p)
        self.assertRegex(p, r"<button disabled>Testar acesso do jus.br</button>")

    def test_teste_liberado_com_os_dados_salvos(self):
        self.preencher_tudo()
        p = self.pagina()
        self.assertNotIn("disabled", self.botao_testar_pdpj(p))
        self.assertRegex(p, r"<button >Testar acesso do jus.br</button>")
        self.assertEqual(self.selos(p)[5], "pronto ✓")

    def test_com_trava_o_botao_fica_desligado_e_mostra_por_que(self):
        self.preencher_tudo()
        pdpj.travar("recusado", "Credenciais inválidas")
        p = self.pagina()
        self.assertIn("disabled", self.botao_testar_pdpj(p))
        self.assertIn("Nova tentativa bloqueada", p)
        self.assertIn("recusado", p)
        self.assertIn("Liberar nova tentativa", p)
        self.assertIn("name='volta' value='/configurar'", p)

    def test_com_trava_o_teste_nao_dispara_nada_e_volta_para_a_tela(self):
        self.preencher_tudo()
        pdpj.travar("recusado", "x")
        with mock.patch("subprocess.Popen", side_effect=AssertionError("não deveria iniciar o teste")):
            r = self.post({"tipo": "teste_pdpj", "volta": "/configurar"}, caminho="/tarefa")
        self.assertTrue(r.headers["Location"].startswith("/configurar?msg="))
        self.assertIn("Teste não iniciado", self.pagina(r.headers["Location"]))

    def test_um_clique_e_uma_tentativa_e_a_tela_nao_repete(self):
        self.preencher_tudo()
        with mock.patch("subprocess.Popen", return_value=FalsoProc()) as popen:
            r = self.post({"tipo": "teste_pdpj", "volta": "/configurar"}, caminho="/tarefa")
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/configurar"))
            for _ in range(3):                           # abrir/atualizar a tela não dispara nada
                p = self.pagina()
            self.assertEqual(popen.call_count, 1)
            self.assertIn("--testar", popen.call_args.args[0][-1])
            self.assertIn("pdpj.py", popen.call_args.args[0][-2])
            self.assertIn("disabled", self.botao_testar_pdpj(p))         # enquanto roda, o botão fica desligado
            r2 = self.post({"tipo": "teste_pdpj", "volta": "/configurar"}, caminho="/tarefa")   # segundo clique: recusado
            self.assertEqual(popen.call_count, 1)
            self.assertIn("Já há uma tarefa em andamento", self.pagina(r2.headers["Location"]))
        self.assertIn("data-rodando", p)

    def test_teste_do_jusbr_e_instalar_ia_usam_a_tarefa_de_sempre(self):
        self.preencher_tudo()
        with mock.patch("subprocess.Popen", return_value=FalsoProc()) as popen:
            r = self.post({"tipo": "teste_acesso", "volta": "/configurar"}, caminho="/tarefa")
        self.assertEqual(r.headers["Location"], "/configurar")
        self.assertIn("coletor.py", popen.call_args.args[0][-2])
        self.base.TAREFA.clear()
        with mock.patch("subprocess.Popen", return_value=FalsoProc()) as popen:
            r = self.post({"tipo": "ia", "volta": "/configurar"}, caminho="/tarefa")
        self.assertEqual(r.headers["Location"], "/configurar")
        self.assertIn("ia_local.py", popen.call_args.args[0][-2])

    def test_volta_so_aceita_a_propria_tela(self):
        with mock.patch("subprocess.Popen", return_value=FalsoProc()):
            r = self.post({"tipo": "teste_acesso", "volta": "https://exemplo.invalido/"}, caminho="/tarefa")
        self.assertEqual(r.headers["Location"], "/acesso")           # sem o campo (ou com outro valor), o comportamento antigo

    def test_liberar_pela_tela_volta_para_ca(self):
        pdpj.travar("recusado", "x")
        r = self.post({"volta": "/configurar"}, caminho="/acesso/pdpj/liberar")
        self.assertTrue(r.headers["Location"].startswith("/configurar?msg="))
        self.assertIsNone(pdpj.trava())

    def test_mostra_o_andamento_da_tarefa_em_curso(self):
        log = TMP / "log-configurar.txt"
        log.write_text("Baixando o modelo ficticio... 40%", encoding="utf-8")
        self.base.TAREFA.update(proc=FalsoProc(), log=str(log), descricao="Instalação da IA local", nome="-", inicio="10:00")
        p = self.pagina()
        self.assertIn("Baixando o modelo ficticio... 40%", p)
        self.assertIn("data-rodando", p)
        self.assertRegex(p, r"<button class='principal' disabled>Instalar IA local</button>")

    # --- IA ---

    def test_botao_de_instalar_some_quando_a_ia_local_esta_pronta(self):
        self.assertIn("Instalar IA local", self.pagina())
        self.ia = dict(COM_IA)
        p = self.pagina()
        self.assertNotIn("Instalar IA local", p)
        self.assertIn("A IA local está pronta", p)

    def test_aviso_de_provedor_externo(self):
        p = self.pagina()
        self.assertIn("provedor externo envia o texto dos documentos", p)

    # --- atalhos ---

    def test_atalhos_no_menu_no_aviso_e_no_inicio(self):
        inicio = self.pagina("/inicio")
        self.assertRegex(inicio, r"<a class='item destaque'[^>]*href='/configurar'")                   # menu lateral
        self.assertIn("aria-label='Configurar tudo'", inicio)
        self.assertRegex(inicio, r"<div class='alerta aviso-topo'>Falta configurar o acesso[^<]*<a href='/configurar'>Configurar tudo</a>")
        self.assertIn("Primeiros passos", inicio)
        self.assertRegex(inicio, r"<a class='ini-botao principal' href='/configurar'>Configurar tudo</a>")   # cartão e pílula do Início
        self.assertGreaterEqual(inicio.count("href='/configurar'"), 4)

    def test_na_propria_tela_o_aviso_some_e_o_menu_marca_a_tela(self):
        p = self.pagina()
        self.assertNotIn("Falta configurar o acesso", p)
        self.assertRegex(p, r"<a class='item destaque ativo'[^>]*aria-current=page")

    def test_atalho_do_inicio_com_relatorio(self):
        comum.usar_projeto(comum.criar_projeto("Relatório fictício"))
        p = self.pagina("/inicio")
        self.assertIn("href='/configurar'>Configurar tudo</a>", p)

    def test_aviso_some_do_inicio_quando_o_acesso_esta_pronto(self):
        self.preencher_tudo()
        p = self.pagina("/inicio")
        self.assertNotIn("Falta configurar o acesso", p)
        self.assertIn("href='/configurar'", p)           # o menu continua oferecendo a tela

    def test_a_tela_acesso_tem_o_link_e_continua_existindo(self):
        p = self.pagina("/acesso")
        self.assertIn("<h1>Acesso e escritório</h1>", p)
        self.assertIn("href='/configurar'>Configurar tudo</a>", p)


if __name__ == "__main__":
    unittest.main()
