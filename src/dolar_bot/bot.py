"""Discord wiring. Run: python -m dolar_bot.bot (needs DISCORD_TOKEN in the environment)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

from . import storage
from .core import (
    Alert,
    DolarError,
    alert_fires,
    convert,
    describe_alert,
    format_quotes,
    money,
    parse_quotes,
    resolve_rate,
)

API_URL = "https://dolarapi.com/v1/dolares"
ALERTS_FILE = Path(os.environ.get("DOLAR_BOT_DATA", Path.home() / ".dolar-bot" / "alerts.json"))

client = discord.Client(intents=discord.Intents.none())
tree = app_commands.CommandTree(client)


def fetch_quotes():
    # dolarapi.com answers 403 to Python's default User-Agent, so the bot says who it is.
    request = urllib.request.Request(API_URL, headers={"User-Agent": "dolar-bot/0.1 (Discord bot)"})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return parse_quotes(json.load(resp))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise DolarError("No pude consultar las cotizaciones ahora. Probá en unos minutos.") from None


async def quotes_now():
    return await asyncio.to_thread(fetch_quotes)


async def fail(interaction: discord.Interaction, exc: Exception) -> None:
    await interaction.response.send_message(str(exc), ephemeral=True)


@tree.command(name="dolar", description="Cotizaciones del dólar de hoy")
async def dolar(interaction: discord.Interaction):
    try:
        quotes = await quotes_now()
    except DolarError as exc:
        return await fail(interaction, exc)
    await interaction.response.send_message(f"```\n{format_quotes(quotes)}\n```")


@tree.command(name="convertir", description="Pasar dólares a pesos o pesos a dólares")
@app_commands.describe(monto="Cantidad", moneda="Lo que tenés", tipo="blue, oficial, mep, ccl...")
@app_commands.choices(
    moneda=[app_commands.Choice(name="dólares", value="usd"), app_commands.Choice(name="pesos", value="ars")]
)
async def convertir(
    interaction: discord.Interaction, monto: float, moneda: app_commands.Choice[str], tipo: str = "blue"
):
    try:
        quotes = await quotes_now()
        text = convert(monto, moneda.value, resolve_rate(tipo), quotes)
    except DolarError as exc:
        return await fail(interaction, exc)
    await interaction.response.send_message(text)


@tree.command(name="alerta", description="Avisarte por mensaje privado cuando el dólar llegue a un valor")
@app_commands.describe(tipo="blue, oficial, mep, ccl...", cuando="Si sube o baja a ese valor", valor="Pesos")
@app_commands.choices(
    cuando=[app_commands.Choice(name="sube a", value="up"), app_commands.Choice(name="baja a", value="down")]
)
async def alerta(interaction: discord.Interaction, tipo: str, cuando: app_commands.Choice[str], valor: float):
    try:
        if valor <= 0:
            raise DolarError("El valor tiene que ser mayor que cero.")
        new = Alert(interaction.user.id, resolve_rate(tipo), "sell", cuando.value == "up", valor)
        storage.save(ALERTS_FILE, storage.add(storage.load(ALERTS_FILE), new))
    except (DolarError, ValueError) as exc:
        return await fail(interaction, exc)
    await interaction.response.send_message(
        f"Listo. Te aviso por privado cuando {describe_alert(new)}. "
        "Tenés que tener los mensajes privados abiertos.",
        ephemeral=True,
    )


@tree.command(name="alertas", description="Tus alertas activas")
async def alertas(interaction: discord.Interaction):
    mine = [a for a in storage.load(ALERTS_FILE) if a.user_id == interaction.user.id]
    text = "\n".join(f"{i}. {describe_alert(a)}" for i, a in enumerate(mine, 1)) or "No tenés alertas."
    await interaction.response.send_message(text, ephemeral=True)


@tree.command(name="borrar-alerta", description="Borrar una alerta por su número")
async def borrar_alerta(interaction: discord.Interaction, numero: int):
    try:
        storage.save(ALERTS_FILE, storage.remove(storage.load(ALERTS_FILE), interaction.user.id, numero))
    except ValueError as exc:
        return await fail(interaction, exc)
    await interaction.response.send_message("Borrada.", ephemeral=True)


@tasks.loop(minutes=10)
async def check_alerts():
    alerts = storage.load(ALERTS_FILE)
    if not alerts:
        return
    try:
        quotes = await quotes_now()
    except DolarError:
        return  # try again in 10 minutes
    remaining = []
    for a in alerts:
        if not alert_fires(a, quotes):
            remaining.append(a)
            continue
        price = money(quotes[a.rate].sell)
        try:
            user = await client.fetch_user(a.user_id)
            await user.send(f"Alerta: {describe_alert(a)}. Ahora está en {price}.")
        except discord.HTTPException:
            remaining.append(a)  # DMs closed or Discord hiccup: keep it for the next round
    if len(remaining) != len(alerts):
        storage.save(ALERTS_FILE, remaining)


@client.event
async def on_ready():
    await tree.sync()
    if not check_alerts.is_running():
        check_alerts.start()
    print(f"Ready as {client.user}")


def main() -> int:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("Set the DISCORD_TOKEN environment variable first (see README).", file=sys.stderr)
        return 2
    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
