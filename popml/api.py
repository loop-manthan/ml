from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types
import requests
import base64
import json
import os
import re

app = FastAPI()

client = genai.Client(api_key=GEMINI_API_KEY)

def get_fatsecret_token():
    auth_url = "https://oauth.fatsecret.com/connect/token"
    auth_header = base64.b64encode(f"{FATSECRET_CLIENT_ID}:{FATSECRET_CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "client_credentials", "scope": "basic"}
    return requests.post(auth_url, headers=headers, data=data).json().get("access_token")

def parse_macros(description, weight_g):
    def extract(pattern):
        match = re.search(pattern, description)
        return float(match.group(1)) if match else 0

    cals_100 = extract(r'Calories: (\d+)kcal')
    fat_100 = extract(r'Fat: ([\d.]+)g')
    carbs_100 = extract(r'Carbs: ([\d.]+)g')
    protein_100 = extract(r'Protein: ([\d.]+)g')

    factor = weight_g / 100

    return {
        "calories": round(cals_100 * factor, 2),
        "fat": round(fat_100 * factor, 2),
        "carbs": round(carbs_100 * factor, 2),
        "protein": round(protein_100 * factor, 2)
    }

@app.post("/analyze")
async def analyze_food(file: UploadFile = File(...)):
    image_bytes = await file.read()

    prompt = """
    Identify the food. Estimate weight in grams. Give exact values.
    Use generic names (e.g. 'Apple' not 'Gala Apple').
    Return ONLY JSON: {"food": "name", "weight": 000}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=file.content_type)
        ]
    )

    ai_data = json.loads(response.text.strip().replace('```json', '').replace('```', ''))
    food_name = ai_data['food']
    weight_g = ai_data['weight']

    token = get_fatsecret_token()
    headers = {"Authorization": f"Bearer {token}"}

    params = {
        "method": "foods.search",
        "search_expression": food_name,
        "format": "json",
        "max_results": 5
    }

    res = requests.post(
        "https://platform.fatsecret.com/rest/server.api",
        headers=headers,
        params=params
    ).json()

    if "foods" in res and "food" in res["foods"]:
        food_data = res["foods"]["food"]
        match = food_data[0] if isinstance(food_data, list) else food_data

        desc = match.get("food_description", "")
        macros = parse_macros(desc, weight_g)

        return JSONResponse({
            "prediction": food_name,
            "weight_g": weight_g,
            "matched_name": match["food_name"],
            "macros": macros
        })

    return JSONResponse({
        "error": "FatSecret search failed",
        "prediction": food_name,
        "debug": res
    }, status_code=400)