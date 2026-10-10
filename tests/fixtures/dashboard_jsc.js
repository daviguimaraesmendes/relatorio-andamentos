// Roda o núcleo do painel (nucleo.js + um modelo) FORA do navegador, com um DOM de mentira, no `jsc` do macOS
// (JavaScriptCore). Serve para conferir os números da contingência sem Playwright. Uso:
//   jsc dashboard_jsc.js -- <cfg.json> <modelo: contencioso|carteira> <pasta src/modelos/dashboard/>
// Imprime uma linha JSON com os indicadores de contingência e o estado do bloco.
var CFGTEXT = read(arguments[0]);
var MODELO = arguments[1];
var PASTA = arguments[2];
var elementos = {};
function el() {
  return { hidden: false, value: "", textContent: "", innerHTML: "", dataset: {}, style: {}, className: "", disabled: false,
    classList: { add: function () {}, remove: function () {}, toggle: function () {} },
    setAttribute: function () {}, getAttribute: function () { return null; }, querySelector: function () { return el(); },
    querySelectorAll: function () { return []; }, closest: function () { return el(); }, addEventListener: function () {},
    appendChild: function () {}, insertBefore: function () {}, focus: function () {}, remove: function () {} };
}
var document = {
  getElementById: function (id) { if (id === "cfg") return { textContent: CFGTEXT }; return elementos[id] || (elementos[id] = el()); },
  documentElement: { dataset: {}, style: {} }, body: {}, createElement: function () { return el(); }, querySelectorAll: function () { return []; }
};
var window = { addEventListener: function () {}, print: function () {} };
function getComputedStyle() { return { getPropertyValue: function () { return "#000"; }, fontFamily: "x" }; }
// os arquivos são scripts de navegador: "use strict" e "const DASH" ficariam presos dentro do eval
(0, eval)(read(PASTA + "nucleo.js").replace('"use strict";', "").replace("const DASH", "var DASH"));
(0, eval)(read(PASTA + MODELO + ".js").replace('"use strict";', ""));
DASH.iniciar();
var kpis = (elementos["kpis-contingencia"] || {}).innerHTML || "";
print(JSON.stringify({
  total: DASH.estado.ind.total, ativos: DASH.estado.ind.ativos, exposicao: DASH.estado.ind.exposicao,
  contingencia: DASH.estado.ind.contingencia,
  bloco_oculto: !!(elementos["sec-contingencia"] && elementos["sec-contingencia"].hidden),
  kpis: (kpis.match(/data-kpi="[a-z_]+"/g) || []).map(function (k) { return k.slice(10, -1); }),
  qualidade: DASH.estado.qualidade.filter(function (q) { return q.n > 0; }).map(function (q) { return q.id; })
}));
