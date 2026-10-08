"""Entregas: pastas entrada/ e saida/ do relatório, geração dos arquivos e a tela /entregas.

Cada relatório tem duas pastas de trabalho (por padrão dentro de `projetos/<slug>/`; o perfil
pode apontá-las para uma pasta do Drive para Desktop):

    entrada/   arquivos que a pessoa enviou (relatórios antigos, o .docx/.xlsx mais recente)
    saida/     uma subpasta por rodada ("AAAA-MM-DD_HHMMSS-<tipo>") com o que o programa entregou:
               relatório em texto (.docx, um por cliente), planilha (.xlsx), painel (.html) e o
               relatório de qualidade da base (qualidade.html)

A tela /entregas lista as rodadas com download de cada arquivo (só dentro de saida/), mostra o
relatório de qualidade e a lista "conferir manualmente" (processos que a fila mandou para
revisão manual: captcha, segredo de justiça, não localizado, erro) e oferece "Gerar agora".

Geração (`gerar`): monta o EstadoRelatorio do CONTRATOS §5 com as fichas e os eventos APROVADOS e
chama os escritores `escritores.docx_a`, `escritores.xlsx_b` e `escritores.dashboard` (WS-6/7/8).
O texto de andamentos que cada escritor devolve em `textos_gravados` é guardado em
`ficha["ultimo_texto_gravado"]` (CONTRATOS §5). Como o modelo A é "por cliente", sai um .docx por
cliente; a planilha e o painel cobrem o relatório inteiro. O molde (arquivo do cliente a
atualizar) é o .docx/.xlsx mais recente de entrada/; o .docx só vale como molde quando há um único
cliente. Escritor ausente ou com falha vira aviso (nunca derruba a tela). O painel (C) lê a
planilha, então a planilha é gerada sempre que o painel é pedido.

Módulos dos outros workstreams (fila, escritores, qualidade) são importados na hora do uso;
sem eles a tela diz, em português, que o recurso ainda não está disponível.
"""
import datetime
import html
import importlib
import re
import subprocess
import sys
from pathlib import Path

from flask import abort, request, send_file

import comum
import ficha
from painel import perfil as per
from painel.base import WINDOWS, _dentro, _ir, _msg

ROTULO_ESTADO = {"manual": "precisa de conferência manual", "erro": "deu erro", "so_djen": "só publicações (DJEN)"}
MENSAGEM_DE_CODIGO = {"captcha": "o tribunal pediu verificação (captcha) que não foi resolvida",
                      "segredo": "processo em segredo de justiça",
                      "nao_encontrado": "processo não localizado no tribunal",
                      "fisico": "processo físico (sem autos eletrônicos): o relatório segue pelo DJEN e pelo que você lançar à mão",
                      "timeout": "o tribunal demorou demais para responder",
                      "sessao_expirada": "a sessão de acesso expirou",
                      "outro": "erro não identificado"}


ESTILO_FLUXO = """<style>
.botoes-grandes{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:16px 0}
.botao-grande{display:block;border:1px solid var(--linha);border-radius:8px;padding:18px;text-decoration:none;color:var(--tinta);background:var(--fundo2)}
.botao-grande:hover,.botao-grande:focus{border-color:var(--acento);outline:2px solid var(--acento)}
.botao-grande b{display:block;font-size:18px;margin-bottom:6px}
.zona{border:2px dashed var(--acento);border-radius:8px;padding:26px;background:var(--fundo2)}
.zona input[type=file]{width:100%;font:inherit;padding:14px 0}
table.t{border-collapse:collapse;width:100%;margin:8px 0}
table.t td,table.t th{border-bottom:1px solid var(--linha);padding:6px 4px;text-align:left;font-size:14px;vertical-align:top}
.nivel-erro{color:var(--alerta);font-weight:700}.nivel-atencao{color:#92400e;font-weight:600}
progress{width:100%;height:18px}
.linha2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:640px){.linha2{grid-template-columns:1fr}}
</style>"""


class Indisponivel(Exception):
    """Módulo de outro workstream (ainda) não disponível; a mensagem já é para o usuário."""


def modulo(nome, descricao):
    try:
        return importlib.import_module(nome)
    except ImportError as erro:
        raise Indisponivel(f"{descricao} ainda não está disponível nesta versão do programa ({erro}).") from erro


def abrir_fila():
    return modulo("fila", "A fila de coleta").Fila(comum.PROJETO)


# ---------------------------------------------------------------- pastas

def pasta_de_trabalho():
    """Pasta-base de entrada/ e saida/: a do perfil, se existir; senão, a pasta do relatório."""
    escolhida = (per.carregar().get("pasta_de_trabalho") or "").strip()
    if escolhida and Path(escolhida).expanduser().is_dir():
        return Path(escolhida).expanduser()
    return Path(comum.PROJETO_DIR)


def pasta_entrada():
    pasta = pasta_de_trabalho() / "entrada"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_saida():
    pasta = pasta_de_trabalho() / "saida"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def nova_rodada(tipo):
    """Subpasta nova de saida/ para uma geração (nunca reaproveita uma existente)."""
    base = f"{datetime.datetime.now():%Y-%m-%d_%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', tipo.lower()).strip('-') or 'entrega'}"
    pasta, n = pasta_saida() / base, 2
    while pasta.exists():
        pasta, n = pasta_saida() / f"{base}-{n}", n + 1
    pasta.mkdir(parents=True)
    return pasta


def nome_de_arquivo(texto, padrao="relatorio"):
    limpo = re.sub(r"[^\w .()-]", "", str(texto or ""), flags=re.UNICODE).strip(" .")
    return limpo[:80] or padrao


def molde_mais_recente(extensao):
    """O arquivo mais recente de entrada/ com a extensão dada (ou None)."""
    arquivos = [a for a in pasta_entrada().iterdir() if a.is_file() and a.suffix.lower() == extensao]
    return max(arquivos, key=lambda a: (a.stat().st_mtime, a.name)) if arquivos else None


def listar_saida():
    """[{"rodada": nome, "arquivos": [{"nome", "rel", "tamanho"}]}], da mais nova para a mais antiga."""
    saida, rodadas = pasta_saida(), []
    for pasta in sorted((p for p in saida.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        arquivos = [{"nome": a.name, "rel": f"{pasta.name}/{a.name}", "tamanho": a.stat().st_size}
                    for a in sorted(pasta.iterdir()) if a.is_file()]
        rodadas.append({"rodada": pasta.name, "arquivos": arquivos})
    return rodadas


# ---------------------------------------------------------------- conferir manualmente

def itens_para_conferir(fila=None):
    """Processos que a fila não conseguiu coletar: [{"numero", "estado", "motivo"}].
    Usa `Fila.itens()` (lista de dicts com "numero", "estado", "erro") quando a fila a oferece."""
    try:
        fila = fila or abrir_fila()
    except Indisponivel:
        return []
    itens = getattr(fila, "itens", None)
    if not callable(itens):
        return []
    achados = []
    for it in itens():
        if it.get("estado") in ("manual", "erro"):
            erro = it.get("erro") or {}
            codigo = erro.get("codigo") if isinstance(erro, dict) else str(erro or "")
            achados.append({"numero": it.get("numero", ""), "estado": it["estado"], "fisico": codigo == "fisico",
                            "motivo": MENSAGEM_DE_CODIGO.get(codigo, (erro.get("mensagem") if isinstance(erro, dict) else "") or "motivo não informado")})
    return sorted(achados, key=lambda a: a["numero"])


# ---------------------------------------------------------------- qualidade

def verificar_qualidade(fichas, perfil_do_relatorio):
    """Roda `qualidade.verificar` (WS-11): lista de achados; Indisponivel se o módulo não existir."""
    return modulo("qualidade", "O verificador de qualidade da base").verificar(fichas, perfil_do_relatorio)


def html_da_qualidade(achados, titulo):
    e = html.escape
    linhas = "".join(
        f"<tr><td>{e(str(a.get('gravidade', '')))}</td><td>{e(', '.join(a.get('numeros') or []))}</td>"
        f"<td>{e(str(a.get('mensagem', '')))}</td><td>{e(str(a.get('sugestao', '')))}</td></tr>" for a in achados)
    corpo = (f"<table border='1' cellpadding='4' style='border-collapse:collapse'><tr><th>Gravidade</th><th>Processos</th>"
             f"<th>O que foi achado</th><th>Sugestão</th></tr>{linhas}</table>" if achados else "<p>Nenhum problema encontrado.</p>")
    return (f"<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>{e(titulo)}</title>"
            f"<body style='font-family:system-ui,sans-serif'><h1>{e(titulo)}</h1>"
            f"<p>{len(achados)} achado(s). Confira antes de entregar o relatório ao cliente.</p>{corpo}</body></html>")


# ---------------------------------------------------------------- geração

def _estado(nome, data_base, fichas, eventos, perfil_do_relatorio, parametros_extra=None):
    return {"cliente": nome, "data_base": data_base, "fichas": fichas, "eventos": eventos,
            "perfil": perfil_do_relatorio, "parametros": {**perfil_do_relatorio.get("parametros", {}), **(parametros_extra or {})}}


def _aviso(nivel, codigo, onde, mensagem):
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": []}


def _chamar(escritor, molde, estado, destino):
    return escritor.gravar(molde, estado, destino)


def gerar(entregas=None, tipo="entrega", rodada=None, fichas=None, parametros_extra=None):
    """Gera as entregas pedidas (padrão: as do perfil) numa rodada nova de saida/.

    Desde o WS-14 quem faz o trabalho é `fluxos.entregar` (julgamento, escritores, qualidade, "o que mudou",
    retrato mensal e memória do ciclo); esta função só mantém a assinatura que as telas já usavam.
    Devolve {"rodada": Path, "arquivos": [Path], "resultados": {rotulo: Resultado}, "avisos": [Aviso], "qualidade": ...}.
    `fichas` permite gerar de um conjunto já carregado (nada é persistido); `parametros_extra` entra em
    `estado["parametros"]` (ex.: campos_nao_migrados na migração)."""
    fluxos = modulo("fluxos", "A geração dos arquivos")
    return fluxos.entregar(comum.PROJETO, entregas, tipo=tipo, rodada=rodada, fichas=fichas, parametros_extra=parametros_extra)


def _guardar_textos(fichas, resultado, data_base, arquivo):
    """`Resultado["textos_gravados"]` -> `ficha["ultimo_texto_gravado"]` (CONTRATOS §5)."""
    por_numero = {f["numero"]: f for f in fichas}
    for numero, texto in (resultado.get("textos_gravados") or {}).items():
        if numero in por_numero:
            por_numero[numero]["ultimo_texto_gravado"] = {"data_base": data_base, "texto": texto, "arquivo": arquivo}


def resumo_do_resultado(saida):
    """Frase curta (para mensagem na tela) do que foi gerado."""
    partes = []
    for rotulo, res in saida["resultados"].items():
        partes.append(f"{rotulo.split(':')[0]}: {len(res.get('processos_atualizados', []))} atualizado(s), "
                      f"{len(res.get('processos_novos', []))} novo(s), {len(res.get('ignorados', []))} já constava(m)")
    erros = [a for a in saida["avisos"] if a.get("nivel") == "erro"]
    texto = f"{len(saida['arquivos'])} arquivo(s) gerado(s) em saida/{saida['rodada'].name}."
    if partes:
        texto += "\n" + "\n".join(partes)
    if erros:
        texto += "\nNão deu para gerar tudo:\n" + "\n".join(a["mensagem"] for a in erros)
    return texto


# ---------------------------------------------------------------- tela

def _html_do_ultimo_ciclo():
    """Avisos do último ciclo (fluxos.py): andamento que já constava, edição manual sobrescrita, número repetido, processo
    novo ou sumido... Nenhum derruba o fluxo; aqui a pessoa decide."""
    try:
        dados = modulo("fluxos", "Os fluxos").ultimo_ciclo(comum.PROJETO)
    except Exception:  # noqa: BLE001 - a tela nunca cai por causa disto
        return ""
    avisos = (dados or {}).get("avisos") or []
    if not avisos:
        return ""
    e = html.escape
    linhas = "".join(f"<tr><td>{e(str(a.get('nivel', '')))}</td><td>{e(str(a.get('codigo', '')))}</td><td>{e(str(a.get('onde', '')))}</td>"
                     f"<td>{e(str(a.get('mensagem', '')))}</td></tr>" for a in avisos[:200])
    return ("<h2>Para conferir do último ciclo</h2><p class='dica'>Nada disto impediu a entrega; são pontos que merecem um olhar "
            "antes de enviar ao cliente.</p><table class='t'><tr><th>Nível</th><th>Aviso</th><th>Onde</th><th>O que houve</th></tr>"
            + linhas + "</table>" + (f"<p class='dica'>E mais {len(avisos) - 200}.</p>" if len(avisos) > 200 else ""))


def _tamanho(bytes_):
    return f"{bytes_ / 1024:.0f} KB" if bytes_ >= 1024 else f"{bytes_} bytes"


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"
    e = html.escape

    @app.get("/entregas")
    def entregas_ver_entregas():
        h = [cabecalho("entregas"), ESTILO_FLUXO, "<h1>Entregas</h1>", _msg()]
        if not comum.PROJETO:
            return "".join(h) + "<p>Crie ou importe um relatório primeiro.</p>"
        p = per.carregar()
        h.append(f"<p class='dica'>Arquivos que você enviou ficam em <b>{e(str(pasta_entrada()))}</b>; os que o programa entrega, em "
                 f"<b>{e(str(pasta_saida()))}</b>. Nada aqui sai do seu computador.</p>")
        h.append(f"<form class='caixa' method='post' action='/entregas/gerar'>{oculto}<b>Gerar agora</b>"
                 "<p class='dica'>Monta os arquivos com os andamentos já aprovados em Revisar. O arquivo que você enviou nunca é "
                 "sobrescrito: o programa grava uma versão nova.</p>")
        for chave, rotulo in per.ENTREGAS.items():
            h.append(f"<p><label><input type='checkbox' name='entregas' value='{chave}' {'checked' if chave in p['entregas'] else ''}> {e(rotulo)}</label></p>")
        h.append("<button class='principal'>Gerar entregas</button> "
                 "<span class='dica'>(muda em <a href='/perfil'>Perfil</a>)</span></form>")
        rodadas = listar_saida()
        h.append("<h2>Arquivos entregues</h2>")
        if not rodadas:
            h.append("<p class='dica'>Nada entregue ainda.</p>")
        for r in rodadas:
            h.append(f"<div class='caixa'><b>{e(r['rodada'])}</b>"
                     f"<form style='display:inline;float:right' method='post' action='/entregas/mostrar'>{oculto}"
                     f"<input type='hidden' name='p' value='{e(r['rodada'])}'><button>Mostrar a pasta</button></form><ul>")
            for a in r["arquivos"]:
                h.append(f"<li><a href='/entregas/baixar?p={e(a['rel'])}'>{e(a['nome'])}</a> <span class='dica'>({_tamanho(a['tamanho'])})</span></li>")
            h.append("</ul></div>" if r["arquivos"] else "<span class='dica'>Pasta vazia.</span></div>")
        h.append("<h2>Qualidade da base</h2>")
        h.append(f"<form class='caixa' method='post' action='/entregas/qualidade'>{oculto}"
                 "<p class='dica'>Procura processo repetido, rótulo fora do padrão, acordo sem valor, datas incoerentes e outros "
                 "problemas, antes de você entregar.</p><button>Verificar agora</button></form>")
        achados = _ULTIMA_QUALIDADE.get(comum.PROJETO)
        if achados is not None:
            h.append(f"<p><b>{len(achados)}</b> achado(s) na última verificação.</p>")
            if achados:
                h.append("<table class='t'><tr><th>Gravidade</th><th>Processos</th><th>O que foi achado</th><th>Sugestão</th></tr>")
                for a in achados[:200]:
                    h.append(f"<tr><td>{e(str(a.get('gravidade', '')))}</td><td>{e(', '.join(a.get('numeros') or []))}</td>"
                             f"<td>{e(str(a.get('mensagem', '')))}</td><td>{e(str(a.get('sugestao', '')))}</td></tr>")
                h.append("</table>")
        h.append("<h2>Conferir manualmente</h2>")
        itens = itens_para_conferir()
        eletronicos = [it for it in itens if not it.get("fisico")]
        fisicos = [it for it in itens if it.get("fisico")]
        if eletronicos:
            h.append("<p class='dica'>A coleta não conseguiu estes processos. Veja-os no tribunal e complete à mão.</p>"
                     "<table class='t'><tr><th>Processo</th><th>Situação</th><th>Motivo</th></tr>")
            for it in eletronicos:
                h.append(f"<tr><td>{e(it['numero'])}</td><td>{e(ROTULO_ESTADO.get(it['estado'], it['estado']))}</td><td>{e(it['motivo'])}</td></tr>")
            h.append("</table>")
        if fisicos:
            h.append(f"<h3>Processos físicos ({len(fisicos)})</h3><p class='dica'>Sem autos eletrônicos: não são falha da coleta e "
                     "não entram na taxa de sucesso. O relatório deles segue com as publicações do DJEN e com o que você lançar à mão.</p>"
                     "<table class='t'><tr><th>Processo</th></tr>"
                     + "".join(f"<tr><td>{e(it['numero'])}</td></tr>" for it in fisicos) + "</table>")
        if not itens:
            h.append("<p class='dica'>Nenhum processo para conferir à mão agora.</p>")
        h.append(_html_do_ultimo_ciclo())
        return "".join(h)

    @app.post("/entregas/gerar")
    def entregas_gerar_agora():
        token_ok()
        if not comum.PROJETO:
            return _ir("/entregas", "Não há relatório ativo.")
        pedidas = [x for x in request.form.getlist("entregas") if x in per.ENTREGAS]
        if not pedidas:
            return _ir("/entregas", "Marque pelo menos uma entrega.")
        saida = gerar(pedidas, "entrega")
        _ULTIMA_QUALIDADE[comum.PROJETO] = saida.get("qualidade", _ULTIMA_QUALIDADE.get(comum.PROJETO))
        return _ir("/entregas", resumo_do_resultado(saida))

    @app.post("/entregas/qualidade")
    def entregas_qualidade_agora():
        token_ok()
        if not comum.PROJETO:
            return _ir("/entregas", "Não há relatório ativo.")
        try:
            achados = verificar_qualidade(ficha.carregar(todas=True), per.carregar())
        except Indisponivel as erro:
            return _ir("/entregas", str(erro))
        except Exception as erro:  # noqa: BLE001
            return _ir("/entregas", f"Não consegui verificar a base: {erro}")
        _ULTIMA_QUALIDADE[comum.PROJETO] = achados
        return _ir("/entregas", f"Verificação concluída: {len(achados)} achado(s).")

    @app.get("/entregas/baixar")
    def entregas_baixar():
        if not comum.PROJETO:
            abort(404)
        caminho = pasta_saida() / request.args.get("p", "")
        if not _dentro(pasta_saida(), caminho) or not caminho.is_file():
            abort(404)
        return send_file(caminho, as_attachment=True, download_name=caminho.name)

    @app.post("/entregas/mostrar")
    def entregas_mostrar():
        token_ok()
        if not comum.PROJETO:
            abort(404)
        pasta = pasta_saida() / request.form.get("p", "")
        if not _dentro(pasta_saida(), pasta) or not pasta.is_dir():
            abort(404)
        comando = (["explorer", str(pasta)] if WINDOWS else
                   ["open", str(pasta)] if sys.platform == "darwin" else ["xdg-open", str(pasta)])
        subprocess.run(comando, check=False)
        return _ir("/entregas")


_ULTIMA_QUALIDADE = {}   # slug -> achados da última verificação feita nesta sessão do painel
