import discord
import re
from discord.ext import commands
import youtube_dl
import asyncio
import random
from collections import deque
import humanize
import aiosqlite
import os
import glob
from datetime import datetime, timedelta
import pytz

DB_PATH = 'database.db'

os.makedirs('songs', exist_ok=True)
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True 
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': 'songs/%(extractor)s-%(id)s-%(title)s.%(ext)s',
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
async def play(ctx, url):
    guild_id = str(ctx.guild.id)

    if ctx.author.voice is None:
        await ctx.send("You are not in a voice channel.")
        return

    if ctx.voice_client is None:
        channel = ctx.author.voice.channel
        await channel.connect()
    elif ctx.voice_client.channel != ctx.author.voice.channel:
        await ctx.voice_client.move_to(ctx.author.voice.channel)

    async with ctx.typing():
        player = await YTDLSource.from_url(url, loop=bot.loop)
        song_title = player.title

    async with aiosqlite.connect(DB_PATH) as db:
        if ctx.voice_client.is_playing():
            # Add song to playlist
            await db.execute('INSERT INTO playlist (guild_id, url, title) VALUES (?, ?, ?)', (guild_id, url, song_title))
            await db.commit()
            await ctx.send(f'Added to playlist: {song_title}')
        else:
            # Play the song immediately
            ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(ctx), bot.loop))
            await ctx.send(f'Now playing: {song_title}')


async def play_next_song(ctx):
    guild_id = str(ctx.guild.id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT url FROM playlist WHERE guild_id = ? ORDER BY id LIMIT 1', (guild_id,))
        next_song = await cursor.fetchone()
        if next_song:
            url = next_song[0]
            player = await YTDLSource.from_url(url, loop=bot.loop)
            ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(ctx), bot.loop))
            await db.execute('DELETE FROM playlist WHERE guild_id = ? AND url = ?', (guild_id, url))
            await db.commit()
            await ctx.send(f'Now playing: {player.title}')

@bot.command()
async def clear(ctx):
    guild_id = str(ctx.guild.id)  # Get the guild ID
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM playlist WHERE guild_id = ?', (guild_id,))
        await db.commit()
        await ctx.send('Playlist cleared.')
@bot.command()
async def next(ctx):
    guild_id = str(ctx.guild.id)  # Get the guild ID

    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        await ctx.send("I'm not connected to a voice channel.")
        return

    # Stop the current song if any
    ctx.voice_client.stop()

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT url FROM playlist WHERE guild_id = ? ORDER BY id LIMIT 1', (guild_id,))
        song = await cursor.fetchone()

        if song:
            url = song[0]
            player = await YTDLSource.from_url(url, loop=bot.loop)
            ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next_song(ctx), bot.loop))
            await db.execute('DELETE FROM playlist WHERE guild_id = ? AND url = ?', (guild_id, url))
            await db.commit()
            await ctx.send(f'Now playing: {player.title}')
        else:
            await ctx.send('No more songs in the playlist.')

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id == bot.user.id and after.channel is None:
        # Bot has been disconnected from the channel
        guild_id = str(before.channel.guild.id)  # Get the guild ID
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM playlist WHERE guild_id = ?', (guild_id,))
            await db.commit()

        # Updated path to the directory where songs are downloaded
        download_path = 'songs'  # or './songs' if in the same directory as your script

        if os.path.exists(download_path):
            # Remove downloaded files
            for file in glob.glob(os.path.join(download_path, '*')):
                try:
                    os.remove(file)
                    print(f"Deleted file: {file}")  # Logging which file is deleted
                except Exception as e:
                    print(f"Error deleting file {file}: {e}")  # Logging any error
        else:
            print(f"Directory not found: {download_path}")




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
            discord.SelectOption(label="Dream", value="DreamMS"),
            discord.SelectOption(label="Reboot", value="Reboot"),
            discord.SelectOption(label="IRL", value="IRL"),
            # You can add more options here if needed
        ]
    )

    async def select_callback(interaction: discord.Interaction):
        content_options = {
            "DreamMS": [":book: Read forum ban appeals:book: ", " :write: Time to CZAK!!:smiling_imp: ", " <:pandarob:> EMPRESS, you seem like you need belt scrolls :pandarob: ", ":Vina:  CHAOS SCROLL IT", ":pandagrim:  mag mag mag mag :pandagrim: ", ":pandacool:   18 man ncht it. **coins for days**", ":writef3:  Did you do **dailies** yet?", ":pandaree:  Have you tried Farming?", "PB it ... time for ROTS :takemymoney: ", " :pandaelf:  Reroll for the 22nd time D'oh", " :money_with_wings: Swipe for boxes $$, help dreaM get his lambo :money_with_wings: ", "Chu Chu, it's the CWK TRAIN :railway_track: ", "CousinMS it. :wechat:  "],
            "Reboot": [":x: Quit reboot and play DreamMS :x: "],    
            "reboot": ["dailies", "monster park", "legion", "farm", "Cube for that triple prime ", "Suffer in vhilla", "Coconut", "Quit and play Dream"],
            "overwatch": ["Play as TANK", "Play as Support", "Play as DPS", "Play as Mercy", "Play as Moira", "Play as Reaper", "Play as Reinhardt"],
            "IRL": [":money_with_wings:  Treat yourself with a nice gift :money_with_wings: ", "Pet your dog🐶", ":saluting_face:  Time to GYM (or some kind of sport :golf: )", "Get some Boba :bubble_tea: ", "Go watch that movie you've been thinking about :film_frames: ", "Drink water :baby_bottle:  ", ":pizza:  Eat Pizza :pizza: ", "Eat haidilao YUM YUM", "YOGAAA", "Buy feet pics", ":warning:  call parents and get scolded for not being perfect child :warning: ", "Tell John a joke :joy: "],
            "Anything": ["dailies", "czak", "4 man ncht", "5-6 man ncht", "18 man ncht", "cwk", "Magnus", "FL emp", "Pink Bean", "OW tank", "OW support", "OW DPS", "PlateUp"]
        }

        selected_value = interaction.data['values'][0]  # Get the selected value from the interaction
        choice = random.choice(content_options[selected_value])
        # Personalized greeting with the user's name
        await interaction.response.send_message(f"Hello **{interaction.user.display_name}**! \nYour {selected_value} RNG is: {choice}")

    select.callback = select_callback


    # Create a view to hold the select menu
    view = discord.ui.View()
    view.add_item(select)

    await ctx.send("Choose your game:", view=view)

async def setup_database():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS events (
                            id INTEGER PRIMARY KEY,
                            name TEXT,
                            timestamp INTEGER,
                            members TEXT,
                            channel_id INTEGER,
                            creator_id INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS reminders (
                            id INTEGER PRIMARY KEY,
                            event_id INTEGER,
                            reminder_time INTEGER,
                            sent INTEGER,
                            FOREIGN KEY(event_id) REFERENCES events(id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS playlist (
                            id INTEGER PRIMARY KEY,
                            guild_id TEXT,
                            url TEXT,
                            title TEXT)''')
        await db.commit()


async def add_event(name, timestamp, member_ids, channel_id, creator_id):
    member_str = ','.join(map(str, member_ids))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO events (name, timestamp, members, channel_id, creator_id) VALUES (?, ?, ?, ?, ?)', 
                         (name, timestamp, member_str, channel_id, creator_id))
        event_id_cursor = await db.execute('SELECT last_insert_rowid()')
        event_id = (await event_id_cursor.fetchone())[0]

        # Schedule reminders - only 1 day and 60 minutes before the event
        for delta in [timedelta(days=1), timedelta(minutes=60)]:
            reminder_time = datetime.fromtimestamp(timestamp, tz=pytz.utc) - delta
            await db.execute('INSERT INTO reminders (event_id, reminder_time, sent) VALUES (?, ?, ?)', 
                             (event_id, int(reminder_time.timestamp()), 0))

        await db.commit()



async def check_reminders():
    while True:
        async with aiosqlite.connect(DB_PATH) as db:
            current_time = datetime.now(pytz.utc).timestamp()
            cursor = await db.execute('SELECT * FROM reminders WHERE reminder_time <= ? AND sent = 0', (current_time,))
            reminders = await cursor.fetchall()
            for reminder in reminders:
                event_id = reminder[1]
                cursor = await db.execute('SELECT name, members, channel_id, timestamp FROM events WHERE id = ?', (event_id,))
                event = await cursor.fetchone()
                if event:
                    event_name, member_ids, channel_id, timestamp = event  # Fetch the timestamp here
                    member_mentions = ' '.join([f'<@{member_id}>' for member_id in member_ids.split(',')])
                    reminder_message = f"Reminder: **{event_name}**  <t:{timestamp}:R>. {member_mentions}"
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(reminder_message)
                    await db.execute('UPDATE reminders SET sent = 1 WHERE id = ?', (reminder[0],))
            await db.commit()
        await asyncio.sleep(60)  # Check every minute



@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    bot.loop.create_task(check_reminders())


@bot.command(name='host')
async def host(ctx, raid_type: str = None, unix_timestamp: str = None, *, members: str = None):
    if raid_type is None or unix_timestamp is None or members is None:
        # Display the select options
        select = discord.ui.Select(
            options=[
                discord.SelectOption(label="Magnus", value="magnus"),
                discord.SelectOption(label="Empress", value="empress"),
                discord.SelectOption(label="PinkBean", value="pink_bean")
            ]
        )

        async def select_callback(interaction: discord.Interaction):
            raid_type_value = interaction.data['values'][0]
            raid_type_readable = raid_type_value.replace('_', ' ').title()
            await interaction.response.send_message(
                f"Selected raid: {raid_type_readable}. Please enter the UNIX timestamp for the event.", 
                ephemeral=True
            )

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                msg = await bot.wait_for('message', check=check, timeout=120.0)
                event_unix_timestamp = int(msg.content)

                members = ctx.channel.members
                member_options = [discord.SelectOption(label=member.display_name, value=str(member.id)) for member in members if not member.bot]

                if not member_options:
                    await ctx.send("No members available for alerts.")
                    return

                member_select = discord.ui.Select(
                    options=member_options,
                    placeholder="Select members to notify",
                    min_values=1,
                    max_values=len(member_options)
                )

                async def member_select_callback(interaction: discord.Interaction):
                    selected_member_ids = interaction.data['values']
                    selected_members = [member for member in members if str(member.id) in selected_member_ids]

                    await add_event(raid_type_readable, event_unix_timestamp, [member.id for member in selected_members], ctx.channel.id, ctx.author.id)

                    member_mentions = ''.join([f"<@{member.id}>" for member in selected_members])
                    formatted_message = (
                        f"**{raid_type_readable}**: <t:{event_unix_timestamp}:F>"
                        f"\n{member_mentions}"
                        #"Reminders will be sent 1 day, 1 hour and 15 minutes before the timestamp."
                    )
                    await interaction.response.send_message(formatted_message)

                member_select.callback = member_select_callback
                view = discord.ui.View()
                view.add_item(member_select)
                await interaction.followup.send("Select members that will get reminders:", view=view, ephemeral=True)

            except ValueError:
                await ctx.send("Invalid UNIX timestamp. Please enter a valid number.")
            except asyncio.TimeoutError:
                await ctx.send("You took too long to respond.")

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await ctx.send("Which raid are you hosting?", view=view)

    else:
        # Process the command with parameters
        raid_type_readable = raid_type.replace('_', ' ').title()
        try:
            event_unix_timestamp = int(unix_timestamp)

            # Use a regular expression to find all user mentions in the string
            member_ids = [int(user_id) for user_id in re.findall(r'<@!?(\d+)>', members)]

            await add_event(raid_type_readable, event_unix_timestamp, member_ids, ctx.channel.id, ctx.author.id)

            member_mentions = ' '.join([f'<@{member_id}>' for member_id in member_ids])
            formatted_message = (
                f"**{raid_type_readable}**:  <t:{event_unix_timestamp}:F>"
                f"\n{member_mentions}"
                #"Reminders will be sent 1 day, 1 hour and 15 minutes before the timestamp."
            )
            await ctx.send(formatted_message)
        except ValueError:
            await ctx.send("Invalid input. Please use the format: !host <RaidType> <UnixTimestamp> <@Member1 @Member2 ...>")


@bot.command(name='hoststatus')
async def hoststatus(ctx):
    current_timestamp = int(datetime.now().timestamp())  # Get current timestamp
    async with aiosqlite.connect(DB_PATH) as db:
        # Select only future events
        cursor = await db.execute('SELECT id, name, timestamp FROM events WHERE creator_id = ? AND timestamp > ?', (ctx.author.id, current_timestamp))
        events = await cursor.fetchall()
        if events:
            response = "Your upcoming events:\n" + '\n'.join([f"ID: {event[0]}, Name: {event[1]}, Time: <t:{event[2]}:F>" for event in events])
        else:
            response = "You have no upcoming events."
        await ctx.send(response)


@bot.command(name='hostcancel')
async def hostcancel(ctx, identifier: str = None):
    if identifier is None:
        # User did not provide an identifier
        await ctx.send("Please use the following structure: !hostcancel \"Event Name or Event ID\"")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        if identifier.isdigit():
            # Treat the identifier as an Event ID
            event_id = int(identifier)
            cursor = await db.execute('SELECT creator_id FROM events WHERE id = ?', (event_id,))
            result = await cursor.fetchone()

            if result and result[0] == ctx.author.id:
                await db.execute('DELETE FROM events WHERE id = ?', (event_id,))
                await db.execute('DELETE FROM reminders WHERE event_id = ?', (event_id,))
                await db.commit()
                await ctx.send(f"Event with ID {event_id} deleted.")
            else:
                await ctx.send("No event found with that ID, or you do not have permission to delete it.")

        else:
            # Treat the identifier as an Event Name (case-insensitive)
            identifier_lower = identifier.lower()  # Convert identifier to lowercase
            cursor = await db.execute('SELECT id FROM events WHERE LOWER(name) = ? AND creator_id = ?', (identifier_lower, ctx.author.id))
            events = await cursor.fetchall()

            if not events:
                await ctx.send("No events found with that name, or you do not have permission to delete them.")
                return

            for event in events:
                event_id = event[0]
                await db.execute('DELETE FROM events WHERE id = ?', (event_id,))
                await db.execute('DELETE FROM reminders WHERE event_id = ?', (event_id,))

            await db.commit()
            await ctx.send(f"All events named '{identifier}' have been deleted.")



# Initialize the database
asyncio.run(setup_database())

# Don't forget to replace 'YOUR_BOT_TOKEN' with your actual bot token
bot.run('MTE5OTA5NTE1MTU2MjMzODM2NQ.GgDswI.fB52I8BLrUmgnua4BBil9CPeFsnZHVWfa5w0fY')