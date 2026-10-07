"""SPIKE S2: gera um .docx FICTÍCIO "tipo Google Docs" do modelo A, para testar leitura e atualização.

Independente do docx_atualizador.py de propósito (o fixture não pode ser escrito pelo código que ele testa).
Reproduz as manias de uma exportação do Google Docs:
- runs FRAGMENTADOS em pontos aleatórios (até no meio de palavra e da data), cada um com seu rPr completo
  repetido (rFonts Arial, sz/szCs, rtl, b com w:val="1" ou "0");
- fontes e tamanhos direto no run, sem estilos nomeados;
- parágrafos com pPr de espaçamento e jc, linhas de tabela com larguras explícitas (tcW, tblGrid, layout fixo),
  bordas e sombreamento por célula, marcador de bookmark solto;
- parágrafos vazios (com run vazio) entre as tabelas.

Casos de borda incluídos: um processo com 3 números no título (principal, agravo, apenso); um sem valor da
causa (célula vazia); um com "Data de citação: -"; um com anotação do advogado em destaque no fim do texto;
um com mesclagem vertical (dois réus); um sem frase de fecho; um com fecho todo em negrito; um com data
escrita no meio da frase ("em 14/10/2026", minúsculo).

Todos os dados são inventados; os números CNJ são gerados em tempo de execução (dígito verificador correto,
sequenciais 1234567 a 1234570, permitidos pelo empacotar.sh). Nada é gravado como literal.

Uso: python gerar_modelo.py DESTINO.docx [semente]
"""
import random
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DATA_BASE = "18/09/2026"
CLIENTE = "COMERCIAL EXEMPLO ALFA LTDA."


def cnj(i, ano=2024, j=8, tr=6, origem=1):
    """Número CNJ fictício com DV correto: sequencial 1234567..1234570, variando ano/justiça/origem."""
    seq = f"{1234567 + (i % 4):07d}"
    dv = 98 - int(f"{seq}{ano}{j}{tr:02d}{origem:04d}00") % 97
    return f"{seq}-{dv:02d}.{ano}.{j}.{tr:02d}.{origem:04d}"


def processos():
    """Os 12 processos fictícios (dados inventados)."""
    P = []

    def novo(i, **kw):
        base = dict(numeros=[cnj(i, 2020 + i % 6, 8, 6, 10 + i)], tipos=[], assunto="Indenização por dano moral",
                    autores="Maria Exemplo da Silva", reus=CLIENTE, ajuizamento="15/02/2026", valor_causa="R$ 25.000,00",
                    citacao="02/03/2026", juizo="3ª Vara Cível da Comarca de Cidade Modelo", area="Cível",
                    materia="Responsabilidade civil", momento="AGUARDANDO SENTENÇA", andamentos=[], fecho="padrao",
                    extra=None)
        base.update(kw)
        P.append(base)

    novo(0, andamentos=[("02/03/2026", "foi proferido despacho determinando a citação da parte ré."),
                        ("20/04/2026", "a parte ré apresentou contestação."),
                        ("12/06/2026", "a parte autora apresentou réplica."),
                        ("30/07/2026", "os autos foram conclusos para sentença.")])
    novo(1, numeros=[cnj(1, 2022, 8, 6, 2), cnj(2, 2025, 8, 6, 0), cnj(3, 2022, 8, 6, 3)], tipos=["agravo", "apenso"],
         assunto="Cobrança de duplicatas", autores="Indústria Fictícia Beta S.A.", reus=CLIENTE, valor_causa="R$ 180.450,90",
         momento="AGUARDANDO JULGAMENTO DO AGRAVO", area="Empresarial", materia="Títulos de crédito",
         andamentos=[("10/03/2026", "foi deferida em parte a tutela de urgência."),
                     ("25/03/2026", "a ré interpôs agravo de instrumento."),
                     ("14/08/2026", "foi concedido efeito suspensivo ao agravo.")],
         extra="nota")
    novo(2, numeros=[cnj(4, 2025, 5, 7, 12)], assunto="Horas extras e reflexos", autores="João Exemplo Pereira",
         reus=CLIENTE, valor_causa="R$ 62.300,00", juizo="12ª Vara do Trabalho de Cidade Modelo", area="Trabalhista",
         materia="Jornada de trabalho", momento="AGUARDANDO AUDIÊNCIA",
         andamentos=[("05/05/2026", "foi designada audiência de instrução para 22/10/2026."),
                     ("01/09/2026", "a ré juntou documentos e rol de testemunhas.")])
    novo(3, assunto="Obrigação de fazer", autores="Associação Modelo de Moradores", valor_causa="",   # SEM valor da causa
         momento="AGUARDANDO CONTESTAÇÃO", andamentos=[("06/07/2026", "a ré foi citada por meio eletrônico.")])
    novo(4, assunto="Execução de título extrajudicial", autores=CLIENTE, reus="Comércio Fictício Gama Ltda.",
         valor_causa="R$ 48.900,00", citacao="-", momento="AGUARDANDO CITAÇÃO DOS EXECUTADOS", area="Cível",
         materia="Execução", andamentos=[("11/05/2026", "foi determinada a citação dos executados.")])
    novo(5, assunto="Cumprimento de sentença", valor_causa="R$ 75.000,00", momento="CUMPRIMENTO DE SENTENÇA",
         materia="Cumprimento de sentença",
         andamentos=[("08/06/2026", "foi proferida sentença de parcial procedência."),
                     ("29/06/2026", "a sentença transitou em julgado."),
                     ("17/08/2026", "foi iniciado o cumprimento de sentença, com intimação da ré para pagar.")])
    novo(6, assunto="Rescisão contratual", reus="Construtora Fictícia Delta Ltda.; Banco Modelo S.A.",
         valor_causa="R$ 310.000,00", momento="AGUARDANDO JULGAMENTO DA APELAÇÃO", area="Contratual",
         materia="Contrato de compra e venda", extra="vmerge",
         andamentos=[("09/02/2026", "foi proferida sentença de procedência."),
                     ("13/03/2026", "a parte ré interpôs recurso de apelação.")])
    novo(7, assunto="Revisão de cláusulas", valor_causa="R$ 15.500,00", momento="TRÂNSITO EM JULGADO",
         materia="Contrato bancário", area="Consumidor", fecho="negrito",
         andamentos=[("03/04/2026", "foi proferida sentença de improcedência."),
                     ("20/05/2026", "a sentença transitou em julgado.")])
    novo(8, assunto="Ação declaratória", valor_causa="R$ 9.800,00", momento="ARQUIVADO", fecho="nenhum",
         andamentos=[("14/01/2026", "os autos foram arquivados definitivamente.")])
    novo(9, assunto="Produção antecipada de provas", valor_causa="R$ 5.000,00", momento="AGUARDANDO PROVA PERICIAL",
         fecho="variante", andamentos=[("16/06/2026", "foi nomeado perito para a realização da prova técnica.")])
    novo(10, assunto="Despejo por falta de pagamento", autores=CLIENTE, reus="Pedro Exemplo Souza",
         valor_causa="R$ 36.000,00", momento="AGUARDANDO SENTENÇA", area="Imobiliário", materia="Locação",
         andamentos=[("22/07/2026", "foi realizada audiência, com concessão de prazo até 30/09/2026 para alegações."),
                     ("04/09/2026", "o juiz determinou a juntada de documentos em 5 dias, com novo exame em 14/10/2026.")],
         extra="data_no_meio")
    novo(11, assunto="Indenização por dano material", autores="Carla Exemplo Lima", valor_causa="R$ 42.700,00",
         materia="Responsabilidade civil", momento="AGUARDANDO RÉPLICA",
         andamentos=[("27/08/2026", "a parte ré apresentou contestação com documentos.")])
    return P


class Fabrica:
    def __init__(self, semente=7):
        self.rng = random.Random(semente)

    def rpr(self, negrito, tam=22, extra=""):
        # Google repete o rPr completo em todo run; b com w:val e rtl explícitos
        b = f'<w:b w:val="{1 if negrito else 0}"/>' if (negrito or self.rng.random() < 0.5) else ""
        return (f'<w:rPr><w:rFonts w:ascii="Arial" w:cs="Arial" w:eastAsia="Arial" w:hAnsi="Arial"/>{b}'
                f'<w:color w:val="000000"/><w:sz w:val="{tam}"/><w:szCs w:val="{tam}"/>{extra}<w:rtl w:val="0"/></w:rPr>')

    def runs(self, texto, negrito=False, tam=22, extra="", fragmentar=True):
        """Quebra o texto em 1 a 4 runs, em pontos aleatórios (inclusive no meio de palavra ou de data)."""
        if not texto:
            return ""
        n = self.rng.choice([1, 2, 2, 3, 4]) if fragmentar and len(texto) > 6 else 1
        cortes = sorted(self.rng.sample(range(1, len(texto)), min(n - 1, len(texto) - 1))) if n > 1 else []
        pedacos, ini = [], 0
        for c in cortes + [len(texto)]:
            pedacos.append(texto[ini:c])
            ini = c
        return "".join(f'<w:r>{self.rpr(negrito, tam, extra)}<w:t xml:space="preserve">{escape(p)}</w:t></w:r>'
                       for p in pedacos if p)

    def par(self, runs, jc="left"):
        return (f'<w:p><w:pPr><w:pBdr><w:top w:space="0" w:color="auto" w:val="nil" w:sz="0"/><w:left w:space="0" w:color="auto" '
                f'w:val="nil" w:sz="0"/><w:bottom w:space="0" w:color="auto" w:val="nil" w:sz="0"/><w:right w:space="0" '
                f'w:color="auto" w:val="nil" w:sz="0"/><w:between w:space="0" w:color="auto" w:val="nil" w:sz="0"/></w:pBdr>'
                f'<w:spacing w:after="0" w:before="0" w:line="240" w:lineRule="auto"/><w:contextualSpacing w:val="0"/>'
                f'<w:jc w:val="{jc}"/><w:rPr/></w:pPr>{runs}</w:p>')

    def par_vazio(self):
        return self.par(f'<w:r>{self.rpr(False)}</w:r>')

    BORDAS = "".join(f'<w:{l} w:color="000000" w:space="0" w:sz="6" w:val="single"/>' for l in ("top", "left", "bottom", "right"))

    def tc(self, larg, pars, span=1, fill=None, vmerge=None):
        vm = ""
        if vmerge == "inicio":
            vm = '<w:vMerge w:val="restart"/>'
        elif vmerge == "cont":
            vm = "<w:vMerge/>"
        return (f'<w:tc><w:tcPr><w:tcW w:w="{larg}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "") + vm
                + f'<w:tcBorders>{self.BORDAS}</w:tcBorders>' + (f'<w:shd w:fill="{fill}" w:val="clear"/>' if fill else "")
                + '<w:tcMar><w:top w:w="100" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="100" w:type="dxa"/>'
                  '<w:right w:w="100" w:type="dxa"/></w:tcMar><w:vAlign w:val="top"/></w:tcPr>' + pars + '</w:tc>')

    def tr(self, tcs, cab=False):
        return (f'<w:tr><w:trPr><w:cantSplit w:val="0"/><w:tblHeader w:val="{1 if cab else 0}"/></w:trPr>{"".join(tcs)}</w:tr>')

    def tbl(self, grade, linhas):
        cols = "".join(f'<w:gridCol w:w="{g}"/>' for g in grade)
        return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(grade)}" w:type="dxa"/><w:jc w:val="left"/><w:tblInd w:w="0" w:type="dxa"/>'
                f'<w:tblBorders>{self.BORDAS}<w:insideH w:color="000000" w:space="0" w:sz="6" w:val="single"/>'
                f'<w:insideV w:color="000000" w:space="0" w:sz="6" w:val="single"/></w:tblBorders>'
                f'<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{cols}</w:tblGrid>{"".join(linhas)}</w:tbl>')


def _titulo(p):
    n = p["numeros"]
    rot = {"agravo": "AGRAVO DE INSTRUMENTO Nº", "apenso": "APENSO Nº"}
    t = f"PROCESSO Nº {n[0]}"
    for i, x in enumerate(n[1:]):
        t += f" / {rot.get(p['tipos'][i], 'VINCULADO Nº')} {x}"
    return f"{t} [ {p['momento']} ]"


def _andamentos(f, p, variante):
    """Runs do texto corrido: 'Em ' + data em negrito + ', texto.' ... + nota do advogado + fecho."""
    xml = ""
    for i, (data, texto) in enumerate(p["andamentos"]):
        xml += f.runs(("" if i == 0 else " ") + "Em ", False)
        xml += f.runs(data, True)
        xml += f.runs(", " + texto, False)
    if p["extra"] == "nota":
        xml += f.runs(" ", False) + f.runs("(Anotação do advogado: conferir o valor com o cliente.)", False,
                                          extra='<w:i w:val="1"/><w:highlight w:val="yellow"/>', fragmentar=False)
    espaco = f.runs(" ", False) if p["andamentos"] else ""
    if p["fecho"] == "padrao":
        xml += espaco + f.runs("Em ", False) + f.runs(DATA_BASE, True) + f.runs(", sem atualizações.", False)
    elif p["fecho"] == "negrito":
        xml += espaco + f.runs(f"Em {DATA_BASE}, sem atualizações.", True)
    elif p["fecho"] == "variante":
        xml += espaco + f.runs("Em ", False) + f.runs(DATA_BASE, True) + f.runs(", sem atualização.", False)
    return xml


def bloco(f, p, variante, idx=0):
    L = [1900, 2600, 1900, 2626]
    rot = lambda s, larg=None: f.tc(larg or L[0], f.par(f.runs(s, True)), fill="EFEFEF")
    val = lambda i, s, span=1, vm=None: f.tc(sum(L[i:i + span]), f.par(f.runs(s, False) if s else ""), span, vmerge=vm)
    reus = p["reus"].split("; ")
    linhas = [f.tr([f.tc(sum(L), f.par(f'<w:bookmarkStart w:id="{idx}" w:name="_gjdgxs{idx}"/>' + f.runs(_titulo(p), True)
                                  + f'<w:bookmarkEnd w:id="{idx}"/>'), 4, fill="D9D9D9")]),
              f.tr([rot("Assunto"), val(1, p["assunto"], 3)]),
              f.tr([rot("Autor(es)"), val(1, p["autores"], 3)])]
    if p["extra"] == "vmerge":      # mesclagem vertical: rótulo "Réu(s)" ocupa duas linhas, um réu em cada
        linhas.append(f.tr([f.tc(L[0], f.par(f.runs("Réu(s)", True)), fill="EFEFEF", vmerge="inicio"), val(1, reus[0], 3)]))
        linhas.append(f.tr([f.tc(L[0], f.par(f.runs("", True)), fill="EFEFEF", vmerge="cont"), val(1, reus[1], 3)]))
    else:
        linhas.append(f.tr([rot("Réu(s)"), val(1, p["reus"], 3)]))
    linhas += [f.tr([rot("Ajuizamento"), val(1, p["ajuizamento"]), rot("Valor da Causa", L[2]), val(3, p["valor_causa"])]),
               f.tr([rot("Data de citação"), val(1, p["citacao"]), rot("Juízo", L[2]), val(3, p["juizo"])]),
               f.tr([rot("Área do Direito"), val(1, p["area"]), rot("Matéria Principal", L[2]), val(3, p["materia"])])]
    if variante == "andamentos_abaixo":     # variante: "Andamentos:" numa linha e o texto na linha de baixo
        linhas.append(f.tr([f.tc(sum(L), f.par(f.runs("Andamentos:", True)), 4, fill="EFEFEF")]))
        linhas.append(f.tr([f.tc(sum(L), f.par(_andamentos(f, p, variante), "both"), 4)]))
    else:
        linhas.append(f.tr([rot("Andamentos:"), f.tc(sum(L[1:]), f.par(_andamentos(f, p, variante), "both"), 3)]))
    return f.tbl(L, linhas)


def resumo(f, ps):
    L = [2300, 2400, 2600, 1726]
    cab = f.tr([f.tc(L[i], f.par(f.runs(s, True, 18)), fill="D9D9D9") for i, s in
                enumerate(["Nº DO PROCESSO", "ASSUNTO", "MOMENTO ATUAL DO PROCESSO", "ÚLTIMO ANDAMENTO"])], cab=True)
    linhas = [cab]
    for p in ps:
        nums = f.par(f.runs(p["numeros"][0], False, 18)) + "".join(
            f.par(f.runs(f"{p['tipos'][i].capitalize()}: {n}", False, 18)) for i, n in enumerate(p["numeros"][1:]))
        ultimo = p["andamentos"][-1][0]
        linhas.append(f.tr([f.tc(L[0], nums), f.tc(L[1], f.par(f.runs(p["assunto"], False, 18))),
                            f.tc(L[2], f.par(f.runs(p["momento"], True, 18))), f.tc(L[3], f.par(f.runs(ultimo, False, 18)))]))
    return f.tbl(L, linhas)


def gerar(destino, semente=7, variante=None, n=12):
    """Grava o .docx fictício em `destino`. variante='andamentos_abaixo' muda a posição do texto. Devolve os dados usados."""
    import docx
    f = Fabrica(semente)
    ps = processos()[:n]
    d = docx.Document()
    corpo = d.element.body
    sect = corpo.find(f"{{{W_NS}}}sectPr")
    for filho in list(corpo):
        if filho is not sect:
            corpo.remove(filho)
    sect.find(f"{{{W_NS}}}pgSz").set(f"{{{W_NS}}}w", "11906")
    sect.find(f"{{{W_NS}}}pgSz").set(f"{{{W_NS}}}h", "16838")
    sect.find(f"{{{W_NS}}}pgMar").set(f"{{{W_NS}}}left", "1440")
    sect.find(f"{{{W_NS}}}pgMar").set(f"{{{W_NS}}}right", "1440")
    xml = [f.par(f.runs(CLIENTE, True, 28)),
           f.par(f.runs("Data-Base:", True) + f.runs(" ", False) + f.runs(DATA_BASE, False)),
           f.par_vazio(), resumo(f, ps), f.par_vazio()]
    for idx, p in enumerate(ps):
        xml += [bloco(f, p, variante, idx), f.par_vazio()]
    for x in xml:
        raiz = etree.fromstring(f'<w:r0 xmlns:w="{W_NS}">{x}</w:r0>')
        sect.addprevious(raiz[0])
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    d.save(str(destino))
    return {"cliente": CLIENTE, "data_base": DATA_BASE, "processos": ps}


if __name__ == "__main__":
    dados = gerar(sys.argv[1] if len(sys.argv) > 1 else "modelo_ficticio.docx", int(sys.argv[2]) if len(sys.argv) > 2 else 7)
    print(f"{len(dados['processos'])} processos gerados")
