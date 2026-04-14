# Camada de Execucao

Scripts nesta pasta devem ser:

- deterministicos,
- testaveis,
- orientados a entrada/saida clara.

## Script base

- `verificar_saldo.py`: compara saldo atual com limite minimo e devolve resultado em JSON.
- `monitorar_saldo_meta_ads.py`: consulta saldos das contas do Meta Ads e envia alerta no grupo via Evolution API quando saldo <= R$200.

## Agendamento

- `cron_meta_ads_balance.example`: linha de CRON para execucao as 08:00 e 18:00.

## Observacao de producao

- Em VPS, prefira agendar `scripts/run_monitor.sh` em vez de chamar Python direto.
