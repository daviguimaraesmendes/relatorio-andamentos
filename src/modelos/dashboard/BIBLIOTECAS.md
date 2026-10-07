# Bibliotecas JavaScript embutidas nos dashboards

Os dashboards (modelo C) são arquivos `.html` **autônomos e offline**: nada é carregado de CDN. As duas
bibliotecas abaixo são copiadas para dentro de cada HTML gerado por `escritores/dashboard.py`.
Os arquivos desta pasta são cópias **sem alteração** dos arquivos publicados no cdnjs (versões fixas).

| Arquivo | Biblioteca | Versão | Licença | Origem |
| --- | --- | --- | --- | --- |
| `xlsx.full.min.js` | SheetJS Community Edition (leitura do `.xlsx` no navegador) | 0.18.5 | Apache-2.0 | https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js |
| `chart.umd.min.js` | Chart.js (gráficos) | 4.4.1 | MIT | https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js |

Baixados em 07/10/2026.

## Integridade

SHA-256 dos arquivos desta pasta (conferido por `dashboard.verificar_bibliotecas()` a cada geração):

```
c9506197caf809a075b6dee1da0d36fb19da7158ffe8a88e7b0c96c5d8623c99  xlsx.full.min.js
81ffafe13c37e1b25793b020d446f4d9739b949dadb7f9f79d709a0cad781c2f  chart.umd.min.js
```

SHA-512 em formato SRI, idêntico ao que o cdnjs publica para esses dois arquivos (conferido em 07/10/2026):

```
xlsx.full.min.js   sha512-r22gChDnGvBylk90+2e/ycr3RVrDi8DIOkIGNhJlKfuyQM4tIRAI062MaV8sfjQKYVGjOBaZBOA87z+IhZE9DA==
chart.umd.min.js   sha512-CQBWl4fJHWbryGE+Pc7UAxWMUMNMWzWxF4SQo9CgkJIN1kx6djDQZjh3Y8SZ1d+6I+1zze6Z7kHXO7q3UyZAWw==
```

## Observações

- O texto das bibliotecas contém endereços `http://...` (identificadores de espaço de nomes XML do SheetJS,
  como `schemas.openxmlformats.org`). São apenas cadeias de texto usadas para interpretar o `.xlsx`; a
  biblioteca **não faz requisição de rede**. Por isso, ao procurar referências externas no HTML final, o
  teste ignora os blocos `<script data-biblioteca>`.
- No modo `embutido` o SheetJS não é incluído (os dados já vão dentro da página); só o Chart.js.
- Para atualizar uma biblioteca: baixe a nova versão fixa do cdnjs, grave aqui, atualize esta tabela e os
  hashes em `escritores/dashboard.py` (constante `BIBLIOTECAS`) e rode `tests/test_dashboard.py`.
- Sem rede e sem os arquivos desta pasta, `dashboard.gravar` devolve um aviso de erro
  (`bibliotecas_ausentes`) em vez de gerar uma página que dependa de CDN.
- Fontes: o HTML usa a pilha de fontes do sistema (sem Google Fonts nem arquivos de fonte embutidos).
