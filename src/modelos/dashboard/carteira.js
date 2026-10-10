"use strict";
/* Modelo "carteira simples" (no estilo do relatório em texto, modelo A): quantos processos há em cada momento
 * atual, por área e matéria, por tribunal, e há quanto tempo cada processo ativo está sem andamento.
 * Não depende de valores em dinheiro nem de probabilidade. Usa o núcleo (nucleo.js). */
(function () {
  const FAIXAS = ["até 15 dias", "16 a 30 dias", "31 a 60 dias", "61 a 90 dias", "mais de 90 dias", "sem data"];

  function montar(h) {
    const P = h.html_painel;
    return '<div class="sec"><span class="n">01</span><h2>Visão da carteira</h2><div class="regua"></div></div>'
      + '<div class="kpis" id="kpis-carteira"></div>'
      + '<div class="grade" style="margin-top:16px">'
      + P("momento", "Processos por momento atual", "Processos ativos, os 12 momentos mais frequentes", { largo: true, altura: "alto" })
      + P("area", "Por área do direito", "Todos os processos da seleção")
      + P("materia", "Por matéria principal", "As 10 matérias mais frequentes", { altura: "alto" })
      + P("tribunal", "Por tribunal", "Todos os processos da seleção", { largo: true, altura: "alto" })
      + "</div>"
      + '<div class="sec"><span class="n">02</span><h2>Prazos de último andamento</h2><div class="regua"></div></div>'
      + '<div class="kpis" id="kpis-prazos"></div>'
      + '<div class="grade" style="margin-top:16px">'
      + P("faixas", "Há quanto tempo sem andamento", "Processos ativos, por tempo desde o último andamento")
      + P("atraso_momento", "Processos parados há mais de 90 dias", "Por momento atual")
      + "</div>"
      + h.montarContingencia()
      + '<div class="sec"><span class="n">03</span><h2>Ao longo do tempo</h2><div class="regua"></div></div>'
      + '<div id="aviso-serie"></div><div class="grade">'
      + P("serie_qtd", "Processos ao longo do tempo", "Carteira inteira (não segue os filtros)", { largo: true })
      + "</div>";
  }

  const comAlfa = (hex, a) => { const m = /^#([0-9a-f]{6})$/i.exec(hex.trim()); if (!m) return hex; const n = parseInt(m[1], 16); return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")"; };

  function render(ctx) {
    const { D, ind, h } = ctx, $ = h.$, kpi = h.kpi;
    const ativos = D.filter((r) => r.ativo);
    const dias = (r) => (r.ultimoAnd ? Math.max(h.diasEntre(r.ultimoAnd, ctx.dataBase), 0) : null);

    $("kpis-carteira").innerHTML =
      kpi("total", "Total de processos", h.fmtNum(ind.total), "na seleção atual", ind.total)
      + kpi("ativos", "Processos ativos", h.fmtNum(ind.ativos), h.fmtPct(ind.ativos, ind.total) + " da seleção", ind.ativos, "c")
      + kpi("encerrados", "Processos encerrados", h.fmtNum(ind.encerrados), h.fmtPct(ind.encerrados, ind.total) + " da seleção", ind.encerrados, "n")
      + kpi("saldo12", "Saldo da carteira (12 meses)", (ind.saldo12 > 0 ? "+" : "") + h.fmtNum(ind.saldo12), ind.entradas12 + " novos × " + ind.baixas12 + " encerrados", ind.saldo12, ind.saldo12 > 0 ? "b" : "c");
    $("kpis-prazos").innerHTML =
      kpi("sem_andamento_30", "Ativos sem andamento há mais de 30 dias", h.fmtNum(ind.semAndamento30), h.fmtPct(ind.semAndamento30, ind.ativosComData) + " dos ativos com data", ind.semAndamento30, "b")
      + kpi("sem_andamento_60", "Há mais de 60 dias", h.fmtNum(ind.semAndamento60), h.fmtPct(ind.semAndamento60, ind.ativosComData) + " dos ativos com data", ind.semAndamento60, "b")
      + kpi("sem_andamento_90", "Há mais de 90 dias", h.fmtNum(ind.semAndamento90), h.fmtPct(ind.semAndamento90, ind.ativosComData) + " dos ativos com data", ind.semAndamento90, "b")
      + kpi("mediana_dias", "Mediana de dias sem andamento", ind.medianaDias == null ? "—" : h.fmtNum(ind.medianaDias), "contados até " + h.fmtData(ctx.dataBase), ind.medianaDias, "d")
      + kpi("ativos_sem_data", "Ativos sem data de último andamento", h.fmtNum(ind.faixas["sem data"]), "não entram nos prazos", ind.faixas["sem data"], "n");

    h.barrasDeMapa("momento", h.contar(ativos, (r) => r.momento), 12, h.cat(0));
    h.roscaDeMapa("area", h.contar(D, (r) => r.area), "Processos por área do direito.");
    h.barrasDeMapa("materia", h.contar(D.filter((r) => r.materia), (r) => r.materia), 10, h.cat(2));
    h.barrasDeMapa("tribunal", h.contar(D.filter((r) => r.tribunal), (r) => r.tribunal), 14, h.cat(6));

    const base = h.css("--s1");
    h.marcarVazio("faixas", !ind.ativos);
    if (ind.ativos) h.grafico("faixas", { type: "bar", data: { labels: FAIXAS, datasets: [{ label: "Processos ativos", data: FAIXAS.map((f) => ind.faixas[f]),
      backgroundColor: FAIXAS.map((f, i) => (f === "sem data" ? h.cat("outros") : comAlfa(base, 0.35 + i * 0.16))), borderRadius: 4, maxBarThickness: 48 }] }, options: h.opBarra({}) });
    h.barrasDeMapa("atraso_momento", h.contar(ativos.filter((r) => dias(r) != null && dias(r) > 90), (r) => r.momento || "(sem momento)"), 10, h.cat(1));

    h.desenharContingencia(ctx);          // bloco de contingência: só aparece quando a planilha traz passivo, provisão ou pagamentos

    const serie = h.serieHistorica({ total: ctx.indTodos.total, ativos: ctx.indTodos.ativos, encerrados: ctx.indTodos.encerrados, valorCausa: null, valorEstimado: null, valorEconomizado: null });
    $("aviso-serie").innerHTML = serie.filter((p) => !p.atual).length < 1 ? '<div class="nota">A série histórica aparece quando houver ao menos um retrato anterior (aba "Histórico" da planilha ou retratos mensais). Hoje só existe o retrato desta planilha.</div>' : "";
    const linha = (rotulo, campo, i) => ({ label: rotulo, data: serie.map((p) => p[campo]), borderColor: h.cat(i), backgroundColor: h.cat(i), borderWidth: 2, pointRadius: 4, tension: 0 });
    h.marcarVazio("serie_qtd", false);
    h.grafico("serie_qtd", { type: "line", data: { labels: serie.map((p) => h.fmtData(p.data) + (p.atual ? " (esta planilha)" : "")), datasets: [linha("Total", "total", 0), linha("Ativos", "ativos", 1), linha("Encerrados", "encerrados", 2)] },
      options: { maintainAspectRatio: false, _inteiro: true, interaction: { mode: "index", intersect: false }, plugins: { legend: { display: true, position: "bottom" } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
  }

  const A = () => DASH.AJUDAS;
  const colunas = [
    { k: "numero", rotulo: "Nº do processo", valor: (r) => r.numero, html: (r) => r.numeros.map((n) => "<span>" + A().esc(n) + "</span>").join("") + (r.dvOk === false ? '<span class="etq prov">DV inválido</span>' : "") },
    { k: "cliente", rotulo: "Cliente", valor: (r) => r.cliente, html: (r) => A().esc(A().curto(r.cliente || "—", 32)) },
    { k: "momento", rotulo: "Momento atual", valor: (r) => r.momento, html: (r) => A().esc(r.momento || "—") },
    { k: "area", rotulo: "Área", valor: (r) => r.area, html: (r) => A().esc(r.area) },
    { k: "materia", rotulo: "Matéria", valor: (r) => r.materia, html: (r) => A().esc(r.materia || "—") },
    { k: "tribunal", rotulo: "Tribunal", valor: (r) => r.tribunal, html: (r) => A().esc(r.tribunal || "—") },
    { k: "ultimoAnd", rotulo: "Último andamento", valor: (r) => r.ultimoAnd || "", html: (r) => A().fmtData(r.ultimoAnd) },
    { k: "dias", rotulo: "Dias sem andamento", num: true, valor: (r) => (r.ativo && r.ultimoAnd ? A().diasEntre(r.ultimoAnd, DASH.estado.dataBase) : null),
      html: (r) => (r.ativo && r.ultimoAnd ? A().fmtNum(Math.max(A().diasEntre(r.ultimoAnd, DASH.estado.dataBase), 0)) : "—") },
    { k: "situacao", rotulo: "Situação", valor: (r) => (r.ativo ? "Ativo" : "Encerrado"), html: (r) => (r.ativo ? "Ativo" : "Encerrado") }
  ];
  DASH.registrarModelo({ montar, render, colunas, numeroTabela: "04" });
})();
