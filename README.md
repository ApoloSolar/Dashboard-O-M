# Painel O&M — Dashboard de Manutenção (Odoo)

Dashboard HTML que mostra as ordens de serviço do módulo **Projeto** do Odoo
(renomeado para **O&M**). Os dados são buscados na API do Odoo por um
**GitHub Action agendado**, que gera o arquivo `docs/data.json`. O
**GitHub Pages** serve o dashboard, que lê esse JSON.

A chave de API fica guardada em **GitHub Secrets** (criptografada) e nunca
aparece no código nem na página publicada.

```
├── .github/workflows/update-data.yml   # roda o fetch e commita o data.json
├── scripts/fetch_odoo.py               # busca os dados no Odoo (só stdlib)
└── docs/
    ├── index.html                      # o dashboard
    └── data.json                       # gerado pelo Action (vem com dados de exemplo)
```

## Como a atualização funciona

1. O Action roda de hora em hora (e também pode ser disparado manualmente).
2. Ele executa `scripts/fetch_odoo.py`, que conecta no Odoo via XML-RPC,
   lê as tarefas do `project.task` e resolve os nomes dos responsáveis.
3. Grava `docs/data.json` e faz commit se algo mudou.
4. O GitHub Pages publica a página; ao abrir, ela lê o `data.json` mais recente.

Não é tempo real a cada clique — é atualização automática no intervalo agendado.
Para trocar o intervalo, edite o `cron` em `.github/workflows/update-data.yml`.

## Configuração (uma vez)

### 1. Suba os arquivos para um repositório no GitHub
Crie um repositório novo e envie todos estes arquivos para a branch `main`.

### 2. Cadastre os Secrets
No repositório: **Settings → Secrets and variables → Actions → New repository secret**.
Crie os quatro:

| Secret          | Exemplo                          |
|-----------------|----------------------------------|
| `ODOO_URL`      | `https://apolo-solar2.odoo.com`  |
| `ODOO_DB`       | nome do seu banco de dados       |
| `ODOO_USERNAME` | seu login (e-mail)               |
| `ODOO_API_KEY`  | sua chave de API do Odoo         |

### 3. Ative o GitHub Pages
**Settings → Pages → Build and deployment**: em *Source* escolha **Deploy from a branch**,
selecione a branch `main` e a pasta **`/docs`**. Salve.
O endereço fica algo como `https://SEU-USUARIO.github.io/NOME-DO-REPO/`.

### 4. Gere os dados pela primeira vez
Vá em **Actions → Atualizar dados do Odoo → Run workflow**.
Ao terminar, o `docs/data.json` estará atualizado com os dados reais.

## Rodar localmente (teste)

```bash
export ODOO_URL="https://apolo-solar2.odoo.com"
export ODOO_DB="seu_banco"
export ODOO_USERNAME="voce@email.com"
export ODOO_API_KEY="sua_api_key"

python scripts/fetch_odoo.py            # gera docs/data.json
cd docs && python -m http.server 8000   # abra http://localhost:8000
```

## Personalização

- **Prioridades**: em `docs/index.html`, ajuste `PRIO_LABELS` com os nomes reais
  dos níveis (o campo parece ser customizado, com 4 níveis).
- **Estágios**: o objeto `STAGE_META` define cor e ordem de cada estágio pelo ID.
  Se você criar/renomear estágios no Odoo, ajuste aqui.
- **Intervalo de atualização**: `cron` no arquivo do workflow.

## ⚠️ Sobre privacidade dos dados

O GitHub Pages publica a página (e o `data.json`) de forma **pública**, mesmo que
o repositório seja privado. Se as informações de manutenção forem sensíveis,
**não** use o GitHub Pages público — nesse caso o caminho é hospedar em ambiente
com controle de acesso, ou usar um proxy serverless com autenticação. A chave de
API, essa sim, permanece protegida nos Secrets em qualquer cenário.
