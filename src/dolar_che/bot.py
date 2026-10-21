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

from . import cards, settings, storage
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
    dollar_rows,
    format_daily_summary,
    gap_percent,
    last_days,
    money,
    period_moves,
    resolve_rate,
    stamps_text,
)

HOME = settings.home()
ALERTS_FILE = Path(os.environ.get("DOLAR_CHE_DATA") or HOME / "alerts.json")
SUMMARY_TIME = time(18, 0, tzinfo=ART)
BUTTONS_LAST_SECONDS = 15 * 60  # after this, buttons stop answering; the command can be run again

client = discord.Client(intents=discord.Intents.none())
tree = app_commands.CommandTree(client)
rates = Rates()

RATE_CHOICES = [app_commands.Choice(name=SHORT_NAMES[k], value=k) for k in HISTORY_RATES]
DAY_CHOICES = [
    app_commands.Choice(name="7 días · una semana", value=7),
    app_commands.Choice(name="30 días · un mes", value=30),
    app_commands.Choice(name="90 días · tres meses", value=90),
    app_commands.Choice(name="365 días · un año", value=365),
]
PERIOD_CHOICES = [
    app_commands.Choice(name="Hoy contra el día anterior", value=1),
    app_commands.Choice(name="Últimos 7 días", value=7),
    app_commands.Choice(name="Últimos 30 días", value=30),
]
CURRENCY_CHOICES = [
    app_commands.Choice(name="Tengo dólares → quiero pesos", value="usd"),
    app_commands.Choice(name="Tengo pesos → quiero dólares", value="ars"),
]
SUMMARY_RATES = ("blue", "oficial", "bolsa", "contadoconliqui", "cripto", "tarjeta")


def now() -> datetime:
    return datetime.now(timezone.utc)


def today():
    return now().astimezone(ART).date()


# ---------------------------------------------------------------- building replies


async def dolar_card() -> discord.Embed:
    quotes = await asyncio.to_thread(rates.dollars)
    histories = await asyncio.to_thread(rates.histories, SUMMARY_RATES)
    rows = dollar_rows(quotes, histories, today())
    gap = gap_percent(quotes) if "blue" in quotes and "oficial" in quotes else None
    return cards.dolar(rows, gap, stamps_text(quotes, now()), now())


async def history_card(rate: str, days: int) -> tuple[discord.Embed, discord.File]:
    window = last_days(await asyncio.to_thread(rates.history, rate), days, today())
    if len(window) < 2:
        raise DolarError("No hay suficientes días de historial para ese período.")
    footer = f"Fuente: argentinadatos.com · {now().astimezone(ART):%d/%m/%Y %H:%M}"
    png = await asyncio.to_thread(render, window, f"Dólar {SHORT_NAMES[rate]} · últimos {days} días", footer)
    return cards.history(rate, days, window), discord.File(io.BytesIO(png), filename="historial.png")


async def summary_card(period: int) -> discord.Embed:
    histories = await asyncio.to_thread(rates.histories, SUMMARY_RATES)
    return cards.summary(period, period_moves(histories, period, today()))


# ---------------------------------------------------------------- buttons


class AlertModal(discord.ui.Modal, title="Crear una alerta"):
    tipo = discord.ui.TextInput(
        label="¿Qué dólar?",
        default="blue",
        placeholder="blue, oficial, mep, ccl, cripto, tarjeta",
        max_length=20,
    )
    valor = discord.ui.TextInput(
        label="Avisame cuando llegue a ($)", placeholder="por ejemplo 1600", max_length=12
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rate = resolve_rate(str(self.tipo))
            target = float(str(self.valor).replace("$", "").replace(".", "").replace(",", ".").strip())
            if target <= 0:
                raise DolarError("El valor tiene que ser mayor que cero, che.")
            quotes = await asyncio.to_thread(rates.dollars)
            current = quotes[rate].sell if rate in quotes else None
            # Up or down is clear from where the rate is now: no need to ask.
            above = current is None or target >= current
            new = Alert(interaction.user.id, rate, "sell", above, target)
            storage.save(ALERTS_FILE, storage.add(storage.load(ALERTS_FILE), new))
        except (DolarError, ValueError) as exc:
            return await interaction.response.send_message(embed=cards.problem(str(exc)), ephemeral=True)
        now_text = f" Ahora está en {money(current)}." if current else ""
        await interaction.response.send_message(
            embed=cards.simple(
                "🔔 Alerta creada",
                f"Te aviso por privado cuando {describe_alert(new)}.{now_text}",
                "/alertas para ver o borrar tus alertas",
            ),
            ephemeral=True,
        )


class DolarView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=BUTTONS_LAST_SECONDS)

    @discord.ui.button(label="Actualizar", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, _button: discord.ui.Button):
        try:
            await interaction.response.edit_message(embed=await dolar_card(), view=self)
        except DolarError as exc:
            await interaction.response.send_message(embed=cards.problem(str(exc)), ephemeral=True)

    @discord.ui.button(label="Gráfico del blue", emoji="📈", style=discord.ButtonStyle.primary)
    async def chart(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer()
        try:
            embed, file = await history_card("blue", 30)
        except DolarError as exc:
            return await interaction.followup.send(embed=cards.problem(str(exc)), ephemeral=True)
        await interaction.followup.send(embed=embed, file=file, view=HistoryView("blue", 30))

    @discord.ui.button(label="Crear alerta", emoji="🔔", style=discord.ButtonStyle.success)
    async def alert(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(AlertModal())

    @discord.ui.button(label="Cómo se movió", emoji="🧉", style=discord.ButtonStyle.secondary)
    async def moved(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer()
        try:
            embed = await summary_card(1)
        except DolarError as exc:
            return await interaction.followup.send(embed=cards.problem(str(exc)), ephemeral=True)
        await interaction.followup.send(embed=embed, view=SummaryView(1))


class HistoryView(discord.ui.View):
    """Buttons to switch period and a menu to switch rate, editing the same message."""

    def __init__(self, rate: str, days: int):
        super().__init__(timeout=BUTTONS_LAST_SECONDS)
        self.rate, self.days = rate, days
        for d, label in ((7, "7 días"), (30, "30 días"), (90, "90 días"), (365, "1 año")):
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if d == days else discord.ButtonStyle.secondary,
                disabled=d == days,
                row=0,
            )
            button.callback = self._switch(rate, d)
            self.add_item(button)
        menu = discord.ui.Select(
            placeholder=f"Cambiar de dólar (ahora: {SHORT_NAMES[rate]})",
            options=[
                discord.SelectOption(label=SHORT_NAMES[k], value=k, default=k == rate) for k in HISTORY_RATES
            ],
            row=1,
        )

        async def pick(interaction: discord.Interaction):
            await self._show(interaction, menu.values[0], self.days)

        menu.callback = pick
        self.add_item(menu)

    def _switch(self, rate: str, days: int):
        async def callback(interaction: discord.Interaction):
            await self._show(interaction, rate, days)

        return callback

    async def _show(self, interaction: discord.Interaction, rate: str, days: int):
        await interaction.response.defer()
        try:
            embed, file = await history_card(rate, days)
        except DolarError as exc:
            return await interaction.followup.send(embed=cards.problem(str(exc)), ephemeral=True)
        await interaction.edit_original_response(
            embed=embed, attachments=[file], view=HistoryView(rate, days)
        )


class SummaryView(discord.ui.View):
    def __init__(self, period: int):
        super().__init__(timeout=BUTTONS_LAST_SECONDS)
        for p, label in ((1, "Hoy"), (7, "7 días"), (30, "30 días")):
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if p == period else discord.ButtonStyle.secondary,
                disabled=p == period,
            )
            button.callback = self._switch(p)
            self.add_item(button)

    def _switch(self, period: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                embed = await summary_card(period)
            except DolarError as exc:
                return await interaction.followup.send(embed=cards.problem(str(exc)), ephemeral=True)
            await interaction.edit_original_response(embed=embed, view=SummaryView(period))

        return callback


# ---------------------------------------------------------------- commands


async def fail(interaction: discord.Interaction, exc: Exception) -> None:
    await interaction.followup.send(embed=cards.problem(str(exc)), ephemeral=True)


@tree.command(
    name="dolar", description="Cómo está el dólar ahora: compra, venta, cuánto se movió y a qué hora"
)
async def dolar(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        embed = await dolar_card()
    except DolarError as exc:
        return await fail(interaction, exc)
    await interaction.followup.send(embed=embed, view=DolarView())


@tree.command(
    name="historial", description="Gráfico de un dólar en los últimos días, con mínimo, máximo y promedio"
)
@app_commands.describe(
    tipo="Qué dólar (si no elegís, el blue)", dias="Cuántos días para atrás (si no elegís, 30)"
)
@app_commands.choices(tipo=RATE_CHOICES, dias=DAY_CHOICES)
async def historial(
    interaction: discord.Interaction,
    tipo: app_commands.Choice[str] | None = None,
    dias: app_commands.Choice[int] | None = None,
):
    await interaction.response.defer()
    rate, days = (tipo.value if tipo else "blue"), (dias.value if dias else 30)
    try:
        embed, file = await history_card(rate, days)
    except DolarError as exc:
        return await fail(interaction, exc)
    await interaction.followup.send(embed=embed, file=file, view=HistoryView(rate, days))


@tree.command(name="resumen", description="Cómo se movió cada dólar: hoy, en la semana o en el mes")
@app_commands.describe(periodo="Qué período comparar (si no elegís, hoy contra el día anterior)")
@app_commands.choices(periodo=PERIOD_CHOICES)
async def resumen(interaction: discord.Interaction, periodo: app_commands.Choice[int] | None = None):
    await interaction.response.defer()
    period = periodo.value if periodo else 1
    try:
        embed = await summary_card(period)
    except DolarError as exc:
        return await fail(interaction, exc)
    await interaction.followup.send(embed=embed, view=SummaryView(period))


@tree.command(name="convertir", description="Pasá dólares a pesos o pesos a dólares")
@app_commands.describe(
    monto="Cuánto querés convertir",
    moneda="Qué tenés y qué querés",
    tipo="Con qué dólar (si no elegís, el blue)",
)
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
        return await fail(interaction, exc)
    await interaction.followup.send(
        embed=cards.simple("💱 Conversión", text, "/convertir tipo:MEP para usar otro dólar")
    )


@tree.command(
    name="compra", description="Cuánto te sale en pesos algo que cuesta dólares, pagando con tarjeta"
)
@app_commands.describe(dolares="Precio en dólares, por ejemplo 20 para una suscripción")
async def compra(interaction: discord.Interaction, dolares: float):
    await interaction.response.defer()
    try:
        text = card_purchase(dolares, await asyncio.to_thread(rates.dollars), now())
    except DolarError as exc:
        return await fail(interaction, exc)
    await interaction.followup.send(
        embed=cards.simple("💳 Compra con tarjeta", text, "/convertir si querés el cambio a otro dólar")
    )


@tree.command(name="monedas", description="Euro, real, peso chileno y peso uruguayo, en pesos")
async def monedas(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        embed = cards.currencies(await asyncio.to_thread(rates.currencies), now())
    except DolarError as exc:
        return await fail(interaction, exc)
    await interaction.followup.send(embed=embed)


@tree.command(name="alerta", description="Te aviso por privado cuando un dólar llegue a un valor")
@app_commands.describe(
    tipo="Qué dólar", cuando="Si querés que te avise cuando sube o cuando baja", valor="El valor en pesos"
)
@app_commands.choices(
    tipo=RATE_CHOICES,
    cuando=[
        app_commands.Choice(name="Cuando suba a ese valor", value="up"),
        app_commands.Choice(name="Cuando baje a ese valor", value="down"),
    ],
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
        return await interaction.response.send_message(embed=cards.problem(str(exc)), ephemeral=True)
    await interaction.response.send_message(
        embed=cards.simple(
            "🔔 Alerta creada",
            f"Te aviso por privado cuando {describe_alert(new)}. Fijate de tener los mensajes privados abiertos.",
            "/alertas para ver o borrar tus alertas",
        ),
        ephemeral=True,
    )


@tree.command(name="alertas", description="Tus alertas activas")
async def alertas(interaction: discord.Interaction):
    mine = [a for a in storage.load(ALERTS_FILE) if a.user_id == interaction.user.id]
    text = "\n".join(f"**{i}.** Cuando {describe_alert(a)}" for i, a in enumerate(mine, 1))
    await interaction.response.send_message(
        embed=cards.simple(
            "🔔 Tus alertas",
            text or "No tenés alertas todavía.",
            "/borrar-alerta numero:1 borra la primera · /alerta crea otra",
        ),
        ephemeral=True,
    )


@tree.command(name="borrar-alerta", description="Borrá una de tus alertas por su número (lo ves en /alertas)")
@app_commands.describe(numero="El número que aparece en /alertas")
async def borrar_alerta(interaction: discord.Interaction, numero: int):
    try:
        storage.save(ALERTS_FILE, storage.remove(storage.load(ALERTS_FILE), interaction.user.id, numero))
    except ValueError as exc:
        return await interaction.response.send_message(embed=cards.problem(str(exc)), ephemeral=True)
    await interaction.response.send_message(
        embed=cards.simple("🗑️ Alerta borrada", "Listo, la borré.", "/alertas para ver las que quedan"),
        ephemeral=True,
    )


@tree.command(name="ayuda", description="Qué sabe hacer DOLAR CHE")
async def ayuda(interaction: discord.Interaction):
    text = (
        "**/dolar** cómo está el dólar ahora, con botones para el gráfico y las alertas\n"
        "**/historial** gráfico de 7 días a un año (`tipo` y `dias` son opcionales)\n"
        "**/resumen** cómo se movió cada dólar hoy, en la semana o en el mes\n"
        "**/convertir** dólares a pesos o al revés\n"
        "**/compra** cuánto sale algo en dólares con tarjeta\n"
        "**/monedas** euro, real y pesos chileno y uruguayo\n"
        "**/alerta** te aviso cuando llegue a tu número · **/alertas** las tuyas\n"
        "**/resumen-aca** el resumen de las 18 h sale en este canal (admins)\n\n"
        "Los datos son de referencia, no son un consejo financiero."
    )
    await interaction.response.send_message(
        embed=cards.simple("🇦🇷 DOLAR CHE", text, "empezá por /dolar"), view=DolarView(), ephemeral=True
    )


@tree.command(name="resumen-aca", description="El resumen diario de las 18 h sale en este canal")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def resumen_aca(interaction: discord.Interaction):
    settings.set_summary_channel(HOME, interaction.channel_id)
    await interaction.response.send_message(
        embed=cards.simple(
            "🧉 Resumen diario activado",
            "Los días hábiles a las 18 h te dejo acá cómo cerró el dólar.",
            "/resumen-apagar lo desactiva",
        ),
        ephemeral=True,
    )


@tree.command(name="resumen-apagar", description="Deja de publicar el resumen diario")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def resumen_apagar(interaction: discord.Interaction):
    settings.set_summary_channel(HOME, None)
    await interaction.response.send_message(
        embed=cards.simple(
            "Resumen diario apagado", "Listo, no lo publico más.", "/resumen-aca lo vuelve a activar"
        ),
        ephemeral=True,
    )


# ---------------------------------------------------------------- background jobs


@tasks.loop(minutes=10)
async def every_ten_minutes():
    try:
        quotes = await asyncio.to_thread(rates.dollars)
    except DolarError:
        return  # try again in 10 minutes
    if "blue" in quotes:
        # The bot's status shows the blue to everyone, and where to start.
        activity = discord.Activity(
            type=discord.ActivityType.watching, name=f"Blue {money(quotes['blue'].sell, 0)} · /ayuda"
        )
        await client.change_presence(activity=activity)
    alerts = storage.load(ALERTS_FILE)
    remaining = []
    for a in alerts:
        if not alert_fires(a, quotes):
            remaining.append(a)
            continue
        try:
            user = await client.fetch_user(a.user_id)
            await user.send(
                embed=cards.simple(
                    "🔔 ¡Che, llegó!",
                    f"{describe_alert(a).capitalize()}: ahora está en **{money(quotes[a.rate].sell)}**.",
                    "/alerta para crear otra",
                )
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
        histories = await asyncio.to_thread(rates.histories, SUMMARY_RATES)
        format_daily_summary(histories, today())  # raises on weekends or when there is no close today
        await channel.send(embed=cards.summary(1, period_moves(histories, 1, today())), view=SummaryView(1))
    except DolarError:
        return  # never post an old close as today's


@client.event
async def on_ready():
    await tree.sync()
    for loop in (every_ten_minutes, daily_summary):
        if not loop.is_running():
            loop.start()
    print(f"DOLAR CHE ready as {client.user}", flush=True)


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
