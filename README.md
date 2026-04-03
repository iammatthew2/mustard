# Mustard

This is a WIP

ollama with Gemma 3 4B-it-QAT running on a Raspberry Pi 5, 8gb

Not a chat bot. This agent is the brain of a set of networked devices. It provides personality and interactivity.

Inputs and outputs are all handled over MQTT

Available inputs include:
- x,y coordinates of people (likely users) who are infront of the a camera in the same room (Meeps)
- distance sensor from skippy. Requires close proximity
- sound sensor from skippy. Boolean - sound heard or not
- button presses on Noodle


We have two LED matrix display available:
 - Eowyn: 64x32
 - Gimli: 32x16