from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI = os.getenv("GEMINI_KEY")