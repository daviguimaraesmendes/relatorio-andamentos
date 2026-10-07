"""Gerador de dashboards (WS-8): `escritores/dashboard.py` + `modelos/dashboard/`.

Duas camadas:
  1. sem navegador: avisos estruturados, HTML sem referência externa, bibliotecas embutidas, arquivos de modelo
     sem número de processo;
  2. com Playwright/Chromium (pulados se não houver): abre os DOIS modos sem rede (qualquer requisição externa
     é bloqueada e reprovada), confere KPIs e contagens contra um cálculo INDEPENDENTE em Python sobre as 200
     fichas fictícias, confere que o mesmo .xlsx dá os mesmos números nos dois modos, as regras de integridade
     da economia, a aba de qualidade (defeitos das fixtures), filtros, tema escuro, impressão e celular.

    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 -m unittest tests/test_dashboard.py -v

Tudo fictício: a planilha de teste é montada aqui (openpyxl) a partir de `ficticio.gerar_carteira`; números de
processo são calculados em tempo de execução.
"""
import datetime
import json
import math
import os
import re
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import ficticio  # noqa: E402
import ficha  # noqa: E402
import carteira  # noqa: E402
import simulado  # noqa: E402

from escritores import dashboard  # noqa: E402  (pacote de espaço de nomes: src/escritores)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
try:
    from playwright.sync_api import sync_playwright
    _PW = True
except ImportError:  # pragma: no cover
    _PW = False

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = RAIZ / "src" / "modelos" / "dashboard"
DB = simulado.HOJE            # data de referência das fixtures
TMP = Path(tempfile.mkdtemp(prefix="dash-", dir=str(isolamento.TMP)))
D = Decimal


# ------------------------------------------------------------------ planilha fictícia (modelo B simplificado)

def _cabecalhos():
    return ["Número do Processo", "Tribunal", "Ativo", *[c[0] for c in ficha.CAMPOS.values()], "Andamentos"]


def escrever_xlsx(caminho, fichas, com_total=True, historico=True, grupo=None, extras=()):
    """.xlsx fictício: título e linha em branco acima do cabeçalho, aba Parâmetros, aba Histórico e linhas-marcador no
    fim (total e contador de rodapé). Parte dos valores sai como TEXTO brasileiro (R$ 1.234,56 e DD/MM/AAAA)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Processos"
    ws["A1"] = "Acompanhamento processual (fictício)"
    cab = _cabecalhos()
    for j, c in enumerate(cab, 1):
        ws.cell(row=3, column=j, value=c)
    tipos = {c[0]: c[2] for c in ficha.CAMPOS.values()}
    nome_do_campo = {c[0]: n for n, c in ficha.CAMPOS.items()}
    linha = 4
    for i, f in enumerate(fichas):
        ws.cell(row=linha, column=1, value=f["numero"])
        m = carteira.CNJ.fullmatch(f["numero"])
        ws.cell(row=linha, column=2, value=carteira.tribunal(m.groups()) if m else "")
        if i % 2 == 0:  # metade das linhas traz a coluna Ativo; nas outras o painel deduz do momento atual
            ws.cell(row=linha, column=3, value="Sim" if f["ativo"] else "Não")
        for j, c in enumerate(cab[3:-1], 4):
            v = ficha.obter(f, nome_do_campo[c])
            if v in (None, ""):
                continue
            t = tipos[c]
            if t == "dinheiro":
                v = dashboard_texto_dinheiro(v) if i % 7 == 3 else float(D(v))
            elif t == "data":
                d = datetime.date.fromisoformat(v)
                v = d.strftime("%d/%m/%Y") if i % 5 == 2 else datetime.datetime(d.year, d.month, d.day)
            ws.cell(row=linha, column=j, value=v)
        ws.cell(row=linha, column=len(cab), value=ficticio.gerar_historico(f))
        linha += 1
    for dados in extras:   # linhas montadas à mão: {cabeçalho: valor}
        for j, c in enumerate(cab, 1):
            if c in dados:
                ws.cell(row=linha, column=j, value=dados[c])
        linha += 1
    if com_total:
        ws.cell(row=linha, column=1, value=f"TOTAL: {len(fichas)}")
        ws.cell(row=linha + 1, column=1, value=23)
        ws.cell(row=linha + 1, column=2, value="NÃO ALTERAR ESSA LINHA")
    for j in range(1, len(cab) + 1):
        ws.cell(row=3, column=j).font = Font(bold=True)
    p = wb.create_sheet("Parâmetros")
    p["A1"] = "Parâmetros"
    p["A3"] = "Data de referência"
    p["B3"] = datetime.datetime.fromisoformat(DB)
    p["A4"] = "Empresas do grupo"
    p["B4"] = "\n".join(grupo or [])
    if historico:
        h = wb.create_sheet("Histórico")
        h.append(["Data-base", "Total de processos", "Processos ativos", "Processos encerrados", "Valor da causa", "Valor estimado", "Valor economizado"])
        for k, (d, tot, at, valor) in enumerate([("2026-07-07", 150, 90, 1.5e6), ("2026-08-07", 170, 98, 1.7e6), ("2026-09-07", 190, 104, 1.9e6)]):
            h.append([datetime.datetime.fromisoformat(d), tot, at, tot - at, valor, valor * 0.6, valor * 0.1])
    wb.save(caminho)
    return caminho


def dashboard_texto_dinheiro(v):
    inteiro, frac = f"{D(v):.2f}".split(".")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    return f"R$ {'.'.join(grupos)},{frac}"


# ------------------------------------------------------------------ cálculo independente (sobre as fichas, não sobre a planilha)

CLASSE = {"Procedente": "procedente", "Parcialmente procedente": "parcial", "Improcedente": "improcedente", "Acordo": "acordo",
          "Extinto sem resolução de mérito": "extinto", "Arquivado / desistência": "arquivado", "Incompetência declarada": "incompetencia"}


def _g(f, campo):
    return ficha.obter(f, campo)


def _dec(f, campo):
    v = _g(f, campo)
    return D(v) if v not in (None, "") else None


def _arredonda(x):  # Math.round do JavaScript (meio para cima)
    return int(math.floor(x + 0.5))


def economia_de(f):
    """(valor | None, motivo_fora | None) pelas regras do PLANO 7.2 e da especificação do WS-8."""
    if f["ativo"]:
        return None, None
    if _g(f, "polo_cliente") == "ativo":
        return None, "polo_ativo"
    acordo = _g(f, "resultado") == "Acordo"
    va, ve = _dec(f, "valor_acordo"), _dec(f, "valor_estimado")
    estimado = ve if ve is not None else (va if acordo else None)
    if acordo and not (va and va > 0) and not (estimado and estimado > 0):
        return None, "acordo_sem_valor"
    eco = _dec(f, "valor_economizado")
    if eco is not None:
        return eco, None
    causa = _dec(f, "valor_causa")
    if causa is not None and estimado is not None:
        return causa - estimado, None
    return None, "sem_valor"


def esperado(fichas, db=DB):
    ativos = [f for f in fichas if f["ativo"]]
    enc = [f for f in fichas if not f["ativo"]]
    soma = lambda xs: sum(xs, D(0))
    passivos = [f for f in ativos if _g(f, "polo_cliente") != "ativo"]

    def expo(f):
        for c in ("valor_estimado", "valor_arbitrado", "valor_execucao", "valor_causa"):
            if _dec(f, c) is not None:
                return _dec(f, c)
        return None
    com_valor = [f for f in passivos if (expo(f) or 0) > 0]
    prob = {"Provável": D(0), "Possível": D(0), "Remota": D(0), "semProb": D(0)}
    for f in com_valor:
        prob[_g(f, "probabilidade") or "semProb"] += expo(f)
    classes = {k: 0 for k in ("procedente", "parcial", "improcedente", "acordo", "extinto", "arquivado", "incompetencia", "exclusao", "outro")}
    for f in fichas:
        if _g(f, "resultado"):
            classes[CLASSE[_g(f, "resultado")]] += 1
    fora = {"polo_ativo": 0, "exclusao_lide": 0, "acordo_terceiro": 0, "acordo_sem_valor": 0, "sem_valor": 0}
    elegiveis = []
    for f in enc:
        valor, motivo = economia_de(f)
        if motivo:
            fora[motivo] += 1
        elif valor is not None:
            elegiveis.append(valor)
    corte = datetime.date.fromisoformat(db).replace(year=datetime.date.fromisoformat(db).year - 1).isoformat()
    entradas = sum(1 for f in fichas if _g(f, "data_ajuizamento") and corte <= _g(f, "data_ajuizamento") <= db)

    def enc_data(f):
        return _g(f, "data_transito") or _g(f, "ultimo_andamento")
    baixas = sum(1 for f in enc if enc_data(f) and corte <= enc_data(f) <= db)
    tempos = []
    for f in enc:
        t = _g(f, "taxa_resolucao_dias")
        if t and float(t) > 0:
            tempos.append(float(t))
        elif enc_data(f) and _g(f, "data_ajuizamento"):
            tempos.append(max((datetime.date.fromisoformat(enc_data(f)) - datetime.date.fromisoformat(_g(f, "data_ajuizamento"))).days, 0))
    dias = sorted(max((datetime.date.fromisoformat(db) - datetime.date.fromisoformat(_g(f, "ultimo_andamento"))).days, 0)
                  for f in ativos if _g(f, "ultimo_andamento"))
    n = len(dias)
    faixas = {"até 15 dias": 0, "16 a 30 dias": 0, "31 a 60 dias": 0, "61 a 90 dias": 0, "mais de 90 dias": 0, "sem data": len(ativos) - n}
    for d in dias:
        faixas["até 15 dias" if d <= 15 else "16 a 30 dias" if d <= 30 else "31 a 60 dias" if d <= 60 else "61 a 90 dias" if d <= 90 else "mais de 90 dias"] += 1
    return {
        "total": len(fichas), "ativos": len(ativos), "encerrados": len(enc),
        "valorCausaAtivos": float(soma(_dec(f, "valor_causa") or D(0) for f in ativos)),
        "exposicao": float(soma(expo(f) for f in com_valor)), "exposicaoProb": {k: float(v) for k, v in prob.items()},
        "poloAtivoAtivos": len(ativos) - len(passivos), "comResultado": sum(classes.values()), "resultadoClasses": classes,
        "economia": {"valor": float(soma(elegiveis)), "elegiveis": len(elegiveis), "fora": fora},
        "entradas12": entradas, "baixas12": baixas, "saldo12": entradas - baixas,
        "tempoMedioDias": _arredonda(sum(tempos) / len(tempos)) if tempos else None,
        "semAndamento30": sum(1 for d in dias if d > 30), "semAndamento60": sum(1 for d in dias if d > 60), "semAndamento90": sum(1 for d in dias if d > 90),
        "medianaDias": (dias[n // 2] if n % 2 else (dias[n // 2 - 1] + dias[n // 2]) / 2) if n else None, "faixas": faixas,
    }


# ------------------------------------------------------------------ navegador

class _Pagina:
    """Página aberta no Chromium, sem rede: toda requisição que não seja do arquivo local é bloqueada e anotada."""
    def __init__(self, navegador, **kw):
        self.ctx = navegador.new_context(**kw)
        self.externas, self.erros_js, self.erros_console = [], [], []
        self.ctx.route("**/*", self._rota)
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda e: self.erros_js.append(str(e)))
        self.page.on("console", lambda m: self.erros_console.append(m.text) if m.type == "error" else None)

    def _rota(self, rota):
        url = rota.request.url
        if url.startswith(("file:", "data:", "blob:", "about:")):
            rota.continue_()
        else:
            self.externas.append(url)
            rota.abort()

    def abrir(self, html, xlsx=None):
        self.page.goto(Path(html).resolve().as_uri())
        if xlsx is not None:
            self.page.set_input_files("#arquivo", str(xlsx))
        self.page.wait_for_function("document.documentElement.dataset.pronto === '1'", timeout=60000)
        return self

    def ind(self):
        return self.page.evaluate("JSON.parse(JSON.stringify(DASH.estado.ind))")

    def kpis(self):
        return self.page.evaluate("Object.fromEntries([...document.querySelectorAll('[data-kpi]')].map(e => [e.dataset.kpi, e.dataset.valor == null ? null : Number(e.dataset.valor)]))")

    def kpi_textos(self):
        return self.page.evaluate("Object.fromEntries([...document.querySelectorAll('[data-kpi]')].map(e => [e.dataset.kpi, e.querySelector('.valor').textContent]))")

    def fechar(self):
        self.ctx.close()


def _perto(teste, real, esperado_, caminho=""):
    if isinstance(esperado_, dict):
        teste.assertEqual(set(real) >= set(esperado_), True, f"{caminho}: faltam chaves {set(esperado_) - set(real)}")
        for k, v in esperado_.items():
            _perto(teste, real[k], v, f"{caminho}.{k}")
    elif isinstance(esperado_, float) or isinstance(real, float):
        teste.assertIsNotNone(real, caminho)
        teste.assertAlmostEqual(real, esperado_, delta=0.006, msg=caminho)
    else:
        teste.assertEqual(real, esperado_, caminho)


# ------------------------------------------------------------------ 1. sem navegador

class TestGeracao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = ficticio.gerar_carteira(30, clientes=2, semente=3)
        cls.xlsx = escrever_xlsx(TMP / "pequena.xlsx", cls.fichas)
        cls.perfil = {"parametros": {"headcount": None, "empresas_do_grupo": ["Cliente Exemplo 01"]}}

    def _gravar(self, nome, **op):
        r = dashboard.gravar(self.xlsx, TMP / nome, self.perfil, **op)
        self.assertIsNotNone(r["destino"], r["avisos"])
        return r, Path(r["destino"]).read_text(encoding="utf-8")

    def test_resultado_segue_o_contrato(self):
        r, _ = self._gravar("a.html", modo="embutido")
        for chave in ("destino", "processos_atualizados", "processos_novos", "ignorados", "mudancas", "avisos", "textos_gravados"):
            self.assertIn(chave, r)
        self.assertEqual(r["processos_no_painel"], 30)
        self.assertEqual(r["template"], "contencioso")     # perfil com empresas do grupo
        self.assertTrue(Path(r["destino"]).read_bytes().startswith(b"<!doctype html>"))

    def test_template_padrao_sem_grupo_e_carteira(self):
        r = dashboard.gravar(self.xlsx, TMP / "b.html", {"parametros": {}})
        self.assertEqual(r["template"], "carteira")

    def test_html_nao_tem_referencia_externa(self):
        for modo in ("modelo", "embutido"):
            for template in ("contencioso", "carteira"):
                _, html = self._gravar(f"c-{modo}-{template}.html", modo=modo, template=template)
                sem_bibliotecas = re.sub(r"<script data-biblioteca=.*?</script>", "", html, flags=re.S)
                self.assertNotRegex(sem_bibliotecas, r"https?://|//cdn|\bsrc\s*=|<link\b|@import|url\(\s*['\"]?https?:", f"{modo}/{template}")
                self.assertNotIn("fonts.googleapis", html)
                self.assertNotIn("fonts.gstatic", html)
                self.assertEqual(html.count("data-biblioteca="), 1 if modo == "embutido" else 2)

    def test_bibliotecas_embutidas_sao_as_registradas(self):
        _, html = self._gravar("d.html", modo="modelo")
        for _, (nome, versao, sha) in dashboard.BIBLIOTECAS.items():
            self.assertIn((MODELOS / nome).read_text(encoding="utf-8")[:2000], html)
            self.assertIn(f'data-biblioteca="{versao}"', html)
            self.assertIn(sha, (MODELOS / "BIBLIOTECAS.md").read_text(encoding="utf-8"))
        self.assertEqual(dashboard.verificar_bibliotecas(), [])

    def test_biblioteca_ausente_ou_adulterada_vira_aviso(self):
        pasta = TMP / "sem-bibliotecas"
        pasta.mkdir(exist_ok=True)
        avisos = dashboard.verificar_bibliotecas(pasta)
        self.assertEqual({a["codigo"] for a in avisos}, {"bibliotecas_ausentes"})
        (pasta / "chart.umd.min.js").write_text("alterado")
        avisos = dashboard.verificar_bibliotecas(pasta, so=("chart",))
        self.assertEqual([a["codigo"] for a in avisos], ["biblioteca_diferente"])

    def test_embutido_nao_leva_o_texto_dos_andamentos(self):
        _, html = self._gravar("e.html", modo="embutido")
        texto = ficticio.gerar_historico(self.fichas[0])
        self.assertIn(texto[:40], self._gravar("e2.html", modo="embutido", incluir_andamentos=True)[1])
        self.assertNotIn(texto[:40], html)
        r = dashboard.gravar(self.xlsx, TMP / "e3.html", self.perfil, modo="embutido")
        self.assertIn("andamentos_minimizados", [a["codigo"] for a in r["avisos"]])

    def test_erros_esperados_viram_avisos_sem_arquivo(self):
        casos = {
            "destino_igual_origem": dict(xlsx=self.xlsx, destino=self.xlsx, op={}),
            "modo_invalido": dict(xlsx=self.xlsx, destino=TMP / "x.html", op={"modo": "nuvem"}),
            "template_invalido": dict(xlsx=self.xlsx, destino=TMP / "x.html", op={"template": "inexistente"}),
            "planilha_inexistente": dict(xlsx=TMP / "nao-existe.xlsx", destino=TMP / "x.html", op={"modo": "embutido"}),
        }
        for codigo, c in casos.items():
            r = dashboard.gravar(c["xlsx"], c["destino"], self.perfil, **c["op"])
            self.assertIsNone(r["destino"], codigo)
            self.assertIn(codigo, [a["codigo"] for a in r["avisos"]])
            self.assertEqual({"nivel", "codigo", "onde", "mensagem", "candidatos"}, set(r["avisos"][0]))
        lixo = TMP / "lixo.xlsx"
        lixo.write_text("isto não é uma planilha")
        r = dashboard.gravar(lixo, TMP / "x.html", self.perfil, modo="embutido")
        self.assertIsNone(r["destino"])
        self.assertIn("planilha_ilegivel", [a["codigo"] for a in r["avisos"]])
        self.assertTrue(self.xlsx.exists())   # o original nunca é tocado

    def test_modelo_aceita_xlsx_nulo_e_data_invalida_avisa(self):
        r = dashboard.gravar(None, TMP / "f.html", self.perfil, data_base="31/02/2026")
        self.assertIsNotNone(r["destino"])
        self.assertIn("data_base_invalida", [a["codigo"] for a in r["avisos"]])

    def test_config_nao_quebra_o_script_com_texto_hostil(self):
        r = dashboard.gravar(None, TMP / "g.html", self.perfil, titulo="</script><script>alert(1)</script>",
                             cliente="Cliente </script> & <!-- x", empresas_do_grupo=["A </script> B"])
        html = Path(r["destino"]).read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", html)
        cfg = re.search(r'<script type="application/json" id="cfg">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(json.loads(cfg)["empresas_do_grupo"], ["A </script> B"])

    def test_retratos_mensais_entram_na_config_e_invalido_avisa(self):
        retratos = [{"data_base": "2026-08-07", "totais": {"processos": 10, "ativos": 6, "encerrados": 4, "valor_causa": "100.00"}}, {"sem": "data"}]
        r = dashboard.gravar(None, TMP / "h.html", self.perfil, historico=retratos)
        self.assertIn("retrato_invalido", [a["codigo"] for a in r["avisos"]])
        cfg = re.search(r'<script type="application/json" id="cfg">(.*?)</script>', Path(r["destino"]).read_text(encoding="utf-8"), re.S).group(1)
        self.assertEqual([x["data_base"] for x in json.loads(cfg)["historico"]], ["2026-08-07"])

    def test_arquivos_do_modelo_sem_numero_de_processo(self):
        cnj = re.compile(r"\b[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}\b")
        permitidos = re.compile(r"0000000-00\.0000\.0\.00\.0000|9999999-99\.9999\.9\.99\.9999|123456[7-9]-|1234570-")
        for arq in [*MODELOS.glob("*"), RAIZ / "src" / "escritores" / "dashboard.py"]:
            if arq.suffix in (".js", ".css", ".html", ".md", ".py"):
                for m in cnj.finditer(arq.read_text(encoding="utf-8")):
                    self.assertTrue(permitidos.search(m.group(0)), f"{arq.name}: {m.group(0)}")


# ------------------------------------------------------------------ 2. com navegador

@unittest.skipUnless(_PW, "Playwright não instalado")
class TestNavegador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.navegador = cls.pw.chromium.launch()
        except Exception as e:  # Chromium ausente
            cls.pw.stop()
            raise unittest.SkipTest(f"Chromium indisponível: {e}")
        cls.fichas = ficticio.gerar_carteira(200, clientes=5, semente=1)
        cls.grupo = ["Cliente Exemplo 01", "Cliente Exemplo 02"]
        cls.xlsx = escrever_xlsx(TMP / "carteira200.xlsx", cls.fichas, grupo=cls.grupo)
        cls.perfil = {"parametros": {"headcount": None, "empresas_do_grupo": cls.grupo}}
        cls.esperado = esperado(cls.fichas)
        cls.html = {}
        for template in ("contencioso", "carteira"):
            for modo in ("modelo", "embutido"):
                r = dashboard.gravar(cls.xlsx, TMP / f"p-{template}-{modo}.html", cls.perfil, modo=modo, template=template, data_base=DB)
                assert r["destino"], r["avisos"]
                cls.html[(template, modo)] = r["destino"]
        cls.abertas = []

    @classmethod
    def tearDownClass(cls):
        cls.navegador.close()
        cls.pw.stop()

    def abrir(self, template, modo, **kw):
        p = _Pagina(self.navegador, **kw)
        self.abertas.append(p)
        return p.abrir(self.html[(template, modo)], self.xlsx if modo == "modelo" else None)

    def tearDown(self):
        for p in self.abertas:
            self.assertEqual(p.externas, [], f"requisição externa: {p.externas}")
            self.assertEqual(p.erros_js, [], p.erros_js)
            p.fechar()
        self.abertas.clear()

    # ---- números

    def test_contencioso_confere_com_calculo_independente_nos_dois_modos(self):
        resultados = {}
        for modo in ("modelo", "embutido"):
            p = self.abrir("contencioso", modo)
            ind = p.ind()
            _perto(self, ind, self.esperado, modo)
            resultados[modo] = (ind, p.kpis(), p.kpi_textos())
        self.assertEqual(resultados["modelo"][0], resultados["embutido"][0])           # mesmo .xlsx, mesmos números
        self.assertEqual(resultados["modelo"][1], resultados["embutido"][1])
        self.assertEqual(resultados["modelo"][2], resultados["embutido"][2])           # e o mesmo texto nos cartões

    def test_cartoes_mostram_os_numeros_do_calculo_independente(self):
        p = self.abrir("contencioso", "embutido")
        k, e = p.kpis(), self.esperado
        self.assertEqual(k["total"], e["total"])
        self.assertEqual((k["ativos"], k["encerrados"]), (e["ativos"], e["encerrados"]))
        self.assertAlmostEqual(k["valor_causa_ativos"], e["valorCausaAtivos"], delta=0.006)
        self.assertAlmostEqual(k["exposicao"], e["exposicao"], delta=0.006)
        self.assertAlmostEqual(k["exposicao_provavel"], e["exposicaoProb"]["Provável"], delta=0.006)
        self.assertAlmostEqual(k["economia"], e["economia"]["valor"], delta=0.006)
        self.assertEqual(k["acordo"], e["resultadoClasses"]["acordo"])
        self.assertEqual(k["saldo12"], e["saldo12"])
        self.assertEqual(k["tempo_medio"], e["tempoMedioDias"])

    def test_carteira_confere_com_calculo_independente_nos_dois_modos(self):
        saidas = []
        for modo in ("modelo", "embutido"):
            p = self.abrir("carteira", modo)
            ind = p.ind()
            _perto(self, ind, {k: self.esperado[k] for k in ("total", "ativos", "encerrados", "semAndamento30", "semAndamento60", "semAndamento90", "medianaDias", "faixas")}, modo)
            k = p.kpis()
            self.assertEqual((k["sem_andamento_30"], k["sem_andamento_90"]), (self.esperado["semAndamento30"], self.esperado["semAndamento90"]))
            saidas.append(ind)
        self.assertEqual(saidas[0], saidas[1])

    def test_contagens_dos_graficos_somam_o_que_os_cartoes_dizem(self):
        p = self.abrir("contencioso", "embutido")
        soma = lambda id_: p.page.evaluate(f"Chart.getChart('ch-{id_}').data.datasets.reduce((s, d) => s + d.data.reduce((a, b) => a + b, 0), 0)")
        self.assertEqual(soma("fase"), self.esperado["ativos"])
        self.assertLessEqual(soma("momento"), self.esperado["ativos"])   # só os 10 momentos mais frequentes
        self.assertEqual(soma("tribunal") <= 200, True)
        self.assertEqual(soma("resultado"), self.esperado["comResultado"])

    def test_rankings_de_materia_ignoram_as_acessorias_e_genericas(self):
        p = self.abrir("contencioso", "embutido")
        rotulos = p.page.evaluate("[...Chart.getChart('ch-pareto').data.labels, ...Chart.getChart('ch-defesa').data.labels]")
        self.assertGreater(len(rotulos), 3)
        self.assertNotIn("Outros", rotulos)
        n_outros = sum(1 for f in self.fichas if _g(f, "materia_principal") == "Outros")
        self.assertGreater(n_outros, 0)       # existem na carteira, só não entram no ranking

    def test_um_processo_nunca_e_contado_duas_vezes(self):
        p = self.abrir("contencioso", "embutido")
        numeros = p.page.evaluate("DASH.estado.unicos.map(r => r.chave)")
        self.assertEqual(len(numeros), len(set(numeros)))
        self.assertEqual(p.page.evaluate("document.querySelectorAll('#t-corpo tr').length"), 50)  # primeira página

    # ---- integridade da economia (casos montados à mão)

    def test_economia_deixa_de_fora_e_sinaliza_os_casos_que_inflam(self):
        base = ficticio.gerar_carteira(4, clientes=1, semente=9)
        n = lambda i: ficticio.numero_ficticio(900 + i)
        causa = 100000.0
        def caso(i, res, momento="ACORDO HOMOLOGADO", **kw):
            d = {"Número do Processo": n(i), "Tribunal": "TJCE", "Ativo": "Não", "Valor da causa": causa, "Momento atual do processo": momento,
                 "Resultado": res, "Polo do cliente": "passivo", "Área do direito": "Cível", "Matéria principal": "Dano moral"}
            d.update(kw)
            return d
        extras = [
            caso(1, "Acordo", **{"Valor estimado": 30000.0, "Valor do acordo": 30000.0}),                                # conta: 70 000
            caso(2, "Acordo"),                                                                                          # acordo sem valor
            caso(3, "Acordo", **{"Valor do acordo": 20000.0, "Observações": "Acordo pago por terceiro (seguradora)."}),   # terceiro
            caso(4, "Procedente", momento="TRÂNSITO EM JULGADO", **{"Valor estimado": 40000.0, "Observações": "Cliente excluído da lide."}),  # exclusão da lide
            caso(5, "Improcedente", momento="TRÂNSITO EM JULGADO", **{"Valor estimado": 0.0}),                           # conta: 100 000
            caso(6, "Improcedente", momento="TRÂNSITO EM JULGADO", **{"Polo do cliente": "ativo", "Valor estimado": 0.0}),  # polo ativo
            caso(7, "Procedente", momento="TRÂNSITO EM JULGADO"),                                                       # sem valor lançado
            caso(8, "Improcedente", momento="TRÂNSITO EM JULGADO", **{"Valor estimado": 0.0, "Valor economizado": 99000.0}),  # coluna manda: 99 000
            caso(9, None, momento="AGUARDANDO SENTENÇA", Ativo="Sim", **{"Valor estimado": 50000.0}),                    # ativo: sem economia
        ]
        arq = escrever_xlsx(TMP / "economia.xlsx", [], extras=extras, historico=False)
        html = dashboard.gravar(arq, TMP / "economia.html", self.perfil, modo="embutido", template="contencioso", data_base=DB)["destino"]
        p = _Pagina(self.navegador)
        self.abertas.append(p)
        p.abrir(html)
        e = p.ind()["economia"]
        self.assertEqual(e["fora"], {"polo_ativo": 1, "exclusao_lide": 1, "acordo_terceiro": 1, "acordo_sem_valor": 1, "sem_valor": 1})
        self.assertEqual(e["elegiveis"], 3)
        self.assertAlmostEqual(e["valor"], 70000 + 100000 + 99000, delta=0.006)
        self.assertEqual(p.ind()["total"], 9)
        nota = p.page.inner_text("#nota-economia")
        self.assertIn("fora do indicador", nota)
        q = {x["id"]: x["n"] for x in p.page.evaluate("DASH.estado.qualidade")}
        self.assertEqual((q["fora_acordo_terceiro"], q["fora_exclusao_lide"], q["fora_acordo_sem_valor"], q["fora_polo_ativo"]), (1, 1, 1, 1))
        # a tabela sinaliza cada caso (e o botão do painel não conta o que ficou de fora)
        self.assertEqual(p.page.locator("#t-corpo .etq.fora").count(), 5)

    def test_vinculados_e_numeros_com_mascara_diferente_contam_uma_vez(self):
        a, b, c = (ficticio.numero_ficticio(950 + i) for i in range(3))
        sem_mascara = re.sub(r"\D", "", a)
        extras = [
            {"Número do Processo": f"{a}\n{b} (agravo)", "Tribunal": "TJCE", "Valor da causa": 1000.0, "Momento atual do processo": "AGUARDANDO SENTENÇA", "Área do direito": "Cível"},
            {"Número do Processo": b, "Tribunal": "TJCE", "Valor da causa": 500.0, "Momento atual do processo": "AGUARDANDO SENTENÇA", "Área do direito": "Cível"},
            {"Número do Processo": sem_mascara, "Tribunal": "TJCE", "Valor da causa": 1000.0, "Momento atual do processo": "AGUARDANDO SENTENÇA", "Área do direito": "Cível"},
            {"Número do Processo": c, "Tribunal": "TJCE", "Valor da causa": 2000.0, "Momento atual do processo": "AGUARDANDO SENTENÇA", "Área do direito": "Cível"},
        ]
        arq = escrever_xlsx(TMP / "vinculados.xlsx", [], extras=extras, historico=False)
        html = dashboard.gravar(arq, TMP / "vinculados.html", self.perfil, modo="embutido", data_base=DB, template="carteira")["destino"]
        p = _Pagina(self.navegador)
        self.abertas.append(p)
        p.abrir(html)
        self.assertEqual(p.ind()["total"], 2)        # a+b+duplicata de a = um processo; c = outro
        q = {x["id"]: x["n"] for x in p.page.evaluate("DASH.estado.qualidade")}
        self.assertEqual((q["duplicados"], q["vinculados"]), (1, 1))

    # ---- qualidade dos dados (defeitos das fixtures)

    def test_aba_qualidade_acha_os_defeitos_das_fixtures(self):
        sujas = ficticio.gerar_carteira(200, clientes=5, semente=1, com_defeitos=True)
        d = sujas.defeitos
        arq = escrever_xlsx(TMP / "suja.xlsx", sujas, grupo=self.grupo)
        html = dashboard.gravar(arq, TMP / "suja.html", self.perfil, modo="embutido", template="contencioso", data_base=DB)["destino"]
        p = _Pagina(self.navegador)
        self.abertas.append(p)
        p.abrir(html)
        q = {x["id"]: x for x in p.page.evaluate("DASH.estado.qualidade")}
        self.assertEqual(q["duplicados"]["n"], len(d["numero_duplicado"]))
        self.assertEqual(q["dv"]["n"], len(d["dv_errado"]))
        por_numero = {f["numero"]: f for f in sujas}
        # com o cliente no polo ativo o caso sai do indicador pelo motivo "polo ativo" (que vem primeiro)
        self.assertEqual(q["fora_acordo_sem_valor"]["n"], sum(1 for n in d["acordo_sem_valor"] if _g(por_numero[n], "polo_cliente") != "ativo"))
        self.assertEqual(q["enc_sem_res"]["n"], len(d["encerrado_sem_resultado"]))
        self.assertEqual(q["conflito"]["n"], len(d["ativo_em_conflito"]))
        self.assertEqual(p.ind()["total"], 200 - len(d["numero_duplicado"]))
        for numero in d["dv_errado"]:
            self.assertTrue(any(numero in i for i in q["dv"]["itens"]))
        p.page.click("#tab-qualidade")
        self.assertTrue(p.page.is_visible("#aba-qualidade"))
        self.assertFalse(p.page.is_visible("#aba-painel"))
        self.assertGreater(int(p.page.inner_text("#selo-qualidade")), 0)

    def test_linhas_de_total_e_rodape_sao_ignoradas_e_colunas_desconhecidas_listadas(self):
        p = self.abrir("contencioso", "embutido")
        q = {x["id"]: x for x in p.page.evaluate("DASH.estado.qualidade")}
        self.assertEqual(q["descartadas"]["n"], 2)
        self.assertEqual(p.ind()["total"], 200)

    # ---- interface

    def test_filtros_e_busca_recalculam_os_indicadores(self):
        p = self.abrir("contencioso", "embutido")
        p.page.select_option("#f-area", "Trabalhista")
        esperado_trab = [f for f in self.fichas if _g(f, "area") == "Trabalhista"]
        self.assertEqual(p.ind()["total"], len(esperado_trab))
        _perto(self, p.ind()["valorCausaAtivos"], float(sum((_dec(f, "valor_causa") or D(0) for f in esperado_trab if f["ativo"]), D(0))))
        p.page.select_option("#f-situacao", "encerrado")
        self.assertEqual(p.ind()["ativos"], 0)
        p.page.click("#b-limpar")
        self.assertEqual(p.ind()["total"], 200)
        p.page.fill("#f-busca", self.fichas[5]["numero"])
        p.page.wait_for_function("DASH.estado.ind.total === 1")
        self.assertEqual(p.page.locator("#t-corpo tr").count(), 1)

    def test_ordenar_tabela_e_paginar(self):
        p = self.abrir("contencioso", "embutido")
        p.page.click("#t-cab button[data-k=valorCausa]")
        p.page.click("#t-cab button[data-k=valorCausa]")   # decrescente
        primeira = p.page.locator("#t-corpo tr").first.locator("td").nth(6).inner_text()
        maior = max(_dec(f, "valor_causa") for f in self.fichas)
        self.assertEqual(re.sub(r"\D", "", primeira), str(int(maior)))
        self.assertEqual(p.page.get_attribute("#t-cab th:nth-child(8)", "aria-sort"), "descending")
        p.page.click("#t-prox")
        self.assertIn("Página 2", p.page.inner_text("#t-pag-info"))

    def test_serie_historica_usa_a_aba_historico_mais_o_retrato_atual(self):
        p = self.abrir("contencioso", "embutido")
        serie = p.page.evaluate("DASH.AJUDAS.serieHistorica({total: 1, ativos: 1, encerrados: 0})")
        self.assertEqual([x["data"] for x in serie], ["2026-07-07", "2026-08-07", "2026-09-07", DB])
        self.assertEqual(serie[-1]["atual"], True)
        retratos = [{"data_base": "2026-09-07", "totais": {"processos": 999, "ativos": 1, "encerrados": 998}}]
        html = dashboard.gravar(self.xlsx, TMP / "serie.html", self.perfil, modo="embutido", data_base=DB, historico=retratos)["destino"]
        p2 = _Pagina(self.navegador)
        self.abertas.append(p2)
        p2.abrir(html)
        s2 = p2.page.evaluate("DASH.AJUDAS.serieHistorica(null)")
        self.assertEqual([x["total"] for x in s2][2], 999)       # o retrato do sistema vale mais que a aba
        self.assertEqual(p2.page.evaluate("Chart.getChart('ch-serie_qtd').data.labels.length"), 4)

    def test_data_de_referencia_vem_da_planilha_quando_nao_informada(self):
        html = dashboard.gravar(self.xlsx, TMP / "semdata.html", self.perfil, modo="embutido")["destino"]
        p = _Pagina(self.navegador)
        self.abertas.append(p)
        p.abrir(html)
        self.assertEqual(p.page.evaluate("DASH.estado.dataBase"), DB)         # aba Parâmetros
        self.assertEqual(p.page.input_value("#f-data"), DB)
        p.page.fill("#f-data", "2026-06-30")
        p.page.dispatch_event("#f-data", "change")
        p.page.wait_for_function("DASH.estado.dataBase === '2026-06-30'")
        self.assertEqual(p.ind()["total"], 200)

    def test_empresas_do_grupo_da_planilha_e_do_perfil(self):
        p = self.abrir("contencioso", "embutido")
        self.assertEqual(p.page.evaluate("DASH.AJUDAS.grupo()"), ["Cliente Exemplo 01", "Cliente Exemplo 02"])  # aba Parâmetros manda (vazia aqui: vale o perfil)
        grupo_planilha = escrever_xlsx(TMP / "grupo.xlsx", self.fichas[:20], grupo=["Empresa Fictícia Alfa", "Empresa Fictícia Beta"])
        html = dashboard.gravar(grupo_planilha, TMP / "grupo.html", {"parametros": {"empresas_do_grupo": ["Outra"]}}, modo="embutido", template="contencioso", data_base=DB)["destino"]
        p2 = _Pagina(self.navegador)
        self.abertas.append(p2)
        p2.abrir(html)
        self.assertEqual(p2.page.evaluate("DASH.AJUDAS.grupo()"), ["Empresa Fictícia Alfa", "Empresa Fictícia Beta"])

    def test_csv_tambem_abre_no_modo_modelo(self):
        csv = TMP / "lista.csv"
        linhas = ["Número do Processo;Área do direito;Valor da causa;Momento atual do processo;Tribunal;Resultado"]
        for i in range(5):
            linhas.append(f"{ficticio.numero_ficticio(970 + i)};Cível;R$ {1000 + i},50;{'PROCESSO ARQUIVADO' if i % 2 else 'AGUARDANDO SENTENÇA'};TJCE;")
        csv.write_text("\n".join(linhas), encoding="utf-8")
        p = _Pagina(self.navegador)
        self.abertas.append(p)
        p.abrir(self.html[("carteira", "modelo")], csv)
        self.assertEqual((p.ind()["total"], p.ind()["ativos"]), (5, 3))
        self.assertAlmostEqual(p.ind()["valorCausaTotal"], sum(1000 + i + 0.5 for i in range(5)), delta=0.006)

    def test_arquivo_sem_processos_mostra_mensagem_clara(self):
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.append(["Nome", "Idade"])
        wb.active.append(["Fulano Fictício", 30])
        arq = TMP / "outra.xlsx"
        wb.save(arq)
        p = _Pagina(self.navegador)
        self.abertas.append(p)
        p.page.goto(Path(self.html[("contencioso", "modelo")]).resolve().as_uri())
        p.page.set_input_files("#arquivo", str(arq))
        p.page.wait_for_function("document.getElementById('msg').textContent.length > 0")
        self.assertIn("Nenhum processo reconhecido", p.page.inner_text("#msg"))
        self.assertTrue(p.page.is_visible("#carregador"))

    # ---- acessibilidade, tema, impressão, celular

    def test_acessibilidade_basica(self):
        p = self.abrir("contencioso", "embutido")
        self.assertEqual(p.page.get_attribute("html", "lang"), "pt-BR")
        self.assertEqual(p.page.locator("[role=tab]").count(), 2)
        sem_rotulo = p.page.evaluate("[...document.querySelectorAll('canvas')].filter(c => !c.getAttribute('aria-label')).length")
        self.assertEqual(sem_rotulo, 0)
        self.assertGreater(p.page.locator("details.tabela-dados").count(), 10)
        self.assertEqual(p.page.evaluate("[...document.querySelectorAll('select,input')].filter(e => !e.labels || !e.labels.length).length"), 0)
        # tabela de dados do gráfico tem cabeçalhos de linha e de coluna
        self.assertGreater(p.page.locator("#td-fase th[scope=row]").count(), 0)
        # navegação por setas entre as abas
        p.page.focus("#tab-painel")
        p.page.keyboard.press("ArrowRight")
        self.assertEqual(p.page.get_attribute("#tab-qualidade", "aria-selected"), "true")

    def test_tema_escuro_troca_as_cores_e_redesenha_sem_erro(self):
        claro = self.abrir("contencioso", "embutido", color_scheme="light")
        fundo_claro = claro.page.evaluate("getComputedStyle(document.body).backgroundColor")
        escuro = self.abrir("contencioso", "embutido", color_scheme="dark")
        fundo_escuro = escuro.page.evaluate("getComputedStyle(document.body).backgroundColor")
        self.assertNotEqual(fundo_claro, fundo_escuro)
        escuro.page.emulate_media(color_scheme="light")
        escuro.page.wait_for_function("getComputedStyle(document.body).backgroundColor !== '%s'" % fundo_escuro)
        self.assertEqual(escuro.ind()["total"], 200)

    def test_impressao_esconde_controles_e_gera_pdf(self):
        p = self.abrir("contencioso", "embutido")
        p.page.emulate_media(media="print")
        self.assertEqual(p.page.evaluate("getComputedStyle(document.getElementById('filtros')).display"), "none")
        self.assertEqual(p.page.evaluate("getComputedStyle(document.querySelector('.abas')).display"), "none")
        pdf = p.page.pdf(format="A4", landscape=True, print_background=True)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 20000)
        # antes de imprimir a tabela mostra TODAS as linhas (e volta a paginar depois)
        p.page.emulate_media(media="screen")
        p.page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
        self.assertEqual(p.page.locator("#t-corpo tr").count(), 200)
        p.page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        self.assertEqual(p.page.locator("#t-corpo tr").count(), 50)

    def test_celular_nao_tem_rolagem_horizontal(self):
        for template in ("contencioso", "carteira"):
            p = self.abrir(template, "embutido", viewport={"width": 375, "height": 800})
            largura = p.page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            self.assertLessEqual(largura[0], largura[1] + 1, template)

    def test_modelo_abre_vazio_e_embutido_abre_pronto(self):
        p = _Pagina(self.navegador)
        self.abertas.append(p)
        p.page.goto(Path(self.html[("contencioso", "modelo")]).resolve().as_uri())
        self.assertTrue(p.page.is_visible("#carregador"))
        self.assertFalse(p.page.is_visible("#app"))
        self.assertEqual(p.page.evaluate("typeof XLSX"), "object")
        e = self.abrir("contencioso", "embutido")
        self.assertFalse(e.page.is_visible("#carregador"))
        self.assertTrue(e.page.is_visible("#app"))
        self.assertEqual(e.page.evaluate("typeof XLSX"), "undefined")   # embutido não leva o SheetJS


if __name__ == "__main__":
    unittest.main()
