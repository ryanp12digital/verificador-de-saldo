# Verificador de Saldo

Projeto inicializado com arquitetura de 3 camadas para separar:

- diretivas (o que fazer),
- orquestracao (decisao),
- execucao deterministica (como fazer).

## Estrutura

- `directives/`: SOPs em Markdown
- `execution/`: scripts Python determinísticos
- `.tmp/`: arquivos temporarios e regeneraveis
- `.env`: variaveis de ambiente

## Como comecar

1. Crie e ative um ambiente virtual Python.
2. Instale dependencias:

   - `pip install -r requirements.txt`

3. Ajuste as variaveis no `.env`.
4. Execute o script base:

   - `python execution/verificar_saldo.py --limite 100`

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

## Fluxo recomendado

1. Leia uma diretiva em `directives/`.
2. Execute o script correspondente em `execution/`.
3. Em caso de erro: corrija o script, reteste e atualize a diretiva com o aprendizado.
