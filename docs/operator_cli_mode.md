# Operator CLI Mode — Crypto_AI (FASE 43)

> O Crypto_AI é **CLI-first / PowerShell-first**. A UI web (FASES 41–42)
> foi descontinuada. Toda funcionalidade crítica é operável **sem
> navegador**, via CLI + JSON Reports + Logs estruturados + Decision Trace
> + Readiness Reports. Este documento consolida os **comandos já
> existentes** (não introduz funcionalidade nova).

## Visão geral

- Núcleo soberano: **RiskEngine**, **ModeGuard**, gates de demo, Safety
  State — inalterados.
- Modo padrão: **paper**. Demo é **gated**; mainnet/live **bloqueados** por
  política.
- Saídas auditáveis: `reports/` (JSON), logs estruturados, Decision Trace,
  Readiness Reports.
- Windows/PowerShell: rode com `PYTHONIOENCODING=utf-8` (evita erro de
  encoding em emojis/acentos). Ex.: `$env:PYTHONIOENCODING='utf-8'`.

## Ambiente

```powershell
# instalar (sem grupo [ui] — descontinuado)
pip install -e .
# opcionais: .[exchange] .[backtesting] .[ai] ou .[all]
$env:PYTHONIOENCODING = 'utf-8'
python scripts/check_config.py        # sanity de configuração
```

## Fluxo operacional (comando por etapa)

### 1. Dados históricos
| Objetivo | Comando |
|---|---|
| Baixar candles (read-only público) | `python scripts/run_historical_data_fetcher.py` |
| Importar/converter klines Binance | `python scripts/convert_binance_klines_to_canonical.py` |
| Download utilitário | `python scripts/download_historical_data.py` |
| Validar Data Readiness | `python scripts/run_data_readiness.py` |

Metadados e checksum são gerados pelo fetcher junto ao dataset canônico
(`data/historical/<SYMBOL>/<TF>/`).

### 2. Pesquisa e validação
| Objetivo | Comando |
|---|---|
| Backtest de estratégia | `python scripts/run_strategy_backtest.py` |
| Backtest (entrypoint simples) | `python scripts/run_backtest.py` (`ctb-backtest`) |
| Calibração + walk-forward + custos | `python scripts/run_strategy_calibration.py` |
| Advisor de parâmetros | `python scripts/run_strategy_parameter_advisor.py` |
| Advisor de SL | `python scripts/run_sl_calibration_advisor.py` |
| Regime window analysis | `python scripts/run_regime_window_analysis.py` |
| Strategy family research | `python scripts/run_strategy_family_research.py` |
| Final research (local-only) | `python scripts/run_final_research_attempt.py` |

Relatórios saem em `reports/` (JSON) com verdict/decisão consultiva.

### 3. Operação Paper
| Objetivo | Comando |
|---|---|
| Session runner (paper) | `python scripts/run_paper_trading.py` (`ctb-paper`) |
| Paper orquestrado | `python scripts/run_paper_orchestrated.py` |
| Challenge endurance | `python scripts/run_challenge_endurance.py` |
| Supervised readiness | `python scripts/run_supervised_readiness.py` |

Telemetry é emitida pelos runners (logs estruturados + reports).

### 4. Operação Demo (gated)
| Objetivo | Comando |
|---|---|
| Operator inputs (V1–V12 / perfil) | `python scripts/run_operator_inputs.py` |
| Perfil operacional (validar) | `python scripts/check_operational_profile.py` |
| Demo session readiness | `python scripts/check_demo_session_readiness.py` |
| Demo session gated | `python scripts/run_demo_session_gated.py` |
| Bybit demo session gated | `python scripts/run_bybit_demo_session_gated.py` |
| Demo endurance | `python scripts/run_demo_endurance.py` |
| Demo 30 min endurance | `python scripts/run_demo_30_min_endurance.py` |
| Diagnóstico Bybit demo | `python scripts/run_bybit_demo_diagnostic.py` |
| Diagnóstico testnet | `python scripts/run_testnet_diagnostic.py` |

> O **perfil operacional** é informado/validado pelo fluxo de **operator
> inputs** existente (`run_operator_inputs.py`) — como antes da UI. Não há
> tela nem CLI novo para isso nesta fase.

Blueprint, Session Gate, Safety Gates e Decision Trace fazem parte do
caminho gated dos runners de demo. **Nenhuma ordem é enviada** sem todos os
gates + confirmação humana.

### 5. Observabilidade
- `reports/` — todos os relatórios em JSON (backtests, readiness, demo,
  decision trace, research).
- Logs estruturados — emitidos pelos runners.
- Decision Trace — registrado por decisão (entrada/hold/block/close; IA/MI
  used/not_used; RiskEngine).

## Infra de rede read-only (NetComms)

Comunicação de rede (quando algum fluxo precisar) passa pelo pacote neutro
`crypto_trading_bot.netcomms` (realocado na FASE 43): adapters **read-only
allowlisted**, gated, com timeout e erro sanitizado, sem expor
secret/header/signature. É **infraestrutura** consumível por CLI; não
depende de nenhuma UI. Não envia ordem/cancel/close.

## Troubleshooting
- **UnicodeEncodeError no Windows:** defina `PYTHONIOENCODING=utf-8`.
- **Dataset não-ready:** rode `run_data_readiness.py` e verifique o report.
- **Demo bloqueada:** esperado — depende de estratégia promovida + operator
  inputs + credenciais + gates + confirmação humana.
- **check_config falha:** leia os avisos; configure regras de risco reais e
  credenciais antes de qualquer operação.

## Segurança (inalterada)
Sem ordem automática; demo/mainnet/live bloqueados por política; RiskEngine/
ModeGuard soberanos; piso de stop-loss 0.005 intacto; secret nunca em
report/log/telemetry.
