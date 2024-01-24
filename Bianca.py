import discord
from discord.ext import commands
import youtube_dl
import asyncio
import random
from collections import deque
from discord.ext import commands


queues = {}

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True 
bot = commands.Bot(command_prefix='!', intents=intents)

youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

@bot.command()
async def join(ctx):
    if ctx.author.voice is None:
        await ctx.send("You are not in a voice channel.")
        return
    channel = ctx.author.voice.channel
    if ctx.voice_client is not None:
        return await ctx.voice_client.move_to(channel)
    await channel.connect()

@bot.command()
async def play(ctx, url):
    if ctx.author.voice is None:
        await ctx.send("You are not in a voice channel.")
        return

    if ctx.voice_client is None:
        channel = ctx.author.voice.channel
        await channel.connect()
    elif ctx.voice_client.channel != ctx.author.voice.channel:
        await ctx.voice_client.move_to(ctx.author.voice.channel)

    try:
        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=bot.loop)
            ctx.voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)

        await ctx.send(f'Now playing: {player.title}')
    except youtube_dl.DownloadError as e:
        await ctx.send(f'An error occurred while downloading the video: {e}')

@bot.command()
async def fairloot(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Step 1: Ask how many people are rolling
        await ctx.send("How many people are rolling?")
        msg = await bot.wait_for('message', check=check, timeout=30.0)  # 30 seconds to reply
        num_people = int(msg.content)

        # Step 2: Collect the names of the people rolling
        await ctx.send("Please enter the names of the people rolling, separated by a comma.")
        msg = await bot.wait_for('message', check=check, timeout=60.0)  # 60 seconds to reply
        names = [name.strip() for name in msg.content.split(',')]

        if len(names) != num_people:
            await ctx.send(f"Number of names provided ({len(names)}) does not match the number of people rolling ({num_people}).")
            return

        # Step 3: Generate roll numbers and sort
        rolls = {name: random.randint(1, 100) for name in names}
        sorted_rolls = sorted(rolls.items(), key=lambda x: x[1], reverse=True)

        # Step 4: Output the results
        result = "\n".join([f"{name} rolled {roll}" for name, roll in sorted_rolls])
        await ctx.send(f"Roll results:\n{result}")

    except ValueError:
        await ctx.send("Please enter a valid number.")
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond.")

@bot.command()
async def roll(ctx, max_roll: int = 100):
    # Ensure the maximum roll value is positive
    if max_roll < 1:
        await ctx.send("Please provide a positive integer for the roll.")
        return

    # Generate and send the random roll result
    roll_result = random.randint(0, max_roll)
    await ctx.send(f"You rolled a {roll_result} (0-{max_roll}).")

@bot.command(name="content", description="Choose a game and get a random content")
async def content(ctx):
    # Create a select menu
    select = discord.ui.Select(
        options=[
            discord.SelectOption(label="Maple", value="maple"),
            discord.SelectOption(label="Overwatch", value="overwatch"),
            discord.SelectOption(label="Anything", value="anything")
        ]
    )

    async def select_callback(interaction: discord.Interaction):
        content_options = {
            "maple": ["dailies", "czak", "4 man ncht", "5-6 man ncht", "18 man ncht", "cwk", "magnus", "FL emp", "pink bean"],
            "overwatch": ["tank", "support", "dps"],
            "anything": ["dailies", "czak", "4 man ncht", "5-6 man ncht", "18 man ncht", "cwk", "Magnus", "FL emp", "Pink Bean", "OW tank", "OW support", "OW DPS", "PlateUp"]
        }

        selected_value = interaction.data['values'][0]  # Get the selected value from the interaction
        choice = random.choice(content_options[selected_value])
        await interaction.response.send_message(f"Random {selected_value} content: {choice}")

    select.callback = select_callback

    # Create a view to hold the select menu
    view = discord.ui.View()
    view.add_item(select)

    await ctx.send("Choose your game:", view=view)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


# Replace 'YOUR_BOT_TOKEN' with your bot's token
bot.run('MTE5OTA5NTE1MTU2MjMzODM2NQ.GgDswI.fB52I8BLrUmgnua4BBil9CPeFsnZHVWfa5w0fY')
