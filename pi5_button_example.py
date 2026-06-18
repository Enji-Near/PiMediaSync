from gpiozero import Button
from signal import pause

# Initialize Pin 10 (GPIO 15)
# pull_up=True ensures the line rests at HIGH. 
# A press pulls it to GND, triggering a FALLING edge.
# bounce_time=0.2 filters out mechanical vibrations for 200 milliseconds.

button = Button(15, pull_up=True, bounce_time=0.2)

# Counter to visually verify debounce success
press_count = 0

def on_falling_edge():
    global press_count
    press_count += 1
    print(f"FALLING Edge Detected! Total clean presses: {press_count}")

# Bind the falling edge event (button press) to the function
button.when_pressed = on_falling_edge

print("--- Raspberry Pi 5 Button Test ---")
print("Monitoring GPIO 15 (Pin 10) for FALLING edges...")
print("Press Ctrl+C to exit.\n")

try:
    pause()
except KeyboardInterrupt:
    print("\nTest terminated cleanly.")