"""Peças comuns do painel: estilo, barra de abas, mensagens, redirecionamento,
verificação do token, proteção de caminhos e a escolha do relatório ativo.
Cada tela (os outros módulos de painel/) recebe `cabecalho` e `token_ok` daqui
pelo `registrar(app, TOKEN, cabecalho, token_ok)`, como em cadastro.py."""
import html
import os
import sys
from pathlib import Path

from flask import abort, redirect, request

import comum

TAREFA = {}  # tarefa em execução (uma por vez: o login usa o certificado)
WINDOWS = sys.platform.startswith("win")

ESTILO = """<style>
:root{--marinho:#0f2236;--marinho-2:#163758;--teal:#4fa598;--teal-2:#3d8a7e;--cobre:#bb734d;
--tinta:#0e1620;--suave:#536773;--linha:#e2e7eb;--fundo:#f1f3f5;--cartao:#ffffff;
--hero-de:#e6f0fb;--hero-ate:#eef4fb;
--ambar:#b45309;--ambar-fundo:#fff8e1;--ambar-borda:#f1dfa0;
--azul:#1d4f91;--azul-fundo:#eaf4fe;--azul-borda:#b9d8f5;
--verde:#15803d;--verde-fundo:#e8f8f0;--verde-borda:#b5e6cb;
--perigo:#b91c1c;--perigo-fundo:#fef2f2;--perigo-borda:#f3c1c1;
--link:#2c7a6e;--botao:#2f7d71;--botao-2:#2a7266;--borda-forte:#8796a2;--sutil:#f6f8f9;--sombra:0 1px 2px rgba(15,34,54,.05);
--fundo2:var(--sutil);--acento:var(--link);--alerta:var(--ambar);--alerta-fundo:var(--ambar-fundo);--ok:var(--verde);--ok-fundo:var(--verde-fundo);
--lateral-w:76px;color-scheme:light}
@media (prefers-color-scheme: dark){:root{color-scheme:dark;
--marinho:#091827;--marinho-2:#163758;--teal:#4fa598;--teal-2:#3d8a7e;--cobre:#d99b78;
--tinta:#e6edf3;--suave:#9fb0bf;--linha:#243545;--fundo:#0b141d;--cartao:#13202d;
--hero-de:#14304a;--hero-ate:#13202d;
--ambar:#ffd27a;--ambar-fundo:rgba(245,158,11,.13);--ambar-borda:rgba(245,158,11,.38);
--azul:#8cc4f5;--azul-fundo:rgba(59,130,246,.15);--azul-borda:rgba(96,165,250,.4);
--verde:#6fdc9f;--verde-fundo:rgba(34,197,94,.13);--verde-borda:rgba(74,222,128,.35);
--perigo:#ff8a8a;--perigo-fundo:rgba(239,68,68,.14);--perigo-borda:rgba(248,113,113,.4);
--link:#6fcdbf;--botao:#2f7d71;--botao-2:#3d8a7e;--borda-forte:#5d7284;--sutil:#0f1b27;--sombra:none}}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:Inter,"SF Pro Text",-apple-system,"Segoe UI",system-ui,sans-serif;font-size:15px;line-height:1.5;color:var(--tinta);background:var(--fundo);margin:0}
a{color:var(--link)}a:hover{text-decoration-thickness:2px}
:focus-visible{outline:2px solid var(--link);outline-offset:2px;border-radius:6px}
input[type=checkbox],input[type=radio]{accent-color:var(--botao)}
.pular{position:absolute;left:12px;top:-60px;z-index:100;background:var(--marinho);color:#fff;padding:8px 14px;border-radius:999px;font-weight:600;text-decoration:none}
.pular:focus{top:10px;outline-color:#fff}

/* casco: barra lateral + barra superior + conteúdo */
.app{display:flex;align-items:flex-start;min-height:100vh}
.lateral{position:sticky;top:0;align-self:flex-start;height:100vh;width:var(--lateral-w);flex:none;background:var(--marinho);color:#c9d6e2;
  display:flex;flex-direction:column;padding:14px 12px;z-index:40;transition:width .18s ease}
html.expandida .lateral{--lateral-w:244px}
.lateral a{color:inherit;text-decoration:none}
.lateral :focus-visible{outline-color:#9be4d8}
.marca-chc{display:flex;align-items:center;gap:12px;height:48px;padding:0 10px;margin-bottom:10px;color:#fff;border-radius:12px;flex:none}
.marca-chc svg{flex:none;width:36px;height:auto}
.marca-chc .nome{font-weight:700;font-size:14px;line-height:1.2;white-space:nowrap}.marca-chc .nome small{display:block;font-weight:400;font-size:11px;color:#9fb4c7;letter-spacing:.04em}
.lateral nav{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;scrollbar-width:none;display:flex;flex-direction:column;gap:4px}
.lateral nav::-webkit-scrollbar{display:none}
.item{position:relative;display:flex;align-items:center;gap:14px;height:46px;padding:0 12px;border-radius:10px;color:#c9d6e2;flex:none;font-size:14px;font-weight:500;white-space:nowrap}
.item .ic{flex:none}
.item:hover{background:var(--marinho-2);color:#fff}
.item.ativo{background:var(--teal-2);color:#fff;font-weight:600}
.item .ponto{position:absolute;left:30px;top:8px;width:10px;height:10px;border-radius:50%;background:#e8a33d;border:2px solid var(--marinho)}
.item .ponto.ok{background:#4ade80}
.sep{height:1px;background:rgba(255,255,255,.1);margin:8px 6px;flex:none}
.rodape-lateral{flex:none;padding-top:8px;border-top:1px solid rgba(255,255,255,.1);display:flex;flex-direction:column;gap:4px}
.rodape-lateral .versao{font-size:11px;color:#8ea3b6;padding:2px 12px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
html:not(.expandida) .rodape-lateral .versao{display:none}
.veu{display:none}
.corpo{flex:1;min-width:0}
.topo{position:sticky;top:0;z-index:30;height:60px;background:var(--cartao);border-bottom:1px solid var(--linha);display:flex;align-items:center;gap:14px;padding:0 24px}
#atencao ~ .app .topo{top:0}
.topo .ico{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;padding:0;margin:0;border-radius:10px;border:1px solid transparent;background:none;color:var(--tinta);cursor:pointer;flex:none}
.topo .ico:hover{background:var(--sutil);border-color:var(--linha)}
.nome-app{font-weight:700;font-size:15px;white-space:nowrap}.nome-app small{font-weight:400;color:var(--suave);font-size:12px;margin-left:6px}
.busca{position:relative;flex:1;max-width:460px;margin-left:auto;min-width:0}
.busca svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--suave);pointer-events:none}
.busca input[type=search]{width:100%;padding:9px 16px 9px 40px;border-radius:999px;background:var(--sutil)}
.topo-fim{display:flex;align-items:center;gap:10px;margin-left:auto;flex:none}
.busca + .topo-fim{margin-left:0}
.topo .pilula{padding:7px 16px;margin:0}
.tarefa{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;background:var(--azul-fundo);border:1px solid var(--azul-borda);color:var(--azul);font-size:13px;font-weight:600;text-decoration:none;max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tarefa::before{content:"";flex:none;width:8px;height:8px;border-radius:50%;background:currentColor;animation:pulsa 1.4s ease-in-out infinite}
@keyframes pulsa{50%{opacity:.25}}
.rel{position:relative}
.rel summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;border:1px solid var(--borda-forte);font-size:14px;background:var(--cartao);white-space:nowrap;max-width:300px}
.rel summary::-webkit-details-marker{display:none}
.rel summary b{overflow:hidden;text-overflow:ellipsis;font-weight:600}
.rel summary svg{flex:none;transition:transform .15s}.rel[open] summary svg{transform:rotate(180deg)}
.rel-lista{position:absolute;right:0;top:calc(100% + 8px);min-width:240px;max-width:min(360px,90vw);background:var(--cartao);border:1px solid var(--linha);border-radius:14px;box-shadow:0 10px 30px rgba(15,34,54,.18);padding:6px;z-index:60}
.rel-lista a{display:block;padding:9px 12px;border-radius:9px;text-decoration:none;color:var(--tinta);font-size:14px}
.rel-lista a:hover{background:var(--sutil)}
.rel-lista a[aria-current]{font-weight:700;background:var(--sutil)}
.rel-lista a.novo{color:var(--link);font-weight:600;border-top:1px solid var(--linha);border-radius:0 0 9px 9px;margin-top:4px}
.painel-ajuda{margin:20px 28px 0;background:var(--cartao);border:1px solid var(--linha);border-left:4px solid var(--teal);border-radius:14px;padding:16px 20px;box-shadow:var(--sombra)}
.painel-ajuda[hidden]{display:none}
.painel-ajuda h2{margin:0 0 6px;font-size:17px}.painel-ajuda p{margin:6px 0}.painel-ajuda ul{margin:6px 0 12px;padding-left:20px}
.aviso-topo{margin:16px 28px 0}
.aviso-topo.forte{background:var(--perigo);border-color:var(--perigo);color:#fff;font-weight:700}.aviso-topo.forte a{color:#fff}
main{max-width:1120px;margin:0 auto;padding:28px 28px 64px}

/* tipografia e blocos */
h1{font-size:30px;line-height:1.2;font-weight:700;letter-spacing:-.01em;margin:4px 0 8px}
h2{margin:32px 0 12px;font-size:19px;font-weight:600;line-height:1.3}
h3{margin:20px 0 8px;font-size:16px;font-weight:600}
p{margin:8px 0}
.rotulo{font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.12em;color:var(--suave)}
.meta,.dica{color:var(--suave);font-size:13px}
.cabeca-pagina{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px 20px;margin:0 0 8px}
.cabeca-pagina h1{margin:0}.cabeca-pagina .acoes{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.caixa,.ev{background:var(--cartao);border:1px solid var(--linha);border-radius:14px;padding:20px;margin:16px 0;box-shadow:var(--sombra)}
.caixa > :first-child,.ev > :first-child{margin-top:0}.caixa > :last-child,.ev > :last-child{margin-bottom:0}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;margin:16px 0}
.grade > .caixa,.grade > .ev{margin:0}
.vazio{text-align:center;color:var(--suave);padding:32px 20px;border:1px dashed var(--borda-forte);border-radius:14px;margin:16px 0;background:var(--sutil)}
.cartoes{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:16px 0}
.cartoes > .cartao{background:var(--cartao);border:1px solid var(--linha);border-radius:14px;padding:14px 16px;font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--suave);line-height:1.35;box-shadow:var(--sombra)}
.cartao b{font-size:30px;line-height:1.15;display:block;color:var(--tinta);letter-spacing:0;text-transform:none;font-weight:700;margin-bottom:2px}
.selo{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;line-height:1.5;background:var(--sutil);border:1px solid var(--linha);color:var(--suave);vertical-align:middle}
.selo.ok{background:var(--verde-fundo);border-color:var(--verde-borda);color:var(--verde)}
.selo.atencao{background:var(--ambar-fundo);border-color:var(--ambar-borda);color:var(--ambar)}
.selo.erro{background:var(--perigo-fundo);border-color:var(--perigo-borda);color:var(--perigo)}
.alerta{background:var(--ambar-fundo);border:1px solid var(--ambar-borda);color:var(--ambar);padding:10px 14px;border-radius:10px;font-size:14px;margin:8px 0}
.alerta a{color:inherit;font-weight:600}
.msg{background:var(--verde-fundo);border:1px solid var(--verde-borda);color:var(--verde);padding:10px 14px;border-radius:10px;margin:16px 0;white-space:pre-line;font-weight:500}
div.erro{background:var(--perigo-fundo);border:1px solid var(--perigo-borda);color:var(--perigo);padding:10px 14px;border-radius:10px;font-size:14px;margin:8px 0}
div.info{background:var(--azul-fundo);border:1px solid var(--azul-borda);color:var(--azul);padding:10px 14px;border-radius:10px;font-size:14px;margin:8px 0}
blockquote{color:var(--suave);border-left:3px solid var(--teal);margin:8px 0;padding:2px 0 2px 14px;font-size:14px}
pre.log{background:#0b1620;color:#d7e2ea;padding:16px;border-radius:14px;font-size:12px;line-height:1.55;max-height:420px;overflow:auto;white-space:pre-wrap;border:1px solid #1e3043}

/* formulários e botões */
button,.pilula{font:inherit;font-size:14px;font-weight:600;line-height:1.2;display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:8px 18px;margin-right:6px;
  border-radius:999px;border:1px solid var(--borda-forte);background:var(--cartao);color:var(--tinta);cursor:pointer;text-decoration:none;transition:background .15s,border-color .15s}
button:hover,.pilula:hover{background:var(--sutil);border-color:var(--tinta)}
button.principal,.pilula.principal{background:var(--botao);border-color:var(--botao);color:#fff}
button.principal:hover,.pilula.principal:hover{background:var(--botao-2);border-color:var(--botao-2)}
button:disabled,button[disabled]{opacity:.5;cursor:not-allowed}
input[type=text],input[type=date],input[type=search],input[type=password],input[type=number],input[type=email],input[type=url],input[type=time],select,textarea{
  font:inherit;font-size:14px;padding:8px 12px;border:1px solid var(--borda-forte);border-radius:10px;background:var(--cartao);color:var(--tinta);max-width:100%}
input::placeholder,textarea::placeholder{color:var(--suave);opacity:1}
textarea{width:100%;display:block}
input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--link);outline-offset:1px;border-color:var(--link)}
label{font-size:14px}
table{width:100%;border-collapse:collapse;font-size:14px;margin:12px 0}
th{text-align:left;font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--suave);padding:8px 12px;border-bottom:1px solid var(--linha);vertical-align:bottom}
td{padding:11px 12px;border-bottom:1px solid var(--linha);vertical-align:top}
tr:last-child > td{border-bottom:none}
table tr:hover > td{background:var(--sutil)}
hr{border:none;border-top:1px solid var(--linha);margin:20px 0}

#atencao{position:sticky;top:0;z-index:70;background:#b91c1c;color:#fff;padding:10px 24px;font-weight:700;font-size:15px}
#atencao small{display:block;font-weight:400;opacity:.9}

/* botão (i) de ajuda; o balão é criado pelo SCRIPT_AJUDA e nunca sai da janela */
.ajuda{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;margin-left:6px;border-radius:50%;
  border:1.5px solid var(--suave);color:var(--suave);font:700 11px/1 Georgia,serif;font-style:italic;cursor:help;vertical-align:middle;user-select:none;background:transparent;flex:none}
.ajuda:hover,.ajuda:focus-visible,.ajuda.aberta{background:var(--botao);color:#fff;border-color:var(--botao)}
.ajuda:focus-visible{outline:2px solid var(--link);outline-offset:2px}
.ajuda-balao{position:fixed;z-index:200;left:0;top:0;width:max-content;max-width:min(320px,calc(100vw - 16px));background:#0e1620;color:#fff;padding:10px 12px;border-radius:10px;
  font:400 13px/1.45 Inter,"SF Pro Text",-apple-system,"Segoe UI",system-ui,sans-serif;font-style:normal;text-align:left;white-space:normal;box-shadow:0 8px 24px rgba(0,0,0,.3);pointer-events:none;border:1px solid rgba(255,255,255,.14)}
.ajuda-balao::before{content:"";position:absolute;left:var(--seta,50%);width:10px;height:10px;background:#0e1620;transform:translateX(-50%) rotate(45deg);top:-6px;border-left:1px solid rgba(255,255,255,.14);border-top:1px solid rgba(255,255,255,.14)}
.ajuda-balao.acima::before{top:auto;bottom:-6px;border:none;border-right:1px solid rgba(255,255,255,.14);border-bottom:1px solid rgba(255,255,255,.14)}
.ajuda-balao[hidden]{display:none}

@media (max-width:1100px){.nome-app small{display:none}}
@media (max-width:980px){.nome-app{display:none}.busca{min-width:150px}.topo .pilula .txt{display:none}}
@media (max-height:760px){.item{height:42px}.lateral nav{gap:2px}.sep{margin:5px 6px}}
/* dicas da barra lateral recolhida (desktop) */
@media (min-width:800px){
  html:not(.expandida) .item .rot,html:not(.expandida) .marca-chc .nome{display:none}
  html:not(.expandida) .item:hover .rot,html:not(.expandida) .item:focus-visible .rot{display:block;position:fixed;left:68px;top:var(--ty,0);transform:translateY(-50%);
    background:#0e1620;color:#fff;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:600;box-shadow:0 6px 18px rgba(0,0,0,.3);z-index:90;pointer-events:none;border:1px solid rgba(255,255,255,.14)}
}
/* celular e janelas estreitas: a lateral vira gaveta */
@media (max-width:799px){
  .lateral{position:fixed;left:0;top:0;bottom:0;height:100%;width:260px;transform:translateX(-102%);visibility:hidden;transition:transform .2s ease,visibility 0s .2s;z-index:80}
  html.gaveta .lateral{transform:none;visibility:visible;transition-delay:0s;box-shadow:0 0 40px rgba(0,0,0,.4)}
  html.gaveta .veu{display:block;position:fixed;inset:0;background:rgba(5,12,20,.55);z-index:75}
  .topo{padding:0 12px;gap:8px}
  .nome-app{display:none}
  .busca{max-width:none;margin-left:0;min-width:0;flex:1 1 60px}
  .busca input[type=search]{padding-left:34px;padding-right:8px}.busca svg{left:10px}
  .topo-fim{margin-left:0;gap:6px;min-width:0}
  .topo .pilula{padding:7px 9px}
  .rel summary{gap:4px}
  .topo .pilula .txt,.rel summary .pre{display:none}
  .rel summary{max-width:110px;padding:7px 10px}
  .tarefa{max-width:120px;padding:6px 8px}
  main{padding:20px 16px 48px}
  .painel-ajuda,.aviso-topo{margin-left:16px;margin-right:16px}
  h1{font-size:25px}
  .caixa,.ev{padding:16px}
  table{display:block;overflow-x:auto}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
@media print{.lateral,.topo,.veu,.painel-ajuda{display:none!important}.app{display:block}body{background:#fff}}
</style>"""

# Antes de pintar a página: lembra se a barra lateral ficou expandida (try/catch: o navegador pode bloquear o armazenamento).
SCRIPT_LATERAL_INICIAL = """<script>
try{if(localStorage.getItem('chc-lateral')==='1')document.documentElement.classList.add('expandida')}catch(e){}
</script>"""

# Hambúrguer (recolhe/expande a lateral; no celular abre a gaveta), menu dos relatórios e painel "Como usar esta tela".
SCRIPT_CASCO = """<script>
(function(){var h=document.documentElement,mq=window.matchMedia('(max-width:799px)'),bt=document.getElementById('alternar-lateral');
function est(){var a=mq.matches?h.classList.contains('gaveta'):h.classList.contains('expandida');if(bt)bt.setAttribute('aria-expanded',a?'true':'false')}
if(bt)bt.addEventListener('click',function(){
if(mq.matches){h.classList.toggle('gaveta')}else{var e=h.classList.toggle('expandida');try{localStorage.setItem('chc-lateral',e?'1':'0')}catch(x){}}est()});
var v=document.querySelector('.veu');if(v)v.addEventListener('click',function(){h.classList.remove('gaveta');est()});
document.addEventListener('keydown',function(e){if(e.key!=='Escape')return;
if(h.classList.contains('gaveta')){h.classList.remove('gaveta');est();if(bt)bt.focus()}
var d=document.querySelector('details.rel[open]');if(d){d.removeAttribute('open');d.querySelector('summary').focus()}});
document.addEventListener('click',function(e){var d=document.querySelector('details.rel[open]');if(d&&!d.contains(e.target))d.removeAttribute('open')});
[].forEach.call(document.querySelectorAll('.lateral .item'),function(a){
function ty(){var r=a.getBoundingClientRect();a.style.setProperty('--ty',(r.top+r.height/2)+'px')}
a.addEventListener('mouseenter',ty);a.addEventListener('focus',ty);
a.addEventListener('click',function(){if(mq.matches){h.classList.remove('gaveta');est()}})});
if(mq.addEventListener)mq.addEventListener('change',function(){h.classList.remove('gaveta');est()});
var ba=document.getElementById('abrir-ajuda'),pa=document.getElementById('ajuda-tela');
function alternar(){var abrir=pa.hidden;pa.hidden=!abrir;ba.setAttribute('aria-expanded',abrir?'true':'false');
if(abrir){pa.scrollIntoView({block:'nearest'});pa.focus()}else ba.focus()}
if(ba&&pa){ba.addEventListener('click',alternar);var f=document.getElementById('fechar-ajuda');if(f)f.addEventListener('click',alternar)}
est()})();
</script>"""

# Faixa vermelha fixa quando a coleta espera uma pessoa (captcha do TRT, login do jus.br). Atualiza sozinha.
SCRIPT_ATENCAO = """<script>
(function(){var f=document.getElementById('atencao');if(!f)return;
function ler(){fetch('/atencao.json',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
if(d&&d.texto){f.textContent=d.texto;f.style.display='block'}else{f.style.display='none'}}).catch(function(){})}
setInterval(ler,5000)})();
</script>"""


def faixa_de_atencao():
    """A faixa vermelha (escondida quando não há pedido). O texto inicial vem do servidor; o script a mantém em dia."""
    import atencao
    registro = atencao.atual()
    texto = html.escape(atencao.texto_da_faixa(registro)) if registro else ""
    return (f"<div id='atencao' role='alert' style='display:{'block' if registro else 'none'}'>{texto}</div>"
            + SCRIPT_ATENCAO)


# Ícones de linha (24x24, traço 1,75), embutidos: o painel não carrega nada de fora.
ICONES = {
    "inicio": "<path d='M3 10.5 12 3l9 7.5'/><path d='M5 9.5V20h5v-6h4v6h5V9.5'/>",
    "fluxo": "<path d='M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z'/><path d='M19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7z'/>",
    "atualizar": "<path d='M20 11a8 8 0 0 0-14.5-4.5L4 8'/><path d='M4 4v4h4'/><path d='M4 13a8 8 0 0 0 14.5 4.5L20 16'/><path d='M20 20v-4h-4'/>",
    "revisar": "<path d='M9 11l3 3 8-8'/><path d='M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9'/>",
    "planilha": "<rect x='3' y='4' width='18' height='16' rx='2'/><path d='M3 10h18M3 15h18M9 4v16'/>",
    "cadastro": "<circle cx='9' cy='8' r='3.5'/><path d='M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6'/><path d='M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.3c2 .7 3 2.6 3 5.7'/>",
    "pedidos": "<path d='M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z'/><path d='M14 3v5h5M9 13h6M9 17h6'/>",
    "entregas": "<path d='M21 3 10 14'/><path d='M21 3l-6.5 18-3.5-7.5L3.5 10z'/>",
    "migracao": "<path d='M4 8h14l-3.5-3.5M20 16H6l3.5 3.5'/>",
    "perfil": "<circle cx='12' cy='8' r='4'/><path d='M4 21c0-4 3.6-7 8-7s8 3 8 7'/>",
    "ia": "<rect x='6' y='6' width='12' height='12' rx='2'/><path d='M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4'/><path d='M10 10h4v4h-4z'/>",
    "config": "<path d='M4 6h9M19 6h1M4 12h3M13 12h7M4 18h9M19 18h1'/><circle cx='16' cy='6' r='2'/><circle cx='10' cy='12' r='2'/><circle cx='16' cy='18' r='2'/>",
    "acesso": "<circle cx='8' cy='15' r='4'/><path d='M11 12 20 3M16 7l3 3'/>",
    "menu": "<path d='M4 6h16M4 12h16M4 18h16'/>",
    "busca": "<circle cx='11' cy='11' r='7'/><path d='m20 20-4-4'/>",
    "ajuda": "<circle cx='12' cy='12' r='9'/><path d='M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.8M12 17.2h.01'/>",
    "seta": "<path d='m6 9 6 6 6-6'/>",
}


def _icone(nome, tam=22):
    return (f"<svg class='ic' width='{tam}' height='{tam}' viewBox='0 0 24 24' fill='none' stroke='currentColor' "
            f"stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true' focusable='false'>"
            f"{ICONES[nome]}</svg>")


# Símbolo do escritório (estaticos/favicon-chc.svg), embutido.
SIMBOLO_CHC = (
    "<path fill-rule='evenodd' d='M167.238 0v237.018h67.472V0h-67.472Z'/>"
    "<path fill-rule='evenodd' d='M67.475 84.79C30.188 84.79 0 115.42 0 153.213v15.383c0 37.793 30.188 68.422 67.475 68.422V84.79Z'/>"
    "<path fill-rule='evenodd' d='M83.603 84.79c0 37.793 30.221 68.423 67.505 68.423V84.79H83.603Z'/>"
    "<path fill-rule='evenodd' d='M250.875 84.79v152.228h67.471v-84.044c-.135-37.692-30.289-68.184-67.471-68.184Z'/>"
    "<path fill-rule='evenodd' d='M83.603 168.596v68.422c37.283 0 67.505-30.629 67.505-68.422H83.603Z'/>"
    "<path fill-rule='evenodd' d='M401.983 84.79c-37.284 0-67.505 30.63-67.505 68.423v15.383c0 37.793 30.221 68.422 67.505 68.422V84.79Z'/>"
    "<path fill-rule='evenodd' d='M418.111 84.79c0 37.793 30.225 68.423 67.475 68.423V84.79h-67.475ZM418.111 168.596v68.422c37.287 0 67.475-30.629 67.475-68.422h-67.475Z'/>")


def _favicon():
    from urllib.parse import quote
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 -124 486 486'><rect x='0' y='-124' width='486' height='486' rx='90' fill='#fff'/>"
           f"<g fill='#163758'>{SIMBOLO_CHC}</g></svg>")
    return "data:image/svg+xml," + quote(svg, safe="")


# (chave, endereço, rótulo). A ordem é a da barra lateral; GRUPOS separa os blocos com um traço fino.
SUBABAS = [("inicio", "/inicio", "Início"),
           ("fluxo", "/fluxo", "Assistente"), ("atualizar", "/atualizar", "Atualizar"), ("revisar", "/", "Revisar"),
           ("planilha", "/planilha", "Planilha"),
           ("cadastro", "/cadastro", "Clientes e processos"), ("pedidos", "/pedidos", "Pedidos"),
           ("entregas", "/entregas", "Entregas"), ("migracao", "/migracao", "Migrar de modelo"),
           ("perfil", "/perfil", "Perfil"), ("ia", "/ia", "IA"), ("config", "/config", "Configuração")]
GRUPOS = {"inicio": 0, "fluxo": 0, "atualizar": 0, "revisar": 0, "planilha": 0,
          "cadastro": 1, "pedidos": 1, "entregas": 1, "migracao": 1,
          "perfil": 2, "ia": 2, "config": 2}
NOME_DO_PAINEL = "Relatório de Andamentos"


def _ia_local_pronta():
    """O motor local (Ollama) está instalado? Verificação barata (sem rede nem subprocesso), usada em todo cabeçalho; o
    detalhe (modelo baixado) fica na tela /ia. Qualquer erro vale 'não': o cabeçalho nunca quebra a tela."""
    try:
        import ia_local
        return ia_local.ollama_exe() is not None
    except Exception:
        return False


def cabecalho(ativa, titulo=NOME_DO_PAINEL):
    """Devolve o HTML da página até abrir o <main>; cada tela escreve o conteúdo e o navegador fecha o resto."""
    import acesso
    pronto = all(acesso.situacao().values())
    projetos = comum.projetos()
    tem_relatorio = bool(comum.PROJETO)
    nome_atual = next((d.get("nome", s) for s, d in projetos if s == comum.PROJETO), "")
    ver = versao()
    e = html.escape

    # barra lateral: itens agrupados, ícone de linha, rótulo no title/aria-label e no balão ao passar o mouse
    itens, grupo_anterior = [], None
    ia_pronta = _ia_local_pronta()
    for chave, url, rotulo in (SUBABAS if tem_relatorio else []):
        if chave == "ia" and not ia_pronta:
            rotulo = "IA (instalar a IA local)"
        if grupo_anterior is not None and GRUPOS.get(chave) != grupo_anterior:
            itens.append("<div class='sep' role='separator'></div>")
        grupo_anterior = GRUPOS.get(chave)
        eh_ativa = chave == ativa
        itens.append(f"<a class='item{' ativo' if eh_ativa else ''}' href='{url}' title='{e(rotulo, quote=True)}' "
                     f"aria-label='{e(rotulo, quote=True)}'{' aria-current=page' if eh_ativa else ''}>"
                     f"{_icone(chave)}{'' if chave != 'ia' or ia_pronta else '<span class=ponto></span>'}<span class='rot'>{e(rotulo)}</span></a>")
    rotulo_acesso = f"Acesso e escritório {'✓' if pronto else '(configurar)'}"
    acesso_ativo = ativa == "acesso"
    rodape = (f"<div class='rodape-lateral'><a class='item{' ativo' if acesso_ativo else ''}' href='/acesso' "
              f"title='{e(rotulo_acesso, quote=True)}' aria-label='{e(rotulo_acesso, quote=True)}'{' aria-current=page' if acesso_ativo else ''}>"
              f"{_icone('acesso')}<span class='ponto{' ok' if pronto else ''}'></span><span class='rot'>{e(rotulo_acesso)}</span></a>"
              f"{('<div class=versao>versão ' + e(ver) + '</div>') if ver else ''}</div>")
    lateral = (f"<aside class='lateral' id='lateral' aria-label='Menu principal'>"
               f"<a class='marca-chc' href='{'/inicio' if tem_relatorio else '/acesso'}' title='CHC Advocacia' aria-label='CHC Advocacia'>"
               f"<svg viewBox='0 0 486 238' fill='currentColor' aria-hidden='true' focusable='false'>{SIMBOLO_CHC}</svg>"
               f"<span class='nome'>{NOME_DO_PAINEL}<small>CHC Advocacia</small></span></a>"
               f"<nav aria-label='Telas do painel'>{''.join(itens)}</nav>{rodape}</aside>")

    # barra do topo
    rodando = (f"<a class='tarefa' href='/atualizar' title='{e('tarefa em andamento: ' + TAREFA['descricao'], quote=True)}'>"
               f"tarefa em andamento: {e(TAREFA['descricao'])}</a>" if _tarefa_rodando() else "")
    lista = "".join(f"<a href='/p/{e(s, quote=True)}'{' aria-current=true' if s == comum.PROJETO else ''}>{e(d.get('nome', s))}</a>"
                    for s, d in projetos)
    menu_relatorios = (f"<details class='rel'><summary aria-label='Escolher o relatório. Atual: {e(nome_atual or 'nenhum', quote=True)}'>"
                       f"<span class='pre'>Relatório:</span> <b>{e(nome_atual or 'nenhum')}</b>{_icone('seta', 16)}</summary>"
                       f"<div class='rel-lista'>{lista}<a class='novo' href='/novo'>+ Novo relatório</a></div></details>")
    busca = (f"<form class='busca' role='search' action='/busca' method='get'>{_icone('busca', 18)}"
             f"<input type='search' name='q' placeholder='Buscar cliente ou processo' aria-label='Buscar cliente ou processo' autocomplete='off'></form>"
             if tem_relatorio else "")
    topo = (f"<header class='topo'><button type='button' class='ico' id='alternar-lateral' aria-controls='lateral' aria-expanded='false' "
            f"aria-label='Mostrar ou recolher o menu' title='Mostrar ou recolher o menu'>{_icone('menu')}</button>"
            f"<span class='nome-app'>{NOME_DO_PAINEL}{('<small>versão ' + e(ver) + '</small>') if ver else ''}</span>"
            f"{busca}<div class='topo-fim'>{rodando}{menu_relatorios}"
            f"<button type='button' class='pilula' id='abrir-ajuda' aria-expanded='false' aria-controls='ajuda-tela'>"
            f"{_icone('ajuda', 18)}<span class='txt'>Ajuda</span></button></div></header>")

    rotulo_da_tela = next((r for c, _, r in SUBABAS if c == ativa), "Acesso e escritório" if acesso_ativo else titulo)
    ajuda_da_tela = (f"<section class='painel-ajuda' id='ajuda-tela' tabindex='-1' hidden aria-label='Como usar esta tela'>"
                     f"<h2>Como usar esta tela</h2><p>Você está em <b>{e(rotulo_da_tela)}</b>.</p><ul>"
                     f"<li>Os ícones da barra à esquerda levam a cada etapa. Passe o mouse (ou use a tecla Tab) para ver o nome; "
                     f"o botão de três linhas, no alto, deixa os nomes sempre visíveis.</li>"
                     f"<li>O botão <b>(i)</b> ao lado de botões e campos explica o que acontece ao usá-los.</li>"
                     f"<li>O menu <b>Relatório</b> escolhe com qual relatório você está trabalhando.</li>"
                     f"<li>A busca procura clientes e processos.</li></ul>"
                     f"<p><a href='/inicio'>Ir para o Início</a> <button type='button' class='pilula' id='fechar-ajuda' style='margin-left:12px'>Fechar</button></p></section>")

    titulo_da_aba = NOME_DO_PAINEL if titulo.strip() in ("", NOME_DO_PAINEL) else f"{titulo.strip()} · {NOME_DO_PAINEL}"
    avisos = ("" if pronto or acesso_ativo else
              "<div class='alerta aviso-topo'>Falta configurar o acesso (senha do certificado e "
              "código do autenticador). <a href='/acesso'>Configurar agora</a></div>")
    return (f"<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{e(titulo_da_aba)}</title>"
            f"<link rel='icon' type='image/svg+xml' href=\"{_favicon()}\">{ESTILO}{SCRIPT_LATERAL_INICIAL}<body>"
            f"<a class='pular' href='#conteudo'>Ir para o conteúdo</a>"
            f"{faixa_de_atencao()}{SCRIPT_AJUDA}"
            f"<div class='app'>{lateral}<div class='veu' aria-hidden='true'></div><div class='corpo'>{topo}{ajuda_da_tela}"
            f"{aviso_de_painel_desatualizado()}{avisos}{SCRIPT_CASCO}<main id='conteudo'>")


def ajuda(texto, titulo="O que é isto?"):
    """Botãozinho (i) com a explicação de um botão, campo ou seção. Vai logo ao lado do elemento explicado:

        f"<button>Atualizar</button>{ajuda('Baixa os andamentos novos dos processos cadastrados.')}"

    Abre ao passar o mouse, ao focar (Tab) e ao clicar/tocar; fecha com Esc ou clicando fora. O texto é
    escapado aqui (passe texto puro, sem HTML). Estilo: `.ajuda` e `.ajuda-balao` em ESTILO; comportamento:
    SCRIPT_AJUDA, que o cabeçalho já inclui."""
    t = html.escape(texto, quote=True)
    return (f"<span class='ajuda' tabindex='0' role='button' aria-label='{html.escape(titulo, quote=True)}: {t}' "
            f"data-ajuda='{t}'>i</span>")


# O balão é um único elemento criado na primeira vez e posicionado pelo script: fica sempre dentro da janela
# (desliza para dentro perto das bordas e vira para cima quando falta espaço embaixo).
SCRIPT_AJUDA = """<script>
(function(){var b=null,aberto=null,atual=null;
function balao(){if(!b){b=document.createElement('div');b.className='ajuda-balao';b.setAttribute('role','tooltip');b.hidden=true;document.body.appendChild(b)}return b}
function pos(el){var t=balao();t.textContent=el.getAttribute('data-ajuda')||'';t.hidden=false;t.style.left='0px';t.style.top='0px';
var r=el.getBoundingClientRect(),w=t.offsetWidth,h=t.offsetHeight,vw=document.documentElement.clientWidth,vh=window.innerHeight,m=8;
var cx=r.left+r.width/2,x=Math.max(m,Math.min(cx-w/2,vw-w-m));
var abaixo=r.bottom+10+h<=vh-m||r.top-10-h<m,y=abaixo?r.bottom+10:r.top-10-h;
t.classList.toggle('acima',!abaixo);t.style.left=x+'px';t.style.top=y+'px';
t.style.setProperty('--seta',Math.max(14,Math.min(cx-x,w-14))+'px')}
function mostrar(el){atual=el;pos(el)}
function esconder(){atual=null;if(b)b.hidden=true}
function fechar(){if(aberto){aberto.classList.remove('aberta');aberto=null}esconder()}
function abrir(el){if(aberto&&aberto!==el)aberto.classList.remove('aberta');el.classList.add('aberta');aberto=el;mostrar(el)}
function de(e){return e.target.closest&&e.target.closest('.ajuda')}
document.addEventListener('mouseover',function(e){var a=de(e);if(a)mostrar(a)});
document.addEventListener('mouseout',function(e){var a=de(e);if(a&&a!==aberto)esconder();else if(a&&aberto)mostrar(aberto)});
document.addEventListener('focusin',function(e){var a=de(e);if(a)mostrar(a)});
document.addEventListener('focusout',function(e){var a=de(e);if(a&&a!==aberto)esconder()});
document.addEventListener('click',function(e){var a=de(e);
if(a){e.preventDefault();e.stopPropagation();aberto===a?fechar():abrir(a)}else fechar()});
document.addEventListener('keydown',function(e){if(e.key==='Escape')fechar();
if((e.key==='Enter'||e.key===' ')&&e.target.classList&&e.target.classList.contains('ajuda')){e.preventDefault();
aberto===e.target?fechar():abrir(e.target)}});
window.addEventListener('resize',function(){if(atual)pos(atual)});
window.addEventListener('scroll',function(){if(atual)pos(atual)},true);
})();
</script>"""


def _msg():
    return f"<div class='msg'>{html.escape(request.args['msg'])}</div>" if request.args.get("msg") else ""


def _ir(caminho, msg=""):
    from urllib.parse import quote
    return redirect(caminho + (("&" if "?" in caminho else "?") + "msg=" + quote(msg) if msg else ""))


def criar_token_ok(TOKEN):
    """O `token_ok` que as telas chamam no início de cada POST."""
    def token_ok():
        if request.form.get("token") != TOKEN:
            abort(403)
    return token_ok


def _dentro(base, caminho):
    try:
        Path(caminho).resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def versao():
    """Texto do arquivo VERSAO (ex.: '2.0.0-beta2'); vazio se não existir. A variável RELATORIO_VERSAO a sobrepõe
    (os testes fixam um valor para o cabeçalho não mudar a cada versão)."""
    if "RELATORIO_VERSAO" in os.environ:
        return os.environ["RELATORIO_VERSAO"]
    try:
        return (comum.RAIZ / "VERSAO").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


VERSAO_CARREGADA = versao()     # a versão do programa que ESTE painel carregou ao abrir


def aviso_de_painel_desatualizado():
    """Se o arquivo VERSAO mudou depois que o painel abriu (pacote novo copiado por cima com o painel ainda aberto), o
    painel segue rodando o código ANTIGO e o número da versão no topo mente. Devolve o aviso, ou ''."""
    atual = versao()
    if atual == VERSAO_CARREGADA:
        return ""
    return ("<div class='alerta aviso-topo forte'>Reinicie o painel: o programa "
            f"foi atualizado para a versão {html.escape(atual or '?')}, mas este painel ainda está rodando a versão "
            f"{html.escape(VERSAO_CARREGADA or '?')}. Feche a janela do Terminal do painel e abra o <b>Abrir painel.command</b> de novo.</div>")


def _tarefa_rodando():
    return bool(TAREFA) and TAREFA["proc"].poll() is None


def coleta_em_andamento_em():
    """Slug do relatório em que a coleta do Assistente está rodando agora, ou None. A coleta roda numa thread deste
    processo e usa o relatório "ativo" (`comum.PROJETO`, global): trocar de relatório no meio gravaria andamentos no
    relatório errado. Por isso a troca fica bloqueada enquanto a coleta roda."""
    try:
        from painel import assistente
        return assistente.EXEC.get("slug") if assistente.execucao_rodando() else None
    except Exception:
        return None


def registrar(app, TOKEN, cabecalho, token_ok):
    """Registra o que vale para todas as telas: a escolha do relatório ativo."""
    @app.before_request
    def escolher_projeto():
        """O relatório ativo vem do cookie; sem relatório nenhum, só a tela de criar."""
        slug = request.cookies.get("projeto")
        disponiveis = [s for s, _ in comum.projetos()]
        rodando = coleta_em_andamento_em()
        if rodando and rodando in disponiveis:
            slug = rodando                  # coleta em andamento: o relatório não muda até terminar
        if slug in disponiveis and slug != comum.PROJETO:
            comum.usar_projeto(slug)
        primeiro_uso = ("/novo", "/acesso", "/tarefa", "/atualizar", "/interromper", "/atencao.json", "/versao.json", "/ia")
        # o assistente e a migração de modelo criam o primeiro relatório: ficam liberados sem relatório
        if not disponiveis and request.path not in primeiro_uso and not request.path.startswith(("/fluxo", "/migracao", "/acesso")):
            return redirect("/novo")

    @app.get("/versao.json")
    def versao_json():
        """Para o lançador (abrir_painel.py): qual versão ESTE servidor carregou, qual está no disco e se há trabalho
        em andamento (nesse caso o lançador não reinicia o servidor)."""
        return {"carregada": VERSAO_CARREGADA, "arquivo": versao(), "coleta": bool(coleta_em_andamento_em()),
                "tarefa": _tarefa_rodando()}

    @app.get("/atencao.json")
    def atencao_json():
        """O que a faixa vermelha mostra agora ({} quando ninguém é esperado)."""
        import atencao
        from flask import jsonify
        registro = atencao.atual()
        resposta = jsonify({**registro, "texto": atencao.texto_da_faixa(registro)} if registro else {})
        resposta.headers["Cache-Control"] = "no-store"
        return resposta
