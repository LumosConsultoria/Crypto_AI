# ⚠️ Regras de Risco — HyroTrader

> **STATUS: PLACEHOLDER — A PREENCHER NA FASE 3**
>
> Este documento reserva espaço para as regras exatas do plano HyroTrader.
> Os valores abaixo são **placeholders conservadores** baseados em boas práticas gerais
> de prop trading. As regras **reais do contrato HyroTrader** devem ser inseridas
> aqui antes de qualquer operação em testnet.

---

## Plano de Referência

- **Plataforma:** HyroTrader
- **Tipo de conta:** One Step (Popular)
- **Capital de trading:** 5.000 USDT
- **Profit Share:** Até 90%

---

## Regras do Desafio (Preencher com valores reais)

| Regra | Valor Atual (Placeholder) | Valor Real HyroTrader |
|-------|--------------------------|----------------------|
| Meta de lucro | A preencher | A preencher |
| Máximo de dias de negociação | A preencher | A preencher |
| Perda máxima diária (Daily Drawdown) | 5% | **Verificar no contrato** |
| Perda máxima total (Max Drawdown) | 10% | **Verificar no contrato** |
| Alavancagem máxima | 3x | **Verificar no contrato** |
| Negociação durante notícias | A preencher | A preencher |
| Negociação com rollover | A preencher | A preencher |

---

## Como Preencher

1. Acesse sua conta HyroTrader em: https://hydrotrader.com (ou plataforma equivalente)
2. Leia o contrato/termos do desafio One Step 5.000 USDT
3. Anote as regras exatas de:
   - Daily loss limit (%)
   - Maximum drawdown (%)
   - Profit target (%)
   - Minimum trading days
   - Maximum trading days
   - Instrumentos permitidos
   - Horários permitidos
   - Regras de notícias econômicas

4. Configure as variáveis correspondentes no `.env`:
   ```
   RISK_MAX_DAILY_LOSS_PCT=<valor_real>
   RISK_MAX_TOTAL_LOSS_PCT=<valor_real>
   RISK_MAX_TRADES_PER_DAY=<valor_real>
   ```

5. Atualize este documento com os valores reais.

---

## Configuração Atual no Sistema

Os valores ativos são lidos do `.env` e podem ser verificados com:
```bash
python scripts/check_config.py
```

Parâmetros relevantes do `.env`:
```
RISK_MAX_DAILY_LOSS_PCT=0.05     # Placeholder: 5%
RISK_MAX_TOTAL_LOSS_PCT=0.10     # Placeholder: 10%
RISK_MAX_TRADES_PER_DAY=10       # Placeholder: 10 trades/dia
RISK_MAX_EXPOSURE_PER_ASSET_PCT=0.20  # Placeholder: 20% por ativo
RISK_MAX_LEVERAGE=3              # Placeholder: 3x
RISK_MIN_STOP_LOSS_PCT=0.005     # Placeholder: 0.5%
```

---

## Regras Adicionais do Sistema (Independentes da HyroTrader)

Estas regras são **internas do bot** e se somam às regras da HyroTrader:

### Stop Loss Obrigatório
- Todo sinal DEVE incluir um stop loss
- Sinais sem stop loss são rejeitados automaticamente pelo RiskEngine
- Stop loss mínimo: configurável via `RISK_MIN_STOP_LOSS_PCT`

### Regra de Não-IA
- Nenhuma decisão de entrada, saída, stop ou posição é feita por IA/LLM
- IA é utilizada APENAS como ferramenta auxiliar de análise de contexto
- Toda decisão é determinística, testável e documentada

### Auditoria Completa
- Todos os sinais, decisões e ordens são registrados em log
- Logs de auditoria são armazenados separadamente dos logs gerais
- Cada bloqueio pelo RiskEngine registra o motivo de forma detalhada

---

## Revisão

Este documento deve ser revisado antes de:
- ✅ Iniciar testes em testnet
- ✅ Iniciar operação em live
- ✅ Alterar qualquer parâmetro de risco

**Última atualização:** FASE 2 — apenas placeholders
**Próxima revisão:** FASE 3 — antes do testnet
