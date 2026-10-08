"""Vocabulários controlados dos relatórios, normalização de rótulos soltos e momento atual por regra.

Os relatórios do escritório escrevem a mesma coisa de jeitos diferentes
("Reversão Justa Causa", "Reversão da justa causa.", "Parcialmente procedente.").
Cada vocabulário abaixo tem os valores canônicos e, por valor, sinônimos
conhecidos. normalizar(vocabulario, texto) devolve o canônico ou None: nunca
adivinha quando há mais de um candidato.

Uso básico
    taxonomia.normalizar("materia", "Horas extras")            -> "Horas extras e reflexos"
    taxonomia.normalizar("resultado", "Parcial procedência.")  -> "Parcialmente procedente"
    taxonomia.sugerir("materia", "reversao de justa")          -> ["Reversão de justa causa"]   (para avisar o usuário)
    taxonomia.normalizar_momento("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)")
                                                               -> ("CUMPRIMENTO DE SENTENÇA", "HONORÁRIOS SUSPENSOS")
    taxonomia.momento_por_regras(movimentos)                   -> ("AGUARDANDO SENTENÇA", 'Movimento de ...')  ou (None, None)

Como o rótulo é comparado
    1) tira acento, caixa e pontuação (tudo que não é letra ou número vira espaço);
    2) igualdade com o valor canônico ou com um sinônimo;
    3) senão, o rótulo contém (ou está contido em) exatamente UM valor/sinônimo, com pelo menos 6 letras;
       quando a mesma frase casa com dois sinônimos, um dentro do outro ("improcedente" e "procedente"),
       vale o MAIOR (o mais específico); dois candidatos diferentes e independentes continuam ambíguos
       (None). Rótulo menor que 4 letras nunca casa por trecho.

Momento atual com qualificador
    O modelo A escreve "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)". O qualificador entre parênteses
    é opcional e não faz parte do vocabulário: normalizar("momento_atual", ...) ignora o parêntese final e
    normalizar_momento() devolve os dois pedaços (qualificador em maiúsculas). formatar_momento() faz o caminho
    inverso. momento_ativo() e categoria_do_momento() aceitam o texto com qualificador.

Sinônimos editáveis por projeto (sobreposição)
    Cada relatório pode ter projetos/<slug>/taxonomia.json, que ACRESCENTA sinônimos aos vocabulários
    (nunca remove nem renomeia valor canônico). Formato:

        {"versao": 1,
         "sinonimos": {"materia": {"Dano moral": ["dano extrapatrimonial", "abalo moral"]},
                       "momento_atual": {"AGUARDANDO SENTENÇA": ["fase de sentença"]}}}

    - taxonomia.carregar(projeto=None)    lê a sobreposição do relatório `projeto` (slug) e a deixa em uso;
                                          sem argumento, acompanha o relatório ativo (comum.PROJETO). Devolve o
                                          dicionário {vocabulário: {canônico: [sinônimos]}}. O arquivo é relido
                                          sozinho quando muda, então editar à mão também vale.
    - taxonomia.adicionar_sinonimo(vocab, canonico, sinonimo, projeto=None)
                                          grava no taxonomia.json e passa a valer na hora. Devolve
                                          {"adicionado": bool, "aviso": None | Aviso}; recusa (com aviso de
                                          código estável) sinônimo vazio, vocabulário/valor desconhecido,
                                          sinônimo que já pertence a OUTRO valor (sinonimo_em_conflito),
                                          repetido (sinonimo_ja_existe) e arquivo ilegível (taxonomia_ilegivel;
                                          o arquivo nunca é sobrescrito nesse caso).
    - taxonomia.remover_sinonimo(...)     desfaz um sinônimo da sobreposição (os da base não se removem).
    - taxonomia.avisos_de_sobreposicao()  avisos da última leitura do arquivo (entradas ignoradas, arquivo ilegível).
    Quem usa o painel: a sobreposição é por processo do computador (estado do módulo), como o relatório ativo.

Momento atual por regra (sem IA)
    momento_por_regras(movimentos, janela=30) olha os movimentos mais recentes (texto do tribunal, no formato de
    ResultadoColeta: {"data","texto","grau","chave"}; também aceita texto puro) e escolhe um valor do vocabulário
    MOMENTO_ATUAL, ou devolve (None, None) quando as regras não bastam (a IA fica com a síntese, WS-5).
    Ordem esperada: cronológica (datas iguais mantêm a ordem recebida; o último da lista é o mais recente).
    Do mais recente para o mais antigo, cada movimento cai em UMA das classes da tabela REGRAS_DE_MOMENTO:
      estado    define o momento ("Conclusos para julgamento" -> AGUARDANDO SENTENÇA); fim da busca;
      ruido     não muda a fase (juntada de documento, expedição, publicação de intimação...); segue adiante;
      decisao   despacho/decisão interlocutória: não define o momento, mas "consome" os "conclusos para
                despacho/decisão" mais antigos (o juiz já decidiu); segue adiante;
      parar     a fase mudou mas as regras não sabem para quê (audiência realizada, réplica, desarquivamento);
                devolve None em vez de olhar mais para trás e acertar o momento ERRADO;
      conclusos "conclusos para ..." vale como estado, a menos que uma decisão mais nova já o tenha consumido.
    Movimento sem nenhuma regra também para a busca (None): na dúvida, não adivinha.
    Sentença publicada sem o movimento de julgamento por perto vira AGUARDANDO PRAZO RECURSAL.
    A evidência é um texto com a data, o movimento e a regra, para a tela de revisão.
    Limites conhecidos: a tabela foi escrita sobre os textos de movimentos.json e do coletor simulado; os textos
    reais de cada tribunal variam e as regras só se calibram no piloto. Ver docs/fase2/RFC-momento-qualificador.md.
"""
import copy
import difflib
import json
import re

import comum
from comum import normalizar as _norm


def _chave(texto):
    """Comparação tolerante: sem acento, sem caixa; tudo que não é letra ou número vira um espaço."""
    return re.sub(r"[^a-z0-9]+", " ", _norm(str(texto or ""))).strip()


# canônico -> sinônimos (além do próprio canônico)
POLO = {"ativo": ("autor", "autora", "autor a", "requerente", "exequente", "reclamante", "apelante", "impetrante",
                  "demandante"),
        "passivo": ("reu", "re", "reu a", "requerido", "requerida", "executado", "executada", "reclamado", "reclamada",
                    "apelado", "apelada", "impetrado", "demandado", "demandada")}

SITUACAO = {"Ativo": ("em andamento", "tramitando", "ativa", "em tramitacao", "em curso", "aberto", "vigente"),
            "Encerrado": ("arquivado", "baixado", "baixa definitiva", "finalizado", "encerrada", "arquivada", "baixada",
                          "finalizada", "transitado em julgado", "concluido", "extinto"),
            "Suspenso": ("sobrestado", "suspensa", "sobrestada", "em suspensao")}

GRAUS = ("1º grau", "2º grau", "TST")      # graus dos eventos (campo `grau`); o TST vem do DataJud (índice tst)
FASE = {"Conhecimento": ("primeiro grau", "1o grau", "fase de conhecimento", "instrucao", "primeira instancia"),
        "Recurso": ("recursal", "2o grau", "segundo grau", "fase recursal", "segunda instancia", "em grau de recurso"),
        "Execução": ("execucao", "cumprimento de sentenca", "cumprimento", "liquidacao", "fase de execucao",
                     "fase de cumprimento", "execucao de sentenca")}

RESULTADO = {"Procedente": ("procedencia", "condenacao", "procedentes", "julgado procedente", "pedido procedente",
                            "procedente o pedido"),
             "Parcialmente procedente": ("parcial procedencia", "procedencia parcial", "parcialmente procedente",
                                         "procedente em parte", "parcialmente procedentes", "procedencia em parte",
                                         "julgado parcialmente procedente", "parcial procedente"),
             "Improcedente": ("improcedencia", "improcedentes", "julgado improcedente", "pedido improcedente",
                              "improcedente o pedido"),
             "Acordo": ("transacao", "homologado acordo", "acordo homologado", "conciliacao", "acordo judicial",
                        "composicao amigavel", "acordo celebrado"),
             "Extinto sem resolução de mérito": ("extinto", "extinta", "extincao", "extinto sem merito",
                                                 "sem resolucao de merito", "extinto sem julgamento do merito",
                                                 "extinto sem resolucao do merito", "sem julgamento de merito",
                                                 "extincao sem resolucao de merito"),
             "Arquivado / desistência": ("desistencia", "arquivamento", "arquivado", "desistencia homologada",
                                         "homologada a desistencia", "arquivamento definitivo",
                                         "arquivado definitivamente", "desistencia da acao"),
             "Incompetência declarada": ("incompetencia", "incompetencia territorial declarada",
                                         "incompetencia territorial", "declarada a incompetencia",
                                         "incompetencia absoluta", "declinio de competencia",
                                         "remetido ao juizo competente")}

PROBABILIDADE = {"Possível": ("possivel",), "Provável": ("provavel",), "Remota": ("remoto", "remota")}

AREA = {"Trabalhista": ("trabalho", "direito do trabalho", "justica do trabalho", "laboral", "reclamacao trabalhista"),
        "Cível": ("civel", "civil", "direito civil", "justica comum"),
        "Consumidor": ("consumo", "direito do consumidor", "relacao de consumo", "juizado especial"),
        "Tributário": ("tributario", "fiscal", "direito tributario", "execucao fiscal"),
        "Administrativo": ("direito administrativo", "direito publico", "servidor publico"),
        "Ambiental": ("direito ambiental",),
        "Empresarial": ("direito empresarial", "societario", "comercial", "direito comercial", "recuperacao judicial",
                        "falencia"),
        "Imobiliário": ("imobiliario", "direito imobiliario"),
        "Contratual": ("direito contratual",),
        "Processual": ("direito processual",),
        "Previdenciário": ("previdenciario", "direito previdenciario", "beneficio previdenciario"),
        "Família e Sucessões": ("familia", "sucessoes", "direito de familia", "inventario", "divorcio")}

TIPO_VINCULO = {"recurso": ("apelacao", "recurso especial", "recurso extraordinario", "recurso ordinario",
                            "recurso de revista", "embargos de declaracao", "agravo interno"),
                "agravo": ("agravo de instrumento", "agravo de peticao"),
                "apenso": ("apensado", "incidente", "embargos a execucao", "embargos do devedor", "cautelar",
                           "impugnacao ao cumprimento"),
                "reajuizamento": ("reajuizada", "reajuizado", "nova acao", "repropositura"),
                "mesma_acao": ("mesma acao", "remetida por incompetencia", "redistribuido por incompetencia",
                               "declinio de competencia")}

# "Momento atual do processo" (quadro-resumo do modelo A). categoria: onde o processo está.
# ativo=False: o processo não conta como ativo nos indicadores.
MOMENTO_ATUAL = {
    "AGUARDANDO CITAÇÃO": ("conhecimento", True),
    "AGUARDANDO CITAÇÃO DO RÉU": ("conhecimento", True),
    "AGUARDANDO CITAÇÃO DOS EXECUTADOS": ("execução", True),
    "AGUARDANDO CITAÇÃO DO EXECUTADO": ("execução", True),
    "AGUARDANDO PAGAMENTO DO SALDO DEVEDOR": ("execução", True),
    "AGUARDANDO CITAÇÃO POR EDITAL": ("conhecimento", True),
    "AGUARDANDO INTIMAÇÃO DO RÉU": ("conhecimento", True),
    "AGUARDANDO CONTESTAÇÃO": ("conhecimento", True),
    "AGUARDANDO RÉPLICA": ("conhecimento", True),
    "AGUARDANDO AUDIÊNCIA": ("conhecimento", True),
    "AGUARDANDO PROVA PERICIAL": ("conhecimento", True),
    "AGUARDANDO SENTENÇA": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO EM 1º GRAU": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO": ("conhecimento", True),
    "CONCLUSOS PARA DECISÃO": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO DA APELAÇÃO": ("recurso", True),
    "AGUARDANDO JULGAMENTO DO RECURSO": ("recurso", True),
    "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO": ("recurso", True),
    "CUMPRIMENTO DE SENTENÇA": ("execução", True),
    "AGUARDANDO CONVERSÃO EM PENHORA": ("execução", True),
    "AGUARDANDO PAGAMENTO": ("execução", True),
    "AGUARDANDO PARCELAMENTO DAS CUSTAS": ("conhecimento", True),
    "AGUARDANDO MANIFESTAÇÃO DE TERCEIROS": ("conhecimento", True),
    "AGUARDANDO SUBSTITUIÇÃO PROCESSUAL": ("conhecimento", True),
    "SUSPENSO": ("suspenso", True),
    "TRÂNSITO EM JULGADO": ("encerrado", False),
    "PROCESSO ARQUIVADO": ("encerrado", False),
    "ACORDO HOMOLOGADO": ("encerrado", False),
    "EXTINTO SEM RESOLUÇÃO DE MÉRITO": ("encerrado", False),
    # --- acrescentados pelo WS-1 (a calibrar no piloto com os relatórios reais) ---
    "AGUARDANDO DESPACHO": ("conhecimento", True),
    "AGUARDANDO MANIFESTAÇÃO DAS PARTES": ("conhecimento", True),
    "AGUARDANDO PRAZO RECURSAL": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO DOS EMBARGOS DE DECLARAÇÃO": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO DO RECURSO ORDINÁRIO": ("recurso", True),
    "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA": ("recurso", True),
    "AGUARDANDO JULGAMENTO DO RECURSO ESPECIAL": ("recurso", True),
    "AGUARDANDO JULGAMENTO DO RECURSO EXTRAORDINÁRIO": ("recurso", True),
    "AGUARDANDO JULGAMENTO DO AGRAVO DE PETIÇÃO": ("recurso", True),
    "AGUARDANDO JULGAMENTO DO AGRAVO INTERNO": ("recurso", True),
    "LIQUIDAÇÃO DE SENTENÇA": ("execução", True),
    "AGUARDANDO PAGAMENTO DE PRECATÓRIO": ("execução", True),
    "REMETIDO AO JUÍZO COMPETENTE": ("encerrado", False),
}
MOMENTO_SINONIMOS = {
    "AGUARDANDO CITAÇÃO DO EXECUTADO": ("aguarda citacao do executado", "aguardando a citacao do executado",
                                        "citacao do executado pendente"),
    "AGUARDANDO PAGAMENTO DO SALDO DEVEDOR": ("aguarda pagamento do saldo", "aguardando pagamento do saldo remanescente",
                                              "saldo devedor pendente"),
    "AGUARDANDO CITAÇÃO": ("aguarda citacao", "aguardando a citacao", "citacao pendente", "pendente de citacao"),
    "AGUARDANDO CITAÇÃO DO RÉU": ("aguarda citacao do reu", "aguardando citacao da re", "aguardando citacao da parte re"),
    "AGUARDANDO CITAÇÃO POR EDITAL": ("citacao por edital", "aguardando edital de citacao"),
    "AGUARDANDO CONTESTAÇÃO": ("aguarda contestacao", "aguardando apresentacao de contestacao", "aguardando defesa",
                               "prazo para contestar"),
    "AGUARDANDO RÉPLICA": ("aguarda replica", "aguardando impugnacao a contestacao", "prazo para replica"),
    "AGUARDANDO AUDIÊNCIA": ("aguarda audiencia", "audiencia designada", "audiencia marcada",
                             "aguardando audiencia de conciliacao", "aguardando audiencia de instrucao"),
    "AGUARDANDO PROVA PERICIAL": ("aguarda pericia", "aguardando pericia", "aguardando laudo pericial",
                                  "pericia designada"),
    "AGUARDANDO SENTENÇA": ("aguarda sentenca", "conclusos para sentenca", "concluso para sentenca",
                            "conclusos para julgamento", "aguardando prolacao de sentenca", "aguardando julgamento de sentenca"),
    "AGUARDANDO JULGAMENTO EM 1º GRAU": ("aguardando julgamento em primeiro grau", "aguardando julgamento de 1o grau"),
    "CONCLUSOS PARA DECISÃO": ("concluso para decisao", "autos conclusos para decisao"),
    "AGUARDANDO JULGAMENTO DA APELAÇÃO": ("aguardando julgamento de apelacao", "aguarda julgamento da apelacao",
                                          "apelacao pendente de julgamento",
                                          "aguardando julgamento do recurso de apelacao"),
    "AGUARDANDO JULGAMENTO DO RECURSO": ("aguarda julgamento do recurso", "recurso pendente de julgamento"),
    "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO": ("aguardando julgamento do agravo de instrumento",
                                                       "aguarda julgamento do agravo de instrumento",
                                                       "agravo de instrumento pendente de julgamento"),
    "CUMPRIMENTO DE SENTENÇA": ("em cumprimento de sentenca", "fase de cumprimento de sentenca",
                                "cumprimento de sentenca em andamento", "execucao de sentenca", "fase de execucao",
                                "em execucao"),
    "AGUARDANDO PAGAMENTO": ("aguarda pagamento", "aguardando pagamento do debito", "aguardando pagamento do acordo"),
    "SUSPENSO": ("processo suspenso", "suspensao", "sobrestado", "processo sobrestado"),
    "TRÂNSITO EM JULGADO": ("transitado em julgado", "transitou em julgado", "com transito em julgado",
                            "transito em julgado certificado"),
    "PROCESSO ARQUIVADO": ("arquivado", "arquivamento", "arquivado definitivamente", "baixa definitiva",
                           "baixado e arquivado", "arquivamento definitivo", "processo arquivado definitivamente"),
    "ACORDO HOMOLOGADO": ("acordo", "acordo judicial", "acordo homologado em juizo", "homologado acordo",
                          "acordo celebrado e homologado", "transacao homologada"),
    "EXTINTO SEM RESOLUÇÃO DE MÉRITO": ("extinto", "extinto sem resolucao do merito", "extinto sem julgamento do merito",
                                        "extincao sem resolucao de merito", "processo extinto"),
    "AGUARDANDO DESPACHO": ("aguarda despacho", "conclusos para despacho", "concluso para despacho"),
    "AGUARDANDO MANIFESTAÇÃO DAS PARTES": ("aguarda manifestacao das partes", "aguardando manifestacao das partes",
                                           "prazo para manifestacao"),
    "AGUARDANDO PRAZO RECURSAL": ("prazo recursal", "aguardando prazo para recurso", "aguardando prazo de recurso",
                                  "sentenca publicada", "aguardando decurso do prazo recursal"),
    "AGUARDANDO JULGAMENTO DOS EMBARGOS DE DECLARAÇÃO": ("embargos de declaracao pendentes",
                                                         "aguardando julgamento de embargos de declaracao"),
    "AGUARDANDO JULGAMENTO DO RECURSO ORDINÁRIO": ("aguardando julgamento de recurso ordinario",
                                                   "recurso ordinario pendente de julgamento"),
    "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA": ("aguardando julgamento de recurso de revista",
                                                    "recurso de revista pendente"),
    "AGUARDANDO JULGAMENTO DO RECURSO ESPECIAL": ("aguardando julgamento de recurso especial",
                                                  "recurso especial pendente"),
    "AGUARDANDO JULGAMENTO DO RECURSO EXTRAORDINÁRIO": ("aguardando julgamento de recurso extraordinario",
                                                        "recurso extraordinario pendente"),
    "AGUARDANDO JULGAMENTO DO AGRAVO DE PETIÇÃO": ("agravo de peticao pendente",
                                                   "aguardando julgamento de agravo de peticao"),
    "AGUARDANDO JULGAMENTO DO AGRAVO INTERNO": ("agravo interno pendente", "aguardando julgamento de agravo interno"),
    "LIQUIDAÇÃO DE SENTENÇA": ("em liquidacao", "fase de liquidacao", "liquidacao"),
    "AGUARDANDO PAGAMENTO DE PRECATÓRIO": ("precatorio expedido", "aguardando precatorio", "aguardando rpv",
                                           "precatorio"),
    "REMETIDO AO JUÍZO COMPETENTE": ("incompetencia declarada", "declinada a competencia",
                                     "remetido por incompetencia"),
}

# Matérias dos pedidos. valor: (tema, classe, entra nos rankings). Valores canônicos existentes NÃO se removem
# (WS-16 usa este vocabulário como o único aceito no prompt dos pedidos; fora dele, "Outros" + sugestão).
MATERIA = {
    "Horas extras e reflexos": ("Jornada", "Mérito", True),
    "Intervalo intra/interjornada": ("Jornada", "Mérito", True),
    "Repouso semanal / feriados": ("Jornada", "Mérito", True),
    "Adicional noturno": ("Jornada", "Mérito", True),
    "Tempo de espera": ("Jornada", "Mérito", True),
    "Controle de jornada": ("Jornada", "Processual", False),
    "Adicional de insalubridade": ("Saúde e segurança", "Mérito", True),
    "Adicional de periculosidade": ("Saúde e segurança", "Mérito", True),
    "Dano material / pensionamento": ("Saúde e segurança", "Mérito", True),
    "Dano estético": ("Saúde e segurança", "Mérito", True),
    "Doença ocupacional / acidente (declaratório)": ("Saúde e segurança", "Mérito", True),
    "Estabilidade (indenização)": ("Estabilidades e afastamentos", "Mérito", True),
    "Limbo previdenciário": ("Estabilidades e afastamentos", "Mérito", True),
    "Salário-maternidade (indenização)": ("Estabilidades e afastamentos", "Mérito", True),
    "Acúmulo / desvio de função": ("Remuneração e benefícios", "Mérito", True),
    "Dano moral": ("Dano moral", "Mérito", True),
    "Honorários advocatícios": ("Acessórios", "Acessório", False),
    "Encargos (INSS/IR/custas) no valor da causa": ("Acessórios", "Acessório", False),
    "Consignação de verbas rescisórias": ("Acessórios", "Processual", False),
    "Outros": ("Acessórios", "Acessório", False),
    # --- acrescentadas pelo WS-1: trabalhistas ---
    "Reconhecimento de vínculo empregatício": ("Vínculo e rescisão", "Mérito", True),
    "Reversão de justa causa": ("Vínculo e rescisão", "Mérito", True),
    "Rescisão indireta": ("Vínculo e rescisão", "Mérito", True),
    "Verbas rescisórias": ("Vínculo e rescisão", "Mérito", True),
    "Aviso prévio": ("Vínculo e rescisão", "Mérito", True),
    "Multa do art. 467 da CLT": ("Vínculo e rescisão", "Mérito", True),
    "Multa do art. 477 da CLT": ("Vínculo e rescisão", "Mérito", True),
    "Seguro-desemprego (indenização)": ("Vínculo e rescisão", "Mérito", True),
    "FGTS e multa de 40%": ("Remuneração e benefícios", "Mérito", True),
    "Diferenças salariais / equiparação": ("Remuneração e benefícios", "Mérito", True),
    "Comissões e prêmios": ("Remuneração e benefícios", "Mérito", True),
    "Gratificações / PLR / bônus": ("Remuneração e benefícios", "Mérito", True),
    "Benefícios (vale-alimentação, plano de saúde)": ("Remuneração e benefícios", "Mérito", True),
    "Férias e 13º salário": ("Remuneração e benefícios", "Mérito", True),
    "Adicional de transferência": ("Remuneração e benefícios", "Mérito", True),
    "Descontos indevidos": ("Remuneração e benefícios", "Mérito", True),
    "Assédio moral": ("Dano moral", "Mérito", True),
    "Responsabilidade subsidiária / solidária": ("Responsabilidade", "Mérito", True),
    "Justiça gratuita": ("Acessórios", "Processual", False),
    # --- acrescentadas pelo WS-1: cíveis ---
    "Cobrança / inadimplemento contratual": ("Contratos e obrigações", "Mérito", True),
    "Rescisão contratual e restituição": ("Contratos e obrigações", "Mérito", True),
    "Revisão contratual": ("Contratos e obrigações", "Mérito", True),
    "Obrigação de fazer / não fazer": ("Contratos e obrigações", "Mérito", True),
    "Indenização por danos materiais": ("Responsabilidade civil", "Mérito", True),
    "Lucros cessantes": ("Responsabilidade civil", "Mérito", True),
    "Repetição de indébito": ("Consumidor e crédito", "Mérito", True),
    "Inexigibilidade de débito / negativação": ("Consumidor e crédito", "Mérito", True),
    "Posse e propriedade": ("Posse e locação", "Mérito", True),
    "Locação e despejo": ("Posse e locação", "Mérito", True),
    "Tutela de urgência": ("Tutelas e incidentes", "Processual", False),
}
MATERIA_SINONIMOS = {
    "Horas extras e reflexos": ("horas extras", "horas extra", "hora extra", "sobrejornada", "horas extraordinarias",
                                "labor extraordinario", "reflexos de horas extras"),
    "Intervalo intra/interjornada": ("intervalo intrajornada", "intervalo interjornada", "intrajornada", "interjornada",
                                     "intervalo para refeicao", "supressao de intervalo"),
    "Repouso semanal / feriados": ("repouso semanal remunerado", "rsr", "dsr", "domingos e feriados",
                                   "feriados em dobro"),
    "Adicional noturno": ("hora noturna", "horas noturnas", "trabalho noturno"),
    "Tempo de espera": ("horas de espera", "tempo a disposicao", "tempo a disposicao do empregador"),
    "Controle de jornada": ("cartao de ponto", "registro de ponto", "controle de ponto"),
    "Adicional de insalubridade": ("insalubridade", "adicional insalubridade", "adicional insalubre"),
    "Adicional de periculosidade": ("periculosidade", "adicional periculosidade", "adicional de periculo"),
    "Dano material / pensionamento": ("pensionamento", "pensao mensal", "pensao vitalicia",
                                      "indenizacao material por acidente"),
    "Dano estético": ("danos esteticos", "dano estetico"),
    "Doença ocupacional / acidente (declaratório)": ("doenca ocupacional", "acidente de trabalho", "acidente do trabalho",
                                                     "doenca profissional", "doenca do trabalho", "nexo causal"),
    "Estabilidade (indenização)": ("estabilidade", "gestante", "estabilidade gestante", "estabilidade da gestante",
                                   "estabilidade provisoria", "estabilidade acidentaria", "garantia de emprego"),
    "Limbo previdenciário": ("limbo", "limbo juridico previdenciario", "alta previdenciaria"),
    "Salário-maternidade (indenização)": ("salario maternidade", "salario maternidade indenizado"),
    "Acúmulo / desvio de função": ("acumulo de funcao", "acumulo de funcoes", "desvio de funcao", "plus salarial",
                                   "acumulo funcional", "diferencas por desvio de funcao"),
    "Dano moral": ("danos morais", "indenizacao por dano moral", "indenizacao por danos morais",
                   "dano extrapatrimonial", "danos extrapatrimoniais"),
    "Assédio moral": ("assedio", "assedio sexual", "assedio organizacional"),
    "Honorários advocatícios": ("honorarios", "honorarios de sucumbencia", "honorarios sucumbenciais", "sucumbencia"),
    "Encargos (INSS/IR/custas) no valor da causa": ("encargos", "encargos no valor da causa", "inss e ir",
                                                    "contribuicoes previdenciarias"),
    "Consignação de verbas rescisórias": ("consignacao em pagamento", "acao de consignacao"),
    "Outros": ("outros pedidos", "demais pedidos", "diversos"),
    "Reconhecimento de vínculo empregatício": ("vinculo empregaticio", "reconhecimento de vinculo", "vinculo de emprego",
                                               "reconhecimento do vinculo de emprego"),
    "Reversão de justa causa": ("reversao justa causa", "reversao da justa causa", "reversao da dispensa por justa causa",
                                "nulidade da justa causa", "justa causa"),
    "Rescisão indireta": ("rescisao indireta do contrato", "despedida indireta", "rescisao indireta do contrato de trabalho"),
    "Verbas rescisórias": ("rescisorias", "saldo de salario", "verbas da rescisao", "diferencas rescisorias",
                           "parcelas rescisorias"),
    "Aviso prévio": ("aviso previo indenizado", "aviso previo proporcional"),
    "Multa do art. 467 da CLT": ("multa do art 467", "multa art 467", "multa do artigo 467", "multa 467",
                                 "art 467 da clt"),
    "Multa do art. 477 da CLT": ("multa do art 477", "multa art 477", "multa do artigo 477", "multa 477",
                                 "art 477 da clt"),
    "Seguro-desemprego (indenização)": ("seguro desemprego", "guias do seguro desemprego"),
    "FGTS e multa de 40%": ("fgts", "fgts 40", "multa de 40", "multa fundiaria", "diferencas de fgts",
                            "depositos de fgts"),
    "Diferenças salariais / equiparação": ("equiparacao salarial", "diferencas salariais", "isonomia salarial",
                                           "equiparacao"),
    "Comissões e prêmios": ("comissoes", "premios", "diferencas de comissoes"),
    "Gratificações / PLR / bônus": ("plr", "participacao nos lucros", "participacao nos lucros e resultados", "bonus",
                                    "gratificacao", "gratificacoes", "gratificacao de funcao"),
    "Benefícios (vale-alimentação, plano de saúde)": ("vale alimentacao", "vale refeicao", "cesta basica",
                                                       "plano de saude", "beneficios"),
    "Férias e 13º salário": ("ferias", "decimo terceiro", "decimo terceiro salario", "13o salario",
                              "ferias vencidas e proporcionais"),
    "Adicional de transferência": ("transferencia", "adicional transferencia"),
    "Descontos indevidos": ("devolucao de descontos", "descontos salariais", "descontos indevidos no salario"),
    "Responsabilidade subsidiária / solidária": ("responsabilidade subsidiaria", "responsabilidade solidaria",
                                                  "subsidiaria", "solidariedade", "grupo economico"),
    "Justiça gratuita": ("gratuidade da justica", "assistencia judiciaria gratuita", "beneficio da justica gratuita"),
    "Cobrança / inadimplemento contratual": ("cobranca", "inadimplemento contratual", "inadimplemento",
                                             "cobranca de divida", "acao de cobranca"),
    "Rescisão contratual e restituição": ("rescisao contratual", "distrato", "resolucao contratual",
                                          "restituicao de valores", "devolucao de valores"),
    "Revisão contratual": ("revisao de contrato", "revisional", "revisao de clausulas"),
    "Obrigação de fazer / não fazer": ("obrigacao de fazer", "obrigacao de nao fazer", "obrigacao de fazer e nao fazer"),
    "Indenização por danos materiais": ("danos materiais", "dano material", "indenizacao por dano material"),
    "Lucros cessantes": ("lucro cessante",),
    "Repetição de indébito": ("repeticao do indebito", "restituicao em dobro", "devolucao em dobro"),
    "Inexigibilidade de débito / negativação": ("inexigibilidade de debito", "declaracao de inexistencia de debito",
                                                 "negativacao indevida", "inscricao indevida",
                                                 "exclusao do nome dos cadastros"),
    "Posse e propriedade": ("reintegracao de posse", "imissao na posse", "usucapiao", "acao possessoria"),
    "Locação e despejo": ("despejo", "acao de despejo", "locacao", "cobranca de alugueis", "renovatoria"),
    "Tutela de urgência": ("tutela antecipada", "tutela provisoria", "liminar", "tutela cautelar"),
}

VOCABULARIOS = {
    "polo": POLO, "situacao": SITUACAO, "fase": FASE, "resultado": RESULTADO, "probabilidade": PROBABILIDADE,
    "area": AREA, "tipo_vinculo": TIPO_VINCULO,
    "momento_atual": {k: MOMENTO_SINONIMOS.get(k, ()) for k in MOMENTO_ATUAL},
    "materia": {k: MATERIA_SINONIMOS.get(k, ()) for k in MATERIA},
}

# Temas de matéria que só aparecem em ações cíveis (o resto é trabalhista; "Outros" serve às duas áreas).
TEMAS_CIVEIS = frozenset({"Contratos e obrigações", "Responsabilidade civil", "Consumidor e crédito",
                          "Posse e locação", "Tutelas e incidentes"})


def materias_da_area(area):
    """Matérias do vocabulário que fazem sentido na área ("Trabalhista" ou outra): trabalhistas e cíveis são
    separadas pelo tema (TEMAS_CIVEIS); "Outros", "Dano moral" e "Honorários advocatícios" servem às duas."""
    civel = area != "Trabalhista"
    comuns = {"Outros", "Dano moral", "Honorários advocatícios"}
    return [m for m, (tema, _, _) in MATERIA.items() if m in comuns or (tema in TEMAS_CIVEIS) == civel]


# ---------------------------------------------------------------- sobreposição por projeto

_PROJETO_FIXO = None     # slug escolhido em carregar(); None = acompanha o relatório ativo (comum.PROJETO)
_CACHE = {"arquivo": None, "mtime": None, "dados": {}, "avisos": []}
_INDICES = {}            # vocabulário -> (índice completo, formas da sobreposição); zerado quando o arquivo muda


def _aviso(nivel, codigo, onde, mensagem, candidatos=None):
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": list(candidatos or [])}


def _arquivo_da_sobreposicao(projeto=None):
    slug = projeto or _PROJETO_FIXO or comum.PROJETO
    return comum.PROJETOS_DIR / slug / "taxonomia.json" if slug else None


def _ler_sobreposicao(arquivo):
    """(dados validados {vocab: {canônico: [sinônimos]}}, avisos, bruto legível ou None)."""
    try:
        bruto = json.loads(arquivo.read_text(encoding="utf-8"))
        if not isinstance(bruto, dict):
            raise ValueError("o arquivo deve ser um objeto JSON")
    except (OSError, ValueError) as erro:
        return {}, [_aviso("erro", "taxonomia_ilegivel", str(arquivo.name),
                           f"Não consegui ler os sinônimos do relatório ({erro}). Eles foram ignorados.")], None
    dados, avisos = {}, []
    for vocab, mapa in (bruto.get("sinonimos") or {}).items():
        if vocab not in VOCABULARIOS or not isinstance(mapa, dict):
            avisos.append(_aviso("atencao", "sinonimo_de_vocabulario_desconhecido", str(vocab),
                                 f"Vocabulário desconhecido no taxonomia.json: {vocab!r}. Ignorado."))
            continue
        for canonico, lista in mapa.items():
            if canonico not in VOCABULARIOS[vocab] or not isinstance(lista, list):
                avisos.append(_aviso("atencao", "sinonimo_de_valor_desconhecido", f"{vocab}: {canonico}",
                                     f"Valor desconhecido em {vocab}: {canonico!r}. Ignorado."))
                continue
            dados.setdefault(vocab, {})[canonico] = [str(s) for s in lista if str(s).strip()]
    return dados, avisos, bruto


def _sobreposicao():
    """Sobreposição em uso (relê o arquivo quando ele muda)."""
    arquivo = _arquivo_da_sobreposicao()
    if arquivo is None:
        mtime = None
    else:
        try:
            mtime = arquivo.stat().st_mtime_ns
        except OSError:
            mtime = None
    if _CACHE["arquivo"] != arquivo or _CACHE["mtime"] != mtime:
        dados, avisos = ({}, []) if mtime is None else _ler_sobreposicao(arquivo)[:2]
        _CACHE.update(arquivo=arquivo, mtime=mtime, dados=dados, avisos=avisos)
        _INDICES.clear()
    return _CACHE["dados"]


def carregar(projeto=None):
    """Lê projetos/<projeto>/taxonomia.json e o deixa em uso (veja o cabeçalho). Sem `projeto`, acompanha o
    relatório ativo. Devolve {vocabulário: {canônico: [sinônimos]}} (vazio se não houver arquivo)."""
    global _PROJETO_FIXO
    _PROJETO_FIXO = projeto or None
    _CACHE.update(arquivo=None, mtime=None, dados={}, avisos=[])
    _INDICES.clear()
    return copy.deepcopy(_sobreposicao())


def avisos_de_sobreposicao():
    """Avisos da última leitura do taxonomia.json (arquivo ilegível, entradas ignoradas)."""
    _sobreposicao()
    return copy.deepcopy(_CACHE["avisos"])


def _indices(vocabulario):
    sobre = _sobreposicao()
    if vocabulario not in _INDICES:
        indice, extras = {}, {}
        for canonico, sinonimos in VOCABULARIOS[vocabulario].items():
            for forma in (canonico, *sinonimos):
                indice.setdefault(_chave(forma), set()).add(canonico)
        for canonico, sinonimos in sobre.get(vocabulario, {}).items():
            for forma in sinonimos:
                indice.setdefault(_chave(forma), set()).add(canonico)
                extras.setdefault(_chave(forma), set()).add(canonico)
        _INDICES[vocabulario] = (indice, extras)
    return _INDICES[vocabulario]


def adicionar_sinonimo(vocab, canonico, sinonimo, projeto=None):
    """Grava `sinonimo` para `canonico` em projetos/<slug>/taxonomia.json. Devolve {"adicionado", "aviso"}."""
    def recusa(nivel, codigo, mensagem, candidatos=None):
        return {"adicionado": False, "aviso": _aviso(nivel, codigo, f"{vocab}: {canonico}", mensagem, candidatos)}

    arquivo = _arquivo_da_sobreposicao(projeto)
    if vocab not in VOCABULARIOS:
        return recusa("erro", "vocabulario_desconhecido", f"Vocabulário desconhecido: {vocab!r}.")
    if canonico not in VOCABULARIOS[vocab]:
        return recusa("erro", "canonico_desconhecido", f"{canonico!r} não é um valor de {vocab}.",
                      sorted(VOCABULARIOS[vocab])[:10])
    chave = _chave(sinonimo)
    if not chave:
        return recusa("erro", "sinonimo_vazio", "O sinônimo está vazio.")
    if arquivo is None:
        return recusa("erro", "sem_projeto", "Nenhum relatório selecionado para guardar o sinônimo.")
    bruto, sobre = {"versao": 1, "sinonimos": {}}, {}
    if arquivo.exists():
        sobre, _, lido = _ler_sobreposicao(arquivo)
        if lido is None:
            return recusa("erro", "taxonomia_ilegivel", "O arquivo de sinônimos do relatório está ilegível; "
                          "não o alterei para não perder o que está nele.")
        bruto = lido
    indice = {}
    for c, sinonimos in VOCABULARIOS[vocab].items():
        for forma in (c, *sinonimos):
            indice.setdefault(_chave(forma), set()).add(c)
    for c, sinonimos in sobre.get(vocab, {}).items():
        for forma in sinonimos:
            indice.setdefault(_chave(forma), set()).add(c)
    donos = indice.get(chave, set())
    if donos - {canonico}:
        return recusa("atencao", "sinonimo_em_conflito",
                      f"{sinonimo!r} já significa outra coisa em {vocab}; não grudei em {canonico!r}.",
                      sorted(donos - {canonico}))
    if canonico in donos:
        return recusa("info", "sinonimo_ja_existe", f"{sinonimo!r} já é sinônimo de {canonico!r}.")
    destino = bruto.setdefault("sinonimos", {}).setdefault(vocab, {}).setdefault(canonico, [])
    destino.append(str(sinonimo).strip())
    bruto["versao"] = bruto.get("versao", 1)
    comum.save_json(arquivo, bruto)
    _CACHE.update(arquivo=None, mtime=None)   # força a releitura
    _INDICES.clear()
    return {"adicionado": True, "aviso": None}


def remover_sinonimo(vocab, canonico, sinonimo, projeto=None):
    """Desfaz um sinônimo gravado na sobreposição do relatório. Devolve {"removido", "aviso"}."""
    arquivo = _arquivo_da_sobreposicao(projeto)
    if arquivo is None or not arquivo.exists():
        return {"removido": False, "aviso": _aviso("info", "sinonimo_inexistente", f"{vocab}: {canonico}",
                                                   "Não há sinônimos gravados para este relatório.")}
    dados, _, bruto = _ler_sobreposicao(arquivo)
    if bruto is None:
        return {"removido": False, "aviso": _aviso("erro", "taxonomia_ilegivel", f"{vocab}: {canonico}",
                                                   "O arquivo de sinônimos está ilegível; não o alterei.")}
    lista = bruto.get("sinonimos", {}).get(vocab, {}).get(canonico, [])
    restantes = [s for s in lista if _chave(s) != _chave(sinonimo)]
    if len(restantes) == len(lista):
        return {"removido": False, "aviso": _aviso("info", "sinonimo_inexistente", f"{vocab}: {canonico}",
                                                   f"{sinonimo!r} não está entre os sinônimos gravados do relatório.")}
    bruto["sinonimos"][vocab][canonico] = restantes
    comum.save_json(arquivo, bruto)
    _CACHE.update(arquivo=None, mtime=None)
    _INDICES.clear()
    return {"removido": True, "aviso": None}


# ---------------------------------------------------------------- normalização

_QUALIFICADOR = re.compile(r"^\s*(.*?)\s*\(([^()]*)\)\s*[.;]?\s*$")


def _separar_qualificador(texto):
    """'X (Y)' -> ('X', 'Y' em maiúsculas); sem parêntese final: (texto, None)."""
    texto = str(texto or "")
    m = _QUALIFICADOR.match(texto)
    if m and m[1].strip():
        qualificador = re.sub(r"\s+", " ", m[2]).strip().upper()
        return m[1].strip(), qualificador or None
    return texto.strip(), None


def valores(nome_vocabulario):
    """Valores canônicos do vocabulário, na ordem em que foram definidos."""
    return list(VOCABULARIOS[nome_vocabulario])


def normalizar(nome_vocabulario, texto):
    """Valor canônico do vocabulário para um rótulo solto, ou None.

    1) igualdade depois de tirar acento, caixa e pontuação (sinônimos do relatório valem primeiro);
    2) o rótulo contém, ou está contido em, exatamente UM valor/sinônimo (pelo menos 6 letras); quando dois
       sinônimos casam e um está dentro do outro, vale o maior; rótulo com menos de 4 letras não casa por trecho;
    3) ambíguo ou desconhecido: None (quem chama decide: avisar e deixar vazio).

    No vocabulário "momento_atual" o parêntese final (qualificador) é ignorado.
    """
    if nome_vocabulario == "momento_atual":
        texto = _separar_qualificador(texto)[0]
    chave = _chave(texto)
    if not chave:
        return None
    indice, extras = _indices(nome_vocabulario)
    if chave in extras and len(extras[chave]) == 1:
        return next(iter(extras[chave]))
    if chave in indice:
        achados = indice[chave]
        return next(iter(achados)) if len(achados) == 1 else None
    # formas (>= 6 letras) dentro do rótulo; dentre elas, só as que não estão dentro de outra forma que também casou
    dentro = [f for f in indice if len(f) >= 6 and f in chave]
    maximais = [f for f in dentro if not any(f != g and f in g for g in dentro)]
    candidatos = {c for f in maximais for c in indice[f]}
    if len(chave) >= 4:  # o rótulo é um pedaço de um valor/sinônimo
        candidatos |= {c for f, cs in indice.items() if len(f) >= 6 and chave in f and f not in dentro for c in cs}
    return next(iter(candidatos)) if len(candidatos) == 1 else None


def sugerir(nome_vocabulario, texto, limite=3):
    """Valores canônicos parecidos com um rótulo que não foi reconhecido (para avisar o usuário)."""
    chave = _chave(_separar_qualificador(texto)[0] if nome_vocabulario == "momento_atual" else texto)
    if not chave:
        return []
    indice, _ = _indices(nome_vocabulario)
    achados = []
    for forma in difflib.get_close_matches(chave, list(indice), n=limite * 3, cutoff=0.6):
        for c in sorted(indice[forma]):
            if c not in achados:
                achados.append(c)
    return achados[:limite]


def normalizar_momento(texto):
    """(momento canônico, qualificador) de um texto como 'CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)'.
    Sem qualificador: (momento, None). Momento desconhecido ou ambíguo: (None, None)."""
    base, qualificador = _separar_qualificador(texto)
    momento = normalizar("momento_atual", base)
    return (momento, qualificador) if momento else (None, None)


def formatar_momento(momento, qualificador=None):
    """'CUMPRIMENTO DE SENTENÇA' + 'HONORÁRIOS SUSPENSOS' -> 'CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)'."""
    qualificador = re.sub(r"\s+", " ", str(qualificador or "")).strip().upper()
    return f"{momento} ({qualificador})" if momento and qualificador else (momento or "")


def _dados_do_momento(momento):
    if momento in MOMENTO_ATUAL:
        return MOMENTO_ATUAL[momento]
    return MOMENTO_ATUAL.get(_separar_qualificador(momento)[0].upper())


def momento_ativo(momento):
    """True/False se o momento atual conta como processo ativo; None se desconhecido.
    Aceita o texto com qualificador entre parênteses."""
    dados = _dados_do_momento(momento)
    return dados[1] if dados else None


def categoria_do_momento(momento):
    dados = _dados_do_momento(momento)
    return dados[0] if dados else None


# ---------------------------------------------------------------- momento atual por regra

# Cada regra: (nome, padrão sobre o texto SEM acento e em minúsculas, efeito, destino)
# Efeitos: estado | ruido | decisao | parar | conclusos | julgamento (estado que também vale como "houve julgamento")
#          | sentenca_publicada | recurso (estado recursal; o tipo do recurso é refinado olhando para trás).
# A PRIMEIRA regra que casa vence: por isso as mais específicas vêm antes das gerais.
_REC = "RECURSO_GENERICO"
REGRAS_DE_MOMENTO = [
    # --- o que reabre ou muda a fase sem dizer para onde (a busca para) ---
    ("desarquivamento", r"\bdesarquiv", "parar", None),
    ("arquivamento_provisorio", r"arquivad[oa]s? provisori|arquivamento provisorio", "parar", None),
    ("fim_da_suspensao", r"(encerrada|levantada|revogada|cessada|fim d[ea]|retomad[oa] o curso)\b.*suspens|"
                          r"voltou a tramitar|levantamento da suspensao", "parar", None),
    # --- encerramentos ---
    ("transito_em_julgado", r"transit(o|ou|ado|ada) em julgado|certidao de transito", "estado", "TRÂNSITO EM JULGADO"),
    ("arquivado", r"^(processo |autos )?arquivad[oa]s?\b|^arquivamento\b|\bbaixa definitiva\b|baixa(d[oa]s?)? e arquiv",
     "estado", "PROCESSO ARQUIVADO"),
    ("acordo_homologado", r"homologad[oa]s? (o |a )?(acordo|transacao)|acordo (judicial )?homologad|"
                          r"homologacao (do|de) acordo|homologada a transacao", "julgamento", "ACORDO HOMOLOGADO"),
    ("desistencia_homologada", r"homologad[oa]s? (a )?desistencia|desistencia homologada", "julgamento",
     "EXTINTO SEM RESOLUÇÃO DE MÉRITO"),
    ("extinto_sem_merito", r"extint\w+.*(sem (resolucao|julgamento)|art\w*\.? ?485|abandono)|"
                           r"extincao.*sem (resolucao|julgamento)", "julgamento", "EXTINTO SEM RESOLUÇÃO DE MÉRITO"),
    ("extincao_com_merito", r"\bextint[oa]\b|\bextincao\b", "parar", None),
    ("incompetencia_declarada", r"declarad[oa] (a )?incompetencia|incompetencia (declarada|reconhecida)|"
                                r"declinad\w+ (a )?competencia|remetid\w+ os autos ao juizo competente", "julgamento",
     "REMETIDO AO JUÍZO COMPETENTE"),
    # --- precatório, suspensão, execução ---
    ("precatorio", r"precatorio|requisicao de pequeno valor|\brpv\b", "estado", "AGUARDANDO PAGAMENTO DE PRECATÓRIO"),
    ("suspenso", r"suspens[oa]\b|suspensao|sobrest", "estado", "SUSPENSO"),
    ("liquidacao", r"liquidacao de sentenca|(abertura|inicio) d[ea] liquidacao", "estado", "LIQUIDAÇÃO DE SENTENÇA"),
    ("calculos_homologados", r"homologad[oa]s? os calculos|calculos homologados", "estado", "CUMPRIMENTO DE SENTENÇA"),
    ("cumprimento_de_sentenca", r"cumprimento de sentenca|inicio do cumprimento|execucao (de|da) (sentenca|titulo)|"
                                r"\bsisbajud\b|\bbacenjud\b|\brenajud\b|\bpenhora\b|\bpenhorad|\balvara\b|"
                                r"intimacao para pagamento|pagamento voluntario", "estado", "CUMPRIMENTO DE SENTENÇA"),
    # --- recursos e julgamentos colegiados ---
    ("embargos_decididos", r"embargos de declaracao (acolhid|nao acolhid|rejeitad|providos|desprovid|conhecid)",
     "decisao", None),
    ("embargos_de_declaracao", r"embargos de declaracao", "estado", "AGUARDANDO JULGAMENTO DOS EMBARGOS DE DECLARAÇÃO"),
    ("retirado_de_pauta", r"deliberad[oa] em sessao.*retirad|retirad[oa] de pauta|adiad[oa].*(julgamento|sessao)", "recurso", _REC),
    ("acordao", r"deliberad[oa] em sessao|acordao (publicad|disponibiliz)|publicad[oa]s?(\(a\))?( o\(a\))? acordao|"
                r"(dado|negado) (provimento|seguimento)|recurso (provido|desprovido|improvido|nao provido|nao conhecido)|"
                r"apelacao (provida|desprovida|improvida)", "estado", "AGUARDANDO PRAZO RECURSAL"),
    ("pauta_de_julgamento", r"incluid[oa] em pauta|intimacao de pauta|pauta de julgamento|"
                            r"sessao de julgamento (designada|marcada)|pautad", "recurso", _REC),
    ("distribuicao_de_recurso", r"distribuid\w+.*(recurso|apelacao|agravo|relator|ministro|camara|turma|embargos)|"
                                r"conclus\w+ ao relator|conclus\w+ para relatoria|recebid[oa]s? os autos.*(tribunal|2o grau)",
     "recurso", _REC),
    ("remessa_em_grau_de_recurso", r"remetid\w+ os autos \(?em grau de recurso|remetid\w+ os autos ao (tribunal|"
                                   r"2o grau|segundo grau|instancia superior)|subida de recurso", "recurso", _REC),
    ("agravo_de_instrumento_distribuido", r"(distribuid|recebid)\w+.*agravo de instrumento", "estado",
     "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO"),
    ("agravo_de_instrumento_interposto", r"agravo de instrumento", "ruido", None),
    ("peticao_de_recurso", r"(apelacao|recurso (ordinario|de revista|especial|extraordinario)|agravo (de peticao|interno)|"
                           r"agravo regimental)", "recurso", _REC),
    ("recurso_nao_conhecido", r"negado seguimento a recurso", "estado", "AGUARDANDO PRAZO RECURSAL"),
    # --- sentença ---
    ("julgado_merito", r"julgad[oa]s? (o pedido |a acao )?(parcialmente |em parte )?(procedente|improcedente)|"
                       r"julgad[oa]s? (procedentes|improcedentes) em parte|julgado o pedido|proferid[oa] sentenca|"
                       r"sentenca proferida", "julgamento", "AGUARDANDO PRAZO RECURSAL"),
    ("sentenca_publicada", r"^publicad[oa](\(a\))?( o\(a\))? sentenca|^disponibilizad[oa]s?.* sentenca|"
                           r"^sentenca (publicada|disponibilizada)", "sentenca_publicada", None),
    # --- andamento de conhecimento ---
    ("audiencia_designada", r"audiencia.*(designad|marcad|redesignad)|designad[oa] audiencia", "estado", "AGUARDANDO AUDIÊNCIA"),
    ("audiencia_encerrada", r"audiencia.*(realizad|encerrad|cancelad|adiad|nao realizad|convertid)", "parar", None),
    ("retorno_do_cejusc", r"cejusc", "parar", None),
    ("remessa_interna", r"^remetid\w+ os autos \(?outros motivos", "parar", None),
    ("laudo_pericial", r"laudo pericial|juntada de laudo|apresentado o laudo", "parar", None),
    ("prova_pericial", r"prova pericial|nomead[oa] perit|pericia designad|designad[oa] pericia|intimacao do perito",
     "estado", "AGUARDANDO PROVA PERICIAL"),
    ("citacao_negativa", r"citacao negativa|nao citad|citacao frustrad|certidao negativa de citacao|"
                         r"aviso de recebimento negativo", "estado", "AGUARDANDO CITAÇÃO"),
    ("citacao_por_edital", r"edital de citacao|citacao por edital", "estado", "AGUARDANDO CITAÇÃO POR EDITAL"),
    ("citacao_cumprida", r"certidao de citacao|citacao (positiva|realizada|efetivada|cumprida)|mandado de citacao cumprido|"
                         r"\bcitad[oa]s?\b|(ar|aviso de recebimento) de citacao", "estado", "AGUARDANDO CONTESTAÇÃO"),
    ("citacao_expedida", r"cita[cç]ao|\bcite se\b|\bcitese\b", "estado", "AGUARDANDO CITAÇÃO"),
    ("contestacao_juntada", r"(juntad|apresentad|protocolad)\w*.*contestacao|contestacao (juntada|apresentada)", "estado",
     "AGUARDANDO RÉPLICA"),
    ("replica_juntada", r"(juntad|apresentad|protocolad)\w*.*(\breplica\b|impugnacao a contestacao)|\breplica (juntada|apresentada)",
     "parar", None),
    ("conclusos_julgamento", r"conclus\w+.*para (julgamento|sentenca)", "conclusos", "AGUARDANDO SENTENÇA"),
    ("conclusos_decisao", r"conclus\w+.*para decisao", "conclusos", "CONCLUSOS PARA DECISÃO"),
    ("conclusos_despacho", r"conclus\w+.*para despacho", "conclusos", "AGUARDANDO DESPACHO"),
    ("distribuicao_inicial", r"^distribuid\w*", "estado", "AGUARDANDO CITAÇÃO"),
    # --- decisões interlocutórias: não definem o momento, mas resolvem "conclusos" anteriores ---
    ("decisao_interlocutoria", r"^(deferid|indeferid|concedid|denegad|proferid[oa]s? (despacho|decisao)|"
                               r"publicad[oa](\(a\))?( o\(a\))? (decisao|despacho)|disponibilizad[oa]s?.* (decisao|despacho)|"
                               r"despacho (publicad|proferid)|decisao (interlocutoria|proferida))", "decisao", None),
    # --- ruído: não muda a fase ---
    ("ruido", r"^(disponibilizad|publicad|expedid|ato ordinatorio|decorrido|certidao|recebid|devolvid|confirmada|"
              r"juntada|intimacao|cienci|mero expediente|redistribuid|remetid|baixa|petic|manifestacao|"
              r"transferid|comunicacao|aviso|carta|ofic)", "ruido", None),
]
_REGRAS_COMPILADAS = [(nome, re.compile(padrao), efeito, destino) for nome, padrao, efeito, destino in REGRAS_DE_MOMENTO]

# Tipo de recurso, para refinar o momento recursal genérico olhando alguns movimentos para trás.
_TIPOS_DE_RECURSO = [
    (re.compile(r"apelacao"), "AGUARDANDO JULGAMENTO DA APELAÇÃO"),
    (re.compile(r"recurso ordinario"), "AGUARDANDO JULGAMENTO DO RECURSO ORDINÁRIO"),
    (re.compile(r"recurso de revista"), "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA"),
    (re.compile(r"recurso especial"), "AGUARDANDO JULGAMENTO DO RECURSO ESPECIAL"),
    (re.compile(r"recurso extraordinario"), "AGUARDANDO JULGAMENTO DO RECURSO EXTRAORDINÁRIO"),
    (re.compile(r"agravo de peticao"), "AGUARDANDO JULGAMENTO DO AGRAVO DE PETIÇÃO"),
    (re.compile(r"agravo interno|agravo regimental"), "AGUARDANDO JULGAMENTO DO AGRAVO INTERNO"),
    (re.compile(r"agravo de instrumento"), "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO"),
]
_RECURSO_GENERICO = "AGUARDANDO JULGAMENTO DO RECURSO"
_PRAZO_RECURSAL = "AGUARDANDO PRAZO RECURSAL"
_OLHAR_PARA_TRAS = 6      # movimentos anteriores examinados para refinar o tipo de recurso / achar o julgamento


def _como_movimento(m):
    if isinstance(m, dict):
        return {"data": m.get("data"), "texto": str(m.get("texto") or ""), "grau": m.get("grau")}
    return {"data": None, "texto": str(m or ""), "grau": None}


def _rotular(m):
    return {**m, "norm": _norm(m["texto"])}


def _casar(m):
    for nome, padrao, efeito, destino in _REGRAS_COMPILADAS:
        if padrao.search(m["norm"]):
            return nome, efeito, destino
    return None, None, None


def _segundo_grau(m):
    return bool(re.search(r"\b(2|segundo)\b|2o grau", _norm(str(m.get("grau") or ""))))


def _no_tst(m):
    """Movimento do Tribunal Superior do Trabalho (grau "TST"): o recurso que ali tramita é o de revista (ou
    agravo contra a decisão que o nega), salvo se o próprio andamento disser outro."""
    return bool(re.search(r"\btst\b", _norm(str(m.get("grau") or ""))))


_REVISTA = "AGUARDANDO JULGAMENTO DO RECURSO DE REVISTA"


def _refinar_recurso(ordenados, i):
    """Tipo de recurso lendo o próprio movimento e os anteriores (até _OLHAR_PARA_TRAS)."""
    for k in range(i, max(-1, i - _OLHAR_PARA_TRAS - 1), -1):
        for padrao, momento in _TIPOS_DE_RECURSO:
            if padrao.search(ordenados[k]["norm"]):
                return momento, ordenados[k]
    return _RECURSO_GENERICO, ordenados[i]


def _evidencia(regra, mov, extra=None):
    quando = ""
    if mov.get("data"):
        d = str(mov["data"])[:10]
        quando = f" de {d[8:10]}/{d[5:7]}/{d[0:4]}" if re.match(r"\d{4}-\d{2}-\d{2}", d) else f" de {d}"
    texto = f'Movimento{quando}: "{mov["texto"].strip()}" (regra: {regra})'
    return f"{texto}; {extra}" if extra else texto


def momento_por_regras(movimentos, janela=30):
    """(momento | None, evidência) pelo texto dos movimentos mais recentes. Veja o cabeçalho do módulo."""
    lista = [_rotular(_como_movimento(m)) for m in (movimentos or [])]
    ordenados = [m for _, m in sorted(enumerate(lista), key=lambda p: (str(p[1]["data"] or "0000"), p[0]))]
    consumido_decisao = False
    n = len(ordenados)
    for i in range(n - 1, max(-1, n - 1 - janela), -1):
        mov = ordenados[i]
        regra, efeito, destino = _casar(mov)
        if efeito is None or efeito == "parar":
            return None, None
        if efeito == "ruido":
            continue
        if efeito == "decisao":
            consumido_decisao = True
            continue
        if efeito == "conclusos":
            if consumido_decisao and destino != "AGUARDANDO SENTENÇA":
                continue            # o juiz já despachou/decidiu depois destes conclusos
            if destino == "AGUARDANDO SENTENÇA" and _no_tst(mov):
                momento, origem = _refinar_recurso(ordenados, i)
                return (_REVISTA if momento == _RECURSO_GENERICO else momento), _evidencia(regra, mov, "movimento do TST")
            if destino == "AGUARDANDO SENTENÇA" and _segundo_grau(mov):
                momento, origem = _refinar_recurso(ordenados, i)
                return momento, _evidencia(regra, mov, "movimento de 2º grau")
            return destino, _evidencia(regra, mov)
        if efeito == "sentenca_publicada":
            for k in range(i - 1, max(-1, i - _OLHAR_PARA_TRAS - 1), -1):
                r2, e2, d2 = _casar(ordenados[k])
                if e2 == "julgamento":
                    return d2, _evidencia(r2, ordenados[k], "sentença publicada em seguida")
            return _PRAZO_RECURSAL, _evidencia(regra, mov)
        if efeito == "recurso":
            momento, origem = _refinar_recurso(ordenados, i)
            if _no_tst(mov) and momento == _RECURSO_GENERICO:
                return _REVISTA, _evidencia(regra, mov, "movimento do TST")
            return momento, _evidencia(regra, mov, None if origem is mov else
                                       f'tipo do recurso pelo movimento "{origem["texto"].strip()}"')
        # estado ou julgamento
        if regra == "distribuicao_inicial" and _no_tst(mov):
            momento, origem = _refinar_recurso(ordenados, i)
            return (_REVISTA if momento == _RECURSO_GENERICO else momento), _evidencia(regra, mov, "movimento do TST")
        if regra == "distribuicao_inicial" and _segundo_grau(mov):
            momento, origem = _refinar_recurso(ordenados, i)
            return momento, _evidencia(regra, mov, "movimento de 2º grau")
        return destino, _evidencia(regra, mov)
    return None, None
