"""Testes do assistente dos fluxos (WS-9): tela inicial com os quatro fluxos, importar (conferência da
migração), migrar de modelo (mapeamento), elaborar inicial e atualizar (modo contínuo e imediato, estimativa,
progresso, pausar, retomar, parar), entregas e perfil. Tudo com `app.test_client()`, dados fictícios, sem rede.

Os módulos dos outros workstreams (leitores, consolidar, fila, escritores, qualidade) ainda estão sendo
construídos em paralelo: aqui entram STUBS (módulos falsos colocados em sys.modules durante cada teste, com a
interface de docs/fase2/CONTRATOS.md). O coletor é o `ColetorSimulado` de src/simulado.py. Quando os módulos
reais chegarem, estes testes continuam valendo, porque os stubs têm precedência dentro do teste.

Arquivos "de relatório" são fixtures: `FIXTURE:` + JSON de um RelatorioLido (o leitor falso o devolve como está).
Listas (.txt/.csv/.xlsx) passam por `carteira.ler_lista` de verdade.

    python3 -m unittest tests/test_painel_assistente.py -v
"""
import io
import json
import re
import shutil
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import ficticio  # noqa: E402
import simulado  # noqa: E402
import carteira as cart  # noqa: E402
import comum  # noqa: E402
import ficha  # noqa: E402
from flask import Flask  # noqa: E402

TOKEN = "token-de-teste"
PADRAO_DE_PAGINA_LIVRE = re.compile(r"(src|href)=['\"]https?://", re.I)


# ================================================================ stubs dos outros workstreams

def _processo_lido(f, com_andamentos=True):
    campos = {n: {"valor": c["valor"], "origem": c["origem"] if c["origem"] == "humano" else "migrado"}
              for n, c in f.get("campos", {}).items()}
    return {"numero": f["numero"], "vinculados": [dict(v) for v in f.get("vinculados", [])], "campos": campos,
            "andamentos_texto": ficticio.gerar_historico(f) if com_andamentos else "",
            "ultimo_andamento": ficha.obter(f, "ultimo_andamento"), "origem_no_arquivo": "linha 2"}


def relatorio(fichas, formato="xlsx_b", data_base="2026-09-18", cliente=None, avisos=(), sem_destino=(), mapeamento=None,
              com_andamentos=True):
    rel = {"formato": formato, "cliente": cliente, "data_base": data_base,
           "processos": [_processo_lido(f, com_andamentos) for f in fichas], "parametros": {},
           "colunas_sem_destino": list(sem_destino), "avisos": list(avisos)}
    if mapeamento is not None:
        rel["mapeamento"] = mapeamento
    return rel


def gravar_fixture(caminho, rel, **extra):
    Path(caminho).write_bytes(b"FIXTURE:" + json.dumps({"rel": rel, **extra}, ensure_ascii=False).encode())
    return Path(caminho)


def _payload(caminho):
    dados = Path(caminho).read_bytes()
    if dados.startswith(b"FIXTURE:"):
        return json.loads(dados[8:].decode())
    return None


def stub_leitores():
    mod = types.ModuleType("leitores")

    def detectar(caminho):
        caminho = Path(caminho)
        p = _payload(caminho)
        if p is not None:
            return p["rel"]["formato"]
        if caminho.suffix.lower() in (".txt", ".csv", ".md"):
            return "lista"
        if caminho.suffix.lower() == ".xlsx":
            try:
                import openpyxl
                openpyxl.load_workbook(caminho).close()
                return "lista"
            except Exception:
                return "desconhecido"
        return "desconhecido"

    def ler(caminho, formato=None, mapeamento=None):
        caminho = Path(caminho)
        p = _payload(caminho)
        if p is not None:
            if p.get("erro"):
                raise ValueError(p["erro"])
            rel = dict(p["rel"], arquivo=caminho.name)
            if mapeamento is not None and p.get("linhas"):
                rel["processos"] = []
                for linha in p["linhas"]:
                    numero_col = next((c for c, campo in mapeamento.items() if campo == "numero"), None)
                    if not numero_col:
                        continue
                    campos = {campo: {"valor": linha[c], "origem": "migrado"} for c, campo in mapeamento.items()
                              if campo not in ("numero", "andamentos") and linha.get(c)}
                    rel["processos"].append({"numero": linha[numero_col], "vinculados": [], "campos": campos,
                                             "andamentos_texto": "", "ultimo_andamento": None, "origem_no_arquivo": "linha"})
            mod.chamadas_ler.append({"formato": formato, "mapeamento": mapeamento})
            return rel
        registros, invalidos = cart.ler_lista(str(caminho))
        processos = [{"numero": r["numero"], "vinculados": [],
                      "campos": {k: {"valor": r[k], "origem": "migrado"} for k in ("cliente", "polo_cliente", "parte_contraria", "responsavel") if r.get(k)},
                      "andamentos_texto": "", "ultimo_andamento": None, "origem_no_arquivo": "linha"} for r in registros]
        avisos = [{"nivel": "erro", "codigo": "numero_invalido", "onde": caminho.name,
                   "mensagem": f"Número com dígito verificador errado: {n}", "candidatos": []} for n in invalidos]
        return {"formato": "lista", "arquivo": caminho.name, "cliente": None, "data_base": None, "processos": processos,
                "parametros": {}, "colunas_sem_destino": [], "avisos": avisos}

    mod.detectar, mod.ler, mod.chamadas_ler = detectar, ler, []
    return mod


def stub_consolidar():
    mod = types.ModuleType("consolidar")

    def consolidar(fichas):
        grupos = {}
        for f in fichas:
            nome = ficha.obter(f, "cliente") or ""
            chave = re.sub(r"\b(ltda|s a)\b", "", comum.normalizar(nome)).strip(" .")
            grupos.setdefault(chave, set()).add(nome)
        avisos = [{"nivel": "atencao", "codigo": "grafias_cliente", "onde": "clientes",
                   "mensagem": "O mesmo cliente aparece escrito de jeitos diferentes.", "candidatos": sorted(nomes)}
                  for nomes in grupos.values() if len(nomes) > 1]
        return fichas, avisos

    mod.consolidar = consolidar
    return mod


def stub_fila():
    """Fila falsa com a interface do CONTRATOS §6 (em memória, uma por relatório)."""
    mod = types.ModuleType("fila")
    mod.ESTADOS, mod.chamadas_enfileirar, mod.MEDIA_S = {}, [], 90.0

    class Fila:
        def __init__(self, projeto):
            self.projeto = projeto
            self.s = mod.ESTADOS.setdefault(projeto, {"itens": {}, "pausada": False, "parar": False, "janela": None})

        def definir_janela(self, inicio, fim):
            self.s["janela"] = (inicio, fim)

        def enfileirar(self, numeros, *, modo="continuo", profundidade="padrao", prioridade=0, desde=None):
            mod.chamadas_enfileirar.append({"numeros": list(numeros), "modo": modo, "profundidade": profundidade, "desde": desde})
            for n in numeros:
                if self.s["itens"].get(n, {}).get("estado") != "coletado":
                    self.s["itens"][n] = {"numero": n, "estado": "pendente", "desde": desde, "profundidade": profundidade, "erro": None}

        def resumo(self):
            contagem = {k: sum(1 for i in self.s["itens"].values() if i["estado"] == k)
                        for k in ("pendente", "coletando", "coletado", "erro", "manual")}
            return {"total": len(self.s["itens"]), **contagem, "estimativa_s": contagem["pendente"] * mod.MEDIA_S}

        def pausar(self):
            self.s["pausada"] = True

        def retomar(self):
            self.s["pausada"], self.s["parar"] = False, False

        def parar_com_seguranca(self):
            self.s["parar"] = True

        def itens(self):
            return [dict(i) for i in self.s["itens"].values()]

    def rodar_fila(fila, coletor, ao_progresso=None):
        s = fila.s
        while not (s["pausada"] or s["parar"]):
            pendentes = [i for i in s["itens"].values() if i["estado"] == "pendente"]
            if not pendentes:
                break
            item = pendentes[0]
            item["estado"] = "coletando"
            r = coletor.coletar({"numero": item["numero"]}, item["profundidade"], item["desde"])
            erro = r.get("erro")
            if not erro:
                item["estado"] = "coletado"
            else:
                item["erro"] = erro
                item["estado"] = "manual" if erro["codigo"] in ("captcha", "segredo", "nao_encontrado") else "erro"
            if ao_progresso:
                ao_progresso(fila.resumo())

    def cobertura(projeto):
        return {"TJCE": {"coletado": 1, "so_djen": 0, "manual": 0}}

    class ColetorReal:
        def __init__(self):
            raise RuntimeError("o coletor real não deve ser criado nos testes")

    mod.Fila, mod.rodar_fila, mod.cobertura, mod.ColetorReal = Fila, rodar_fila, cobertura, ColetorReal
    return mod


def stub_escritor(rotulo, extensao):
    mod = types.ModuleType(f"escritores.{rotulo}")
    mod.chamadas = []

    def gravar(molde, estado, destino, **opcoes):
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({"cliente": estado["cliente"], "fichas": len(estado["fichas"]),
                                       "eventos": [e["id"] for e in estado["eventos"]]}), encoding="utf-8")
        mod.chamadas.append({"molde": molde, "estado": estado, "destino": destino, "opcoes": opcoes})
        aprovados = {e["numero"] for e in estado["eventos"]}
        return {"destino": destino, "processos_atualizados": sorted(aprovados), "processos_novos": [], "ignorados": [],
                "mudancas": [], "avisos": [], "textos_gravados": {f["numero"]: f"Texto gravado de {f['numero']}" for f in estado["fichas"]}}

    mod.gravar = gravar
    if rotulo == "dashboard":                          # CONTRATOS §5: gravar(xlsx, destino, perfil, **opcoes)
        def gravar_painel(xlsx, destino, perfil, **opcoes):
            destino = Path(destino)
            destino.write_text(f"<html>painel de {Path(xlsx).name}</html>", encoding="utf-8")
            mod.chamadas.append({"molde": xlsx, "estado": None, "destino": destino, "opcoes": opcoes, "perfil": perfil})
            return {"destino": destino, "processos_atualizados": [], "processos_novos": [], "ignorados": [], "mudancas": [], "avisos": []}
        mod.gravar = gravar_painel
    return mod


def stub_qualidade():
    mod = types.ModuleType("qualidade")
    mod.verificar = lambda fichas, perfil: [{"codigo": "exemplo", "gravidade": "atencao", "numeros": [fichas[0]["numero"]] if fichas else [],
                                             "mensagem": "Achado de teste <b>escapado</b>.", "sugestao": "Confira."}]
    return mod


def todos_os_stubs():
    pacote = types.ModuleType("escritores")
    return {"leitores": stub_leitores(), "consolidar": stub_consolidar(), "fila": stub_fila(), "qualidade": stub_qualidade(),
            "escritores": pacote, "escritores.docx_a": stub_escritor("docx_a", ".docx"),
            "escritores.xlsx_b": stub_escritor("xlsx_b", ".xlsx"), "escritores.dashboard": stub_escritor("dashboard", ".html")}


# ================================================================ base dos testes

class Base(unittest.TestCase):
    N, CLIENTES = 30, 2

    def setUp(self):
        from painel import assistente, base, entregas, migracao, perfil
        self.ass, self.base, self.ent, self.mig, self.per = assistente, base, entregas, migracao, perfil
        self.fichas = ficticio.gerar_carteira(self.N, clientes=self.CLIENTES, semente=3)
        for f in self.fichas:
            f.pop("linha_de_base", None)
            f["linha_de_base"] = None
        shutil.rmtree(TMP / "projetos-de-teste", ignore_errors=True)       # cada teste começa sem relatórios
        self.ativos = [f for f in self.fichas if f.get("ativo", True)]       # só os ativos entram na coleta
        self.proj = ficticio.criar_projeto_de_teste(self.fichas, nome="Relatório do Teste")
        self.pasta_arquivos = TMP / f"arquivos-{id(self)}"
        self.pasta_arquivos.mkdir(parents=True, exist_ok=True)
        import acesso
        cofre = {"cert_senha": "x", "totp_secret": "y"}
        self.patches = [mock.patch.object(acesso, "obter", lambda chave: cofre.get(chave)),
                        mock.patch.dict(sys.modules, todos_os_stubs()),
                        mock.patch.object(assistente, "INTERVALO_DA_JANELA_S", 0.05)]
        for p in self.patches:
            p.start()
        self.m = {n: sys.modules[n] for n in ("leitores", "fila", "consolidar", "escritores.docx_a", "escritores.xlsx_b",
                                               "escritores.dashboard")}
        self.coletor = None
        assistente.FABRICA_DE_COLETOR = lambda: self.coletor
        self.resetar_execucao()
        base.TAREFA.clear()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        token_ok = base.criar_token_ok(TOKEN)
        for tela in (base, assistente, migracao, entregas, perfil):
            tela.registrar(self.app, TOKEN, base.cabecalho, token_ok)
        self.c = self.app.test_client()
        self.paginas = {}

    def tearDown(self):
        t = self.ass.EXEC["thread"]
        if t is not None and t.is_alive():
            self.ass.EXEC["pedido"] = "parada"
            self.ass._ESPERA.set()
            t.join(5)
        self.resetar_execucao()
        self.ass.FABRICA_DE_COLETOR = None
        self.base.TAREFA.clear()
        for p in reversed(self.patches):
            p.stop()
        ficticio.restaurar_comum()

    # --- apoio

    def resetar_execucao(self):
        e = self.ass.EXEC
        e.update(thread=None, slug=None, fila=None, estado="parado", pedido=None, resumo=None, erro=None, inicio=None,
                 modo="continuo")
        e["log"].clear()

    def get(self, caminho, **kw):
        r = self.c.get(caminho, follow_redirects=kw.pop("seguir", True), **kw)
        texto = r.get_data(as_text=True)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            self.paginas[caminho] = texto
        r.close()
        return r, texto

    def post(self, caminho, dados=None, token=True, seguir=True, **kw):
        corpo = dict(dados or {})
        if token:
            corpo["token"] = TOKEN
        r = self.c.post(caminho, data=corpo, follow_redirects=seguir, **kw)
        texto = r.get_data(as_text=True)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            self.paginas[caminho + " (resposta)"] = texto
        return r, texto

    def arquivo(self, nome, conteudo=b"x"):
        return (io.BytesIO(conteudo), nome)

    def esperar_execucao(self, segundos=20):
        t = self.ass.EXEC["thread"]
        self.assertIsNotNone(t, "a coleta não foi iniciada")
        t.join(segundos)
        self.assertFalse(t.is_alive(), "a coleta não terminou a tempo")

    def fichas_do_projeto(self):
        return ficha.carregar(todas=True)

    def novo_coletor(self, fichas=None, **kw):
        kw.setdefault("taxa_falha", 0.0)
        self.coletor = simulado.ColetorSimulado(fichas or self.fichas, semente=1, pasta=TMP / "docs-sim", **kw)
        return self.coletor


# ================================================================ tela inicial, rotas e proteção

class TelaInicial(Base):
    def test_quatro_botoes(self):
        r, t = self.get("/fluxo")
        self.assertEqual(r.status_code, 200)
        self.assertIn("O que você quer fazer?", t)
        for rotulo, destino in (("Importar relatórios existentes", "/fluxo/importar"), ("Elaborar relatório inicial", "/fluxo/inicial"),
                                ("Atualizar relatório", "/fluxo/atualizar"), ("Migrar de modelo", "/migracao")):
            self.assertIn(rotulo, t)
            self.assertIn(f"href='{destino}'", t)
        self.assertEqual(t.count("class='botao-grande'"), 4)
        self.assertIn("Relatório do Teste", t)
        self.assertIn(f"{self.N} processo(s); {self.N} sem relatório anterior", t)

    def test_subabas_na_barra(self):
        _, t = self.get("/fluxo")
        for rotulo in ("Assistente", "Entregas", "Perfil"):
            self.assertIn(f"<span class='rot'>{rotulo}</span></a>", t)      # menu lateral

    def test_revisao_registra_as_rotas_novas(self):
        import revisao
        regras = {r.rule for r in revisao.app.url_map.iter_rules()}
        for rota in ("/fluxo", "/fluxo/importar", "/fluxo/inicial", "/fluxo/atualizar", "/fluxo/progresso", "/migracao",
                     "/entregas", "/perfil", "/"):
            self.assertIn(rota, regras)

    def test_todo_post_exige_token(self):
        rotas = [r.rule for r in self.app.url_map.iter_rules()
                 if "POST" in r.methods and r.rule.startswith(("/fluxo", "/migracao", "/entregas", "/perfil"))]
        self.assertGreaterEqual(len(rotas), 14)
        for rota in rotas:
            r, _ = self.post(rota, {"lote": "000000000000"}, token=False, seguir=False)
            self.assertEqual(r.status_code, 403, rota)

    def test_sem_relatorio_vai_para_novo(self):
        vazio = TMP / "projetos-vazio-assistente"
        vazio.mkdir(exist_ok=True)
        antes = comum.PROJETOS_DIR, comum.ATUAL_FILE
        comum.PROJETOS_DIR, comum.ATUAL_FILE = vazio, vazio / ".projeto_atual"
        try:
            r, _ = self.get("/", seguir=False)
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/novo"))
            for rota in ("/fluxo", "/fluxo/importar", "/migracao"):          # WS-14: o primeiro uso começa pelo assistente
                r, _ = self.get(rota, seguir=False)
                self.assertEqual(r.status_code, 200, rota)
        finally:
            comum.PROJETOS_DIR, comum.ATUAL_FILE = antes

    def test_lote_invalido_nao_sai_da_pasta(self):
        for lote in ("..", "../..", "zzzzzzzzzzzz", "0" * 12, ""):
            r, _ = self.get(f"/fluxo/importar/conferir?lote={lote}")
            self.assertEqual(r.status_code, 404, lote)

    def test_paginas_sem_javascript_externo_e_com_token_nos_formularios(self):
        for caminho in ("/fluxo", "/fluxo/importar", "/fluxo/inicial", "/fluxo/atualizar", "/fluxo/progresso", "/migracao",
                        "/entregas", "/perfil"):
            self.get(caminho)
        self.assertGreaterEqual(len(self.paginas), 8)
        for caminho, t in self.paginas.items():
            self.assertNotRegex(t, PADRAO_DE_PAGINA_LIVRE, caminho)
            self.assertNotIn("<script src", t, caminho)
            for form in re.findall(r"<form[^>]*method='post'.*?</form>", t, flags=re.S):
                self.assertIn(f"name='token' value='{TOKEN}'", form, caminho)
        _, t = self.get("/fluxo/importar")
        self.assertIn("type='file' name='arquivos' multiple", t)


# ================================================================ importar

class Importar(Base):
    def _arquivos_de_importacao(self):
        """Um xlsx_b, um docx_a, uma lista csv, um .exe, um .docx ilegível e um arquivo vazio."""
        lote_b, lote_a = self.fichas[:10], self.fichas[10:18]
        # o mesmo cliente escrito de dois jeitos: o consolidar (stub) sugere, a pessoa escolhe
        cliente_b = ficha.obter(lote_b[0], "cliente")
        for f in lote_b:
            ficha.definir(f, "cliente", cliente_b, "migrado", forcar=True)
        for f in lote_a:
            ficha.definir(f, "cliente", cliente_b.replace(" Ltda", ""), "migrado", forcar=True)
        rel_b = relatorio(lote_b, "xlsx_b", "2026-09-18", cliente=cliente_b,
                          sem_destino=[{"coluna": "Observação interna", "amostra": ["a", "b"]}],
                          avisos=[{"nivel": "atencao", "codigo": "rotulo_fora_do_vocabulario", "onde": "linha 4",
                                   "mensagem": "Rótulo de matéria fora do padrão.", "candidatos": []}])
        rel_a = relatorio(lote_a, "docx_a", "2026-08-31", cliente=cliente_b.replace(" Ltda", ""))
        pasta = ficticio.gerar_lista_bruta(self.pasta_arquivos, self.fichas[18:], semente=1)
        gravar_fixture(self.pasta_arquivos / "planilha.xlsx", rel_b)
        gravar_fixture(self.pasta_arquivos / "texto.docx", rel_a)
        self.esperado_lista = pasta["csv"]
        return {"arquivos": [self.arquivo("planilha.xlsx", (self.pasta_arquivos / "planilha.xlsx").read_bytes()),
                             self.arquivo("texto.docx", (self.pasta_arquivos / "texto.docx").read_bytes()),
                             self.arquivo("lista.csv", pasta["csv"]["arquivo"].read_bytes()),
                             self.arquivo("programa.exe", b"MZ"),
                             self.arquivo("quebrado.docx", b"lixo que nao e docx"),
                             self.arquivo("vazio.txt", b"")]}, lote_b, lote_a

    def test_fluxo_completo_importar(self):
        dados, lote_b, lote_a = self._arquivos_de_importacao()
        r, t = self.post("/fluxo/importar/enviar", dados, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.request.path, "/fluxo/importar/conferir")
        lote = r.request.args["lote"]
        # o que foi lido
        n_lista = len(self.esperado_lista["validos"])
        total = len(lote_b) + len(lote_a) + n_lista
        self.assertIn(f"Li {total} processo(s) de 3 arquivo(s)", t)
        self.assertIn("data-base 18/09/2026", t)
        for rotulo in ("Relatório em texto (modelo A)", "Planilha (modelo B)", "Lista de números de processo"):
            self.assertIn(rotulo, t)
        # arquivos recusados, cada um com o seu motivo
        self.assertIn("Arquivos que não consegui usar", t)
        self.assertIn("Tipo de arquivo não aceito (.exe)", t)
        self.assertIn("Não reconheci o formato deste arquivo", t)
        self.assertIn("O arquivo está vazio.", t)
        # números inválidos, ambiguidades, sem destino, grafias
        self.assertIn("Números com dígito verificador errado", t)
        self.assertIn(self.esperado_lista["invalidos"][0], t)
        self.assertIn("Informações para conferir", t)
        self.assertIn("Rótulo de matéria fora do padrão.", t)
        self.assertIn("Colunas sem destino", t)
        self.assertIn("Observação interna", t)
        self.assertIn("Nomes escritos de mais de um jeito", t)
        self.assertIn("name='grafia_", t)
        self.assertIn("Clientes encontrados", t)
        self.assertIn(f"{n_lista} processo(s) vieram só como número", t)
        # nada foi criado antes da confirmação
        self.assertEqual(len(comum.projetos()), 1)
        # confirma escolhendo a grafia padronizada
        cliente_padrao = ficha.obter(lote_b[0], "cliente")
        indice = int(re.search(r"name='grafia_(\d+)'", t)[1])
        r, t = self.post("/fluxo/importar/confirmar", {"lote": lote, "nome": "Grupo Importado", "destino": "novo",
                                                       f"grafia_{indice}": cliente_padrao})
        self.assertEqual(r.request.path, "/fluxo")
        self.assertIn(f"Relatório criado: Grupo Importado. {total} processo(s) importado(s).", t)
        self.assertIn("nome(s) padronizado(s)", t)
        self.assertIn(f"{n_lista} processo(s) novos, sem relatório anterior", t)
        # o relatório novo é o ativo e tem fichas, clientes, perfil e arquivos em entrada/
        self.assertEqual(self.c.get_cookie("projeto").value, "grupo-importado")
        self.assertEqual(comum.PROJETO, "grupo-importado")
        fichas = self.fichas_do_projeto()
        self.assertEqual(len(fichas), total)
        com_base = [f for f in fichas if f.get("linha_de_base")]
        self.assertEqual(len(com_base), len(lote_b) + len(lote_a))
        self.assertEqual({ficha.obter(f, "cliente") for f in com_base}, {cliente_padrao})
        por_numero = {f["numero"]: f for f in fichas}
        for original in lote_b:
            f = por_numero[original["numero"]]
            self.assertEqual(f["linha_de_base"]["data_base"], "2026-09-18")
            self.assertEqual(f["linha_de_base"]["arquivo"], "planilha.xlsx")
            self.assertEqual(f["linha_de_base"]["andamentos_texto"], ficticio.gerar_historico(original))
            for campo, c in original["campos"].items():
                if c["origem"] == "humano" and campo in ficha.CAMPOS_DE_JULGAMENTO:
                    self.assertEqual(ficha.origem(f, campo), "humano", campo)
                    self.assertEqual(ficha.obter(f, campo), c["valor"])
        self.assertEqual(por_numero[lote_a[0]["numero"]]["linha_de_base"]["data_base"], "2026-08-31")
        sem_base = [f for f in fichas if not f.get("linha_de_base")]
        self.assertEqual(len(sem_base), n_lista)
        self.assertTrue(all(f["numero"] in self.esperado_lista["validos"] for f in sem_base))
        self.assertTrue(all(f["numero"] not in self.esperado_lista["invalidos"] for f in fichas))
        nomes = {c["nome"] for c in comum.load_json(comum.CLIENTES_FILE, {})["clientes"]}
        self.assertIn(cliente_padrao, nomes)
        perfil = self.per.carregar()
        self.assertEqual(perfil["entregas"], ["docx_a", "xlsx_b", "dashboard"])
        entrada = sorted(a.name.split(" - ", 1)[1] for a in self.ent.pasta_entrada().iterdir())
        self.assertEqual(entrada, ["lista.csv", "planilha.xlsx", "texto.docx"])
        self.assertEqual(comum.projeto()["ultimo_relatorio"], "2026-09-18")
        # confirmar de novo não cria outro relatório
        r, t = self.post("/fluxo/importar/confirmar", {"lote": lote, "nome": "Outro", "destino": "novo"})
        self.assertIn("Este envio já foi confirmado.", t)
        self.assertEqual(len(comum.projetos()), 2)

    def test_sem_escolha_de_grafia_nada_e_fundido(self):
        dados, lote_b, lote_a = self._arquivos_de_importacao()
        r, t = self.post("/fluxo/importar/enviar", dados, content_type="multipart/form-data")
        lote = r.request.args["lote"]
        self.post("/fluxo/importar/confirmar", {"lote": lote, "nome": "Sem fusão"})
        nomes = {ficha.obter(f, "cliente") for f in self.fichas_do_projeto() if f.get("linha_de_base")}
        self.assertEqual(len(nomes), 2)

    def test_arquivos_invalidos_voltam_com_mensagem_clara(self):
        casos = [({"arquivos": [self.arquivo("programa.exe", b"MZ")]}, "Tipo de arquivo não aceito (.exe)"),
                 ({"arquivos": [self.arquivo("quebrado.docx", b"nao e docx")]}, "Não reconheci o formato"),
                 ({"arquivos": [self.arquivo("vazio.csv", b"")]}, "O arquivo está vazio."),
                 ({"arquivos": [self.arquivo("", b"")]}, "Escolha pelo menos um arquivo.")]
        for dados, trecho in casos:
            r, t = self.post("/fluxo/importar/enviar", dados, content_type="multipart/form-data")
            self.assertEqual(r.request.path, "/fluxo/importar", trecho)
            self.assertIn(trecho, t)
        gravar_fixture(self.pasta_arquivos / "ruim.xlsx", relatorio([]), erro="arquivo corrompido (zip)")
        r, t = self.post("/fluxo/importar/enviar", {"arquivos": [self.arquivo("ruim.xlsx", (self.pasta_arquivos / "ruim.xlsx").read_bytes())]},
                         content_type="multipart/form-data")
        self.assertIn("Não consegui ler o arquivo (arquivo corrompido (zip))", t)
        self.assertEqual(len(comum.projetos()), 1)

    def test_nome_de_arquivo_malicioso_e_escapado_e_confinado(self):
        rel = relatorio(self.fichas[:2], "xlsx_b", cliente="Cliente <b>Exemplo</b>")
        gravar_fixture(self.pasta_arquivos / "x.xlsx", rel)
        conteudo = (self.pasta_arquivos / "x.xlsx").read_bytes()
        r, t = self.post("/fluxo/importar/enviar", {"arquivos": [self.arquivo("../../<script>alert(1)</script>.xlsx", conteudo)]},
                         content_type="multipart/form-data")
        self.assertEqual(r.request.path, "/fluxo/importar/conferir")
        self.assertNotIn("<script>alert(1)</script>", t)
        self.assertNotIn("<b>Exemplo</b>", t)
        self.assertIn("&lt;b&gt;Exemplo&lt;/b&gt;", t)
        lotes = list(self.ass.pasta_dos_lotes().iterdir())
        self.assertEqual(len(lotes), 1)
        for caminho in lotes[0].rglob("*"):   # nada saiu da pasta do envio
            self.assertTrue(str(caminho.resolve()).startswith(str(lotes[0].resolve())))
        self.assertFalse((TMP / "x.xlsx").exists())

    def test_200_processos_em_dois_arquivos_e_o_mais_recente_vence(self):
        grandes = ficticio.gerar_carteira(200, clientes=5, semente=9)
        gravar_fixture(self.pasta_arquivos / "antigo.xlsx", relatorio(grandes, "xlsx_b", "2026-07-31"))
        gravar_fixture(self.pasta_arquivos / "novo.xlsx", relatorio(grandes[:50], "xlsx_b", "2026-09-30"))
        t0 = time.time()
        r, t = self.post("/fluxo/importar/enviar", {"arquivos": [
            self.arquivo("antigo.xlsx", (self.pasta_arquivos / "antigo.xlsx").read_bytes()),
            self.arquivo("novo.xlsx", (self.pasta_arquivos / "novo.xlsx").read_bytes())]}, content_type="multipart/form-data")
        self.assertIn("Li 200 processo(s) de 2 arquivo(s)", t)
        self.assertIn("50 processo(s) apareceram em mais de um arquivo", t)
        r, _ = self.post("/fluxo/importar/confirmar", {"lote": r.request.args["lote"], "nome": "Duzentos"})
        fichas = self.fichas_do_projeto()
        self.assertEqual(len(fichas), 200)
        bases = {f["linha_de_base"]["data_base"] for f in fichas[:50]}
        self.assertEqual(bases, {"2026-09-30"})
        self.assertEqual({f["linha_de_base"]["data_base"] for f in fichas[50:]}, {"2026-07-31"})
        self.assertLess(time.time() - t0, 60)

    def test_acrescentar_ao_relatorio_atual_nao_sobrescreve_o_que_e_humano(self):
        alvo = self.fichas_do_projeto()[0]
        ficha.definir(alvo, "resultado", "Procedente", "humano")
        todas = self.fichas_do_projeto()
        todas[0] = alvo
        ficha.salvar(todas)
        outro = ficticio.gerar_carteira(3, clientes=1, semente=77)
        copia = ficha.nova_ficha(alvo["numero"])
        ficha.definir(copia, "resultado", "Improcedente", "migrado")
        ficha.definir(copia, "vara", "Vara do arquivo", "migrado")
        gravar_fixture(self.pasta_arquivos / "mais.xlsx", relatorio([copia, *outro], "xlsx_b", "2026-09-18"))
        r, t = self.post("/fluxo/importar/enviar", {"arquivos": [self.arquivo("mais.xlsx", (self.pasta_arquivos / "mais.xlsx").read_bytes())]},
                         content_type="multipart/form-data")
        self.assertIn("acrescentar ao relatório atual", t)
        r, t = self.post("/fluxo/importar/confirmar", {"lote": r.request.args["lote"], "nome": "n/a", "destino": "atual"})
        self.assertIn("Acrescentei ao relatório atual: 3 processo(s) novo(s)", t)
        fichas = {f["numero"]: f for f in self.fichas_do_projeto()}
        self.assertEqual(len(fichas), self.N + 3)
        self.assertEqual(ficha.obter(fichas[alvo["numero"]], "resultado"), "Procedente")
        self.assertEqual(ficha.origem(fichas[alvo["numero"]], "resultado"), "humano")
        self.assertEqual(comum.PROJETO, self.proj["slug"])
        self.assertEqual(len(comum.projetos()), 1)

    def test_leitor_ausente_vira_mensagem(self):
        with mock.patch.dict(sys.modules, {"leitores": None}):
            r, t = self.post("/fluxo/importar/enviar", {"arquivos": [self.arquivo("a.txt", b"qualquer coisa")]},
                             content_type="multipart/form-data")
        self.assertEqual(r.request.path, "/fluxo/importar")
        self.assertIn("O leitor de relatórios ainda não está disponível", t)

    def test_consolidar_ausente_ou_com_defeito_nao_derruba(self):
        gravar_fixture(self.pasta_arquivos / "a.xlsx", relatorio(self.fichas[:3], "xlsx_b"))
        dados = lambda: {"arquivos": [self.arquivo("a.xlsx", (self.pasta_arquivos / "a.xlsx").read_bytes())]}
        with mock.patch.dict(sys.modules, {"consolidar": None}):
            r, t = self.post("/fluxo/importar/enviar", dados(), content_type="multipart/form-data")
        self.assertIn("A consolidação (agrupar vinculados, achar duplicatas) ainda não está disponível", t)
        quebrado = types.ModuleType("consolidar")
        quebrado.consolidar = lambda f: 1 / 0
        with mock.patch.dict(sys.modules, {"consolidar": quebrado}):
            r, t = self.post("/fluxo/importar/enviar", dados(), content_type="multipart/form-data")
        self.assertIn("Não consegui conferir duplicados e vinculados", t)

    def test_vinculados_aparecem_na_conferencia(self):
        com = next(f for f in self.fichas if f.get("vinculados"))
        gravar_fixture(self.pasta_arquivos / "v.xlsx", relatorio([com], "xlsx_b"))
        r, t = self.post("/fluxo/importar/enviar", {"arquivos": [self.arquivo("v.xlsx", (self.pasta_arquivos / "v.xlsx").read_bytes())]},
                         content_type="multipart/form-data")
        self.assertIn("Processos ligados entre si", t)
        self.assertIn(com["vinculados"][0]["numero"], t)


# ================================================================ migrar de modelo

class MigrarDeModelo(Base):
    def _tabela(self, n=6):
        fichas = self.fichas[:n]
        linhas = [{"Proc.": f["numero"], "Empresa": ficha.obter(f, "cliente"), "Foro": ficha.obter(f, "vara"),
                   "Anotações": f"nota {i}", "Valor": "R$ 1.000,00"} for i, f in enumerate(fichas)]
        proposta = {"Proc.": {"campo": "numero", "confianca": 0.97}, "Empresa": {"campo": "cliente", "confianca": 0.9},
                    "Foro": {"campo": "municipio", "confianca": 0.4}}     # proposta errada de propósito: Foro é vara
        rel = relatorio(fichas, "tabela_livre", None, mapeamento=proposta,
                        sem_destino=[{"coluna": "Anotações", "amostra": ["nota 0", "nota 1"]}, {"coluna": "Valor", "amostra": ["R$ 1.000,00"]}])
        gravar_fixture(self.pasta_arquivos / "outra-planilha.xlsx", rel, linhas=linhas)
        return (self.pasta_arquivos / "outra-planilha.xlsx").read_bytes()

    def _enviar(self, conteudo, nome="outra-planilha.xlsx"):
        r, t = self.post("/migracao/enviar", {"arquivo": self.arquivo(nome, conteudo)}, content_type="multipart/form-data")
        self.assertEqual(r.request.path, "/migracao/mapear", t[:300])
        return r.request.args["lote"], t

    def test_tela_de_mapeamento_mostra_sugestao_e_o_que_nao_tem_destino(self):
        lote, t = self._enviar(self._tabela())
        self.assertIn("Mapeamento das colunas", t)
        for coluna in ("Proc.", "Empresa", "Foro", "Anotações", "Valor"):
            self.assertIn(f"<td>{coluna}</td>", t)
        self.assertIn("97%", t)                      # confiança da sugestão
        self.assertIn("Número do processo", t)       # destino na planilha
        self.assertIn("Autor(es)", t)                # opção do seletor (campo da ficha)
        self.assertIn("Sem destino (2)", t)
        self.assertIn("Campos não migrados", t)
        self.assertIn("name='modelos' value='docx_a' checked", t)
        self.assertIn("name='modelos' value='xlsx_b' checked", t)
        self.assertIn("<option value='municipio' selected>", t)

    def test_previa_e_conversao_com_mapeamento_corrigido(self):
        lote, _ = self._enviar(self._tabela(6))
        base = {"lote": lote, "map_0": "numero", "map_1": "cliente", "map_2": "vara", "map_3": "", "map_4": "valor_causa",
                "nome": "Convertido Exemplo", "estilo_texto": "b", "modelos": ["docx_a", "xlsx_b"]}
        r, t = self.post("/migracao/converter", {**base, "acao": "prever"})
        self.assertEqual(r.request.path, "/migracao/converter")
        self.assertIn("Prévia: 6 processo(s)", t)
        self.assertEqual(self.m["leitores"].chamadas_ler[-1]["mapeamento"],
                         {"Proc.": "numero", "Empresa": "cliente", "Foro": "vara", "Anotações": None, "Valor": "valor_causa"})
        self.assertIn("Sem destino (1)", t)
        self.assertEqual(len(comum.projetos()), 1)       # prévia não cria nada
        r, t = self.post("/migracao/converter", {**base, "acao": "converter"})
        self.assertEqual(r.request.path, "/entregas")
        self.assertIn("Relatório convertido: Convertido Exemplo. 6 processo(s).", t)
        self.assertEqual(comum.PROJETO, "convertido-exemplo")
        fichas = self.fichas_do_projeto()
        self.assertEqual(len(fichas), 6)
        self.assertEqual(ficha.obter(fichas[0], "vara"), ficha.obter(self.fichas[0], "vara"))
        self.assertEqual(ficha.obter(fichas[0], "valor_causa"), "1000.00")
        perfil = self.per.carregar()
        self.assertEqual((perfil["entregas"], perfil["estilo_texto"]), (["docx_a", "xlsx_b"], "b"))
        # os escritores receberam o estado e o que ficou sem destino
        chamada = self.m["escritores.xlsx_b"].chamadas[-1]
        self.assertIsNone(chamada["molde"])
        self.assertEqual(chamada["estado"]["parametros"]["campos_nao_migrados"], [{"coluna": "Anotações", "amostra": ["nota 0", "nota 1"]}])
        self.assertEqual(len(chamada["estado"]["fichas"]), 6)
        self.assertTrue(self.m["escritores.docx_a"].chamadas)
        self.assertIn("Planilha - ", t)
        self.assertIn("qualidade.html", t)

    def test_conversao_exige_modelo_e_processos(self):
        lote, _ = self._enviar(self._tabela(3))
        r, t = self.post("/migracao/converter", {"lote": lote, "map_0": "numero", "nome": "x", "acao": "converter"})
        self.assertIn("Escolha pelo menos um modelo de destino", t)
        r, t = self.post("/migracao/converter", {"lote": lote, "map_0": "", "map_1": "cliente", "nome": "x", "acao": "converter",
                                                 "modelos": ["xlsx_b"]})
        self.assertIn("Não encontrei nenhum processo com este mapeamento", t)
        self.assertEqual(len(comum.projetos()), 1)

    def test_formato_conhecido_nao_tem_seletor_e_converte(self):
        rel = relatorio(self.fichas[:4], "docx_a", "2026-09-18", cliente="Cliente Exemplo 01 Ltda",
                        mapeamento={"Autor(es)": "autores"})
        gravar_fixture(self.pasta_arquivos / "modelo-a.docx", rel)
        lote, t = self._enviar((self.pasta_arquivos / "modelo-a.docx").read_bytes(), "modelo-a.docx")
        self.assertIn("já está num formato conhecido", t)
        self.assertNotIn("<select name='map_", t)
        r, t = self.post("/migracao/converter", {"lote": lote, "nome": "A para B", "acao": "converter", "modelos": ["xlsx_b"]})
        self.assertEqual(r.request.path, "/entregas")
        self.assertEqual(len(self.fichas_do_projeto()), 4)
        self.assertEqual(self.m["leitores"].chamadas_ler[-1]["mapeamento"], None)

    def test_arquivo_invalido_na_migracao(self):
        r, t = self.post("/migracao/enviar", {"arquivo": self.arquivo("lixo.docx", b"nada")}, content_type="multipart/form-data")
        self.assertEqual(r.request.path, "/migracao")
        self.assertIn("Não consegui usar o arquivo", t)
        r, t = self.get("/migracao/mapear?lote=" + "a" * 12)
        self.assertEqual(r.status_code, 404)

    def test_normalizar_mapeamento_aceita_os_tres_formatos(self):
        n = self.mig.normalizar_mapeamento
        esperado = [{"coluna": "A", "campo": "vara", "confianca": 0.5}]
        self.assertEqual(n({"A": {"campo": "vara", "confianca": 0.5}}), esperado)
        self.assertEqual(n([{"coluna": "A", "campo": "vara", "confianca": 0.5}]), esperado)
        self.assertEqual(n({"A": "vara"}), [{"coluna": "A", "campo": "vara", "confianca": None}])
        self.assertEqual(n(None), [])


# ================================================================ elaborar inicial, fila e progresso

class ElaborarInicial(Base):
    N = 40

    def _preparar(self, modo="continuo", **extra):
        dados = {"com_entregas": "1", "entregas": ["docx_a", "xlsx_b"], "profundidade": "rapido", "modo_coleta": modo,
                 "janela_inicio": "21:00", "janela_fim": "05:30", "so_novos": "1", **extra}
        return self.post("/fluxo/inicial/preparar", dados)

    def test_formulario_oferece_as_escolhas(self):
        _, t = self.get("/fluxo/inicial")
        for trecho in ("name='entregas' value='docx_a'", "name='entregas' value='xlsx_b'", "name='entregas' value='dashboard'",
                       "name='profundidade' value='rapido'", "name='profundidade' value='padrao'", "name='profundidade' value='completo'",
                       "name='modo_coleta' value='continuo'", "name='modo_coleta' value='imediato'", "name='janela_inicio'",
                       "name='cliente'", "name='so_novos'", "Cliente Exemplo 01 Ltda"):
            self.assertIn(trecho, t)

    def test_modo_continuo_coleta_tudo_com_falhas_e_grava_a_capa(self):
        # fichas do relatório sem vara/município: a coleta (simulada) as completa, com origem "coletado"
        todas = self.fichas_do_projeto()
        for f in todas:
            ficha.limpar(f, "vara")
            ficha.limpar(f, "municipio")
        ficha.salvar(todas)
        coletor = self.novo_coletor(taxa_falha=0.25)
        r, t = self._preparar("continuo")
        self.assertEqual(r.request.path, "/fluxo/progresso")
        self.assertIn(f"{len(self.ativos)} processo(s) na fila.", t)
        self.assertIn("Coleta iniciada.", t)
        self.esperar_execucao()
        envio = self.m["fila"].chamadas_enfileirar[0]
        self.assertEqual((envio["modo"], envio["profundidade"], envio["desde"]), ("continuo", "rapido", None))
        self.assertEqual(self.m["fila"].ESTADOS[comum.PROJETO]["janela"], ("21:00", "05:30"))
        resumo = self.m["fila"].Fila(comum.PROJETO).resumo()
        self.assertEqual(resumo["pendente"], 0)
        self.assertEqual(resumo["coletado"] + resumo["erro"] + resumo["manual"], len(self.ativos))
        self.assertGreater(resumo["manual"] + resumo["erro"], 0)         # as falhas aleatórias aconteceram
        self.assertEqual(self.ass.EXEC["estado"], "concluida")
        for numero, vezes in coletor.chamadas_por_numero.items():
            self.assertEqual(vezes, 1)
        # a capa dos coletados entrou na ficha com origem "coletado"; polo e parte contrária não mudam
        estados = {i["numero"]: i["estado"] for i in self.m["fila"].Fila(comum.PROJETO).itens()}
        por_numero = {f["numero"]: f for f in self.fichas_do_projeto()}
        originais = {f["numero"]: f for f in self.fichas}
        coletados = [n for n, e in estados.items() if e == "coletado"]
        self.assertTrue(coletados)
        for n in coletados:
            self.assertEqual(ficha.obter(por_numero[n], "vara"), ficha.obter(originais[n], "vara"))
            self.assertEqual(ficha.origem(por_numero[n], "vara"), "coletado")
            self.assertEqual(ficha.obter(por_numero[n], "polo_cliente"), ficha.obter(originais[n], "polo_cliente"))
        for n, e in estados.items():
            if e != "coletado":
                self.assertIsNone(ficha.obter(por_numero[n], "vara"))
        _, t = self.get("/fluxo/progresso")
        self.assertIn("Coleta: concluída", t)
        self.assertIn("<progress", t)
        self.assertIn("Cobertura por tribunal", t)
        self.assertIn("Ir para a revisão", t)
        # o perfil guardou as escolhas
        perfil = self.per.carregar()
        self.assertEqual((perfil["entregas"], perfil["profundidade"], perfil["modo_coleta"], perfil["janela_coleta"]),
                         (["docx_a", "xlsx_b"], "rapido", "continuo", {"inicio": "21:00", "fim": "05:30"}))

    def test_modo_imediato_mostra_estimativa_e_so_comeca_apos_confirmar(self):
        coletor = self.novo_coletor()
        r, t = self._preparar("imediato")
        self.assertEqual(r.request.path, "/fluxo/confirmar")
        self.assertIn(f"{len(self.ativos)} processo(s)", t)
        self.assertIn("cerca de", t)                    # pendentes x 90 s (vem de Fila.resumo()["estimativa_s"])
        self.assertIn("Confirmar e começar agora", t)
        self.assertEqual(coletor.chamadas, 0)
        self.assertEqual(self.m["fila"].Fila(comum.PROJETO).resumo()["pendente"], len(self.ativos))
        r, t = self.post("/fluxo/comecar")
        self.assertEqual(r.request.path, "/fluxo/progresso")
        self.esperar_execucao()
        self.assertEqual(coletor.chamadas, len(self.ativos))
        self.assertEqual(self.m["fila"].Fila(comum.PROJETO).resumo()["coletado"], len(self.ativos))

    def test_recusar_a_confirmacao_nao_coleta_nada_mas_da_para_comecar_depois(self):
        coletor = self.novo_coletor()
        self._preparar("imediato")
        _, t = self.get("/fluxo/progresso")           # "Agora não"
        self.assertEqual(coletor.chamadas, 0)
        self.assertIn("Coleta: nada em andamento", t)
        self.assertIn("Começar ou continuar a coleta", t)
        self.assertIn("0 de", t)
        self.post("/fluxo/retomar")
        self.esperar_execucao()
        self.assertEqual(coletor.chamadas, len(self.ativos))

    def test_filtro_por_cliente(self):
        self.novo_coletor()
        cliente = sorted({ficha.obter(f, "cliente") for f in self.fichas})[1]
        esperados = {f["numero"] for f in self.ativos if ficha.obter(f, "cliente") == cliente}
        self.assertTrue(0 < len(esperados) < len(self.ativos))
        self._preparar("continuo", cliente=cliente)
        self.esperar_execucao()
        self.assertEqual(set(self.m["fila"].chamadas_enfileirar[0]["numeros"]), esperados)
        self.assertEqual(set(self.coletor.chamadas_por_numero), esperados)

    def test_so_processos_sem_relatorio_anterior(self):
        todas = self.fichas_do_projeto()
        for f in todas[:10]:
            ficticio.anexar_linha_de_base(f, data_base="2026-09-18")
        primeiros = {f["numero"] for f in todas[:10]}
        ficha.salvar(todas)
        self.novo_coletor()
        self._preparar("continuo")
        self.esperar_execucao()
        sem_base = sum(1 for f in self.ativos if f["numero"] not in primeiros)
        com_base = len(self.ativos) - sem_base
        self.assertTrue(sem_base and com_base)
        self.assertEqual(len(self.m["fila"].chamadas_enfileirar[0]["numeros"]), sem_base)
        # sem o filtro, os que têm relatório anterior entram com "desde" = data-base deles
        self.m["fila"].chamadas_enfileirar.clear()
        self.m["fila"].ESTADOS.clear()
        self.resetar_execucao()
        self.post("/fluxo/inicial/preparar", {"com_entregas": "1", "entregas": ["xlsx_b"], "profundidade": "rapido", "modo_coleta": "continuo"})
        self.esperar_execucao()
        desde = {e["desde"]: len(e["numeros"]) for e in self.m["fila"].chamadas_enfileirar}
        self.assertEqual(desde, {None: sem_base, "2026-09-18": com_base})

    def test_escolhas_invalidas_nao_enfileiram(self):
        self.novo_coletor()
        for dados, trecho in (({"com_entregas": "1", "profundidade": "rapido", "modo_coleta": "continuo"}, "Marque pelo menos uma entrega"),
                              ({"entregas": ["xlsx_b"], "profundidade": "enorme", "modo_coleta": "continuo"}, "Escolha uma opção válida"),
                              ({"entregas": ["xlsx_b"], "profundidade": "rapido", "modo_coleta": "continuo", "janela_inicio": "25:99",
                                "janela_fim": "06:00"}, "HH:MM")):
            r, t = self.post("/fluxo/inicial/preparar", dados)
            self.assertEqual(r.request.path, "/fluxo/inicial")
            self.assertIn(trecho, t)
        self.assertEqual(self.m["fila"].chamadas_enfileirar, [])

    def test_fila_ausente_vira_mensagem(self):
        with mock.patch.dict(sys.modules, {"fila": None}):
            r, t = self._preparar("continuo")
        self.assertEqual(r.request.path, "/fluxo/inicial")
        self.assertIn("A fila de coleta ainda não está disponível", t)

    def test_sem_acesso_configurado_o_coletor_real_nao_e_criado(self):
        self.ass.FABRICA_DE_COLETOR = None
        import acesso
        with mock.patch.object(acesso, "obter", lambda chave: None):
            r, t = self._preparar("continuo")
        self.assertIn("Falta configurar o acesso", t)
        self.assertFalse(self.ass.execucao_rodando())

    def test_nao_inicia_junto_com_tarefa_da_tela_atualizar(self):
        class Proc:
            def poll(self):
                return None
        self.base.TAREFA.update(proc=Proc(), descricao="x", nome="n", inicio="10:00", log="/nao/existe")
        self.novo_coletor()
        r, t = self._preparar("continuo")
        self.assertIn("Há uma tarefa da tela Atualizar em andamento", t)
        self.assertEqual(self.coletor.chamadas, 0)

    def test_progresso_json(self):
        self.novo_coletor()
        self._preparar("continuo")
        self.esperar_execucao()
        r, _ = self.get("/fluxo/progresso.json")
        dados = r.get_json()
        self.assertEqual(dados["estado"], "concluida")
        self.assertEqual(dados["resumo"]["total"], len(self.ativos))
        self.assertTrue(dados["log"])
        self.assertIn("TJCE", dados["cobertura"])

    def test_duracao_humana(self):
        d = self.ass.duracao_humana
        self.assertEqual(d(None), "não consegui estimar")
        self.assertEqual(d(30), "cerca de 1 min")
        self.assertEqual(d(600), "cerca de 10 min")
        self.assertEqual(d(3600), "cerca de 1 h")
        self.assertEqual(d(3600 * 2 + 900), "cerca de 2 h 15 min")


class PausarRetomarParar(Base):
    N = 40

    def _coletor_com_portao(self, no_numero):
        """Coletor simulado que segura a N-ésima chamada até o teste liberar (para apertar o botão no meio)."""
        coletor = self.novo_coletor()
        original = coletor.coletar
        liberar, chegou = threading.Event(), threading.Event()

        def coletar(processo, profundidade="padrao", desde=None):
            if coletor.chamadas + 1 == no_numero:
                chegou.set()
                liberar.wait(10)
            return original(processo, profundidade, desde)
        coletor.coletar = coletar
        return liberar, chegou

    def _iniciar(self):
        return self.post("/fluxo/inicial/preparar", {"com_entregas": "1", "entregas": ["xlsx_b"], "profundidade": "rapido", "modo_coleta": "continuo"})

    def test_pausar_e_retomar(self):
        liberar, chegou = self._coletor_com_portao(4)
        self._iniciar()
        self.assertTrue(chegou.wait(10))
        r, t = self.post("/fluxo/pausar")
        self.assertIn("Coleta em pausa", t)
        self.assertIn("Coleta: em pausa", t)
        self.assertIn("Retomar", t)
        liberar.set()
        self.esperar_execucao()
        self.assertEqual(self.coletor.chamadas, 4)                      # o processo corrente terminou; o resto esperou
        self.assertEqual(self.ass.EXEC["estado"], "pausada")
        resumo = self.m["fila"].Fila(comum.PROJETO).resumo()
        self.assertEqual((resumo["coletado"], resumo["pendente"]), (4, len(self.ativos) - 4))
        r, t = self.post("/fluxo/retomar")
        self.assertIn("Coleta iniciada", t)
        self.esperar_execucao()
        self.assertEqual(self.m["fila"].Fila(comum.PROJETO).resumo()["coletado"], len(self.ativos))
        self.assertEqual(self.ass.EXEC["estado"], "concluida")
        self.assertTrue(all(v == 1 for v in self.coletor.chamadas_por_numero.values()), "repetiu processo coletado")

    def test_parar_com_seguranca(self):
        liberar, chegou = self._coletor_com_portao(3)
        self._iniciar()
        self.assertTrue(chegou.wait(10))
        r, t = self.post("/fluxo/parar")
        self.assertIn("Parando com segurança", t)
        self.assertIn("parando", t)
        liberar.set()
        self.esperar_execucao()
        self.assertEqual(self.coletor.chamadas, 3)
        self.assertEqual(self.ass.EXEC["estado"], "parada")
        _, t = self.get("/fluxo/progresso")
        self.assertIn("Coleta: parada", t)
        self.assertIn("Começar ou continuar a coleta", t)
        self.assertNotIn("location.reload", t)
        self.post("/fluxo/retomar")
        self.esperar_execucao()
        self.assertEqual(self.coletor.chamadas, len(self.ativos))

    def test_modo_continuo_espera_a_janela_e_termina_quando_a_fila_esvazia(self):
        """Se `rodar_fila` volta com pendentes (fora da janela), o painel espera e tenta de novo."""
        self.novo_coletor()
        fila_mod = self.m["fila"]
        original = fila_mod.rodar_fila
        rodadas = []

        def rodar_so_depois_de_duas_tentativas(fila, coletor, ao_progresso=None):
            rodadas.append(1)
            if len(rodadas) >= 3:
                return original(fila, coletor, ao_progresso)
        fila_mod.rodar_fila = rodar_so_depois_de_duas_tentativas
        self._iniciar()
        self.esperar_execucao()
        self.assertEqual(len(rodadas), 3)
        self.assertEqual(self.coletor.chamadas, len(self.ativos))

    def test_captcha_e_segredo_nao_travam_o_resto(self):
        a, b = self.ativos[0]["numero"], self.ativos[1]["numero"]
        self.novo_coletor(falhar_em={a: "captcha", b: "segredo"})
        self._iniciar()
        self.esperar_execucao()
        resumo = self.m["fila"].Fila(comum.PROJETO).resumo()
        self.assertEqual((resumo["manual"], resumo["coletado"]), (2, len(self.ativos) - 2))
        _, t = self.get("/entregas")
        self.assertIn("Conferir manualmente", t)
        self.assertIn(a, t)
        self.assertIn("verificação (captcha)", t)
        self.assertIn("segredo de justiça", t)


# ================================================================ atualizar

class Atualizar(Base):
    N = 20

    def setUp(self):
        super().setUp()
        todas = self.fichas_do_projeto()
        for f in todas:
            ficticio.anexar_linha_de_base(f, data_base="2026-08-31")
        ficha.salvar(todas)
        self.fichas = todas
        self.ativos = [f for f in todas if f.get("ativo", True)]

    def _enviar(self, rel, nome="relatorio.xlsx"):
        gravar_fixture(self.pasta_arquivos / nome, rel)
        return self.post("/fluxo/atualizar/enviar", {"arquivos": [self.arquivo(nome, (self.pasta_arquivos / nome).read_bytes())]},
                         content_type="multipart/form-data")

    def test_confere_contra_a_carteira_e_inclui_os_novos(self):
        novos = ficticio.gerar_carteira(2, clientes=1, semente=55)
        no_arquivo = self.fichas[:18] + novos
        sumidos = [f["numero"] for f in self.fichas[18:]]
        r, t = self._enviar(relatorio(no_arquivo, "xlsx_b", "2026-09-30"))
        self.assertEqual(r.request.path, "/fluxo/atualizar/conferir")
        self.assertIn("Processos novos no arquivo (2)", t)
        sumidos = [f["numero"] for f in self.fichas[18:] if f.get("ativo", True)]       # só os ativos contam como "sumidos"
        self.assertTrue(sumidos)
        self.assertIn(f"Processos da carteira que não aparecem no arquivo ({len(sumidos)})", t)
        for n in [f["numero"] for f in novos] + sumidos:
            self.assertIn(n, t)
        self.assertIn("name='incluir_novos'", t)
        self.assertIn("name='incluir_sumidos'", t)
        self.novo_coletor(fichas=self.fichas + novos)
        # inclui os novos, mas deixa de acompanhar os que sumiram (caixa desmarcada)
        r, t = self.post("/fluxo/atualizar/preparar", {"lote": r.request.args["lote"], "incluir_novos": "1", "entregas": ["xlsx_b"],
                                                       "profundidade": "rapido", "modo_coleta": "continuo"})
        self.assertIn("2 processo(s) novo(s) incluído(s) na carteira.", t)
        self.assertEqual(len(self.fichas_do_projeto()), self.N + 2)
        self.esperar_execucao()
        enfileirados = {n for e in self.m["fila"].chamadas_enfileirar for n in e["numeros"]}
        self.assertEqual(enfileirados, {f["numero"] for f in no_arquivo if f.get("ativo", True)})
        self.assertTrue(set(sumidos).isdisjoint(enfileirados))
        # todos são coletados desde a data-base do arquivo enviado
        self.assertEqual({e["desde"] for e in self.m["fila"].chamadas_enfileirar}, {"2026-09-30"})
        self.assertTrue(any(a.name.endswith("relatorio.xlsx") for a in self.ent.pasta_entrada().iterdir()))

    def test_continuar_acompanhando_os_que_sumiram(self):
        r, t = self._enviar(relatorio(self.fichas[:15], "xlsx_b", "2026-09-30"))
        self.novo_coletor()
        self.post("/fluxo/atualizar/preparar", {"lote": r.request.args["lote"], "incluir_sumidos": "1", "entregas": ["xlsx_b"],
                                                "profundidade": "rapido", "modo_coleta": "continuo"})
        self.esperar_execucao()
        self.assertEqual({n for e in self.m["fila"].chamadas_enfileirar for n in e["numeros"]}, {f["numero"] for f in self.ativos})

    def test_sem_arquivo_cada_processo_usa_a_sua_data(self):
        todas = self.fichas_do_projeto()
        todas[0]["ativo"] = todas[1]["ativo"] = True
        ficticio.anexar_linha_de_base(todas[0], data_base="2026-05-01")
        todas[1]["ultimo_texto_gravado"] = {"data_base": "2026-09-15", "texto": "x", "arquivo": "a.docx"}
        ficha.salvar(todas)
        outros = sum(1 for f in todas[2:] if f.get("ativo", True))
        r, t = self.post("/fluxo/atualizar/enviar", {"arquivos": []}, content_type="multipart/form-data")
        self.assertEqual(r.request.path, "/fluxo/atualizar/conferir")
        self.assertIn("Sem arquivo enviado", t)
        self.novo_coletor()
        self.post("/fluxo/atualizar/preparar", {"lote": r.request.args["lote"], "entregas": ["xlsx_b"], "profundidade": "rapido",
                                                "modo_coleta": "continuo"})
        self.esperar_execucao()
        desde = {e["desde"]: len(e["numeros"]) for e in self.m["fila"].chamadas_enfileirar}
        self.assertEqual(desde, {"2026-05-01": 1, "2026-09-15": 1, "2026-08-31": outros})

    def test_arquivo_invalido_na_atualizacao(self):
        r, t = self.post("/fluxo/atualizar/enviar", {"arquivos": [self.arquivo("lista.csv", b"1")]}, content_type="multipart/form-data")
        self.assertEqual(r.request.path, "/fluxo/atualizar")
        self.assertIn("Tipo de arquivo não aceito (.csv)", t)
        r, t = self.post("/fluxo/atualizar/enviar", {"arquivos": [self.arquivo("quebrado.docx", b"lixo")]}, content_type="multipart/form-data")
        self.assertIn("Não consegui usar o arquivo enviado", t)

    def test_desde_do_processo(self):
        d = self.ass.desde_do_processo
        self.assertIsNone(d({}))
        self.assertEqual(d({"linha_de_base": {"data_base": "2026-08-31"}}), "2026-08-31")
        self.assertEqual(d({"linha_de_base": {"data_base": None, "ultimo_andamento": "2026-07-01"}}), "2026-07-01")
        self.assertEqual(d({"linha_de_base": {"data_base": "2026-08-31"}, "ultimo_texto_gravado": {"data_base": "2026-09-15"}}), "2026-09-15")
        self.assertEqual(d({"linha_de_base": {"data_base": "2026-08-31"}}, "2026-09-30"), "2026-09-30")
        self.assertEqual(d({"linha_de_base": {"data_base": "2026-08-31"}}, "2026-01-01"), "2026-08-31")


# ================================================================ entregas

class Entregas(Base):
    N = 12

    def _aprovar_eventos(self):
        eventos = [{"id": f"e:{i}", "numero": f["numero"], "status": "aprovado" if i % 2 == 0 else "rascunho",
                    "data": "01/10/2026", "frase": f"Frase {i}."} for i, f in enumerate(self.fichas)]
        comum.salvar_eventos(eventos)
        return {e["id"] for e in eventos if e["status"] == "aprovado"}

    def test_gerar_entregas_chama_os_escritores_com_o_estado(self):
        aprovados = self._aprovar_eventos()
        r, t = self.post("/entregas/gerar", {"entregas": ["docx_a", "xlsx_b", "dashboard"]})
        self.assertEqual(r.request.path, "/entregas")
        self.assertIn("arquivo(s) gerado(s) em saida/", t)
        saida = self.ent.pasta_saida()
        rodadas = [p for p in saida.iterdir() if p.is_dir()]
        self.assertEqual(len(rodadas), 1)
        nomes = sorted(a.name for a in rodadas[0].iterdir())
        self.assertEqual(sum(n.endswith(".docx") for n in nomes), 2)          # um por cliente
        self.assertEqual([n for n in nomes if not n.endswith(".docx")],
                         ["Painel - Relatório do Teste.html", "Planilha - Relatório do Teste.xlsx", "qualidade.html"])
        docx, xlsx, painel = (self.m[f"escritores.{x}"].chamadas for x in ("docx_a", "xlsx_b", "dashboard"))
        self.assertEqual(len(docx), 2)
        self.assertEqual(len(xlsx), 1)
        self.assertEqual(len(painel), 1)
        self.assertEqual({ev["id"] for ev in xlsx[0]["estado"]["eventos"]}, aprovados)      # só aprovados
        self.assertEqual(len(xlsx[0]["estado"]["fichas"]), self.N)
        for c in docx:
            esperado = sum(1 for f in self.fichas if ficha.obter(f, "cliente") == c["estado"]["cliente"])
            self.assertEqual(len(c["estado"]["fichas"]), esperado)
        self.assertEqual(xlsx[0]["estado"]["perfil"]["entregas"], ["docx_a", "xlsx_b", "dashboard"])
        self.assertIsInstance(painel[0]["molde"], Path)                   # o painel recebe a planilha gerada
        self.assertEqual(painel[0]["molde"].name, "Planilha - Relatório do Teste.xlsx")
        # texto gravado guardado na ficha (CONTRATOS §5)
        f0 = self.fichas_do_projeto()[0]
        self.assertEqual(f0["ultimo_texto_gravado"]["texto"], f"Texto gravado de {f0['numero']}")
        self.assertEqual(f0["ultimo_texto_gravado"]["arquivo"], "Planilha - Relatório do Teste.xlsx")
        # a tela lista, com download e relatório de qualidade
        _, t = self.get("/entregas")
        self.assertIn("Arquivos entregues", t)
        self.assertIn("/entregas/baixar?p=", t)
        self.assertIn("Planilha - Relatório do Teste.xlsx", t)
        self.assertIn("Qualidade da base", t)
        r, t = self.post("/entregas/qualidade")
        self.assertIn("Verificação concluída: 1 achado(s).", t)
        self.assertIn("Achado de teste &lt;b&gt;escapado&lt;/b&gt;.", t)
        self.assertNotIn("<b>escapado</b>", t)
        self.assertIn("<b>escapado</b>", (rodadas[0] / "qualidade.html").read_text(encoding="utf-8").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"))

    def test_molde_do_cliente_e_de_um_so_cliente(self):
        entrada = self.ent.pasta_entrada()
        (entrada / "cliente.xlsx").write_bytes(b"x")
        (entrada / "cliente.docx").write_bytes(b"x")
        perfil = self.per.carregar()
        perfil["molde_planilha"] = "cliente"
        self.per.salvar(perfil)
        self.post("/entregas/gerar", {"entregas": ["docx_a", "xlsx_b"]})
        self.assertEqual(self.m["escritores.xlsx_b"].chamadas[-1]["molde"], entrada / "cliente.xlsx")
        self.assertTrue(all(c["molde"] is None for c in self.m["escritores.docx_a"].chamadas))   # 2 clientes: modelo padrão
        # com um cliente só, o .docx enviado é o molde
        so_um = [f for f in self.fichas if ficha.obter(f, "cliente") == "Cliente Exemplo 01 Ltda"]
        ficha.salvar(so_um)
        self.m["escritores.docx_a"].chamadas.clear()
        import os
        os.utime(entrada / "cliente.docx", (time.time() + 60, time.time() + 60))     # enviado depois da última entrega
        self.post("/entregas/gerar", {"entregas": ["docx_a"]})
        self.assertEqual(self.m["escritores.docx_a"].chamadas[-1]["molde"], entrada / "cliente.docx")

    def test_escritor_ausente_ou_com_falha_vira_aviso_e_o_resto_sai(self):
        with mock.patch.dict(sys.modules, {"escritores.dashboard": None}):
            r, t = self.post("/entregas/gerar", {"entregas": ["xlsx_b", "dashboard"]})
        self.assertIn("O gerador do painel (.html) ainda não está disponível", t)
        self.assertEqual(len(self.m["escritores.xlsx_b"].chamadas), 1)
        quebrado = types.ModuleType("escritores.xlsx_b")
        quebrado.gravar = lambda *a, **k: 1 / 0
        with mock.patch.dict(sys.modules, {"escritores.xlsx_b": quebrado}):
            r, t = self.post("/entregas/gerar", {"entregas": ["xlsx_b"]})
        self.assertIn("Não consegui gerar a planilha", t)

    def test_download_so_dentro_de_saida(self):
        self._aprovar_eventos()
        self.post("/entregas/gerar", {"entregas": ["xlsx_b"]})
        rodada = next(p for p in self.ent.pasta_saida().iterdir() if p.is_dir())
        arquivo = next(a for a in rodada.iterdir() if a.suffix == ".xlsx")
        r, _ = self.get(f"/entregas/baixar?p={rodada.name}/{arquivo.name}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertEqual(r.data, arquivo.read_bytes())
        (self.proj["pasta"] / "segredo.txt").write_text("não pode sair", encoding="utf-8")
        for p in ("../segredo.txt", "../../projeto.json", f"{rodada.name}", "", "/etc/passwd", "..%2Fsegredo.txt"):
            r, _ = self.get(f"/entregas/baixar?p={p}")
            self.assertEqual(r.status_code, 404, p)

    def test_mostrar_a_pasta(self):
        self._aprovar_eventos()
        self.post("/entregas/gerar", {"entregas": ["xlsx_b"]})
        rodada = next(p for p in self.ent.pasta_saida().iterdir() if p.is_dir())
        with mock.patch("subprocess.run") as run:
            self.post("/entregas/mostrar", {"p": rodada.name})
            self.post("/entregas/mostrar", {"p": "../.."})
            self.assertEqual(len(run.call_args_list), 1)
            self.assertEqual(run.call_args_list[0].args[0][-1], str(rodada))

    def test_pasta_de_trabalho_pode_ficar_no_drive(self):
        drive = TMP / "drive-para-desktop"
        drive.mkdir(exist_ok=True)
        r, t = self.post("/perfil/salvar", {**self._perfil_completo(), "pasta_de_trabalho": str(drive)})
        self.assertIn("Perfil salvo.", t)
        self.post("/entregas/gerar", {"entregas": ["xlsx_b"]})
        self.assertTrue((drive / "saida").is_dir())
        self.assertTrue((drive / "entrada").is_dir())
        self.assertEqual(len([p for p in (drive / "saida").iterdir()]), 1)
        self.assertFalse((self.proj["pasta"] / "saida").exists())

    def _perfil_completo(self):
        p = self.per.carregar()
        return {"entregas": p["entregas"], "molde_planilha": p["molde_planilha"], "estilo_texto": p["estilo_texto"],
                "profundidade": p["profundidade"], "modo_coleta": p["modo_coleta"], "janela_inicio": "20:00",
                "janela_fim": "06:00", "headcount": "", "empresas_do_grupo": "", "colunas_ativas": p["colunas_ativas"],
                "pasta_de_trabalho": ""}

    def test_pagina_sem_nada_entregue(self):
        _, t = self.get("/entregas")
        self.assertIn("Nada entregue ainda.", t)
        self.assertIn("Nenhum processo para conferir à mão agora.", t)
        self.assertIn("name='entregas' value='docx_a'", t)


# ================================================================ perfil

class Perfil(Base):
    def _form(self, **mudancas):
        p = self.per.carregar()
        dados = {"entregas": p["entregas"], "molde_planilha": "padrao", "estilo_texto": "a", "profundidade": "padrao",
                 "modo_coleta": "continuo", "janela_inicio": "20:00", "janela_fim": "06:00", "headcount": "",
                 "empresas_do_grupo": "", "colunas_ativas": p["colunas_ativas"], "pasta_de_trabalho": ""}
        dados.update(mudancas)
        return dados

    def test_tela_mostra_o_perfil_padrao(self):
        _, t = self.get("/perfil")
        for trecho in ("name='entregas' value='dashboard' checked", "name='molde_planilha'", "name='estilo_texto'",
                       "name='profundidade'", "name='modo_coleta'", "name='janela_inicio' size='5' value='20:00'",
                       "name='headcount'", "name='empresas_do_grupo'", "name='colunas_ativas' value='valor_economizado' checked",
                       "name='pasta_de_trabalho'", "local (nada sai do seu computador)"):
            self.assertIn(trecho, t)
        self.assertEqual(t.count("name='colunas_ativas'"), len(self.per.COLUNAS_MODELO_B) + len(
            [c for c in ficha.CAMPOS if c not in self.per.COLUNAS_MODELO_B]))
        self.assertEqual(len(self.per.COLUNAS_MODELO_B), 29)

    def test_salvar_perfil_valido(self):
        r, t = self.post("/perfil/salvar", self._form(entregas=["xlsx_b"], profundidade="completo", modo_coleta="imediato",
                                                      headcount="1200", empresas_do_grupo="Empresa Uma\n\nEmpresa Dois\nEmpresa Uma",
                                                      janela_inicio="22:00", janela_fim="5:30", estilo_texto="b", molde_planilha="cliente"))
        self.assertIn("Perfil salvo.", t)
        p = comum.load_json(self.proj["pasta"] / "perfil.json", None)
        self.assertEqual((p["entregas"], p["profundidade"], p["modo_coleta"], p["estilo_texto"], p["molde_planilha"]),
                         (["xlsx_b"], "completo", "imediato", "b", "cliente"))
        self.assertEqual(p["parametros"], {"headcount": 1200, "empresas_do_grupo": ["Empresa Uma", "Empresa Dois"]})
        self.assertEqual(p["janela_coleta"], {"inicio": "22:00", "fim": "05:30"})
        self.assertEqual(p["versao"], 1)
        _, t = self.get("/perfil")
        self.assertIn("1200", t)
        self.assertIn("Empresa Dois", t)

    def test_perfil_invalido_nao_grava(self):
        antes = self.per.carregar()
        for mudanca, trecho in (({"entregas": []}, "Marque pelo menos uma entrega"), ({"profundidade": "x"}, "Escolha uma opção válida"),
                                ({"janela_inicio": "9h"}, "HH:MM"), ({"headcount": "mil"}, "número inteiro"),
                                ({"colunas_ativas": []}, "pelo menos uma coluna"),
                                ({"pasta_de_trabalho": str(TMP / "nao-existe-mesmo")}, "A pasta de trabalho não existe")):
            r, t = self.post("/perfil/salvar", self._form(**mudanca))
            self.assertIn("Não salvei o perfil", t, trecho)
            self.assertIn(trecho, t)
        self.assertEqual(self.per.carregar(), antes)
        self.assertFalse((self.proj["pasta"] / "perfil.json").exists())

    def test_preserva_o_que_a_tela_nao_conhece(self):
        arquivo = self.proj["pasta"] / "perfil.json"
        comum.save_json(arquivo, {"versao": 1, "ia": {"provedor": "anthropic", "consentimento_externo": True, "pseudonimizar": False,
                                                       "por_cliente": {"A": True}}, "chave_futura": {"x": 1}})
        self.post("/perfil/salvar", self._form(profundidade="rapido"))
        p = comum.load_json(arquivo, None)
        self.assertEqual(p["ia"]["provedor"], "anthropic")
        self.assertEqual(p["ia"]["por_cliente"], {"A": True})
        self.assertEqual(p["chave_futura"], {"x": 1})
        self.assertEqual(p["profundidade"], "rapido")
        _, t = self.get("/perfil")
        self.assertIn("externo (anthropic)", t)

    def test_consentimento_so_conta_com_true_explicito(self):
        arquivo = self.proj["pasta"] / "perfil.json"
        for valor in ("true", "sim", 1, None, "false"):
            comum.save_json(arquivo, {"ia": {"provedor": "anthropic", "consentimento_externo": valor}})
            _, t = self.get("/perfil")
            self.assertIn("local (nada sai do seu computador)", t, repr(valor))

    def test_arquivo_malformado_cai_no_padrao(self):
        arquivo = self.proj["pasta"] / "perfil.json"
        for conteudo in ("{isto nao e json", "[1, 2]", '{"entregas": "docx_a", "profundidade": 3, "parametros": 5}', ""):
            arquivo.write_text(conteudo, encoding="utf-8")
            p = self.per.carregar()
            self.assertEqual(p["entregas"], ["docx_a", "xlsx_b", "dashboard"], conteudo)
            self.assertEqual(p["profundidade"], "padrao")
            self.assertEqual(p["parametros"], {"headcount": None, "empresas_do_grupo": []})
            r, _ = self.get("/perfil")
            self.assertEqual(r.status_code, 200)

    def test_ponto_de_extensao_para_a_tela_de_ia(self):
        self.per.PONTOS_DE_EXTENSAO.append(lambda perfil: "<p id='bloco-ia'>Bloco do WS-18</p>")
        self.per.PONTOS_DE_EXTENSAO.append(lambda perfil: 1 / 0)       # bloco com defeito não derruba a tela
        try:
            r, t = self.get("/perfil")
            self.assertEqual(r.status_code, 200)
            self.assertIn("id='bloco-ia'", t)
        finally:
            del self.per.PONTOS_DE_EXTENSAO[:]

    def test_link_para_a_tela_de_ia_so_quando_existe(self):
        _, t = self.get("/perfil")
        self.assertNotIn("Escolher o motor e o consentimento", t)      # a barra de abas já tem /ia; o link é o do bloco
        app = Flask(__name__)
        app.add_url_rule("/ia", "tela_ia_falsa", lambda: "ia")        # a tela do WS-18 existiria aqui
        token_ok = self.base.criar_token_ok(TOKEN)
        for tela in (self.base, self.per):
            tela.registrar(app, TOKEN, self.base.cabecalho, token_ok)
        t = app.test_client().get("/perfil").get_data(as_text=True)
        self.assertIn("Escolher o motor e o consentimento", t)


if __name__ == "__main__":
    unittest.main()
