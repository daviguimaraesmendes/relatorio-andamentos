"""Regras de confidencialidade da Fase 2: UMA fonte para o teste (`test_confidencialidade.py`) e para o
`empacotar.sh` (que roda este arquivo sobre a pasta do pacote antes de gerar o .zip).

O que é procurado, em arquivo de texto e também por dentro de .docx/.xlsx/.zip (ativos de `src/modelos/`):

- `numero_de_processo`  número CNJ (com ou sem máscara) fora do permitido: o modelo de zeros/noves e os
                         sintéticos 1234567 a 1234570 (os demais fictícios são gerados em tempo de execução);
- `nome_cadastrado`     nome de cliente/parte cadastrado NESTE computador (projetos/*/clientes.json, a carteira
                         dos projetos e o config.json: quem assina e o revisor). Só vale onde há dados reais;
- `empresa_suspeita`    "<Palavras> Ltda/S.A." com palavra que não é claramente fictícia ou genérica
                         (heurística: pode errar; para um nome fictício novo barrado, acrescente a palavra a
                         GENERICAS, ou o par (arquivo, nome) a LEGADO com justificativa);
- `documento_pessoal`   CPF, CNPJ, e-mail e telefone no formato real (placeholders conhecidos passam);
- `segredo`             chave de API, chave privada, "senha/segredo/token = '...'" com valor que não parece de teste;
- `arquivo_proibido`    certificado, config.json, carteira/clientes/eventos/fila de projeto, pasta projetos/, .env.

Também `referencias_externas(html)`: lista tudo que um HTML carregaria ou chamaria fora do computador
(script/estilo/imagem/fonte/iframe de outro domínio, `@import`, `fetch(...)` etc.). Os painéis e dashboards são
offline: o resultado esperado é vazio.

Uso pelo terminal (o `empacotar.sh` faz isto; o código de saída é 1 se houver achado grave):

    python3 tests/confidencialidade_regras.py PASTA [--raiz RAIZ_COM_projetos] [--sem-heuristica]

`--sem-heuristica` deixa `empresa_suspeita` como aviso (não derruba o pacote). Nada aqui usa rede.
"""
import hashlib
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections import namedtuple
from pathlib import Path

Achado = namedtuple("Achado", "arquivo linha tipo trecho")

# ---------------------------------------------------------------- números de processo

CNJ_MASCARA = re.compile(r"(?<!\d)\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?!\d)")
CNJ_SEM_MASCARA = re.compile(r"(?<!\d)\d{20}(?!\d)")
PREFIXOS_SINTETICOS = {"1234567", "1234568", "1234569", "1234570"}


def numero_permitido(numero):
    """O modelo (só zeros ou só noves) e os sintéticos 1234567-1234570 são os únicos números que podem estar
    em arquivo versionado. Mesma regra que o `empacotar.sh` sempre aplicou."""
    digitos = re.sub(r"\D", "", numero)
    return len(set(digitos)) == 1 and digitos[0] in "09" or digitos[:7] in PREFIXOS_SINTETICOS


# ---------------------------------------------------------------- nomes

# Palavras que, sozinhas, não identificam ninguém (fictícias, genéricas ou de ligação).
GENERICAS = {
    "exemplo", "exemplos", "ficticia", "ficticio", "ficticias", "ficticios", "teste", "testes", "modelo", "modelos",
    "razao", "social", "cliente", "clientes", "empresa", "empresas", "sua", "seu", "nome", "fulano", "beltrano",
    "ciclano", "acme", "xyz", "foo", "bar", "alfa", "beta", "gama", "delta", "epsilon", "ome", "omega",
    "comercio", "comercial", "servicos", "industria", "industrias", "banco", "construtora", "incorporadora",
    "transportes", "distribuidora", "holding", "grupo", "associacao", "cidade", "pessoa", "parte", "autora", "autor",
    "reu", "re", "de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "com", "cia", "companhia", "filial",
    "matriz", "cada", "uma", "um", "outra", "outro", "qualquer", "nova", "novo", "sem", "numero", "ltda", "sa",
    "eireli", "x", "y", "z", "primeiro", "segunda", "terceira",
    "chacara", "tomadora", "aparece", "que", "nao",
}
# Nomes já presentes no repositório antes deste teste existir, a confirmar com quem é dono do arquivo.
# Chave: (arquivo, sha1 do nome normalizado) para este arquivo não repetir o nome. Quando o nome for trocado por
# um fictício no arquivo de origem, apague a linha daqui.
LEGADO = {
    ("tests/test_pipeline.py", "c6b992f69a0f"),   # empresa citada em teste da Fase 1 (nome_bate), revisar: parece real
}

EMPRESA = re.compile(r"((?:[A-ZÀ-Ý][\wÀ-ÿ&'.\-]*[ \t]+){1,5})(?:Ltda|LTDA|S\.A\.?|S/A|EIRELI|Eireli)(?![\wÀ-ÿ])")


def sem_acento(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def _ficticio_ou_generico(nome):
    palavras = [p for p in re.split(r"[^a-z0-9]+", sem_acento(nome)) if p]
    return all(p in GENERICAS or p.isdigit() or len(p) == 1 for p in palavras)


def _hash_nome(nome):
    return hashlib.sha1(" ".join(sem_acento(nome).split()).encode()).hexdigest()[:12]


def nomes_cadastrados(raiz):
    """Nomes reais cadastrados neste computador (vazio fora do Mac do escritório): clientes e variações,
    partes contrárias/autores/réus com nome completo, quem assina e o revisor. Em minúsculas, sem acento."""
    raiz = Path(raiz)
    nomes = set()

    def juntar(texto, minimo=6):
        for parte in re.split(r"[;\n]", str(texto or "")):
            n = " ".join(sem_acento(parte).split())
            if len(n) >= minimo and not _ficticio_ou_generico(n):
                nomes.add(n)

    for arquivo in raiz.glob("projetos/*/clientes.json"):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for c in (dados.get("clientes", []) if isinstance(dados, dict) else dados):
            juntar(c.get("nome"))
            for v in c.get("variacoes", []) or []:
                juntar(v)
            primeiro = (c.get("nome") or "").split()[:1]
            if primeiro and len(primeiro[0]) > 3 and not _ficticio_ou_generico(primeiro[0]):
                nomes.add(sem_acento(primeiro[0]))      # como o empacotar.sh sempre fez (1ª palavra)
    for arquivo in raiz.glob("projetos/*/data/carteira.json"):
        try:
            itens = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for it in itens if isinstance(itens, list) else []:
            campos = {k: (v.get("valor") if isinstance(v, dict) else v) for k, v in (it.get("campos") or {}).items()}
            for chave in ("parte_contraria", "autores", "reus"):
                texto = it.get(chave) or campos.get(chave)
                for parte in re.split(r"[;\n]", str(texto or "")):
                    if len(parte.split()) >= 2:
                        juntar(parte, minimo=8)
    for caminho in (raiz / "config.json",):
        try:
            cfg = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in (cfg.get("identificadores_escritorio") or []) + [cfg.get("revisor")]:
            juntar(item)
    return nomes


# ---------------------------------------------------------------- documentos pessoais e segredos

CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
CNPJ = re.compile(r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})(?![\w\-])")
TELEFONE = re.compile(r"\(\d{2}\)[ ]?9?\d{4}-\d{4}(?!\d)")
DOMINIOS_FICTICIOS = ("example.com", "example.org", "example.net", "exemplo.com", "exemplo.com.br", "anthropic.com")
TLDS_RESERVADOS = (".test", ".invalid", ".example", ".localhost")


def _documento_ficticio(texto):
    digitos = re.sub(r"\D", "", texto)
    return len(set(digitos)) == 1 or digitos in ("12345678909", "12345678000195")


def _email_ficticio(dominio):
    dominio = dominio.lower()
    return dominio in DOMINIOS_FICTICIOS or dominio.endswith(TLDS_RESERVADOS)


def _telefone_ficticio(texto):
    return len(set(re.sub(r"\D", "", texto))) <= 2 or re.sub(r"\D", "", texto)[-8:] in ("12345678", "99999999")


SEGREDO_PREFIXADO = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-ant-[A-Za-z0-9_\-]{16,}|\bsk-[A-Za-z0-9]{32,}|\bAKIA[0-9A-Z]{16}\b|"
    r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bxox[abprs]-[A-Za-z0-9\-]{10,}|\bAIza[0-9A-Za-z_\-]{35}")
SEGREDO_ATRIBUIDO = re.compile(
    r"""["']?\b(senha|password|passwd|pin|segredo|secret|api[_\-]?key|chave[_\-]?api|authorization|bearer)\b["']?"""
    r"""\s*[:=]\s*["']([^"'\s{}$%]{8,})["']""", re.I)
# Valor com uma destas palavras é de teste (o teste de consentimento do WS-18 precisa de chaves falsas).
MARCADORES_DE_TESTE = ("falso", "falsa", "fake", "teste", "test", "exemplo", "example", "dummy", "xxx", "ficticio",
                       "ficticia", "placeholder", "mock", "simulado", "segredo-de", "chave-de", "abcd", "1234", "aaaa",
                       "jbswy3dpehpk3pxp", "sua-chave", "your", "changeme", "nao-e-real", "naoereal")


def _valor_de_teste(valor):
    v = valor.lower()
    return any(m in v for m in MARCADORES_DE_TESTE)


def _segredos(linha):
    for m in SEGREDO_PREFIXADO.finditer(linha):
        if not _valor_de_teste(m.group(0)):
            yield m.group(0)[:12] + "..."
    for m in SEGREDO_ATRIBUIDO.finditer(linha):
        if not _valor_de_teste(m.group(2)):
            yield f"{m.group(1)} = '{m.group(2)[:3]}...'"


# ---------------------------------------------------------------- arquivos proibidos

EXTENSOES_PROIBIDAS = (".pfx", ".p12", ".pem", ".key", ".jks", ".keystore", ".cer", ".crt", ".der")
NOMES_PROIBIDOS = {"config.json", "carteira.json", "clientes.json", "eventos.json", "estado_coleta.json", "fila.json",
                   "pedidos.json", ".env", "taxonomia.json"}
PASTAS_DE_DADOS_NA_RAIZ = {"projetos", "ensaio", "data", "dist"}


def arquivo_proibido(relativo):
    """Motivo (texto) se o caminho não pode ir para o repositório/pacote; None se estiver tudo bem."""
    p = Path(relativo)
    if p.parts and p.parts[0] in PASTAS_DE_DADOS_NA_RAIZ and not (p.parts[0] == "projetos" and p.name == ".gitkeep"):
        return f"pasta de dados na raiz ({p.parts[0]}/)"
    if p.suffix.lower() in EXTENSOES_PROIBIDAS:
        return "certificado ou chave"
    if p.name in NOMES_PROIBIDOS and p.parts[:1] not in (("tests",), ("docs",)) and p.parts[:2] != ("src", "modelos"):
        return "arquivo de dados ou de configuração pessoal"
    return None


# ---------------------------------------------------------------- varredura

EXTENSOES_OFFICE = (".docx", ".xlsx", ".xlsm", ".pptx", ".dotx", ".xltx", ".zip")


def texto_do_arquivo(caminho):
    """Texto para varredura: UTF-8; .docx/.xlsx/.zip viram o texto dos XML/textos internos (tags removidas)."""
    caminho = Path(caminho)
    if caminho.suffix.lower() in EXTENSOES_OFFICE:
        try:
            with zipfile.ZipFile(caminho) as z:
                partes = []
                for info in z.infolist():
                    if info.filename.endswith((".xml", ".rels", ".txt", ".json", ".csv", ".html", ".md")):
                        bruto = z.read(info.filename).decode("utf-8", "ignore")
                        partes.append(re.sub(r"<[^>]+>", " ", bruto) if info.filename.endswith((".xml", ".rels")) else bruto)
                return "\n".join(partes)
        except (zipfile.BadZipFile, OSError):
            return ""
    try:
        bruto = caminho.read_bytes()
    except OSError:
        return ""
    if b"\0" in bruto[:8192]:
        return ""
    return bruto.decode("utf-8", "ignore")


def varrer_texto(texto, arquivo="(texto)", nomes=frozenset(), heuristica=True):
    """Lista de Achado em um texto. `nomes`: saída de nomes_cadastrados()."""
    achados = []
    for n, linha in enumerate(texto.splitlines(), 1):
        for m in list(CNJ_MASCARA.finditer(linha)) + list(CNJ_SEM_MASCARA.finditer(linha)):
            if not numero_permitido(m.group(0)):
                achados.append(Achado(arquivo, n, "numero_de_processo", m.group(0)))
        for m in CPF.finditer(linha):
            if not _documento_ficticio(m.group(0)):
                achados.append(Achado(arquivo, n, "documento_pessoal", "CPF " + m.group(0)[:3] + ".***"))
        for m in CNPJ.finditer(linha):
            if not _documento_ficticio(m.group(0)):
                achados.append(Achado(arquivo, n, "documento_pessoal", "CNPJ " + m.group(0)[:2] + ".***"))
        for m in EMAIL.finditer(linha):
            if not _email_ficticio(m.group(1)):
                achados.append(Achado(arquivo, n, "documento_pessoal", "e-mail @" + m.group(1)))
        for m in TELEFONE.finditer(linha):
            if not _telefone_ficticio(m.group(0)):
                achados.append(Achado(arquivo, n, "documento_pessoal", "telefone " + m.group(0)[:4] + "***"))
        for trecho in _segredos(linha):
            achados.append(Achado(arquivo, n, "segredo", trecho))
        if nomes:
            plano = " ".join(sem_acento(linha).split())
            for nome in nomes:
                if re.search(rf"(?<![a-z0-9]){re.escape(nome)}(?![a-z0-9])", plano):
                    achados.append(Achado(arquivo, n, "nome_cadastrado", nome[:3] + "***"))
        if heuristica:
            for m in EMPRESA.finditer(linha):
                nome = m.group(1).strip()
                if not _ficticio_ou_generico(nome) and (str(arquivo).replace("\\", "/"), _hash_nome(m.group(0))) not in LEGADO:
                    achados.append(Achado(arquivo, n, "empresa_suspeita", nome))
    return achados


def varrer(raiz, arquivos=None, nomes=None, heuristica=True):
    """Varre `arquivos` (relativos à raiz; padrão: tudo sob a raiz) e devolve a lista de Achado."""
    raiz = Path(raiz)
    if arquivos is None:
        arquivos = []
        for pasta, _subpastas, nomes_dos_arquivos in os.walk(raiz):
            arquivos += [(Path(pasta) / n).relative_to(raiz) for n in nomes_dos_arquivos]
    nomes = nomes_cadastrados(raiz) if nomes is None else nomes
    achados = []
    for rel in arquivos:
        rel = Path(rel)
        motivo = arquivo_proibido(rel)
        if motivo:
            achados.append(Achado(rel.as_posix(), 0, "arquivo_proibido", motivo))
            continue
        achados += varrer_texto(texto_do_arquivo(raiz / rel), rel.as_posix(), nomes, heuristica)
    return achados


# ---------------------------------------------------------------- HTML offline

HOSTS_LOCAIS = ("localhost", "127.0.0.1", "[::1]", "0.0.0.0")
_URL = r"""(?:https?:)?//(?!(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?:[:/"'\s)]|$))"""
ATRIBUTO_DE_RECURSO = re.compile(
    rf"""(?i)\b(?:src|action|poster|data|data-src|srcset|formaction|manifest|ping)\s*=\s*["']?\s*{_URL}""")
LINK_REL = re.compile(rf"""(?i)<link\b[^>]*\bhref\s*=\s*["']?\s*{_URL}""")
LINK_NAVEGACAO = re.compile(rf"""(?i)<a\b[^>]*\bhref\s*=\s*["']?\s*{_URL}""")
CSS_URL = re.compile(rf"""(?i)url\(\s*["']?\s*{_URL}""")
CSS_IMPORT = re.compile(rf"""(?i)@import\s+(?:url\()?\s*["']?\s*{_URL}""")
JS_CHAMADA = re.compile(
    r"""(?:\b(?:fetch|importScripts|sendBeacon|WebSocket|EventSource|import)\s*\(\s*|\.open\(\s*["'][A-Za-z]+["']\s*,\s*)"""
    r"""[`"']\s*(?:https?|wss?):(?:\/\/)?(?!(?:localhost|127\.0\.0\.1))""")
SCRIPT_OU_ESTILO = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
URL_NO_TEXTO = re.compile(r"""(?:https?|wss?)://(?!(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?:[:/"'\s)<]|$))[^\s"'<>)]+""")
NAMESPACES_OK = ("http://www.w3.org/",)


def referencias_externas(html, incluir_links=True, procurar_no_texto=True):
    """Lista de textos curtos descrevendo cada referência a outro domínio em um HTML (vazia = offline).
    `incluir_links`: também conta `<a href>` externo (navegação); `procurar_no_texto`: qualquer URL http(s) fora
    de <script>/<style> que não seja do próprio computador ou namespace do W3C."""
    achados = []
    for rotulo, regra in (("recurso", ATRIBUTO_DE_RECURSO), ("<link>", LINK_REL), ("css url()", CSS_URL),
                          ("css @import", CSS_IMPORT), ("chamada em script", JS_CHAMADA)):
        achados += [f"{rotulo}: {m.group(0)[:80]}" for m in regra.finditer(html)]
    if incluir_links:
        achados += [f"link: {m.group(0)[:80]}" for m in LINK_NAVEGACAO.finditer(html)]
    if procurar_no_texto:
        fora_de_codigo = SCRIPT_OU_ESTILO.sub(" ", html)
        for m in URL_NO_TEXTO.finditer(fora_de_codigo):
            if not m.group(0).startswith(NAMESPACES_OK):
                achados.append(f"url no texto: {m.group(0)[:80]}")
    vistos, unicos = set(), []
    for a in achados:
        if a not in vistos:
            vistos.add(a)
            unicos.append(a)
    return unicos


# ---------------------------------------------------------------- linha de comando (empacotar.sh)

def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Confere confidencialidade de uma pasta (usado pelo empacotar.sh).")
    ap.add_argument("pasta")
    ap.add_argument("--raiz", help="onde ficam projetos/*/clientes.json e config.json (padrão: a própria pasta)")
    ap.add_argument("--sem-heuristica", action="store_true", help="empresa_suspeita vira aviso, não derruba")
    a = ap.parse_args(argv)
    pasta = Path(a.pasta)
    achados = varrer(pasta, nomes=nomes_cadastrados(a.raiz or pasta))
    graves = [x for x in achados if not (a.sem_heuristica and x.tipo == "empresa_suspeita")]
    for x in achados:
        if x not in graves:
            print(f"  aviso (confira): {x.arquivo}:{x.linha} {x.tipo} {x.trecho}")
    for x in graves[:60]:
        print(f"  {x.arquivo}:{x.linha} {x.tipo} {x.trecho}")
    externos = []       # HTML dos ativos: nada de domínio externo (dashboards e modelos são offline)
    for p in sorted(pasta.glob("src/modelos/**/*.html")):
        for ref in referencias_externas(p.read_text(encoding="utf-8", errors="ignore")):
            externos.append(f"  {p.relative_to(pasta).as_posix()}: referência externa ({ref})")
    for linha in externos[:30]:
        print(linha)
    return 1 if (graves or externos) else 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
