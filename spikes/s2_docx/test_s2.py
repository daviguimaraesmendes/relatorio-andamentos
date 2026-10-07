"""Testes do SPIKE S2 (escritor DOCX do modelo A). Só dados fictícios, sem rede.

    python3 -m unittest spikes/s2_docx/test_s2.py -v

Os testes do LibreOffice são pulados se o `soffice` não existir. NADA aqui prova que o Word ou o Google Docs
abrem os arquivos: só python-docx, lxml e LibreOffice foram usados.
"""
import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lxml import etree  # noqa: E402

import docx_atualizador as da  # noqa: E402
import gerar_modelo as gm  # noqa: E402

W = da.W_NS
w = da.w
DATA_BASE_NOVA = "07/10/2026"
SOFFICE = shutil.which("soffice")
TMP = Path(tempfile.mkdtemp(prefix="s2-docx-"))
PROCS = gm.processos()


def num(i):
    return PROCS[i]["numeros"][0]


def doc_xml(caminho):
    with zipfile.ZipFile(caminho) as z:
        return etree.fromstring(z.read("word/document.xml"))


def c14n(el):
    return etree.tostring(el, method="c14n")


def corpo(caminho):
    return doc_xml(caminho).find(w("body"))


def tabelas(caminho):
    return list(corpo(caminho).findall(w("tbl")))


def texto_el(el):
    return "".join(t.text or "" for t in el.iter(w("t")))


def runs_do_par_andamentos(caminho, i):
    """Runs do parágrafo de 'Andamentos' do processo i (tabela i+1: a 0 é o resumo)."""
    tbl = tabelas(caminho)[i + 1]
    ultima = tbl.findall(w("tr"))[-1]
    par = [p for p in ultima.findall(w("tc"))[-1].findall(w("p"))][-1]
    return par, par.findall(w("r"))


def so_digitos_e_letras(s):
    return re.sub(r"\s+", "", s)


def escrever_doc(origem, destino, fn):
    """Reescreve word/document.xml de `origem` aplicando fn(root); o resto do pacote fica igual."""
    with zipfile.ZipFile(origem) as zin, zipfile.ZipFile(destino, "w") as zout:
        for info in zin.infolist():
            dados = zin.read(info.filename)
            if info.filename == "word/document.xml":
                raiz = etree.fromstring(dados)
                fn(raiz)
                dados = etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(info, dados)


def pdf_texto(docx_path):
    """Converte com o LibreOffice e devolve o texto do PDF (sem espaços/quebras, para comparar)."""
    from pypdf import PdfReader
    saida = Path(tempfile.mkdtemp(dir=TMP))
    perfil = saida / "perfil"
    r = subprocess.run([SOFFICE, f"-env:UserInstallation=file://{perfil}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(saida), str(docx_path)], capture_output=True, text=True, timeout=240)
    pdf = saida / (Path(docx_path).stem + ".pdf")
    if not pdf.exists():
        raise AssertionError(f"soffice falhou: {r.stdout} {r.stderr}")
    leitor = PdfReader(str(pdf))
    return so_digitos_e_letras("".join(p.extract_text() for p in leitor.pages)), len(leitor.pages)


def proc_novo(numeros=None, tipos=None):
    return {"numeros": numeros or ["1234568-27.2026.8.06.0099"], "tipos": tipos or [], "assunto": "Ação de teste nova",
            "autores": "Fulana Exemplo de Tal", "reus": gm.CLIENTE, "ajuizamento": "2026-09-30", "valor_causa": "12345.60",
            "data_citacao": None, "juizo": "1ª Vara Fictícia da Comarca Modelo", "area": "Cível", "materia": "Contratos",
            "momento_atual": "aguardando citação",
            "andamentos": [{"data": "01/10/2026", "texto": "foi distribuída a ação."},
                           {"data": "03/10/2026", "texto": "foi determinada a citação da parte ré."}]}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.molde = TMP / "molde.docx"
        if not cls.molde.exists():
            gm.gerar(cls.molde, semente=7)

    def destino(self, nome):
        p = TMP / f"{self.id().split('.')[-1]}-{nome}.docx"
        if p.exists():
            p.unlink()
        return p

    def atualizacoes(self):
        return [
            {"numero": num(0), "momento_atual": "Cumprimento de sentença",
             "andamentos": [{"data": "2026-10-02", "texto": "O juiz proferiu sentença de procedência."},
                            {"data": "05/10/2026", "texto": "a ré interpôs recurso de apelação."}]},
            {"numeros": [PROCS[1]["numeros"][1]], "andamentos": [{"data": "01/10/2026", "texto": "foi julgado o agravo."}]},
            {"numero": num(2)},   # sem novidade: só renova o fecho
        ]

    def aplicar(self, atualizacoes=None, nome="saida", molde=None, **kw):
        destino = self.destino(nome)
        res = da.atualizar(molde or self.molde, destino, atualizacoes if atualizacoes is not None else self.atualizacoes(),
                           DATA_BASE_NOVA, **kw)
        return destino, res


class TestLeitura(Base):
    def test_estrutura_do_fixture(self):
        est = da.ler_estrutura(self.molde)
        self.assertEqual(est["data_base"], gm.DATA_BASE)
        self.assertEqual(est["cliente"], gm.CLIENTE)
        self.assertEqual(len(est["resumo"]), 12)
        self.assertEqual(len(est["processos"]), 12)
        self.assertEqual(est["avisos"], [])
        tres = est["processos"][1]
        self.assertEqual(len(tres["numeros"]), 3)
        self.assertEqual(est["resumo"][1]["numeros"], tres["numeros"])
        self.assertEqual(est["processos"][3]["valor_causa"], "")          # sem valor da causa
        self.assertEqual(est["processos"][4]["data_citacao"], "-")
        self.assertEqual(est["processos"][0]["momento_atual"], "AGUARDANDO SENTENÇA")
        self.assertEqual(est["processos"][0]["fecho"]["data"], gm.DATA_BASE)
        self.assertIsNone(est["processos"][8]["fecho"])                    # sem fecho
        self.assertTrue(all(a["data_em_negrito"] for p in est["processos"] for a in p["andamentos"]))
        self.assertEqual(da.verificar_coerencia(self.molde), [])

    def test_runs_fragmentados_no_fixture(self):
        """O fixture precisa ser mesmo 'sujo': muitos runs por parágrafo e datas quebradas."""
        _, runs = runs_do_par_andamentos(self.molde, 0)
        self.assertGreater(len(runs), 12)
        quebradas = [r for r in runs if re.fullmatch(r"[\d/]{1,9}", texto_el(r)) and len(texto_el(r)) < 10 and "/" in texto_el(r)
                     and len(texto_el(r)) != 10]
        self.assertTrue(quebradas, "esperava ao menos uma data partida em runs")


class TestAtualizacao(Base):
    def test_resumo_titulo_data_base_andamentos_e_fecho(self):
        destino, res = self.aplicar()
        est = da.ler_estrutura(destino)
        self.assertEqual(est["data_base"], DATA_BASE_NOVA)
        p0 = est["processos"][0]
        self.assertEqual(p0["momento_atual"], "CUMPRIMENTO DE SENTENÇA")                    # título
        self.assertEqual(est["resumo"][0]["momento_atual"], "CUMPRIMENTO DE SENTENÇA")      # resumo (negrito, caixa alta)
        self.assertEqual(est["resumo"][0]["ultimo_andamento"], "05/10/2026")
        self.assertEqual([a["data"] for a in p0["andamentos"]][-2:], ["02/10/2026", "05/10/2026"])
        self.assertTrue(p0["andamentos"][-1]["texto"].startswith("a ré interpôs"))
        self.assertTrue(p0["andamentos"][-2]["texto"].startswith("o juiz proferiu"))        # caixa ajustada
        self.assertEqual(p0["fecho"]["data"], DATA_BASE_NOVA)                               # fecho trocado
        self.assertEqual(p0["andamentos_texto"].count("sem atualizações"), 1)
        self.assertTrue(p0["andamentos_texto"].endswith(f"Em {DATA_BASE_NOVA}, sem atualizações."))
        # agravo reconhecido por UM dos três números; resumo atualizado
        self.assertEqual(est["resumo"][1]["ultimo_andamento"], "01/10/2026")
        # sem novidade: texto igual, só o fecho muda
        antes = da.ler_estrutura(self.molde)["processos"][2]["andamentos_texto"]
        depois = est["processos"][2]["andamentos_texto"]
        self.assertEqual(depois, antes.replace(gm.DATA_BASE, DATA_BASE_NOVA))
        self.assertEqual({m["campo"] for m in res["mudancas"] if m["numero"] == num(2)}, {"andamentos_fecho"})
        self.assertEqual(set(res["processos_atualizados"]), {num(0), PROCS[1]["numeros"][0], num(2)})

    def test_datas_novas_em_negrito_no_xml(self):
        destino, _ = self.aplicar()
        par, runs = runs_do_par_andamentos(destino, 0)
        for data in ("02/10/2026", "05/10/2026", DATA_BASE_NOVA):
            ach = [r for r in runs if texto_el(r) == data]
            self.assertEqual(len(ach), 1, data)
            self.assertTrue(da._negrito(ach[0].find(w("rPr"))), data)
        # e o texto novo NÃO está em negrito
        for r in runs:
            if texto_el(r).startswith(", o juiz proferiu"):
                self.assertFalse(da._negrito(r.find(w("rPr"))))

    def test_runs_novos_copiam_formatacao_do_vizinho(self):
        destino, _ = self.aplicar()
        _, antes = runs_do_par_andamentos(self.molde, 0)
        _, depois = runs_do_par_andamentos(destino, 0)
        modelo = next(r for r in reversed(antes) if texto_el(r).strip() and not da._negrito(r.find(w("rPr"))))
        novo = next(r for r in depois if texto_el(r).startswith(", o juiz proferiu"))
        def sem_b(rpr):
            rpr = copy.deepcopy(rpr)
            for b in rpr.findall(w("b")) + rpr.findall(w("bCs")):
                rpr.remove(b)
            return c14n(rpr)
        self.assertEqual(sem_b(novo.find(w("rPr"))), sem_b(modelo.find(w("rPr"))))
        # fonte/tamanho do negrito também são os do texto (Arial 11)
        data = next(r for r in depois if texto_el(r) == "02/10/2026")
        rpr = data.find(w("rPr"))
        self.assertEqual(rpr.find(w("sz")).get(w("val")), "22")
        self.assertEqual(rpr.find(w("rFonts")).get(w("ascii")), "Arial")

    def test_preservacao_do_que_nao_deveria_mudar(self):
        destino, _ = self.aplicar()
        t0, t1 = tabelas(self.molde), tabelas(destino)
        self.assertEqual(len(t0), len(t1))
        atualizados = {0, 1, 2}               # índices de processos tocados (tabela i+1)
        for i in range(1, len(t0)):
            if i - 1 not in atualizados:
                self.assertEqual(c14n(t0[i]), c14n(t1[i]), f"bloco {i - 1} mudou sem ter sido atualizado")
        # quadro-resumo: linhas dos processos não tocados idênticas; células intocadas das tocadas também
        r0, r1 = t0[0].findall(w("tr")), t1[0].findall(w("tr"))
        self.assertEqual(c14n(r0[0]), c14n(r1[0]))
        for k in range(1, len(r0)):
            if k - 1 not in atualizados:
                self.assertEqual(c14n(r0[k]), c14n(r1[k]))
        for k in atualizados:
            c0, c1 = r0[k + 1].findall(w("tc")), r1[k + 1].findall(w("tc"))
            for j in (0, 1):     # nº e assunto
                self.assertEqual(c14n(c0[j]), c14n(c1[j]))
            for j in range(4):   # larguras e bordas (tcPr) nunca mudam
                self.assertEqual(c14n(c0[j].find(w("tcPr"))), c14n(c1[j].find(w("tcPr"))))
        # blocos tocados: tudo igual, menos título (momento) e célula de andamentos
        for i in atualizados:
            a, b = t0[i + 1], t1[i + 1]
            self.assertEqual(c14n(a.find(w("tblPr"))), c14n(b.find(w("tblPr"))))
            self.assertEqual(c14n(a.find(w("tblGrid"))), c14n(b.find(w("tblGrid"))))
            la, lb = a.findall(w("tr")), b.findall(w("tr"))
            for k in range(1, len(la) - 1):
                self.assertEqual(c14n(la[k]), c14n(lb[k]))
            self.assertEqual(c14n(la[-1].findall(w("tc"))[0]), c14n(lb[-1].findall(w("tc"))[0]))     # rótulo
            self.assertEqual(c14n(la[-1].findall(w("tc"))[-1].find(w("tcPr"))), c14n(lb[-1].findall(w("tc"))[-1].find(w("tcPr"))))
            self.assertEqual(c14n(la[0].find(w("trPr"))), c14n(lb[0].find(w("trPr"))))
        # parágrafos fora das tabelas: só o da Data-Base muda
        p0 = [c14n(p) for p in corpo(self.molde).findall(w("p"))]
        p1 = [c14n(p) for p in corpo(destino).findall(w("p"))]
        self.assertEqual(len(p0), len(p1))
        diferentes = [k for k in range(len(p0)) if p0[k] != p1[k]]
        self.assertEqual(len(diferentes), 1)
        self.assertIn("Data-Base", texto_el(corpo(destino).findall(w("p"))[diferentes[0]]))
        # outras partes do pacote: byte a byte
        with zipfile.ZipFile(self.molde) as z0, zipfile.ZipFile(destino) as z1:
            self.assertEqual(z0.namelist(), z1.namelist())
            for n in z0.namelist():
                if n != "word/document.xml":
                    self.assertEqual(z0.read(n), z1.read(n), n)

    def test_so_acrescenta_texto_do_advogado_e_runs_antigos_intactos(self):
        destino, _ = self.aplicar()
        # processo 1 tem anotação do advogado em destaque (itálico + marca-texto) no fim do texto
        antes = da.ler_estrutura(self.molde)["processos"][1]["andamentos_texto"]
        depois = da.ler_estrutura(destino)["processos"][1]["andamentos_texto"]
        corpo_antigo = antes[:antes.rindex(" Em 18/09/2026")]
        self.assertTrue(depois.startswith(corpo_antigo), "texto antigo foi reescrito")
        self.assertIn("(Anotação do advogado: conferir o valor com o cliente.)", depois)
        par, runs = runs_do_par_andamentos(destino, 1)
        nota = [r for r in runs if "Anotação do advogado" in texto_el(r)]
        self.assertEqual(len(nota), 1)
        self.assertIsNotNone(nota[0].find(w("rPr")).find(w("highlight")))                      # destaque do advogado preservado
        for r in runs:                                                                          # ...e NÃO herdado pelo texto novo
            if "foi julgado o agravo" in texto_el(r):
                self.assertIsNone(r.find(w("rPr")).find(w("highlight")))
                self.assertIsNone(r.find(w("rPr")).find(w("i")))
        # todo run antigo que termina antes do fecho (menos o espaço separador) continua idêntico, byte a byte
        _, runs0 = runs_do_par_andamentos(self.molde, 1)
        texto0 = "".join(texto_el(r) for r in runs0)
        limite = texto0.rindex("Em 18/09/2026") - 1
        pos, verificados = 0, 0
        for k, r in enumerate(runs0):
            fim = pos + len(texto_el(r))
            if fim <= limite:
                self.assertEqual(c14n(r), c14n(runs[k]), f"run {k} mudou")
                verificados += 1
            pos = fim
        self.assertGreater(verificados, 10)

    def test_idempotencia(self):
        d1, r1 = self.aplicar(nome="um")
        self.assertTrue(r1["mudancas"])
        upds = self.atualizacoes() + [{"novo": self.proc_novo()}]
        d1, r1 = self.aplicar(upds, nome="um")
        d2 = self.destino("dois")
        r2 = da.atualizar(d1, d2, upds, DATA_BASE_NOVA)
        self.assertEqual(r2["mudancas"], [])
        self.assertEqual(r2["processos_atualizados"], [])
        self.assertEqual(r2["processos_novos"], [])
        with zipfile.ZipFile(d1) as z1, zipfile.ZipFile(d2) as z2:
            self.assertEqual(z1.read("word/document.xml"), z2.read("word/document.xml"))
        est = da.ler_estrutura(d2)
        t = est["processos"][0]["andamentos_texto"]
        self.assertEqual(t.count("02/10/2026"), 1)
        self.assertEqual(t.count("sem atualizações"), 1)
        self.assertEqual(len(est["processos"]), 13)
        self.assertTrue(any(i["motivo"] == "andamento já presente" for i in r2["ignorados"]))
        # reaplicação com 'texto_conhecido' antigo não acusa edição manual
        upds_c = copy.deepcopy(upds)
        upds_c[0]["texto_conhecido"] = da.ler_estrutura(self.molde)["processos"][0]["andamentos_texto"]
        r3 = da.atualizar(d1, self.destino("tres"), upds_c, DATA_BASE_NOVA)
        self.assertFalse([a for a in r3["avisos"] if a["codigo"] == "edicao_manual"])

    proc_novo = staticmethod(lambda numeros=None, tipos=None: proc_novo(numeros, tipos))

    def test_nao_duplica_andamento_ja_presente_mesmo_com_variacao(self):
        existente = "a ré juntou documentos e rol de testemunhas."
        upds = [{"numero": num(2), "andamentos": [
            {"data": "01/09/2026", "texto": "A ré juntou documentos e rol de testemunhas"},     # caixa e ponto diferentes
            {"data": "01/09/2026", "texto": "foi juntada nova procuração aos autos."},          # outra coisa, mesma data
        ]}]
        destino, res = self.aplicar(upds)
        t = da.ler_estrutura(destino)["processos"][2]["andamentos_texto"]
        self.assertEqual(t.count(existente), 1)
        self.assertIn("nova procuração", t)
        self.assertEqual(sum(1 for i in res["ignorados"] if i["motivo"] == "andamento já presente"), 1)

    def test_edicao_manual_recente_so_acrescenta_e_avisa(self):
        conhecido = da.ler_estrutura(self.molde)["processos"][0]["andamentos_texto"]
        # o advogado acrescentou uma frase à mão depois do último ciclo
        def mexer(raiz):
            tbl = raiz.find(w("body")).findall(w("tbl"))[1]
            par = tbl.findall(w("tr"))[-1].findall(w("tc"))[-1].findall(w("p"))[-1]
            fecho = [r for r in par.findall(w("r"))]
            novo = da._novo_run(" Em ", da._rpr_modelo(fecho[0].find(w("rPr")), False))
            par.insert(len(par) - 4, novo)       # antes dos runs do fecho: edição no meio do final
            par.insert(len(par) - 4, da._novo_run("(nota do advogado: cliente ligou)", da._rpr_modelo(fecho[0].find(w("rPr")), False)))
        editado = TMP / "editado.docx"
        escrever_doc(self.molde, editado, mexer)
        upds = [{"numero": num(0), "texto_conhecido": conhecido,
                 "andamentos": [{"data": "02/10/2026", "texto": "o juiz proferiu sentença."}]}]
        destino, res = self.aplicar(upds, molde=editado)
        avisos = [a for a in res["avisos"] if a["codigo"] == "edicao_manual"]
        self.assertEqual(len(avisos), 1)
        t = da.ler_estrutura(destino)["processos"][0]["andamentos_texto"]
        self.assertIn("(nota do advogado: cliente ligou)", t)       # nada apagado
        self.assertIn("o juiz proferiu sentença.", t)
        # sem divergência, sem aviso
        destino2, res2 = self.aplicar([{"numero": num(0), "texto_conhecido": conhecido,
                                        "andamentos": [{"data": "02/10/2026", "texto": "o juiz proferiu sentença."}]}], nome="limpo")
        self.assertFalse([a for a in res2["avisos"] if a["codigo"] == "edicao_manual"])

    def test_duplicata_provavelmente_digitada_a_mao_nao_e_repetida(self):
        # o andamento de 30/07 já está no texto (digitado pelo sistema ou à mão), com palavras um pouco diferentes
        upds = [{"numero": num(0), "andamentos": [{"data": "30/07/2026", "texto": "os autos foram conclusos ao juiz para sentença."}]}]
        destino, res = self.aplicar(upds)
        t = da.ler_estrutura(destino)["processos"][0]["andamentos_texto"]
        self.assertEqual(t.count("30/07/2026"), 1)
        self.assertEqual(len(res["ignorados"]), 1)

    def test_fecho_variantes(self):
        sem_novidade = [{"numero": num(i)} for i in (7, 9, 8)]
        destino, res = self.aplicar(sem_novidade)
        est = da.ler_estrutura(destino)
        # 7: fecho todo em negrito -> continua em negrito; só a data muda
        t7 = est["processos"][7]["andamentos_texto"]
        self.assertTrue(t7.endswith(f"Em {DATA_BASE_NOVA}, sem atualizações."))
        _, runs = runs_do_par_andamentos(destino, 7)
        self.assertTrue(all(da._negrito(r.find(w("rPr"))) for r in runs if texto_el(r) in (DATA_BASE_NOVA,)))
        # 9: 'sem atualização' (singular) mantém a redação original
        self.assertTrue(est["processos"][9]["andamentos_texto"].endswith(f"Em {DATA_BASE_NOVA}, sem atualização."))
        # 8: não tinha fecho -> acrescentado com aviso informativo
        self.assertTrue(est["processos"][8]["andamentos_texto"].endswith(f"Em {DATA_BASE_NOVA}, sem atualizações."))
        self.assertTrue(est["processos"][8]["fecho"]["data_em_negrito"])
        self.assertTrue([a for a in res["avisos"] if a["codigo"] == "fecho_acrescentado"])

    def test_fecho_apos_novidade_falso(self):
        destino, _ = self.aplicar([{"numero": num(0), "andamentos": [{"data": "02/10/2026", "texto": "foi proferida sentença."}]}],
                                  fecho_apos_novidade=False)
        p = da.ler_estrutura(destino)["processos"][0]
        self.assertIsNone(p["fecho"])
        self.assertTrue(p["andamentos_texto"].endswith("Em 02/10/2026, foi proferida sentença."))

    def test_renovar_fecho_dos_demais(self):
        destino, res = self.aplicar([{"numero": num(0)}], renovar_fecho_dos_demais=True)
        est = da.ler_estrutura(destino)
        for p in est["processos"]:
            self.assertEqual((p["fecho"] or {}).get("data"), DATA_BASE_NOVA, p["numeros"][0])
        self.assertEqual(da.verificar_coerencia(destino), [])

    def test_numero_nao_encontrado(self):
        destino, res = self.aplicar([{"numero": "9999999-99.9999.9.99.9999", "andamentos": [{"data": "01/10/2026", "texto": "x."}]}])
        self.assertEqual(res["nao_encontrados"], ["9999999-99.9999.9.99.9999"])
        self.assertTrue([a for a in res["avisos"] if a["codigo"] == "processo_nao_encontrado"])

    def test_original_nunca_e_sobrescrito(self):
        antes = self.molde.read_bytes()
        with self.assertRaises(ValueError):
            da.atualizar(self.molde, self.molde, [], DATA_BASE_NOVA)
        link = TMP / "link.docx"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(self.molde)
        with self.assertRaises(ValueError):
            da.atualizar(self.molde, link, [], DATA_BASE_NOVA)
        existente = self.destino("ja_existe")
        existente.write_bytes(b"x")
        with self.assertRaises(FileExistsError):
            da.atualizar(self.molde, existente, [], DATA_BASE_NOVA)
        self.aplicar()
        self.assertEqual(self.molde.read_bytes(), antes)

    def test_mesclagem_vertical_preservada(self):
        destino, _ = self.aplicar([{"numero": num(6), "momento_atual": "Trânsito em julgado",
                                    "andamentos": [{"data": "01/10/2026", "texto": "a apelação foi julgada."}]}])
        a, b = tabelas(self.molde)[7], tabelas(destino)[7]
        self.assertEqual(len(list(a.iter(w("vMerge")))), 2)
        self.assertEqual(len(list(b.iter(w("vMerge")))), 2)
        ra, rb = a.findall(w("tr")), b.findall(w("tr"))
        for k in range(2, len(ra) - 1):
            self.assertEqual(c14n(ra[k]), c14n(rb[k]))

    def test_sem_mudancas_o_document_xml_fica_identico(self):
        destino, res = self.aplicar([], molde=self.molde)
        # data-base muda, então não é "sem mudança"; com a mesma data-base é
        d2 = self.destino("mesma")
        res2 = da.atualizar(self.molde, d2, [], gm.DATA_BASE)
        self.assertEqual(res2["mudancas"], [])
        with zipfile.ZipFile(self.molde) as z0, zipfile.ZipFile(d2) as z1:
            self.assertEqual(z0.read("word/document.xml"), z1.read("word/document.xml"))


class TestProcessoNovo(Base):
    def test_clona_bloco_e_linha_do_resumo(self):
        destino, res = self.aplicar([{"novo": self.proc()}])
        self.assertEqual(res["processos_novos"], [self.proc()["numeros"][0]])
        est = da.ler_estrutura(destino)
        self.assertEqual(len(est["processos"]), 13)
        self.assertEqual(len(est["resumo"]), 13)
        novo = est["processos"][-1]
        self.assertEqual(novo["numeros"], self.proc()["numeros"])
        self.assertEqual(novo["momento_atual"], "AGUARDANDO CITAÇÃO")
        self.assertEqual(novo["valor_causa"], "R$ 12.345,60")
        self.assertEqual(novo["data_citacao"], "-")
        self.assertEqual(novo["ajuizamento"], "30/09/2026")
        self.assertEqual([a["data"] for a in novo["andamentos"]], ["01/10/2026", "03/10/2026"])
        self.assertTrue(all(a["data_em_negrito"] for a in novo["andamentos"]))
        self.assertEqual(novo["fecho"]["data"], DATA_BASE_NOVA)
        self.assertEqual(est["resumo"][-1], {"numeros": novo["numeros"], "assunto": "Ação de teste nova",
                                             "momento_atual": "AGUARDANDO CITAÇÃO", "ultimo_andamento": "03/10/2026"})
        self.assertEqual(da.verificar_coerencia(destino, fechos=False), [])
        # nada de texto do bloco-modelo sobrou no clone
        modelo_texto = da.ler_estrutura(self.molde)["processos"][-1]
        for campo in ("assunto", "autores", "juizo", "materia"):
            self.assertNotEqual(novo[campo], modelo_texto[campo])
        self.assertNotIn(modelo_texto["andamentos"][0]["texto"], novo["andamentos_texto"])
        # estrutura (larguras, mesclagens, bordas) igual à do modelo clonado
        tb = tabelas(destino)
        self.assertEqual(c14n(tb[-1].find(w("tblGrid"))), c14n(tb[-2].find(w("tblGrid"))))
        self.assertEqual(c14n(tb[-1].find(w("tblPr"))), c14n(tb[-2].find(w("tblPr"))))
        spans = lambda t: [[tc.find(w("tcPr")).find(w("gridSpan")) is not None for tc in tr.findall(w("tc"))] for tr in t.findall(w("tr"))]
        self.assertEqual(spans(tb[-1]), spans(tb[-2]))
        # parágrafo vazio separa as tabelas (senão o Word as funde)
        corpo_ = corpo(destino)
        filhos = list(corpo_)
        i = filhos.index(corpo_.findall(w("tbl"))[-1])
        self.assertEqual(filhos[i - 1].tag, w("p"))
        self.assertFalse(texto_el(filhos[i - 1]).strip())

    def proc(self, **kw):
        return proc_novo(**kw)

    def test_processo_novo_com_tres_numeros(self):
        p = self.proc(numeros=["1234569-13.2026.8.06.0100", "1234570-91.2026.8.06.0101", "1234567-35.2026.8.06.0102"],
                      tipos=["agravo", "apenso"])
        destino, _ = self.aplicar([{"novo": p}])
        est = da.ler_estrutura(destino)
        self.assertEqual(est["processos"][-1]["numeros"], p["numeros"])
        self.assertEqual(est["resumo"][-1]["numeros"], p["numeros"])
        self.assertIn("AGRAVO Nº", est["processos"][-1]["titulo"])
        self.assertEqual(da.verificar_coerencia(destino, fechos=False), [])

    def test_novo_nao_duplica_se_numero_ja_existe(self):
        p = self.proc(numeros=[num(0)])
        destino, res = self.aplicar([{"novo": p}])
        self.assertEqual(res["processos_novos"], [])
        self.assertEqual(len(da.ler_estrutura(destino)["processos"]), 12)

    def test_modelo_ruim_nao_e_clonado(self):
        """Com os 7 primeiros processos, o último bloco tem mesclagem vertical: o clone deve vir de um bloco limpo."""
        molde = TMP / "molde7.docx"
        gm.gerar(molde, n=7)
        destino, res = self.aplicar([{"novo": self.proc()}], molde=molde, nome="m7")
        self.assertEqual(len(list(tabelas(destino)[-1].iter(w("vMerge")))), 0)
        self.assertFalse([a for a in res["avisos"] if a["codigo"] == "modelo_imperfeito"])
        self.assertEqual(da.ler_estrutura(destino)["processos"][-1]["reus"], gm.CLIENTE)

    def test_celula_solta_do_modelo_nao_vaza_para_o_clone(self):
        """Se o único bloco tem texto fora do padrão, o clone esvazia a célula e avisa."""
        molde = TMP / "molde1.docx"
        gm.gerar(molde, n=1)
        def mexer(raiz):    # texto solto numa linha extra do bloco
            tbl = raiz.find(w("body")).findall(w("tbl"))[1]
            extra = copy.deepcopy(tbl.findall(w("tr"))[-1])
            for t in extra.iter(w("t")):
                t.text = "Observação manual do advogado sobre este processo"
            tbl.append(extra)
        sujo = TMP / "sujo.docx"
        escrever_doc(molde, sujo, mexer)
        destino, res = self.aplicar([{"novo": self.proc()}], molde=sujo, nome="sujo")
        self.assertNotIn("Observação manual", texto_el(tabelas(destino)[-1]))
        self.assertTrue([a for a in res["avisos"] if a["codigo"] in ("celula_limpa", "modelo_imperfeito")])
        self.assertIn("Observação manual", texto_el(tabelas(destino)[1]))        # o original do advogado ficou


class TestVariantes(Base):
    def test_texto_de_andamentos_na_linha_de_baixo(self):
        molde = TMP / "abaixo.docx"
        gm.gerar(molde, variante="andamentos_abaixo")
        est = da.ler_estrutura(molde)
        self.assertEqual(len(est["processos"][0]["andamentos"]), 4)
        destino, _ = self.aplicar([{"numero": num(0), "andamentos": [{"data": "02/10/2026", "texto": "foi proferida sentença."}]}],
                                  molde=molde, nome="abaixo")
        p = da.ler_estrutura(destino)["processos"][0]
        self.assertEqual(p["andamentos"][-1]["data"], "02/10/2026")
        self.assertEqual(p["fecho"]["data"], DATA_BASE_NOVA)

    def test_varias_fragmentacoes(self):
        """O resultado não pode depender de onde o Google quebrou os runs."""
        esperado = None
        for semente in range(1, 13):
            molde = TMP / f"frag{semente}.docx"
            gm.gerar(molde, semente=semente)
            destino, res = self.aplicar(self.atualizacoes(), molde=molde, nome=f"frag{semente}")
            est = da.ler_estrutura(destino)
            textos = [p["andamentos_texto"] for p in est["processos"]]
            if esperado is None:
                esperado = textos
            self.assertEqual(textos, esperado, f"semente {semente}")
            self.assertEqual(da.verificar_coerencia(destino, fechos=False), [], f"semente {semente}")
            self.assertTrue(all(a["data_em_negrito"] for p in est["processos"] for a in p["andamentos"]))

    def test_controle_de_alteracoes_e_comentario_no_trecho_final(self):
        """Limite documentado: com revisão/comentário no parágrafo, nada é removido; só acrescenta e avisa."""
        def mexer(raiz):
            tbl = raiz.find(w("body")).findall(w("tbl"))[1]
            par = tbl.findall(w("tr"))[-1].findall(w("tc"))[-1].findall(w("p"))[-1]
            runs = par.findall(w("r"))
            ins = etree.Element(w("ins"))
            ins.set(w("id"), "900"), ins.set(w("author"), "Advogada Exemplo"), ins.set(w("date"), "2026-09-20T10:00:00Z")
            runs[-1].addprevious(ins)
            for r in runs[-3:]:
                ins.append(r)
            ini = etree.Element(w("commentRangeStart")); ini.set(w("id"), "5")
            par.insert(1, ini)
        sujo = TMP / "revisao.docx"
        escrever_doc(self.molde, sujo, mexer)
        destino, res = self.aplicar([{"numero": num(0), "andamentos": [{"data": "02/10/2026", "texto": "foi proferida sentença."}]}],
                                    molde=sujo, nome="revisao")
        self.assertTrue([a for a in res["avisos"] if a["codigo"] == "revisao_no_trecho"])
        r = doc_xml(destino)
        self.assertEqual(len(list(r.iter(w("ins")))), 1)
        self.assertEqual(len(list(r.iter(w("commentRangeStart")))), 1)
        t = da.ler_estrutura(destino)["processos"][0]["andamentos_texto"]
        self.assertIn(f"Em {gm.DATA_BASE}, sem atualizações.", t)       # fecho antigo preservado dentro da revisão
        self.assertTrue(t.endswith(f"Em {DATA_BASE_NOVA}, sem atualizações."))


class TestGerarDoZero(Base):
    def relatorio(self):
        procs = []
        for i, p in enumerate(PROCS[:5]):
            procs.append({"numeros": p["numeros"], "tipos": p["tipos"], "assunto": p["assunto"], "autores": p["autores"],
                          "reus": p["reus"], "ajuizamento": p["ajuizamento"], "valor_causa": p["valor_causa"] or None,
                          "data_citacao": p["citacao"], "juizo": p["juizo"], "area": p["area"], "materia": p["materia"],
                          "momento_atual": p["momento"], "andamentos": [{"data": d, "texto": t} for d, t in p["andamentos"]]})
        procs.append(dict(procs[0], numeros=[PROCS[0]["numeros"][0].replace("-86.", "-87.")], andamentos=[]))
        return {"cliente": gm.CLIENTE, "data_base": "2026-10-07", "processos": procs}

    def test_gerar_recarrega_e_e_coerente(self):
        destino = self.destino("zero")
        res = da.gerar(destino, self.relatorio())
        self.assertEqual(len(res["processos_novos"]), 6)
        import docx
        d = docx.Document(str(destino))
        self.assertEqual(len(d.tables), 7)            # resumo + 6 blocos
        est = da.ler_estrutura(destino)
        self.assertEqual(est["data_base"], DATA_BASE_NOVA)
        self.assertEqual(len(est["resumo"]), 6)
        self.assertEqual(est["processos"][1]["numeros"], PROCS[1]["numeros"])
        self.assertEqual(est["processos"][3]["valor_causa"], "-")
        self.assertEqual(est["processos"][5]["andamentos_texto"], f"Em {DATA_BASE_NOVA}, sem atualizações.")
        self.assertTrue(all(a["data_em_negrito"] for p in est["processos"] for a in p["andamentos"]))
        self.assertEqual(da.verificar_coerencia(destino), [])

    def test_gerado_do_zero_pode_ser_atualizado(self):
        base = self.destino("zero2")
        da.gerar(base, self.relatorio())
        destino, res = self.aplicar([{"numero": num(0), "andamentos": [{"data": "05/10/2026", "texto": "foi proferida sentença."}],
                                      "momento_atual": "Aguardando julgamento da apelação"},
                                     {"novo": proc_novo()}], molde=base, nome="zero3")
        est = da.ler_estrutura(destino)
        self.assertEqual(len(est["processos"]), 7)
        self.assertEqual(est["processos"][0]["momento_atual"], "AGUARDANDO JULGAMENTO DA APELAÇÃO")
        self.assertEqual(da.verificar_coerencia(destino), [])

    def test_gerar_nao_sobrescreve(self):
        destino = self.destino("zero4")
        da.gerar(destino, self.relatorio())
        with self.assertRaises(FileExistsError):
            da.gerar(destino, self.relatorio())


class TestContratoGravar(Base):
    def estado(self):
        def ficha(i, **campos):
            p = PROCS[i]
            f = {"numero": p["numeros"][0], "vinculados": [{"numero": n, "tipo": t} for n, t in zip(p["numeros"][1:], p["tipos"])],
                 "campos": {"assunto": {"valor": p["assunto"], "origem": "migrado"},
                            "autores": {"valor": p["autores"], "origem": "migrado"}, "reus": {"valor": p["reus"], "origem": "migrado"},
                            "momento_atual": {"valor": p["momento"], "origem": "migrado"}}}
            for k, v in campos.items():
                f["campos"][k] = {"valor": v, "origem": "coletado"}
            return f
        return {"cliente": gm.CLIENTE, "data_base": "2026-10-07", "perfil": {}, "parametros": {},
                "fichas": [ficha(0, momento_atual="CUMPRIMENTO DE SENTENÇA", ultimo_andamento="2026-10-02"),
                           ficha(1),
                           dict(ficha(2), numero="1234568-27.2026.8.06.0099", vinculados=[], campos={
                               "assunto": {"valor": "Ação nova", "origem": "coletado"},
                               "valor_causa": {"valor": "1500.00", "origem": "coletado"},
                               "data_ajuizamento": {"valor": "2026-09-30", "origem": "coletado"},
                               "vara": {"valor": "1ª Vara Fictícia", "origem": "coletado"},
                               "momento_atual": {"valor": "AGUARDANDO CITAÇÃO", "origem": "coletado"}})],
                "eventos": [{"numero": num(0), "data": "02/10/2026", "frase": "Foi proferida sentença de procedência.",
                             "conteudo": "", "status": "aprovado"},
                            {"numero": PROCS[1]["numeros"][1], "data": "01/10/2026", "frase": "Foi julgado o agravo de instrumento.",
                             "grau": "2º grau", "status": "aprovado"}]}

    def test_gravar_com_molde(self):
        destino = self.destino("g1")
        res = da.gravar(self.molde, self.estado(), destino)
        for chave in ("destino", "processos_atualizados", "processos_novos", "mudancas", "avisos"):
            self.assertIn(chave, res)
        self.assertEqual(Path(res["destino"]), destino)
        self.assertEqual(res["processos_novos"], ["1234568-27.2026.8.06.0099"])
        self.assertTrue(all(set(m) == {"numero", "campo", "antes", "depois"} for m in res["mudancas"]))
        self.assertTrue(all({"nivel", "onde", "mensagem", "candidatos"} <= set(a) for a in res["avisos"]))
        est = da.ler_estrutura(destino)
        self.assertEqual(est["processos"][0]["momento_atual"], "CUMPRIMENTO DE SENTENÇA")
        self.assertIn("Em 02/10/2026, foi proferida sentença de procedência.", est["processos"][0]["andamentos_texto"])
        self.assertIn("Em 01/10/2026, no 2º grau, foi julgado o agravo de instrumento.", est["processos"][1]["andamentos_texto"])
        self.assertEqual(est["processos"][-1]["valor_causa"], "R$ 1.500,00")
        # idempotente
        res2 = da.gravar(self.molde, self.estado(), self.destino("g2"))
        res3 = da.gravar(destino, self.estado(), self.destino("g3"))
        self.assertEqual(res3["mudancas"], [])
        with self.assertRaises(ValueError):
            da.gravar(self.molde, self.estado(), self.molde)

    def test_gravar_sem_molde_cria_do_zero(self):
        destino = self.destino("g4")
        res = da.gravar(None, self.estado(), destino)
        self.assertEqual(len(res["processos_novos"]), 3)
        self.assertEqual(da.verificar_coerencia(destino), [])
        self.assertEqual(len(da.ler_estrutura(destino)["processos"]), 3)


@unittest.skipUnless(SOFFICE, "soffice não instalado")
class TestLibreOffice(Base):
    def test_atualizado_abre_e_texto_novo_aparece_no_pdf(self):
        upds = self.atualizacoes() + [{"novo": proc_novo()}]
        destino, _ = self.aplicar(upds, nome="pdf")
        texto, paginas = pdf_texto(destino)
        self.assertGreater(paginas, 2)
        for trecho in ("Data-Base:07/10/2026", "02/10/2026", "ojuizproferiusentençadeprocedência", "05/10/2026",
                       "Em07/10/2026,sematualizações", "1234568-27.2026.8.06.0099", "Açãodetestenova", "CUMPRIMENTODESENTENÇA",
                       "foidistribuídaaação"):
            self.assertIn(so_digitos_e_letras(trecho), texto, trecho)
        self.assertNotIn("18/09/2026,sematualizações" + "Em", texto)
        # o que não foi tocado continua lá
        self.assertIn(so_digitos_e_letras("Anotação do advogado: conferir o valor com o cliente."), texto)

    def test_original_e_gerado_do_zero_tambem_abrem(self):
        texto, paginas = pdf_texto(self.molde)
        self.assertIn("COMERCIALEXEMPLOALFALTDA.", texto)
        self.assertGreater(paginas, 2)
        base = self.destino("zero_pdf")
        da.gerar(base, TestGerarDoZero.relatorio(self))
        texto2, _ = pdf_texto(base)
        self.assertIn("PROCESSONº" + so_digitos_e_letras(PROCS[0]["numeros"][0]), texto2)

    def test_resumo_e_blocos_batem_no_pdf(self):
        destino, _ = self.aplicar()
        texto, _ = pdf_texto(destino)
        # momento novo aparece no quadro-resumo e no título do bloco: pelo menos 2 vezes
        self.assertGreaterEqual(texto.count("CUMPRIMENTODESENTENÇA"), 2)


if __name__ == "__main__":
    unittest.main()
