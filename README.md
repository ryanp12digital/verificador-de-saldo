# Verificador de Saldo

Projeto inicializado com arquitetura de 3 camadas para separar:

- diretivas (o que fazer),
- orquestracao (decisao),
- execucao deterministica (como fazer).

## Estrutura

- `directives/`: SOPs em Markdown
- `execution/`: scripts Python determinísticos
- `web/`: dashboard HTML/CSS/JS (servida pelo Flask)
- `config/`: JSONs de contas (fallback quando nao ha Postgres)
- `.tmp/`: arquivos temporarios e regeneraveis
- `.env`: variaveis de ambiente

## Como comecar

1. Crie e ative um ambiente virtual Python.
2. Instale dependencias:

   - `pip install -r requirements.txt`

3. Copie `.env.example` para `.env` e ajuste as variaveis.
4. Script base (legado):

   - `python execution/verificar_saldo.py --limite 100`

## PostgreSQL (lista de contas)

Se `DATABASE_URL` **ou** `POSTGRES_HOST` + `POSTGRES_USER` + `POSTGRES_PASSWORD` + `POSTGRES_DB` estiverem definidos:

- As contas **Meta** e **Google Ads** monitoradas vêm da tabela `monitored_accounts` (criada automaticamente na primeira subida da dashboard ou ao rodar os monitors).
- Lista vazia no banco significa **nenhuma** conta monitorada (não há fallback “todas as contas” do Meta).

Importar uma vez a partir do JSON legado:

- `python execution/import_meta_json_to_db.py`

Sem Postgres, o comportamento antigo permanece: `config/meta_ad_accounts.json` e `META_ALLOWED_ACCOUNT_IDS` / `META_ACCOUNT_LABELS`.

## Dashboard (configuracao + saldos ao vivo)

1. Defina `DASHBOARD_API_TOKEN` no `.env`.
2. Na raiz do repositorio:

   - `python execution/dashboard_server.py`

3. Abra `http://127.0.0.1:5050` (ou `DASHBOARD_HOST` / `DASHBOARD_PORT`). Informe o token na tela; ele fica salvo no `localStorage` do navegador.

Rotas da API (header `Authorization: Bearer <DASHBOARD_API_TOKEN>`):

- `GET/PUT /api/accounts/meta` e `GET/PUT /api/accounts/google`
- `GET /api/balances/meta` e `GET /api/balances/google` (usam credenciais Meta / Google do `.env`)
- `GET /api/health` (sem token)

Seguranca: por padrao o servidor escuta em `127.0.0.1`. Em VPS publica use TLS/reverse proxy e token forte.

## Automacao Meta Ads (VPS + CRON)

- Script: `execution/monitorar_saldo_meta_ads.py`
- Regra:
  - saldo `> R$200`: nao notifica
  - saldo `<= R$200`: notifica no grupo
  - destaque para "proximo de R$100" (padrao `<= R$120`)
- Dry-run:
  - `python execution/monitorar_saldo_meta_ads.py --dry-run`
- CRON de exemplo:
  - `execution/cron_meta_ads_balance.example`

## Google Ads (monitoramento)

- Script: `execution/monitorar_saldo_google_ads.py`
- Usa orcamento `account_budget` quando disponivel; contas so faturamento automatico podem retornar `indisponivel`.
- OAuth (uma vez, para obter `GOOGLE_ADS_REFRESH_TOKEN`):

  - `python execution/google_ads_setup_oauth.py`

- CRON de exemplo: `execution/cron_google_ads_balance.example`
- JSON fallback: `config/google_ad_accounts.json` (`accounts[].customer_id`, `name`)

## Producao na VPS

- Arquivos de deploy:
  - `docs/DEPLOY_VPS.md`
  - `scripts/setup_vps.sh`
  - `scripts/install_cron.sh`
  - `scripts/run_monitor.sh`
- Fluxo rapido:
  - `cp .env.example .env`
  - `chmod +x scripts/*.sh`
  - `./scripts/setup_vps.sh`
  - `./scripts/install_cron.sh`

## Deploy no EasyPanel (Dockerfile)

- Build method: `Dockerfile`
- O agendamento roda dentro do container via `supercronic`
- Variaveis obrigatorias no painel (Meta + Evolution): ver `.env.example`
- Opcional: `DASHBOARD_ENABLED=true` e `DASHBOARD_HOST=0.0.0.0` para subir a dashboard em background no mesmo container (ver `scripts/entrypoint.sh`)
- Postgres: o container precisa de rota de rede ate o host/porta do banco; passe `DATABASE_URL` ou `POSTGRES_*`

## Controle de contas por JSON (sem Postgres)

- Meta: `config/meta_ad_accounts.json` — `accounts`: `name`, `id`
- Prioridade sem Postgres:
  1. JSON em `META_ACCOUNTS_JSON_PATH`
  2. Fallback para `META_ALLOWED_ACCOUNT_IDS` e `META_ACCOUNT_LABELS`

## Fluxo recomendado

1. Leia uma diretiva em `directives/`.
2. Execute o script correspondente em `execution/`.
3. Em caso de erro: corrija o script, reteste e atualize a diretiva com o aprendizado.
