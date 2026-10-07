"""Sugestão dos campos de julgamento (src/julgamento.py): uma tabela de casos por regra.
Só dados fictícios: números de `ficticio.numero_ficticio`, partes e textos inventados, sem rede."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: F401  (aponta comum.py para uma pasta temporária)
import ficticio  # noqa: E402  (já põe src/ no sys.path)
import ficha  # noqa: E402
import julgamento  # noqa: E402
import extrair  # noqa: E402
import simulado  # noqa: E402

NUM = ficticio.numero_ficticio(0)
OUTRO = ficticio.numero_ficticio(1)
CAUSA = "100000.00"


def nova(polo="passivo", causa=CAUSA, momento=None, numero=NUM, **extras):
    """Ficha fictícia com os campos de que as regras dependem (origem `coletado`, exceto onde `extras` disser)."""
    f = ficha.nova_ficha(numero)
    ficha.definir(f, "polo_cliente", polo, "coletado")
    if causa:
        ficha.definir(f, "valor_causa", causa, "coletado")
    if momento:
        ficha.definir(f, "momento_atual", momento, "coletado")
        ficha.definir(f, "situacao", "Ativo" if f.get("ativo", True) else "Encerrado", "derivado")
    for campo, valor in extras.items():
        origem = "humano" if campo in ficha.CAMPOS_DE_JULGAMENTO else "coletado"
        ficha.definir(f, campo, valor, origem)
    return f


def encerrada(f, momento="TRÂNSITO EM JULGADO"):
    """Marca a ficha como encerrada (momento + ativo + situação), como a coleta faria."""
    f["ativo"] = False
    ficha.definir(f, "momento_atual", momento, "coletado")
    ficha.definir(f, "situacao", "Encerrado", "coletado")
    return f


def doc(tipo, texto, data, grau="1º grau", numero=NUM, status="aprovado", **extras):
    """Evento de documento aprovado: `texto` vai no trecho de origem (o que a revisão aprovou)."""
    ev = {"id": f"{numero}:{tipo}:{data}", "tipo_evento": "documento", "numero": numero, "tipo": tipo, "descricao": tipo,
          "data": data, "grau": grau, "status": status, "trecho_origem": texto, "conteudo": ""}
    ev.update(extras)
    return ev


def mov(titulo, data, grau="1º grau", numero=NUM, status="aprovado"):
    return {"id": f"{numero}:mov:{data}:{titulo[:10]}", "tipo_evento": "movimento", "numero": numero, "titulo": titulo,
            "data": data, "grau": grau, "status": status, "frase": ""}


def sentenca(texto, data="2026-06-18"):
    return doc("Sentença", texto, data)


PROCEDENTE = "Ante o exposto, JULGO PROCEDENTE o pedido formulado na inicial, para condenar a ré ao pagamento de R$ 40.000,00, com correção monetária."
PARCIAL = "Ante o exposto, JULGO PARCIALMENTE PROCEDENTES os pedidos, condenando a ré ao pagamento de R$ 25.000,50; improcedentes os demais."
IMPROCEDENTE = "Ante o exposto, JULGO IMPROCEDENTE o pedido formulado na inicial. Condeno o autor ao pagamento de custas."
ACORDO = "HOMOLOGO o acordo celebrado entre as partes e JULGO EXTINTO o processo, com resolução de mérito."
EXTINCAO = "Ante o exposto, JULGO EXTINTO o processo, sem resolução do mérito, com fundamento no art. 485, VI, do CPC."
DESISTENCIA = "O autor requereu a desistência da ação. HOMOLOGO a desistência e JULGO EXTINTO o processo, sem resolução de mérito."
INCOMPETENCIA = "DECLARO a incompetência deste juízo para processar a causa e determino a remessa dos autos ao juízo competente."


def valor(sugestoes, campo):
    return sugestoes[campo]["valor"] if campo in sugestoes else None


class CasoBase(unittest.TestCase):
    def sugerir(self, f, eventos, **kw):
        return julgamento.sugerir(f, eventos, **kw)

    def ressalvas(self, s, campo):
        return " | ".join(s[campo]["ressalvas"]).lower()


class TestResultadoEProbabilidade(CasoBase):
    def test_procedente_com_evidencia(self):
        s = self.sugerir(nova(), [sentenca(PROCEDENTE)])
        self.assertEqual(valor(s, "resultado"), "Procedente")
        self.assertEqual(valor(s, "probabilidade"), "Provável")
        self.assertEqual(s["resultado"]["regra"], "resultado_procedente")
        self.assertEqual(s["probabilidade"]["regra"], "prob_procedencia")
        ev = s["resultado"]["evidencia"]
        self.assertIn("Sentença", ev["documento"])
        self.assertIn("18/06/2026", ev["documento"])
        self.assertIn("JULGO PROCEDENTE", ev["trecho"])

    def test_parcial_procedencia_conta_como_provavel(self):
        s = self.sugerir(nova(), [sentenca(PARCIAL)])
        self.assertEqual(valor(s, "resultado"), "Parcialmente procedente")
        self.assertEqual(valor(s, "probabilidade"), "Provável")
        self.assertEqual(s["probabilidade"]["regra"], "prob_parcial")

    def test_improcedente_e_remota(self):
        s = self.sugerir(nova(), [sentenca(IMPROCEDENTE)])
        self.assertEqual(valor(s, "resultado"), "Improcedente")
        self.assertEqual(valor(s, "probabilidade"), "Remota")

    def test_cliente_autor_sem_inversao(self):
        """A probabilidade é a do resultado do processo: a mesma para autor e réu (PLANO 7.2)."""
        for polo in ("ativo", "passivo"):
            with self.subTest(polo=polo):
                f = nova(polo=polo)
                self.assertEqual(valor(self.sugerir(f, [sentenca(PROCEDENTE)]), "probabilidade"), "Provável")
                self.assertEqual(valor(self.sugerir(f, [sentenca(PARCIAL)]), "probabilidade"), "Provável")
                self.assertEqual(valor(self.sugerir(f, [sentenca(IMPROCEDENTE)]), "probabilidade"), "Remota")

    def test_acordo_sem_probabilidade(self):
        s, avisos = julgamento.sugerir_com_avisos(nova(), [sentenca(ACORDO)])
        self.assertEqual(valor(s, "resultado"), "Acordo")
        self.assertNotIn("probabilidade", s)
        self.assertIn("sem_probabilidade", [a["codigo"] for a in avisos])

    def test_extincao_desistencia_e_incompetencia(self):
        casos = ((EXTINCAO, "Extinto sem resolução de mérito"), (DESISTENCIA, "Arquivado / desistência"),
                 (INCOMPETENCIA, "Incompetência declarada"))
        for texto, esperado in casos:
            with self.subTest(esperado=esperado):
                s = self.sugerir(nova(), [sentenca(texto)])
                self.assertEqual(valor(s, "resultado"), esperado)
                self.assertNotIn("probabilidade", s)

    def test_processo_sem_decisao(self):
        s = self.sugerir(nova(), [doc("Contestação", "A ré requer a improcedência dos pedidos.", "2026-03-01"),
                                  mov("Conclusos para julgamento", "2026-05-01")])
        self.assertNotIn("resultado", s)
        self.assertEqual(valor(s, "probabilidade"), "Possível")
        self.assertEqual(s["probabilidade"]["regra"], "prob_sem_decisao")
        self.assertEqual(valor(s, "valor_estimado"), CAUSA)
        self.assertNotIn("valor_economizado", s)  # processo ativo

    def test_encerrado_sem_decisao_nao_inventa_probabilidade(self):
        s, avisos = julgamento.sugerir_com_avisos(encerrada(nova()), [])
        self.assertNotIn("probabilidade", s)
        self.assertIn("encerrado_sem_decisao", [a["codigo"] for a in avisos])

    def test_sem_nenhum_evento(self):
        s = self.sugerir(nova(), [])
        self.assertEqual(set(s), {"probabilidade", "valor_estimado"})

    def test_texto_da_decisao_vem_do_conteudo_ou_do_arquivo(self):
        ev = doc("Sentença", "", "2026-06-18", conteudo="O juiz julgou improcedente o pedido do autor.")
        self.assertEqual(valor(self.sugerir(nova(), [ev]), "resultado"), "Improcedente")
        arquivo = isolamento.TMP / "sentenca-teste.txt"
        arquivo.write_text("PODER JUDICIÁRIO (fictício)\n" + PARCIAL, encoding="utf-8")
        ev = doc("Sentença", "", "2026-06-18", texto_arquivo=str(arquivo))
        self.assertEqual(valor(self.sugerir(nova(), [ev]), "resultado"), "Parcialmente procedente")
        ev = doc("Sentença", "", "2026-06-18", texto_arquivo=str(isolamento.TMP / "nao-existe.txt"))
        s, avisos = julgamento.sugerir_com_avisos(nova(), [ev])
        self.assertNotIn("resultado", s)
        self.assertIn("texto_arquivo_ilegivel", [a["codigo"] for a in avisos])

    def test_movimento_do_tribunal(self):
        s = self.sugerir(nova(), [mov("Julgado parcialmente procedente o pedido", "2026-06-18")])
        self.assertEqual(valor(s, "resultado"), "Parcialmente procedente")
        self.assertIn("Movimento de 18/06/2026", s["resultado"]["evidencia"]["documento"])

    def test_so_decisao_conta(self):
        """Petição que pede a improcedência, juntada e embargos/impugnação não viram resultado."""
        eventos = [doc("Contestação", "Requer a improcedência dos pedidos; julgue-se improcedente a ação.", "2026-03-01"),
                   doc("Réplica", "Requer que seja julgado procedente o pedido.", "2026-04-01"),
                   mov("Juntada de Petição de apelação requerendo julgar procedente", "2026-07-01"),
                   doc("Decisão", "Em sede de impugnação ao cumprimento, JULGO IMPROCEDENTE a impugnação.", "2026-08-01")]
        s, avisos = julgamento.sugerir_com_avisos(nova(), eventos)
        self.assertNotIn("resultado", s)
        self.assertEqual(valor(s, "probabilidade"), "Possível")

    def test_evento_nao_aprovado_e_de_outro_processo_ignorados(self):
        eventos = [doc("Sentença", PROCEDENTE, "2026-06-18", status="rascunho"),
                   doc("Sentença", PROCEDENTE, "2026-06-18", status="coletado"),
                   doc("Sentença", PROCEDENTE, "2026-06-18", numero=OUTRO)]
        self.assertNotIn("resultado", self.sugerir(nova(), eventos))
        self.assertEqual(valor(self.sugerir(nova(), [doc("Sentença", PROCEDENTE, "2026-06-18", status="relatado")]), "resultado"),
                         "Procedente")

    def test_decisao_de_vinculado_agravo_nao_decide_a_causa(self):
        f = nova()
        ficha.vincular(f, OUTRO, "agravo")
        s = self.sugerir(f, [doc("Acórdão", "NEGOU PROVIMENTO ao agravo. JULGO IMPROCEDENTE.", "2026-07-01", numero=OUTRO,
                                 grau="2º grau")])
        self.assertNotIn("resultado", s)

    def test_decisao_mais_recente_vale(self):
        eventos = [sentenca(IMPROCEDENTE, "2026-03-10"), sentenca(PROCEDENTE, "2026-05-20")]
        self.assertEqual(valor(self.sugerir(nova(), eventos), "resultado"), "Procedente")
        self.assertEqual(valor(self.sugerir(nova(), list(reversed(eventos))), "resultado"), "Procedente")

    def test_texto_com_procedencia_e_improcedencia_avisa(self):
        s = self.sugerir(nova(), [sentenca("JULGO IMPROCEDENTE a ação e PROCEDENTE a reconvenção, sem valor certo.")])
        self.assertEqual(valor(s, "resultado"), "Improcedente")
        self.assertIn("procedência e improcedência", self.ressalvas(s, "resultado"))

    def test_acordo_negado_nao_e_acordo(self):
        s = self.sugerir(nova(), [sentenca("INDEFIRO a homologação do acordo, por falta de assinatura.")])
        self.assertNotIn("resultado", s)


class TestRecursoEInstancia(CasoBase):
    def test_primeiro_grau_com_recurso_pendente(self):
        eventos = [sentenca(PROCEDENTE, "2026-06-18"), doc("Apelação", "Interpõe APELAÇÃO contra a sentença.", "2026-07-02")]
        s = self.sugerir(nova(), eventos)
        self.assertIn("sujeita a recurso", self.ressalvas(s, "probabilidade"))
        self.assertIn("recurso pendente", self.ressalvas(s, "probabilidade"))
        self.assertIn("sujeita a recurso", self.ressalvas(s, "resultado"))

    def test_primeiro_grau_sem_transito_tambem_e_sujeita_a_recurso(self):
        s = self.sugerir(nova(), [sentenca(IMPROCEDENTE)])
        self.assertIn("sujeita a recurso", self.ressalvas(s, "probabilidade"))

    def test_primeiro_grau_transitado_sem_ressalva(self):
        eventos = [sentenca(PROCEDENTE, "2026-06-18"), mov("Transitado em julgado", "2026-08-10")]
        s = self.sugerir(nova(), eventos)
        self.assertNotIn("recurso", self.ressalvas(s, "probabilidade"))
        self.assertEqual(valor(s, "probabilidade"), "Provável")

    def test_trancito_por_momento_atual_ou_data_do_transito(self):
        f = nova(momento="CUMPRIMENTO DE SENTENÇA")
        self.assertNotIn("recurso", self.ressalvas(self.sugerir(f, [sentenca(PROCEDENTE)]), "probabilidade"))
        f = nova(data_transito="2026-08-10")
        self.assertNotIn("recurso", self.ressalvas(self.sugerir(f, [sentenca(PROCEDENTE)]), "probabilidade"))

    def test_momento_de_recurso_conta_como_pendente(self):
        f = nova(momento="AGUARDANDO JULGAMENTO DA APELAÇÃO")
        s = self.sugerir(f, [sentenca(PROCEDENTE)])
        self.assertIn("recurso pendente", self.ressalvas(s, "probabilidade"))

    def test_tribunal_reforma_a_decisao_de_primeiro_grau(self):
        eventos = [sentenca(PROCEDENTE, "2026-06-18"), doc("Apelação", "Interpõe apelação.", "2026-07-02"),
                   doc("Acórdão", "A Turma DEU PROVIMENTO ao recurso para reformar a sentença e julgar improcedente o pedido.",
                       "2026-10-01", grau="2º grau")]
        s = self.sugerir(nova(), eventos)
        self.assertEqual(valor(s, "resultado"), "Improcedente")
        self.assertEqual(valor(s, "probabilidade"), "Remota")
        self.assertIn("reformou", self.ressalvas(s, "resultado"))
        self.assertIn("antes: procedente", self.ressalvas(s, "probabilidade"))
        self.assertNotIn("sujeita a recurso", self.ressalvas(s, "probabilidade"))
        self.assertIn("Acórdão", s["resultado"]["evidencia"]["documento"])

    def test_acordao_usa_o_texto_depois_do_provimento(self):
        """O relatório do acórdão cita a sentença ('julgou improcedente'); vale o dispositivo."""
        texto = ("Trata-se de apelação contra sentença que julgou improcedente o pedido. Ante o exposto, DOU PROVIMENTO "
                 "ao recurso para julgar procedente o pedido.")
        eventos = [sentenca(IMPROCEDENTE, "2026-06-18"), doc("Acórdão", texto, "2026-10-01", grau="2º grau")]
        self.assertEqual(valor(self.sugerir(nova(), eventos), "resultado"), "Procedente")

    def test_acordao_que_mantem_confirma_e_vira_evidencia(self):
        eventos = [sentenca(PROCEDENTE, "2026-06-18"), doc("Apelação", "Interpõe apelação.", "2026-07-02"),
                   doc("Acórdão", "A Turma, por unanimidade, NEGOU PROVIMENTO ao recurso, mantendo integralmente a sentença recorrida.",
                       "2026-10-01", grau="2º grau")]
        s = self.sugerir(nova(), eventos)
        self.assertEqual(valor(s, "resultado"), "Procedente")
        self.assertEqual(s["resultado"]["regra"], "resultado_mantido")
        self.assertIn("Acórdão", s["resultado"]["evidencia"]["documento"])
        self.assertIn("NEGOU PROVIMENTO", s["resultado"]["evidencia"]["trecho"])
        self.assertNotIn("sujeita a recurso", self.ressalvas(s, "probabilidade"))
        self.assertEqual(valor(s, "valor_estimado"), "40000.00")  # o valor continua o da sentença mantida

    def test_acordao_que_da_provimento_sem_dizer_o_resultado_nao_sugere(self):
        eventos = [sentenca(PROCEDENTE, "2026-06-18"),
                   doc("Acórdão", "A Turma DEU PROVIMENTO PARCIAL ao recurso, reduzindo a condenação.", "2026-10-01", grau="2º grau")]
        s, avisos = julgamento.sugerir_com_avisos(nova(), eventos)
        self.assertEqual(s, {})
        self.assertIn("acordao_reforma_sem_resultado", [a["codigo"] for a in avisos])

    def test_acordao_sem_a_sentenca_nos_eventos(self):
        s, avisos = julgamento.sugerir_com_avisos(nova(), [doc("Acórdão", "NEGOU PROVIMENTO ao recurso ordinário, mantida a sentença.",
                                                               "2026-10-01", grau="2º grau")])
        self.assertNotIn("resultado", s)
        self.assertIn("acordao_sem_sentenca", [a["codigo"] for a in avisos])

    def test_negado_seguimento_a_recurso_mantem(self):
        eventos = [sentenca(IMPROCEDENTE, "2026-06-18"), mov("Negado seguimento a Recurso", "2026-09-01", grau="2º grau")]
        s = self.sugerir(nova(), eventos)
        self.assertEqual(valor(s, "resultado"), "Improcedente")
        self.assertNotIn("sujeita a recurso", self.ressalvas(s, "probabilidade"))

    def test_agravo_de_instrumento_nao_confirma_a_sentenca(self):
        eventos = [sentenca(IMPROCEDENTE, "2026-06-18"),
                   doc("Acórdão", "NEGOU PROVIMENTO ao agravo de instrumento.", "2026-09-01", grau="2º grau")]
        self.assertIn("sujeita a recurso", self.ressalvas(self.sugerir(nova(), eventos), "probabilidade"))

    def test_embargos_de_declaracao_nao_reformam(self):
        eventos = [sentenca(PROCEDENTE, "2026-06-18"),
                   doc("Decisão", "Dou provimento aos embargos de declaração para sanar omissão.", "2026-07-01")]
        self.assertEqual(valor(self.sugerir(nova(), eventos), "resultado"), "Procedente")

    def test_grau_pelo_tipo_do_documento_e_desempate_no_mesmo_dia(self):
        eventos = [doc("Acórdão", "JULGO PROCEDENTE o pedido.", "2026-09-01", grau=None),
                   sentenca(IMPROCEDENTE, "2026-09-01")]
        self.assertEqual(valor(self.sugerir(nova(), eventos), "resultado"), "Procedente")


class TestValorEstimado(CasoBase):
    def test_sem_decisao_valor_da_causa(self):
        s = self.sugerir(nova(), [])
        self.assertEqual(valor(s, "valor_estimado"), CAUSA)
        self.assertEqual(s["valor_estimado"]["regra"], "estimado_causa")

    def test_valor_lido_da_condenacao(self):
        s = self.sugerir(nova(), [sentenca(PROCEDENTE)])
        self.assertEqual(valor(s, "valor_estimado"), "40000.00")
        self.assertEqual(s["valor_estimado"]["regra"], "estimado_condenacao")
        self.assertIn("R$ 40.000,00", s["valor_estimado"]["evidencia"]["trecho"])
        s = self.sugerir(nova(), [sentenca(PARCIAL)])
        self.assertEqual(valor(s, "valor_estimado"), "25000.50")

    def test_valor_arbitrado_da_ficha_vale_e_diferenca_vira_ressalva(self):
        f = nova(valor_arbitrado="35000.00")
        s = self.sugerir(f, [sentenca(PROCEDENTE)])
        self.assertEqual(valor(s, "valor_estimado"), "35000.00")
        self.assertEqual(s["valor_estimado"]["regra"], "estimado_arbitrado")
        self.assertIn("difere", self.ressalvas(s, "valor_estimado"))

    def test_procedente_sem_valor_claro_mantem_a_causa_com_ressalva(self):
        s = self.sugerir(nova(), [sentenca("JULGO PROCEDENTE o pedido. Liquidação por cálculos.")])
        self.assertEqual(valor(s, "valor_estimado"), CAUSA)
        self.assertEqual(s["valor_estimado"]["regra"], "estimado_causa_sem_valor")
        self.assertIn("não identificado", self.ressalvas(s, "valor_estimado"))

    def test_honorarios_e_multa_nao_sao_a_condenacao(self):
        s = self.sugerir(nova(), [sentenca("JULGO PROCEDENTE o pedido. Condeno a ré ao pagamento de honorários de R$ 3.000,00 e multa.")])
        self.assertEqual(s["valor_estimado"]["regra"], "estimado_causa_sem_valor")

    def test_dois_valores_na_decisao_nao_define(self):
        s = self.sugerir(nova(), [sentenca("JULGO PROCEDENTE. Condeno A ao pagamento de R$ 1.000,00 e condeno B ao pagamento de R$ 2.000,00.")])
        self.assertEqual(valor(s, "valor_estimado"), CAUSA)
        self.assertIn("mais de um valor", self.ressalvas(s, "valor_estimado"))

    def test_improcedencia_extincao_e_desistencia_valem_zero(self):
        for texto in (IMPROCEDENTE, EXTINCAO, DESISTENCIA):
            with self.subTest(texto=texto[:30]):
                s = self.sugerir(nova(), [sentenca(texto)])
                self.assertEqual(valor(s, "valor_estimado"), "0.00")
                self.assertEqual(s["valor_estimado"]["regra"], "estimado_zero")

    def test_incompetencia_mantem_a_causa(self):
        s = self.sugerir(nova(), [sentenca(INCOMPETENCIA)])
        self.assertEqual(valor(s, "valor_estimado"), CAUSA)

    def test_acordo_com_valor_da_ficha(self):
        s = self.sugerir(nova(valor_acordo="30000.00"), [sentenca(ACORDO)])
        self.assertEqual(valor(s, "valor_estimado"), "30000.00")
        self.assertEqual(s["valor_estimado"]["regra"], "estimado_acordo")

    def test_acordo_com_valor_no_texto(self):
        texto = "O acordo prevê pagamento de R$ 12.345,67, em parcela única. HOMOLOGO o acordo celebrado entre as partes."
        s = self.sugerir(nova(), [sentenca(texto)])
        self.assertEqual(valor(s, "valor_estimado"), "12345.67")

    def test_acordo_com_valor_na_peticao_e_nao_na_sentenca(self):
        eventos = [doc("Petição", "As partes firmaram acordo no valor de R$ 8.000,00, a pagar em dez dias.", "2026-05-01"),
                   sentenca(ACORDO, "2026-05-20")]
        self.assertEqual(valor(self.sugerir(nova(), eventos), "valor_estimado"), "8000.00")

    def test_acordo_sem_valor_mantem_a_causa_com_ressalva(self):
        s = self.sugerir(nova(), [sentenca(ACORDO)])
        self.assertEqual(valor(s, "valor_estimado"), CAUSA)
        self.assertIn("acordo sem valor", self.ressalvas(s, "valor_estimado"))

    def test_sem_valor_da_causa_nao_sugere_e_avisa(self):
        s, avisos = julgamento.sugerir_com_avisos(nova(causa=None), [])
        self.assertNotIn("valor_estimado", s)
        self.assertIn("valor_causa_ausente", [a["codigo"] for a in avisos])

    def test_valor_do_tribunal_vale_depois_da_reforma(self):
        eventos = [sentenca(PROCEDENTE, "2026-06-18"),
                   doc("Acórdão", "DOU PROVIMENTO PARCIAL ao recurso para julgar parcialmente procedente o pedido e condenar a ré ao pagamento de "
                       "R$ 10.000,00.", "2026-10-01", grau="2º grau")]
        s = self.sugerir(nova(), eventos)
        self.assertEqual(valor(s, "resultado"), "Parcialmente procedente")
        self.assertEqual(valor(s, "valor_estimado"), "10000.00")


class TestValorEconomizado(CasoBase):
    def test_so_processo_encerrado(self):
        self.assertNotIn("valor_economizado", self.sugerir(nova(), [sentenca(IMPROCEDENTE)]))
        s = self.sugerir(encerrada(nova()), [sentenca(IMPROCEDENTE)])
        self.assertEqual(valor(s, "valor_economizado"), CAUSA)  # causa 100.000 - estimado 0
        self.assertEqual(s["valor_economizado"]["regra"], "economia_causa_menos_estimado")

    def test_causa_menos_estimado_e_nao_o_contrario(self):
        s = self.sugerir(encerrada(nova()), [sentenca(PROCEDENTE)])
        self.assertEqual(valor(s, "valor_economizado"), "60000.00")

    def test_acordo_com_valor_conta(self):
        s = self.sugerir(encerrada(nova(valor_acordo="30000.00"), "ACORDO HOMOLOGADO"), [sentenca(ACORDO)])
        self.assertEqual(valor(s, "valor_economizado"), "70000.00")

    def test_acordo_sem_valor_nao_conta(self):
        s = self.sugerir(encerrada(nova(), "ACORDO HOMOLOGADO"), [sentenca(ACORDO)])
        self.assertIsNone(valor(s, "valor_economizado"))
        self.assertEqual(s["valor_economizado"]["regra"], "economia_nao_conta")
        self.assertIn("acordo sem valor", self.ressalvas(s, "valor_economizado"))

    def test_acordo_pago_por_terceiro_nao_conta(self):
        texto = "O pagamento do acordo será efetuado pela seguradora denunciada. HOMOLOGO o acordo celebrado entre as partes."
        s = self.sugerir(encerrada(nova(valor_acordo="30000.00"), "ACORDO HOMOLOGADO"), [sentenca(texto)])
        self.assertIsNone(valor(s, "valor_economizado"))
        self.assertIn("terceiro", self.ressalvas(s, "valor_economizado"))
        self.assertEqual(valor(s, "valor_estimado"), "30000.00")  # o valor estimado continua sendo o do acordo

    def test_acordo_pago_por_terceiro_dito_nas_observacoes(self):
        f = encerrada(nova(valor_acordo="30000.00"), "ACORDO HOMOLOGADO")
        ficha.definir(f, "observacoes", "Acordo quitado por terceiro (empresa tomadora).", "humano")
        s = self.sugerir(f, [sentenca(ACORDO)])
        self.assertIn("terceiro", self.ressalvas(s, "valor_economizado"))

    def test_exclusao_da_lide_nao_conta(self):
        texto = "Acolho a preliminar de ilegitimidade e EXCLUO a ré da lide, JULGANDO EXTINTO o processo sem resolução do mérito."
        s = self.sugerir(encerrada(nova()), [sentenca(texto)])
        self.assertIsNone(valor(s, "valor_economizado"))
        self.assertIn("exclusão da lide", self.ressalvas(s, "valor_economizado"))

    def test_exclusao_indeferida_nao_e_exclusao(self):
        s = self.sugerir(encerrada(nova()), [sentenca("INDEFIRO o pedido de exclusão da lide. " + IMPROCEDENTE)])
        self.assertEqual(valor(s, "valor_economizado"), CAUSA)

    def test_cliente_autor_nao_conta_e_sem_inversao(self):
        f = encerrada(nova(polo="ativo"))
        s = self.sugerir(f, [sentenca(IMPROCEDENTE)])
        self.assertIsNone(valor(s, "valor_economizado"))
        self.assertIn("cliente é autor", self.ressalvas(s, "valor_economizado"))
        self.assertEqual(valor(s, "probabilidade"), "Remota")  # sem inversão: improcedência é Remota também para o autor

    def test_incompetencia_nao_conta(self):
        s = self.sugerir(encerrada(nova()), [sentenca(INCOMPETENCIA)])
        self.assertIsNone(valor(s, "valor_economizado"))
        self.assertIn("incompetência", self.ressalvas(s, "valor_economizado"))

    def test_procedente_sem_valor_na_decisao_nao_conta(self):
        s = self.sugerir(encerrada(nova()), [sentenca("JULGO PROCEDENTE o pedido, a liquidar.")])
        self.assertIsNone(valor(s, "valor_economizado"))
        self.assertIn("sem base na decisão", self.ressalvas(s, "valor_economizado"))

    def test_extincao_conta_com_ressalva(self):
        s = self.sugerir(encerrada(nova(), "EXTINTO SEM RESOLUÇÃO DE MÉRITO"), [sentenca(EXTINCAO)])
        self.assertEqual(valor(s, "valor_economizado"), CAUSA)
        self.assertIn("proposta de novo", self.ressalvas(s, "valor_economizado"))

    def test_diferenca_negativa_vira_ressalva(self):
        s = self.sugerir(encerrada(nova(causa="10000.00")), [sentenca(PROCEDENTE)])
        self.assertEqual(valor(s, "valor_economizado"), "-30000.00")
        self.assertIn("negativa", self.ressalvas(s, "valor_economizado"))

    def test_polo_desconhecido_e_ressalva(self):
        f = encerrada(nova(polo=None))
        s = self.sugerir(f, [sentenca(IMPROCEDENTE)])
        self.assertEqual(valor(s, "valor_economizado"), CAUSA)
        self.assertIn("polo do cliente não informado", self.ressalvas(s, "valor_economizado"))

    def test_encerrado_pelo_resultado_mesmo_sem_momento(self):
        s = self.sugerir(nova(valor_acordo="30000.00"), [sentenca(ACORDO)])
        self.assertEqual(valor(s, "valor_economizado"), "70000.00")

    def test_momento_com_qualificador_entre_parenteses(self):
        f = nova()
        f["ativo"] = False
        ficha.definir(f, "momento_atual", "PROCESSO ARQUIVADO", "coletado")
        f["campos"]["momento_atual"]["valor"] = "PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)"
        s = self.sugerir(f, [sentenca(IMPROCEDENTE)])
        self.assertEqual(valor(s, "valor_economizado"), CAUSA)


class TestCampoHumanoEAplicacao(CasoBase):
    def test_campo_humano_nao_aparece_e_nao_e_sobrescrito(self):
        f = nova(probabilidade="Possível", resultado="Acordo")
        original = copy.deepcopy(f)
        s = self.sugerir(f, [sentenca(PROCEDENTE)])
        self.assertNotIn("probabilidade", s)
        self.assertNotIn("resultado", s)
        self.assertIn("valor_estimado", s)
        self.assertEqual(f, original)  # sugerir não altera a ficha
        julgamento.aplicar(f, julgamento.sugerir(f, [sentenca(PROCEDENTE)]))
        self.assertEqual(ficha.obter(f, "probabilidade"), "Possível")
        self.assertEqual(ficha.origem(f, "probabilidade"), "humano")
        self.assertEqual(ficha.obter(f, "resultado"), "Acordo")

    def test_aplicar_forca_nao_vence_humano_nem_outra_origem(self):
        f = nova(probabilidade="Possível")
        s = julgamento.sugerir(nova(), [sentenca(PROCEDENTE)])      # sugestão calculada em outra ficha
        self.assertNotIn("probabilidade", julgamento.aplicar(f, s))
        self.assertEqual(ficha.obter(f, "probabilidade"), "Possível")
        ficha.definir(f, "valor_estimado", "1.00", "derivado")
        self.assertNotIn("valor_estimado", julgamento.aplicar(f, s))
        self.assertEqual(ficha.obter(f, "valor_estimado"), "1.00")

    def test_aplicar_grava_origem_sugerido_com_evidencia(self):
        f = nova()
        s = julgamento.sugerir(f, [sentenca(PROCEDENTE), doc("Apelação", "Interpõe apelação.", "2026-07-02")])
        gravados = julgamento.aplicar(f, s)
        self.assertEqual(set(gravados), {"resultado", "probabilidade", "valor_estimado"})
        for campo in gravados:
            self.assertEqual(ficha.origem(f, campo), "sugerido")
        self.assertEqual(ficha.obter(f, "resultado"), "Procedente")
        self.assertEqual(ficha.obter(f, "valor_estimado"), "40000.00")
        evidencia = f["campos"]["probabilidade"]["evidencia"]
        self.assertIn("prob_procedencia", evidencia)
        self.assertIn("Sujeita a recurso", evidencia)
        self.assertEqual(ficha.validar(f), [])

    def test_nova_sugestao_atualiza_a_anterior(self):
        f = nova()
        julgamento.aplicar(f, julgamento.sugerir(f, [sentenca(PROCEDENTE)]))
        eventos = [sentenca(PROCEDENTE, "2026-06-18"), sentenca(IMPROCEDENTE, "2026-09-18")]
        julgamento.aplicar(f, julgamento.sugerir(f, eventos))
        self.assertEqual(ficha.obter(f, "resultado"), "Improcedente")
        self.assertEqual(ficha.obter(f, "probabilidade"), "Remota")
        self.assertEqual(ficha.origem(f, "resultado"), "sugerido")

    def test_aplicar_ignora_economia_que_nao_conta_e_campos_estranhos(self):
        f = encerrada(nova(polo="ativo"))
        s = julgamento.sugerir(f, [sentenca(IMPROCEDENTE)])
        self.assertIsNone(valor(s, "valor_economizado"))
        self.assertNotIn("valor_economizado", julgamento.aplicar(f, s))
        self.assertIsNone(ficha.obter(f, "valor_economizado"))
        self.assertEqual(julgamento.aplicar(f, {"vara": {"valor": "1ª Vara"}, "resultado": {"valor": None}}), [])

    def test_forma_da_saida(self):
        s = julgamento.sugerir(encerrada(nova(valor_acordo="1.00")), [sentenca(ACORDO)])
        self.assertTrue(s)
        for campo, entrada in s.items():
            self.assertIn(campo, julgamento.CAMPOS_SUGERIDOS)
            self.assertEqual(set(entrada), {"valor", "regra", "evidencia", "ressalvas"})
            self.assertEqual(set(entrada["evidencia"]), {"documento", "trecho"})
            self.assertIsInstance(entrada["evidencia"]["documento"], str)
            self.assertIsInstance(entrada["evidencia"]["trecho"], str)
            self.assertIn(entrada["regra"], julgamento.REGRAS)
            self.assertTrue(all(isinstance(r, str) and r for r in entrada["ressalvas"]))
            self.assertLessEqual(len(entrada["evidencia"]["trecho"]), julgamento.LIMITE_TRECHO + 4)


class TestTextoDoRelatorio(CasoBase):
    def com_texto(self, texto, **kw):
        f = nova(**kw)
        f["linha_de_base"] = {"data_base": "2026-09-18", "arquivo": "relatorio-exemplo.docx", "andamentos_texto": texto,
                              "ultimo_andamento": None}
        return f

    def test_resultado_vem_do_texto_do_relatorio_com_ressalva(self):
        f = self.com_texto("Em 10/03/2026 foi apresentada contestação pelo cliente. "
                           "Em 18/06/2026 foi proferida sentença julgando improcedente o pedido formulado na inicial. "
                           "Em 20/07/2026 a decisão transitou em julgado.")
        s = self.sugerir(f, [])
        self.assertEqual(valor(s, "resultado"), "Improcedente")
        self.assertEqual(valor(s, "probabilidade"), "Remota")
        self.assertIn("relatório anterior", self.ressalvas(s, "resultado"))
        self.assertIn("Texto do relatório anterior (18/06/2026)", s["resultado"]["evidencia"]["documento"])
        self.assertNotIn("recurso", self.ressalvas(s, "probabilidade"))  # trânsito está no texto

    def test_texto_do_relatorio_pode_ser_desligado(self):
        f = self.com_texto("Em 18/06/2026 foi proferida sentença julgando procedente o pedido.")
        self.assertNotIn("resultado", self.sugerir(f, [], usar_relatorio=False))

    def test_evento_novo_vence_o_texto_antigo(self):
        f = self.com_texto("Em 18/06/2026 foi proferida sentença julgando procedente o pedido formulado na inicial.")
        eventos = [doc("Acórdão", "NEGOU PROVIMENTO à apelação, mantida a sentença.", "2026-10-01", grau="2º grau")]
        s = self.sugerir(f, eventos)
        self.assertEqual(valor(s, "resultado"), "Procedente")
        self.assertIn("Acórdão", s["resultado"]["evidencia"]["documento"])

    def test_peticao_no_texto_do_relatorio_nao_vira_resultado(self):
        f = self.com_texto("Em 05/05/2026 o autor apresentou apelação requerendo seja julgado procedente o pedido.")
        self.assertNotIn("resultado", self.sugerir(f, []))

    def test_acordo_e_valor_do_texto_do_relatorio(self):
        f = self.com_texto("Em 18/06/2026 foi homologado acordo entre as partes, no valor de R$ 12.000,00.")
        s = self.sugerir(f, [])
        self.assertEqual(valor(s, "resultado"), "Acordo")
        self.assertEqual(valor(s, "valor_estimado"), "12000.00")


class TestConcordancia(CasoBase):
    def migrada(self, numero, texto, polo="passivo", **humano):
        f = nova(polo=polo, numero=numero)
        f["linha_de_base"] = {"data_base": "2026-09-18", "arquivo": "relatorio-exemplo.docx", "andamentos_texto": texto,
                              "ultimo_andamento": None}
        for campo, v in humano.items():
            ficha.definir(f, campo, v, "humano")
        return f

    def carteira(self):
        n = [ficticio.numero_ficticio(100 + i) for i in range(5)]
        proc = "Em 18/06/2026 foi proferida sentença julgando procedente o pedido formulado na inicial. Em 20/08/2026 a decisão transitou em julgado."
        impr = "Em 18/06/2026 foi proferida sentença julgando improcedente o pedido formulado na inicial. Em 20/08/2026 a decisão transitou em julgado."
        return n, [
            # concordam em tudo (autor também: sem inversão)
            self.migrada(n[0], impr, resultado="Improcedente", probabilidade="Remota", valor_estimado="0.00"),
            self.migrada(n[1], impr, polo="ativo", resultado="Improcedente", probabilidade="Remota", valor_estimado="0.00"),
            # humano lançou Possível, a regra lê procedência: diverge em probabilidade, concorda no resultado
            self.migrada(n[2], proc, resultado="Procedente", probabilidade="Possível", valor_estimado="40000.00"),
            # humano lançou resultado que o texto não diz
            self.migrada(n[3], "Em 10/03/2026 foi apresentada contestação.", resultado="Acordo"),
            # humano sem nenhum campo de julgamento: fora do total
            self.migrada(n[4], proc),
        ]

    def test_concordancia_por_campo_e_casos_divergentes(self):
        n, fichas = self.carteira()
        # valor da condenação: o texto do relatório não traz R$; o valor arbitrado entra pela ficha
        ficha.definir(fichas[2], "valor_arbitrado", "40000.00", "humano")
        c = julgamento.concordancia(fichas)
        self.assertEqual(set(c), set(julgamento.CAMPOS_SUGERIDOS))
        self.assertEqual((c["resultado"]["concordam"], c["resultado"]["total"]), (3, 4))
        self.assertEqual(c["resultado"]["casos_divergentes"], [n[3]])
        self.assertEqual((c["probabilidade"]["concordam"], c["probabilidade"]["total"]), (2, 3))
        self.assertEqual(c["probabilidade"]["casos_divergentes"], [n[2]])
        self.assertEqual((c["valor_estimado"]["concordam"], c["valor_estimado"]["total"]), (3, 3))
        self.assertEqual(c["valor_estimado"]["casos_divergentes"], [])
        self.assertEqual((c["valor_economizado"]["concordam"], c["valor_economizado"]["total"]), (0, 0))
        self.assertIn("resultado_improcedente", c["resultado"]["por_regra"])
        self.assertEqual(c["resultado"]["por_regra"]["resultado_improcedente"], {"concordam": 2, "total": 2})
        self.assertEqual(c["resultado"]["por_regra"]["sem_sugestao"], {"concordam": 0, "total": 1})

    def test_concordancia_compara_com_o_que_ja_esta_lancado_mesmo_sendo_humano(self):
        """`sugerir` esconde o campo humano; a concordância precisa do cálculo completo."""
        _, fichas = self.carteira()
        self.assertNotIn("resultado", julgamento.sugerir(fichas[0], []))
        self.assertEqual(julgamento.concordancia(fichas[:1])["resultado"]["concordam"], 1)

    def test_economia_nao_conta_diverge_de_valor_lancado(self):
        n = ficticio.numero_ficticio(110)
        f = self.migrada(n, "Em 18/06/2026 foi proferida sentença julgando improcedente o pedido.", polo="ativo",
                         valor_economizado="100000.00")
        encerrada(f)
        c = julgamento.concordancia([f])
        self.assertEqual((c["valor_economizado"]["concordam"], c["valor_economizado"]["total"]), (0, 1))
        self.assertEqual(c["valor_economizado"]["casos_divergentes"], [n])

    def test_eventos_opcionais_na_concordancia(self):
        n = ficticio.numero_ficticio(111)
        f = nova(numero=n)
        ficha.definir(f, "resultado", "Procedente", "humano")
        ev = doc("Sentença", PROCEDENTE, "2026-06-18", numero=n)
        self.assertEqual(julgamento.concordancia([f])["resultado"]["concordam"], 0)
        for eventos in ([ev], {n: [ev]}):
            self.assertEqual(julgamento.concordancia([f], eventos)["resultado"]["concordam"], 1)

    def test_tolerancia_de_um_centavo_e_vazio(self):
        n = ficticio.numero_ficticio(112)
        f = nova(numero=n, valor_estimado="100000.01")
        self.assertEqual(julgamento.concordancia([f])["valor_estimado"]["concordam"], 1)
        self.assertEqual(julgamento.concordancia([])["resultado"], {"concordam": 0, "total": 0, "casos_divergentes": [], "por_regra": {}})

    def test_carteira_ficticia_gerada(self):
        """Carteira sintética com campos humanos e histórico coerente: o resultado lido do texto bate com o lançado."""
        fichas = ficticio.gerar_carteira(80, semente=3)
        for f in fichas:
            ficticio.anexar_linha_de_base(f, data_base=ficticio.HOJE)
        c = julgamento.concordancia(fichas)
        self.assertGreater(c["resultado"]["total"], 3)
        self.assertEqual(c["resultado"]["casos_divergentes"], [], c["resultado"])
        for campo in julgamento.CAMPOS_SUGERIDOS:
            self.assertLessEqual(c[campo]["concordam"], c[campo]["total"])
            self.assertEqual(c[campo]["total"], sum(r["total"] for r in c[campo]["por_regra"].values()))
            self.assertEqual(len(c[campo]["casos_divergentes"]), c[campo]["total"] - c[campo]["concordam"])
        # o valor estimado também concorda onde o humano lançou (arbitrado/acordo/causa vêm da própria ficha)
        self.assertEqual(c["valor_estimado"]["casos_divergentes"], [], c["valor_estimado"])
        # economia lançada à mão que a regra NÃO conta: só o cliente autor (PLANO 7.2; ver RFC-julgamento-fixture)
        por_numero = {f["numero"]: f for f in fichas}
        for numero in c["valor_economizado"]["casos_divergentes"]:
            self.assertEqual(ficha.obter(por_numero[numero], "polo_cliente"), "ativo", numero)


class TestComColetorSimulado(CasoBase):
    """Ponta a ponta sem rede: documentos (PDF e HTML) e movimentos do coletor simulado viram eventos aprovados;
    as regras leem o texto extraído e reproduzem o que a ficha diz."""

    def eventos_do_coletor(self, coletor, f):
        r = coletor.coletar({"numero": f["numero"]}, "completo")
        eventos = [{"tipo_evento": "movimento", "numero": f["numero"], "titulo": m["texto"], "data": m["data"],
                    "grau": m["grau"], "status": "aprovado"} for m in r["movimentos"]]
        for d in r["documentos"]:
            texto, _ = extrair.extrair_arquivo(d["caminho"])
            arquivo = Path(d["caminho"]).with_suffix(".txt")
            arquivo.write_text(texto, encoding="utf-8")
            eventos.append({"tipo_evento": "documento", "numero": f["numero"], "tipo": d["tipo"], "data": d["data"],
                            "descricao": d["nome"].split(" - ")[2].rsplit(".", 1)[0], "grau": "1º grau", "status": "aprovado",
                            "texto_arquivo": str(arquivo)})
        return eventos

    def test_resultado_e_valores_batem_com_a_ficha(self):
        fichas = ficticio.gerar_carteira(60, semente=5)
        coletor = simulado.ColetorSimulado(fichas, semente=1, taxa_falha=0, pasta=isolamento.TMP / "julgamento-sim")
        com_resultado = comparados = 0
        for f in fichas:
            sugestoes = julgamento.sugerir(ficha.nova_ficha(f["numero"], **{
                c: ficha.obter(f, c) for c in ("valor_causa", "polo_cliente", "momento_atual", "situacao") if ficha.obter(f, c)}),
                self.eventos_do_coletor(coletor, f), usar_relatorio=False)
            esperado = ficha.obter(f, "resultado")
            self.assertEqual(valor(sugestoes, "resultado"), esperado, f["numero"])
            com_resultado += esperado is not None
            if esperado == "Acordo" and ficha.obter(f, "valor_acordo"):
                comparados += 1
                self.assertEqual(valor(sugestoes, "valor_estimado"), ficha.obter(f, "valor_acordo"))
        self.assertGreater(com_resultado, 10)
        self.assertGreater(comparados, 0)


class TestEventosDoRelatorio(CasoBase):
    def test_divide_o_texto_por_data(self):
        f = nova()
        f["linha_de_base"] = {"data_base": "2026-09-18", "arquivo": "x.docx", "ultimo_andamento": None,
                              "andamentos_texto": "Em 10/03/2026 foi marcada audiência para 25/04/2026, às 10h. "
                                                  "18/06/2026 - Foi proferida sentença julgando procedente o pedido."}
        f["ultimo_texto_gravado"] = {"data_base": "2026-10-07", "arquivo": "x.docx",
                                     "texto": "Em 01/10/2026 foi interposta apelação."}
        eventos = julgamento.eventos_do_relatorio(f)
        self.assertEqual([e["data"] for e in eventos], ["2026-03-10", "2026-06-18", "2026-10-01"])
        self.assertIn("25/04/2026", eventos[0]["titulo"])  # a data dentro da frase não divide o texto
        self.assertTrue(all(e["status"] == "aprovado" and e["tipo_evento"] == "texto_relatorio" for e in eventos))
        s = self.sugerir(f, [])
        self.assertEqual(valor(s, "resultado"), "Procedente")
        self.assertIn("recurso pendente", self.ressalvas(s, "probabilidade"))  # a apelação está no último texto gravado

    def test_sem_texto_nao_ha_eventos(self):
        self.assertEqual(julgamento.eventos_do_relatorio(nova()), [])


class TestAvisos(CasoBase):
    def test_avisos_tem_o_formato_do_contrato(self):
        _, avisos = julgamento.sugerir_com_avisos(encerrada(nova(causa=None)), [])
        self.assertTrue(avisos)
        for a in avisos:
            self.assertEqual(set(a), {"nivel", "codigo", "onde", "mensagem", "candidatos"})
            self.assertIn(a["nivel"], ("info", "atencao", "erro"))
            self.assertEqual(a["onde"], NUM)

    def test_evento_malformado_nao_quebra(self):
        s = self.sugerir(nova(), [None, "texto", {}, {"status": "aprovado"}, {"status": "aprovado", "data": "lixo", "titulo": 5}])
        self.assertIn("probabilidade", s)


if __name__ == "__main__":
    unittest.main()
