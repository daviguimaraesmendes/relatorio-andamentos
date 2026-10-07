"use strict";
/* Núcleo comum dos dashboards (contencioso e carteira). Escrito para o relatorio-andamentos.
 *
 * O que faz: lê a planilha (grade de abas), reconhece colunas por similaridade de cabeçalho, monta um
 * registro por processo, aplica as regras de integridade dos indicadores, calcula os indicadores, cuida de
 * filtros, tabela, aba de qualidade, impressão e tema. Cada modelo (contencioso.js, carteira.js) só
 * desenha os blocos e registra-se com DASH.registrarModelo({...}).
 *
 * Duas fontes de dados, o MESMO código depois da leitura:
 *   modo "modelo":   o usuário solta o .xlsx; o SheetJS devolve a grade das abas (gradeDoWorkbook).
 *   modo "embutido": o gerador Python já gravou a grade em CFG.dados (mesmo formato) e a página abre pronta.
 * Formato da grade: [{nome: "Processos", linhas: [[célula, ...], ...]}]; célula = número | texto | booleano | null.
 * Datas chegam como número de série do Excel ou como texto (DD/MM/AAAA ou AAAA-MM-DD).
 *
 * Regras de integridade (lições dos relatórios de referência):
 *   - "economia" = valor da causa - valor estimado (ou a coluna "Valor economizado", se lançada), SÓ de processo
 *     encerrado e com valor lançado. Ficam FORA do indicador, e sinalizados: cliente no polo ativo, exclusão da
 *     lide, acordo pago por terceiro, acordo sem valor lançado e encerrado sem valor lançado.
 *   - um processo nunca é contado duas vezes: o mesmo número (com ou sem máscara), ou número que aparece como
 *     vinculado (agravo, apenso) de outra linha, vira UMA linha; o resto vai para a aba de qualidade.
 *   - dinheiro é somado em centavos inteiros (sem erro de ponto flutuante).
 *   - exposição (risco) só de processo ativo e com o cliente no polo passivo.
 * O estado fica em DASH.estado (usado pelos testes): {registros, unicos, filtrados, ind, qualidade, dataBase}.
 */
const DASH = (function () {
  const CFG = JSON.parse(document.getElementById("cfg").textContent);
  const $ = (id) => document.getElementById(id);
  const estado = { registros: [], unicos: [], filtrados: [], ind: null, qualidade: [], dataBase: null, historico: [], leitura: null };
  let modelo = null;
  const GRAFICOS = {};

  /* ---------------------------------------------------------------- utilidades */
  const norm = (s) => (s == null ? "" : String(s)).normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[º°ª]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtNum = (n) => (n == null || isNaN(n) ? "—" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: 0 }));
  const fmtDec = (n, d) => (n == null || isNaN(n) ? "—" : Number(n).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const fmtBRL = (n) => (n == null || isNaN(n) ? "—" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }).format(n));
  const fmtBRLc = (n) => {
    if (n == null || isNaN(n)) return "—";
    const a = Math.abs(n);
    if (a >= 1e6) return "R$ " + (n / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + " mi";
    if (a >= 1e3) return "R$ " + (n / 1e3).toLocaleString("pt-BR", { maximumFractionDigits: 0 }) + " mil";
    return fmtBRL(n);
  };
  const fmtPct = (parte, todo) => (todo ? Math.round((parte / todo) * 100) + "%" : "—");
  const fmtData = (iso) => (iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(0, 4) : "—");
  const centavos = (v) => Math.round(v * 100);
  /** Soma em reais, feita em centavos inteiros. */
  const somar = (lista, f) => lista.reduce((s, x) => { const v = f(x); return s + (v == null || isNaN(v) ? 0 : centavos(v)); }, 0) / 100;
  const contar = (lista, f) => { const m = {}; lista.forEach((x) => { const k = f(x); if (k == null || k === "") return; m[k] = (m[k] || 0) + 1; }); return m; };
  const topo = (obj, n) => Object.entries(obj).sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), "pt-BR")).slice(0, n || 999);
  const unicos = (arr) => [...new Set(arr.filter((x) => x != null && x !== ""))].sort((a, b) => String(a).localeCompare(String(b), "pt-BR"));
  const hojeISO = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
  const diasEntre = (a, b) => Math.round((Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10)) - Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))) / 864e5);
  function addMeses(iso, n) {
    let y = +iso.slice(0, 4), m = +iso.slice(5, 7) - 1 + n; const d = +iso.slice(8, 10);
    y += Math.floor(m / 12); m = ((m % 12) + 12) % 12;
    const ultimo = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    return y + "-" + String(m + 1).padStart(2, "0") + "-" + String(Math.min(d, ultimo)).padStart(2, "0");
  }
  const mediana = (v) => { if (!v.length) return null; const s = v.slice().sort((a, b) => a - b); const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };

  /* ---------------------------------------------------------------- conversões de valor */
  function parseDinheiro(v) {
    if (v == null || v === "" || typeof v === "boolean") return null;
    if (typeof v === "number") return isFinite(v) ? v : null;
    let s = String(v).replace(/r\$/i, "").replace(/[\s ]/g, "").replace(/[^0-9.,-]/g, "");
    if (!/\d/.test(s)) return null;
    if (s.includes(",") && s.includes(".")) s = s.lastIndexOf(",") > s.lastIndexOf(".") ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
    else if (s.includes(",")) s = s.replace(",", ".");
    else if ((s.match(/\./g) || []).length > 1 || /\.\d{3}$/.test(s)) s = s.replace(/\./g, "");
    const n = parseFloat(s);
    return isFinite(n) ? n : null;
  }
  function serialParaISO(n) {
    if (!(n > 20000 && n < 80000)) return null;
    const d = new Date(Date.UTC(1899, 11, 30) + Math.floor(n) * 864e5);
    return d.getUTCFullYear() + "-" + String(d.getUTCMonth() + 1).padStart(2, "0") + "-" + String(d.getUTCDate()).padStart(2, "0");
  }
  function validaISO(y, m, d) {
    const t = new Date(Date.UTC(y, m - 1, d));
    return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d && y > 1900 && y < 2200;
  }
  function paraISO(v) {
    if (v == null || v === "" || typeof v === "boolean") return null;
    if (typeof v === "number") return serialParaISO(v);
    const s = String(v).trim();
    let m = s.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (m) return validaISO(+m[3], +m[2], +m[1]) ? m[3] + "-" + m[2].padStart(2, "0") + "-" + m[1].padStart(2, "0") : null;
    m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return validaISO(+m[1], +m[2], +m[3]) ? m[1] + "-" + m[2] + "-" + m[3] : null;
    return null;
  }
  /** Maior data DD/MM/AAAA de um texto de andamentos (ISO) ou null. */
  function ultimaDataDoTexto(t) {
    if (!t) return null;
    let melhor = null;
    (String(t).match(/\d{1,2}\/\d{1,2}\/\d{4}/g) || []).forEach((x) => { const i = paraISO(x); if (i && (!melhor || i > melhor)) melhor = i; });
    return melhor;
  }
  const CNJ_RE = /(?<!\d)(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})(?!\d)/g;
  const mascaraCNJ = (m) => m[1] + "-" + m[2] + "." + m[3] + "." + m[4] + "." + m[5] + "." + m[6];
  function dvConfere(m) {
    let r = 0; const digitos = m[1] + m[3] + m[4] + m[5] + m[6] + "00";
    for (const c of digitos) r = (r * 10 + (c.charCodeAt(0) - 48)) % 97;
    return +m[2] === 98 - r;
  }
  const UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SE", "SP", "TO"];
  function tribunalDoNumero(m) {
    const j = m[4], tr = +m[5];
    if (j === "8" && tr >= 1 && tr <= 27) return "TJ" + UFS[tr - 1];
    return { "4": "TRF" + tr, "5": "TRT" + tr, "1": "STF", "3": "STJ", "6": "TRE" + tr, "9": "TJM" + tr }[j] || "";
  }
  function limparTribunal(v) {
    if (v == null || v === "") return "";
    let s = String(v).trim().toUpperCase().replace(/\s+/g, " ");
    let m = s.match(/^(TRT|TRF|TRE|TJM)[\s-]*0*(\d+)/);
    if (m) return m[1] + m[2];
    m = s.match(/^TJ[\s-]*([A-Z]{2})$/);
    return m ? "TJ" + m[1] : s;
  }
  function normProb(v) {
    const n = norm(v);
    if (n.startsWith("prov")) return "Provável";
    if (n.startsWith("poss")) return "Possível";
    if (n.startsWith("rem")) return "Remota";
    return null;
  }
  const RESULTADOS = {
    procedente: "Procedente", parcial: "Parcialmente procedente", improcedente: "Improcedente", acordo: "Acordo",
    extinto: "Extinto sem resolução de mérito", arquivado: "Arquivado / desistência", incompetencia: "Incompetência declarada",
    exclusao: "Exclusão da lide", outro: "Outros"
  };
  const TERMINAIS = ["acordo", "extinto", "arquivado", "incompetencia", "exclusao"];
  function classeResultado(v) {
    const n = norm(v);
    if (!n || /nao julgad|sem resultado|aguardand/.test(n)) return null;
    if (/exclus\w* da lide|ilegitimidade/.test(n)) return "exclusao";
    if (n.includes("parcial")) return "parcial";
    if (n.includes("improcedent") || n.includes("improcedenc")) return "improcedente";
    if (n.includes("procedent") || n.includes("procedenc") || n.includes("condenac")) return "procedente";
    if (n.includes("acordo") || n.includes("transac")) return "acordo";
    if (n.includes("extint")) return "extinto";
    if (n.includes("arquiv") || n.includes("desist")) return "arquivado";
    if (n.includes("incompet")) return "incompetencia";
    return "outro";
  }
  function normArea(v) {
    const n = norm(v);
    if (!n || /^[\d\W]+$/.test(n)) return null;
    const tabela = [["trabalh", "Trabalhista"], ["consum", "Consumidor"], ["civ", "Cível"], ["tribut", "Tributário"], ["fiscal", "Tributário"],
      ["administ", "Administrativo"], ["ambient", "Ambiental"], ["empres", "Empresarial"], ["imobili", "Imobiliário"], ["previd", "Previdenciário"]];
    for (const [k, r] of tabela) if (n.includes(k)) return r;
    return String(v).trim();
  }

  /* ---------------------------------------------------------------- mapeamento de colunas */
  // cada campo: lista de rótulos normalizados (sem acento, sem º). Passo 1: igualdade; passo 2: começa com (rótulos >= 8 letras).
  const ALIASES = {
    numero: ["numero do processo", "n do processo", "no do processo", "numero", "processo", "autos"],
    autores: ["autor(es)", "autores", "autor", "reclamante"],
    reus: ["reu(s)", "reus", "reu", "reclamada", "reclamado"],
    vara: ["vara / juizo", "vara/juizo", "vara", "juizo"],
    municipio: ["municipio", "comarca"], uf: ["uf", "estado"], tribunal: ["tribunal"],
    dataAjuiz: ["data do ajuizamento", "data ajuizamento", "ajuizamento"],
    area: ["area do direito", "area"], materia: ["materia principal", "materia"], objeto: ["objeto"],
    valorCausa: ["valor da causa"],
    momento: ["momento atual do processo", "momento atual", "momento"],
    situacao: ["situacao"], fase: ["fase processual", "fase"],
    ultimoAnd: ["data do ultimo andamento", "ultimo andamento"],
    ativo: ["ativo"],
    arbitrado: ["valor arbitrado em juizo", "valor arbitrado"],
    prob: ["probabilidade (do resultado)", "probabilidade"],
    valorEstimado: ["valor estimado"], valorExec: ["valor da execucao"], valorAcordo: ["valor do acordo", "valor acordo"],
    custas: ["custas processuais"], depositos: ["depositos recursais"], garantias: ["garantias processuais"],
    resultado: ["resultado"], economizado: ["valor economizado"],
    transito: ["data do transito em julgado", "transito em julgado"],
    resolDias: ["taxa de resolucao (em dias)", "taxa de resolucao (dias)", "taxa de resolucao"],
    recurso: ["houve recurso da empresa?", "houve recurso"],
    terceirizado: ["reclamante terceirizado?", "reclamante terceirizado", "terceirizado"],
    tipo: ["tipo de processo", "natureza do processo", "natureza", "tipo"],
    cliente: ["cliente"], responsavel: ["responsavel"], polo: ["polo do cliente", "polo"], parteContraria: ["parte contraria"],
    observacoes: ["observacoes", "observacao"], andamentos: ["andamentos"],
    vinculados: ["processos vinculados", "vinculados", "outros numeros"],
    _ignorada: ["outra(s) parte(s)", "outras partes", "contato", "apelido do processo", "apelido", "classe", "assunto", "data de citacao", "percentual de exito"]
  };
  function montarIndice(cabecalho) {
    const idx = {}, usada = new Set();
    const hn = cabecalho.map(norm);
    for (const passo of [1, 2]) {
      for (const k in ALIASES) {
        if (idx[k] != null && k !== "_ignorada") continue;
        hn.forEach((h, i) => {
          if (!h || usada.has(i) || (idx[k] != null && k !== "_ignorada")) return;
          const bate = ALIASES[k].some((a) => (passo === 1 ? h === a : a.length >= 8 && h.startsWith(a)));
          if (bate) { if (k === "_ignorada") { usada.add(i); (idx._ign = idx._ign || []).push(i); } else { idx[k] = i; usada.add(i); } }
        });
      }
    }
    idx._naoReconhecidas = cabecalho.map((c, i) => (c != null && String(c).trim() && !usada.has(i) ? String(c).trim() : null)).filter(Boolean);
    return idx;
  }
  function acharCabecalho(linhas) {
    for (let i = 0; i < Math.min(linhas.length, 20); i++) {
      const lin = linhas[i] || [];
      if (!lin.some((c) => c != null && String(c).trim())) continue;
      const idx = montarIndice(lin);
      const reconhecidas = Object.keys(idx).filter((k) => k[0] !== "_").length;
      if (idx.numero != null && reconhecidas >= 3) return { i, idx };
    }
    return null;
  }

  /* ---------------------------------------------------------------- vocabulário de momentos (vem do gerador) */
  const MOMENTOS = {};
  Object.keys(CFG.momentos || {}).forEach((k) => { MOMENTOS[norm(k)] = CFG.momentos[k]; });
  function classeMomento(texto) {
    const n = norm(String(texto || "").replace(/\(.*?\)/g, ""));
    if (!n) return { ativo: null, cat: null };
    if (MOMENTOS[n]) return { ativo: !!MOMENTOS[n][1], cat: MOMENTOS[n][0] };
    if (/arquiv|transito em julgado|acordo homologado|extint|baixa definitiva/.test(n)) return { ativo: false, cat: "encerrado" };
    if (/aguard|conclus|cumprimento|suspens|sobrest/.test(n)) return { ativo: true, cat: null };
    return { ativo: null, cat: null };
  }
  const FASE_DA_CATEGORIA = { conhecimento: "Conhecimento", recurso: "Recurso", "execução": "Execução", "execucao": "Execução", suspenso: "Suspenso", encerrado: "Encerrado" };

  /* ---------------------------------------------------------------- empresas do grupo e parâmetros */
  let GRUPO = (CFG.empresas_do_grupo || []).slice();
  let PARAMETROS = Object.assign({}, CFG.parametros || {});
  function empresaDoGrupo(nome) {
    if (!nome) return null;
    const n = norm(nome); let achou = null;
    GRUPO.forEach((g) => { const gn = norm(g); if (gn && n.includes(gn) && (!achou || gn.length > norm(achou).length)) achou = g; });
    return achou;
  }
  function lerParametros(linhas) {
    const out = { grupo: [], dataRef: null, headcount: null };
    const rotulo = (c) => norm(c);
    for (let i = 0; i < linhas.length; i++) {
      const lin = linhas[i] || [];
      for (let j = 0; j < lin.length; j++) {
        const r = rotulo(lin[j]); if (!r) continue;
        const direita = lin.slice(j + 1).filter((c) => c != null && String(c).trim() !== "");
        const abaixo = []; for (let k = i + 1; k < linhas.length; k++) { const c = (linhas[k] || [])[j]; if (c == null || String(c).trim() === "") break; abaixo.push(c); }
        if (/empresas? do grupo|empresas? do grupo empresarial/.test(r)) {
          (direita.length ? direita : abaixo).forEach((c) => String(c).split(/[\r\n;]+/).forEach((p) => { const t = p.trim(); if (t) out.grupo.push(t); }));
        } else if (/data (de )?referencia|data-base|data base/.test(r)) {
          const d = paraISO(direita[0]) || paraISO(abaixo[0]); if (d) out.dataRef = d;
        } else if (/headcount|numero de empregados|n de empregados|colaboradores|empregados/.test(r)) {
          const n = parseDinheiro(direita[0] != null ? direita[0] : abaixo[0]); if (n != null && n > 0) out.headcount = n;
        }
      }
    }
    return out;
  }
  function lerHistoricoAba(linhas) {
    const ach = (() => {
      for (let i = 0; i < Math.min(linhas.length, 10); i++) {
        const hn = (linhas[i] || []).map(norm);
        const col = (alts) => hn.findIndex((h) => h && alts.some((a) => h === a || h.startsWith(a)));
        const c = { data: col(["data-base", "data base", "data de referencia", "data", "competencia", "mes"]),
          total: col(["total de processos", "processos", "total"]), ativos: col(["processos ativos", "ativos"]),
          encerrados: col(["processos encerrados", "encerrados"]), valorCausa: col(["valor da causa", "valor causa"]),
          valorEstimado: col(["valor estimado"]), valorEconomizado: col(["valor economizado", "economia"]) };
        if (c.data >= 0 && Object.keys(c).filter((k) => k !== "data" && c[k] >= 0).length >= 1) return { i, c };
      }
      return null;
    })();
    if (!ach) return [];
    const pontos = [];
    for (let i = ach.i + 1; i < linhas.length; i++) {
      const lin = linhas[i] || []; const d = paraISO(lin[ach.c.data]); if (!d) continue;
      const v = (k) => (ach.c[k] >= 0 ? parseDinheiro(lin[ach.c[k]]) : null);
      pontos.push({ data: d, total: v("total"), ativos: v("ativos"), encerrados: v("encerrados"), valorCausa: v("valorCausa"), valorEstimado: v("valorEstimado"), valorEconomizado: v("valorEconomizado") });
    }
    return pontos;
  }

  /* ---------------------------------------------------------------- leitura da planilha */
  function linhaEhDeProcesso(numero, lin) {
    const s = String(numero).trim();
    if ((lin || []).some((c) => { const n = norm(c); return n.includes("nao alterar") || n.startsWith("total") || n.startsWith("subtotal"); })) return false;
    if (/^\d+([.,]\d+)?$/.test(s) && s.replace(/\D/g, "").length < 7) return false; // contador de rodapé
    return /\d/.test(s);
  }
  const txt = (v) => (v == null ? "" : String(v).trim());
  function lerPlanilha(grade) {
    const registros = [], descartadas = [], abas = [], colunasNaoReconhecidas = [], ausentes = new Set();
    let historicoAba = [], params = null;
    grade.forEach((aba) => {
      const nn = norm(aba.nome), linhas = aba.linhas || [];
      if (nn.startsWith("parametro")) { params = lerParametros(linhas); abas.push({ nome: aba.nome, tipo: "parametros", linhas: 0 }); return; }
      if (nn.startsWith("hist")) { historicoAba = historicoAba.concat(lerHistoricoAba(linhas)); abas.push({ nome: aba.nome, tipo: "historico", linhas: 0 }); return; }
      const cab = acharCabecalho(linhas);
      if (!cab) { abas.push({ nome: aba.nome, tipo: "ignorada", linhas: 0 }); return; }
      const idx = cab.idx; let lidas = 0;
      colunasNaoReconhecidas.push(...idx._naoReconhecidas.map((c) => ({ aba: aba.nome, coluna: c })));
      ["valorCausa", "valorEstimado", "resultado", "prob", "momento"].forEach((k) => { if (idx[k] == null) ausentes.add(k); });
      for (let i = cab.i + 1; i < linhas.length; i++) {
        const lin = linhas[i]; if (!lin) continue;
        const get = (k) => (idx[k] != null ? lin[idx[k]] : null);
        const bruto = get("numero");
        if (bruto == null || String(bruto).trim() === "") continue;
        if (!linhaEhDeProcesso(bruto, lin)) { descartadas.push({ aba: aba.nome, linha: i + 1, texto: String(bruto).slice(0, 40) }); continue; }
        registros.push(montarRegistro(get, idx, aba.nome, i + 1, lin));
        lidas++;
      }
      abas.push({ nome: aba.nome, tipo: "processos", linhas: lidas });
    });
    return { registros, descartadas, abas, colunasNaoReconhecidas, ausentes: [...ausentes], historicoAba, params };
  }

  function montarRegistro(get, idx, abaNome, linhaNum, lin) {
    const bruto = String(get("numero")).trim();
    const ms = [...bruto.matchAll(CNJ_RE)];
    const numeros = ms.map(mascaraCNJ);
    const vincCol = [...txt(get("vinculados")).matchAll(CNJ_RE)].map(mascaraCNJ);
    const principal = numeros[0] || bruto;
    const vinculados = [...new Set([...numeros.slice(1), ...vincCol])].filter((n) => n !== principal);
    const rec = {
      aba: abaNome, linha: linhaNum, numero: principal, numeros: [principal, ...vinculados], vinculados,
      chave: ms[0] ? mascaraCNJ(ms[0]).replace(/\D/g, "") : "t:" + norm(bruto),
      cnj: !!ms[0], dvOk: ms[0] ? dvConfere(ms[0]) : null,
      autores: txt(get("autores")), reus: txt(get("reus")), vara: txt(get("vara")), municipio: txt(get("municipio")), uf: txt(get("uf")),
      dataAjuiz: paraISO(get("dataAjuiz")), ultimoAnd: paraISO(get("ultimoAnd")),
      materia: txt(get("materia")), objeto: txt(get("objeto")), momento: txt(get("momento")), situacao: txt(get("situacao")),
      resultadoTxt: txt(get("resultado")), observacoes: txt(get("observacoes")),
      cliente: txt(get("cliente")) || CFG.cliente || "", responsavel: txt(get("responsavel")),
      valorCausa: parseDinheiro(get("valorCausa")), arbitrado: parseDinheiro(get("arbitrado")), valorEstimado: parseDinheiro(get("valorEstimado")),
      valorExec: parseDinheiro(get("valorExec")), valorAcordo: parseDinheiro(get("valorAcordo")), economizadoCol: parseDinheiro(get("economizado")),
      transito: paraISO(get("transito")), resolDiasCol: parseDinheiro(get("resolDias")),
      prob: idx.prob != null ? normProb(get("prob")) : null,
      terceirizado: (() => { const n = norm(get("terceirizado")); return n.startsWith("sim") ? "Terceirizado" : n.startsWith("nao") ? "Próprio" : null; })(),
      temColunaProb: idx.prob != null, temColunaEstimado: idx.valorEstimado != null
    };
    rec.tribunal = limparTribunal(get("tribunal")) || (ms[0] ? tribunalDoNumero(ms[0]) : "");
    rec.area = normArea(get("area")) || (norm(abaNome).includes("trabalh") ? "Trabalhista" : "Outros");
    if (!rec.ultimoAnd) rec.ultimoAnd = ultimaDataDoTexto(get("andamentos"));
    rec.classeRes = classeResultado(rec.resultadoTxt);
    rec.resultado = rec.classeRes ? (rec.classeRes === "outro" ? rec.resultadoTxt : RESULTADOS[rec.classeRes]) : "";
    // polo do cliente: coluna, ou (sem coluna) o grupo empresarial como autor
    const poloN = norm(get("polo"));
    rec.polo = /ativ|autor|reclamante/.test(poloN) ? "ativo" : /passiv|reu|reclamad/.test(poloN) ? "passivo" : null;
    if (!rec.polo && GRUPO.length && empresaDoGrupo(rec.autores) && !empresaDoGrupo(rec.reus)) rec.polo = "ativo";
    // natureza: coluna tipo; senão aba administrativa; senão o padrão CNJ (só judicial tem número CNJ)
    const tn = norm(get("tipo"));
    rec.natureza = tn.startsWith("admin") ? "Administrativo" : tn.startsWith("judic") ? "Judicial" : norm(abaNome).includes("administr") ? "Administrativo" : rec.cnj ? "Judicial" : "Administrativo";
    // ativo x encerrado (ordem de confiança: coluna Ativo, momento atual, situação, aba, resultado terminal)
    const cm = classeMomento(rec.momento), ac = norm(get("ativo"));
    const ativoCol = ac.startsWith("sim") ? true : ac.startsWith("nao") ? false : null;
    const sn = norm(rec.situacao);
    const ativoSit = /encerrad|arquivad|baixad|finalizad/.test(sn) ? false : /ativo|andamento|tramit|suspens|sobrest/.test(sn) ? true : null;
    if (ativoCol != null) { rec.ativo = ativoCol; rec.conflitoAtivo = cm.ativo != null && cm.ativo !== ativoCol; }
    else if (cm.ativo != null) rec.ativo = cm.ativo;
    else if (ativoSit != null) rec.ativo = ativoSit;
    else if (norm(abaNome).includes("arquivad")) rec.ativo = false;
    else rec.ativo = !TERMINAIS.includes(rec.classeRes);
    rec.fase = txt(get("fase")) || FASE_DA_CATEGORIA[cm.cat] || "";
    rec.dataEnc = rec.ativo ? null : (rec.transito || rec.ultimoAnd);
    rec.resolDias = rec.resolDiasCol != null && rec.resolDiasCol > 0 ? rec.resolDiasCol
      : (!rec.ativo && rec.dataEnc && rec.dataAjuiz ? Math.max(diasEntre(rec.dataAjuiz, rec.dataEnc), 0) : null);
    rec.valorExposicao = rec.valorEstimado != null ? rec.valorEstimado : rec.arbitrado != null ? rec.arbitrado : rec.valorExec != null ? rec.valorExec : rec.valorCausa;
    rec.econ = calcularEconomia(rec);
    return rec;
  }

  /** Economia do processo: {valor, fora}. `fora` = motivo de ficar fora do indicador (ou null). Só encerrado. */
  const MOTIVOS = {
    polo_ativo: "cliente no polo ativo (crédito, não risco)", exclusao_lide: "exclusão da lide",
    acordo_terceiro: "acordo pago por terceiro", acordo_sem_valor: "acordo sem valor lançado", sem_valor: "encerrado sem valor lançado"
  };
  function calcularEconomia(r) {
    if (r.ativo) return { valor: null, fora: null };
    const blob = norm([r.resultadoTxt, r.observacoes, r.objeto, r.situacao, r.momento].join(" "));
    const acordo = r.classeRes === "acordo" || /acordo/.test(norm(r.momento));
    const estimado = r.valorEstimado != null ? r.valorEstimado : (acordo ? r.valorAcordo : null);
    let fora = null;
    if (r.polo === "ativo") fora = "polo_ativo";
    else if (r.classeRes === "exclusao" || /exclus\w* d[ao] lide|exclu[ií]d\w* d[ao] (lide|polo)|ilegitimidade passiva/.test(blob)) fora = "exclusao_lide";
    else if (acordo && /acordo[^.;]{0,60}terceir|terceir[^.;]{0,60}(pag|arc|quit)|pago por terceiro|pagamento por terceiro/.test(blob)) fora = "acordo_terceiro";
    else if (acordo && !(r.valorAcordo > 0) && !(estimado > 0)) fora = "acordo_sem_valor";
    let valor = null;
    if (!fora) {
      if (r.economizadoCol != null) valor = r.economizadoCol;
      else if (r.valorCausa != null && estimado != null) valor = Math.round((centavos(r.valorCausa) - centavos(estimado))) / 100;
      else fora = "sem_valor";
    }
    return { valor, fora };
  }

  /* ---------------------------------------------------------------- um processo, uma linha */
  function deduplicar(registros) {
    // união de números: principal + vinculados de cada linha; cada componente conexo vira UM processo
    const pai = new Map();
    const raiz = (x) => { while (pai.get(x) !== x) { pai.set(x, pai.get(pai.get(x))); x = pai.get(x); } return x; };
    const unir = (a, b) => { if (!pai.has(a)) pai.set(a, a); if (!pai.has(b)) pai.set(b, b); pai.set(raiz(a), raiz(b)); };
    registros.forEach((r) => { if (!pai.has(r.chave)) pai.set(r.chave, r.chave); r.vinculados.forEach((v) => unir(r.chave, v.replace(/\D/g, ""))); });
    const grupos = new Map();
    registros.forEach((r) => { const k = raiz(r.chave); if (!grupos.has(k)) grupos.set(k, []); grupos.get(k).push(r); });
    const mantidos = new Set(), removidos = [];
    grupos.forEach((lista) => {
      let escolhido = lista[0];
      lista.forEach((r) => { if (r.vinculados.length > escolhido.vinculados.length) escolhido = r; });
      mantidos.add(escolhido);
      lista.forEach((r) => { if (r !== escolhido) removidos.push({ numero: r.numero, aba: r.aba, linha: r.linha, mantido: escolhido.numero,
        tipo: r.chave === escolhido.chave ? "duplicado" : "vinculado" }); });
    });
    return { unicos: registros.filter((r) => mantidos.has(r)), removidos };
  }

  /* ---------------------------------------------------------------- filtros */
  const FILTROS = { area: (r) => r.area, natureza: (r) => r.natureza, tribunal: (r) => r.tribunal, prob: (r) => r.prob, cliente: (r) => r.cliente };
  function preencherFiltros() {
    const base = estado.unicos;
    const opcoes = { area: unicos(base.map((r) => r.area)), natureza: unicos(base.map((r) => r.natureza)), tribunal: unicos(base.map((r) => r.tribunal)),
      prob: ["Provável", "Possível", "Remota"].filter((p) => base.some((r) => r.prob === p)), cliente: unicos(base.map((r) => r.cliente)) };
    const rotulos = { area: "Todas", natureza: "Todas", tribunal: "Todos", prob: "Todas", cliente: "Todos" };
    Object.keys(opcoes).forEach((k) => {
      const sel = $("f-" + k), caixa = sel.closest(".campo");
      sel.innerHTML = '<option value="">' + rotulos[k] + "</option>" + opcoes[k].map((v) => '<option value="' + esc(v) + '">' + esc(v) + "</option>").join("");
      caixa.hidden = opcoes[k].length < 2; // filtro sem escolha não aparece
      sel.onchange = atualizar;
    });
    $("f-situacao").onchange = atualizar;
    let t; $("f-busca").oninput = () => { clearTimeout(t); t = setTimeout(atualizar, 150); };
    $("f-data").onchange = () => { if ($("f-data").value) { estado.dataBase = $("f-data").value; atualizar(); } };
    $("b-limpar").onclick = () => { ["area", "natureza", "tribunal", "prob", "cliente", "situacao"].forEach((k) => ($("f-" + k).value = "")); $("f-busca").value = ""; atualizar(); };
  }
  function filtrar() {
    const v = (k) => $("f-" + k).value, q = norm($("f-busca").value), sit = v("situacao");
    return estado.unicos.filter((r) => {
      for (const k in FILTROS) { const sel = v(k); if (sel && FILTROS[k](r) !== sel) return false; }
      if (sit === "ativo" && !r.ativo) return false;
      if (sit === "encerrado" && r.ativo) return false;
      if (q && !norm([r.numeros.join(" "), r.autores, r.reus, r.materia, r.objeto, r.tribunal, r.cliente, r.municipio, r.momento].join(" ")).includes(q)) return false;
      return true;
    });
  }

  /* ---------------------------------------------------------------- indicadores */
  function indicadores(D, dataBase) {
    const ativos = D.filter((r) => r.ativo), encerr = D.filter((r) => !r.ativo);
    const passivos = ativos.filter((r) => r.polo !== "ativo");
    const comValorExp = passivos.filter((r) => (r.valorExposicao || 0) > 0);
    const expProb = { "Provável": 0, "Possível": 0, "Remota": 0, semProb: 0 };
    comValorExp.forEach((r) => { const k = r.prob || "semProb"; expProb[k] = Math.round((expProb[k] + r.valorExposicao) * 100) / 100; });
    const comRes = D.filter((r) => r.classeRes);
    const classes = {}; Object.keys(RESULTADOS).forEach((k) => (classes[k] = 0));
    comRes.forEach((r) => classes[r.classeRes]++);
    const fora = { polo_ativo: 0, exclusao_lide: 0, acordo_terceiro: 0, acordo_sem_valor: 0, sem_valor: 0 };
    const elegiveis = [];
    encerr.forEach((r) => { if (r.econ.fora) fora[r.econ.fora]++; else if (r.econ.valor != null) elegiveis.push(r); });
    const economiaValor = somar(elegiveis, (r) => r.econ.valor), causaEleg = somar(elegiveis, (r) => r.valorCausa);
    const corte = addMeses(dataBase, -12);
    const entradas12 = D.filter((r) => r.dataAjuiz && r.dataAjuiz >= corte && r.dataAjuiz <= dataBase).length;
    const baixas12 = encerr.filter((r) => r.dataEnc && r.dataEnc >= corte && r.dataEnc <= dataBase).length;
    const resolv = encerr.map((r) => r.resolDias).filter((x) => x != null);
    const dias = ativos.filter((r) => r.ultimoAnd).map((r) => Math.max(diasEntre(r.ultimoAnd, dataBase), 0));
    const faixas = { "até 15 dias": 0, "16 a 30 dias": 0, "31 a 60 dias": 0, "61 a 90 dias": 0, "mais de 90 dias": 0, "sem data": 0 };
    ativos.forEach((r) => {
      if (!r.ultimoAnd) { faixas["sem data"]++; return; }
      const d = Math.max(diasEntre(r.ultimoAnd, dataBase), 0);
      faixas[d <= 15 ? "até 15 dias" : d <= 30 ? "16 a 30 dias" : d <= 60 ? "31 a 60 dias" : d <= 90 ? "61 a 90 dias" : "mais de 90 dias"]++;
    });
    return {
      total: D.length, ativos: ativos.length, encerrados: encerr.length,
      judiciais: D.filter((r) => r.natureza === "Judicial").length, administrativos: D.filter((r) => r.natureza === "Administrativo").length,
      valorCausaAtivos: somar(ativos, (r) => r.valorCausa), valorCausaTotal: somar(D, (r) => r.valorCausa),
      exposicao: somar(comValorExp, (r) => r.valorExposicao), exposicaoProb: expProb, poloAtivoAtivos: ativos.length - passivos.length,
      comResultado: comRes.length, resultadoClasses: classes,
      economia: { valor: economiaValor, elegiveis: elegiveis.length, causaElegiveis: causaEleg, pct: causaEleg ? economiaValor / causaEleg : null, fora },
      entradas12, baixas12, saldo12: entradas12 - baixas12,
      tempoMedioDias: resolv.length ? Math.round(resolv.reduce((a, b) => a + b, 0) / resolv.length) : null, encerradosComTempo: resolv.length,
      semAndamento30: dias.filter((d) => d > 30).length, semAndamento60: dias.filter((d) => d > 60).length, semAndamento90: dias.filter((d) => d > 90).length,
      medianaDias: mediana(dias), ativosComData: dias.length, faixas,
      processosPor100: PARAMETROS.headcount ? (ativos.length / PARAMETROS.headcount) * 100 : null
    };
  }

  /* ---------------------------------------------------------------- qualidade dos dados */
  function montarQualidade(leitura, removidos) {
    const U = estado.unicos, q = [];
    const add = (id, nivel, titulo, itens, texto) => { if (itens.length || nivel === "info") q.push({ id, nivel, titulo, n: itens.length, itens, texto: texto || "" }); };
    const lista = (arr, f) => arr.map(f);
    const ref = (r) => r.numero + " (" + r.aba + ", linha " + r.linha + ")";
    add("lido", "info", "Processos reconhecidos", leitura.abas.filter((a) => a.tipo === "processos").map((a) => a.nome + ": " + a.linhas + " linha(s)"),
      leitura.registros.length + " linhas de processo lidas; " + U.length + " processos distintos no painel.");
    add("duplicados", "atencao", "Mesmo número em mais de uma linha", lista(removidos.filter((x) => x.tipo === "duplicado"), (x) => x.numero + " (" + x.aba + ", linha " + x.linha + ")"),
      "Só uma linha por processo entra nas contagens; as demais foram descartadas.");
    add("vinculados", "atencao", "Linhas já contadas como vinculadas de outro processo", lista(removidos.filter((x) => x.tipo === "vinculado"), (x) => x.numero + " vinculado a " + x.mantido),
      "Agravo, apenso ou recurso listado junto do principal conta como uma linha só.");
    add("dv", "erro", "Número CNJ com dígito verificador inválido", lista(U.filter((r) => r.cnj && r.dvOk === false), ref), "Provável erro de digitação; confira com o tribunal.");
    add("sem_causa", "atencao", "Sem valor da causa interpretável", lista(U.filter((r) => r.valorCausa == null), ref), "Não entram nas somas de valor.");
    if (U.some((r) => r.temColunaProb)) add("ativo_sem_prob", "atencao", "Processo ativo sem probabilidade", lista(U.filter((r) => r.ativo && !r.prob && r.polo !== "ativo"), ref), "A exposição aparece como \"sem probabilidade\".");
    add("enc_sem_res", "atencao", "Encerrado sem resultado lançado", lista(U.filter((r) => !r.ativo && !r.classeRes), ref), "Fora das taxas de desfecho.");
    add("conflito", "atencao", "Coluna \"Ativo\" em conflito com o momento atual", lista(U.filter((r) => r.conflitoAtivo), ref), "Vale a coluna \"Ativo\"; revise a linha.");
    const enc = U.filter((r) => !r.ativo);
    Object.keys(MOTIVOS).forEach((m) => {
      const itens = enc.filter((r) => r.econ.fora === m);
      add("fora_" + m, m === "polo_ativo" ? "info" : "atencao", "Fora do indicador de economia: " + MOTIVOS[m], lista(itens, ref),
        "Aparece sinalizado na tabela e não entra na soma da economia.");
    });
    if (leitura.descartadas.length) add("descartadas", "info", "Linhas ignoradas (totais, rodapés e marcadores)", lista(leitura.descartadas, (d) => d.aba + ", linha " + d.linha + ": " + d.texto), "");
    if (leitura.colunasNaoReconhecidas.length) add("colunas", "info", "Colunas não reconhecidas (não usadas nos indicadores)", lista(leitura.colunasNaoReconhecidas, (c) => c.aba + ": " + c.coluna), "");
    const nomes = { valorCausa: "Valor da causa", valorEstimado: "Valor estimado", resultado: "Resultado", prob: "Probabilidade", momento: "Momento atual" };
    add("ausentes", "atencao", "Colunas esperadas que não existem na planilha", lista(leitura.ausentes, (k) => nomes[k] || k), "Os indicadores que dependem delas ficam vazios.");
    return q;
  }
  function desenharQualidade() {
    const q = estado.qualidade, pendentes = q.filter((x) => x.nivel !== "info" && x.n > 0).reduce((s, x) => s + x.n, 0);
    $("selo-qualidade").textContent = pendentes;
    $("q-intro").innerHTML = pendentes ? "<b>" + fmtNum(pendentes) + " ponto(s) de atenção</b> na planilha. Eles afetam a precisão das somas; vale padronizar na planilha de origem. Estes avisos olham o arquivo inteiro, independentemente dos filtros."
      : "<b>Nenhum ponto de atenção</b> encontrado na planilha.";
    $("q-lista").innerHTML = q.map((x) => {
      const mostra = x.itens.slice(0, 40).map((i) => "<li>" + esc(i) + "</li>").join("");
      const resto = x.itens.length > 40 ? "<li>… e mais " + (x.itens.length - 40) + "</li>" : "";
      return '<div class="q-item ' + (x.n === 0 && x.nivel !== "info" ? "info" : x.nivel) + '" data-q="' + x.id + '"><h3>' + esc(x.titulo) + '</h3><div class="q-n" data-n="' + x.n + '">' + fmtNum(x.n) + "</div>"
        + (x.texto ? "<p>" + esc(x.texto) + "</p>" : "") + (x.n ? "<details><summary>Ver lista</summary><ul>" + mostra + resto + "</ul></details>" : "") + "</div>";
    }).join("");
  }

  /* ---------------------------------------------------------------- cores e gráficos */
  const css = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  const cat = (i) => (i === "outros" ? css("--outros") : css("--s" + ((i % 8) + 1)));
  const COR_PROB = { "Provável": "--critico", "Possível": "--alerta", "Remota": "--bom", semProb: "--outros" };
  function configurarChart() {
    if (typeof Chart === "undefined") return;
    Chart.defaults.animation = false;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 11;
    Chart.defaults.color = css("--tinta-2");
    Chart.defaults.borderColor = css("--linha");
  }
  const curto = (s, n) => { s = String(s); return s.length > (n || 34) ? s.slice(0, (n || 34) - 1) + "…" : s; };
  function html_painel(id, titulo, sub, extra) {
    extra = extra || {};
    return '<div class="painel' + (extra.largo ? " largo" : "") + '" id="p-' + id + '"><h3>' + esc(titulo) + '</h3><div class="sub" id="sub-' + id + '">' + (sub || "") + "</div>"
      + '<div class="caixa-graf ' + (extra.altura || "") + '"><canvas id="ch-' + id + '" role="img" aria-label="' + esc(titulo) + '"></canvas></div>'
      + '<details class="tabela-dados"><summary>Ver como tabela</summary><div class="rolagem" id="td-' + id + '"></div></details></div>';
  }
  function kpi(chave, rotulo, valorTxt, sub, valor, cls) {
    return '<div class="kpi ' + (cls || "") + '" data-kpi="' + chave + '"' + (valor != null ? ' data-valor="' + valor + '"' : "") + '><div class="rotulo">' + esc(rotulo)
      + '</div><div class="valor">' + valorTxt + '</div><div class="sub">' + (sub || "") + "</div></div>";
  }
  function tabelaDeDados(id, cfg) {
    const el = $("td-" + id); if (!el) return;
    const rotulos = cfg.data.labels, sets = cfg.data.datasets;
    const fmt = (v) => (typeof v === "number" ? (Math.abs(v) >= 1000 && !(cfg.options && cfg.options._inteiro) ? fmtDec(v, 2) : fmtDec(v, Number.isInteger(v) ? 0 : 2)) : (v == null ? "—" : esc(v)));
    let h = "<table><thead><tr><th scope=\"col\"><button type=\"button\" tabindex=\"-1\">Item</button></th>" + sets.map((s) => '<th scope="col"><button type="button" tabindex="-1">' + esc(s.label || "Valor") + "</button></th>").join("") + "</tr></thead><tbody>";
    rotulos.forEach((l, i) => { h += '<tr><th scope="row">' + esc(l) + "</th>" + sets.map((s) => '<td class="num">' + fmt(s.data[i]) + "</td>").join("") + "</tr>"; });
    el.innerHTML = h + "</tbody></table>";
  }
  function grafico(id, cfg, resumo) {
    if (GRAFICOS[id]) { GRAFICOS[id].destroy(); delete GRAFICOS[id]; }
    const el = $("ch-" + id); if (!el || typeof Chart === "undefined") return;
    GRAFICOS[id] = new Chart(el, cfg);
    el.setAttribute("aria-label", (resumo ? resumo + " " : "") + "Os dados também estão em \"Ver como tabela\".");
    tabelaDeDados(id, cfg);
  }
  const opBarra = (o) => {
    o = o || {};
    const fm = o.dinheiro ? fmtBRL : fmtNum;
    return { indexAxis: o.horizontal ? "y" : "x", maintainAspectRatio: false, _inteiro: !o.dinheiro,
      plugins: { legend: { display: !!o.legenda, position: "bottom" }, tooltip: { callbacks: {
        title: (it) => it[0].label, label: (c) => (c.dataset.label ? c.dataset.label + ": " : "") + fm(c.parsed[o.horizontal ? "x" : "y"]) + (o.sufixo || "") } } },
      scales: { x: { stacked: !!o.empilhado, beginAtZero: true, grid: { display: !!o.horizontal }, ticks: { precision: 0, callback: o.horizontal ? (o.dinheiro ? (v) => fmtBRLc(v) : undefined) : function (v) { return curto(this.getLabelForValue(v), 14); }, autoSkip: !!o.horizontal, maxRotation: o.horizontal ? 0 : 45 } },
        y: { stacked: !!o.empilhado, beginAtZero: true, grid: { display: !o.horizontal }, ticks: { precision: 0, autoSkip: false, callback: o.horizontal ? function (v) { return curto(this.getLabelForValue(v), 30); } : (o.dinheiro ? (v) => fmtBRLc(v) : undefined) } } } };
  };
  const opRosca = () => ({ maintainAspectRatio: false, cutout: "58%", _inteiro: true, plugins: { legend: { position: "right", labels: { boxWidth: 11, padding: 8, font: { size: 11 } } },
    tooltip: { callbacks: { label: (c) => c.label + ": " + fmtNum(c.parsed) + " (" + Math.round((c.parsed / c.dataset.data.reduce((a, b) => a + b, 0)) * 100) + "%)" } } } });
  /** Barras horizontais simples de um mapa {rótulo: n}, cor única; vazio vira aviso. */
  function barrasDeMapa(id, mapa, n, cor, opcoes, resumo) {
    const it = topo(mapa, n);
    marcarVazio(id, !it.length);
    if (!it.length) { if (GRAFICOS[id]) { GRAFICOS[id].destroy(); delete GRAFICOS[id]; } const td = $("td-" + id); if (td) td.innerHTML = ""; return; }
    grafico(id, { type: "bar", data: { labels: it.map((x) => x[0]), datasets: [{ label: (opcoes && opcoes.rotulo) || "Processos", data: it.map((x) => x[1]), backgroundColor: cor || cat(0), borderRadius: 4, maxBarThickness: 22 }] },
      options: opBarra(Object.assign({ horizontal: true }, opcoes)) }, resumo);
  }
  function marcarVazio(id, vazio) {
    const p = $("p-" + id); if (!p) return;
    const caixa = p.querySelector(".caixa-graf"); let av = p.querySelector(".vazio");
    if (vazio && !av) { av = document.createElement("div"); av.className = "vazio"; av.textContent = "Sem dados para este gráfico na seleção atual."; p.insertBefore(av, caixa); }
    if (av) av.hidden = !vazio;
    caixa.hidden = vazio;
  }
  /** Rosca com no máximo 7 fatias + "Outros"; cor por posição fixa (primeiras 7 cores). */
  function roscaDeMapa(id, mapa, resumo) {
    let it = topo(mapa), vazio = !it.length;
    marcarVazio(id, vazio);
    if (vazio) { if (GRAFICOS[id]) { GRAFICOS[id].destroy(); delete GRAFICOS[id]; } const td = $("td-" + id); if (td) td.innerHTML = ""; return; }
    if (it.length > 8) { const resto = it.slice(7).reduce((s, x) => s + x[1], 0); it = it.slice(0, 7).concat([["Outros", resto]]); }
    grafico(id, { type: "doughnut", data: { labels: it.map((x) => x[0]), datasets: [{ label: "Processos", data: it.map((x) => x[1]),
      backgroundColor: it.map((x, i) => (x[0] === "Outros" ? cat("outros") : cat(i))), borderWidth: 2, borderColor: css("--cartao") }] }, options: opRosca() }, resumo);
  }

  /* ---------------------------------------------------------------- tabela de processos */
  const TAB = { ordem: null, dir: 1, pagina: 0, porPagina: 50, todas: false };
  function etiquetaProb(p) { return p ? '<span class="etq ' + (p === "Provável" ? "prov" : p === "Possível" ? "poss" : "rem") + '">' + p + "</span>" : "—"; }
  function desenharTabela(D) {
    const cols = modelo.colunas; let linhas = D.slice();
    if (TAB.ordem) {
      const c = cols.find((x) => x.k === TAB.ordem);
      linhas.sort((a, b) => { let x = c.valor(a), y = c.valor(b); if (x == null) x = typeof y === "number" ? -Infinity : ""; if (y == null) y = typeof x === "number" ? -Infinity : "";
        return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "pt-BR")) * TAB.dir; });
    }
    const total = linhas.length, ini = TAB.todas ? 0 : TAB.pagina * TAB.porPagina;
    const fatia = TAB.todas ? linhas : linhas.slice(ini, ini + TAB.porPagina);
    $("t-contagem").textContent = total + " processo(s) na seleção. Clique no título da coluna para ordenar.";
    $("t-cab").innerHTML = "<tr>" + cols.map((c) => '<th scope="col"' + (TAB.ordem === c.k ? ' aria-sort="' + (TAB.dir > 0 ? "ascending" : "descending") + '"' : "") + '><button type="button" data-k="' + c.k + '">' + esc(c.rotulo) + "</button></th>").join("") + "</tr>";
    $("t-corpo").innerHTML = fatia.length ? fatia.map((r) => "<tr>" + cols.map((c) => (c.k === "numero" ? '<th scope="row" class="proc">' : "<td" + (c.num ? ' class="num"' : "") + ">") + c.html(r) + (c.k === "numero" ? "</th>" : "</td>")).join("") + "</tr>").join("")
      : '<tr><td colspan="' + cols.length + '" class="vazio">Nenhum processo corresponde aos filtros.</td></tr>';
    $("t-cab").querySelectorAll("button").forEach((b) => (b.onclick = () => { TAB.dir = TAB.ordem === b.dataset.k ? -TAB.dir : 1; TAB.ordem = b.dataset.k; TAB.pagina = 0; desenharTabela(D); }));
    const paginas = Math.max(1, Math.ceil(total / TAB.porPagina));
    $("t-pag").hidden = TAB.todas || total <= TAB.porPagina;
    $("t-pag-info").textContent = "Página " + (TAB.pagina + 1) + " de " + paginas;
    $("t-ant").disabled = TAB.pagina === 0; $("t-prox").disabled = TAB.pagina >= paginas - 1;
    $("t-ant").onclick = () => { TAB.pagina--; desenharTabela(D); };
    $("t-prox").onclick = () => { TAB.pagina++; desenharTabela(D); };
  }
  function htmlTabela() {
    return '<div class="sec"><span class="n">' + (modelo.numeroTabela || "") + "</span><h2>Processos (detalhe)</h2><div class=\"regua\"></div></div>"
      + '<div class="tabela-caixa"><div class="contagem" id="t-contagem" aria-live="polite"></div><div class="rolagem"><table id="tabela"><caption class="somente-leitor">Processos da seleção atual</caption><thead id="t-cab"></thead><tbody id="t-corpo"></tbody></table></div>'
      + '<div class="paginacao" id="t-pag"><button type="button" class="btn sec" id="t-ant">Anterior</button><span id="t-pag-info"></span><button type="button" class="btn sec" id="t-prox">Próxima</button></div></div>';
  }

  /* ---------------------------------------------------------------- série histórica (comum aos modelos) */
  function serieHistorica(atual) {
    const mapa = new Map();
    estado.historico.forEach((p) => mapa.set(p.data, p));
    (CFG.historico || []).forEach((r) => {
      const t = r.totais || {}; const n = (x) => (x == null || x === "" ? null : parseDinheiro(x));
      mapa.set(r.data_base, { data: r.data_base, total: n(t.processos), ativos: n(t.ativos), encerrados: n(t.encerrados), valorCausa: n(t.valor_causa), valorEstimado: n(t.valor_estimado), valorEconomizado: n(t.valor_economizado) });
    });
    if (atual && !mapa.has(estado.dataBase)) mapa.set(estado.dataBase, Object.assign({ data: estado.dataBase, atual: true }, atual));
    return [...mapa.values()].sort((a, b) => (a.data < b.data ? -1 : 1));
  }

  /* ---------------------------------------------------------------- ciclo principal */
  function atualizar() {
    const D = filtrar();
    estado.filtrados = D;
    estado.ind = indicadores(D, estado.dataBase);
    estado.indTodos = indicadores(estado.unicos, estado.dataBase);
    configurarChart();
    modelo.render({ D, todos: estado.unicos, ind: estado.ind, indTodos: estado.indTodos, dataBase: estado.dataBase, h: AJUDAS });
    TAB.pagina = 0; desenharTabela(D);
    document.documentElement.dataset.pronto = "1";
  }
  const AJUDAS = { $, esc, norm, fmtNum, fmtDec, fmtBRL, fmtBRLc, fmtPct, fmtData, somar, contar, topo, unicos, kpi, html_painel, grafico, opBarra, opRosca, barrasDeMapa, roscaDeMapa,
    marcarVazio, cat, css, curto, etiquetaProb, empresaDoGrupo, serieHistorica, diasEntre, MOTIVOS, COR_PROB, RESULTADOS, grupo: () => GRUPO, parametros: () => PARAMETROS, cfg: CFG };

  function carregar(grade, origem) {
    const leitura = lerPlanilha(grade);
    if (leitura.params) {
      if (leitura.params.grupo.length) GRUPO = leitura.params.grupo; // a lista da planilha manda sobre a do perfil
      if (leitura.params.headcount) PARAMETROS.headcount = leitura.params.headcount;
    }
    if (!leitura.registros.length) { mostrarMsg("Nenhum processo reconhecido. A planilha precisa ter uma coluna \"Número do Processo\" e ao menos mais duas colunas conhecidas.", "erro"); return false; }
    // o grupo pode ter vindo da planilha: refaz o polo dos registros que dependiam dele
    if (leitura.params && leitura.params.grupo.length) leitura.registros.forEach((r) => { if (!r.polo && empresaDoGrupo(r.autores) && !empresaDoGrupo(r.reus)) { r.polo = "ativo"; r.econ = calcularEconomia(r); } });
    const { unicos: u, removidos } = deduplicar(leitura.registros);
    estado.registros = leitura.registros; estado.unicos = u; estado.leitura = leitura; estado.historico = leitura.historicoAba;
    estado.dataBase = CFG.data_base || (leitura.params && leitura.params.dataRef) || hojeISO();
    $("f-data").value = estado.dataBase;
    estado.qualidade = montarQualidade(leitura, removidos);
    const clientes = unicos(u.map((r) => r.cliente));
    $("etiqueta").innerHTML = (clientes.length ? "Cliente: <b>" + esc(clientes.length === 1 ? clientes[0] : clientes.length + " clientes") + "</b> · " : "") + fmtNum(u.length) + " processos · fonte: " + esc(origem) + " · data de referência " + fmtData(estado.dataBase);
    $("estado").classList.add("pronto"); $("estado-texto").textContent = "Dados carregados";
    $("carregador").hidden = true; $("app").hidden = false;
    montarConteudo(); preencherFiltros(); desenharQualidade(); atualizar();
    return true;
  }
  function montarConteudo() { $("conteudo").innerHTML = modelo.montar(AJUDAS) + htmlTabela(); }
  function mostrarMsg(t, c) { const m = $("msg"); m.textContent = t; m.className = "msg " + (c || ""); }

  /* ---------------------------------------------------------------- entrada (SheetJS) */
  function gradeDoWorkbook(wb) {
    return wb.SheetNames.map((nome) => {
      const ws = wb.Sheets[nome]; const linhas = [];
      if (ws && ws["!ref"]) {
        const r = XLSX.utils.decode_range(ws["!ref"]);
        for (let R = r.s.r; R <= r.e.r; R++) {
          const lin = [];
          for (let C = r.s.c; C <= r.e.c; C++) {
            const c = ws[XLSX.utils.encode_cell({ r: R, c: C })];
            // erro de célula (t "e") não vira número; fórmula sem valor em cache vira vazio
            lin.push(!c || c.t === "e" || c.v === undefined ? null : c.v);
          }
          linhas.push(lin);
        }
      }
      return { nome, linhas };
    });
  }
  function lerArquivo(f) {
    mostrarMsg("Lendo " + f.name + "…");
    if (typeof XLSX === "undefined") { mostrarMsg("Esta página não traz o leitor de planilhas.", "erro"); return; }
    const ehCsv = /\.csv$/i.test(f.name), rd = new FileReader();
    rd.onload = (e) => {
      try {
        const wb = ehCsv ? XLSX.read(e.target.result, { type: "string", raw: true }) : XLSX.read(new Uint8Array(e.target.result), { type: "array", cellDates: false });
        if (carregar(gradeDoWorkbook(wb), f.name)) mostrarMsg("");
      } catch (err) { console.error(err); mostrarMsg("Não consegui abrir o arquivo: " + err.message, "erro"); }
    };
    rd.onerror = () => mostrarMsg("Falha ao ler o arquivo.", "erro");
    if (ehCsv) rd.readAsText(f, "UTF-8"); else rd.readAsArrayBuffer(f);
  }

  /* ---------------------------------------------------------------- interface: abas, impressão, tema */
  function ligarAbas() {
    const abas = [["tab-painel", "aba-painel"], ["tab-qualidade", "aba-qualidade"]];
    const ir = (i) => abas.forEach(([t, p], k) => { $(t).setAttribute("aria-selected", k === i); $(t).tabIndex = k === i ? 0 : -1; $(p).hidden = k !== i; });
    abas.forEach(([t], i) => {
      $(t).onclick = () => ir(i);
      $(t).onkeydown = (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { const j = (i + (e.key === "ArrowRight" ? 1 : abas.length - 1)) % abas.length; ir(j); $(abas[j][0]).focus(); } };
    });
  }
  function redesenharTudo() { if (estado.unicos.length && modelo) { configurarChart(); atualizar(); } }
  function ligarImpressao() {
    $("b-imprimir").onclick = () => window.print();
    let antes = null;
    window.addEventListener("beforeprint", () => { antes = TAB.todas; TAB.todas = true; if (estado.filtrados.length) desenharTabela(estado.filtrados); Object.values(GRAFICOS).forEach((c) => c.resize()); });
    window.addEventListener("afterprint", () => { TAB.todas = antes; if (estado.filtrados.length) desenharTabela(estado.filtrados); Object.values(GRAFICOS).forEach((c) => c.resize()); });
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(redesenharTudo);
    }
  }
  function ligarCarregador() {
    const soltar = $("soltar"), entrada = $("arquivo");
    ["dragenter", "dragover"].forEach((e) => soltar.addEventListener(e, (ev) => { ev.preventDefault(); soltar.classList.add("sobre"); }));
    ["dragleave", "drop"].forEach((e) => soltar.addEventListener(e, (ev) => { ev.preventDefault(); soltar.classList.remove("sobre"); }));
    soltar.addEventListener("drop", (ev) => { const f = ev.dataTransfer.files[0]; if (f) lerArquivo(f); });
    entrada.onchange = () => { if (entrada.files[0]) lerArquivo(entrada.files[0]); };
    $("b-trocar").onclick = () => { $("app").hidden = true; $("carregador").hidden = false; $("estado").classList.remove("pronto"); $("estado-texto").textContent = "Sem dados"; entrada.value = ""; mostrarMsg(""); };
  }

  return {
    estado, CFG, AJUDAS,
    registrarModelo(m) { modelo = m; },
    /** Utilidades expostas para testes e para os modelos. */
    util: { norm, parseDinheiro, paraISO, dvConfere, classeResultado, limparTribunal, lerPlanilha, deduplicar },
    iniciar() {
      ligarAbas(); ligarImpressao(); ligarCarregador();
      if (CFG.modo === "embutido" && CFG.dados) {
        try { carregar(CFG.dados.sheets || CFG.dados, CFG.fonte || "dados embutidos"); }
        catch (err) { console.error(err); document.getElementById("carregador").hidden = false; mostrarMsg("Erro ao montar o painel: " + err.message, "erro"); }
      }
    }
  };
})();
