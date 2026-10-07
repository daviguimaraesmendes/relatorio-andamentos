"""Taxonomia (WS-1): vocabulários ampliados, normalização, momento atual com qualificador, sinônimos por
projeto e momento atual por regra. Só dados fictícios (números sintéticos; movimentos inventados)."""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: F401  (aponta comum.py para uma pasta temporária)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import comum  # noqa: E402
import ficha  # noqa: E402
import simulado  # noqa: E402
import taxonomia  # noqa: E402
import ficticio  # noqa: E402

# Valores canônicos que já existiam no fim da Etapa 0: nenhum pode sumir (CONTRATOS, seção 2).
CANONICOS_ORIGINAIS = {
    "polo": {"ativo", "passivo"},
    "situacao": {"Ativo", "Encerrado", "Suspenso"},
    "fase": {"Conhecimento", "Recurso", "Execução"},
    "resultado": {"Procedente", "Parcialmente procedente", "Improcedente", "Acordo", "Extinto sem resolução de mérito",
                  "Arquivado / desistência", "Incompetência declarada"},
    "probabilidade": {"Possível", "Provável", "Remota"},
    "area": {"Trabalhista", "Cível", "Consumidor", "Tributário", "Administrativo", "Ambiental", "Empresarial",
             "Imobiliário", "Contratual", "Processual", "Previdenciário"},
    "tipo_vinculo": {"recurso", "agravo", "apenso", "reajuizamento", "mesma_acao"},
    "momento_atual": {
        "AGUARDANDO CITAÇÃO", "AGUARDANDO CITAÇÃO DO RÉU", "AGUARDANDO CITAÇÃO DOS EXECUTADOS",
        "AGUARDANDO CITAÇÃO POR EDITAL", "AGUARDANDO INTIMAÇÃO DO RÉU", "AGUARDANDO CONTESTAÇÃO", "AGUARDANDO RÉPLICA",
        "AGUARDANDO AUDIÊNCIA", "AGUARDANDO PROVA PERICIAL", "AGUARDANDO SENTENÇA", "AGUARDANDO JULGAMENTO EM 1º GRAU",
        "AGUARDANDO JULGAMENTO", "CONCLUSOS PARA DECISÃO", "AGUARDANDO JULGAMENTO DA APELAÇÃO",
        "AGUARDANDO JULGAMENTO DO RECURSO", "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO", "CUMPRIMENTO DE SENTENÇA",
        "AGUARDANDO CONVERSÃO EM PENHORA", "AGUARDANDO PAGAMENTO", "AGUARDANDO PARCELAMENTO DAS CUSTAS",
        "AGUARDANDO MANIFESTAÇÃO DE TERCEIROS", "AGUARDANDO SUBSTITUIÇÃO PROCESSUAL", "SUSPENSO", "TRÂNSITO EM JULGADO",
        "PROCESSO ARQUIVADO", "ACORDO HOMOLOGADO", "EXTINTO SEM RESOLUÇÃO DE MÉRITO"},
    "materia": {
        "Horas extras e reflexos", "Intervalo intra/interjornada", "Repouso semanal / feriados", "Adicional noturno",
        "Tempo de espera", "Controle de jornada", "Adicional de insalubridade", "Adicional de periculosidade",
        "Dano material / pensionamento", "Dano estético", "Doença ocupacional / acidente (declaratório)",
        "Estabilidade (indenização)", "Limbo previdenciário", "Salário-maternidade (indenização)",
        "Acúmulo / desvio de função", "Dano moral", "Honorários advocatícios",
        "Encargos (INSS/IR/custas) no valor da causa", "Consignação de verbas rescisórias", "Outros"},
}


class TestVocabularios(unittest.TestCase):
    def test_nenhum_valor_canonico_sumiu(self):
        for nome, originais in CANONICOS_ORIGINAIS.items():
            self.assertLessEqual(originais, set(taxonomia.VOCABULARIOS[nome]), nome)

    def test_matéria_ampliada_com_trabalhistas_e_civeis(self):
        novas = {"Reversão de justa causa", "Verbas rescisórias", "Multa do art. 467 da CLT",
                 "Multa do art. 477 da CLT", "Reconhecimento de vínculo empregatício", "Assédio moral",
                 "Cobrança / inadimplemento contratual", "Indenização por danos materiais", "Repetição de indébito"}
        self.assertLessEqual(novas, set(taxonomia.MATERIA))
        for valor in taxonomia.MATERIA.values():
            self.assertEqual(len(valor), 3)
            self.assertIn(valor[1], ("Mérito", "Processual", "Acessório"))
        self.assertIn("Reversão de justa causa", taxonomia.materias_da_area("Trabalhista"))
        self.assertNotIn("Reversão de justa causa", taxonomia.materias_da_area("Cível"))
        self.assertIn("Cobrança / inadimplemento contratual", taxonomia.materias_da_area("Cível"))
        self.assertIn("Outros", taxonomia.materias_da_area("Cível"))

    def test_cada_forma_pertence_a_um_unico_valor_e_normaliza_para_ele(self):
        for nome, vocabulario in taxonomia.VOCABULARIOS.items():
            dono = {}
            for canonico, sinonimos in vocabulario.items():
                for forma in (canonico, *sinonimos):
                    chave = taxonomia._chave(forma)
                    self.assertTrue(chave, f"{nome}: forma vazia em {canonico}")
                    self.assertEqual(dono.setdefault(chave, canonico), canonico,
                                     f"{nome}: {forma!r} pertence a dois valores")
                    self.assertEqual(taxonomia.normalizar(nome, forma), canonico, f"{nome}: {forma!r}")

    def test_sinonimos_so_de_valores_existentes(self):
        self.assertLessEqual(set(taxonomia.MATERIA_SINONIMOS), set(taxonomia.MATERIA))
        self.assertLessEqual(set(taxonomia.MOMENTO_SINONIMOS), set(taxonomia.MOMENTO_ATUAL))

    def test_momentos_novos_tem_categoria_conhecida(self):
        for momento, (categoria, ativo) in taxonomia.MOMENTO_ATUAL.items():
            self.assertIn(categoria, ("conhecimento", "recurso", "execução", "suspenso", "encerrado"), momento)
            self.assertEqual(ativo, categoria != "encerrado", momento)


class TestNormalizar(unittest.TestCase):
    def test_materias_soltas(self):
        casos = {"Reversão Justa Causa": "Reversão de justa causa", "Reversão da justa causa.": "Reversão de justa causa",
                 "REVERSÃO DA JUSTA CAUSA": "Reversão de justa causa", "Horas extras": "Horas extras e reflexos",
                 "HORAS EXTRAS E REFLEXOS": "Horas extras e reflexos", "Adicional Insalubridade": "Adicional de insalubridade",
                 "Danos morais.": "Dano moral", "Indenização por dano moral": "Dano moral", "assédio": "Assédio moral",
                 "Multa do art 477": "Multa do art. 477 da CLT", "multa do art. 467 da CLT": "Multa do art. 467 da CLT",
                 "Verbas Rescisórias": "Verbas rescisórias", "Pagamento de verbas rescisórias": "Verbas rescisórias",
                 "Consignação de verbas rescisórias": "Consignação de verbas rescisórias",
                 "intervalo intrajornada": "Intervalo intra/interjornada", "Intervalo intra / interjornada": "Intervalo intra/interjornada",
                 "Salario maternidade": "Salário-maternidade (indenização)", "FGTS + 40%": "FGTS e multa de 40%",
                 "Cobrança": "Cobrança / inadimplemento contratual", "Danos materiais": "Indenização por danos materiais",
                 "Repetição do indébito": "Repetição de indébito", "13º salário": "Férias e 13º salário"}
        for texto, esperado in casos.items():
            self.assertEqual(taxonomia.normalizar("materia", texto), esperado, texto)

    def test_ambiguo_curto_ou_desconhecido_vira_none(self):
        for texto in ("Horas extras e dano moral", "qualquer coisa", "", None, "he", "assédio e justa causa"):
            self.assertIsNone(taxonomia.normalizar("materia", texto), texto)
        self.assertIsNone(taxonomia.normalizar("resultado", "qualquer coisa"))

    def test_frases_com_forma_dentro_de_outra_valem_pela_maior(self):
        n = taxonomia.normalizar
        self.assertEqual(n("resultado", "Julgado improcedente o pedido inicial"), "Improcedente")
        self.assertEqual(n("resultado", "sentença: parcialmente procedente"), "Parcialmente procedente")
        self.assertEqual(n("resultado", "Procedente"), "Procedente")

    def test_resultados_areas_situacoes(self):
        n = taxonomia.normalizar
        self.assertEqual(n("resultado", "Procedente em parte."), "Parcialmente procedente")
        self.assertEqual(n("resultado", "Homologada a desistência"), "Arquivado / desistência")
        self.assertEqual(n("resultado", "Extinto sem julgamento do mérito"), "Extinto sem resolução de mérito")
        self.assertEqual(n("resultado", "Declinada a competência"), None)  # não é sinônimo: nunca adivinha
        self.assertEqual(n("resultado", "Declínio de competência"), "Incompetência declarada")
        self.assertEqual(n("area", "Justiça do Trabalho"), "Trabalhista")
        self.assertEqual(n("area", "Direito Civil"), "Cível")
        self.assertEqual(n("situacao", "Em tramitação"), "Ativo")
        self.assertEqual(n("situacao", "Arquivada"), "Encerrado")
        self.assertEqual(n("fase", "Fase de cumprimento"), "Execução")
        self.assertEqual(n("polo", "Reclamada"), "passivo")
        self.assertEqual(n("polo", "Autor(a)"), "ativo")
        self.assertEqual(n("tipo_vinculo", "Agravo de instrumento"), "agravo")
        self.assertEqual(n("tipo_vinculo", "Embargos à execução"), "apenso")

    def test_rotulos_do_gabarito_de_defeitos(self):
        """Os rótulos soltos de matéria que o gerador de defeitos produz normalizam para a mesma matéria."""
        sujas = ficticio.gerar_carteira(200, com_defeitos=True)
        pares = sujas.defeitos["materia_dois_rotulos"]
        self.assertTrue(pares)
        por_numero = {f["numero"]: f for f in sujas}
        for a, b in pares:
            ra, rb = (ficha.obter(por_numero[x], "materia_principal") for x in (a, b))
            self.assertNotEqual(ra, rb)
            self.assertIsNotNone(taxonomia.normalizar("materia", ra))
            self.assertEqual(taxonomia.normalizar("materia", ra), taxonomia.normalizar("materia", rb))

    def test_sugerir_para_rotulo_desconhecido(self):
        sugestoes = taxonomia.sugerir("materia", "Reversao de justa-causa por abandono")
        self.assertIn("Reversão de justa causa", sugestoes)
        self.assertEqual(taxonomia.sugerir("materia", ""), [])
        self.assertEqual(taxonomia.sugerir("resultado", "Parcialmente procedent")[0], "Parcialmente procedente")


class TestMomentoComQualificador(unittest.TestCase):
    def test_qualificador_entre_parenteses(self):
        n = taxonomia.normalizar_momento
        self.assertEqual(n("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)"), ("CUMPRIMENTO DE SENTENÇA", "HONORÁRIOS SUSPENSOS"))
        self.assertEqual(n("PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)"), ("PROCESSO ARQUIVADO", "DECISÃO FAVORÁVEL"))
        self.assertEqual(n("AGUARDANDO SENTENÇA"), ("AGUARDANDO SENTENÇA", None))
        self.assertEqual(n("aguardando sentença (conclusos desde 10/09)"), ("AGUARDANDO SENTENÇA", "CONCLUSOS DESDE 10/09"))
        self.assertEqual(n("Cumprimento de sentença ( honorários   suspensos ) ."), ("CUMPRIMENTO DE SENTENÇA", "HONORÁRIOS SUSPENSOS"))
        self.assertEqual(n("INVENTADO (ALGO)"), (None, None))
        self.assertEqual(n(""), (None, None))
        self.assertEqual(n("CUMPRIMENTO DE SENTENÇA ()"), ("CUMPRIMENTO DE SENTENÇA", None))

    def test_formatar_e_ida_e_volta(self):
        self.assertEqual(taxonomia.formatar_momento("CUMPRIMENTO DE SENTENÇA", "honorários suspensos"),
                         "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)")
        self.assertEqual(taxonomia.formatar_momento("SUSPENSO"), "SUSPENSO")
        self.assertEqual(taxonomia.formatar_momento(None, "X"), "")
        for texto in ("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)", "AGUARDANDO SENTENÇA"):
            self.assertEqual(taxonomia.formatar_momento(*taxonomia.normalizar_momento(texto)), texto)

    def test_qualificador_nao_atrapalha_a_normalizacao_nem_a_ficha(self):
        # 'suspensos' dentro do qualificador não pode transformar o rótulo em ambíguo (SUSPENSO)
        self.assertEqual(taxonomia.normalizar("momento_atual", "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)"),
                         "CUMPRIMENTO DE SENTENÇA")
        f = ficha.nova_ficha(ficticio.numero_ficticio(0))
        self.assertTrue(ficha.definir(f, "momento_atual", "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)", "migrado"))
        self.assertEqual(ficha.obter(f, "momento_atual"), "CUMPRIMENTO DE SENTENÇA")

    def test_ativo_e_categoria_aceitam_qualificador(self):
        self.assertTrue(taxonomia.momento_ativo("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)"))
        self.assertFalse(taxonomia.momento_ativo("PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)"))
        self.assertEqual(taxonomia.categoria_do_momento("PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)"), "encerrado")
        self.assertIsNone(taxonomia.momento_ativo("INVENTADO (X)"))

    def test_sinonimos_de_momento(self):
        n = taxonomia.normalizar
        self.assertEqual(n("momento_atual", "Conclusos para sentença"), "AGUARDANDO SENTENÇA")
        self.assertEqual(n("momento_atual", "Transitado em julgado"), "TRÂNSITO EM JULGADO")
        self.assertEqual(n("momento_atual", "Em cumprimento de sentença"), "CUMPRIMENTO DE SENTENÇA")
        self.assertEqual(n("momento_atual", "arquivado definitivamente"), "PROCESSO ARQUIVADO")
        self.assertEqual(n("momento_atual", "Aguardando pagamento do acordo"), "AGUARDANDO PAGAMENTO")
        self.assertIsNone(n("momento_atual", "Aguardando"))


class TestSobreposicaoPorProjeto(unittest.TestCase):
    def tearDown(self):
        taxonomia.carregar(None)
        ficticio.restaurar_comum()

    def _projeto(self):
        proj = ficticio.criar_projeto_de_teste([], nome="Projeto Taxonomia")
        taxonomia.carregar(None)
        return proj

    def test_sem_arquivo_nada_muda(self):
        self._projeto()
        self.assertEqual(taxonomia.carregar(), {})
        self.assertIsNone(taxonomia.normalizar("materia", "abalo moral"))

    def test_adicionar_grava_e_vale_na_hora(self):
        proj = self._projeto()
        self.assertIsNone(taxonomia.normalizar("materia", "abalo moral"))
        r = taxonomia.adicionar_sinonimo("materia", "Dano moral", "Abalo moral")
        self.assertEqual(r, {"adicionado": True, "aviso": None})
        self.assertEqual(taxonomia.normalizar("materia", "abalo moral."), "Dano moral")
        arquivo = proj["pasta"] / "taxonomia.json"
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        self.assertEqual(dados["versao"], 1)
        self.assertEqual(dados["sinonimos"]["materia"]["Dano moral"], ["Abalo moral"])
        self.assertEqual(taxonomia.carregar(proj["slug"]), {"materia": {"Dano moral": ["Abalo moral"]}})
        # momento atual também
        self.assertTrue(taxonomia.adicionar_sinonimo("momento_atual", "AGUARDANDO SENTENÇA", "fase de sentença")["adicionado"])
        self.assertEqual(taxonomia.normalizar("momento_atual", "Fase de sentença (prazo vencido)"), "AGUARDANDO SENTENÇA")
        # a ficha passa a aceitar o rótulo do relatório
        f = ficha.nova_ficha(ficticio.numero_ficticio(1))
        self.assertTrue(ficha.definir(f, "momento_atual", "fase de sentença", "migrado"))

    def test_recusas_com_aviso_de_codigo_estavel(self):
        self._projeto()
        r = taxonomia.adicionar_sinonimo("materia", "Dano moral", "horas extras")  # já é de OUTRA matéria
        self.assertFalse(r["adicionado"])
        self.assertEqual(r["aviso"]["codigo"], "sinonimo_em_conflito")
        self.assertEqual(r["aviso"]["candidatos"], ["Horas extras e reflexos"])
        self.assertEqual(taxonomia.adicionar_sinonimo("materia", "Dano moral", "danos morais")["aviso"]["codigo"],
                         "sinonimo_ja_existe")
        self.assertEqual(taxonomia.adicionar_sinonimo("materia", "Não existe", "x")["aviso"]["codigo"], "canonico_desconhecido")
        self.assertEqual(taxonomia.adicionar_sinonimo("inventado", "Dano moral", "x")["aviso"]["codigo"], "vocabulario_desconhecido")
        self.assertEqual(taxonomia.adicionar_sinonimo("materia", "Dano moral", " . ")["aviso"]["codigo"], "sinonimo_vazio")
        taxonomia.adicionar_sinonimo("materia", "Dano moral", "abalo moral")
        self.assertEqual(taxonomia.adicionar_sinonimo("materia", "Dano moral", "Abalo Moral")["aviso"]["codigo"],
                         "sinonimo_ja_existe")
        # o mesmo sinônimo novo para outro valor também conflita (já está na sobreposição)
        self.assertEqual(taxonomia.adicionar_sinonimo("materia", "Assédio moral", "abalo moral")["aviso"]["codigo"],
                         "sinonimo_em_conflito")

    def test_sem_projeto_devolve_aviso(self):
        taxonomia.carregar(None)
        ficticio.restaurar_comum()
        self.assertIsNone(comum.PROJETO)
        r = taxonomia.adicionar_sinonimo("materia", "Dano moral", "abalo moral")
        self.assertEqual(r["aviso"]["codigo"], "sem_projeto")

    def test_arquivo_ilegivel_nunca_e_sobrescrito(self):
        proj = self._projeto()
        arquivo = proj["pasta"] / "taxonomia.json"
        arquivo.write_text("{isto não é json", encoding="utf-8")
        self.assertEqual(taxonomia.carregar(), {})
        self.assertEqual(taxonomia.avisos_de_sobreposicao()[0]["codigo"], "taxonomia_ilegivel")
        self.assertEqual(taxonomia.adicionar_sinonimo("materia", "Dano moral", "abalo moral")["aviso"]["codigo"], "taxonomia_ilegivel")
        self.assertEqual(arquivo.read_text(encoding="utf-8"), "{isto não é json")
        self.assertEqual(taxonomia.normalizar("materia", "danos morais"), "Dano moral")  # a base continua valendo

    def test_edicao_manual_e_entradas_invalidas(self):
        proj = self._projeto()
        arquivo = proj["pasta"] / "taxonomia.json"
        comum.save_json(arquivo, {"versao": 1, "sinonimos": {
            "materia": {"Dano moral": ["abalo moral"], "Inventada": ["x"]}, "inventado": {"a": ["b"]}}})
        self.assertEqual(taxonomia.normalizar("materia", "abalo moral"), "Dano moral")  # relê o arquivo sozinho
        codigos = {a["codigo"] for a in taxonomia.avisos_de_sobreposicao()}
        self.assertEqual(codigos, {"sinonimo_de_valor_desconhecido", "sinonimo_de_vocabulario_desconhecido"})

    def test_remover(self):
        self._projeto()
        taxonomia.adicionar_sinonimo("materia", "Dano moral", "abalo moral")
        self.assertTrue(taxonomia.remover_sinonimo("materia", "Dano moral", "Abalo moral")["removido"])
        self.assertIsNone(taxonomia.normalizar("materia", "abalo moral"))
        self.assertEqual(taxonomia.remover_sinonimo("materia", "Dano moral", "abalo moral")["aviso"]["codigo"],
                         "sinonimo_inexistente")
        self.assertFalse(taxonomia.remover_sinonimo("materia", "Dano moral", "danos morais")["removido"])  # da base

    def test_sobreposicao_e_do_projeto(self):
        proj_a = self._projeto()
        taxonomia.adicionar_sinonimo("materia", "Dano moral", "abalo moral")
        outro = comum.criar_projeto("Outro Projeto")
        comum.usar_projeto(outro)           # o relatório ativo mudou: a sobreposição acompanha
        self.assertIsNone(taxonomia.normalizar("materia", "abalo moral"))
        comum.usar_projeto(proj_a["slug"])
        self.assertEqual(taxonomia.normalizar("materia", "abalo moral"), "Dano moral")
        self.assertEqual(taxonomia.carregar(outro), {})  # fixar outro slug explicitamente
        self.assertIsNone(taxonomia.normalizar("materia", "abalo moral"))


MOV = lambda texto, data=None, grau=None: {"data": data, "texto": texto, "grau": grau, "chave": f"{data}|{texto}|1"}


def _seq(*textos):
    """Movimentos em ordem cronológica, um por dia."""
    return [MOV(t, f"2026-03-{i + 1:02d}") for i, t in enumerate(textos)]


class TestMomentoPorRegras(unittest.TestCase):
    def momento(self, *textos):
        return taxonomia.momento_por_regras(_seq(*textos))[0]

    def test_tabela_de_casos(self):
        casos = [
            (("Conclusos para julgamento",), "AGUARDANDO SENTENÇA"),
            (("Conclusos para sentença",), "AGUARDANDO SENTENÇA"),
            (("Conclusos para julgamento", "Juntada de Petição de manifestação"), "AGUARDANDO SENTENÇA"),
            (("Conclusos para julgamento", "Proferido despacho de mero expediente"), "AGUARDANDO SENTENÇA"),
            (("Conclusos para despacho",), "AGUARDANDO DESPACHO"),
            (("Conclusos para decisão",), "CONCLUSOS PARA DECISÃO"),
            (("Distribuído por sorteio", "Conclusos para despacho", "Proferido despacho de mero expediente"),
             "AGUARDANDO CITAÇÃO"),
            (("Conclusos para decisão", "Deferida a tutela de urgência"), None),            # nada antes: sem como saber
            (("Expedido(a) citação a(o) EMPRESA", "Conclusos para decisão", "Deferida a tutela de urgência",
              "Publicado Decisão em 10/03/2026."), "AGUARDANDO CITAÇÃO"),
            (("Expedido(a) citação a(o) EMPRESA",), "AGUARDANDO CITAÇÃO"),
            (("Expedido(a) citação a(o) EMPRESA", "Juntada de certidão de citação"), "AGUARDANDO CONTESTAÇÃO"),
            (("Expedido(a) citação a(o) EMPRESA", "Juntada de certidão de citação negativa"), "AGUARDANDO CITAÇÃO"),
            (("Edital de citação publicado",), "AGUARDANDO CITAÇÃO POR EDITAL"),
            (("Juntada de Petição de contestação", "Decorrido o prazo de FULANO"), "AGUARDANDO RÉPLICA"),
            (("Juntada de Petição de contestação", "Juntada de Petição de réplica"), None),
            (("Audiência de conciliação designada (12/11/2026 09:00:00)", "Expedida/certificada a comunicação eletrônica"),
             "AGUARDANDO AUDIÊNCIA"),
            (("Audiência de instrução realizada (12/11/2026 10:00:00)",), None),
            (("Audiência de conciliação designada (12/11/2026 09:00:00)", "Audiência de conciliação cancelada (12/11/2026 09:00:00)"), None),
            (("Conclusos para decisão", "Deferido o pedido de prova pericial"), "AGUARDANDO PROVA PERICIAL"),
            (("Juntada de Petição de apelação", "Remetidos os Autos (em grau de recurso) ao Tribunal"),
             "AGUARDANDO JULGAMENTO DA APELAÇÃO"),
            (("Juntada de Petição de recurso ordinário", "Remetidos os Autos (em grau de recurso) ao Tribunal"),
             "AGUARDANDO JULGAMENTO DO RECURSO ORDINÁRIO"),
            (("Remetidos os Autos (em grau de recurso)",), "AGUARDANDO JULGAMENTO DO RECURSO"),
            (("Distribuído recurso à 2ª Câmara",), "AGUARDANDO JULGAMENTO DO RECURSO"),
            (("Julgado improcedente o pedido", "Juntada de Petição de apelação"), "AGUARDANDO JULGAMENTO DA APELAÇÃO"),
            (("Juntada de Petição de agravo de instrumento",), None),                       # neutro para o principal
            (("Distribuído agravo de instrumento",), "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO"),
            (("Juntada de Petição de embargos de declaração",), "AGUARDANDO JULGAMENTO DOS EMBARGOS DE DECLARAÇÃO"),
            (("Deliberado em Sessão - Julgado", "Publicado Acórdão em 10/03/2026."), "AGUARDANDO PRAZO RECURSAL"),
            (("Remetidos os Autos (em grau de recurso)", "Deliberado em Sessão - Retirado"), "AGUARDANDO JULGAMENTO DO RECURSO"),
            (("Julgado procedente o pedido", "Publicado Sentença em 10/03/2026."), "AGUARDANDO PRAZO RECURSAL"),
            (("Publicado Sentença em 10/03/2026.",), "AGUARDANDO PRAZO RECURSAL"),
            (("Audiência de conciliação realizada (10/03/2026 09:00:00)", "Homologado o acordo entre as partes",
              "Publicado Sentença em 10/03/2026."), "ACORDO HOMOLOGADO"),
            (("Conclusos para julgamento", "Extinto o processo sem resolução do mérito", "Publicado Sentença em 10/03/2026."),
             "EXTINTO SEM RESOLUÇÃO DE MÉRITO"),
            (("Homologada a desistência da ação",), "EXTINTO SEM RESOLUÇÃO DE MÉRITO"),
            (("Declarada a incompetência do juízo",), "REMETIDO AO JUÍZO COMPETENTE"),
            (("Extinto o processo por pagamento",), None),
            (("Certidão de trânsito em julgado",), "TRÂNSITO EM JULGADO"),
            (("Transitado em julgado", "Expedida/certificada a comunicação eletrônica"), "TRÂNSITO EM JULGADO"),
            (("Transitado em julgado", "Arquivado Definitivamente"), "PROCESSO ARQUIVADO"),
            (("Arquivado Definitivamente", "Desarquivado"), None),
            (("Transitado em julgado", "Desarquivado", "Juntada de Petição de cumprimento de sentença"), "CUMPRIMENTO DE SENTENÇA"),
            (("Arquivado Provisoriamente",), None),
            (("Juntada de Petição de cumprimento de sentença", "Conclusos para decisão", "Publicado Decisão em 10/03/2026."),
             "CUMPRIMENTO DE SENTENÇA"),
            (("Homologados os cálculos",), "CUMPRIMENTO DE SENTENÇA"),
            (("Início da liquidação de sentença",), "LIQUIDAÇÃO DE SENTENÇA"),
            (("Processo suspenso em razão de expedição de precatório",), "AGUARDANDO PAGAMENTO DE PRECATÓRIO"),
            (("Suspenso o processo por decisão judicial",), "SUSPENSO"),
            (("Suspenso o processo por decisão judicial", "Levantada a suspensão"), None),
            (("Recebidos os autos do CEJUSC",), None),
            (("Remetidos os Autos (outros motivos) para Gabinete",), None),
            (("Movimentação inventada sem regra nenhuma",), None),
            (("Juntada de Petição de contestação", "Movimentação inventada sem regra nenhuma"), None),
            ((), None),
        ]
        for textos, esperado in casos:
            self.assertEqual(self.momento(*textos), esperado, textos)

    def test_o_resultado_sempre_esta_no_vocabulario_e_toda_regra_aponta_para_valor_valido(self):
        for nome, _padrao, efeito, destino in taxonomia.REGRAS_DE_MOMENTO:
            self.assertIn(efeito, ("estado", "ruido", "decisao", "parar", "conclusos", "julgamento", "sentenca_publicada",
                                   "recurso"), nome)
            if efeito in ("estado", "conclusos", "julgamento"):
                self.assertIn(destino, taxonomia.MOMENTO_ATUAL, nome)
        for _padrao, momento in taxonomia._TIPOS_DE_RECURSO:
            self.assertIn(momento, taxonomia.MOMENTO_ATUAL)
        self.assertIn(taxonomia._RECURSO_GENERICO, taxonomia.MOMENTO_ATUAL)
        self.assertEqual(len({r[0] for r in taxonomia.REGRAS_DE_MOMENTO}), len(taxonomia.REGRAS_DE_MOMENTO))  # nomes únicos

    def test_evidencia_traz_data_movimento_e_regra(self):
        momento, evidencia = taxonomia.momento_por_regras([MOV("Conclusos para julgamento", "2026-05-05")])
        self.assertEqual(momento, "AGUARDANDO SENTENÇA")
        self.assertIn("05/05/2026", evidencia)
        self.assertIn("Conclusos para julgamento", evidencia)
        self.assertIn("conclusos_julgamento", evidencia)
        self.assertEqual(taxonomia.momento_por_regras([]), (None, None))
        self.assertEqual(taxonomia.momento_por_regras(None), (None, None))

    def test_ordena_por_data_e_aceita_texto_puro(self):
        movs = [MOV("Juntada de Petição de manifestação", "2026-05-09"), MOV("Conclusos para julgamento", "2026-05-01"),
                MOV("Transitado em julgado", "2026-05-20")]
        self.assertEqual(taxonomia.momento_por_regras(movs)[0], "TRÂNSITO EM JULGADO")      # fora de ordem
        self.assertEqual(taxonomia.momento_por_regras(["Conclusos para julgamento", "Juntada de Petição de x"])[0],
                         "AGUARDANDO SENTENÇA")                                              # texto puro, ordem recebida
        mesmo_dia = [MOV("Conclusos para julgamento", "2026-05-01"), MOV("Julgado procedente o pedido", "2026-05-01")]
        self.assertEqual(taxonomia.momento_por_regras(mesmo_dia)[0], "AGUARDANDO PRAZO RECURSAL")

    def test_segundo_grau_pelo_grau_do_movimento(self):
        movs = [MOV("Conclusos para julgamento", "2026-05-01", "2º grau")]
        self.assertEqual(taxonomia.momento_por_regras(movs)[0], "AGUARDANDO JULGAMENTO DO RECURSO")
        movs = [MOV("Juntada de Petição de apelação", "2026-04-01", "1º grau"),
                MOV("Conclusos para julgamento", "2026-05-01", "2º grau")]
        self.assertEqual(taxonomia.momento_por_regras(movs)[0], "AGUARDANDO JULGAMENTO DA APELAÇÃO")
        movs = [MOV("Conclusos para julgamento", "2026-05-01", "1º grau")]
        self.assertEqual(taxonomia.momento_por_regras(movs)[0], "AGUARDANDO SENTENÇA")

    def test_janela_de_busca(self):
        textos = ["Conclusos para julgamento"] + ["Juntada de Petição de manifestação"] * 35
        movs = [MOV(t, f"2026-01-{1 + i // 2:02d}") for i, t in enumerate(textos)]
        self.assertIsNone(taxonomia.momento_por_regras(movs)[0])                    # além da janela padrão (30)
        self.assertEqual(taxonomia.momento_por_regras(movs, janela=50)[0], "AGUARDANDO SENTENÇA")

    def test_concorda_com_a_simulacao_dos_tribunais(self):
        """Os movimentos do coletor simulado nascem do momento da ficha; as regras têm de devolver o mesmo momento
        (ou outro equivalente na mesma etapa, quando a simulação não distingue)."""
        equivalentes = {
            "AGUARDANDO CITAÇÃO": {"AGUARDANDO CITAÇÃO", "AGUARDANDO CITAÇÃO DO RÉU", "AGUARDANDO CITAÇÃO DOS EXECUTADOS",
                                   "AGUARDANDO CITAÇÃO POR EDITAL", "AGUARDANDO INTIMAÇÃO DO RÉU"},
            "AGUARDANDO RÉPLICA": {"AGUARDANDO RÉPLICA", "AGUARDANDO PARCELAMENTO DAS CUSTAS",
                                   "AGUARDANDO MANIFESTAÇÃO DE TERCEIROS", "AGUARDANDO SUBSTITUIÇÃO PROCESSUAL"},
            "AGUARDANDO SENTENÇA": {"AGUARDANDO SENTENÇA", "AGUARDANDO JULGAMENTO EM 1º GRAU", "AGUARDANDO JULGAMENTO",
                                    "CONCLUSOS PARA DECISÃO"},
            "CUMPRIMENTO DE SENTENÇA": {"CUMPRIMENTO DE SENTENÇA", "AGUARDANDO CONVERSÃO EM PENHORA", "AGUARDANDO PAGAMENTO"},
        }
        fichas = ficticio.gerar_carteira(300, clientes=4, semente=5)
        placar, erros = Counter(), []
        for f in fichas:
            movs = simulado.movimentos_dos_fatos(simulado.fatos(f, 1))
            momento, evidencia = taxonomia.momento_por_regras(movs)
            real = ficha.obter(f, "momento_atual")
            if momento is None:
                placar["sem regra"] += 1
                erros.append((real, None))
                continue
            self.assertIn(momento, taxonomia.MOMENTO_ATUAL)
            self.assertTrue(evidencia)
            if taxonomia.categoria_do_momento(real) == "recurso":
                ok = taxonomia.categoria_do_momento(momento) == "recurso"
            else:
                grupo = next((g for g in equivalentes.values() if real in g), {real})
                ok = momento in grupo
            placar["certo" if ok else "errado"] += 1
            if not ok:
                erros.append((real, momento))
        self.assertEqual(erros, [], placar)
        self.assertEqual(placar["certo"], len(fichas))


if __name__ == "__main__":
    unittest.main()
