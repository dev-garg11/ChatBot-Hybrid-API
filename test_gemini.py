from google import genai

client = genai.Client(api_key="AIzaSyC8GcwCZPWWxHmyV1ENyXlsmBxkYkh0k9g")

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Hello"
)

print(response.text)