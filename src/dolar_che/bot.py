"""Discord wiring. Run: dolar-che (token in DISCORD_TOKEN or in ~/.dolar-che/token)."""

from __future__ import annotations

import asyncio
import io
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

from . import settings, storage
from .api import Rates
from .chart import render
from .core import (
    ART,
    HISTORY_RATES,
    SHORT_NAMES,
    Alert,
    DolarError,
    alert_fires,
    card_purchase,
    convert,
    describe_alert,
    format_currencies,
    format_daily_summary,
    format_history,
    format_quotes,
    last_days,
    money,
)

HOME = settings.home()
ALERTS_FILE = Path(os.environ.get("DOLAR_CHE_DATA") or HOME / "alerts.json")
SUMMARY_TIME = time(18, 0, tzinfo=ART)

client = discord.Client(intents=discord.Intents.none())
tree = app_commands.CommandTree(client)
rates = Rates()

RATE_CHOICES = [app_commands.Choice(name=SHORT_NAMES[k], value=k) for k in HISTORY_RATES]
CURRENCY_CHOICES = [
    app_commands.Choice(name="dólares → pesos", value="usd"),
    app_commands.Choice(name="pesos → dólares", value="ars"),
]
DAY_CHOICES = [app_commands.Choice(name=f"{d} días", value=d) for d in (7, 30, 90, 365)]


def now() -> datetime:
    return datetime.now(timezone.utc)


async def oops(interaction: discord.Interaction, exc: Exception) -> None:
    await interaction.followup.send(f"😕 {exc}", ephemeral=True)


@tree.command(name="dolar", description="Cómo está el dólar ahora, con la hora de cada cotización")
async def dolar(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        text = format_quotes(await asyncio.to_thread(rates.dollars), now())
    except DolarError as exc:
        return await oops(interaction, exc)
    await interaction.followup.send(text)


@tree.command(name="convertir", description="Pasá dólares a pesos o pesos a dólares")
@app_commands.describe(monto="Cuánto querés convertir", moneda="Qué querés convertir", tipo="Qué dólar usar")
@app_commands.choices(moneda=CURRENCY_CHOICES, tipo=RATE_CHOICES)
async def convertir(
    interaction: discord.Interaction,
    monto: float,
    moneda: app_commands.Choice[str],
    tipo: app_commands.Choice[str] | None = None,
):
    await interaction.response.defer()
    try:
        quotes = await asyncio.to_thread(rates.dollars)
        text = convert(monto, moneda.value, tipo.value if tipo else "blue", quotes, now())
    except DolarError as exc:
        return await oops(interaction, exc)
    await interaction.followup.send(text)


@tree.command(name="compra", description="Cuánto te sale en pesos algo en dólares con tarjeta, con impuestos")
@app_commands.describe(dolares="Precio en dólares de lo que querés comprar")
async def compra(interaction: discord.Interaction, dolares: float):
    await interaction.response.defer()
    try:
        text = card_purchase(dolares, await asyncio.to_thread(rates.dollars), now())
    except DolarError as exc:
        return await oops(interaction, exc)
    await interaction.followup.send(text)


@tree.command(name="monedas", description="Euro, real, peso chileno y peso uruguayo, en pesos")
async def monedas(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        text = format_currencies(await asyncio.to_thread(rates.currencies), now())
    except DolarError as exc:
        return await oops(interaction, exc)
    await interaction.followup.send(text)


@tree.command(name="historial", description="Gráfico de cómo se movió un dólar en los últimos días")
@app_commands.choices(tipo=RATE_CHOICES, dias=DAY_CHOICES)
async def historial(
    interaction: discord.Interaction,
    tipo: app_commands.Choice[str],
    dias: app_commands.Choice[int] | None = None,
):
    await interaction.response.defer()
    days = dias.value if dias else 30
    try:
        history = await asyncio.to_thread(rates.history, tipo.value)
        window = last_days(history, days, now().astimezone(ART).date())
        text = format_history(tipo.value, days, window)
        png = await asyncio.to_thread(
            render, window, f"Dólar {SHORT_NAMES[tipo.value]} · últimos {days} días"
        )
    except DolarError as exc:
        return await oops(interaction, exc)
    await interaction.followup.send(text, file=discord.File(io.BytesIO(png), filename="historial.png"))


@tree.command(name="alerta", description="Te aviso por privado cuando un dólar llegue a un valor")
@app_commands.describe(tipo="Qué dólar", cuando="Si sube o baja a ese valor", valor="En pesos")
@app_commands.choices(
    tipo=RATE_CHOICES,
    cuando=[app_commands.Choice(name="sube a", value="up"), app_commands.Choice(name="baja a", value="down")],
)
async def alerta(
    interaction: discord.Interaction,
    tipo: app_commands.Choice[str],
    cuando: app_commands.Choice[str],
    valor: float,
):
    try:
        if valor <= 0:
            raise DolarError("El valor tiene que ser mayor que cero, che.")
        new = Alert(interaction.user.id, tipo.value, "sell", cuando.value == "up", valor)
        storage.save(ALERTS_FILE, storage.add(storage.load(ALERTS_FILE), new))
    except (DolarError, ValueError) as exc:
        return await interaction.response.send_message(f"😕 {exc}", ephemeral=True)
    await interaction.response.send_message(
        f"¡Dale! Te aviso por privado cuando {describe_alert(new)}. "
        "Fijate de tener los mensajes privados abiertos.",
        ephemeral=True,
    )


@tree.command(name="alertas", description="Tus alertas activas")
async def alertas(interaction: discord.Interaction):
    mine = [a for a in storage.load(ALERTS_FILE) if a.user_id == interaction.user.id]
    text = "\n".join(f"{i}. Cuando {describe_alert(a)}" for i, a in enumerate(mine, 1))
    await interaction.response.send_message(text or "No tenés alertas. Creá una con /alerta.", ephemeral=True)


@tree.command(name="borrar-alerta", description="Borrá una de tus alertas por su número")
async def borrar_alerta(interaction: discord.Interaction, numero: int):
    try:
        storage.save(ALERTS_FILE, storage.remove(storage.load(ALERTS_FILE), interaction.user.id, numero))
    except ValueError as exc:
        return await interaction.response.send_message(f"😕 {exc}", ephemeral=True)
    await interaction.response.send_message("Listo, la borré.", ephemeral=True)


@tree.command(name="ayuda", description="Qué sabe hacer DOLAR CHE")
async def ayuda(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**DOLAR CHE** 🇦🇷\n"
        "`/dolar` cómo está el dólar ahora\n"
        "`/convertir` dólares a pesos o al revés\n"
        "`/compra` cuánto sale algo en dólares con tarjeta\n"
        "`/monedas` euro, real y pesos chileno y uruguayo\n"
        "`/historial` gráfico de los últimos días\n"
        "`/alerta` te aviso cuando llegue a tu número\n"
        "`/resumen-aca` el resumen de las 18 h sale en este canal (solo admins)\n"
        "Los datos son de referencia, no son un consejo financiero.",
        ephemeral=True,
    )


@tree.command(name="resumen-aca", description="El resumen diario de las 18 h sale en este canal")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def resumen_aca(interaction: discord.Interaction):
    settings.set_summary_channel(HOME, interaction.channel_id)
    await interaction.response.send_message(
        "¡Listo! Los días hábiles a las 18 h te dejo acá cómo cerró el dólar. 🧉", ephemeral=True
    )


@tree.command(name="resumen-apagar", description="Deja de publicar el resumen diario")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def resumen_apagar(interaction: discord.Interaction):
    settings.set_summary_channel(HOME, None)
    await interaction.response.send_message("Listo, no publico más el resumen diario.", ephemeral=True)


@tasks.loop(minutes=10)
async def check_alerts():
    alerts = storage.load(ALERTS_FILE)
    if not alerts:
        return
    try:
        quotes = await asyncio.to_thread(rates.dollars)
    except DolarError:
        return  # try again in 10 minutes
    remaining = []
    for a in alerts:
        if not alert_fires(a, quotes):
            remaining.append(a)
            continue
        try:
            user = await client.fetch_user(a.user_id)
            await user.send(
                f"🔔 ¡Che! {describe_alert(a).capitalize()}: ahora está en {money(quotes[a.rate].sell)}."
            )
        except discord.HTTPException:
            remaining.append(a)  # private messages closed or a Discord hiccup: keep it
    if len(remaining) != len(alerts):
        storage.save(ALERTS_FILE, remaining)


@tasks.loop(time=SUMMARY_TIME)
async def daily_summary():
    channel_id = settings.summary_channel(os.environ, HOME)
    if channel_id is None:
        return
    channel = client.get_channel(channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        print(f"Summary channel {channel_id} is not a channel the bot can write to.", file=sys.stderr)
        return
    try:
        histories = {
            r: await asyncio.to_thread(rates.history, r)
            for r in ("blue", "oficial", "bolsa", "contadoconliqui")
        }
        await channel.send(format_daily_summary(histories, now().astimezone(ART).date()))
    except DolarError:
        return  # no close today (weekend or holiday) or the service is down: skip, never post stale data


@client.event
async def on_ready():
    await tree.sync()
    for loop in (check_alerts, daily_summary):
        if not loop.is_running():
            loop.start()
    print(f"DOLAR CHE ready as {client.user}")


def main() -> int:
    token = settings.load_token(os.environ, HOME)
    if not token:
        print(
            f"No token found. Put it in {HOME / 'token'} or in DISCORD_TOKEN (see README).", file=sys.stderr
        )
        return 2
    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
