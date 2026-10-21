# dolar-bot

A Discord bot for Argentine communities. Anyone who earns, saves or pays in dollars in
Argentina checks the exchange rate several times a day, and the "blue" rate is not on most
bank apps. This bot puts it one slash command away and can warn you when it reaches the
number you care about.

*En castellano: un bot de Discord con las cotizaciones del dólar (oficial, blue, MEP, CCL,
cripto, tarjeta), un conversor y alertas por mensaje privado.*

| Command | What it does |
|---|---|
| `/dolar` | Table with buy and sell prices for every rate, and the blue/official gap |
| `/convertir monto moneda tipo` | USD to pesos (at the buy price) or pesos to USD (at the sell price), for any rate |
| `/alerta tipo cuando valor` | A private message when a rate goes up to or down to a price (one time) |
| `/alertas`, `/borrar-alerta` | List and delete your alerts (up to 5 each) |

Rates come from the free public API at <https://dolarapi.com>. The bot makes at most one
request per command and one every 10 minutes for alerts, and says so plainly when the
service is down instead of showing old numbers. Rates are informative and not financial advice.

## Run it

1. Create an application and bot at <https://discord.com/developers/applications> and invite it
   with the `applications.commands` scope.
2. Install and start:

```bash
pip install .
export DISCORD_TOKEN="your token"       # Windows PowerShell: $env:DISCORD_TOKEN="your token"
python -m dolar_bot.bot
```

The token is read only from the environment. Alerts are stored in `~/.dolar-bot/alerts.json`
(change it with `DOLAR_BOT_DATA`). The bot needs no special Discord permissions or intents.

## How it is organised

- `core.py`: reading the API answer, Argentine number format, conversion rules, gap and
  alert rule. Pure functions with no network or Discord.
- `storage.py`: alerts in a JSON file, written to a temp file and renamed so a crash cannot
  leave half a file; a corrupt file means "no alerts", never a crash.
- `bot.py`: the thin layer that connects them to Discord and the API.

Details that were easy to get wrong and have tests: selling dollars uses the *buy* price and
buying uses the *sell* price; an alert at exactly the target does fire; a missing rate never
fires an alert; one broken entry in the API list does not discard the good ones.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The tests cover the logic. The Discord commands were not tested against a live server in
this repository.

## License

MIT
