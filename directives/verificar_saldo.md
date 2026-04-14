# SOP: Verificacao de saldo

## Objetivo

Verificar o saldo atual e sinalizar se esta abaixo de um limite minimo definido.

## Entradas

- Limite minimo (`--limite` no script)
- Variavel de ambiente `SALDO_ATUAL`

## Ferramenta de execucao

- Script: `execution/verificar_saldo.py`

## Saida esperada

JSON com:

- `saldo_atual`
- `limite_minimo`
- `status` (`ok` ou `abaixo_do_limite`)

## Edge cases

- `SALDO_ATUAL` ausente no `.env`
- `SALDO_ATUAL` nao numerico
- Limite negativo informado pelo operador

## Procedimento

1. Confirmar se `.env` esta preenchido.
2. Rodar:

   - `python execution/verificar_saldo.py --limite 100`

3. Interpretar o campo `status`.
4. Se houver erro, corrigir script e registrar aprendizado nesta diretiva.
