import random
import logging
import subprocess
import sys
import os
import re
import time
import concurrent.futures
import discord
from discord.ext import commands, tasks
import docker
import asyncio
from discord import app_commands

TOKEN = ''  # Add your bot token here
RAM_LIMIT = '128g'
SERVER_LIMIT = 12
database_file = 'database.txt'

intents = discord.Intents.default()
intents.messages = False
intents.message_content = False

bot = commands.Bot(command_prefix='/', intents=intents)
client = docker.from_env()

# Generate random port
def generate_random_port():
    return random.randint(1025, 65535)

# Add entry to database
def add_to_database(user, container_name, ssh_command):
    with open(database_file, 'a') as f:
        f.write(f"{user}|{container_name}|{ssh_command}\n")

# Remove entry from database
def remove_from_database(ssh_command):
    if not os.path.exists(database_file):
        return
    with open(database_file, 'r') as f:
        lines = f.readlines()
    with open(database_file, 'w') as f:
        for line in lines:
            if ssh_command not in line:
                f.write(line)

# Capture output line containing 'ssh session'
async def capture_ssh_session_line(process):
    while True:
        output = await process.stdout.readline()
        if not output:
            break
        output = output.decode('utf-8').strip()
        if "ssh session:" in output:
            return output.split("ssh session:")[1].strip()
    return None

# Get SSH command from database by container id
def get_ssh_command_from_database(container_id):
    if not os.path.exists(database_file):
        return None
    with open(database_file, 'r') as f:
        for line in f:
            if container_id in line:
                return line.split('|')[2]
    return None

# Get all servers for a user
def get_user_servers(user):
    if not os.path.exists(database_file):
        return []
    servers = []
    with open(database_file, 'r') as f:
        for line in f:
            if line.startswith(user):
                servers.append(line.strip())
    return servers

# Count servers for a user
def count_user_servers(user):
    return len(get_user_servers(user))

# Get container ID from database by user
def get_container_id_from_database(user, container_name):
    if not os.path.exists(database_file):
        return None
    with open(database_file, 'r') as f:
        for line in f:
            if line.startswith(user) and container_name in line:
                return line.split('|')[1]
    return None

@bot.event
async def on_ready():
    change_status.start()
    print(f'Bot is ready. Logged in as {bot.user}')
    await bot.tree.sync()

@tasks.loop(seconds=5)
async def change_status():
    try:
        if os.path.exists(database_file):
            with open(database_file, 'r') as f:
                lines = f.readlines()
                instance_count = len(lines)
        else:
            instance_count = 0
        status = f"with {instance_count} Cloud Instances"
        await bot.change_presence(activity=discord.Game(name=status))
    except Exception as e:
        print(f"Failed to update status: {e}")

async def capture_output(process, keyword):
    while True:
        output = await process.stdout.readline()
        if not output:
            break
        output = output.decode('utf-8').strip()
        if keyword in output:
            return output
    return None

# Regenerate SSH session
async def regen_ssh_command(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)
    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="No active instance found for your user.", color=0xff0000))
        return
    try:
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error executing tmate: {e}", color=0xff0000))
        return
    ssh_session_line = await capture_ssh_session_line(exec_cmd)
    if ssh_session_line:
        await interaction.user.send(embed=discord.Embed(description=f"### New SSH Session Command:\n```{ssh_session_line}```", color=0x00ff00))
        await interaction.response.send_message(embed=discord.Embed(description="New SSH session generated. Check your DMs.", color=0x00ff00))
    else:
        await interaction.response.send_message(embed=discord.Embed(description="Failed to generate new SSH session.", color=0xff0000))

# Start server
async def start_server(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)
    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="No instance found for your user.", color=0xff0000))
        return
    try:
        subprocess.run(["docker", "start", container_id], check=True)
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        ssh_session_line = await capture_ssh_session_line(exec_cmd)
        if ssh_session_line:
            await interaction.user.send(embed=discord.Embed(description=f"### Instance Started\nSSH Session Command:\n```{ssh_session_line}```", color=0x00ff00))
            await interaction.response.send_message(embed=discord.Embed(description="Instance started successfully. Check your DMs.", color=0x00ff00))
        else:
            await interaction.response.send_message(embed=discord.Embed(description="Instance started, but failed to get SSH session.", color=0xff0000))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error starting instance: {e}", color=0xff0000))

# Stop server
async def stop_server(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)
    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="No instance found for your user.", color=0xff0000))
        return
    try:
        subprocess.run(["docker", "stop", container_id], check=True)
        await interaction.response.send_message(embed=discord.Embed(description="Instance stopped successfully.", color=0x00ff00))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error stopping instance: {e}", color=0xff0000))

# Restart server
async def restart_server(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)
    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="No instance found for your user.", color=0xff0000))
        return
    try:
        subprocess.run(["docker", "restart", container_id], check=True)
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F",
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        ssh_session_line = await capture_ssh_session_line(exec_cmd)
        if ssh_session_line:
            await interaction.user.send(embed=discord.Embed(description=f"### Instance Restarted\nSSH Session Command:\n```{ssh_session_line}```", color=0x00ff00))
            await interaction.response.send_message(embed=discord.Embed(description="Instance restarted successfully. Check your DMs.", color=0x00ff00))
        else:
            await interaction.response.send_message(embed=discord.Embed(description="Instance restarted but failed to get SSH session.", color=0xff0000))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(description=f"Error restarting instance: {e}", color=0xff0000))

# Neofetch command to show fake info
@bot.tree.command(name="neofetch", description="Show fake system info")
@app_commands.describe(container_name="Your container name")
async def neofetch(interaction: discord.Interaction, container_name: str):
    user = str(interaction.user)
    container_id = get_container_id_from_database(user, container_name)
    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(description="No instance found for your user.", color=0xff0000))
        return

    # Run the fake-neofetch script inside the container
    process = await asyncio.create_subprocess_exec(
        "docker", "exec", container_id, "bash", "/fake-neofetch.sh",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if stdout:
        embed = discord.Embed(title="System Info", description=f"```\n{stdout.decode()}\n```", color=0x00ff00)
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(title="Error", description="Failed to retrieve system info.", color=0xff0000)
        await interaction.response.send_message(embed=embed)

# Create Ubuntu server with fake-neofetch script
async def create_server_task(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(description="Creating Instance, this may take a few seconds.", color=0x00ff00))
    user = str(interaction.user)
    if count_user_servers(user) >= SERVER_LIMIT:
        await interaction.followup.send(embed=discord.Embed(description="```Error: Instance limit reached```", color=0xff0000))
        return

    image = "ubuntu-22.04-with-tmate"
    try:
        container_id = subprocess.check_output([
            "docker", "run", "-itd", "--privileged", "--cap-add=ALL", image
        ]).strip().decode('utf-8')
    except subprocess.CalledProcessError as e:
        await interaction.followup.send(embed=discord.Embed(description=f"Error creating container: {e}", color=0xff0000))
        return

    # Add fake-neofetch script inside the container
    subprocess.run([
        "docker", "exec", container_id, "bash", "-c",
        "echo '#!/bin/bash\n" +
        "echo \"OS: Ubuntu 22.04\"\n" +
        "echo \"Host: Docker Container\"\n" +
        "echo \"Kernel: 5.15.0\"\n" +
        "echo \"Uptime: 1 day, 3 hours\"\n" +
        "echo \"Packages: 1023 (dpkg)\"\n" +
        "echo \"Shell: bash 5.1\"\n" +
        "echo \"Resolution: 1920x1080\"\n" +
        "echo \"DE: XFCE\"\n" +
        "echo \"WM: Xfwm4\"\n" +
        "echo \"WM Theme: Arc
