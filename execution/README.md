# Camada de Execucao

Scripts nesta pasta devem ser:

- deterministicos,
- testaveis,
- orientados a entrada/saida clara.

## Script base

- `verificar_saldo.py`: compara saldo atual com limite minimo e devolve resultado em JSON.
- `monitorar_saldo_meta_ads.py`: consulta saldos Meta Ads e envia alerta via Evolution quando saldo <= limite.
- `monitorar_saldo_google_ads.py`: consulta Google Ads (`account_budget`) e envia alerta no mesmo padrao.

## Modulos compartilhados

- `db.py`: Postgres (`monitored_accounts`) quando `DATABASE_URL` ou `POSTGRES_*` estao definidos.
- `accounts_config.py`: resolve lista de contas (Postgres ou JSON / env legado).
- `meta_ads_balance.py`: Graph API Meta (fetch, parse de saldo).
- `google_ads_balance.py`: GAQL Google Ads (melhor esforco).
- `evolution_notify.py`: envio de mensagem ao grupo Evolution.
- `http_util.py`: HTTP com retentativas.

## Dashboard

- `dashboard_server.py`: Flask — estaticos em `../web/` e API `/api/*` (token `DASHBOARD_API_TOKEN`).
- `import_meta_json_to_db.py`: importa `config/meta_ad_accounts.json` para o Postgres.
- `google_ads_setup_oauth.py`: fluxo OAuth para gerar `GOOGLE_ADS_REFRESH_TOKEN`.

## Agendamento

- `cron_meta_ads_balance.example`: CRON Meta.
- `cron_google_ads_balance.example`: CRON Google Ads.

## Observacao de producao

- Em VPS, prefira agendar `scripts/run_monitor.sh` em vez de chamar Python direto.
- Com Postgres ativo, cadastre contas pela dashboard ou importe o JSON antes de depender do CRON.
