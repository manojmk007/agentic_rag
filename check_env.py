from dotenv import load_dotenv
import os

load_dotenv()

key = os.getenv("GEMINI_API_KEY")

if key:
    print("API KEY FOUND")
    print("Length:", len(key))
else:
    print("API KEY NOT FOUND")