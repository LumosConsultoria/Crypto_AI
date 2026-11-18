# 🤖 Crypto Trading Bot

> **Portfolio / research status (November 2026):** Source and unit tests from the original local project. This is an experimental trading research system, NOT a production trading product, guaranteed investment strategy, or evidence of profitable live performance. Default to paper trading. Offline tests do not validate exchange, network, or live market behavior. No data or credentials are included. See [PORTFOLIO.md](PORTFOLIO.md).

Bot de trading quantitativo/assistido por IA para Bitcoin e outras criptomoedas.

> ⚠️ **MODO PADRÃO: PAPER TRADING** — Nenhuma ordem real é enviada sem aprovação explícita e configuração manual adicional.

> 🖥️ **CLI-first (FASE 43)** — O Crypto_AI é operado por **CLI / PowerShell / JSON / Reports / Decision Trace / Readiness**. A UI web (FASES 41–42) foi **descontinuada**. Toda funcionalidade crítica é acessível **sem navegador**. Interfaces gráficas futuras serão **consumidoras** do core (nunca dependências). Guia operacional: [docs/operator_cli_mode.md](docs/operator_cli_mode.md).

---

## 🎯 Objetivo

Desenvolver um sistema de trading algorítmico profissional, seguro e auditável, começando por simulação (paper trading) e testnet da Bybit, evoluindo gradualmente para operação real somente após validação completa.

**Ambiente-alvo futuro:** HyroTrader account — 5.000 USD  
**Exchange principal:** Bybit  
**Linguagem:** Python 3.12.x (versão principal do projeto)

---

## 🏗️ Arquitetura

```
<project-root>/
├── src/
│   └── crypto_trading_bot/
│       ├── config/           # Configurações e regras de risco
│       ├── core/             # Núcleo orquestrador e ModeGuard
│       ├── data/             # Coleta de dados de mercado
│       ├── indicators/       # Indicadores técnicos
│       ├── risk/             # Motor de risco (prioridade máxima)
│       ├── strategies/       # Estratégias determinísticas
│       ├── execution/        # Execução de ordens (paper/testnet/live)
│       ├── exchange/         # Clientes de exchange
│       ├── backtesting/      # Motor de backtesting
│       ├── ai_assistant/     # Módulo auxiliar de IA (NÃO decide trades)
│       └── logging_system/   # Logs estruturados e auditoria
├── tests/                    # Testes unitários e de integração
├── scripts/                  # Scripts utilitários
├── docs/                     # Documentação
├── notebooks/                # Análises exploratórias
├── .env.example              # Template de variáveis de ambiente
├── pyproject.toml            # Configuração do projeto
├── requirements.txt          # Dependências de produção
└── requirements-dev.txt      # Dependências de desenvolvimento
```

Veja [docs/architecture.md](docs/architecture.md) para detalhes completos.

---

## 🛡️ Princípios de Segurança

1. **ModeGuard ativo**: o modo padrão é `paper`. Mudar para `live` requer:
   - `TRADING_MODE=live` no `.env`
   - `ENABLE_LIVE_TRADING=true` no `.env`
   - Confirmação explícita em código (`confirm_live_trading=True`)
2. **Motor de Risco soberano**: toda operação passa pelo `RiskEngine` antes de ser executada.
3. **Stop loss obrigatório**: qualquer sinal sem stop loss é rejeitado automaticamente.
4. **Sem segredos no código**: todas as chaves de API ficam no `.env` (nunca versionado).
5. **AI não decide trades**: IA é usada apenas para análise auxiliar de contexto e logs.

---

## 🚀 Início Rápido

### Pré-requisitos

- **Python 3.12.x** (versão principal — use `py -3.12` no Windows ou `python3.12` no Linux/Mac)
- pip ou poetry

> ⚠️ Evite Python 3.14+ neste projeto: bibliotecas científicas/quant como `numba`, `vectorbt` e outras ainda não têm suporte completo.

### Instalação

```bash
# Clone o repositório
git clone https://github.com/LumosConsultoria/Crypto_AI.git
cd Crypto_AI

# Crie o ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Instale as dependências
pip install -r requirements.txt
pip install -r requirements-dev.txt  # para desenvolvimento/testes

# Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env com suas configurações (nunca use chaves reais no início)
```

### Verificar Configuração

```bash
python scripts/check_config.py
```

### Rodar Testes

```bash
pytest tests/ -v
pytest tests/ -v --cov=src/crypto_trading_bot
```

### Iniciar Paper Trading

```bash
python scripts/run_paper_trading.py
```

### Testar Market Data em Modo Seguro (FASE 3A)

Você pode testar a coleta de dados públicos da Bybit sem API key, sem autenticação e sem enviar ordens:

```python
# Testar dados reais da Bybit (somente leitura, sem API key)
from crypto_trading_bot.exchange.bybit_client import BybitClient
from crypto_trading_bot.data.market_data import MarketDataService

# Usar testnet (padrão seguro)
with BybitClient(use_testnet=True, default_category="linear") as client:
    service = MarketDataService(exchange=client)
    
    # Buscar preço atual de BTCUSDT
    price = service.get_latest_price("BTCUSDT")
    print(f"BTC: ${price:,.2f}")
    
    # Buscar candles (últimas 50, timeframe 15min)
    candles = service.get_candles("BTCUSDT", "15", limit=50)
    print(f"{len(candles)} candles recebidas")
    closes = [c.close for c in candles]
    
    # Buscar order book
    ob = service.get_order_book("BTCUSDT", depth=5)
    print(f"Bid: {ob.best_bid} | Ask: {ob.best_ask}")
```

> ✅ **Seguro:** este código não envia ordens, não autentica e não usa API key.  
> ✅ **Testável offline:** use `MockExchange` no lugar de `BybitClient` para testes sem internet.

---

## 📋 Fases do Projeto

| Fase | Status | Descrição |
|------|--------|-----------|
| FASE 1 | ✅ Concluída | Análise e proposta de arquitetura |
| FASE 2 | ✅ Concluída | Estrutura base, ModeGuard, RiskEngine, PaperTrader — 98 testes |
| FASE 3A | ✅ Concluída | Market Data Bybit read-only, MarketDataService, 167 testes |
| FASE 3B | ⏳ Planejada | Bybit testnet (autenticação), execução simulada real |
| FASE 3C | ⏳ Planejada | Backtesting, indicadores técnicos (ta lib) |
| FASE 4 | ⏳ Futura | Estratégias validadas, análise avançada |
| FASE 5 | ⏳ Futura | ML/AI auxiliar, Polymarket, análise de notícias |
| FASE 6 | ⏳ Futura | Live trading (após validação completa) |

---

## ⚠️ Avisos Importantes

- Este software é para fins educacionais e de pesquisa.
- Trading de criptomoedas envolve riscos significativos.
- **NUNCA** configure `ENABLE_LIVE_TRADING=true` sem validação completa do sistema.
- O autor não se responsabiliza por perdas financeiras.

---

## 📄 Licença

Projeto privado — todos os direitos reservados.
