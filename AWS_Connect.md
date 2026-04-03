To connect Amazon Connect to your Python server, you need to configure the connection inside the Amazon Connect AWS Console. There is no configuration needed in your code for "where is AWS," because your server is a passive listener (it waits for AWS to knock on its door).

Here is exactly how the event flows from AWS to your WebSocket:

1. Where do I put the details in AWS?
You don't put "AWS details" in your code; you put your server's URL into your Amazon Connect Contact Flow:

Open Amazon Connect: Go to your instance in the AWS Console.
Edit Contact Flow: Open the flow you want Maya to handle (e.g., your Main IVR).
Add "Start Media Streaming" Block:
Drag this block into your flow.
In the settings, you choose the Real-time Media Stream and point it to your server's endpoint: ws://<YOUR_EC2_PUBLIC_IP>:8001/connect
Set Audio Format: Ensure it’s set to 8kHz Mu-law (this matches the conversion logic I wrote in your amazon_connect_server.py).
2. How does Amazon Connect send events?
Once that "Start Media Streaming" block is reached in a call:

Establishing Link: Amazon Connect initiates a WebSocket connection to your EC2 server's IP.
Sending start: AWS immediately sends a JSON object over the socket:
json
{ "event": "start", "start": { "streamId": "..." } }
Your code receives this and says, "Okay, I'm ready, Maya!"
Continuous media: As long as the caller is speaking, AWS sends thousands of these messages every second:
json
{ "event": "media", "media": { "payload": "Base64EncodedAudio..." } }
Your code decodes this and feeds it to ElevenLabs for transcription.
Sending stop: When the call ends, AWS sends:
json
{ "event": "stop" }
Your code then closes the AI session to save your API costs.
Summary
The "Server" (your Python code) stays open and waits.
The "Client" (Amazon Connect) is the one that knows the IP of your server and sends the JSON events.
If you are hosting on an EC2 instance, make sure you open Port 8001 in your AWS Security Group so the Amazon Connect service can reach your WebSocket!