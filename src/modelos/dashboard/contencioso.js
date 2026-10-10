"use strict";
/* Modelo "contencioso": painel executivo de uma carteira de litígios (KPIs, roscas e barras, filtros, tabela,
 * série histórica). Usa o núcleo (nucleo.js); aqui só ficam os blocos e os textos. Os indicadores vêm de
 * ctx.ind (calculados no núcleo, com as regras de integridade descritas lá). */
(function () {
  let paretoPorValor = false;

  function montar(h) {
    const P = h.html_painel;
    return '<div class="sec"><span class="n">01</span><h2>Carteira e volume</h2><div class="regua"></div></div>'
      + '<div class="kpis" id="kpis-carteira"></div><div id="faixa-carteira"></div>'
      + '<div class="grade" style="margin-top:16px">'
      + P("risco", "Onde está o risco", "", { altura: "alto" })
      + P("fase", "Fase processual", "Processos ativos, por fase")
      + P("concentracao", "O risco está concentrado ou espalhado?", "", { largo: true, altura: "baixo" })
      + P("probexp", "Exposição por probabilidade", "Processos ativos com o cliente no polo passivo")
      + P("momento", "Momento atual", "Processos ativos, os 10 momentos mais frequentes")
      + P("fluxo", "Fluxo: ajuizamentos e encerramentos por ano", "", { largo: true })
      + P("municipio", "Litigiosidade por município", "Onde o passivo nasce", { altura: "alto" })
      + P("tribunal", "Distribuição por tribunal", "Dispersão jurisdicional", { altura: "alto" })
      + P("reu", "Concentração por empresa do grupo", "", { largo: true, altura: "alto" })
      + "</div>"
      + '<div class="sec"><span class="n">02</span><h2>Desempenho e desfechos</h2><div class="regua"></div></div>'
      + '<div class="kpis" id="kpis-desempenho"></div><div id="nota-economia"></div>'
      + '<div class="grade" style="margin-top:16px">'
      + P("resultado", "Distribuição de resultados", "", { altura: "alto" })
      + P("defesa", "Onde a defesa ganha e onde perde", "", { altura: "alto" })
      + "</div>"
      + h.montarContingencia()
      + '<div class="sec"><span class="n">03</span><h2>Causa-raiz e prevenção</h2><div class="regua"></div></div>'
      + '<div class="grade">'
      + '<div class="painel largo" id="p-pareto"><h3>Quais teses geram o passivo <button type="button" class="btn sec nao-imprimir" id="b-pareto" style="float:right;padding:3px 10px;font-size:11px">ver por R$</button></h3><div class="sub" id="sub-pareto"></div>'
      + '<div class="caixa-graf alto"><canvas id="ch-pareto" role="img" aria-label="Teses que geram o passivo"></canvas></div><details class="tabela-dados"><summary>Ver como tabela</summary><div class="rolagem" id="td-pareto"></div></details></div>'
      + P("tese", "O passivo vem de poucas teses ou de muitas?", "", { largo: true, altura: "baixo" })
      + P("terc", "Origem dos reclamantes (terceirização)", "Só quando a planilha informa", {})
      + "</div>"
      + '<div class="sec"><span class="n">04</span><h2>Ao longo do tempo</h2><div class="regua"></div></div>'
      + '<div id="aviso-serie"></div><div class="grade">'
      + P("serie_qtd", "Processos ao longo do tempo", "Carteira inteira (não segue os filtros)")
      + P("serie_valor", "Valores ao longo do tempo", "Carteira inteira (não segue os filtros)")
      + "</div>";
  }

  function barraConcentracao(h, id, itens, rotuloTop, rotuloResto, ehDinheiro, topN, textoSub) {
    const total = itens.reduce((s, x) => s + x, 0);
    if (!total) { h.marcarVazio(id, true); return; }
    h.marcarVazio(id, false);
    const top = itens.slice(0, topN).reduce((s, x) => s + x, 0);
    let ac = 0, n80 = itens.length;
    for (let i = 0; i < itens.length; i++) { ac += itens[i]; if (ac / total >= 0.8) { n80 = i + 1; break; } }
    const fm = ehDinheiro ? h.fmtBRL : h.fmtNum;
    h.grafico(id, { type: "bar", data: { labels: ["Total"], datasets: [
      { label: rotuloTop, data: [top], backgroundColor: h.cat(1), borderRadius: 0 },
      { label: rotuloResto, data: [total - top], backgroundColor: h.cat("outros"), borderRadius: 0 }] },
      options: { indexAxis: "y", maintainAspectRatio: false, _inteiro: !ehDinheiro,
        plugins: { legend: { display: true, position: "bottom" }, tooltip: { callbacks: { label: (c) => c.dataset.label + ": " + fm(c.parsed.x) + " (" + Math.round((c.parsed.x / total) * 100) + "%)" } } },
        scales: { x: { stacked: true, beginAtZero: true, max: total, ticks: { stepSize: total / 10, callback: (v) => Math.round((v / total) * 100) + "%" } }, y: { stacked: true, ticks: { display: false } } } } });
    h.$("sub-" + id).textContent = textoSub(Math.round((top / total) * 100), n80, itens.length);
  }

  function render(ctx) {
    const { D, ind, h } = ctx, $ = h.$, kpi = h.kpi;
    const ativos = D.filter((r) => r.ativo);
    const passivos = ativos.filter((r) => r.polo !== "ativo");

    /* ---- 01 carteira ---- */
    $("kpis-carteira").innerHTML =
      kpi("total", "Total de processos", h.fmtNum(ind.total), ind.judiciais + " judiciais · " + ind.administrativos + " administrativos", ind.total)
      + kpi("ativos", "Processos ativos", h.fmtNum(ind.ativos), h.fmtPct(ind.ativos, ind.total) + " da seleção", ind.ativos, "c")
      + kpi("encerrados", "Processos encerrados", h.fmtNum(ind.encerrados), h.fmtPct(ind.encerrados, ind.total) + " da seleção", ind.encerrados, "n")
      + kpi("saldo12", "Saldo da carteira (12 meses)", (ind.saldo12 > 0 ? "+" : "") + h.fmtNum(ind.saldo12),
        ind.entradas12 + " entradas × " + ind.baixas12 + " encerramentos · " + (ind.saldo12 > 0 ? "carteira crescendo" : ind.saldo12 < 0 ? "carteira diminuindo" : "estável"), ind.saldo12, ind.saldo12 > 0 ? "b" : "c")
      + kpi("valor_causa_ativos", "Valor da causa (ativos)", h.fmtBRLc(ind.valorCausaAtivos), "soma dos processos ativos", ind.valorCausaAtivos, "d")
      + kpi("exposicao", "Exposição estimada (ativos)", h.fmtBRLc(ind.exposicao),
        "valor estimado, ou arbitrado, ou da causa" + (ind.poloAtivoAtivos ? " · " + ind.poloAtivoAtivos + " com o cliente no polo ativo fora (crédito, não risco)" : ""), ind.exposicao, "b")
      + kpi("exposicao_provavel", "Exposição com perda provável", h.fmtBRLc(ind.exposicaoProb["Provável"]), "ativos com probabilidade \"Provável\"", ind.exposicaoProb["Provável"], "b")
      + (ind.processosPor100 != null ? kpi("por100", "Ativos por 100 empregados", h.fmtDec(ind.processosPor100, 1), "headcount informado na planilha", ind.processosPor100, "d") : "");
    const pAt = ind.total ? Math.round((ind.ativos / ind.total) * 100) : 0;
    $("faixa-carteira").innerHTML = ind.total ? '<div class="nota"><b>Andamento da carteira:</b> ' + pAt + "% em curso (" + h.fmtNum(ind.ativos) + ") · " + (100 - pAt) + "% encerrados (" + h.fmtNum(ind.encerrados) + ")"
      + '<div class="faixa" role="img" aria-label="' + pAt + '% em curso, ' + (100 - pAt) + '% encerrados"><span style="width:' + pAt + '%;background:' + h.cat(1) + '"></span><span style="width:' + (100 - pAt) + '%;background:' + h.cat(2) + '"></span></div></div>' : "";

    const expo = passivos.filter((r) => (r.valorExposicao || 0) > 0).sort((a, b) => b.valorExposicao - a.valorExposicao);
    h.marcarVazio("risco", !expo.length);
    if (expo.length) {
      const top = expo.slice(0, 10), t5 = expo.slice(0, 5).reduce((s, r) => s + Math.round(r.valorExposicao * 100), 0) / 100;
      h.grafico("risco", { type: "bar", data: { labels: top.map((r) => (r.materia || "(sem matéria)") + " · " + (r.municipio || r.tribunal || "—")),
        datasets: [{ label: "Exposição", data: top.map((r) => r.valorExposicao), backgroundColor: h.cat(1), borderRadius: 4, maxBarThickness: 22 }] }, options: h.opBarra({ horizontal: true, dinheiro: true }) });
      $("sub-risco").textContent = "Os 10 maiores processos ativos · os 5 maiores concentram " + Math.round((t5 / ind.exposicao) * 100) + "% da exposição";
      barraConcentracao(h, "concentracao", expo.map((r) => r.valorExposicao), Math.min(5, expo.length) + " maiores processos", "os outros " + Math.max(expo.length - 5, 0), true, 5,
        (p, n80, n) => "Os 5 maiores valem " + p + "% da exposição. São necessários " + n80 + " dos " + n + " processos para chegar a 80%.");
    } else h.marcarVazio("concentracao", true);

    h.roscaDeMapa("fase", h.contar(ativos, (r) => r.fase || "(não informado)"), "Processos ativos por fase.");
    const ep = ind.exposicaoProb, ordem = ["Provável", "Possível", "Remota", "semProb"], nomes = { semProb: "Sem probabilidade" };
    const temEp = ordem.some((k) => ep[k] > 0);
    h.marcarVazio("probexp", !temEp);
    if (temEp) h.grafico("probexp", { type: "bar", data: { labels: ordem.map((k) => nomes[k] || k), datasets: [{ label: "Exposição", data: ordem.map((k) => ep[k]),
      backgroundColor: ordem.map((k) => h.css(h.COR_PROB[k])), borderRadius: 4, maxBarThickness: 40 }] }, options: h.opBarra({ dinheiro: true }) });
    h.barrasDeMapa("momento", h.contar(ativos, (r) => r.momento), 10, h.cat(0));

    // fluxo anual (só judicial): ajuizamentos x encerramentos; encerramento = trânsito, ou o último andamento do encerrado
    const jud = D.filter((r) => r.natureza === "Judicial"), ent = {}, sai = {};
    jud.forEach((r) => { if (r.dataAjuiz) ent[r.dataAjuiz.slice(0, 4)] = (ent[r.dataAjuiz.slice(0, 4)] || 0) + 1; if (!r.ativo && r.dataEnc) sai[r.dataEnc.slice(0, 4)] = (sai[r.dataEnc.slice(0, 4)] || 0) + 1; });
    const anos = [...new Set([...Object.keys(ent), ...Object.keys(sai)])].sort();
    h.marcarVazio("fluxo", !anos.length);
    if (anos.length) h.grafico("fluxo", { type: "bar", data: { labels: anos, datasets: [
      { label: "Ajuizamentos", data: anos.map((a) => ent[a] || 0), backgroundColor: h.cat(1), borderRadius: 4 },
      { label: "Encerramentos", data: anos.map((a) => sai[a] || 0), backgroundColor: h.cat(0), borderRadius: 4 }] }, options: h.opBarra({ legenda: true }) });
    $("sub-fluxo").textContent = "Só processos judiciais. Encerramento = data do trânsito em julgado ou, na falta, a do último andamento do processo encerrado.";

    h.barrasDeMapa("municipio", h.contar(D.filter((r) => r.municipio), (r) => r.municipio), 12, h.cat(0));
    h.barrasDeMapa("tribunal", h.contar(D.filter((r) => r.tribunal), (r) => r.tribunal), 12, h.cat(6));
    // concentração por réu: só empresas do grupo (lista do perfil ou da aba Parâmetros); sem lista, os réus mais frequentes
    const g = h.grupo();
    if (g.length) {
      const doGrupo = D.map((r) => h.empresaDoGrupo(r.reus)).filter(Boolean);
      const fora = D.length - doGrupo.length;
      h.barrasDeMapa("reu", h.contar(doGrupo, (x) => x), 10, h.cat(1));
      $("sub-reu").textContent = "Só as empresas do grupo informadas no perfil ou na aba Parâmetros" + (fora ? " · " + fora + " processo(s) com réu fora da lista não aparecem aqui" : "");
    } else {
      h.barrasDeMapa("reu", h.contar(D.filter((r) => r.reus), (r) => h.curto(r.reus, 40)), 10, h.cat(1));
      $("sub-reu").textContent = "Réus mais frequentes (informe as empresas do grupo no perfil para agrupá-las)";
    }

    /* ---- 02 desempenho ---- */
    const c = ind.resultadoClasses, cr = ind.comResultado;
    const pct = (n) => h.fmtPct(n, cr), base = "de " + h.fmtNum(cr) + " com resultado lançado";
    const e = ind.economia, fora = e.fora, totalFora = Object.values(fora).reduce((a, b) => a + b, 0);
    $("kpis-desempenho").innerHTML =
      kpi("parcial", "Parcialmente procedentes", pct(c.parcial), c.parcial + " " + base, c.parcial, "b")
      + kpi("acordo", "Taxa de acordo", pct(c.acordo), c.acordo + " " + base, c.acordo)
      + kpi("improcedencia", "Índice de improcedência", pct(c.improcedente), c.improcedente + " " + base, c.improcedente, "c")
      + kpi("extincao", "Extinções sem mérito", pct(c.extinto), c.extinto + " " + base, c.extinto, "n")
      + kpi("tempo_medio", "Tempo médio até o encerramento", ind.tempoMedioDias == null ? "—" : h.fmtNum(ind.tempoMedioDias) + " dias", ind.encerradosComTempo + " encerrados com datas", ind.tempoMedioDias, "n")
      + kpi("economia", "Economia apurada", h.fmtBRLc(e.valor), e.elegiveis + " processo(s) encerrado(s) com valor lançado" + (e.pct != null ? " · " + Math.round(e.pct * 100) + "% do valor da causa deles" : ""), e.valor, "d");
    const partes = Object.keys(fora).filter((k) => fora[k]).map((k) => "<b>" + fora[k] + "</b> " + h.MOTIVOS[k]);
    $("nota-economia").innerHTML = '<div class="nota' + (totalFora ? " alerta" : "") + '" data-fora="' + totalFora + '"><b>Como a economia é calculada:</b> valor da causa menos valor estimado (ou o valor economizado lançado), só de processo encerrado e com valor lançado. '
      + (totalFora ? "Ficam <b>fora do indicador</b>, para não inflar o número: " + partes.join("; ") + ". A lista está na aba \"Qualidade dos dados\"." : "Nenhum caso ficou fora do indicador nesta seleção.") + "</div>";

    const rotulosRes = Object.keys(h.RESULTADOS).filter((k) => c[k] > 0);
    const corRes = { procedente: "--critico", parcial: "--alerta", improcedente: "--bom", acordo: "--s1", extinto: "--outros", arquivado: "--outros", incompetencia: "--outros", exclusao: "--outros", outro: "--outros" };
    h.marcarVazio("resultado", !rotulosRes.length);
    if (rotulosRes.length) {
      h.grafico("resultado", { type: "bar", data: { labels: rotulosRes.map((k) => h.RESULTADOS[k]), datasets: [{ label: "Processos", data: rotulosRes.map((k) => c[k]),
        backgroundColor: rotulosRes.map((k) => h.css(corRes[k])), borderRadius: 4, maxBarThickness: 22 }] }, options: h.opBarra({ horizontal: true }) });
    }
    $("sub-resultado").textContent = "Processos com resultado lançado (ativos e encerrados)";
    // defesa: só mérito (procedente / parcial / improcedente), sem acordos, extinções, incompetência e sem o cliente como autor
    const FORA_RANK = new Set(h.cfg.materias_fora_do_ranking || []);   // acessórias/genéricas (taxonomia.MATERIA, "entra nos rankings" = não)
    const merito = D.filter((r) => ["procedente", "parcial", "improcedente"].includes(r.classeRes) && r.polo !== "ativo" && !FORA_RANK.has(r.materia));
    const bal = {};
    merito.forEach((r) => { const k = r.materia || "(não informado)"; bal[k] = bal[k] || { fav: 0, par: 0, des: 0 }; bal[k][r.classeRes === "improcedente" ? "fav" : r.classeRes === "parcial" ? "par" : "des"]++; });
    const bk = Object.entries(bal).sort((a, b) => (b[1].fav + b[1].par + b[1].des) - (a[1].fav + a[1].par + a[1].des) || a[0].localeCompare(b[0], "pt-BR")).slice(0, 10);
    h.marcarVazio("defesa", !bk.length);
    if (bk.length) h.grafico("defesa", { type: "bar", data: { labels: bk.map((x) => x[0]), datasets: [
      { label: "Improcedente", data: bk.map((x) => x[1].fav), backgroundColor: h.css("--bom") },
      { label: "Parcialmente procedente", data: bk.map((x) => x[1].par), backgroundColor: h.css("--alerta") },
      { label: "Procedente", data: bk.map((x) => x[1].des), backgroundColor: h.css("--critico") }] }, options: h.opBarra({ horizontal: true, empilhado: true, legenda: true }) });
    $("sub-defesa").textContent = merito.length + " processos julgados no mérito (fora: acordos, extinções, incompetência e processos em que o cliente é autor)";

    h.desenharContingencia(ctx);          // bloco de contingência: só aparece quando a planilha traz passivo, provisão ou pagamentos

    /* ---- 03 causa-raiz ---- */
    const agg = {};
    D.forEach((r) => { const k = r.materia; if (!k || FORA_RANK.has(k)) return; agg[k] = agg[k] || { q: 0, s: 0 }; agg[k].q++; agg[k].s += Math.round((r.valorCausa || 0) * 100); });
    const teses = Object.entries(agg).map(([k, o]) => ({ k, q: o.q, s: o.s / 100 })).sort((a, b) => (paretoPorValor ? b.s - a.s : b.q - a.q) || a.k.localeCompare(b.k, "pt-BR"));
    const bp = $("b-pareto");
    if (bp) { bp.textContent = paretoPorValor ? "ver por quantidade" : "ver por R$"; bp.onclick = () => { paretoPorValor = !paretoPorValor; render(ctx); }; }
    $("sub-pareto").innerHTML = paretoPorValor ? "Soma do <b>valor da causa</b> por matéria principal (ativos e encerrados da seleção; sem as matérias acessórias ou genéricas, como \"Outros\")" : "Número de processos por matéria principal (ativos e encerrados da seleção; sem as matérias acessórias ou genéricas, como \"Outros\")";
    h.marcarVazio("pareto", !teses.length);
    if (teses.length) {
      const t = teses.slice(0, 12);
      h.grafico("pareto", { type: "bar", data: { labels: t.map((x) => x.k), datasets: [{ label: paretoPorValor ? "Valor da causa" : "Processos", data: t.map((x) => (paretoPorValor ? x.s : x.q)),
        backgroundColor: paretoPorValor ? h.cat(2) : h.cat(0), borderRadius: 4, maxBarThickness: 22 }] }, options: h.opBarra({ horizontal: true, dinheiro: paretoPorValor }) });
      barraConcentracao(h, "tese", teses.map((x) => (paretoPorValor ? x.s : x.q)), "3 maiores teses", "as outras " + Math.max(teses.length - 3, 0), paretoPorValor, 3,
        (p, n80, n) => "As 3 maiores teses respondem por " + p + "% do " + (paretoPorValor ? "valor" : "volume") + ". São necessárias " + n80 + " das " + n + " teses para chegar a 80%: " + (n80 <= 3 ? "causa-raiz concentrada." : "origem difusa."));
    } else h.marcarVazio("tese", true);
    const terc = h.contar(D.filter((r) => r.area === "Trabalhista" && r.terceirizado), (r) => r.terceirizado);
    $("p-terc").hidden = !Object.keys(terc).length;
    if (Object.keys(terc).length) h.roscaDeMapa("terc", terc, "Origem dos reclamantes trabalhistas.");

    /* ---- 04 série histórica ---- */
    const serie = h.serieHistorica({ total: ctx.indTodos.total, ativos: ctx.indTodos.ativos, encerrados: ctx.indTodos.encerrados,
      valorCausa: ctx.indTodos.valorCausaTotal, valorEstimado: null, valorEconomizado: ctx.indTodos.economia.valor });
    const reais = serie.filter((p) => !p.atual).length;
    $("aviso-serie").innerHTML = reais < 1 ? '<div class="nota">A série histórica aparece quando houver ao menos um retrato anterior (aba "Histórico" da planilha ou retratos mensais gerados a cada atualização). Hoje só existe o retrato desta planilha.</div>' : "";
    const rot = serie.map((p) => h.fmtData(p.data) + (p.atual ? " (esta planilha)" : ""));
    const linha = (rotulo, campo, i) => ({ label: rotulo, data: serie.map((p) => p[campo]), borderColor: h.cat(i), backgroundColor: h.cat(i), borderWidth: 2, pointRadius: 4, spanGaps: false, tension: 0 });
    const opLinha = (din) => ({ maintainAspectRatio: false, _inteiro: !din, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: true, position: "bottom" }, tooltip: { callbacks: { label: (x) => x.dataset.label + ": " + (din ? h.fmtBRL(x.parsed.y) : h.fmtNum(x.parsed.y)) } } },
      scales: { y: { beginAtZero: true, ticks: { callback: din ? (v) => h.fmtBRLc(v) : undefined, precision: 0 } } } });
    h.marcarVazio("serie_qtd", false); h.marcarVazio("serie_valor", false);
    h.grafico("serie_qtd", { type: "line", data: { labels: rot, datasets: [linha("Total", "total", 0), linha("Ativos", "ativos", 1), linha("Encerrados", "encerrados", 2)] }, options: opLinha(false) });
    h.grafico("serie_valor", { type: "line", data: { labels: rot, datasets: [linha("Valor da causa", "valorCausa", 0), linha("Valor estimado", "valorEstimado", 3), linha("Economia", "valorEconomizado", 2)] }, options: opLinha(true) });
  }

  const tag = (txt, cls) => '<span class="etq ' + (cls || "") + '">' + txt + "</span>";
  const colunas = [
    { k: "numero", rotulo: "Nº do processo", valor: (r) => r.numero, html: (r) => r.numeros.map((n) => "<span>" + DASH.AJUDAS.esc(n) + "</span>").join("") + (r.ativo ? "" : '<span style="font-weight:400;color:var(--tinta-3)">encerrado</span>') + (r.dvOk === false ? tag("DV inválido", "prov") : "") },
    { k: "area", rotulo: "Área", valor: (r) => r.area, html: (r) => DASH.AJUDAS.esc(r.area) + '<br><span style="font-size:11px;color:var(--tinta-3)">' + DASH.AJUDAS.esc(r.natureza) + "</span>" },
    { k: "reus", rotulo: "Réu", valor: (r) => r.reus, html: (r) => DASH.AJUDAS.esc(DASH.AJUDAS.curto(r.reus || "—", 38)) },
    { k: "materia", rotulo: "Matéria", valor: (r) => r.materia, html: (r) => DASH.AJUDAS.esc(r.materia || "—") },
    { k: "tribunal", rotulo: "Tribunal", valor: (r) => r.tribunal, html: (r) => DASH.AJUDAS.esc(r.tribunal || "—") },
    { k: "momento", rotulo: "Momento atual", valor: (r) => r.momento, html: (r) => DASH.AJUDAS.esc(r.momento || r.fase || "—") },
    { k: "prob", rotulo: "Prob.", valor: (r) => r.prob || "", html: (r) => DASH.AJUDAS.etiquetaProb(r.prob) },
    { k: "valorCausa", rotulo: "Valor da causa", num: true, valor: (r) => r.valorCausa, html: (r) => DASH.AJUDAS.fmtBRL(r.valorCausa) },
    { k: "valorEstimado", rotulo: "Valor estimado", num: true, valor: (r) => r.valorEstimado, html: (r) => DASH.AJUDAS.fmtBRL(r.valorEstimado) },
    { k: "resultado", rotulo: "Resultado", valor: (r) => r.resultado, html: (r) => DASH.AJUDAS.esc(r.resultado || "—") },
    { k: "economia", rotulo: "Economia", num: true, valor: (r) => r.econ.valor, html: (r) => r.ativo ? "—" : r.econ.fora ? tag("fora: " + DASH.AJUDAS.esc(DASH.AJUDAS.MOTIVOS[r.econ.fora]), "fora") : DASH.AJUDAS.fmtBRL(r.econ.valor) }
  ];
  DASH.registrarModelo({ montar, render, colunas, numeroTabela: "05" });
})();
