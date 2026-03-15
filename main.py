import ollama
import json

# Your 'Digital Twin' State
current_state = {
    "left_light": "off",
    "right_light": "off",
    "top-lid-servo": "centered",
    "rotation": "centered"
}

def ask_brain(sensor_input):
    payload = {
        "state": current_state,
        "event": sensor_input
    }
    
    # We use ollama.chat to keep the service connection open
    response = ollama.chat(
        model='meep-brain',
        messages=[{'role': 'user', 'content': json.dumps(payload)}],
        # stream=False ensures we get the whole JSON back at once
        stream=False 
    )
    
    return response['message']['content']

# Test it without the CLI terminating
result = ask_brain({"face_detected": True, "position": "left"})
print(f"Brain Decision: {result}")