# Deploy em VPS (Producao)

## 1) Clonar o projeto

```bash
git clone <url-do-repo> verificador-de-saldo
cd verificador-de-saldo
```

## 2) Configurar variaveis

```bash
cp .env.example .env
nano .env
```

Preencha os campos obrigatorios:

- `META_ACCESS_TOKEN`
- `META_BUSINESS_ID`
- `EVOLUTION_SERVER_URL`
- `EVOLUTION_API_KEY`
- `EVOLUTION_INSTANCE`
- `EVOLUTION_GROUP_ID`

## 3) Preparar ambiente

```bash
chmod +x scripts/*.sh
./scripts/setup_vps.sh
```

Se o dry-run terminar sem erro, siga para o cron.

## 4) Instalar CRON (08:00 e 18:00)

```bash
./scripts/install_cron.sh
```

## 5) Verificar operacao

Rodar manualmente:

```bash
./scripts/run_monitor.sh
```

Acompanhar log:

```bash
tail -f .tmp/monitor_meta_ads.log
```

## Operacao diaria

- Alterar limites sem mexer em codigo:
  - `ALERT_THRESHOLD` e `NEAR_THRESHOLD` no `.env`
- Reiniciar nao e necessario para cron; proxima execucao ja usa novo `.env`.

## Troubleshooting rapido

- Token expirado Meta: renovar `META_ACCESS_TOKEN`.
- Grupo nao recebe: validar `EVOLUTION_INSTANCE`, `EVOLUTION_GROUP_ID` e `EVOLUTION_API_KEY`.
- Erro de timezone: confirmar `TZ=America/Sao_Paulo` no `.env`.

## EasyPanel (Dockerfile)

Se o deploy for no EasyPanel:

1. Selecione `Dockerfile` como metodo de build.
2. Caminho do Dockerfile: `Dockerfile`.
3. Configure as variaveis de ambiente do `.env` no painel.
4. Opcionalmente, defina:
   - `CRON_SCHEDULE=0 8,18 * * *`
   - `ALERT_THRESHOLD=200`
   - `NEAR_THRESHOLD=120`
5. Suba o servico.

Observacao: o container executa `supercronic` internamente, entao nao precisa configurar cron do host.
