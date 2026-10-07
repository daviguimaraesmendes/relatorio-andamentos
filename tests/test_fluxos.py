"""Testes dos fluxos ponta a ponta (src/fluxos.py, WS-14): migrar, converter, inicial, atualizar e entregar, com o
coletor simulado, 200 processos e 5 clientes, sem rede e sem IA real.

Tudo é dado fictício e gerado em tempo de execução (tests/ficticio.py). O que NÃO é exercitado aqui: o ColetorReal
(certificado, jus.br, TRT), provedores de IA reais, Word, Excel e Google (só python-docx, openpyxl, LibreOffice e
Chromium offline).

    python3 -m unittest tests/test_fluxos.py -v
"""
import datetime
import json
import shutil
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import ficticio  # noqa: E402
import simulado  # noqa: E402
import comum  # noqa: E402
import ficha  # noqa: E402
import fluxos  # noqa: E402
import historico  # noqa: E402

D = Decimal
DATA_1, DATA_2, DATA_3 = "2026-07-31", "2026-08-31", "2026-09-30"


# ------------------------------------------------------------------ apoio

class Relogio:
    """Relógio falso da fila: `dormir` só adianta o relógio (nenhum teste espera de verdade)."""

    def __init__(self, inicio=datetime.datetime(2026, 10, 7, 22, 0)):
        self.agora = inicio

    def __call__(self):
        return self.agora

    def dormir(self, segundos):
        self.agora += datetime.timedelta(seconds=segundos)


def opcoes_da_fila(relogio=None, **extra):
    relogio = relogio or Relogio()
    return {"relogio": relogio, "dormir": relogio.dormir, "pausa_s": (0, 0), "janelas": ["20:00-06:00"],
            "espera_base_s": 60, "tentativas_max": 3, **extra}


class ColetorAte:
    """Coletor simulado que só enxerga o que existia até uma data: faz o tempo passar entre os ciclos mudando `ate`."""

    def __init__(self, base, ate):
        self.base, self.ate = base, ate
        self.completos = []            # números cujo coletar() terminou sem erro (cada um conta uma coleta de verdade)

    def coletar(self, processo, profundidade, desde):
        r = self.base.coletar(processo, profundidade, desde)
        if r.get("erro"):
            return r
        r = dict(r)
        r["movimentos"] = [m for m in r["movimentos"] if m["data"] <= self.ate]
        r["documentos"] = [d for d in r["documentos"] if d["data"] <= self.ate]
        self.completos.append(processo["numero"])
        return r

    def __getattr__(self, nome):
        return getattr(self.base, nome)


class ProvedorFalso:
    """Provedor de IA falso (CONTRATOS §8): conta chamadas e devolve um resumo que cita o início do documento."""

    def __init__(self, motor="local:falso"):
        self.motor, self.chamadas, self.clientes = motor, 0, []

    def gerar(self, sistema, usuario, *, esquema=None, cliente="", partes=()):
        self.chamadas += 1
        self.clientes.append(cliente)
        texto = usuario.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0] if "<<<\n" in usuario else ""
        trecho = " ".join(texto.split())[:90]
        dados = {"conteudo": "determinando o cumprimento do que foi decidido", "trecho_origem": trecho, "prazo": None,
                 "audiencia": None, "efeito": "neutro"}
        return {"texto": json.dumps(dados), "json": dados, "motor": self.motor, "avisos": []}


def magra(f):
    """A ficha 'magra' de uma lista de números: só número, cliente, polo, parte contrária e responsável."""
    m = ficha.nova_ficha(f["numero"])
    for campo in ("cliente", "polo_cliente", "parte_contraria", "responsavel"):
        v = ficha.obter(f, campo)
        if v:
            ficha.definir(m, campo, v, "migrado")
    return m


def aprovar_tudo(projeto_slug=None, so_numeros=None):
    """A pessoa que revisa: todo rascunho vira aprovado."""
    lista = comum.eventos()
    n = 0
    for e in lista:
        if e["status"] == "rascunho" and (so_numeros is None or e["numero"] in so_numeros):
            e["status"] = "aprovado"
            n += 1
    comum.salvar_eventos(lista)
    return n


def dec(v):
    return ficha.dinheiro(v) or D(0)


class Base(unittest.TestCase):
    N, CLIENTES = 200, 5

    def abrir_projeto(self, magras=True, n=None, clientes=None, semente=1, reserva=0, **kw):
        """Projeto com `n` processos (lista de números) e o coletor simulado conhecendo `n + reserva` (os da reserva
        podem ser 'cadastrados depois'). `self.verdade` são as fichas completas que o tribunal simulado conhece."""
        n = n or self.N
        todas = ficticio.gerar_carteira(n + reserva, clientes=clientes or self.CLIENTES, semente=semente)
        self.verdade, self.reserva = list(todas), list(todas[n:])
        fichas = [magra(f) for f in todas[:n]] if magras else todas[:n]
        shutil.rmtree(TMP / "projetos-de-teste", ignore_errors=True)
        self.proj = ficticio.criar_projeto_de_teste(fichas, nome="Relatório de Fluxos")
        self.addCleanup(ficticio.restaurar_comum)
        self.slug = self.proj["slug"]
        self.relogio = Relogio()
        self.simulado = simulado.ColetorSimulado(todas, semente=1, taxa_falha=kw.pop("taxa_falha", 0.0),
                                                 pasta=self.proj["pasta"] / "docs-sim", **kw)
        self.coletor = ColetorAte(self.simulado, DATA_1)
        return self.proj

    def fila(self, **extra):
        return opcoes_da_fila(self.relogio, **extra)

    def inicial(self, **kw):
        kw.setdefault("profundidade", "padrao")
        kw.setdefault("modo", "imediato")
        kw.setdefault("data_base", DATA_1)
        kw.setdefault("coletor", self.coletor)
        kw.setdefault("fila_opcoes", self.fila())
        return fluxos.inicial(self.slug, **kw)

    def atualizar(self, arquivos=None, **kw):
        kw.setdefault("modo", "imediato")
        kw.setdefault("coletor", self.coletor)
        kw.setdefault("fila_opcoes", self.fila())
        return fluxos.atualizar(self.slug, arquivos, **kw)

    def fichas(self):
        with fluxos._em(self.slug):
            return ficha.carregar(todas=True)

    def eventos(self):
        with fluxos._em(self.slug):
            return comum.eventos()

    def codigos(self, r):
        return {a["codigo"] for a in r["avisos"]}


# ------------------------------------------------------------------ inicial

class Inicial(Base):
    N, CLIENTES = 12, 2

    def test_para_na_revisao_e_depois_entrega(self):
        self.abrir_projeto()
        r = self.inicial()
        self.assertTrue(r["ok"], r["resumo"])
        self.assertEqual(r["etapa"], "revisao")
        self.assertEqual(r["arquivos"], [])
        self.assertGreater(r["pendentes_de_revisao"], 0)
        eventos = self.eventos()
        self.assertEqual({e["status"] for e in eventos} - {"rascunho", "descartado"}, set())
        # nenhum evento nasce aprovado e todo rascunho traz motor e profundidade
        for e in eventos:
            self.assertEqual(e["profundidade"], "padrao")
            if e["status"] == "rascunho":
                self.assertIn("motor", e)
        # a capa foi gravada nas fichas, com origem coletado, e polo/parte contrária continuam os da lista
        for f in self.fichas():
            self.assertEqual(ficha.origem(f, "valor_causa"), "coletado")
            self.assertEqual(ficha.origem(f, "polo_cliente"), "migrado")
        r2 = self.inicial()                        # sem aprovar nada: continua parado na revisão, sem recoletar
        self.assertEqual(r2["etapa"], "revisao")
        self.assertEqual(len(self.coletor.completos), len(set(self.coletor.completos)), "ninguém foi recoletado")
        aprovar_tudo()
        r3 = self.inicial()
        self.assertEqual(r3["etapa"], "entregue", r3["resumo"])
        nomes = sorted(Path(a).name for a in r3["arquivos"])
        self.assertEqual(sum(n.endswith(".docx") for n in nomes), 2)
        self.assertTrue({"qualidade.html", "O que mudou neste ciclo.txt"} <= set(nomes))
        self.assertTrue(any(n.startswith("Planilha") for n in nomes) and any(n.startswith("Painel") for n in nomes))

    def test_tres_profundidades(self):
        quantidade = {}
        for prof in ("rapido", "padrao", "completo"):
            self.abrir_projeto(semente=2)
            r = self.inicial(profundidade=prof)
            self.assertEqual(r["etapa"], "revisao", (prof, r["resumo"]))
            docs = [e for e in self.eventos() if e["tipo_evento"] == "documento"]
            quantidade[prof] = len(docs)
            for e in self.eventos():
                self.assertEqual(e["profundidade"], prof)
            if prof == "rapido":
                self.assertEqual(docs, [], "no nível rápido nenhum documento é aberto")
            ficticio.restaurar_comum()
        self.assertEqual(quantidade["rapido"], 0)
        self.assertGreater(quantidade["padrao"], 0)
        self.assertGreaterEqual(quantidade["completo"], quantidade["padrao"])

    def test_momento_atual_ativo_e_ultimo_andamento(self):
        self.abrir_projeto()
        self.inicial()
        com_momento = [f for f in self.fichas() if ficha.obter(f, "momento_atual")]
        self.assertGreater(len(com_momento), 0)
        for f in com_momento:
            self.assertEqual(ficha.origem(f, "momento_atual"), "coletado")
            import taxonomia
            ativo = taxonomia.momento_ativo(ficha.obter(f, "momento_atual"))
            if ativo is not None:
                self.assertEqual(f["ativo"], ativo)
            self.assertEqual(ficha.validar(f), [])
        import traduzir
        for f in self.fichas():
            evs = [e for e in self.eventos() if e["numero"] in ficha.todos_os_numeros(f)]
            relevantes = [e for e in evs if e["tipo_evento"] == "documento" or traduzir.traduzir_movimento(e["titulo"])[1]]
            if evs:             # cálculo independente: a maior data entre documentos e movimentos que não são de rotina
                datas = [ficha.parse_data(e["data"]) for e in (relevantes or evs)]
                self.assertEqual(ficha.obter(f, "ultimo_andamento"), max(datas), f["numero"])

    def test_julgamento_so_sugerido_e_so_depois_da_revisao(self):
        self.abrir_projeto()
        self.inicial()
        for f in self.fichas():          # antes da revisão nenhum campo de julgamento foi tocado
            for c in ficha.CAMPOS_DE_JULGAMENTO:
                self.assertIsNone(ficha.obter(f, c))
        humano = self.fichas()[0]
        humano_numero = humano["numero"]
        with fluxos._em(self.slug):
            fs = ficha.carregar(todas=True)
            ficha.definir(fs[0], "probabilidade", "Remota", "humano")
            ficha.definir(fs[0], "resultado", "Improcedente", "humano")
            ficha.salvar(fs)
        aprovar_tudo()
        r = self.inicial()
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        f0 = next(f for f in self.fichas() if f["numero"] == humano_numero)
        self.assertEqual((ficha.origem(f0, "probabilidade"), ficha.obter(f0, "probabilidade")), ("humano", "Remota"))
        self.assertEqual((ficha.origem(f0, "resultado"), ficha.obter(f0, "resultado")), ("humano", "Improcedente"))
        origens = {ficha.origem(f, c) for f in self.fichas() for c in ficha.CAMPOS_DE_JULGAMENTO} - {None}
        self.assertTrue(origens <= {"sugerido", "humano"}, origens)

    def test_so_quem_nao_tem_relatorio_e_coletado(self):
        self.abrir_projeto()
        with fluxos._em(self.slug):
            fs = ficha.carregar(todas=True)
            for f in fs[:4]:                                   # estes já têm relatório anterior
                f["linha_de_base"] = {"data_base": "2026-06-30", "andamentos_texto": "Em 01/06/2026 foi feito algo.",
                                      "arquivo": "x.docx", "ultimo_andamento": "2026-06-01"}
            ficha.salvar(fs)
        r = self.inicial()
        self.assertEqual(r["processos"], self.N - 4)
        self.assertEqual(len(set(self.coletor.completos)), self.N - 4)
        # "todos" soma os que seguem ativos ao escopo do ciclo aberto (encerrado fora do ciclo não é acompanhado)
        r = self.inicial(todos=True, data_base="2026-07-31")
        self.assertEqual(r["processos"], self.N)
        self.assertEqual(len(self.coletor.completos), len(set(self.coletor.completos)))

    def test_conferir_manualmente_nao_trava_o_resto(self):
        self.abrir_projeto(falhar_em={})
        alvo = [f["numero"] for f in self.verdade]
        self.simulado.falhar_em = {alvo[0]: "captcha", alvo[1]: "segredo", alvo[2]: ("timeout", 1), alvo[3]: ("timeout", 9)}
        r = self.inicial()
        manual = {c["numero"]: c["codigo"] for c in r["conferir_manualmente"]}
        self.assertEqual(manual.get(alvo[0]), "captcha")
        self.assertEqual(manual.get(alvo[1]), "segredo")
        self.assertIn(alvo[3], manual)                            # timeout que não passa vira conferência depois das tentativas
        self.assertNotIn(alvo[2], manual)                          # timeout passageiro: repetiu e deu certo
        self.assertEqual(r["etapa"], "revisao")
        self.assertGreater(r["fila"]["coletado"], self.N - 6)
        aprovar_tudo()
        r = self.inicial()
        self.assertEqual(r["etapa"], "entregue")
        guardado = fluxos.ultimo_ciclo(self.slug)
        self.assertEqual({c["numero"] for c in guardado["conferir_manualmente"]}, set(manual))



# ------------------------------------------------------------------ entregas A, B e C com 200 processos

def _abrir_navegador():
    """(playwright, navegador) ou (None, None) se o Chromium não estiver disponível."""
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        return pw, pw.chromium.launch()
    except Exception:  # noqa: BLE001
        return None, None


class Entregas200(Base):
    N, CLIENTES = 200, 5

    def test_a_b_e_c_abrem_e_batem_com_calculo_independente(self):
        import openpyxl
        import docx
        from escritores import docx_a
        self.abrir_projeto()
        self.assertEqual(self.inicial()["etapa"], "revisao")
        aprovar_tudo()
        antes = self.eventos()
        r = self.inicial(entregas=["docx_a", "xlsx_b", "dashboard"])
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        self.assertEqual([a for a in r["avisos"] if a["nivel"] == "erro"], [])
        fichas = self.fichas()
        por_numero = {f["numero"]: f for f in fichas}
        self.assertEqual(len(fichas), self.N)
        arquivos = [Path(a) for a in r["arquivos"]]
        docxs = sorted(a for a in arquivos if a.suffix == ".docx")
        xlsx = next(a for a in arquivos if a.suffix == ".xlsx")
        html = next(a for a in arquivos if a.suffix == ".html" and a.name.startswith("Painel"))
        self.assertEqual(len(docxs), self.CLIENTES)
        # --- cálculo independente, a partir das fichas gravadas (não dos escritores)
        total = len(fichas)
        ativos = sum(1 for f in fichas if f.get("ativo", True))
        soma_causa = sum((dec(ficha.obter(f, "valor_causa")) for f in fichas), D(0))
        soma_causa_ativos = sum((dec(ficha.obter(f, "valor_causa")) for f in fichas if f.get("ativo", True)), D(0))
        # --- A: um bloco por processo, com o momento no título e as datas dos eventos aprovados no texto
        vistos = set()
        for caminho in docxs:
            doc = docx.Document(caminho)                                  # abre em python-docx
            est = docx_a.ler_estrutura(caminho)
            cliente = est["cliente"]
            esperados = {f["numero"] for f in fichas if ficha.obter(f, "cliente") == cliente}
            achados = {b["numeros"][0] for b in est["processos"]}
            self.assertEqual(achados, esperados, cliente)
            self.assertEqual(len(doc.tables), 1 + len(esperados))        # quadro-resumo + um bloco por processo
            vistos |= achados
            for b in est["processos"]:
                f = por_numero[b["numeros"][0]]
                momento = ficha.obter(f, "momento_atual")
                if momento:
                    self.assertEqual(b["momento"], momento, f["numero"])
                for e in antes:
                    if e["numero"] in ficha.todos_os_numeros(f) and e["status"] == "aprovado":
                        self.assertIn(e["data"], b["andamentos_texto"], (f["numero"], e["titulo"]))
        self.assertEqual(vistos, set(por_numero))
        # --- B: uma linha por processo; soma de Valor da Causa igual à das fichas; texto com as datas
        wb = openpyxl.load_workbook(xlsx, data_only=True)
        ws = wb["Processos"]
        cab = [c.value for c in ws[1]]
        col = {nome: i for i, nome in enumerate(cab)}
        linhas = [row for row in ws.iter_rows(min_row=2, values_only=True) if row[col["Número do Processo"]]]
        self.assertEqual(len(linhas), total)
        self.assertEqual({l[col["Número do Processo"]] for l in linhas}, set(por_numero))
        self.assertEqual(sum((D(str(l[col["Valor da Causa"]] or 0)) for l in linhas), D(0)).quantize(D("0.01")), soma_causa)
        for l in linhas:
            f = por_numero[l[col["Número do Processo"]]]
            texto = l[col["Andamentos"]] or ""
            for e in antes:
                if e["numero"] in ficha.todos_os_numeros(f) and e["status"] == "aprovado":
                    self.assertIn(e["data"], texto, (f["numero"], e["titulo"]))
        # --- C: abre no navegador, sem rede, e os números do painel são os mesmos
        pw, navegador = _abrir_navegador()
        if pw is None:
            self.skipTest("Chromium indisponível neste ambiente")
        self.addCleanup(pw.stop)
        ctx = navegador.new_context()
        externas = []
        ctx.route("**/*", lambda rota: rota.continue_() if rota.request.url.startswith(("file:", "data:", "blob:", "about:"))
                  else (externas.append(rota.request.url), rota.abort()))
        pagina = ctx.new_page()
        erros = []
        pagina.on("pageerror", lambda e: erros.append(str(e)))
        pagina.goto(html.resolve().as_uri())
        pagina.wait_for_function("document.documentElement.dataset.pronto === '1'", timeout=60000)
        ind = pagina.evaluate("JSON.parse(JSON.stringify(DASH.estado.ind))")
        ctx.close()
        navegador.close()
        self.assertEqual((externas, erros), ([], []))
        self.assertEqual((ind["total"], ind["ativos"], ind["encerrados"]), (total, ativos, total - ativos))
        self.assertAlmostEqual(ind["valorCausaAtivos"], float(soma_causa_ativos), delta=0.01)

    def test_qualidade_o_que_mudou_e_retrato_mensal(self):
        self.abrir_projeto()
        self.inicial()
        aprovar_tudo()
        r = self.inicial()
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        self.assertIsNotNone(r["qualidade"])
        self.assertIn("O que mudou", Path(next(a for a in r["arquivos"] if "mudou" in str(a))).read_text(encoding="utf-8"))
        depois = r["o_que_mudou"]["totais"]["depois"]
        self.assertEqual((depois["processos"], depois["ativos"]), (self.N, sum(1 for f in self.fichas() if f.get("ativo", True))))
        retrato = Path(r["retrato"])
        dados = json.loads(retrato.read_text(encoding="utf-8"))
        fichas = self.fichas()
        self.assertEqual(dados["data_base"], DATA_1)
        self.assertEqual(dados["totais"]["processos"], len(fichas))
        self.assertEqual(D(dados["totais"]["valor_causa"]), sum((dec(ficha.obter(f, "valor_causa")) for f in fichas), D(0)))
        self.assertEqual(len(dados["por_processo"]), len(fichas))
        with fluxos._em(self.slug):
            self.assertEqual([x["data_base"] for x in historico.carregar(self.slug)], [DATA_1])


# ------------------------------------------------------------------ atualizar

def _estrutura(caminho):
    from escritores import docx_a
    return docx_a.ler_estrutura(caminho)


def _andamentos_por_numero(docxs):
    saida = {}
    for caminho in docxs:
        for b in _estrutura(caminho)["processos"]:
            saida[b["numeros"][0]] = [(a["data"], a["texto"]) for a in b["andamentos"]]
    return saida


def editar_docx_a_mao(origem, destino, numero, frase):
    """O advogado acrescenta uma frase à mão no texto de andamentos de um processo (python-docx)."""
    import docx
    doc = docx.Document(origem)
    for tabela in doc.tables[1:]:
        if numero in tabela.rows[0].cells[0].text:
            for linha in tabela.rows:
                if linha.cells[0].text.strip().startswith("Andamentos"):
                    linha.cells[1].paragraphs[-1].add_run(" " + frase)
                    doc.save(destino)
                    return destino
    raise AssertionError(f"processo {numero} não achado em {origem}")


class Atualizar(Base):
    N, CLIENTES = 200, 5

    def _ciclo(self, data_base, ate, arquivos=None, depois=None):
        """Um ciclo completo: atualizar (para na revisão), revisão humana, atualizar de novo (entrega)."""
        self.coletor.ate = ate
        r = self.atualizar(arquivos, data_base=data_base)
        self.assertIn(r["etapa"], ("revisao", "entregue"), r["resumo"])
        n = aprovar_tudo()
        if depois:
            depois()
        r = self.atualizar(None, data_base=data_base)
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        return r, n

    def test_tres_ciclos_sem_duplicar_sem_perder_humano_e_sem_sobrescrever_edicao_manual(self):
        self.abrir_projeto(reserva=1)
        r0 = self.inicial()
        with fluxos._em(self.slug):                                # um campo humano que nenhum ciclo pode perder
            fs = ficha.carregar(todas=True)
            ficha.definir(fs[3], "valor_estimado", "1234.56", "humano")
            ficha.definir(fs[3], "observacoes", "Cliente prioritário", "humano")
            humano_numero = fs[3]["numero"]
            ficha.salvar(fs)
        aprovar_tudo()
        r0 = self.inicial()
        self.assertEqual(r0["etapa"], "entregue", r0["resumo"])
        saida0 = [Path(a) for a in r0["arquivos"]]
        base0 = _andamentos_por_numero(a for a in saida0 if a.suffix == ".docx")
        # ---- ciclo 2: sem enviar arquivo (parte da última entrega do programa); só vem o que é posterior
        r1, n1 = self._ciclo(DATA_2, DATA_2)
        self.assertGreater(n1, 0)
        saida1 = [Path(a) for a in r1["arquivos"]]
        base1 = _andamentos_por_numero(a for a in saida1 if a.suffix == ".docx")
        for numero, antigos in base0.items():
            self.assertEqual(base1[numero][:len(antigos)], antigos, f"{numero}: o que já estava no texto não pode mudar")
        novos_ciclo2 = sum(len(base1[n]) - len(base0[n]) for n in base0)
        self.assertGreater(novos_ciclo2, 0)
        # ---- ciclo 3: o advogado edita um texto à mão e envia o .docx; entra um processo novo na carteira
        alvo = next(n for n, a in base1.items() if len(a) > 2)
        docx_enviado = next(a for a in saida1 if a.suffix == ".docx" and alvo in str(_estrutura(a)["processos"]))
        editado = editar_docx_a_mao(docx_enviado, TMP / "editado-por-advogado.docx", alvo,
                                    "Em 05/09/2026, o cliente telefonou pedindo notícias (nota do advogado).")
        novo_numero = self.reserva[0]["numero"]
        with fluxos._em(self.slug):
            fs = ficha.carregar(todas=True)
            fs.append(magra(self.reserva[0]))
            ficha.salvar(fs)
        r2, n2 = self._ciclo(DATA_3, DATA_3, arquivos=[editado])
        self.assertIn("texto_editado_a_mao", self.codigos(r2) | {a["codigo"] for a in r2["avisos"]})
        avisos_edicao = [a for a in r2["avisos"] if a["codigo"] == "texto_editado_a_mao"]
        self.assertEqual([a["onde"] for a in avisos_edicao], [alvo])
        saida2 = [Path(a) for a in r2["arquivos"]]
        base2 = _andamentos_por_numero(a for a in saida2 if a.suffix == ".docx")
        self.assertIn(novo_numero, base2)                                   # o processo novo entrou
        self.assertTrue(base2[novo_numero])
        estrutura_alvo = next(b for a in saida2 if a.suffix == ".docx" for b in _estrutura(a)["processos"] if b["numeros"][0] == alvo)
        self.assertIn("nota do advogado", estrutura_alvo["andamentos_texto"])      # a edição manual sobreviveu
        for numero, antigos in base1.items():
            if numero != alvo:
                self.assertEqual(base2[numero][:len(antigos)], antigos)
        # ---- em nenhum ciclo houve duplicata de andamento nem perda de campo humano; evento relatado uma vez só
        for base in (base0, base1, base2):
            for numero, lista in base.items():
                self.assertEqual(len(lista), len(set(lista)), f"{numero}: andamento duplicado")
        ids = [e["id"] for e in self.eventos()]
        self.assertEqual(len(ids), len(set(ids)))
        h = next(f for f in self.fichas() if f["numero"] == humano_numero)
        self.assertEqual((ficha.origem(h, "valor_estimado"), ficha.obter(h, "valor_estimado")), ("humano", "1234.56"))
        self.assertEqual(ficha.obter(h, "observacoes"), "Cliente prioritário")
        # ---- três retratos mensais coerentes com as fichas
        with fluxos._em(self.slug):
            serie = historico.carregar(self.slug)
        self.assertEqual([x["data_base"] for x in serie], [DATA_1, DATA_2, DATA_3])
        self.assertEqual([x["totais"]["processos"] for x in serie], [self.N, self.N, self.N + 1])
        # ---- a planilha da última entrega tem a linha do processo novo e o texto sem duplicata
        import openpyxl
        xlsx = next(a for a in saida2 if a.suffix == ".xlsx")
        ws = openpyxl.load_workbook(xlsx, data_only=True)["Processos"]
        cab = [c.value for c in ws[1]]
        numeros_b = {row[cab.index("Número do Processo")] for row in ws.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(numeros_b, {f["numero"] for f in self.fichas()})
        self.assertGreaterEqual(len(r2["arquivos"]), 8)


# ------------------------------------------------------------------ interrupção e retomada

class ArquivoEnviado(Base):
    N, CLIENTES = 30, 3

    def test_processo_novo_sumido_e_campo_humano_do_arquivo(self):
        self.abrir_projeto(reserva=1)
        self.inicial()
        aprovar_tudo()
        self.assertEqual(self.inicial()["etapa"], "entregue")
        fichas = [dict(f) for f in self.fichas()]
        ativas = [f for f in fichas if f.get("ativo", True)]
        sumido = ativas[0]["numero"]
        enviadas = [f for f in fichas if f["numero"] != sumido]
        ficha.definir(enviadas[0], "probabilidade", "Remota", "humano")          # o advogado preencheu na planilha
        ficha.definir(enviadas[0], "resultado", "Improcedente", "humano")
        novo = ficticio.anexar_linha_de_base(self.reserva[0], data_base=DATA_1)
        enviadas.append(novo)
        arquivo = escrever_xlsx_b(enviadas, TMP / "planilha-enviada.xlsx", "Relatório de Fluxos", DATA_1)
        self.coletor.ate = DATA_2                                      # um mês depois: há novidades para revisar
        r = self.atualizar([arquivo], data_base=DATA_2)
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(r["novos"], [novo["numero"]])
        self.assertEqual(r["sumiram"], [sumido])
        codigos = {a["codigo"] for a in r["avisos"]}
        self.assertTrue({"processo_novo_no_arquivo", "processo_sumiu_do_arquivo"} <= codigos)
        por_numero = {f["numero"]: f for f in self.fichas()}
        self.assertIn(novo["numero"], por_numero)
        self.assertTrue(por_numero[novo["numero"]]["linha_de_base"]["andamentos_texto"])
        self.assertFalse(por_numero[novo["numero"]].get("precisa_relatorio_inicial"))
        self.assertTrue(por_numero[sumido].get("ativo", True) or por_numero[sumido].get("ultima_coleta"))   # segue na carteira
        alvo = por_numero[enviadas[0]["numero"]]
        self.assertEqual((ficha.origem(alvo, "probabilidade"), ficha.obter(alvo, "probabilidade")), ("humano", "Remota"))
        self.assertEqual(ficha.obter(alvo, "resultado"), "Improcedente")
        # o arquivo enviado foi guardado em entrada/ e é o molde da entrega seguinte; o original não é tocado
        guardado = list((self.proj["pasta"] / "entrada").glob("*planilha-enviada*.xlsx"))
        self.assertEqual(len(guardado), 1)
        antes = arquivo.read_bytes()
        aprovar_tudo()
        r = self.atualizar(None, data_base=DATA_2)
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        self.assertEqual(arquivo.read_bytes(), antes)
        self.assertEqual(sum(str(a).endswith(".xlsx") for a in r["arquivos"]), 1)

    def test_arquivo_que_nao_e_do_programa_e_recusado_sem_travar(self):
        self.abrir_projeto()
        lixo = TMP / "nao-e-relatorio.xlsx"
        lixo.write_bytes(b"x")
        r = self.atualizar([lixo], data_base=DATA_1)
        self.assertFalse(r["ok"])
        self.assertIn("arquivo_nao_aceito", {a["codigo"] for a in r["avisos"]})
        self.assertEqual(self.eventos(), [])



class DataJud(Base):
    N, CLIENTES = 12, 2

    def _resposta(self, numero):
        """Resposta do DataJud no formato da wiki (fixture da WS-4) para o número pedido."""
        bruto = (Path(__file__).resolve().parent / "fixtures" / "capa" / "datajud_resposta.json").read_text(encoding="utf-8")
        digitos = "".join(c for c in numero if c.isdigit())
        return json.dumps(json.loads(bruto.replace("@@DIGITOS@@", digitos))).encode()

    def test_capa_do_datajud_completa_o_que_o_coletor_nao_trouxe_e_so_com_chave(self):
        import capa
        self.abrir_projeto()
        pedidos = []

        def transporte(url, cabecalhos, corpo):
            pedidos.append(url)
            numero = next(f["numero"] for f in self.verdade if "".join(c for c in f["numero"] if c.isdigit()) in corpo.decode())
            return 200, self._resposta(numero)
        # coletor "real": traz movimentos e documentos, mas capa vazia
        class SemCapa(ColetorAte):
            def coletar(self, processo, profundidade, desde):
                r = super().coletar(processo, profundidade, desde)
                return dict(r, capa={}) if not r.get("erro") else r
        self.coletor = SemCapa(self.simulado, DATA_1)
        capa._ultima_datajud[0] = 0.0
        with mock.patch.object(fluxos, "TRANSPORTE_DATAJUD", transporte), \
                mock.patch.object(capa, "DATAJUD_INTERVALO_S", 0), \
                mock.patch.object(capa, "_config_datajud", lambda: (True, "chave-publica-ficticia")):
            r = self.inicial()
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self.assertEqual(len(pedidos), self.N)
        com_classe = [f for f in self.fichas() if ficha.obter(f, "classe")]
        self.assertTrue(com_classe)
        for f in com_classe:
            self.assertEqual(ficha.origem(f, "classe"), "coletado")
        # sem chave: nenhuma chamada e nenhum aviso por processo
        self.abrir_projeto()
        pedidos.clear()
        with mock.patch.object(fluxos, "TRANSPORTE_DATAJUD", transporte), \
                mock.patch.object(capa, "_config_datajud", lambda: (True, "")):
            r = self.inicial()
        self.assertEqual(pedidos, [])
        self.assertNotIn("datajud_sem_chave", self.codigos(r))

    def test_datajud_recusando_a_chave_vira_um_aviso_so_e_nao_trava(self):
        import capa
        self.abrir_projeto()

        class SemCapa(ColetorAte):
            def coletar(self, processo, profundidade, desde):
                r = super().coletar(processo, profundidade, desde)
                return dict(r, capa={}) if not r.get("erro") else r
        self.coletor = SemCapa(self.simulado, DATA_1)
        capa._ultima_datajud[0] = 0.0
        with mock.patch.object(fluxos, "TRANSPORTE_DATAJUD", lambda *a: (401, b"{}")), \
                mock.patch.object(capa, "DATAJUD_INTERVALO_S", 0), \
                mock.patch.object(capa, "_config_datajud", lambda: (True, "chave-velha")):
            self.inicial()
            aprovar_tudo()
            r = self.inicial()
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        recusas = [a for a in r["avisos"] if a["codigo"] == "datajud_chave_recusada"]
        self.assertEqual(len(recusas), 1)



class Interrompe:
    """Coletor que levanta KeyboardInterrupt (Ctrl+C) na chamada de número `quando`."""

    def __init__(self, base, quando):
        self.base, self.quando, self.chamadas = base, quando, 0

    def coletar(self, processo, profundidade, desde):
        self.chamadas += 1
        if self.chamadas == self.quando:
            raise KeyboardInterrupt()
        return self.base.coletar(processo, profundidade, desde)

    def __getattr__(self, nome):
        return getattr(self.base, nome)


class Retomada(Base):
    N, CLIENTES = 30, 3

    def _limpo(self):
        """Os eventos de uma rodada sem interrupção (a referência)."""
        self.abrir_projeto()
        self.inicial()
        ids = {e["id"] for e in self.eventos()}
        ficticio.restaurar_comum()
        return ids

    def _conferir_retomada(self, referencia, coletados_antes, completos_antes):
        eventos = self.eventos()
        ids = [e["id"] for e in eventos]
        self.assertEqual(len(ids), len(set(ids)), "evento duplicado depois da retomada")
        self.assertEqual(set(ids), referencia, "a retomada deve chegar ao mesmo conjunto de eventos")
        repetidos = [n for n in self.coletor.completos[completos_antes:] if n in coletados_antes]
        self.assertEqual(repetidos, [], "processo já coletado foi coletado de novo")

    def _estado_da_fila(self):
        import fila
        f = fila.Fila(self.slug, **self.fila())
        return {i["numero"] for i in f.itens(estado="coletado")}

    def test_ctrl_c_em_cinco_pontos_distintos(self):
        referencia = self._limpo()
        for quando in (1, 4, 13, 22, 30):
            with self.subTest(interrupcao_na_chamada=quando):
                self.abrir_projeto()
                self.coletor = ColetorAte(Interrompe(self.simulado, quando), DATA_1)
                r = self.inicial()
                self.assertFalse(r["ok"])
                self.assertTrue(r.get("interrompido"))
                coletados = self._estado_da_fila()
                self.assertEqual(len(coletados), quando - 1)
                completos = len(self.coletor.completos)
                r = self.inicial()
                self.assertEqual(r["etapa"], "revisao", r["resumo"])
                self._conferir_retomada(referencia, coletados, completos)
                ficticio.restaurar_comum()

    def test_queda_depois_de_coletar_e_antes_de_gravar_repete_so_aquele_processo(self):
        referencia = self._limpo()
        self.abrir_projeto()
        original = fluxos.processar_resultado
        chamadas = []

        def cai_na_septima(slug, numero, resultado, profundidade=None):
            chamadas.append(numero)
            if len(chamadas) == 7:
                raise OSError("disco cheio (simulado)")
            return original(slug, numero, resultado, profundidade)
        with mock.patch.object(fluxos, "processar_resultado", cai_na_septima):
            r = self.inicial()
        self.assertEqual(r["etapa"], "revisao")                  # o resto não travou; o processo caído foi repetido
        eventos = [e["id"] for e in self.eventos()]
        self.assertEqual(len(eventos), len(set(eventos)))
        self.assertEqual(set(eventos), referencia)
        self.assertEqual(len(chamadas), self.N + 1)              # uma tentativa a mais, só dele
        self.assertEqual(len(self.coletor.completos), self.N + 1)

    def test_parar_com_seguranca_e_continuar(self):
        referencia = self._limpo()
        self.abrir_projeto()
        import fila
        pedido = {}

        def progresso(d):
            if d.get("etapa") == "coleta" and d.get("evento") == "coletado" and d.get("coletado") == 10 and not pedido:
                pedido["feito"] = True
                fila.Fila(self.slug, **self.fila()).parar_com_seguranca()
        r = self.inicial(ao_progresso=progresso)
        self.assertEqual(r["etapa"], "coleta")                   # parou no meio, tudo gravado
        coletados = self._estado_da_fila()
        self.assertEqual(len(coletados), 10)
        completos = len(self.coletor.completos)
        r = self.inicial()
        self.assertEqual(r["etapa"], "revisao", r["resumo"])
        self._conferir_retomada(referencia, coletados, completos)

    def test_falha_na_entrega_nao_perde_nada_e_a_repeticao_entrega(self):
        self.abrir_projeto()
        self.inicial()
        aprovar_tudo()
        from escritores import xlsx_b
        with mock.patch.object(xlsx_b, "gravar", side_effect=RuntimeError("Excel indisponível (simulado)")):
            r = self.inicial()
        self.assertFalse(r["ok"])
        self.assertIn("escritor_falhou", self.codigos(r))
        self.assertEqual({e["status"] for e in self.eventos()} - {"aprovado", "descartado"}, set(),
                         "nada pode ficar 'relatado' se a planilha não saiu")
        r = self.inicial()
        self.assertEqual(r["etapa"], "entregue", r["resumo"])
        self.assertEqual(sum(e["status"] == "relatado" for e in self.eventos()),
                         sum(1 for e in self.eventos() if e["status"] != "descartado"))


# ------------------------------------------------------------------ IA e consentimento

class Cofre:
    """Substitui acesso.obter/guardar por um dicionário (nenhum cofre real)."""

    def __init__(self):
        self.dados = {}

    def __enter__(self):
        import acesso
        self.patches = [mock.patch.object(acesso, "obter", lambda c: self.dados.get(c)),
                        mock.patch.object(acesso, "guardar", lambda c, v: self.dados.__setitem__(c, v))]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()


class Transporte:
    """HTTP falso do provedor compatível com OpenAI: guarda o que seria enviado e devolve um resumo válido."""

    def __init__(self):
        self.pedidos = []

    def __call__(self, url, cabecalhos, corpo, timeout):
        dados = json.loads(corpo)
        self.pedidos.append(dados)
        usuario = next(m["content"] for m in reversed(dados["messages"]) if m["role"] == "user")
        texto = usuario.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0] if "<<<\n" in usuario else ""
        resposta = {"conteudo": "determinando o que foi decidido", "trecho_origem": " ".join(texto.split())[:80], "prazo": None,
                    "audiencia": None, "efeito": "neutro"}
        return 200, json.dumps({"model": "modelo-x", "choices": [{"message": {"content": json.dumps(resposta)},
                                                                    "finish_reason": "stop"}]}).encode()


class IA(Base):
    N, CLIENTES = 30, 3

    def setUp(self):
        import ia
        self.ia = ia
        self.cofre = Cofre().__enter__()
        self.addCleanup(self.cofre.__exit__)
        self.config = TMP / f"config-fluxos-{self._testMethodName}.json"
        self.config.unlink(missing_ok=True)
        p = mock.patch.object(comum, "CONFIG_FILE", self.config)
        p.start()
        self.addCleanup(p.stop)
        self.assertEqual(ia.cadastrar("externo-a", "openai_compativel", "modelo-x", endereco="https://api.exemplo.invalid/v1",
                                      chave="chave-ficticia-ABCDEF123456"), [])
        self.transporte, self.chamadas_locais = Transporte(), []

        def ollama(caminho, corpo=None, timeout=300):
            self.chamadas_locais.append(corpo)
            usuario = corpo["messages"][-1]["content"]
            texto = usuario.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0] if "<<<\n" in usuario else ""
            return {"message": {"content": json.dumps({"conteudo": "determinando o que foi decidido", "prazo": None,
                                                      "trecho_origem": " ".join(texto.split())[:80], "audiencia": None,
                                                      "efeito": "neutro"})}}
        local = ia.ProvedorLocal(modelo="modelo-local:1b", ollama=ollama)
        fabrica = lambda perfil, cliente: ia.provedor(perfil, cliente, projeto=self.slug, local=local, transporte=self.transporte)
        p2 = mock.patch.object(fluxos, "FABRICA_DE_PROVEDOR", fabrica)
        p2.start()
        self.addCleanup(p2.stop)

    def _perfil(self, **ia_):
        from painel import perfil as per
        with fluxos._em(self.slug):
            perfil = per.carregar(self.slug)
            perfil["ia"] = {"provedor": "externo-a", "consentimento_externo": False, "pseudonimizar": False, "por_cliente": {}, **ia_}
            per.salvar(perfil, self.slug)

    def _clientes_dos_documentos(self, motor_prefixo):
        return {e["cliente"] for e in self.eventos() if e["tipo_evento"] == "documento" and (e.get("motor") or "").startswith(motor_prefixo)}

    def test_sem_consentimento_nada_sai_do_computador(self):
        self.abrir_projeto()
        self._perfil()
        self.inicial()
        docs = [e for e in self.eventos() if e["tipo_evento"] == "documento"]
        self.assertGreater(len(docs), 0)
        self.assertEqual(self.transporte.pedidos, [], "nenhum pedido pode ter ido ao provedor externo")
        self.assertGreater(len(self.chamadas_locais), 0)
        self.assertEqual({(e["motor"] or "").split(":")[0] for e in docs if e["status"] == "rascunho"}, {"local"})
        self.assertEqual(self.ia.registro_de_envios(self.slug), [])

    def test_consentimento_por_cliente_so_vale_para_aquele_cliente(self):
        self.abrir_projeto()
        cliente = sorted({ficha.obter(f, "cliente") for f in self.verdade})[0]
        self._perfil(por_cliente={cliente: True})
        self.inicial()
        externos = self._clientes_dos_documentos("externo:")
        locais = self._clientes_dos_documentos("local:")
        self.assertEqual(externos, {cliente})
        self.assertTrue(locais and cliente not in locais)
        self.assertGreater(len(self.transporte.pedidos), 0)
        envios = self.ia.registro_de_envios(self.slug)
        self.assertTrue(envios and {e["cliente"] for e in envios} == {cliente})
        # o selo mostra a origem de cada resumo
        selos = {self.ia.selo(e["motor"]) for e in self.eventos() if e["tipo_evento"] == "documento" and e["status"] == "rascunho"}
        self.assertEqual(selos, {"local", "externa: externo-a"})

    def test_consentimento_do_relatorio_inteiro(self):
        self.abrir_projeto()
        self._perfil(consentimento_externo=True)
        self.inicial()
        self.assertEqual(self._clientes_dos_documentos("local:"), set())
        self.assertGreater(len(self.transporte.pedidos), 0)

    def test_ia_fora_do_ar_vira_rascunho_sem_resumo_e_nao_trava(self):
        self.abrir_projeto()
        self._perfil()
        with mock.patch.object(fluxos, "FABRICA_DE_PROVEDOR", lambda perfil, cliente: ProvedorQueFalha()):
            r = self.inicial()
        self.assertEqual(r["etapa"], "revisao")
        docs = [e for e in self.eventos() if e["tipo_evento"] == "documento" and e["status"] == "rascunho"]
        self.assertTrue(docs)
        for e in docs:
            self.assertFalse(e["conteudo"])
            self.assertTrue(any("Sem resumo automático" in a for a in e["alertas"]))
            self.assertEqual(e["motor"], "regra")


class ProvedorQueFalha:
    def gerar(self, *a, **k):
        raise ConnectionError("sem rede (simulado)")


# ------------------------------------------------------------------ migrar (importar relatórios existentes)

def escrever_docx_a(fichas, destino, cliente, data_base):
    from escritores import docx_a
    estado = {"cliente": cliente, "data_base": data_base, "fichas": fichas, "eventos": [], "perfil": {"estilo_texto": "a"},
              "parametros": {}}
    res = docx_a.gravar(None, estado, Path(destino))
    assert res["destino"], res["avisos"]
    return Path(destino)


def escrever_xlsx_b(fichas, destino, cliente, data_base, historico_=None):
    from escritores import xlsx_b
    estado = {"cliente": cliente, "data_base": data_base, "fichas": fichas, "eventos": [], "perfil": {"molde_planilha": "padrao"},
              "parametros": {}, "historico": historico_ or []}
    res = xlsx_b.gravar(None, estado, Path(destino), invalidar_cache=True)
    assert res["destino"], res["avisos"]
    return Path(destino)


class Migrar(Base):
    N, CLIENTES = 60, 3

    def setUp(self):
        shutil.rmtree(TMP / "projetos-de-teste", ignore_errors=True)
        self.proj = ficticio.criar_projeto_de_teste([], nome="Projeto Existente")      # só para isolar o comum
        self.addCleanup(ficticio.restaurar_comum)
        self.pasta = TMP / f"migrar-{self._testMethodName}"
        shutil.rmtree(self.pasta, ignore_errors=True)
        self.pasta.mkdir(parents=True)
        self.carteira = ficticio.gerar_carteira(self.N, clientes=self.CLIENTES, semente=4, com_linha_de_base=True)
        nomes = sorted({ficha.obter(f, "cliente") for f in self.carteira})
        self.por_cliente = {n: [f for f in self.carteira if ficha.obter(f, "cliente") == n] for n in nomes}

    def _arquivos(self):
        c1, c2, c3 = self.por_cliente.values()
        self.docx = escrever_docx_a(c1, self.pasta / "relatorio-a.docx", ficha.obter(c1[0], "cliente"), "2026-09-18")
        self.xlsx = escrever_xlsx_b(c2, self.pasta / "planilha-b.xlsx", ficha.obter(c2[0], "cliente"), "2026-09-18")
        extra = [c1[0]] + c3[:10]                                  # um número que já está no .docx e 10 do terceiro cliente
        self.lista = ficticio.gerar_lista_bruta(self.pasta / "listas", extra)["csv"]
        return [self.docx, self.xlsx, self.lista["arquivo"]]

    def test_docx_xlsx_e_lista_viram_fichas_linhas_de_base_e_vinculos(self):
        arquivos = self._arquivos()
        antes = [s for s, _ in comum.projetos()]
        previa = fluxos.migrar(arquivos, confirmar=False)
        self.assertTrue(previa["ok"], previa["resumo"])
        self.assertFalse(previa["confirmado"])
        self.assertEqual([s for s, _ in comum.projetos()], antes, "a conferência não grava nada")
        c1, c2, c3 = self.por_cliente.values()
        sem = fluxos.migrar(arquivos, confirmar=False)               # a planilha não traz o cliente: o programa avisa
        self.assertIn("processo_sem_cliente", {a["codigo"] for a in sem["avisos"]})
        r = fluxos.migrar(arquivos, nome="Relatório Migrado", cliente_padrao=ficha.obter(c2[0], "cliente"))
        self.assertTrue(r["ok"], r["resumo"])
        esperados = {f["numero"] for f in c1 + c2} | set(self.lista["validos"])
        with fluxos._em(r["projeto"]):
            fichas = ficha.carregar(todas=True)
        por_numero = {f["numero"]: f for f in fichas}
        self.assertEqual(set(por_numero), esperados)
        self.assertEqual(r["processos"], len(esperados))
        self.assertEqual(r["data_base"], "2026-09-18")
        # linha de base: texto lido do relatório (nunca recoletado); só-lista fica marcado "novo, precisa de relatório inicial"
        for f in c1 + c2:
            lb = por_numero[f["numero"]]["linha_de_base"]
            self.assertEqual(lb["data_base"], "2026-09-18")
            self.assertTrue(lb["andamentos_texto"].strip(), f["numero"])
            self.assertFalse(por_numero[f["numero"]].get("precisa_relatorio_inicial"))
        so_lista = set(self.lista["validos"]) - {f["numero"] for f in c1 + c2}
        self.assertEqual(set(r["novos_sem_relatorio"]), so_lista)
        for n in so_lista:
            self.assertTrue(por_numero[n]["precisa_relatorio_inicial"])
            self.assertFalse(por_numero[n]["linha_de_base"])
        # vínculos conservados (principal + vinculados = uma linha)
        com_vinculo = [f for f in c1 + c2 if f["vinculados"]]
        self.assertTrue(com_vinculo)
        for f in com_vinculo:
            lidos = {v["numero"]: v["tipo"] for v in por_numero[f["numero"]]["vinculados"]}
            self.assertEqual(set(lidos), {v["numero"] for v in f["vinculados"]}, f["numero"])
            if f in c1:           # o texto (modelo A) guarda o tipo; a planilha (modelo B) só lista os números
                self.assertEqual(lidos, {v["numero"]: v["tipo"] for v in f["vinculados"]}, f["numero"])
        # o que o usuário lançou no relatório (colunas de julgamento da planilha) entra como humano
        for f in c2:
            for campo in ("probabilidade", "resultado"):
                if ficha.obter(f, campo):
                    self.assertEqual(ficha.obter(por_numero[f["numero"]], campo), ficha.obter(f, campo), (f["numero"], campo))
                    self.assertEqual(ficha.origem(por_numero[f["numero"]], campo), "humano")
        # relatório de ambiguidades: número com dígito errado listado, não importado
        invalidos = self.lista["invalidos"]
        self.assertTrue(invalidos)
        todos_avisos = [a for g in r["ambiguidades"].values() for a in g]
        self.assertTrue(any(i in a["mensagem"] or i in a["onde"] for i in invalidos for a in todos_avisos), "dígito errado não listado")
        self.assertTrue(set(invalidos).isdisjoint(por_numero))
        self.assertEqual(r["clientes"], sorted(self.por_cliente))
        # arquivos enviados guardados em entrada/ e perfil ajustado ao que foi enviado
        self.assertEqual(len(r["copias_em_entrada"]), 3)
        from painel import perfil as per
        with fluxos._em(r["projeto"]):
            perfil = per.carregar(r["projeto"])
        self.assertEqual(perfil["entregas"], ["docx_a", "xlsx_b", "dashboard"])
        self.assertEqual(perfil["molde_planilha"], "cliente")
        # segunda importação: nada muda e nada humano se perde
        r2 = fluxos.migrar(arquivos, projeto=r["projeto"])
        self.assertEqual((r2["adicionadas"], r2["atualizadas"]), (0, 0))
        with fluxos._em(r["projeto"]):
            outra = {f["numero"]: f for f in ficha.carregar(todas=True)}
        for n, f in por_numero.items():
            self.assertEqual(f["campos"], outra[n]["campos"], n)

    def test_numero_em_dois_arquivos_vale_o_mais_recente_e_avisa(self):
        c1 = next(iter(self.por_cliente.values()))
        antigo = escrever_docx_a(c1, self.pasta / "agosto.docx", ficha.obter(c1[0], "cliente"), "2026-08-31")
        novo = escrever_docx_a(c1, self.pasta / "setembro.docx", ficha.obter(c1[0], "cliente"), "2026-09-30")
        r = fluxos.migrar([antigo, novo], nome="Dois Meses")
        self.assertIn("processo_em_varios_arquivos", {a["codigo"] for a in r["avisos"]})
        with fluxos._em(r["projeto"]):
            fichas = ficha.carregar(todas=True)
        self.assertEqual(len(fichas), len(c1))
        self.assertTrue(all(f["linha_de_base"]["data_base"] == "2026-09-30" for f in fichas))

    def test_serie_de_tres_meses_reconstroi_o_historico(self):
        todos = next(iter(self.por_cliente.values()))
        cliente = ficha.obter(todos[0], "cliente")
        cortes = {"2026-07-31": todos[:5], "2026-08-31": todos[:8], "2026-09-30": todos[:10]}
        arquivos = [escrever_xlsx_b(fs, self.pasta / f"{db}.xlsx", cliente, db) for db, fs in cortes.items()]
        r = fluxos.migrar(arquivos, nome="Série")
        self.assertEqual(r["serie"], list(cortes))
        with fluxos._em(r["projeto"]):
            serie = historico.carregar(r["projeto"])
        self.assertEqual([x["data_base"] for x in serie], list(cortes))
        for retrato, (db, fs) in zip(serie, cortes.items()):             # cálculo independente por mês
            self.assertEqual(retrato["totais"]["processos"], len(fs))
            self.assertEqual(D(retrato["totais"]["valor_causa"]),
                             sum((dec(ficha.obter(f, "valor_causa")) for f in fs), D(0)).quantize(D("0.01")))
            self.assertEqual({p["numero"] for p in retrato["por_processo"]}, {f["numero"] for f in fs})

    def test_arquivo_invalido_e_listado_sem_derrubar_os_outros(self):
        lixo = self.pasta / "lixo.xlsx"
        lixo.write_bytes(b"isto nao e uma planilha")
        c1 = next(iter(self.por_cliente.values()))
        bom = escrever_docx_a(c1, self.pasta / "bom.docx", ficha.obter(c1[0], "cliente"), "2026-09-18")
        r = fluxos.migrar([lixo, bom], nome="Misto")
        self.assertTrue(r["ok"])
        self.assertEqual([x["arquivo"] for x in r["rejeitados"]], ["lixo.xlsx"])
        sozinho = fluxos.migrar([lixo])
        self.assertFalse(sozinho["ok"])


# ------------------------------------------------------------------ converter (migrar de modelo)

class Converter(Base):
    N, CLIENTES = 20, 2

    def setUp(self):
        shutil.rmtree(TMP / "projetos-de-teste", ignore_errors=True)
        self.proj = ficticio.criar_projeto_de_teste([], nome="Projeto Existente")
        self.addCleanup(ficticio.restaurar_comum)
        self.pasta = TMP / f"converter-{self._testMethodName}"
        shutil.rmtree(self.pasta, ignore_errors=True)
        self.pasta.mkdir(parents=True)
        self.carteira = ficticio.gerar_carteira(self.N, clientes=self.CLIENTES, semente=6, com_linha_de_base=True)

    def _tabela_fora_do_padrao(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Nº do Processo", "Parte autora", "Parte ré", "Juízo", "Valor da causa (R$)", "Anotações da equipe"])
        for f in self.carteira:
            ws.append([f["numero"], ficha.obter(f, "autores"), ficha.obter(f, "reus"), ficha.obter(f, "vara"),
                       float(dec(ficha.obter(f, "valor_causa"))), f"anotação interna sobre {f['numero'][:7]}"])
        caminho = self.pasta / "controle-do-escritorio.xlsx"
        wb.save(caminho)
        return caminho

    def test_xlsx_fora_do_padrao_vira_modelo_b_com_aba_de_campos_nao_migrados(self):
        import openpyxl
        r = fluxos.converter(self._tabela_fora_do_padrao(), "xlsx_b", nome="Convertido B", data_base="2026-09-30")
        self.assertTrue(r["ok"], r["resumo"])
        xlsx = next(Path(a) for a in r["arquivos"] if str(a).endswith(".xlsx"))
        wb = openpyxl.load_workbook(xlsx, data_only=True)
        ws = wb["Processos"]
        cab = [c.value for c in ws[1]]
        numeros = {row[cab.index("Número do Processo")] for row in ws.iter_rows(min_row=2, values_only=True) if row[0]}
        self.assertEqual(numeros, {f["numero"] for f in self.carteira})
        somas = sum(D(str(row[cab.index("Valor da Causa")] or 0)) for row in ws.iter_rows(min_row=2, values_only=True) if row[0])
        self.assertEqual(somas.quantize(D("0.01")), sum((dec(ficha.obter(f, "valor_causa")) for f in self.carteira), D(0)))
        # nada se perde em silêncio: a coluna sem destino está na aba "Campos não migrados" e no csv
        self.assertEqual([c["coluna"] for c in r["campos_nao_migrados"]], ["Anotações da equipe"])
        aba = [[c for c in linha] for linha in wb["Campos não migrados"].iter_rows(values_only=True)]
        achatado = " ".join(str(c) for linha in aba for c in linha if c)
        self.assertIn("Anotações da equipe", achatado)
        self.assertTrue(any(str(a).endswith("Campos não migrados.csv") for a in r["arquivos"]))
        self.assertIn("Anotações da equipe", next(Path(a) for a in r["arquivos"] if str(a).endswith(".csv")).read_text(encoding="utf-8-sig"))

    def test_docx_para_b_e_b_para_a(self):
        import docx
        import openpyxl
        cliente = ficha.obter(self.carteira[0], "cliente")
        so_um = [f for f in self.carteira if ficha.obter(f, "cliente") == cliente]
        origem = escrever_docx_a(so_um, self.pasta / "origem.docx", cliente, "2026-09-18")
        r1 = fluxos.converter(origem, "xlsx_b", nome="Do A para o B")
        self.assertTrue(r1["ok"], r1["resumo"])
        xlsx = next(Path(a) for a in r1["arquivos"] if str(a).endswith(".xlsx"))
        ws = openpyxl.load_workbook(xlsx, data_only=True)["Processos"]
        cab = [c.value for c in ws[1]]
        # no modelo B os vinculados vão na mesma célula do principal ("principal; vinculado; ...")
        achados = {row[cab.index("Número do Processo")].split(";")[0].strip() for row in ws.iter_rows(min_row=2, values_only=True) if row[0]}
        self.assertEqual(achados, {f["numero"] for f in so_um})
        textos = {row[cab.index("Número do Processo")].split(";")[0].strip(): row[cab.index("Andamentos")]
                  for row in ws.iter_rows(min_row=2, values_only=True) if row[0]}
        for f in so_um:                                              # o histórico do texto foi para a planilha
            self.assertTrue(textos[f["numero"]], f["numero"])
        r2 = fluxos.converter(xlsx, "docx_a", nome="Do B para o A", estilo_texto="b")
        self.assertTrue(r2["ok"], r2["resumo"])
        saida = next(Path(a) for a in r2["arquivos"] if str(a).endswith(".docx"))
        doc = docx.Document(saida)
        titulos = " ".join(t.rows[0].cells[0].text for t in doc.tables)
        for f in so_um:
            self.assertIn(f["numero"], titulos)
        # o original nunca é alterado
        self.assertTrue(origem.exists())

    def test_modelo_de_destino_invalido(self):
        r = fluxos.converter(self._tabela_fora_do_padrao(), "pdf")
        self.assertFalse(r["ok"])
        self.assertIn("modelo_de_destino", {a["codigo"] for a in r["avisos"]})

if __name__ == "__main__":
    unittest.main()
