# SOP: Monitoramento de saldo Meta Ads

## Objetivo

Verificar os saldos das contas de anuncio dos clientes no Meta Ads e avisar no grupo quando o saldo estiver baixo.

## Regras de negocio

- Se saldo > R$200: nao envia mensagem.
- Se saldo <= R$200: envia alerta no grupo.
- Se saldo estiver proximo de R$100 (padrao <= R$120): marcar como atencao.
- Se saldo <= R$100: marcar como critico.

## Entradas

- `.env` com:
  - `META_ACCESS_TOKEN`
  - `META_BUSINESS_ID`
  - `EVOLUTION_SERVER_URL`
  - `EVOLUTION_API_KEY`
  - `EVOLUTION_INSTANCE`
  - `EVOLUTION_GROUP_ID`
  - `MAX_RETRIES`
  - `RETRY_DELAY_SECONDS`
  - `META_BALANCE_IS_CENTS` (opcional, padrao `true`)

## Ferramenta de execucao

- Script: `execution/monitorar_saldo_meta_ads.py`

## Comando manual

```bash
python execution/monitorar_saldo_meta_ads.py --alert-threshold 200 --near-threshold 120
```

## Dry-run (sem enviar no grupo)

```bash
python execution/monitorar_saldo_meta_ads.py --dry-run
```

## Agendamento na VPS (CRON)

Rodar todos os dias as 08:00 e as 18:00:

```cron
0 8,18 * * * /caminho/do/projeto/scripts/run_monitor.sh
```

## Preparacao para producao

1. Copiar `.env.example` para `.env` e preencher.
2. Rodar `chmod +x scripts/*.sh`.
3. Rodar `./scripts/setup_vps.sh`.
4. Rodar `./scripts/install_cron.sh`.
5. Verificar logs em `.tmp/monitor_meta_ads.log`.

## Saida esperada

- Log em JSON com total de contas encontradas e total abaixo de R$200.
- Mensagem no grupo apenas quando houver ao menos uma conta com saldo <= R$200.

## Self-annealing

Se falhar:

1. Ler erro da API do Meta ou da Evolution.
2. Corrigir script.
3. Reexecutar em `--dry-run` antes do modo normal.
4. Atualizar esta diretiva com o aprendizado.
