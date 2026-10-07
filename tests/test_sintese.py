"""Síntese (WS-5): momento atual, último andamento e narrativa, com fichas fictícias, o coletor simulado e um
provedor de IA FALSO e determinístico (nenhuma chamada de rede, nenhum modelo real).

    python3 -m unittest tests/test_sintese.py -v
"""
import copy
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import ficha as fch  # noqa: E402
import ficticio  # noqa: E402
import extrair  # noqa: E402
import resumir  # noqa: E402
import simulado  # noqa: E402
import sintese  # noqa: E402
import taxonomia  # noqa: E402
import traduzir  # noqa: E402

FICHAS = ficticio.gerar_carteira(200, clientes=5, semente=1)
PASTA = tempfile.mkdtemp(prefix="sintese-teste-", dir=isolamento.TMP)
COLETOR = simulado.ColetorSimulado(FICHAS, semente=1, taxa_falha=0.0, pasta=PASTA)
DATA_NO_TEXTO = re.compile(r"Em (\d{2})/(\d{2})/(\d{4})")
DEFINITIVOS = {"TRÂNSITO EM JULGADO", "PROCESSO ARQUIVADO", "ACORDO HOMOLOGADO", "EXTINTO SEM RESOLUÇÃO DE MÉRITO",
               "AGUARDANDO AUDIÊNCIA", "AGUARDANDO PROVA PERICIAL", "AGUARDANDO RÉPLICA", "AGUARDANDO SENTENÇA"}
_CACHE = {}
_TEXTOS = {}


def coleta(f, profundidade="padrao"):
    chave = (f["numero"], profundidade)
    if chave not in _CACHE:
        _CACHE[chave] = COLETOR.coletar({"numero": f["numero"]}, profundidade, None)
    return copy.deepcopy(_CACHE[chave])


def eventos_da_coleta(f, resultado, com_texto=True):
    """Eventos no formato da Fase 1 (movimento e documento), como o coletor e o extrair os deixam."""
    evs = []
    for i, m in enumerate(resultado["movimentos"]):
        evs.append({"id": f"{f['numero']}:m{i}", "tipo_evento": "movimento", "numero": f["numero"], "titulo": m["texto"],
                    "data": fch.data_br(m["data"]), "status": "coletado", "chave": m["chave"], "grau": m["grau"]})
    for i, d in enumerate(resultado["documentos"]):
        info = traduzir.separar_nome_documento(d["nome"])
        ev = {"id": f"{f['numero']}:d{i}", "tipo_evento": "documento", "numero": f["numero"], "titulo": d["nome"],
              "tipo": info["tipo"], "descricao": info["descricao"], "data": fch.data_br(d["data"]), "status": "extraido",
              "arquivo": d["caminho"]}
        if com_texto:
            if d["caminho"] not in _TEXTOS:  # ler o PDF é o que mais demora; cada arquivo é lido uma vez
                _TEXTOS[d["caminho"]] = extrair.extrair_arquivo(d["caminho"])[0]
            ev["texto"] = _TEXTOS[d["caminho"]]
        evs.append(ev)
    return evs


class ProvedorFalso:
    """Provedor de IA determinístico (interface de CONTRATOS §8). Resume documentos por palavras-chave do texto e
    indica o momento por `momento_ia(linhas)`; registra as chamadas."""

    def __init__(self, motor="falso:teste", momento_ia=None, inventar_trecho=False, falhar=False, texto_puro=False):
        self.motor, self.momento_ia, self.inventar_trecho = motor, momento_ia, inventar_trecho
        self.falhar, self.texto_puro, self.chamadas = falhar, texto_puro, []

    def gerar(self, sistema, usuario, *, esquema=None, cliente=""):
        self.chamadas.append({"sistema": sistema, "usuario": usuario, "esquema": esquema, "cliente": cliente})
        if self.falhar:
            raise ConnectionError("provedor fora do ar")
        if esquema and "momento" in esquema["properties"]:
            dados = (self.momento_ia or (lambda linhas: {"momento": None, "qualificador": None, "trecho_origem": ""}))(
                usuario.split("<<<")[1].split(">>>")[0].strip().splitlines())
        else:
            dados = self._resumo(usuario.split("<<<")[1].rsplit(">>>", 1)[0])
        import json
        return {"texto": json.dumps(dados, ensure_ascii=False), "json": None if self.texto_puro else dados, "motor": self.motor}

    def _resumo(self, texto):
        regras = [("JULGO PARCIALMENTE", "julgando parcialmente procedentes os pedidos da inicial"),
                  ("JULGO PROCEDENTE", "julgando procedente o pedido da inicial"),
                  ("JULGO IMPROCEDENTE", "julgando improcedente o pedido da inicial"),
                  ("HOMOLOGO", "homologando o acordo entre as partes"),
                  ("EXTINGO", "extinguindo o processo sem resolução do mérito")]
        for chave, conteudo in regras:
            m = re.search(rf"[^.\n]*{chave}[^.\n]*", texto)
            if m:
                trecho = "A condenação foi fixada em dez milhões de reais" if self.inventar_trecho else m.group(0).strip()
                return {"conteudo": conteudo, "trecho_origem": trecho, "prazo": None, "audiencia": None, "efeito": "neutro"}
        linha = next((l.strip() for l in texto.splitlines() if len(l.strip()) > 30), "")
        return {"conteudo": "determinando o prosseguimento do processo", "trecho_origem": linha[:120], "prazo": None,
                "audiencia": None, "efeito": "neutro"}


def ficha_com(**campos):
    f = fch.nova_ficha(ficticio.numero_ficticio(900))
    for nome, valor in campos.items():
        fch.definir(f, nome, valor, "coletado")
    return f


def mov(data, texto):
    return {"data": data, "texto": texto, "grau": "1º grau", "chave": f"{data}|{texto}|1"}


def evento_mov(i, data_br, titulo, **extra):
    return {"id": f"x:m{i}", "tipo_evento": "movimento", "numero": ficticio.numero_ficticio(900), "titulo": titulo,
            "data": data_br, "status": "coletado", **extra}


def evento_doc(i, data_br, tipo, descricao=None, **extra):
    return {"id": f"x:d{i}", "tipo_evento": "documento", "numero": ficticio.numero_ficticio(900),
            "titulo": f"{190000000 + i} - {tipo} - {descricao or tipo}.pdf", "tipo": tipo, "descricao": descricao or tipo,
            "data": data_br, "status": "extraido", **extra}


# ============================================================================================ momento atual

class TestMomentoRegras(unittest.TestCase):
    def test_sempre_do_vocabulario_e_coerente_com_a_ficha(self):
        familias_ok = exatos = 0
        for f in FICHAS:
            esperado = fch.obter(f, "momento_atual")
            m = sintese.momento_atual(f, [], coleta(f)["movimentos"], None)
            self.assertEqual(set(m) - {"motor"}, {"momento", "qualificador", "evidencia", "origem", "origem_ficha", "alertas"})
            if m["momento"] is None:
                self.assertIsNone(m["origem"])
                self.assertTrue(m["alertas"], "sem momento tem de explicar o porquê")
                continue
            self.assertIn(m["momento"], taxonomia.MOMENTO_ATUAL)
            self.assertEqual((m["origem"], m["origem_ficha"]), ("regra", "derivado"))
            self.assertTrue(m["evidencia"], "regra sempre traz o movimento que a sustenta")
            self.assertEqual(taxonomia.categoria_do_momento(m["momento"]), taxonomia.categoria_do_momento(esperado),
                             f"{esperado} lido como {m['momento']}")
            familias_ok += 1
            if esperado in DEFINITIVOS:
                self.assertEqual(m["momento"], esperado, f"{esperado}: sinal definitivo tem de bater")
                exatos += 1
        self.assertGreater(familias_ok, 150, "as regras devem cobrir a maior parte da carteira")
        self.assertGreater(exatos, 80)

    def test_evidencia_e_um_movimento_real_com_data(self):
        f = FICHAS[3]
        movimentos = coleta(f)["movimentos"]
        m = sintese.momento_atual(f, [], movimentos, None)
        # evidência de taxonomia.momento_por_regras: 'Movimento de DD/MM/AAAA: "texto" (regra: nome)'
        achado = re.search(r'(\d{2}/\d{2}/\d{4}): "(.+)"', m["evidencia"])
        self.assertIsNotNone(achado, m["evidencia"])
        self.assertIn((fch.parse_data(achado[1]), achado[2]), [(x["data"], x["texto"]) for x in movimentos])

    def test_usa_os_movimentos_dos_eventos_quando_nao_ha_movimentos(self):
        f = next(f for f in FICHAS if fch.obter(f, "momento_atual") == "AGUARDANDO SENTENÇA")
        r = coleta(f)
        evs = eventos_da_coleta(f, r, com_texto=False)
        self.assertEqual(sintese.momento_atual(f, evs, [], None)["momento"], "AGUARDANDO SENTENÇA")
        self.assertEqual(sintese.momento_atual(f, [], r["movimentos"], None)["momento"], "AGUARDANDO SENTENÇA")

    def test_neutros_nao_mudam_o_momento_e_incerteza_para(self):
        f = ficha_com()
        base = [mov("2026-08-01", "Conclusos para julgamento")]
        ruido = [mov("2026-08-05", "Publicado Decisão em 05/08/2026."), mov("2026-08-06", "Expedida/certificada a comunicação eletrônica")]
        self.assertEqual(sintese.momento_atual(f, [], base + ruido, None)["momento"], "AGUARDANDO SENTENÇA")
        incerto = base + [mov("2026-08-07", "Desarquivado")]
        self.assertIsNone(sintese.momento_atual(f, [], incerto, None)["momento"])
        desconhecido = base + [mov("2026-08-07", "Movimento qualquer que nenhuma regra cobre")]
        self.assertIsNone(sintese.momento_atual(f, [], desconhecido, None)["momento"])

    def test_separar_qualificador(self):
        self.assertEqual(sintese.separar_qualificador("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)"),
                         ("CUMPRIMENTO DE SENTENÇA", "HONORÁRIOS SUSPENSOS"))
        self.assertEqual(sintese.separar_qualificador("SUSPENSO"), ("SUSPENSO", None))
        self.assertEqual(sintese.separar_qualificador("PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)"),
                         ("PROCESSO ARQUIVADO", "DECISÃO FAVORÁVEL"))

    def test_usa_a_regra_do_ws1_quando_existir_e_separa_o_qualificador(self):
        chamadas = []

        def regras(movimentos):
            chamadas.append(movimentos)
            return "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)", {"texto": "17/09/2026: Suspensos os honorários"}

        with mock.patch.object(taxonomia, "momento_por_regras", regras, create=True):
            m = sintese.momento_atual(ficha_com(), [], [mov("2026-09-17", "Suspensos os honorários")], ProvedorFalso())
        self.assertEqual((m["momento"], m["qualificador"], m["origem"]), ("CUMPRIMENTO DE SENTENÇA", "HONORÁRIOS SUSPENSOS", "regra"))
        self.assertEqual(m["evidencia"], "17/09/2026: Suspensos os honorários")
        self.assertEqual(chamadas[0], [{"data": "2026-09-17", "texto": "Suspensos os honorários"}])

    def test_regra_fora_do_vocabulario_e_descartada(self):
        with mock.patch.object(taxonomia, "momento_por_regras", lambda mv: ("MOMENTO INVENTADO", "x"), create=True):
            m = sintese.momento_atual(ficha_com(), [], [mov("2026-09-17", "Algo")], None)
        self.assertIsNone(m["momento"])
        self.assertTrue(any("fora do vocabulário" in a for a in m["alertas"]))

    def test_nao_altera_a_ficha_nem_os_eventos(self):
        f = FICHAS[7]
        r = coleta(f)
        evs = eventos_da_coleta(f, r, com_texto=False)
        antes = copy.deepcopy((f, evs, r))
        sintese.momento_atual(f, evs, r["movimentos"], ProvedorFalso())
        self.assertEqual(antes, (f, evs, r))


class TestMomentoIA(unittest.TestCase):
    MOVS = [mov("2026-09-10", "Petição de manifestação sobre honorários suspensos até o trânsito"),
            mov("2026-09-12", "Movimento qualquer que nenhuma regra cobre")]

    def resposta(self, **dados):
        base = {"momento": "CUMPRIMENTO DE SENTENÇA", "qualificador": None,
                "trecho_origem": "Petição de manifestação sobre honorários suspensos"}
        base.update(dados)
        return lambda linhas: base

    def test_ia_responde_com_vocabulario_fechado_e_trecho_conferido(self):
        prov = ProvedorFalso(momento_ia=self.resposta(qualificador="honorários suspensos"))
        f = ficha_com(cliente="Cliente Exemplo 01 Ltda", polo_cliente="passivo")
        m = sintese.momento_atual(f, [], self.MOVS, prov)
        self.assertEqual((m["momento"], m["qualificador"], m["origem"], m["origem_ficha"], m["motor"]),
                         ("CUMPRIMENTO DE SENTENÇA", "HONORÁRIOS SUSPENSOS", "ia", "sugerido", "falso:teste"))
        self.assertIn("honorários suspensos", m["evidencia"])
        self.assertTrue(any("IA" in a for a in m["alertas"]), "momento de IA sempre pede conferência")
        self.assertEqual(len(prov.chamadas), 1)
        pedido = prov.chamadas[0]
        self.assertEqual(pedido["cliente"], "Cliente Exemplo 01 Ltda")
        enum = pedido["esquema"]["properties"]["momento"]["enum"]
        self.assertEqual(enum, [*taxonomia.MOMENTO_ATUAL, None], "esquema com o vocabulário fechado")
        for momento in taxonomia.MOMENTO_ATUAL:
            self.assertIn(f"- {momento}", pedido["usuario"])
        self.assertEqual(pedido["usuario"].index("12/09/2026") < pedido["usuario"].index("10/09/2026"), True,
                         "linhas da mais recente para a mais antiga")

    def test_resposta_so_em_texto_json_tambem_vale(self):
        m = sintese.momento_atual(ficha_com(), [], self.MOVS, ProvedorFalso(momento_ia=self.resposta(), texto_puro=True))
        self.assertEqual(m["momento"], "CUMPRIMENTO DE SENTENÇA")

    def test_aceita_o_momento_sem_acento_ou_caixa_mas_devolve_o_canonico(self):
        m = sintese.momento_atual(ficha_com(), [], self.MOVS,
                                  ProvedorFalso(momento_ia=self.resposta(momento="cumprimento de sentenca")))
        self.assertEqual(m["momento"], "CUMPRIMENTO DE SENTENÇA")

    def test_nunca_devolve_valor_fora_do_vocabulario(self):
        for invalido in ("AGUARDANDO ALGUMA COISA", "cumprimento", "AGUARDANDO", 42):
            m = sintese.momento_atual(ficha_com(), [], self.MOVS, ProvedorFalso(momento_ia=self.resposta(momento=invalido)))
            self.assertIsNone(m["momento"], invalido)
            self.assertIsNone(m["origem"])
            self.assertTrue(any("vocabulário" in a for a in m["alertas"]))

    def test_sem_evidencia_vira_none_e_alerta(self):
        casos = {"trecho vazio": {"trecho_origem": ""},
                 "trecho inventado": {"trecho_origem": "O juiz determinou o pagamento imediato da condenação"},
                 "trecho curto demais": {"trecho_origem": "Petição"},
                 "momento nulo": {"momento": None}}
        for nome, dados in casos.items():
            m = sintese.momento_atual(ficha_com(), [], self.MOVS, ProvedorFalso(momento_ia=self.resposta(**dados)))
            self.assertIsNone(m["momento"], nome)
            self.assertTrue(m["alertas"], nome)

    def test_qualificador_que_nao_consta_do_processo_e_descartado(self):
        m = sintese.momento_atual(ficha_com(), [], self.MOVS, ProvedorFalso(momento_ia=self.resposta(qualificador="DECISÃO FAVORÁVEL")))
        self.assertEqual(m["momento"], "CUMPRIMENTO DE SENTENÇA")
        self.assertIsNone(m["qualificador"])
        self.assertTrue(any("Qualificador" in a for a in m["alertas"]))

    def test_provedor_com_erro_ou_ausente_nao_derruba(self):
        m = sintese.momento_atual(ficha_com(), [], self.MOVS, ProvedorFalso(falhar=True))
        self.assertIsNone(m["momento"])
        self.assertTrue(any("ConnectionError" in a for a in m["alertas"]))
        m = sintese.momento_atual(ficha_com(), [], self.MOVS, None)
        self.assertIsNone(m["momento"])
        self.assertTrue(any("provedor" in a for a in m["alertas"]))
        m = sintese.momento_atual(ficha_com(), [], [], ProvedorFalso(momento_ia=self.resposta()))
        self.assertIsNone(m["momento"], "sem movimentos nem documentos não há o que perguntar")

    def test_ia_nao_e_chamada_quando_a_regra_responde(self):
        f = next(f for f in FICHAS if fch.obter(f, "momento_atual") == "TRÂNSITO EM JULGADO")
        prov = ProvedorFalso(momento_ia=self.resposta())
        m = sintese.momento_atual(f, [], coleta(f)["movimentos"], prov)
        self.assertEqual((m["momento"], m["origem"]), ("TRÂNSITO EM JULGADO", "regra"))
        self.assertEqual(prov.chamadas, [])

    def test_documentos_entram_nas_linhas_enviadas(self):
        evs = [evento_doc(1, "15/09/2026", "Sentença", conteudo="julgando procedente", trecho_origem="JULGO PROCEDENTE o pedido", frase="Foi proferida sentença.")]
        prov = ProvedorFalso(momento_ia=lambda linhas: {"momento": "TRÂNSITO EM JULGADO", "qualificador": None,
                                                         "trecho_origem": "Documento: Sentença"})
        m = sintese.momento_atual(ficha_com(), evs, [mov("2026-09-12", "Movimento qualquer que nenhuma regra cobre")], prov)
        self.assertEqual(m["momento"], "TRÂNSITO EM JULGADO")
        self.assertIn("Resumo: Foi proferida sentença. julgando procedente", prov.chamadas[0]["usuario"])

    def test_deterministico(self):
        a = sintese.momento_atual(ficha_com(), [], self.MOVS, ProvedorFalso(momento_ia=self.resposta()))
        b = sintese.momento_atual(ficha_com(), [], self.MOVS, ProvedorFalso(momento_ia=self.resposta()))
        self.assertEqual(a, b)


# ============================================================================================ último andamento

class TestUltimoAndamento(unittest.TestCase):
    def test_igual_ao_ultimo_andamento_das_fichas(self):
        for f in FICHAS[:80]:
            r = coleta(f)
            evs = eventos_da_coleta(f, r, com_texto=False)
            esperado = fch.obter(f, "ultimo_andamento")
            self.assertEqual(sintese.ultimo_andamento([], r["movimentos"]), esperado)
            self.assertEqual(sintese.ultimo_andamento(evs, []), esperado)
            self.assertEqual(sintese.ultimo_andamento(evs, r["movimentos"]), esperado)

    def test_maior_data_entre_movimentos_e_documentos(self):
        movs = [mov("2026-09-01", "Conclusos para despacho")]
        docs = [evento_doc(1, "05/09/2026", "Decisão")]
        self.assertEqual(sintese.ultimo_andamento(docs, movs), "2026-09-05")
        self.assertEqual(sintese.ultimo_andamento([], movs), "2026-09-01")

    def test_rotina_so_e_ignorada_se_houver_outro_relevante(self):
        movs = [mov("2026-09-01", "Conclusos para despacho"), mov("2026-09-20", "Expedida/certificada a comunicação eletrônica"),
                mov("2026-09-22", "Juntada de certidão de rotina")]
        self.assertEqual(sintese.ultimo_andamento([], movs), "2026-09-01")
        self.assertEqual(sintese.ultimo_andamento([], movs, ignorar_rotina=False), "2026-09-22")
        so_rotina = movs[1:]
        self.assertEqual(sintese.ultimo_andamento([], so_rotina), "2026-09-22", "só rotina: vale a mais recente")

    def test_criterio_de_rotina_configuravel(self):
        movs = [mov("2026-09-01", "Conclusos para despacho"), mov("2026-09-10", "Conclusos para julgamento")]
        self.assertEqual(sintese.ultimo_andamento([], movs, eh_rotina=lambda item: "julgamento" in item["texto"]), "2026-09-01")
        docs = [evento_doc(1, "05/09/2026", "Decisão")]
        vistos = []
        sintese.ultimo_andamento(docs, movs, eh_rotina=lambda item: vistos.append(item["tipo"]) or False)
        self.assertEqual(sorted(vistos), ["documento", "movimento", "movimento"])

    def test_datas_dos_eventos_em_varios_formatos(self):
        evs = [evento_mov(1, "", "Conclusos para decisão (31/08/2026 13:20:05)"),
               {**evento_mov(2, "", "Conclusos para despacho"), "data": None, "detectado_em": "2026-08-15T10:00:00"},
               evento_mov(3, "2026-08-20", "Conclusos para julgamento")]
        self.assertEqual(sintese.ultimo_andamento(evs, []), "2026-08-31")
        self.assertEqual(sintese.ultimo_andamento(evs[1:], []), "2026-08-20")
        self.assertEqual(sintese.ultimo_andamento(evs[1:2], []), "2026-08-15")

    def test_sem_nada_devolve_none(self):
        self.assertIsNone(sintese.ultimo_andamento([], []))
        self.assertIsNone(sintese.ultimo_andamento(None, None))


# ============================================================================================ narrativa inicial

def datas_do_texto(texto):
    return [f"{a}-{m}-{d}" for d, m, a in DATA_NO_TEXTO.findall(texto)]


class TestNarrativaInicial(unittest.TestCase):
    def setUp(self):
        self.f = next(f for f in FICHAS if fch.obter(f, "momento_atual") == "TRÂNSITO EM JULGADO" and f.get("linha_de_base") is None)
        self.r = coleta(self.f, "completo")
        self.evs = eventos_da_coleta(self.f, self.r)

    def test_estilo_cronologia_e_origem_de_cada_frase(self):
        det = sintese.detalhar_inicial(self.f, self.evs, "padrao", None)
        self.assertEqual(det["texto"], " ".join(fr["texto"] for fr in det["frases"]))
        self.assertTrue(det["texto"].startswith("Em "))
        for fr in det["frases"]:
            self.assertRegex(fr["texto"], r"^Em \d{2}/\d{2}/\d{4} ")
            self.assertTrue(fr["origem"].get("evento") or fr["origem"].get("campo"), "nenhuma frase sem origem")
            self.assertIn(fr["camada"], ("capa", "movimentos", "documentos"))
        datas = datas_do_texto(det["texto"])
        self.assertEqual(datas, sorted(datas), "ordem cronológica")
        ids = {e["id"] for e in self.evs}
        self.assertTrue({fr["origem"]["evento"] for fr in det["frases"] if "evento" in fr["origem"]} <= ids)

    def test_capa_so_com_campos_que_tem_origem(self):
        det = sintese.detalhar_inicial(self.f, self.evs, "rapido", None)
        capa = [fr for fr in det["frases"] if fr["camada"] == "capa"]
        self.assertTrue(capa)
        self.assertIn(fch.obter(self.f, "vara"), capa[0]["texto"])
        self.assertEqual(capa[0]["origem"]["campo"], "data_ajuizamento")
        sem_capa = ficha_com()
        det = sintese.detalhar_inicial(sem_capa, [], "padrao", None)
        self.assertEqual((det["texto"], det["frases"]), ("", []))
        self.assertTrue(det["alertas"])
        so_vara = sintese.narrativa_inicial(ficha_com(vara="2ª Vara Fictícia", municipio="Cidade Exemplo", uf="CE"), [], "rapido")
        self.assertEqual(so_vara, "A ação tramita perante a 2ª Vara Fictícia, em Cidade Exemplo/CE.")

    def test_distribuicao_nao_se_repete_com_a_capa(self):
        texto = sintese.narrativa_inicial(self.f, self.evs, "rapido")
        self.assertEqual(texto.count("foi distribuída"), 1)
        sem_capa = copy.deepcopy(self.f)
        sem_capa["campos"].pop("data_ajuizamento")
        self.assertIn("o processo foi distribuído.", sintese.narrativa_inicial(sem_capa, self.evs, "rapido"))

    def test_profundidades(self):
        rapido = sintese.detalhar_inicial(self.f, self.evs, "rapido", None)
        padrao = sintese.detalhar_inicial(self.f, copy.deepcopy(self.evs), "padrao", None)
        completo = sintese.detalhar_inicial(self.f, copy.deepcopy(self.evs), "completo", None)
        camadas = lambda d: [fr["camada"] for fr in d["frases"]]
        self.assertNotIn("documentos", camadas(rapido))
        self.assertIn("documentos", camadas(padrao))
        self.assertGreater(camadas(completo).count("documentos"), camadas(padrao).count("documentos"))
        self.assertGreaterEqual(len(completo["frases"]), len(padrao["frases"]))
        docs_padrao = {fr["origem"]["evento"] for fr in padrao["frases"] if fr["camada"] == "documentos"}
        por_id = {e["id"]: e for e in self.evs}
        for ident in docs_padrao:
            self.assertRegex(por_id[ident]["tipo"], r"(?i)inicial|senten|ac[oó]rd|decis")
        extras = {fr["origem"]["evento"] for fr in completo["frases"] if fr["camada"] == "documentos"} - docs_padrao
        self.assertTrue(extras and all(not re.search(r"(?i)senten|ac[oó]rd", por_id[i]["tipo"]) for i in extras))

    def test_profundidade_invalida(self):
        with self.assertRaises(ValueError):
            sintese.narrativa_inicial(self.f, self.evs, "profundo")

    def test_rotina_descartado_e_sem_traducao_nao_entram(self):
        evs = [evento_mov(1, "01/09/2026", "Expedida/certificada a comunicação eletrônica"),
               evento_mov(2, "02/09/2026", "Conclusos para julgamento"),
               evento_mov(3, "03/09/2026", "Conclusos para despacho", status="descartado"),
               evento_mov(4, "04/09/2026", "Movimento qualquer que nenhuma regra cobre"),
               evento_mov(5, "05/09/2026", "Juntada de certidão de rotina")]
        det = sintese.detalhar_inicial(ficha_com(), evs, "padrao")
        self.assertEqual(det["texto"], "Em 02/09/2026 o processo foi encaminhado para julgamento.")
        self.assertEqual(len(det["alertas"]), 1)
        self.assertIn("sem tradução", det["alertas"][0])

    def test_movimento_ja_revisado_entra_mesmo_que_a_regra_o_chame_de_rotina(self):
        ev = evento_mov(1, "02/09/2026", "Juntada de certidão de rotina", status="aprovado", frase="O cartório certificou o prazo.")
        self.assertEqual(sintese.narrativa_inicial(ficha_com(), [ev], "rapido"), "Em 02/09/2026 o cartório certificou o prazo.")

    def test_mesma_informacao_no_mesmo_dia_entra_uma_vez(self):
        evs = [evento_mov(1, "02/09/2026", "Conclusos para julgamento"), evento_mov(2, "02/09/2026", "Conclusos para julgamento")]
        self.assertEqual(sintese.narrativa_inicial(ficha_com(), evs, "rapido").count("encaminhado"), 1)

    def test_documento_cobre_o_andamento_que_o_anuncia(self):
        evs = [evento_mov(1, "02/09/2026", "Publicado Sentença em 02/09/2026."), evento_doc(2, "02/09/2026", "Sentença")]
        self.assertEqual(sintese.narrativa_inicial(ficha_com(), evs, "padrao"), "Em 02/09/2026 foi proferida sentença.")
        self.assertIn("publicada a sentença", sintese.narrativa_inicial(ficha_com(), evs, "rapido"))

    def test_voz_do_escritorio_e_da_parte_contraria(self):
        texto_nos = "EXCELENTÍSSIMO SENHOR JUIZ\nContestação da ré.\nAssinado eletronicamente por: Advogado Fictício - 01/09/2026"
        texto_outro = "EXCELENTÍSSIMO SENHOR JUIZ\nPedido do autor.\nAssinado eletronicamente por: Fulano Estranho - 01/09/2026"
        f = ficha_com(parte_contraria="PESSOA FICTICIA 0001")
        with mock.patch.object(traduzir, "config", return_value={"identificadores_escritorio": ["Advogado Fictício"]}):
            a = sintese.narrativa_inicial(f, [evento_doc(1, "01/09/2026", "Contestação", texto=texto_nos)], "completo")
            b = sintese.narrativa_inicial(f, [evento_doc(2, "01/09/2026", "Petição (outras)", texto=texto_outro)], "completo")
        self.assertEqual(a, "Em 01/09/2026 apresentamos contestação.")
        self.assertEqual(b, "Em 01/09/2026 a parte contrária (Pessoa Ficticia 0001) apresentou petição (outras).")

    def test_resumo_so_entra_com_trecho_que_confere(self):
        texto = "SENTENÇA\nAnte o exposto, JULGO PROCEDENTE o pedido formulado na inicial.\nPublique-se."
        bom = evento_doc(1, "01/09/2026", "Sentença", texto=texto, conteudo="julgando procedente o pedido da inicial",
                         trecho_origem="JULGO PROCEDENTE o pedido formulado na inicial", status="rascunho")
        ruim = evento_doc(2, "02/09/2026", "Sentença", texto=texto, conteudo="condenando a empresa em dez milhões",
                          trecho_origem="a empresa foi condenada em dez milhões de reais", status="rascunho")
        sem_trecho = evento_doc(3, "03/09/2026", "Sentença", texto=texto, conteudo="algo", trecho_origem="", status="rascunho")
        aprovado = evento_doc(4, "04/09/2026", "Sentença", texto=texto, conteudo="mantendo a decisão anterior",
                              trecho_origem="", status="aprovado")
        det = sintese.detalhar_inicial(ficha_com(), [bom, ruim, sem_trecho, aprovado], "padrao")
        self.assertEqual(
            det["texto"],
            "Em 01/09/2026 foi proferida sentença julgando procedente o pedido da inicial. "
            "Em 02/09/2026 foi proferida sentença. Em 03/09/2026 foi proferida sentença. "
            "Em 04/09/2026 foi proferida sentença mantendo a decisão anterior.")
        self.assertEqual(len(det["alertas"]), 2)
        self.assertNotIn("dez milhões", det["texto"])

    def test_resumo_pelo_provedor_com_motor_e_profundidade_gravados(self):
        docs = [e for e in self.evs if e["tipo_evento"] == "documento" and e["tipo"] == "Sentença"]
        self.assertTrue(docs)
        prov = ProvedorFalso(motor="local:falso")
        det = sintese.detalhar_inicial(self.f, self.evs, "padrao", prov)
        texto = det["texto"]
        self.assertRegex(texto, r"foi proferida sentença julgando (parcialmente )?(im)?procedentes? ")
        self.assertEqual(len(prov.chamadas), len([e for e in self.evs if e["tipo_evento"] == "documento" and sintese._documento_chave(e)]))
        for ev in docs:
            self.assertEqual((ev["motor"], ev["profundidade"]), ("local:falso", "padrao"))
            self.assertIn(ev["trecho_origem"], ev["texto"])
            self.assertIn("Resumo gerado pela IA na síntese: conferir na revisão.", ev["alertas"])
        usados = {fr["origem"]["evento"] for fr in det["frases"] if "evento" in fr["origem"]}
        for ev in self.evs:
            if ev["id"] in usados and ev["tipo_evento"] == "movimento":
                self.assertEqual((ev["motor"], ev["profundidade"]), ("regra", "padrao"))
            if ev["id"] not in usados:
                self.assertNotIn("profundidade", ev, "evento que não entrou não é marcado")

    def test_provedor_nao_e_chamado_no_rapido_nem_sem_texto(self):
        prov = ProvedorFalso()
        sintese.narrativa_inicial(self.f, copy.deepcopy(self.evs), "rapido", prov)
        self.assertEqual(prov.chamadas, [])
        sem_texto = eventos_da_coleta(self.f, self.r, com_texto=False)
        sintese.narrativa_inicial(self.f, sem_texto, "completo", prov)
        self.assertEqual(prov.chamadas, [], "sem texto do documento não há o que enviar")

    def test_resumo_inventado_pelo_provedor_e_descartado(self):
        evs = [evento_doc(1, "01/09/2026", "Sentença", texto="SENTENÇA\nAnte o exposto, JULGO PROCEDENTE o pedido da inicial.\n")]
        prov = ProvedorFalso(inventar_trecho=True)
        det = sintese.detalhar_inicial(ficha_com(), evs, "padrao", prov)
        self.assertEqual(det["texto"], "Em 01/09/2026 foi proferida sentença.")
        self.assertNotIn("conteudo", evs[0])
        self.assertTrue(any("descartado" in a for a in det["alertas"]))
        falha = sintese.detalhar_inicial(ficha_com(), [evento_doc(1, "01/09/2026", "Sentença", texto="SENTENÇA\nJULGO PROCEDENTE.")], "padrao",
                                         ProvedorFalso(falhar=True))
        self.assertEqual(falha["texto"], "Em 01/09/2026 foi proferida sentença.")
        self.assertTrue(any("ConnectionError" in a for a in falha["alertas"]))

    def test_deterministico_com_provedor_falso(self):
        a = sintese.narrativa_inicial(self.f, copy.deepcopy(self.evs), "completo", ProvedorFalso())
        b = sintese.narrativa_inicial(self.f, copy.deepcopy(self.evs), "completo", ProvedorFalso())
        self.assertEqual(a, b)
        c = sintese.narrativa_inicial(self.f, list(reversed(copy.deepcopy(self.evs))), "completo", ProvedorFalso())
        self.assertEqual(a, c, "a ordem de entrada dos eventos não muda o texto")

    def test_nao_altera_ficha_e_status_dos_eventos(self):
        antes = copy.deepcopy(self.f)
        sintese.narrativa_inicial(self.f, self.evs, "completo", ProvedorFalso())
        self.assertEqual(antes, self.f)
        self.assertTrue(all(e["status"] in ("coletado", "extraido") for e in self.evs))


class TestHistoricoMigrado(unittest.TestCase):
    BASE = ("Em 12/03/2026 foi distribuída a ação. Em 20/04/2026 foi apresentada contestação. "
            "Em 15/06/2026 foi proferida sentença julgando procedente o pedido.")

    def ficha(self):
        f = ficha_com(vara="1ª Vara Fictícia", data_ajuizamento="2026-03-12")
        f["linha_de_base"] = {"data_base": "2026-09-18", "andamentos_texto": self.BASE, "arquivo": "modelo.docx",
                              "ultimo_andamento": "2026-06-15"}
        return f

    def test_historico_fica_intacto_e_so_entra_o_posterior(self):
        f = self.ficha()
        antes = copy.deepcopy(f)
        evs = [evento_mov(1, "20/04/2026", "Juntada de Petição de contestação"),      # já consta da base
               evento_doc(2, "15/06/2026", "Sentença"),                               # já consta da base
               evento_mov(3, "30/09/2026", "Conclusos para julgamento")]               # novo
        det = sintese.detalhar_inicial(f, evs, "padrao")
        self.assertTrue(det["texto"].startswith(self.BASE), "o histórico migrado nunca é reescrito")
        self.assertEqual(det["texto"], self.BASE + " Em 30/09/2026 o processo foi encaminhado para julgamento.")
        self.assertEqual(f, antes)
        self.assertEqual(sorted(i["codigo"] for i in det["ignorados"]), ["andamento_ja_presente", "andamento_ja_presente"])
        self.assertNotIn("capa", [fr["camada"] for fr in det["frases"]], "a capa não se repete sobre histórico migrado")

    def test_sem_novidade_devolve_exatamente_o_historico(self):
        self.assertEqual(sintese.narrativa_inicial(self.ficha(), [], "completo"), self.BASE)


# ============================================================================================ narrativa incremental

class TestNarrativaIncremental(unittest.TestCase):
    def setUp(self):
        self.f = next(f for f in FICHAS if fch.obter(f, "momento_atual") == "AGUARDANDO SENTENÇA")
        self.evs = eventos_da_coleta(self.f, coleta(self.f, "completo"))

    def test_ciclo_sem_repetir_nada(self):
        f = copy.deepcopy(self.f)
        primeira = sintese.narrativa_incremental(f, self.evs)
        self.assertTrue(primeira.startswith("Em "))
        f["ultimo_texto_gravado"] = {"data_base": "2026-10-07", "texto": primeira, "arquivo": "a.docx"}
        det = sintese.detalhar_incremental(f, self.evs)
        self.assertEqual(det["texto"], "")
        self.assertEqual(len(det["ignorados"]), len(sintese.detalhar_incremental(copy.deepcopy(self.f), self.evs)["frases"]))
        self.assertEqual({i["codigo"] for i in det["ignorados"]}, {"andamento_ja_presente"})
        novo = evento_mov(99, "06/10/2026", "Conclusos para despacho")
        self.assertEqual(sintese.narrativa_incremental(f, self.evs + [novo]), "Em 06/10/2026 o processo foi encaminhado ao juiz para despacho.")

    def test_so_acrescenta_depois_do_ultimo_texto(self):
        f = ficha_com()
        f["ultimo_texto_gravado"] = {"data_base": "2026-09-30", "texto": "Em 10/09/2026 foi proferida sentença.", "arquivo": "a.docx"}
        evs = [evento_mov(1, "05/09/2026", "Conclusos para julgamento"),   # anterior ao texto e ausente dele
               evento_mov(2, "10/09/2026", "Suspenso o processo por decisão judicial"),  # mesmo dia, outro fato
               evento_mov(3, "11/09/2026", "Conclusos para despacho")]
        det = sintese.detalhar_incremental(f, evs)
        self.assertEqual(det["texto"], "Em 10/09/2026 o processo foi suspenso (decisão judicial). "
                                       "Em 11/09/2026 o processo foi encaminhado ao juiz para despacho.")
        self.assertEqual([i["codigo"] for i in det["ignorados"]], ["andamento_anterior_ao_texto"])
        self.assertIn("conferir à mão", det["ignorados"][0]["motivo"])

    def test_nao_repete_o_que_esta_na_linha_de_base(self):
        f = TestHistoricoMigrado().ficha()
        evs = [evento_mov(1, "20/04/2026", "Juntada de Petição de contestação"), evento_mov(2, "01/10/2026", "Conclusos para julgamento")]
        self.assertEqual(sintese.narrativa_incremental(f, evs), "Em 01/10/2026 o processo foi encaminhado para julgamento.")

    def test_fecho_do_texto_existente_nao_conta_como_andamento(self):
        for fecho in ("Em 30/09/2026, sem atualizações.", "Até 30/09/2026 sem atualizações."):
            f = ficha_com()
            f["ultimo_texto_gravado"] = {"data_base": "2026-09-30", "texto": f"Em 10/09/2026 foi proferida sentença. {fecho}", "arquivo": "a.docx"}
            texto = sintese.narrativa_incremental(f, [evento_mov(1, "25/09/2026", "Conclusos para julgamento")])
            self.assertEqual(texto, "Em 25/09/2026 o processo foi encaminhado para julgamento.", fecho)

    def test_reconhece_edicao_manual_e_data_por_extenso(self):
        f = ficha_com()
        f["ultimo_texto_gravado"] = {"data_base": "2026-10-07", "arquivo": "a.docx",
                                     "texto": "Em 10/09/2026 foi proferida sentença. No dia 6 de outubro de 2026 os autos foram "
                                              "encaminhados para julgamento pelo juiz."}
        evs = [evento_doc(1, "10/09/2026", "Sentença"), evento_mov(2, "06/10/2026", "Conclusos para julgamento")]
        self.assertEqual(sintese.narrativa_incremental(f, evs), "")

    def test_nao_altera_a_ficha_e_marca_os_eventos_usados(self):
        f = ficha_com()
        antes = copy.deepcopy(f)
        evs = [evento_mov(1, "25/09/2026", "Conclusos para julgamento"), evento_mov(2, "26/09/2026", "Juntada de certidão de rotina")]
        sintese.narrativa_incremental(f, evs)
        self.assertEqual(antes, f)
        self.assertEqual(evs[0]["motor"], "regra")
        self.assertNotIn("profundidade", evs[0])
        self.assertNotIn("motor", evs[1], "rotina não entrou, não é marcado")

    def test_sem_novidade_devolve_vazio(self):
        self.assertEqual(sintese.narrativa_incremental(ficha_com(), []), "")


# ============================================================================================ resumir (extensão)

class TestResumirComProvedor(unittest.TestCase):
    TEXTO = "SENTENÇA\nAnte o exposto, JULGO PROCEDENTE o pedido formulado na inicial, condenando a ré.\nPublique-se."
    CTX = {"cliente": "Cliente Exemplo 01 Ltda", "polo": "ativo", "contraria": "Empresa Fictícia 001 Ltda"}

    def test_forma_do_resultado_e_chamada_ao_provedor(self):
        prov = ProvedorFalso(motor="local:falso")
        res, alertas, motor = resumir.resumir_com_provedor(prov, self.TEXTO, "Sentença", "juizo", "Foi proferida sentença.", self.CTX, "Cliente Exemplo 01 Ltda")
        self.assertEqual(motor, "local:falso")
        self.assertEqual(set(res) >= {"conteudo", "trecho_origem", "prazo", "audiencia", "efeito"}, True)
        self.assertEqual(res["conteudo"], "julgando procedente o pedido da inicial")
        self.assertEqual(alertas, [])
        chamada = prov.chamadas[0]
        self.assertEqual((chamada["sistema"], chamada["esquema"], chamada["cliente"]), (resumir.SISTEMA, resumir.ESQUEMA, "Cliente Exemplo 01 Ltda"))
        self.assertIn("Tipo do documento: Sentença", chamada["usuario"])

    def test_trecho_inventado_vira_alerta(self):
        prov = ProvedorFalso(inventar_trecho=True)
        _, alertas, _ = resumir.resumir_com_provedor(prov, self.TEXTO, "Sentença", "juizo", "Foi proferida sentença.", self.CTX)
        self.assertTrue(any("trecho citado" in a for a in alertas))

    def test_pede_de_novo_se_nao_vier_em_gerundio(self):
        class Teimoso(ProvedorFalso):
            def gerar(self, sistema, usuario, *, esquema=None, cliente=""):
                r = super().gerar(sistema, usuario, esquema=esquema, cliente=cliente)
                if len(self.chamadas) == 1:
                    return {**r, "json": {**r["json"], "conteudo": "A sentença é favorável ao cliente"}}
                return r

        prov = Teimoso()
        res, _, _ = resumir.resumir_com_provedor(prov, self.TEXTO, "Sentença", "juizo", "Foi proferida sentença.", self.CTX)
        self.assertEqual(len(prov.chamadas), 2)
        self.assertIn("gerúndio", prov.chamadas[1]["usuario"])
        self.assertTrue(res["conteudo"].startswith("julgando"))

    def test_resposta_invalida_levanta_value_error(self):
        class Ruim:
            def gerar(self, *a, **k):
                return {"texto": "isto não é json", "json": None, "motor": "x"}

        with self.assertRaises(ValueError):
            resumir.resumir_com_provedor(Ruim(), self.TEXTO, "Sentença", "juizo", "Foi proferida sentença.", self.CTX)

    def test_fluxo_antigo_continua_com_a_mesma_assinatura(self):
        self.assertTrue(callable(resumir.resumir_texto) and callable(resumir.processar_documento))
        self.assertEqual(resumir.limpar_conteudo("O juiz julga procedente o pedido."), "julgando procedente o pedido")


# ============================================================================================ escala

class TestEscala(unittest.TestCase):
    def test_200_processos_em_todas_as_profundidades(self):
        for f in FICHAS:
            r = coleta(f, "completo")
            evs = eventos_da_coleta(f, r)
            ids = {e["id"] for e in evs}
            for prof in sintese.PROFUNDIDADES:
                det = sintese.detalhar_inicial(f, copy.deepcopy(evs), prof, ProvedorFalso())
                self.assertEqual(det["texto"], " ".join(fr["texto"] for fr in det["frases"]))
                for fr in det["frases"]:
                    self.assertTrue(fr["origem"].get("campo") or fr["origem"].get("evento") in ids)
                datas = datas_do_texto(det["texto"])
                self.assertEqual(datas, sorted(datas), f["numero"])
            self.assertIn(sintese.momento_atual(f, evs, r["movimentos"], ProvedorFalso())["momento"], [None, *taxonomia.MOMENTO_ATUAL])
            self.assertEqual(sintese.ultimo_andamento(evs, r["movimentos"]), fch.obter(f, "ultimo_andamento"))

    def test_nenhum_numero_de_processo_real_nos_textos(self):
        f = FICHAS[0]
        evs = eventos_da_coleta(f, coleta(f, "completo"))
        texto = sintese.narrativa_inicial(f, evs, "completo")
        self.assertNotRegex(texto, r"\d{7}-\d{2}\.\d{4}")


if __name__ == "__main__":
    unittest.main()
