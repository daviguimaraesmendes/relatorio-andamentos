# Identidade visual do painel

Referência dada por Davi: o layout de um painel de gestão jurídica (captura de tela "ADVO") + as cores e o
logotipo do escritório (https://chcadvocacia.adv.br/). O painel **não carrega nada de endereços externos**
(sem Google Fonts, sem CDN, sem imagens remotas): tudo vai embutido (CSS, SVG inline ou `data:`).

## Layout (da referência)

- **Barra lateral esquerda**, estreita (cerca de 80 px) só com ícones de linha (traço fino, 22 px), fundo azul-marinho
  escuro. Topo: marca do escritório. Item ativo: quadrado arredondado (raio 10 px) **preenchido em verde-água
  (teal)**, ícone branco. Rodapé da barra: atalho e avatar/iniciais do usuário. Em tela estreita (celular/janela
  pequena) a barra vira menu recolhível (botão "hambúrguer" na barra do topo). Cada ícone tem rótulo (`title` e
  `aria-label`) e, ao passar o mouse, mostra o nome da tela.
- **Barra do topo**: branca, 60 px, linha inferior fina. À esquerda o botão hambúrguer; à direita um campo de busca
  em pílula, sino de avisos (com bolinha vermelha de contagem) e um botão de contorno "Feedback" (aqui: "Ajuda").
- **Área de conteúdo**: fundo cinza muito claro; cartões brancos com borda fina, **raio 14 px** e sombra quase
  imperceptível; espaço generoso (24 px entre cartões).
- **Cartão de abertura (hero)**: faixa grande com degradê azul claro, raio 20 px. Acima do título, uma linha de
  rótulo em **caixa alta com espaçamento entre letras** ("BOA NOITE · QUINTA-FEIRA, 08 DE OUTUBRO"), título grande
  (34 px, peso 700, quase preto), subtítulo de 16 px, uma frase em itálico cinza e uma pílula verde de contorno
  ("19 concluídas esta semana"). À direita, um cartão branco "RADAR IMEDIATO" com **três blocos de número**
  coloridos (âmbar "ATRASADAS", azul "HOJE", verde "7 DIAS"): número grande, rótulo em caixa alta pequena.
- **Cartões de lista**: título 18 px peso 600, subtítulo cinza 14 px, divisor fino, conteúdo; botão pílula de
  contorno ("Ver todas") no canto superior direito; estado vazio com texto cinza simples e amigável.
- **Botões**: pílula (raio total) para ações secundárias, de contorno; principal preenchido em teal.
- **Tipografia**: família sans moderna tipo Inter; pilha `Inter, "SF Pro Text", -apple-system, "Segoe UI", system-ui,
  sans-serif` (sem baixar fonte). Rótulos pequenos em caixa alta: 11-12 px, peso 600, `letter-spacing:.12em`.

## Cores (tokens em `:root`; claro e escuro)

Da referência: barra lateral azul-marinho, item ativo teal, fundo cinza claro, cartões brancos. Do site do
escritório: azul-marinho `#163758`, cobre `#bb734d` / `#a35f3c`, cinza-azulado `#f3f5f7`, texto `#0e1620`, apoio
`#536773`, linhas `#d4dce2`.

| Token | Valor claro | Uso |
| --- | --- | --- |
| `--marinho` | `#0f2236` | fundo da barra lateral (derivado de `#163758`, mais escuro) |
| `--marinho-2` | `#163758` | hover da barra, cabeçalhos escuros |
| `--teal` | `#4fa598` | item ativo, botão principal, foco |
| `--teal-2` | `#3d8a7e` | hover do botão principal |
| `--cobre` | `#bb734d` | detalhe da marca do escritório (selos, realces, avisos de atenção suave) |
| `--tinta` | `#0e1620` | texto |
| `--suave` | `#536773` | texto secundário |
| `--linha` | `#e2e7eb` | bordas |
| `--fundo` | `#f1f3f5` | fundo da página |
| `--cartao` | `#ffffff` | cartões |
| `--hero-de` / `--hero-ate` | `#e6f0fb` / `#eef4fb` | degradê do cartão de abertura |
| `--ambar` (fundo/borda/texto) | `#fff8e1` / `#f1dfa0` / `#b45309` | atrasadas, atenção |
| `--azul` (fundo/borda/texto) | `#eaf4fe` / `#b9d8f5` / `#1d4f91` | hoje, informação |
| `--verde` (fundo/borda/texto) | `#e8f8f0` / `#b5e6cb` / `#15803d` | em dia, sucesso |
| `--perigo` | `#b91c1c` | erro, faixa de atenção, contagem do sino |

Modo escuro (`prefers-color-scheme: dark`): fundo `#0b141d`, cartões `#13202d`, linhas `#243545`, texto `#e6edf3`;
os tokens de cor acompanham (mesmos matizes, fundos translúcidos). Contraste mínimo AA em tudo.

## Marca

`src/painel/estaticos/logo-chc-white.svg` (logotipo horizontal, branco, para a barra escura) e
`favicon-chc.svg` (símbolo, para a barra estreita e para o ícone da aba). Foram copiados do site do escritório
(material do próprio escritório de Davi). Embutir no HTML (o painel não serve arquivos externos).

## Botão de ajuda (i)

Toda ação, campo e seção que não se explique sozinha ganha `ajuda("texto")` (de `painel/base.py`) ao lado: um (i)
que abre ao passar o mouse, ao focar com Tab e ao tocar/clicar. Texto em português simples, 1 a 3 frases, dizendo
**o que acontece** ao usar, **o que sai do computador** (se algo sair) e **o que não dá para desfazer** (se for o caso).
