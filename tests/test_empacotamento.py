"""Empacotamento, dependências e documentação (teste transversal do WS-13).

1. `empacotar.sh` roda numa CÓPIA do repositório (nada é gravado em dist/ de verdade) e gera um pacote limpo:
   o que deve entrar entra (src/modelos/, README, guia, testes), o que não deve fica fora (spikes/, .claude/,
   projetos/, config.json, documentos internos de coordenação) e o pacote é RECUSADO quando contém número de
   processo fora do permitido (inclusive dentro de .docx/.xlsx), nome de cliente cadastrado, segredo, certificado
   ou referência externa em HTML de modelo.
2. Dependências: todo módulo de terceiros importado por `src/` e `tests/` consta no `requirements.txt`, com versão
   mínima.
3. Documentação: README e guia existem, citam os quatro fluxos e a situação por plataforma (Windows "não
   testado"), e os links relativos apontam para arquivos que existem (links para entregas de outros workstreams
   ainda ausentes são pulados com mensagem).

Pulado sem `bash`/`python3` no PATH (nunca no Mac). Não usa rede.

    python3 -m unittest tests/test_empacotamento.py -v
"""
import ast
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transversal as T  # noqa: E402  (isolamento antes de tudo)
import ficticio  # noqa: E402

RAIZ = T.RAIZ
BASH = shutil.which("bash")


# ------------------------------------------------------------------ 1. empacotar.sh

@unittest.skipUnless(BASH and shutil.which("python3"), "precisa de bash e python3 no PATH")
class Empacotar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="empacotar-")
        self.copia = Path(self.tmp.name) / "repo"
        for rel in T.arquivos_do_projeto():
            destino = self.copia / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RAIZ / rel, destino)
        # o que o git não versiona mas o script precisa tratar como "dados do computador"
        for pasta in ("spikes", ".claude", "projetos", "data", "ensaio"):
            (self.copia / pasta).mkdir(exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def empacotar(self):
        r = subprocess.run([BASH, "empacotar.sh"], cwd=self.copia, capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def zip_path(self):
        return self.copia / "dist" / "relatorio-andamentos.zip"

    def nomes_no_zip(self):
        with zipfile.ZipFile(self.zip_path()) as z:
            return {n.removeprefix("relatorio-andamentos/") for n in z.namelist()}

    def plantar(self, relativo, conteudo):
        alvo = self.copia / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(conteudo, bytes):
            alvo.write_bytes(conteudo)
        else:
            alvo.write_text(conteudo, encoding="utf-8")

    def assert_recusado(self, trecho=None):
        rc, saida = self.empacotar()
        self.assertNotEqual(rc, 0, "o pacote devia ter sido recusado:\n" + saida)
        self.assertFalse(self.zip_path().exists(), "o .zip não pode existir quando o pacote é recusado")
        self.assertIn("ATENÇÃO", saida)
        if trecho:
            self.assertIn(trecho, saida)

    # -- pacote limpo

    def test_pacote_limpo_com_o_que_deve_entrar_e_sem_o_que_nao_deve(self):
        # planta o que NÃO pode ir (dados do computador, protótipos, internos) e o que deve ir
        self.plantar("projetos/rel1/clientes.json", json.dumps({"clientes": [{"nome": "Cliente Exemplo 01 Ltda"}]}))
        self.plantar("projetos/rel1/data/carteira.json", "[]")
        self.plantar("config.json", '{"revisor": "Fulano Exemplo"}')
        self.plantar("spikes/s9/x.py", "print('protótipo')\n")
        self.plantar(".claude/settings.json", "{}")
        self.plantar("src/__pycache__/x.cpython-313.pyc", b"\0\0")
        self.plantar("tests/fixtures/enorme.bin", b"x" * 1_100_000)
        rc, saida = self.empacotar()
        self.assertEqual(rc, 0, saida)
        self.assertTrue(self.zip_path().exists())
        nomes = self.nomes_no_zip()
        for deve in ("README.md", "requirements.txt", "empacotar.sh", "config.exemplo.json", "src/comum.py",
                     "src/taxonomia.py", "tests/test_confidencialidade.py", "tests/confidencialidade_regras.py"):
            self.assertIn(deve, nomes, f"{deve} faltou no pacote")
        for p in T.arquivos_do_projeto():
            if p.parts[:2] in (("src", "modelos"), ("docs", "fase2")) and p.name not in ("BRIEFING-AGENTES.md", "WORKSTREAMS.md"):
                self.assertIn(p.as_posix(), nomes, f"{p} (novo diretório) não entrou no pacote")
        proibidos = [n for n in nomes if n.startswith(("spikes/", ".claude/", ".git/", "dist/", "data/", "ensaio/"))
                     or n in ("config.json", "revisar.command", "cadastro.command", "docs/fase2/BRIEFING-AGENTES.md",
                              "docs/fase2/WORKSTREAMS.md", "tests/fixtures/enorme.bin")
                     or "__pycache__" in n or n.endswith(".pyc") or n.startswith("projetos/") and n != "projetos/"]
        self.assertEqual(proibidos, [], f"entrou no pacote o que devia ficar de fora: {proibidos[:5]}")
        self.assertIn("projetos/", nomes, "a pasta projetos/ vazia deve existir no pacote")
        cfg = json.loads(zipfile.ZipFile(self.zip_path()).read("relatorio-andamentos/config.exemplo.json"))
        self.assertEqual((cfg["identificadores_escritorio"], cfg["revisor"]), ([], ""))

    def test_pacote_mantem_permissao_de_execucao_dos_atalhos(self):
        rc, saida = self.empacotar()
        self.assertEqual(rc, 0, saida)
        with zipfile.ZipFile(self.zip_path()) as z:
            info = z.getinfo("relatorio-andamentos/empacotar.sh")
            self.assertTrue((info.external_attr >> 16) & 0o100, "empacotar.sh perdeu a permissão de execução no .zip")

    def test_o_repositorio_original_nao_e_tocado(self):
        """O teste trabalha numa cópia: o dist/ do repositório de verdade não é criado nem alterado."""
        existia = (RAIZ / "dist").exists()
        rc, saida = self.empacotar()
        self.assertEqual(rc, 0, saida)
        self.assertEqual((RAIZ / "dist").exists(), existia)

    # -- recusas

    def test_recusa_numero_de_processo_fora_do_permitido(self):
        self.plantar("src/nota.txt", f"processo {ficticio.numero_ficticio(7)}\n")
        self.assert_recusado("numero_de_processo")

    def test_aceita_so_os_numeros_permitidos(self):
        self.plantar("src/nota.txt", f"{ficticio.numero_ficticio(0)} e 0000000-00.0000.0.00.0000\n")
        rc, saida = self.empacotar()
        self.assertEqual(rc, 0, saida)

    def test_recusa_numero_dentro_de_docx_ou_xlsx(self):
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/sharedStrings.xml", f"<sst><si><t>{ficticio.numero_ficticio(11)}</t></si></sst>")
        self.plantar("src/modelos/xlsx_b/modelo-sujo.xlsx", buf.getvalue())
        self.assert_recusado("numero_de_processo")

    def test_recusa_nome_de_cliente_cadastrado_neste_computador(self):
        nome = "Quixote" + "lândia Partici" + "pações Ltda"       # montado em tempo de execução
        self.plantar("projetos/rel1/clientes.json", json.dumps({"clientes": [{"nome": nome, "variacoes": []}]}))
        rc, saida = self.empacotar()                              # só em projetos/ (fora do pacote): passa
        self.assertEqual(rc, 0, saida)
        self.plantar("docs/exemplo-vazado.md", f"Atendemos a {nome.upper()} no mês passado.\n")
        self.assert_recusado("nome_cadastrado")

    def test_recusa_segredo_e_certificado(self):
        self.plantar("src/chaves.py", 'ANTHROPIC = "' + "sk-ant-" + "Qz9" * 12 + '"\n')
        self.assert_recusado("segredo")

    def test_recusa_certificado(self):
        self.plantar("src/cert.pfx", b"\x30\x82\x01")
        self.assert_recusado("arquivo_proibido")

    def test_recusa_referencia_externa_em_html_de_modelo(self):
        self.plantar("src/modelos/dashboard/painel.html", "<html><script src='https://cdn.exemplo.test/lib.js'></script></html>")
        self.assert_recusado("referência externa")

    def test_recusa_erro_de_sintaxe(self):
        self.plantar("src/quebrado.py", "def x(:\n")
        rc, saida = self.empacotar()
        self.assertNotEqual(rc, 0, saida)
        self.assertIn("erro de sintaxe", saida)


# ------------------------------------------------------------------ 2. dependências

IMPORT_PARA_PACOTE = {"docx": "python-docx", "yaml": "pyyaml", "PIL": "pillow", "bs4": "beautifulsoup4",
                      "dateutil": "python-dateutil", "win32com": "pywin32", "win32api": "pywin32", "cv2": "opencv-python"}


def _normalizar_pacote(nome):
    return re.sub(r"[-_.]+", "-", nome).lower()


def requisitos():
    """{pacote normalizado: linha} do requirements.txt."""
    saida = {}
    for linha in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linha = linha.split("#")[0].strip()
        if linha:
            nome = re.split(r"[<>=!~;\[ ]", linha, maxsplit=1)[0]
            saida[_normalizar_pacote(nome)] = linha
    return saida


def imports_de_terceiros(pastas=("src", "tests")):
    """{módulo importado: {arquivos}} dos módulos que não são da biblioteca padrão nem do próprio projeto."""
    locais = {p.stem for p in (RAIZ / "src").rglob("*.py")} | {p.name for p in (RAIZ / "src").rglob("*") if p.is_dir()}
    locais |= {p.stem for p in (RAIZ / "tests").glob("*.py")}
    achados = {}
    for pasta in pastas:
        for arquivo in (RAIZ / pasta).rglob("*.py"):
            try:
                arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for no in ast.walk(arvore):
                if isinstance(no, ast.Import):
                    nomes = [a.name.split(".")[0] for a in no.names]
                elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                    nomes = [no.module.split(".")[0]]
                else:
                    continue
                for n in nomes:
                    if n not in sys.stdlib_module_names and n not in locais:
                        achados.setdefault(n, set()).add(arquivo.relative_to(RAIZ).as_posix())
    return achados


class Dependencias(unittest.TestCase):
    def test_todo_import_de_terceiros_esta_no_requirements(self):
        reqs = requisitos()
        faltam = {}
        for modulo, arquivos in imports_de_terceiros().items():
            pacote = _normalizar_pacote(IMPORT_PARA_PACOTE.get(modulo, modulo))
            if pacote not in reqs:
                faltam[modulo] = sorted(arquivos)[:2]
        self.assertEqual(faltam, {}, "módulo de terceiros usado sem constar em requirements.txt "
                                     "(acrescente com versão mínima, ou mapeie em IMPORT_PARA_PACOTE): " + str(faltam))

    def test_requirements_com_versao_minima(self):
        sem_versao = [linha for linha in requisitos().values() if not re.search(r">=\s*\d", linha)]
        self.assertEqual(sem_versao, [], "dependência sem versão mínima: " + str(sem_versao))

    def test_dependencias_da_fase2_declaradas(self):
        reqs = requisitos()
        for pacote in ("python-docx", "openpyxl", "playwright", "flask", "lxml"):
            self.assertIn(pacote, reqs, f"{pacote} deveria constar em requirements.txt")

    def test_docx_e_lxml_instalados_no_ambiente_de_teste(self):
        """Se o requirements.txt manda instalar, o ambiente de teste do coordenador tem de importar."""
        for modulo in ("docx", "lxml", "openpyxl"):
            self.assertIsNotNone(importlib.util.find_spec(modulo), f"{modulo} não instalado neste ambiente")


# ------------------------------------------------------------------ 3. documentação

# Entregas de outros workstreams: o link só passa a valer quando o arquivo chegar (pulado até lá).
ARQUIVOS_DE_OUTROS_WS = {"docs/confidencialidade-ia.md": "WS-18", "docs/pedidos-iniciais.md": "WS-16",
                         "docs/fase2/conferencia-docx.md": "WS-6", "docs/fase2/conferencia-xlsx.md": "WS-7"}
LINK_MD = re.compile(r"\]\((?!https?:|#|mailto:)([^)\s#]+)(?:#[^)]*)?\)")


def arvore_do_readme(texto):
    """Caminhos citados no bloco de árvore do README ('├── nome  /  outro   descrição'), sem placeholders (<...>)."""
    bloco = re.search(r"```\nrelatorio-andamentos/\n(.*?)\n```", texto, re.S)
    if not bloco:
        return []
    pilha, caminhos = [], []
    for linha in bloco.group(1).splitlines():
        m = re.match(r"^((?:│   |    )*)(?:├── |└── )(.*)$", linha)
        if not m:
            continue
        profundidade = len(m.group(1)) // 4
        for parte in re.split(r"\s+/\s+", m.group(2)):
            nome = re.split(r"\s{2,}", parte.strip())[0]
            if not nome or "<" in nome:
                continue
            caminhos.append("/".join(pilha[:profundidade] + [nome.rstrip("/")]))
            if nome.endswith("/"):
                pilha[profundidade:] = [nome.rstrip("/")]
    return caminhos


class Documentacao(unittest.TestCase):
    def texto(self, relativo):
        caminho = RAIZ / relativo
        self.assertTrue(caminho.exists(), f"{relativo} não existe")
        return caminho.read_text(encoding="utf-8")

    def test_quatro_fluxos_no_readme_e_no_guia(self):
        for arquivo in ("README.md", "docs/guia-fase2.md"):
            texto = self.texto(arquivo).lower()
            for fluxo in ("importar relatórios existentes", "elaborar relatório inicial", "atualizar relatório",
                          "migrar de modelo"):
                self.assertIn(fluxo, texto, f"{arquivo} não cita o fluxo '{fluxo}'")

    def test_readme_declara_situacao_por_plataforma_e_ia_externa(self):
        texto = " ".join(self.texto("README.md").lower().split())      # junta as quebras de linha
        self.assertRegex(texto, r"windows.{0,300}n[ãa]o testad", "README tem de dizer que o Windows não foi testado")
        self.assertIn("ia externa", texto)
        self.assertRegex(texto, r"salvo quando você ativa", "a promessa de confidencialidade precisa da ressalva da IA externa")

    def test_guia_tem_secao_de_problemas(self):
        texto = self.texto("docs/guia-fase2.md").lower()
        self.assertIn("o que fazer quando algo dá errado", texto)

    def test_links_relativos_existem(self):
        for arquivo in ("README.md", "docs/guia-fase2.md", "docs/fase2/STATUS.md"):
            base = (RAIZ / arquivo).parent
            for destino in sorted(set(LINK_MD.findall(self.texto(arquivo)))):
                with self.subTest(arquivo=arquivo, link=destino):
                    alvo = (base / destino).resolve()
                    relativo = alvo.relative_to(RAIZ.resolve()).as_posix() if str(alvo).startswith(str(RAIZ.resolve())) else destino
                    if not alvo.exists() and relativo in ARQUIVOS_DE_OUTROS_WS:
                        self.skipTest(f"{relativo} ainda não existe ({ARQUIVOS_DE_OUTROS_WS[relativo]}); reativar na integração")
                    self.assertTrue(alvo.exists(), f"link quebrado em {arquivo}: {destino}")

    def test_status_cobre_todos_os_modulos_da_tabela(self):
        texto = self.texto("docs/fase2/STATUS.md")
        for ws, modulo, arquivo, _contrato in T.MODULOS:
            self.assertIn(arquivo, texto, f"docs/fase2/STATUS.md não cita {arquivo} ({ws})")

    def test_arvore_do_readme_cita_os_diretorios_de_primeiro_nivel(self):
        texto = self.texto("README.md")
        for pasta in sorted(p.name for p in RAIZ.iterdir() if p.is_dir() and p.name in ("src", "tests", "docs")):
            self.assertIn(pasta + "/", texto, f"README não cita {pasta}/ na árvore de arquivos")

    def test_arvore_do_readme_so_cita_o_que_existe(self):
        """Cada caminho da árvore do README existe; os que dependem de entrega de outro workstream são pulados."""
        ainda_nao = {arquivo for _ws, _m, arquivo, _c in T.MODULOS} | set(ARQUIVOS_DE_OUTROS_WS)
        ainda_nao |= {"src/leitores", "src/escritores", "src/modelos"}
        caminhos = arvore_do_readme(self.texto("README.md"))
        self.assertGreater(len(caminhos), 15, "não consegui ler a árvore de arquivos do README")
        for caminho in caminhos:
            with self.subTest(caminho=caminho):
                if not (RAIZ / caminho).exists() and caminho in ainda_nao:
                    self.skipTest(f"{caminho} ainda não existe (entrega de outro workstream); reativar na integração")
                self.assertTrue((RAIZ / caminho).exists(), f"a árvore do README cita {caminho}, que não existe")


if __name__ == "__main__":
    unittest.main()
