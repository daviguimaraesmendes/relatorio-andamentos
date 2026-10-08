"""Tela de cadastro (mesma tela local da revisão, em /cadastro): clientes,
importação de lista de processos, edição da carteira e descoberta no DJEN.
Grava em clientes.json e carteira.json; nada sai da máquina, exceto as
consultas ao DJEN (API pública do CNJ) quando alguém pede.
"""
import html
import tempfile
import urllib.parse
from pathlib import Path

from flask import redirect, request

import carteira as cart
import comum
from comum import load_json, save_json
POLOS = [("", "não informado"), ("ativo", "autor"), ("passivo", "réu")]

ESTILO = """<style>
td.num{white-space:nowrap}
table{border-collapse:collapse;width:100%;margin:8px 0}
td,th{border-bottom:1px solid var(--linha);padding:6px 4px;text-align:left;font-size:14px;vertical-align:top}
input[type=text],select{width:100%;box-sizing:border-box;font:inherit;padding:4px}
.caixa{border:1px solid var(--linha);border-radius:6px;padding:12px;margin:12px 0}
.msg{background:#eef6ee;color:var(--ok);padding:8px 10px;border-radius:4px;margin:12px 0;white-space:pre-line}
.nav a{margin-right:16px}
.dica{color:var(--suave);font-size:13px}
.linha{display:grid;grid-template-columns:1fr 1fr;gap:8px}
@media (max-width:640px){.linha{grid-template-columns:1fr}}
</style>"""


def _e(x):
    return html.escape(str(x or ""))


def _ir(msg):
    return redirect("/cadastro?msg=" + urllib.parse.quote(msg))


def _clientes():
    return load_json(comum.CLIENTES_FILE, {"clientes": []})


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.get("/cadastro")
    def cadastro():
        dados = _clientes()
        clientes = dados.get("clientes", [])
        carteira = load_json(comum.CARTEIRA_FILE, [])
        import djen
        na_carteira = {p["numero"] for p in load_json(comum.CARTEIRA_FILE, [])}
        pendentes = [d for d in load_json(djen.DESCOBERTA_FILE, {}).get("pendentes", []) if d["numero"] not in na_carteira]
        nomes = [c["nome"] for c in clientes]
        opcoes_cli = lambda atual: "".join(
            f"<option value='{_e(n)}' {'selected' if n == atual else ''}>{_e(n)}</option>" for n in [""] + nomes)
        opcoes_polo = lambda atual: "".join(
            f"<option value='{v}' {'selected' if v == (atual or '') else ''}>{r}</option>" for v, r in POLOS)

        h = [cabecalho("cadastro"), ESTILO, "<h1>Clientes e processos</h1>"]
        if request.args.get("msg"):
            h.append(f"<div class='msg'>{_e(request.args['msg'])}</div>")

        # 1. clientes
        h.append("<h2>1. Clientes</h2><p class='dica'>Razão social exatamente como aparece nos processos. "
                 "Variações: nome fantasia, sigla, grafia sem LTDA, separadas por vírgula. "
                 "O responsável vale para todos os processos do cliente.</p>"
                 "<table><tr><th>Razão social</th><th>Variações</th><th>Contato</th><th>Responsável</th><th></th></tr>")
        for i, c in enumerate(clientes):
            fid = f"c{i}"
            h.append(f"<tr><td><form id='{fid}' method='post' action='/cadastro/cliente'>{oculto}"
                     f"<input type='hidden' name='indice' value='{i}'></form>"
                     f"<input form='{fid}' type='text' name='nome' value='{_e(c['nome'])}' required></td>"
                     f"<td><input form='{fid}' type='text' name='variacoes' value='{_e(', '.join(c.get('variacoes', [])))}'></td>"
                     f"<td><input form='{fid}' type='text' name='contato' value='{_e(c.get('contato'))}'></td>"
                     f"<td><input form='{fid}' type='text' name='responsavel' value='{_e(c.get('responsavel'))}'></td>"
                     f"<td><button form='{fid}' name='acao' value='salvar'>Salvar</button>"
                     f"<button form='{fid}' name='acao' value='remover' onclick=\"return confirm('Remover este cliente?')\">Remover</button></td></tr>")
        h.append(f"<tr><td><form id='cnovo' method='post' action='/cadastro/cliente'>{oculto}"
                 "<input type='hidden' name='indice' value='novo'></form>"
                 "<input form='cnovo' type='text' name='nome' placeholder='EMPRESA EXEMPLO COMERCIO LTDA' required></td>"
                 "<td><input form='cnovo' type='text' name='variacoes' placeholder='EMPRESA EXEMPLO, EXEMPLO'></td>"
                 "<td><input form='cnovo' type='text' name='contato' placeholder='e-mail ou WhatsApp'></td>"
                 "<td><input form='cnovo' type='text' name='responsavel' placeholder='Davi'></td>"
                 "<td><button form='cnovo' name='acao' value='salvar'>Adicionar</button></td></tr></table>")

        # 2. importar processos
        h.append(f"<h2>2. Importar processos</h2><form class='caixa' method='post' action='/cadastro/importar' enctype='multipart/form-data'>{oculto}"
                 "<p class='dica'>Cole números de processo (lista, e-mail, qualquer texto) ou envie uma planilha (.xlsx, .csv) "
                 "com as colunas processo, cliente, polo, parte contrária, responsável. Número com dígito verificador errado é recusado.</p>"
                 "<label>Texto colado<textarea name='texto' rows='5' placeholder='0000000-00.0000.0.00.0000'></textarea></label>"
                 "<p><label>ou arquivo <input type='file' name='arquivo' accept='.xlsx,.csv,.txt,.md'></label></p>"
                 "<p class='dica'>Os campos abaixo valem para os processos importados que vierem sem essa informação.</p>"
                 f"<div class='linha'><label>Cliente<select name='cliente'>{opcoes_cli('')}</select></label>"
                 f"<label>Polo do cliente<select name='polo'>{opcoes_polo('')}</select></label>"
                 "<label>Parte contrária<input type='text' name='parte_contraria'></label>"
                 "<label>Responsável<input type='text' name='responsavel'></label></div>"
                 "<p><label><input type='checkbox' name='djen' value='1'> Completar polo e parte contrária pelo DJEN "
                 "(cerca de 3 segundos por processo)</label></p><button>Importar</button></form>")

        # 3. carteira
        ativos = sum(p.get("ativo", True) for p in carteira)
        h.append(f"<h2>3. Carteira ({ativos} ativo(s) de {len(carteira)})</h2>"
                 "<table><tr><th>Processo</th><th>Cliente</th><th>Polo</th><th>Parte contrária</th><th>Responsável</th><th>Ativo</th><th></th></tr>")
        for i, p in enumerate(carteira):
            n, fid = _e(p["numero"]), f"p{i}"
            h.append(f"<tr><td class='num'><form id='{fid}' method='post' action='/cadastro/processo'>{oculto}"
                     f"<input type='hidden' name='numero' value='{n}'></form>"
                     f"{n}<br><span class='dica'>{_e(p.get('tribunal'))}</span></td>"
                     f"<td><select form='{fid}' name='cliente'>{opcoes_cli(p.get('cliente', ''))}</select></td>"
                     f"<td><select form='{fid}' name='polo'>{opcoes_polo(p.get('polo_cliente'))}</select></td>"
                     f"<td><input form='{fid}' type='text' name='parte_contraria' value='{_e(p.get('parte_contraria'))}'></td>"
                     f"<td><input form='{fid}' type='text' name='responsavel' value='{_e(p.get('responsavel'))}'></td>"
                     f"<td><input form='{fid}' type='checkbox' name='ativo' value='1' {'checked' if p.get('ativo', True) else ''}></td>"
                     f"<td><button form='{fid}' name='acao' value='salvar'>Salvar</button>"
                     f"<button form='{fid}' name='acao' value='remover' onclick=\"return confirm('Remover o processo da carteira?')\">Remover</button></td></tr>")
        if not carteira:
            h.append("<tr><td colspan='7' class='dica'>Carteira vazia.</td></tr>")
        h.append("</table>")
        sem_cli = sum(1 for p in carteira if not p.get("cliente"))
        if carteira and sem_cli:
            opcoes_lote = "".join(f"<option value='{_e(n)}'></option>" for n in nomes)
            h.append(f"<div class='caixa'><b>{sem_cli} processo(s) sem cliente: resolva de uma vez.</b>"
                     f"<form method='post' action='/cadastro/lote' style='margin:8px 0'>{oculto}"
                     "<button name='acao' value='identificar'>Identificar os clientes pelas partes dos processos</button> "
                     "<span class='dica'>usa os clientes cadastrados acima (nome e variações) e define também o polo e a parte contrária.</span></form>"
                     f"<form method='post' action='/cadastro/lote'>{oculto}"
                     "<label>Ou coloque o mesmo cliente em todos os que estão sem cliente: "
                     f"<input type='text' name='cliente' list='clientes-lote' size='40' placeholder='nome do cliente' required></label>"
                     f"<datalist id='clientes-lote'>{opcoes_lote}</datalist> "
                     "<button name='acao' value='todos_sem_cliente'>Aplicar a todos os sem cliente</button></form></div>")
        faltando = sum(1 for p in carteira if p.get("cliente") and not (p.get("polo_cliente") and p.get("parte_contraria")))
        sem_cliente = sum(1 for p in carteira if not p.get("cliente"))
        if carteira:
            h.append(f"<form class='caixa' method='post' action='/cadastro/completar'>{oculto}"
                     f"<p class='dica'>{faltando} processo(s) com cliente e sem polo ou parte contrária; "
                     f"{sem_cliente} sem cliente (escolha o cliente na linha e salve antes). "
                     "A busca leva cerca de 3 segundos por processo.</p>"
                     f"<button {'disabled' if not faltando else ''}>Completar pelo DJEN</button></form>")

        # 4. descoberta
        h.append(f"<h2>4. Descoberta no DJEN</h2><form class='caixa' method='post' action='/cadastro/descobrir'>{oculto}"
                 "<p class='dica'>Procura publicações pelo nome de cada cliente e lista processos que não estão na carteira. "
                 "Só aparece processo com publicação no período. Nada entra sozinho.</p>"
                 "<label>Últimos <input type='text' name='dias' value='180' style='width:60px'> dias</label> "
                 "<button>Procurar</button></form>")
        if pendentes:
            h.append("<table><tr><th>Processo</th><th>Cliente</th><th>Polo</th><th>Outras partes</th><th>Última publicação</th><th></th></tr>")
            for d in pendentes:
                h.append(f"<tr><td>{_e(d['numero'])}<br><span class='dica'>{_e(d['tribunal'])}</span></td>"
                         f"<td>{_e(d['cliente'])}</td><td>{_e(d.get('polo_cliente') or '?')}</td>"
                         f"<td>{_e(d.get('outras_partes'))}</td><td>{_e(d.get('ultima'))}</td>"
                         f"<td><form method='post' action='/cadastro/pendente'>{oculto}<input type='hidden' name='numero' value='{_e(d['numero'])}'>"
                         "<button name='acao' value='incluir'>Incluir</button><button name='acao' value='ignorar'>Ignorar</button></form></td></tr>")
            h.append("</table>")
        return "".join(h)

    @app.post("/cadastro/cliente")
    def salvar_cliente():
        token_ok()
        dados = _clientes()
        lista = dados.setdefault("clientes", [])
        f = request.form
        if f["acao"] == "remover":
            nome = lista[int(f["indice"])]["nome"]
            em_uso = [p["numero"] for p in load_json(comum.CARTEIRA_FILE, []) if p.get("cliente") == nome]
            if em_uso:
                return _ir(f"{nome} tem {len(em_uso)} processo(s) na carteira: troque o cliente ou remova os processos antes.")
            lista.pop(int(f["indice"]))
            save_json(comum.CLIENTES_FILE, dados)
            return _ir(f"Cliente removido: {nome}")
        novo = {"nome": f["nome"].strip(),
                "variacoes": [v.strip() for v in f.get("variacoes", "").split(",") if v.strip()],
                "contato": f.get("contato", "").strip(), "responsavel": f.get("responsavel", "").strip()}
        if f["indice"] == "novo":
            if any(cart.normalizar(c["nome"]) == cart.normalizar(novo["nome"]) for c in lista):
                return _ir(f"{novo['nome']} já está cadastrado.")
            lista.append(novo)
        else:
            antigo = lista[int(f["indice"])]["nome"]
            lista[int(f["indice"])] = novo
            if antigo != novo["nome"]:  # renomeado: acompanha nos processos
                carteira = load_json(comum.CARTEIRA_FILE, [])
                for p in carteira:
                    if p.get("cliente") == antigo or (p.get("campos", {}).get("cliente") or {}).get("valor") == antigo:
                        cart.gravar_plano(p, "cliente", novo["nome"])
                save_json(comum.CARTEIRA_FILE, carteira)
        save_json(comum.CLIENTES_FILE, dados)
        return _ir(f"Cliente salvo: {novo['nome']}")

    @app.post("/cadastro/importar")
    def importar():
        token_ok()
        f = request.form
        arquivo = request.files.get("arquivo")
        with tempfile.TemporaryDirectory() as tmp:
            if arquivo and arquivo.filename:
                origem = Path(tmp) / ("lista" + Path(arquivo.filename).suffix.lower())
                arquivo.save(origem)
            elif f.get("texto", "").strip():
                origem = Path(tmp) / "lista.txt"
                origem.write_text(f["texto"], encoding="utf-8")
            else:
                return _ir("Nada para importar: cole os números ou escolha um arquivo.")
            regs, ruins = cart.ler_lista(str(origem), f.get("cliente", ""))
        for r in regs:
            for campo, valor in (("polo_cliente", f.get("polo")), ("parte_contraria", f.get("parte_contraria", "").strip()),
                                 ("responsavel", f.get("responsavel", "").strip())):
                if valor and not r.get(campo):
                    r[campo] = valor
        novos = cart.mesclar(regs, "lista")
        msg = [f"{len(regs)} número(s) lido(s), {novos} novo(s) na carteira."]
        if ruins:
            msg.append("Recusados (dígito verificador não confere): " + ", ".join(ruins))
        sem_cliente = sum(1 for r in regs if not r.get("cliente"))
        if sem_cliente:
            msg.append(f"{sem_cliente} processo(s) sem cliente: escolha o cliente na carteira.")
        if f.get("djen") and regs:
            feitos, sem_cli = cart.completar_com_djen({r["numero"] for r in regs})
            msg.append(f"DJEN: {feitos} processo(s) completado(s) com polo e parte contrária."
                       + (f" {sem_cli} ficaram de fora por estarem sem cliente: escolha o cliente na carteira"
                          " e use o botão 'Completar pelo DJEN'." if sem_cli else ""))
        return _ir("\n".join(msg))

    @app.post("/cadastro/processo")
    def salvar_processo():
        token_ok()
        f = request.form
        carteira = load_json(comum.CARTEIRA_FILE, [])
        if f["acao"] == "remover":
            carteira = [p for p in carteira if p["numero"] != f["numero"]]
            save_json(comum.CARTEIRA_FILE, carteira)
            return _ir(f"Processo removido da carteira: {f['numero']}")
        for p in carteira:
            if p["numero"] == f["numero"]:
                for campo, valor in (("cliente", f.get("cliente", "")), ("polo_cliente", f.get("polo", "")),
                                     ("parte_contraria", f.get("parte_contraria", "").strip()),
                                     ("responsavel", f.get("responsavel", "").strip())):
                    if valor != (p.get(campo) or ""):
                        cart.gravar_plano(p, campo, valor)
                p["ativo"] = bool(f.get("ativo"))
        save_json(comum.CARTEIRA_FILE, carteira)
        return _ir(f"Processo salvo: {f['numero']}")

    @app.post("/cadastro/lote")
    def lote():
        """Cliente em lote: identificar pelas partes, ou o mesmo cliente para todos os processos sem cliente."""
        token_ok()
        import clientes as cli
        import ficha as fch
        f = request.form
        fichas = fch.carregar(todas=True)
        if f.get("acao") == "identificar":
            especs = cli.especs_do_projeto()
            if not especs:
                return _ir("Cadastre primeiro o cliente (razão social e variações), ou use \"Aplicar a todos os sem cliente\".")
            rel = cli.identificar(fichas, especs)
            fch.salvar(fichas)
            msg = ", ".join(f"{q} em {c}" for c, q in sorted(rel["aplicados"].items())) or "nenhum processo casou"
            texto = f"Clientes identificados pelas partes: {msg}."
            if rel["ambiguos"]:
                texto += f" {len(rel['ambiguos'])} com o cliente nos dois lados (confira o polo)."
            if rel["sem_correspondencia"]:
                texto += f" {len(rel['sem_correspondencia'])} continuam sem cliente."
            return _ir(texto)
        if f.get("acao") == "todos_sem_cliente":
            nome = f.get("cliente", "").strip()
            if not nome:
                return _ir("Informe o nome do cliente.")
            n = cli.aplicar_em_lote(fichas, nome, so_sem_cliente=True)
            fch.salvar(fichas)
            cli.registrar([{"nome": nome, "variacoes": []}])
            return _ir(f"{n} processo(s) agora são do cliente {nome}.")
        return _ir("Ação desconhecida.")

    @app.post("/cadastro/completar")
    def completar():
        token_ok()
        feitos, sem_cli = cart.completar_com_djen()
        return _ir(f"DJEN: {feitos} processo(s) completado(s) com polo e parte contrária."
                   + (f" {sem_cli} sem cliente ficaram de fora." if sem_cli else "")
                   + " Processo sem publicação no DJEN precisa ser preenchido à mão.")

    @app.post("/cadastro/descobrir")
    def descobrir():
        token_ok()
        import djen
        if not _clientes().get("clientes"):
            return _ir("Cadastre ao menos um cliente antes de procurar no DJEN.")
        try:
            dias = max(1, min(int(request.form.get("dias", "180")), 730))
        except ValueError:
            dias = 180
        djen.descobrir(dias)
        n = len(load_json(djen.DESCOBERTA_FILE, {}).get("pendentes", []))
        return _ir(f"Descoberta concluída: {n} processo(s) fora da carteira.")

    @app.post("/cadastro/pendente")
    def pendente():
        token_ok()
        import djen
        numero, acao = request.form["numero"], request.form["acao"]
        (djen.incluir if acao == "incluir" else djen.ignorar)([numero])
        return _ir(f"{numero}: {'incluído na carteira' if acao == 'incluir' else 'ignorado'}.")
